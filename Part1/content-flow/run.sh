#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

PYTHON=""
if [[ -x ".venv/bin/python" ]]; then
  PYTHON=".venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON="python3"
elif command -v python >/dev/null 2>&1; then
  PYTHON="python"
else
  echo "Python not found. Please install Python 3." >&2
  exit 1
fi

HOST="${SERVER_HOST:-127.0.0.1}"
PORT="${SERVER_PORT:-8000}"
URL="http://${HOST}:${PORT}/"

check_port() {
  HOST="${HOST}" PORT="${PORT}" "$PYTHON" - <<'PY'
import os
import socket
import sys

host = os.environ["HOST"]
port = int(os.environ["PORT"])
s = socket.socket()
s.settimeout(0.2)
try:
    s.connect((host, port))
    sys.exit(0)
except Exception:
    sys.exit(1)
finally:
    s.close()
PY
}

if check_port; then
  echo "Server already running at ${URL}"
else
  "$PYTHON" -m src.server &
  SERVER_PID=$!
  for _ in {1..40}; do
    if check_port; then
      break
    fi
    sleep 0.2
  done
fi

if command -v open >/dev/null 2>&1; then
  open "$URL"
elif command -v xdg-open >/dev/null 2>&1; then
  xdg-open "$URL"
fi

if [[ -n "${SERVER_PID:-}" ]]; then
  wait "$SERVER_PID"
fi
