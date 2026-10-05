#!/bin/bash
# 启动钉钉机器人（依赖 automa-bridge/.venv 里的 dingtalk-stream）
DIR="$(cd "$(dirname "$0")" && pwd)"
if [ ! -d "$DIR/.venv" ]; then
  echo "首次运行：创建虚拟环境并安装 dingtalk-stream ..."
  python3 -m venv "$DIR/.venv"
  "$DIR/.venv/bin/pip" install -q dingtalk-stream
fi

# python.org 版 Python 在 macOS 不读系统钥匙串证书，SSL 握手会失败；
# 把 certifi 的 CA bundle 喂给 OpenSSL（只影响本进程，不改系统状态）
SSL_CERT_FILE="$("$DIR/.venv/bin/python" -c 'import certifi; print(certifi.where())')"
export SSL_CERT_FILE

exec "$DIR/.venv/bin/python" "$DIR/dingtalk-bot.py"
