#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
钉钉机器人 → Yuze Auto 自动化执行通道。

链路：钉钉群 @机器人「跑 <工作流名>」
  → 钉钉 Stream 长连接推消息到本进程（企业内部机器人，STREAM 模式，免公网 IP）
  → 解析指令 → 调本机桥（automa-bridge）执行工作流 → 轮询结果
  → 通过 sessionWebhook 把结果回复进群。

依赖：pip install dingtalk-stream（venv 建议放本目录 .venv）
配置：~/.automa-bridge/dingtalk.json
  {
    "clientId": "<应用 AppKey>",
    "clientSecret": "<应用 AppSecret>"
  }
  桥的 token 直接复用 ~/.automa-bridge/token，无需重复配置。
启动：python3 dingtalk-bot.py（或 start-dingtalk-bot.command）
"""

import asyncio
import json
import os
import sys

import dingtalk_stream
from dingtalk_stream import AckMessage

try:
    import requests
except ImportError:
    print("[dingtalk-bot] 缺少 requests：.venv/bin/pip install dingtalk-stream")
    sys.exit(1)

HOME = os.path.expanduser("~")
CONFIG_PATH = os.path.join(HOME, ".automa-bridge", "dingtalk.json")
TOKEN_PATH = os.path.join(HOME, ".automa-bridge", "token")
BRIDGE_PORT = 27182
RESULT_TIMEOUT_S = 150


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def load_token():
    with open(TOKEN_PATH, "r", encoding="utf-8") as f:
        return f.read().strip()


class YuzeAutoBot(dingtalk_stream.ChatbotHandler):
    """指令：跑 <工作流名> / 列表 / 帮助（默认）"""

    def __init__(self, bridge_token):
        super().__init__()
        self.bridge_token = bridge_token
        self.bridge = f"http://127.0.0.1:{BRIDGE_PORT}"

    def _get(self, path):
        r = requests.get(
            f"{self.bridge}{path}",
            headers={"X-Yuze-Token": self.bridge_token},
            timeout=10,
        )
        r.raise_for_status()
        return r.json()

    def _post(self, path, payload):
        r = requests.post(
            f"{self.bridge}{path}",
            headers={"X-Yuze-Token": self.bridge_token, "Content-Type": "application/json"},
            json=payload,
            timeout=15,
        )
        r.raise_for_status()
        return r.json()

    def list_workflows(self):
        data = self._get("/yuze/workflows")
        ws = data.get("workflows") or []
        if not ws:
            return "扩展还没上报工作流列表（桥没起？扩展没开 AI 通道？）"
        lines = [f"• {w['name']}" for w in ws]
        return "当前工作流：\n" + "\n".join(lines) + "\n\n回复「跑 工作流名」执行"

    def execute_workflow(self, name):
        # 1) 找工作流（支持模糊包含匹配）
        data = self._get("/yuze/workflows")
        ws = data.get("workflows") or []
        hits = [w for w in ws if name in (w.get("name") or "")]
        if not hits:
            return f"没找到包含「{name}」的工作流，回复「列表」查看全部"
        if len(hits) > 1:
            names = "、".join(w["name"] for w in hits[:5])
            return f"匹配到多条，请用更完整的名字：{names}"

        workflow = hits[0]
        # 2) 入队执行
        cmd = self._post("/yuze/execute", {"workflowId": workflow["id"]})
        command_id = cmd["commandId"]
        # 3) 轮询结果
        deadline = asyncio.get_event_loop().time() + RESULT_TIMEOUT_S
        while asyncio.get_event_loop().time() < deadline:
            results = self._get(f"/yuze/results?since={command_id - 1}").get("results") or []
            hit = [r for r in results if r.get("commandId") == command_id]
            if hit:
                entry = hit[0]
                if entry.get("ok"):
                    detail = entry.get("result") or {}
                    status = detail.get("status", "success")
                    return f"✅ 「{workflow['name']}」执行完成：{status}"
                return f"❌ 「{workflow['name']}」执行失败：{entry.get('error', '未知错误')}"
            asyncio.sleep(3)
        return f"⏳ 「{workflow['name']}」{RESULT_TIMEOUT_S} 秒内未等到执行结果（可能还在跑，稍后回复「列表」确认）"

    async def process(self, callback: dingtalk_stream.CallbackMessage):
        incoming_message = dingtalk_stream.ChatbotMessage.from_dict(callback.data)
        text = (incoming_message.text.content or "").strip()
        print(f"[dingtalk-bot] 收到指令: {text!r}（来自 {incoming_message.sender_nick or incoming_message.sender_staff_id}）")

        if not text or text.startswith("帮助"):
            reply = (
                "Yuze Auto 机器人指令：\n"
                "• 跑 <工作流名> —— 执行工作流并回传结果\n"
                "• 列表 —— 查看全部工作流"
            )
        elif text.startswith("列表"):
            reply = self.list_workflows()
        elif text.startswith("跑 "):
            name = text[2:].strip()
            reply = self.execute_workflow(name) if name else "用法：跑 <工作流名>"
        else:
            reply = "没看懂指令。回复「帮助」查看用法，「列表」看工作流。"

        self.reply_text(reply, incoming_message)
        return AckMessage.STATUS_OK


def main():
    if not os.path.exists(CONFIG_PATH):
        print(f"[dingtalk-bot] 缺配置文件 {CONFIG_PATH}")
        print('内容：{"clientId": "<AppKey>", "clientSecret": "<AppSecret>"}')
        sys.exit(1)

    config = load_config()
    client_id = config.get("clientId")
    client_secret = config.get("clientSecret")
    if not client_id or not client_secret:
        print("[dingtalk-bot] 配置缺 clientId/clientSecret")
        sys.exit(1)

    bridge_token = load_token() if os.path.exists(TOKEN_PATH) else ""
    if not bridge_token:
        print(f"[dingtalk-bot] 桥 token 不存在：{TOKEN_PATH}（先启动桥）")
        sys.exit(1)

    credential = dingtalk_stream.Credential(client_id, client_secret)
    client = dingtalk_stream.DingTalkStreamClient(credential)
    client.register_callback_handler(
        dingtalk_stream.chatbot.ChatbotMessage.TOPIC, YuzeAutoBot(bridge_token)
    )

    print("=" * 56)
    print("[dingtalk-bot] 钉钉机器人已启动（Stream 模式，长连接值守）")
    print(f"[dingtalk-bot] 桥: {f'http://127.0.0.1:{BRIDGE_PORT}'}")
    print("[dingtalk-bot] 群里 @机器人 发「跑 工作流名」即可触发")
    print("[dingtalk-bot] 停止: Ctrl+C")
    print("=" * 56)

    client.start_forever()


if __name__ == "__main__":
    main()
