#!/usr/bin/env bash
set -euo pipefail
root=/Users/vsiyo/Desktop/创业项目/自媒体创作Agent/.codex-work/stage2-hardening-runtime-20260820
cd "$root"
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=.
/home/ubuntu/selfmedia-tools/openclaw-media/.venv/bin/python -m pytest -q tests/test_stage2_runtime_hardening.py tests/test_stage2_gateway.py tests/test_stage2_runtime.py tests/test_stage2_server_cli.py
/home/ubuntu/selfmedia-tools/openclaw-media/.venv/bin/python -m pytest -q tests/test_stage2_*.py
/home/ubuntu/selfmedia-tools/openclaw-media/.venv/bin/python -m compileall -q openclaw_app tests
git diff --check
