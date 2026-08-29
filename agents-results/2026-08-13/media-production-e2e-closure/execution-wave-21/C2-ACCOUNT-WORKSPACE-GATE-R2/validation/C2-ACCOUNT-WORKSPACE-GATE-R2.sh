#!/usr/bin/env bash
set -euo pipefail

root="/Users/vsiyo/Desktop/创业项目/自媒体创作Agent"
bundle="$root/agents-results/2026-08-13/media-production-e2e-closure"
backend="$root/.codex-work/merge-candidate-v4/backend"
history_root="$root/.codex-work/c2-main-takeover/backend"
contract="$bundle/acceptance-fragments/MPE2E-TASK-RUN-V3/acceptance-contract.md"
decision="$bundle/.ssot/nodes/D5.json"
protected_test="$root/scripts/acceptance/test-mpe2e-task-run-v3.sh"
venv="/tmp/mpe2e-account-workspace-gate-r2-venv"
container="mpe2e-account-workspace-gate-r2-pg-$$"

sha() { shasum -a 256 "$1" | awk '{print $1}'; }

cleanup() {
  docker rm -f "$container" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

test "$(sha "$contract")" = "35143a0fb22218ebdcf969ee3a137431c37f21f90781db15572909e1dba0ca8b"
test "$(sha "$decision")" = "c6bd807376561c25820938b1839f50b633a7e2f4911f3460fea9a6f5e1a0e12b"
test "$(sha "$protected_test")" = "dee8b55304a60b4284462310f68f03099369af15071efc2fe5f39dcc8f67b73d"
test "$(sha "$root/acceptance/human/MPE2E-TASK-RUN-V3/checklist.md")" = "aafbab44663b5bf42b8a12f33c45194ae11914d8fb590bd3fc988781da7a636f"
test "$(sha "$root/acceptance/human/MPE2E-TASK-RUN-V3/binding.md")" = "fe13d4f2b161d309e14e4bb3e3919e403518c3c796c99ab45c3bea550299059d"
test "$(sha "$backend/.candidate-source.sha256")" = "c67461000c4dd3cee5f5087d76880a402f2831c20ba365e6c4e719abf3a32b44"
test "$(sha "$history_root/openclaw_app/migrations/postgres_manifest.json")" = "e46eba2ee84bc1a749ae932c089fa953f3abf952005832f697198ec9bb8ecf6c"

python3 - "$history_root" "$backend" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

history_root = Path(sys.argv[1])
candidate_root = Path(sys.argv[2])
history_manifest_path = history_root / "openclaw_app/migrations/postgres_manifest.json"
history_manifest = json.loads(history_manifest_path.read_text(encoding="utf-8"))
entries = [*history_manifest["migrations"], *history_manifest["excludedMigrations"]]
assert len(history_manifest["migrations"]) == 32
assert len(history_manifest["excludedMigrations"]) == 7
for entry in entries:
    relative = Path(entry["source"])
    expected = entry.get("sourceSha256", entry.get("sha256"))
    assert isinstance(expected, str) and len(expected) == 64
    history_path = history_root / relative
    candidate_path = candidate_root / relative
    assert history_path.is_file(), history_path
    assert candidate_path.is_file(), candidate_path
    assert hashlib.sha256(history_path.read_bytes()).hexdigest() == expected, history_path
    assert hashlib.sha256(candidate_path.read_bytes()).hexdigest() == expected, candidate_path
PY

test -f "$backend/openclaw_app/services/media_web_tasks.py"
test -f "$backend/openclaw_app/services/media_task_repository.py"
test -f "$backend/openclaw_app/adapters/http_api.py"
test -f "$backend/openclaw_app/migrations/postgres_manifest.json"
test "$(find "$backend/openclaw_app/migrations/canonical" -maxdepth 1 -type f -name '038_*.sql' | wc -l | tr -d ' ')" = "1"
test "$(find "$backend/openclaw_app/migrations/canonical" -maxdepth 1 -type f -name '*.sql' | wc -l | tr -d ' ')" = "40"

if rg -n 'creator_profiles' "$backend/openclaw_app/services/media_task_repository.py"; then
  echo "task account repository must not use creator_profiles" >&2
  exit 1
fi
rg -n 'workspace_not_allowed' \
  "$backend/openclaw_app/services/media_web_tasks.py" \
  "$backend/openclaw_app/services/media_task_repository.py" >/dev/null
rg -n 'workspace_mode|role' "$backend/openclaw_app/adapters/http_api.py" >/dev/null
rg -n 'customer_owned' \
  "$backend/openclaw_app/migrations/canonical/038_"*.sql \
  "$backend/openclaw_app/services/media_task_repository.py" >/dev/null

pycache="$(mktemp -d /tmp/mpe2e-account-workspace-r2-pycache.XXXXXX)"
PYTHONPYCACHEPREFIX="$pycache" python3 -m py_compile \
  "$backend/openclaw_app/services/media_web_tasks.py" \
  "$backend/openclaw_app/services/media_task_repository.py" \
  "$backend/openclaw_app/adapters/http_api.py" \
  "$backend/scripts/run_postgres_migrations.py"
rm -rf "$pycache"

if [ ! -x "$venv/bin/python" ]; then
  python3 -m venv "$venv"
fi
"$venv/bin/python" -m pip install --disable-pip-version-check -q \
  'pytest==8.4.1' 'psycopg[binary]==3.2.9' 'bcrypt==4.3.0' \
  'cryptography==45.0.6' 'PyYAML==6.0.2'

cd "$backend"
"$venv/bin/python" -m pytest -q \
  tests/test_account_auth.py \
  tests/test_media_web_tasks.py \
  tests/test_media_task_v3_contract.py \
  tests/test_media_web_tasks_postgres.py \
  tests/test_http_api.py \
  tests/test_media_business_http.py \
  tests/test_postgres_migration_runner.py

docker run -d --rm \
  --name "$container" \
  -e POSTGRES_USER=workspaceqa \
  -e POSTGRES_PASSWORD=workspaceqa-local-only \
  -e POSTGRES_DB=workspaceqa \
  -p 127.0.0.1::5432 \
  postgres:16 >/dev/null

for _ in $(seq 1 60); do
  if docker exec "$container" pg_isready -U workspaceqa -d workspaceqa >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
docker exec "$container" pg_isready -U workspaceqa -d workspaceqa >/dev/null
pg_port="$(docker port "$container" 5432/tcp | awk -F: 'NR == 1 {print $NF}')"
test -n "$pg_port"
dsn="postgresql://workspaceqa:workspaceqa-local-only@127.0.0.1:${pg_port}/workspaceqa"

"$venv/bin/python" scripts/run_postgres_migrations.py apply \
  --source-root "$backend" \
  --dsn "$dsn" \
  --mode empty
OPENCLAW_C2_TEST_DATABASE_URL="$dsn" "$venv/bin/python" -m pytest -q \
  tests/test_media_task_repository_postgres.py \
  tests/test_media_web_tasks_postgres.py
"$venv/bin/python" scripts/run_postgres_migrations.py verify \
  --source-root "$backend" \
  --dsn "$dsn"
cleanup

set +e
"$protected_test" >/tmp/mpe2e-account-workspace-r2-protected.log 2>&1
protected_rc=$?
set -e
if [ "$protected_rc" -ne 3 ]; then
  cat /tmp/mpe2e-account-workspace-r2-protected.log >&2
  echo "protected production gate must remain red only because receipts are absent" >&2
  exit 1
fi

test "$(sha "$contract")" = "35143a0fb22218ebdcf969ee3a137431c37f21f90781db15572909e1dba0ca8b"
test "$(sha "$decision")" = "c6bd807376561c25820938b1839f50b633a7e2f4911f3460fea9a6f5e1a0e12b"
test "$(sha "$protected_test")" = "dee8b55304a60b4284462310f68f03099369af15071efc2fe5f39dcc8f67b73d"
test "$(sha "$history_root/openclaw_app/migrations/postgres_manifest.json")" = "e46eba2ee84bc1a749ae932c089fa953f3abf952005832f697198ec9bb8ecf6c"
echo "Account/workspace enqueue gates passed; production receipt gate remains correctly blocked."
