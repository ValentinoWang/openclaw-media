#!/usr/bin/env bash
set -euo pipefail
python3 - <<'PY'
import json
from pathlib import Path
p=Path('agents-results/2026-08-15/media-c-b-stage-2-content-and-ai-document-routing/worker-executions/current-wave/returns/STAGE2-AUDIT-ROUTES.json')
d=json.loads(p.read_text())
required={'task_id','commit','failure_class','failure_origin','proposed_state','findings','missing_integration','exact_files','verification_commands','evidence_paths','unverified'}
assert required <= d.keys(), sorted(required-d.keys())
assert d['task_id']=='STAGE2-AUDIT-ROUTES'
assert d['proposed_state'] in {'VERIFIED','BLOCKED'}
assert isinstance(d['findings'],list) and isinstance(d['missing_integration'],list)
print('ROUTES_RETURN_VALID')
PY
