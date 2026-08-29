#!/usr/bin/env bash
set -euo pipefail
cd /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/.codex-work/stage1-mb1/backend
exec .venv/bin/python -m pytest -q tests/test_stage1_release1b_migration.py tests/test_postgres_migration_runner.py
