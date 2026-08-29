#!/usr/bin/env bash
set -euo pipefail

root="/Users/vsiyo/Desktop/创业项目/自媒体创作Agent"
bundle="$root/agents-results/2026-08-13/media-production-e2e-closure"
candidate="$root/.codex-work/c2-main-takeover"
backend="$candidate/backend"
frontend="$candidate/frontend"
contract="$bundle/acceptance-fragments/MPE2E-TASK-RUN-V3/acceptance-contract.md"
protected_test="$root/scripts/acceptance/test-mpe2e-task-run-v3.sh"
baseline="$bundle/execution-wave-8/C2-V3-IMPLEMENT/candidate-baseline.sha256"
container="c2-v3-pg16-validation"
venv="/tmp/c2-v3-validation-venv"

cleanup() {
  docker rm -f "$container" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

test "$(shasum -a 256 "$contract" | awk '{print $1}')" = "35143a0fb22218ebdcf969ee3a137431c37f21f90781db15572909e1dba0ca8b"
test "$(shasum -a 256 "$protected_test" | awk '{print $1}')" = "dee8b55304a60b4284462310f68f03099369af15071efc2fe5f39dcc8f67b73d"
test "$(shasum -a 256 "$root/acceptance/human/MPE2E-TASK-RUN-V3/checklist.md" | awk '{print $1}')" = "aafbab44663b5bf42b8a12f33c45194ae11914d8fb590bd3fc988781da7a636f"
test "$(shasum -a 256 "$root/acceptance/human/MPE2E-TASK-RUN-V3/binding.md" | awk '{print $1}')" = "fe13d4f2b161d309e14e4bb3e3919e403518c3c796c99ab45c3bea550299059d"
test "$(shasum -a 256 "$baseline" | awk '{print $1}')" = "37f383a3500775682f948ae4dda1aa9eaa5820f3b3b3ca12c1d91e602004b734"

test -f "$backend/openclaw_app/services/media_task_repository.py"
test -f "$backend/openclaw_app/services/media_task_runner.py"
test -f "$backend/openclaw_app/migrations/canonical/037_media_task_runner_receipts.sql"
test -f "$backend/tests/test_media_task_v3_contract.py"
test -f "$backend/tests/test_media_web_tasks_postgres.py"
test -f "$backend/tests/test_media_task_runner.py"

service="$backend/openclaw_app/services/media_web_tasks.py"
if rg -n 'ThreadPoolExecutor|import fcntl|from fcntl|_executor[.]submit|_recover_tasks|_worker_lease|_task_path|_write_task|_iter_tasks|_iter_tenant_tasks|tasks_dir|events_dir' "$service"; then
  echo "legacy file or in-process task execution path remains" >&2
  exit 1
fi
rg -n 'PostgresMediaTaskRepository|MediaTaskRepository' "$service" >/dev/null
rg -n 'PostgresMediaTaskRepository' "$backend/openclaw_app/server_cli.py" >/dev/null
rg -n 'media_task_runner|runner' "$backend/openclaw_app/server_cli.py" >/dev/null
rg -n 'claim_next|heartbeat|runner_public_id|executor_public_id' "$backend/openclaw_app/services/media_task_runner.py" >/dev/null
rg -n 'user_public_id' "$backend/openclaw_app/adapters/http_api.py" >/dev/null
rg -n 'required_input_missing|account_relationship_unavailable|account_relationship_conflict' \
  "$backend/openclaw_app/services/media_web_tasks.py" \
  "$backend/openclaw_app/services/media_task_repository.py" >/dev/null

if rg -n 'ThreadPoolExecutor|import fcntl|from fcntl' \
  "$backend/openclaw_app/services/media_web_tasks.py" \
  "$backend/openclaw_app/services/media_task_runner.py" \
  "$backend/openclaw_app/server_cli.py"; then
  echo "forbidden executor or file locking primitive remains" >&2
  exit 1
fi

pycache="$(mktemp -d /tmp/c2-v3-pycache.XXXXXX)"
PYTHONPYCACHEPREFIX="$pycache" python3 -m py_compile \
  "$backend/openclaw_app/services/media_task_repository.py" \
  "$backend/openclaw_app/services/media_task_runner.py" \
  "$backend/openclaw_app/services/media_web_tasks.py" \
  "$backend/openclaw_app/adapters/http_api.py" \
  "$backend/openclaw_app/server_cli.py"
rm -rf "$pycache"

if [ ! -x "$venv/bin/python" ]; then
  python3 -m venv "$venv"
fi
"$venv/bin/python" -m pip install --disable-pip-version-check -q \
  'pytest==8.4.1' 'psycopg[binary]==3.2.9'

cd "$backend"
"$venv/bin/python" -m pytest -q \
  tests/test_media_task_v3_contract.py \
  tests/test_media_web_tasks_postgres.py \
  tests/test_media_task_runner.py \
  tests/test_media_web_tasks.py \
  tests/test_postgres_migration_runner.py

docker rm -f "$container" >/dev/null 2>&1 || true
docker run -d --rm \
  --name "$container" \
  -e POSTGRES_USER=c2qa \
  -e POSTGRES_PASSWORD=c2qa-local-only \
  -e POSTGRES_DB=c2qa \
  -p 127.0.0.1::5432 \
  postgres:16 >/dev/null

for _ in $(seq 1 60); do
  if docker exec "$container" pg_isready -U c2qa -d c2qa >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
docker exec "$container" pg_isready -U c2qa -d c2qa >/dev/null
pg_port="$(docker port "$container" 5432/tcp | awk -F: 'NR == 1 {print $NF}')"
test -n "$pg_port"
dsn="postgresql://c2qa:c2qa-local-only@127.0.0.1:${pg_port}/c2qa"

"$venv/bin/python" scripts/run_postgres_migrations.py apply \
  --source-root "$backend" \
  --dsn "$dsn" \
  --mode empty
OPENCLAW_C2_TEST_DATABASE_URL="$dsn" "$venv/bin/python" -m pytest -q \
  tests/test_media_task_repository_postgres.py \
  tests/test_media_web_tasks_postgres.py \
  tests/test_media_task_runner.py
"$venv/bin/python" scripts/run_postgres_migrations.py verify \
  --source-root "$backend" \
  --dsn "$dsn"
cleanup

cd "$frontend"
if [ ! -x node_modules/.bin/tsx ]; then
  npm ci --ignore-scripts --no-audit --no-fund
fi
node_modules/.bin/tsc --noEmit -p tsconfig.media-u12b.json
npm run qa:task-launch
npm run qa:media-recent-task-presentation
npm run build:media

set +e
"$protected_test" >/tmp/c2-v3-protected-post-implementation.log 2>&1
protected_rc=$?
set -e
if [ "$protected_rc" -ne 3 ]; then
  cat /tmp/c2-v3-protected-post-implementation.log >&2
  echo "protected production gate must remain red only because receipts are absent" >&2
  exit 1
fi

test "$(shasum -a 256 "$contract" | awk '{print $1}')" = "35143a0fb22218ebdcf969ee3a137431c37f21f90781db15572909e1dba0ca8b"
test "$(shasum -a 256 "$protected_test" | awk '{print $1}')" = "dee8b55304a60b4284462310f68f03099369af15071efc2fe5f39dcc8f67b73d"
echo "C2 V3 implementation validation passed; production receipt gate remains correctly blocked."
