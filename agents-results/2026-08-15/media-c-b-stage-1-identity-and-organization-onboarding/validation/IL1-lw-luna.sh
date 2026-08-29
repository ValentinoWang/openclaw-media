#!/usr/bin/env bash
set -euo pipefail
cd /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/.codex-work/stage1-i2/backend
exec .venv/bin/python -m pytest -q tests/test_account_identity_link.py tests/test_account_identity_workspace.py
