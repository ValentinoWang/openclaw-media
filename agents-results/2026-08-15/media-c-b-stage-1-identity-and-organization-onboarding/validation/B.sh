#!/usr/bin/env bash
set -euo pipefail

cd /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/.codex-work/merge-candidate-v4/backend
exec .venv/bin/python -m pytest -q tests/test_media_stage1_shared_contract.py
