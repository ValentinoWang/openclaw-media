#!/usr/bin/env bash
set -euo pipefail

cd /Users/vsiyo/Desktop/创业项目/自媒体创作Agent
export PYTHONDONTWRITEBYTECODE=1
exec /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/.codex-work/merge-candidate-v4/backend/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_rebuild_stage1_candidate.py
