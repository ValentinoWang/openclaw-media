#!/usr/bin/env bash
set -euo pipefail

ssh -o BatchMode=yes ubuntu@106.52.146.37 '
cd /tmp/openclaw-stage2-org-luna/openclaw-tag-router
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. /home/ubuntu/selfmedia-tools/openclaw-media/.venv/bin/pytest -q tests/test_stage2_external_document.py
PYTHONDONTWRITEBYTECODE=1 /home/ubuntu/selfmedia-tools/openclaw-media/.venv/bin/python - <<'"'"'PY'"'"'
from pathlib import Path
for name in ("openclaw_app/services/stage2_external_document.py", "tests/test_stage2_external_document.py"):
    compile(Path(name).read_text(encoding="utf-8"), name, "exec")
print("stage2 external document in-memory compile passed")
PY
git diff --check
git status --short -- openclaw_app/services/stage2_external_document.py tests/test_stage2_external_document.py
'
