#!/usr/bin/env bash
set -euo pipefail
cd /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/.codex-work/stage1-i6/backend
exec .venv/bin/python -m pytest -q tests/test_stage1_authorization.py tests/test_tenant_activity_access.py tests/test_workspace_resolution.py
