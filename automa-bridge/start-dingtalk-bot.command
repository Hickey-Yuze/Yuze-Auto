#!/bin/bash
# 启动钉钉机器人（依赖 automa-bridge/.venv 里的 dingtalk-stream）
DIR="$(cd "$(dirname "$0")" && pwd)"
if [ ! -d "$DIR/.venv" ]; then
  echo "首次运行：创建虚拟环境并安装 dingtalk-stream ..."
  python3 -m venv "$DIR/.venv"
  "$DIR/.venv/bin/pip" install -q dingtalk-stream
fi
exec "$DIR/.venv/bin/python" "$DIR/dingtalk-bot.py"
