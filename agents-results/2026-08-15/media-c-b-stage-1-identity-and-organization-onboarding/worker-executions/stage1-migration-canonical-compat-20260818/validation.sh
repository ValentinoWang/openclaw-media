#!/usr/bin/env bash
set -u
cd /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/.codex-work/stage1-integrated/backend
./.venv/bin/python -m compileall -q scripts/run_postgres_migrations.py
./.venv/bin/pytest -q tests/test_postgres_migration_runner.py
