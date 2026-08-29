#!/usr/bin/env bash
set -euo pipefail

candidate="/Users/vsiyo/Desktop/创业项目/自媒体创作Agent/.codex-work/stage1-integrated/backend"
cd "$candidate"
export PYTHONPATH="$candidate"
python_bin="$candidate/.venv/bin/python"
if [[ ! -x "$python_bin" ]]; then
  python_bin="python3"
fi

"$python_bin" -m compileall -q openclaw_app/account openclaw_app/server_cli.py

"$python_bin" -m pytest -q \
  tests/test_stage1_personal_auth_lifecycle.py \
  tests/test_server_cli_stage1_composition.py \
  tests/test_account_identity_postgres.py \
  tests/test_account_registration_http_postgres.py
