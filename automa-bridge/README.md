# Automa 本机 Python 桥接服务

Automa（Yuze fork）Python 代码块的「本机桥接」通道。纯 Python 标准库实现，**无需 pip 安装任何依赖**。

## 启动

| 平台 | 方式 |
| --- | --- |
| macOS | 双击 `start-bridge.command`（或终端 `python3 server.py`） |
| Windows | 双击 `start-bridge.bat`（或命令行 `python server.py`） |

首次启动会自动生成 token 到 `~/.automa-bridge/token`（Windows 为 `%USERPROFILE%\.automa-bridge\token`）。

## 配置扩展

1. 打开 Automa → 设置 → General →「Python 桥接」
2. 把 token 文件内容粘贴进 Token 输入框
3. 点击「测试连接」，看到 `✅ 连接成功，本机 Python 3.x.x` 即可

## 协议

- `GET /health` → `{"ok": true, "python": "3.x.x"}`（需 header `X-Yuze-Token`）
- `POST /execute`，body：`{token, timeoutMs, prelude, code, data: {variables, table}}`
  - 响应：`{ok, result, output, durationMs}`，`result` 为 yuze 快照的 JSON 字符串
- 仅监听 `127.0.0.1:27182`（可用环境变量 `YUZE_BRIDGE_PORT` 覆盖端口、`YUZE_BRIDGE_TOKEN` 覆盖 token）

该服务是通用 JSON 协议，DSH 等其他本地工具也可复用同一服务执行 Python 代码。

## AI 工作流通道（Yuze Harness 远程管理）

| 端点 | 说明 |
| --- | --- |
| `POST /yuze/commands` | 扩展轮询：上报工作流摘要 + 取走指令 |
| `POST /yuze/workflows` | AI 导入工作流 `{name, description?, drawflow}` |
| `POST /yuze/execute` | AI 触发执行 `{workflowId}` |
| `GET /yuze/workflows` | 工作流列表快照 |
| `GET /yuze/results?since=N` | 指令执行结果回传/查询 |

## 钉钉机器人（群里 @ 触发自动化）

企业内部机器人（Stream 模式，免公网 IP）：群里 @机器人「跑 <工作流名>」→ 调桥执行 → 结果回复进群。

1. 钉钉开发者后台建企业内部应用 → 开启「机器人」能力（消息接收模式选 **Stream 模式**）→ 发布版本 → 把机器人拉进群
2. 配置 `~/.automa-bridge/dingtalk.json`：`{"clientId": "<AppKey>", "clientSecret": "<AppSecret>"}`
3. 首次运行 `./start-dingtalk-bot.command`（自动建 .venv 装 dingtalk-stream）

指令：`跑 <工作流名>` / `列表` / `帮助`。
