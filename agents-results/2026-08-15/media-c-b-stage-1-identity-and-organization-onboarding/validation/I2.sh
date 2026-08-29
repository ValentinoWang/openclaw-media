#!/usr/bin/env bash
set -euo pipefail

root="/Users/vsiyo/Desktop/创业项目/自媒体创作Agent/.codex-work/stage1-i2/backend"
cd "$root"
export PYTHONDONTWRITEBYTECODE=1
exec "$root/.venv/bin/python" -m pytest -q -p no:cacheprovider \
  tests/test_stage1_personal_auth_lifecycle.py \
  tests/test_account_auth.py \
  tests/test_account_registration.py
