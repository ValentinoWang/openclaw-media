#!/usr/bin/env bash
set -euo pipefail

ssh -o BatchMode=yes -o ConnectTimeout=10 ubuntu@106.52.146.37 '
  set -euo pipefail
  cd /home/ubuntu/selfmedia-tools/openclaw-tag-router
  PYTHON=/home/ubuntu/selfmedia-tools/openclaw-media/.venv/bin/python
  PYTEST=/home/ubuntu/selfmedia-tools/openclaw-media/.venv/bin/pytest
  test -f openclaw_app/services/stage2_context.py
  test -f tests/test_stage2_context.py
  "$PYTHON" -m py_compile openclaw_app/services/stage2_context.py tests/test_stage2_context.py
  "$PYTEST" -q tests/test_stage2_context.py
'
