#!/usr/bin/env bash
set -euo pipefail
ssh -o BatchMode=yes -o ConnectTimeout=10 ubuntu@106.52.146.37 '
  set -euo pipefail
  cd /tmp/openclaw-stage2-harness-luna/openclaw-tag-router
  PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. /home/ubuntu/selfmedia-tools/openclaw-media/.venv/bin/pytest -q tests/test_stage2_contract_validator.py
  PYTHONDONTWRITEBYTECODE=1 /home/ubuntu/selfmedia-tools/openclaw-media/.venv/bin/python - <<'PY'
from pathlib import Path
for name in ("openclaw_app/services/stage2_contract_validator.py", "tests/test_stage2_contract_validator.py"):
    compile(Path(name).read_text(encoding="utf-8"), name, "exec")
print("stage2 contract validator in-memory compile passed")
PY
  git diff --check
  test -z "$(git status --porcelain -- openclaw_app/services/stage2_contract_validator.py tests/test_stage2_contract_validator.py | sed -n "/^??/d")"
'
