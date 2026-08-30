#!/usr/bin/env bash
set -euo pipefail
python3 - <<'PY'
import json
from pathlib import Path
p=Path('agents-results/2026-08-15/media-c-b-stage-2-content-and-ai-document-routing/worker-executions/current-wave/returns/STAGE2-AUDIT-SSOT.json')
d=json.loads(p.read_text())
required={'task_id','failure_class','failure_origin','proposed_state','formal_state','implementation_state','legal_frontier','blockers','next_actions','evidence_paths','unverified'}
assert required <= d.keys(), sorted(required-d.keys())
assert d['task_id']=='STAGE2-AUDIT-SSOT'
assert d['proposed_state'] in {'VERIFIED','BLOCKED'}
assert isinstance(d['blockers'],list) and isinstance(d['next_actions'],list)
print('SSOT_RETURN_VALID')
PY
