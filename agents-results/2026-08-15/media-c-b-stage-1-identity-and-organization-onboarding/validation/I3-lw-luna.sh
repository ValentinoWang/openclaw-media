#!/usr/bin/env bash
set -euo pipefail
cd /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/.codex-work/stage1-ma1-migration/backend
exec .venv/bin/python -m pytest -q tests/test_workspace_resolution.py tests/test_account_auth.py tests/test_account_identity_workspace.py
