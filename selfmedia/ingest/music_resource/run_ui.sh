#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${ROOT_DIR}/.venv"

if [ -z "${PYTHON_BIN:-}" ]; then
  if command -v python3.13 >/dev/null 2>&1; then
    PYTHON_BIN=python3.13
  else
    PYTHON_BIN=python3
  fi
fi

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "Python not found: $PYTHON_BIN" >&2
  exit 1
fi

if [ ! -d "$VENV_DIR" ]; then
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

source "$VENV_DIR/bin/activate"
python -m pip install -r "${ROOT_DIR}/requirements.txt"
if [ "${SKIP_PLAYWRIGHT_INSTALL:-}" != "1" ]; then
  python -m playwright install chromium
fi
exec python "${ROOT_DIR}/ui_server.py" "$@"
