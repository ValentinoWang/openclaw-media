#!/usr/bin/env bash
set -euo pipefail
cd /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/.codex-work/stage1-t1/backend
exec .venv/bin/python -m pytest -q tests/test_stage1_resource_resolver.py tests/test_stage1_writer_gate.py tests/test_lark_resource_sync.py tests/test_lark_resource_hydration.py
