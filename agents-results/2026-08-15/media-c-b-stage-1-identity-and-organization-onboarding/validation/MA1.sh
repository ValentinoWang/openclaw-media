#!/usr/bin/env bash
set -euo pipefail

root="/Users/vsiyo/Desktop/创业项目/自媒体创作Agent/.codex-work/stage1-ma1-migration/backend"
cd "$root"
export PYTHONDONTWRITEBYTECODE=1
exec "$root/.venv/bin/python" -m pytest -q -p no:cacheprovider \
  tests/test_stage1_release1a_migration.py \
  tests/test_postgres_migration_runner.py
