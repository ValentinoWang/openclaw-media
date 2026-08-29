#!/usr/bin/env bash
set -euo pipefail

root="/Users/vsiyo/Desktop/创业项目/自媒体创作Agent"
bundle="$root/agents-results/2026-08-13/media-production-e2e-closure"
baseline="$root/.codex-work/production-baseline-20260814T084319Z/backend"
candidate="$root/.codex-work/merge-candidate-v4/backend"
c2_manifest="$bundle/execution-wave-10/C2-V3-FINDINGS-REPAIR/baseline/postrepair-source.sha256"
task_contract="$bundle/acceptance-fragments/MPE2E-TASK-RUN-V3/acceptance-contract.md"
task_guard="$root/scripts/acceptance/test-mpe2e-task-run-v3.sh"
auth_guard="$root/scripts/acceptance/test-mpe2e-auth-web.sh"
container="c4-backend-verify-r2-$$"
scratch=""

sha() { shasum -a 256 "$1" | awk '{print $1}'; }

cleanup() {
  docker rm -f "$container" >/dev/null 2>&1 || true
  if [ -n "$scratch" ] && [ -d "$scratch" ]; then
    case "$scratch" in
      /tmp/c4-backend-verify-r2.*) rm -rf -- "$scratch" ;;
      *) echo "refusing to clean unexpected path: $scratch" >&2 ;;
    esac
  fi
}
trap cleanup EXIT INT TERM

assert_no_candidate_residue() {
  if find "$candidate" \( \
    -type d \( -name __pycache__ -o -name .pytest_cache -o -name .mypy_cache -o -name .ruff_cache -o -name .cache \) \
    -o -type f \( -name '*.pyc' -o -name '*.pyo' -o -name '*.log' -o -name .DS_Store \) \
  \) -print -quit | grep -q .; then
    echo "candidate contains Python cache or transient residue" >&2
    exit 1
  fi
}

test "$(sha "$bundle/.ssot/manifest.json")" = "c6aca57fc2676e8a51704bb607c84245a0e55681bd4202270e659a8290ce9782"
test "$(sha "$bundle/.ssot/nodes/B1.json")" = "cd561d9e4d8b2184b4932da81fc143ae105bf917fc0e520849b6547ca92fabbc"
test "$(sha "$bundle/.ssot/nodes/C4.json")" = "e8d5102533b0597d7bff0a7d6469262fb48d6efe8e8a8c92b1561cab5f015b21"
test "$(sha "$bundle/acceptance-fragments/MPE2E-AUTH-WEB/acceptance-contract.md")" = "a0feedc825fff609f3cd72cbe7a0705ee0f0276fa18209a7f6192d4393984fdc"
test "$(sha "$task_contract")" = "35143a0fb22218ebdcf969ee3a137431c37f21f90781db15572909e1dba0ca8b"
test "$(sha "$task_guard")" = "dee8b55304a60b4284462310f68f03099369af15071efc2fe5f39dcc8f67b73d"
test "$(sha "$baseline/.manifest.sha256")" = "bca0dac2e657d0d1fd939c87645ad278fb6e9a049ac18429c11e714b5684e49b"
test "$(sha "$c2_manifest")" = "23d4017ba54422ba30f1aceb88ff34b2d0a034470d1bb70b9015e95613abe927"
test "$(sha "$candidate/.candidate-source.sha256")" = "9519c707bb842bea97e46eb770300417467c10fc5f5c8ce6916182e1f7600018"
test "$(wc -l < "$candidate/.candidate-source.sha256" | tr -d ' ')" = "562"

scratch="$(mktemp -d /tmp/c4-backend-verify-r2.XXXXXX)"
persistent_manifest="$scratch/persistent-baseline.sha256"
counts_file="$scratch/baseline-counts.txt"

awk -v persistent_manifest="$persistent_manifest" -v counts_file="$counts_file" '
  BEGIN { persistent = 0; transient = 0; invalid = 0 }
  {
    digest = substr($0, 1, 64)
    separator = substr($0, 65, 2)
    path = substr($0, 67)
    if (length(digest) != 64 || digest ~ /[^0-9a-f]/ || separator != "  " || path == "") {
      invalid = 1
      next
    }
    if (path ~ /(^|\/)__pycache__(\/|$)/ || path ~ /\.py[co]$/ ||
        path ~ /(^|\/)\.DS_Store$/ || path ~ /(^|\/)\.pytest_cache(\/|$)/ ||
        path ~ /\.log$/) {
      transient += 1
      next
    }
    print $0 >> persistent_manifest
    persistent += 1
  }
  END {
    print persistent, transient > counts_file
    if (invalid || persistent != 550 || transient != 236) exit 1
  }
