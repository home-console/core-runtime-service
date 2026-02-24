#!/bin/bash
# Устанавливает remote-client (Go-агент из /remote-client) и запускает его.
# Параметры: ENROLLMENT_TOKEN, CORE_URL (например https://core.example.com:8000).
# Сервер задаётся через RC_SERVER_*; токен передаётся как RC_AUTH_TOKEN для первого подключения.

set -euo pipefail

TOKEN="$1"
CORE_URL="$2"

if [ -z "${TOKEN}" ] || [ -z "${CORE_URL}" ]; then
  echo "Usage: $0 <ENROLLMENT_TOKEN> <CORE_URL>" >&2
  exit 1
fi

mkdir -p /opt/home-agent
cd /opt/home-agent

# Бинарник агента — remote-client (сборка: remote-client/build.sh или Makefile)
# URL может отдавать бинарник по архитектуре (например .../download?arch=linux-amd64)
curl -fsSL "${CORE_URL}/admin/v1/agents/download" -o remote-client
chmod +x remote-client

# Парсим CORE_URL в RC_SERVER_* (http://host:port -> host, port, ws; https -> wss)
CORE_URL="${CORE_URL%/}"
if [[ "${CORE_URL}" =~ ^https?://([^:/]+)(:([0-9]+))? ]]; then
  export RC_SERVER_HOST="${BASH_REMATCH[1]}"
  export RC_SERVER_PORT="${BASH_REMATCH[3]:-8000}"
  if [[ "${CORE_URL}" == https* ]]; then
    export RC_SERVER_PROTOCOL="websocket"
    export RC_USE_TLS="true"
  else
    export RC_SERVER_PROTOCOL="websocket"
    export RC_USE_TLS="false"
  fi
  export RC_SERVER_PATH="/ws"
else
  echo "Invalid CORE_URL: ${CORE_URL}" >&2
  exit 1
fi

# Токен для первого подключения (сервер может принять его как enrollment и выдать секреты)
export RC_AUTH_TOKEN="${TOKEN}"

./remote-client

