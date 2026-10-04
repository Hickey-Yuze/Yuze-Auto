#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Automa 本机 Python 桥接服务（Yuze fork 专用）
=============================================
- 纯标准库实现，零 pip 依赖；macOS / Windows 通用（python3 server.py 即可）
- 仅监听 127.0.0.1，token 鉴权（首次启动自动生成于 ~/.automa-bridge/token）
- 协议：
    GET  /health   → {"ok": true, "python": "3.x.x"}
    POST /execute  body: {token, timeoutMs, prelude, code, data:{variables, table}}
                   响应: {"ok": true, "result": "<yuze dump JSON>", "output": "<stdout>", "durationMs": n}
- 执行模型：快照式。prelude 为扩展内置的 yuze API 源码（单一真源随请求下发），
  先 exec prelude、再 _yuze_init 注入快照、然后 exec 用户代码、最后 _yuze_dump 回传。
"""

import contextlib
import hmac
import io
import itertools
import json
import os
import secrets
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HOST = "127.0.0.1"
PORT = int(os.environ.get("YUZE_BRIDGE_PORT", "27182"))
TOKEN_PATH = os.path.join(os.path.expanduser("~"), ".automa-bridge", "token")
MAX_BODY = 10 * 1024 * 1024  # 10MB，防呆

# ---------------------------------------------------------------------------
# AI 通道：指令队列 + 结果回传 + 工作流快照（线程安全）
# 扩展 background 每 2s POST /yuze/commands（上报工作流摘要 + 取走新指令）；
# AI 侧 POST /yuze/workflows、/yuze/execute 入队，GET /yuze/results 读结果。
# ---------------------------------------------------------------------------
_lock = threading.Lock()
_command_seq = itertools.count(1)
COMMANDS: list = []   # [{id, type, payload, at}]
RESULTS: list = []    # [{commandId, type, ok, result, error, at}]
WORKFLOWS_CACHE: list = []  # 扩展最近一次上报的工作流摘要


def enqueue_command(cmd_type, payload):
    cmd = {"id": next(_command_seq), "type": cmd_type, "payload": payload or {}, "at": time.time()}
    with _lock:
        COMMANDS.append(cmd)
        if len(COMMANDS) > 200:
            del COMMANDS[:-100]
    return cmd


def push_result(entry):
    entry.setdefault("at", time.time())
    with _lock:
        RESULTS.append(entry)
        if len(RESULTS) > 200:
            del RESULTS[:-100]


def load_or_create_token():
    """token 存于 ~/.automa-bridge/token，不存在则生成；可用 YUZE_BRIDGE_TOKEN 环境变量覆盖"""
    env_token = os.environ.get("YUZE_BRIDGE_TOKEN")
    if env_token:
        return env_token

    try:
        with open(TOKEN_PATH, "r", encoding="utf-8") as f:
            token = f.read().strip()
            if token:
                return token
    except OSError:
        pass

    token = secrets.token_hex(16)
    os.makedirs(os.path.dirname(TOKEN_PATH), exist_ok=True)
    with open(TOKEN_PATH, "w", encoding="utf-8") as f:
        f.write(token)

    try:
        os.chmod(TOKEN_PATH, 0o600)
    except OSError:
        pass

    print(f"[bridge] 已生成新 token：{TOKEN_PATH}")
    return token


TOKEN = load_or_create_token()


def execute_payload(payload):
    """执行一次请求：返回响应 dict（不含 ok 之外的协议字段处理）"""
    prelude = payload.get("prelude") or ""
    code = payload.get("code") or ""
    data = payload.get("data") or {}
    variables = data.get("variables") or {}
    table = data.get("table") or []
    loop_data = data.get("loopData") or {}

    # __name__ 设为 __main__：让原版命令行脚本的 if __name__ == "__main__" 直接生效
    namespace = {"__name__": "__main__"}

    started = time.monotonic()

    # 1) 注入 yuze API（单一真源随请求下发）
    exec(compile(prelude, "<yuze-prelude>", "exec"), namespace)
    namespace["_yuze_init"](variables, table, loop_data)

    # 2) 执行用户代码，捕获 stdout/stderr
    # argv 清成空参数：argparse 解析不会吃到桥进程自身的参数，原版脚本自动走默认模式
    sys.argv = ["yuze-block"]
    stdout_buf = io.StringIO()
    with contextlib.redirect_stdout(stdout_buf), contextlib.redirect_stderr(stdout_buf):
        exec(compile(code, "<yuze-user-code>", "exec"), namespace)

    # 3) 回传快照
    result = namespace["_yuze_dump"]()
    duration_ms = int((time.monotonic() - started) * 1000)

    return {
        "ok": True,
        "result": result,
        "output": stdout_buf.getvalue(),
        "durationMs": duration_ms,
    }


def execute_with_timeout(payload, timeout_s):
    """线程执行 + 超时探测（超时后 daemon 线程无法强杀，靠调用方 abort 兜底）"""
    box = {}

    def target():
        try:
            box["payload"] = execute_payload(payload)
        except BaseException as exc:  # noqa: BLE001 - 需要把任何执行期异常回传给扩展
            tb = exc.__traceback__
            lineno = None
            while tb is not None:
                frame_file = os.path.basename(tb.tb_frame.f_code.co_filename or "")
                if frame_file == "<yuze-user-code>":
                    lineno = tb.tb_lineno
                tb = tb.tb_next
            location = f"（用户代码第 {lineno} 行）" if lineno else ""
            box["payload"] = {
                "ok": False,
                "error": f"{type(exc).__name__}: {exc} {location}".strip(),
            }

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join(timeout_s)

    if thread.is_alive():
        return {"ok": False, "error": "Execution timed out on host Python"}

    return box.get("payload", {"ok": False, "error": "unknown"})


class BridgeHandler(BaseHTTPRequestHandler):
    server_version = "YuzeAutomaBridge/1.0"

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Yuze-Token")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

    def _send_json(self, status, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self, body_token=None):
        header_token = self.headers.get("X-Yuze-Token", "")
        candidate = header_token or (body_token or "")
        return hmac.compare_digest(candidate, TOKEN)

    def do_OPTIONS(self):  # noqa: N802 - http.server 命名约定
        self.send_response(204)
        self._cors()
        self.end_headers()

    def _query_param(self, name, default=None):
        qs = parse_qs(urlparse(self.path).query)
        values = qs.get(name)
        return values[0] if values else default

    def do_GET(self):  # noqa: N802
        path = urlparse(self.path).path

        if path == "/health":
            if not self._authorized():
                self._send_json(401, {"ok": False, "error": "unauthorized"})
                return
            self._send_json(200, {"ok": True, "python": sys.version.split()[0]})
            return

        if path == "/yuze/workflows":
            if not self._authorized():
                self._send_json(401, {"ok": False, "error": "unauthorized"})
                return
            with _lock:
                snapshot = list(WORKFLOWS_CACHE)
            self._send_json(200, {"ok": True, "workflows": snapshot})
            return

        if path == "/yuze/results":
            if not self._authorized():
                self._send_json(401, {"ok": False, "error": "unauthorized"})
                return
            try:
                since = int(self._query_param("since", "0"))
            except ValueError:
                since = 0
            with _lock:
                items = [r for r in RESULTS if r["commandId"] > since]
            self._send_json(200, {"ok": True, "results": items})
            return

        self._send_json(404, {"ok": False, "error": "not-found"})

    def do_POST(self):  # noqa: N802
        path = urlparse(self.path).path

        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > MAX_BODY:
            self._send_json(400, {"ok": False, "error": "bad-body-size"})
            return

        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_json(400, {"ok": False, "error": "bad-json"})
            return

        if not self._authorized(payload.get("token")):
            self._send_json(401, {"ok": False, "error": "unauthorized"})
            return

        # 扩展轮询：上报工作流摘要 + 取走新指令
        if path == "/yuze/commands":
            try:
                since = int(payload.get("since") or 0)
            except (TypeError, ValueError):
                since = 0
            reported = payload.get("workflows")
            if isinstance(reported, list):
                with _lock:
                    WORKFLOWS_CACHE.clear()
                    WORKFLOWS_CACHE.extend(reported)
            with _lock:
                pending = [c for c in COMMANDS if c["id"] > since]
                latest = COMMANDS[-1]["id"] if COMMANDS else since
            self._send_json(200, {"ok": True, "commands": pending, "latest": latest})
            return

        # AI：导入工作流（入队，由扩展轮询取走执行导入）
        if path == "/yuze/workflows":
            drawflow = payload.get("drawflow")
            if not payload.get("name") or not isinstance(drawflow, dict):
                self._send_json(400, {"ok": False, "error": "name 与 drawflow 必填"})
                return
            cmd = enqueue_command(
                "import_workflow",
                {
                    "name": payload.get("name"),
                    "description": payload.get("description") or "",
                    "drawflow": drawflow,
                },
            )
            self._send_json(200, {"ok": True, "commandId": cmd["id"]})
            return

        # AI：按 ID 执行已导入的工作流
        if path == "/yuze/execute":
            workflow_id = payload.get("workflowId")
            if not workflow_id:
                self._send_json(400, {"ok": False, "error": "workflowId 必填"})
                return
            cmd = enqueue_command(
                "execute_workflow",
                {"workflowId": workflow_id, "options": payload.get("options") or {}},
            )
            self._send_json(200, {"ok": True, "commandId": cmd["id"]})
            return

        # 扩展：回传指令执行结果
        if path == "/yuze/results":
            command_id = payload.get("commandId")
            if not command_id:
                self._send_json(400, {"ok": False, "error": "commandId 必填"})
                return
            push_result(
                {
                    "commandId": command_id,
                    "type": payload.get("type") or "",
                    "ok": bool(payload.get("ok")),
                    "result": payload.get("result"),
                    "error": payload.get("error"),
                }
            )
            self._send_json(200, {"ok": True})
            return

        if path == "/execute":
            timeout_ms = payload.get("timeoutMs") or 30000
            try:
                timeout_s = max(1, min(float(timeout_ms) / 1000.0, 600))
            except (TypeError, ValueError):
                timeout_s = 30

            response = execute_with_timeout(payload, timeout_s)
            self._send_json(200, response)
            return

        self._send_json(404, {"ok": False, "error": "not-found"})

    def log_message(self, fmt, *args):  # 安静模式：只记录关键请求
        if "/execute" in (args[0] if args else ""):
            sys.stdout.write(f"[bridge] {self.address_string()} {fmt % args}\n")


def main():
    server = ThreadingHTTPServer((HOST, PORT), BridgeHandler)
    print("=" * 56)
    print("[bridge] Automa 本机 Python 桥接服务已启动")
    print(f"[bridge] 地址      : http://{HOST}:{PORT}")
    print(f"[bridge] Python    : {sys.version.split()[0]}")
    print(f"[bridge] token 文件: {TOKEN_PATH}")
    print("[bridge] 停止      : Ctrl+C")
    print("=" * 56)
    print("[bridge] 提示：把上面 token 文件的内容填到 Automa 设置 → Python 桥接")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[bridge] 已停止")
        server.server_close()


if __name__ == "__main__":
    main()