' "$baseline/.manifest.sha256"

read -r persistent_count transient_count < "$counts_file"
test "$persistent_count" = "550"
test "$transient_count" = "236"
(cd "$baseline" && shasum -a 256 -c "$persistent_manifest" >/dev/null)
(cd "$root" && shasum -a 256 -c "$c2_manifest" >/dev/null)

test -f "$candidate/.merge-provenance.json"
test "$(jq -r '.baseline.backend_release' "$candidate/.merge-provenance.json")" = "20260814T062408Z-opc-feishu-login"
test "$(jq -r '.inputs.c2_source_manifest_sha256' "$candidate/.merge-provenance.json")" = "23d4017ba54422ba30f1aceb88ff34b2d0a034470d1bb70b9015e95613abe927"
test "$(jq -r '.inputs.auth_contract_sha256' "$candidate/.merge-provenance.json")" = "a0feedc825fff609f3cd72cbe7a0705ee0f0276fa18209a7f6192d4393984fdc"

if find "$candidate" -type l -print -quit | grep -q .; then
  echo "candidate must not contain symlinks" >&2
  exit 1
fi
assert_no_candidate_residue
(cd "$candidate" && shasum -a 256 -c .candidate-source.sha256 >/dev/null)

test -f "$candidate/openclaw_app/services/media_task_repository.py"
test -f "$candidate/openclaw_app/services/media_task_runner.py"
test -f "$candidate/openclaw_app/migrations/canonical/037_media_task_runner_receipts.sql"
test -f "$candidate/openclaw_app/migrations/037_media_document_workspace_authority.sql"
test -f "$candidate/openclaw_app/migrations/postgres_manifest.json"

rg -n 'login_verified_email|user_public_id|csrf_token' "$candidate/openclaw_app/account/auth.py" >/dev/null
rg -n 'OpcFeishuLoginClient|/auth/feishu/start|/auth/feishu/status|login_verified_email|user_public_id' \
  "$candidate/openclaw_app/adapters/http_api.py" >/dev/null
rg -n 'accounts[.]feishu[.]cn|open[.]feishu[.]cn|https' "$candidate/openclaw_app/account/opc_login.py" >/dev/null
rg -n 'PostgresMediaTaskRepository|media_task_runner|runner' "$candidate/openclaw_app/server_cli.py" >/dev/null
rg -n 'claim_next|heartbeat|runner_public_id|executor_public_id' "$candidate/openclaw_app/services/media_task_runner.py" >/dev/null
rg -n 'required_input_missing|account_relationship_unavailable|account_relationship_conflict' \
  "$candidate/openclaw_app/services/media_web_tasks.py" \
  "$candidate/openclaw_app/services/media_task_repository.py" >/dev/null

if rg -n 'ThreadPoolExecutor|import fcntl|from fcntl|_executor[.]submit|_recover_tasks|_task_path|_write_task|_iter_tasks|tasks_dir|events_dir' \
  "$candidate/openclaw_app/services/media_web_tasks.py" \
  "$candidate/openclaw_app/services/media_task_runner.py" \
  "$candidate/openclaw_app/server_cli.py"; then
  echo "legacy task execution path remains" >&2
  exit 1
fi

pycache="$scratch/pycache"
mkdir -p "$pycache"
PYTHONPYCACHEPREFIX="$pycache" python3 -m py_compile \
  "$candidate/openclaw_app/account/auth.py" \
  "$candidate/openclaw_app/account/opc_login.py" \
  "$candidate/openclaw_app/adapters/http_api.py" \
  "$candidate/openclaw_app/services/media_task_repository.py" \
  "$candidate/openclaw_app/services/media_task_runner.py" \
  "$candidate/openclaw_app/services/media_web_tasks.py" \
  "$candidate/openclaw_app/server_cli.py"

