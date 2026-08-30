#!/usr/bin/env bash
set -euo pipefail

ssh -o BatchMode=yes -o ConnectTimeout=10 ubuntu@106.52.146.37 '
  set -euo pipefail
  cd /home/ubuntu/selfmedia-tools/openclaw-tag-router
  PYTHON=/home/ubuntu/selfmedia-tools/openclaw-media/.venv/bin/python
  PYTEST=/home/ubuntu/selfmedia-tools/openclaw-media/.venv/bin/pytest
  test -f openclaw_app/contracts/stage2_writer_contract.json
  test -f tests/test_stage2_writer_contract.py
  "$PYTHON" -m json.tool openclaw_app/contracts/stage2_writer_contract.json >/dev/null
  "$PYTHON" -m py_compile tests/test_stage2_writer_contract.py
  "$PYTEST" -q tests/test_stage2_writer_contract.py
'
