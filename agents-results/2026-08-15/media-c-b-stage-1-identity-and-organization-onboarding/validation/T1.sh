#!/usr/bin/env bash
set -euo pipefail

root="/Users/vsiyo/Desktop/创业项目/自媒体创作Agent/.codex-work/stage1-t1/backend"
cd "$root"
export PYTHONDONTWRITEBYTECODE=1
exec "$root/.venv/bin/python" -m pytest -q -p no:cacheprovider \
  tests/test_stage1_acceptance_harness.py \
  tests/test_media_stage1_shared_contract.py
