#!/usr/bin/env bash
set -euo pipefail
root=/Users/vsiyo/Desktop/创业项目/自媒体创作Agent/.codex-work/stage2-hardening-persistence-20260820
cd "$root"
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=.
/home/ubuntu/selfmedia-tools/openclaw-media/.venv/bin/python -m pytest -q tests/test_stage2_persistence_hardening.py tests/test_stage2_production.py tests/test_stage2_personal_pipeline.py tests/test_stage2_artifact_state.py tests/test_stage2_external_document.py
/home/ubuntu/selfmedia-tools/openclaw-media/.venv/bin/python -m pytest -q tests/test_stage2_*.py
/home/ubuntu/selfmedia-tools/openclaw-media/.venv/bin/python -m compileall -q openclaw_app tests
git diff --check
