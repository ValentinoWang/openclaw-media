#!/usr/bin/env bash
set -euo pipefail
cd /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/.codex-work/stage1-p10/backend
exec .venv/bin/python -m pytest -q tests/test_stage1_member_invalidation.py tests/test_workspace_resolution.py tests/test_account_auth.py