venv="$scratch/venv"
python3 -m venv "$venv"
PIP_CACHE_DIR="$scratch/pip-cache" "$venv/bin/python" -m pip install \
  --disable-pip-version-check -q \
  'pytest==8.4.1' 'psycopg[binary]==3.2.9' 'bcrypt==4.3.0' 'cryptography==45.0.5'

cd "$candidate"
PYTHONDONTWRITEBYTECODE=1 "$venv/bin/python" -m pytest -q -p no:cacheprovider \
  tests/test_account_auth.py \
  tests/test_http_api.py \
  tests/test_media_business_http.py \
  tests/test_media_task_v3_contract.py \
  tests/test_media_web_tasks.py \
  tests/test_media_task_runner.py \
  tests/test_postgres_migration_runner.py \
  tests/test_tenant_projection_http.py

docker run -d --rm \
  --name "$container" \
  -e POSTGRES_USER=c4qa \
  -e POSTGRES_PASSWORD=c4qa-local-only \
  -e POSTGRES_DB=c4qa \
  -p 127.0.0.1::5432 \
  postgres:16 >/dev/null

ready=0
for _ in $(seq 1 60); do
  if docker exec "$container" pg_isready -U c4qa -d c4qa >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 1
done
test "$ready" = "1"
pg_port="$(docker port "$container" 5432/tcp | awk -F: 'NR == 1 {print $NF}')"
test -n "$pg_port"
dsn="postgresql://c4qa:c4qa-local-only@127.0.0.1:${pg_port}/c4qa"

PYTHONDONTWRITEBYTECODE=1 "$venv/bin/python" scripts/run_postgres_migrations.py \
  apply --source-root "$candidate" --dsn "$dsn" --mode empty
OPENCLAW_ACCOUNT_TEST_DATABASE_URL="$dsn" \
OPENCLAW_C2_TEST_DATABASE_URL="$dsn" \
A2B_TEST_DATABASE_URL="$dsn" \
PYTHONDONTWRITEBYTECODE=1 \
  "$venv/bin/python" -m pytest -q -p no:cacheprovider \
    tests/test_account_auth.py \
    tests/test_account_registration.py \
    tests/test_account_registration_http_postgres.py \
    tests/test_media_task_repository_postgres.py \
    tests/test_media_web_tasks_postgres.py \
    tests/test_media_task_runner.py \
    tests/test_media_document_workspace_authority_migration.py
PYTHONDONTWRITEBYTECODE=1 "$venv/bin/python" scripts/run_postgres_migrations.py \
  verify --source-root "$candidate" --dsn "$dsn"
docker rm -f "$container" >/dev/null

set +e
"$task_guard" >"$scratch/task-guard.log" 2>&1
task_rc=$?
MPE2E_AUTH_WEB_MODE=local-candidate "$auth_guard" >"$scratch/auth-local-guard.log" 2>&1
auth_local_rc=$?
MPE2E_AUTH_WEB_MODE=production "$auth_guard" >"$scratch/auth-production-guard.log" 2>&1
auth_production_rc=$?
set -e
test "$task_rc" -eq 3
test "$auth_local_rc" -eq 20
test "$auth_production_rc" -eq 20

test "$(sha "$bundle/acceptance-fragments/MPE2E-AUTH-WEB/acceptance-contract.md")" = "a0feedc825fff609f3cd72cbe7a0705ee0f0276fa18209a7f6192d4393984fdc"
test "$(sha "$task_contract")" = "35143a0fb22218ebdcf969ee3a137431c37f21f90781db15572909e1dba0ca8b"
test "$(sha "$task_guard")" = "dee8b55304a60b4284462310f68f03099369af15071efc2fe5f39dcc8f67b73d"
test "$(sha "$baseline/.manifest.sha256")" = "bca0dac2e657d0d1fd939c87645ad278fb6e9a049ac18429c11e714b5684e49b"
test "$(sha "$candidate/.candidate-source.sha256")" = "9519c707bb842bea97e46eb770300417467c10fc5f5c8ce6916182e1f7600018"
(cd "$candidate" && shasum -a 256 -c .candidate-source.sha256 >/dev/null)
assert_no_candidate_residue
echo "C4 backend candidate validation passed; baseline persistent/transient counts 550/236; production receipt gates remain red 3/20/20"
