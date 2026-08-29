#!/usr/bin/env bash
set -euo pipefail

root="/Users/vsiyo/Desktop/创业项目/自媒体创作Agent"
bundle="$root/agents-results/2026-08-13/media-production-e2e-closure"
candidate="$root/.codex-work/merge-candidate-v4"
frontend="$candidate/frontend"
backend="$candidate/backend"
contract="$bundle/contracts/material-parsing-coverage-v1.json"
protected_auth="$root/scripts/acceptance/test-mpe2e-auth-web.sh"
protected_task="$root/scripts/acceptance/test-mpe2e-task-run-v3.sh"
container="mpe2e-candidate-r3-pg-$$"
scratch="$(mktemp -d /tmp/mpe2e-candidate-r3.XXXXXX)"

sha() {
  sha256sum "$1" | awk '{print $1}'
}

cleanup() {
  docker rm -f "$container" >/dev/null 2>&1 || true
  find "$scratch" -depth -delete >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

test "$(sha "$frontend/.candidate-source.sha256")" = "420b4ac3c9a064a21c2511d3b71750bedc3fed1b5a2f85ace236d5930cefccb0"
test "$(sha "$backend/.candidate-source.sha256")" = "a5e34064d554fe6a11b93f608b23202e737b40eac9dcedc4388c18dc952710be"
test "$(wc -l < "$frontend/.candidate-source.sha256" | tr -d ' ')" = "200"
test "$(wc -l < "$backend/.candidate-source.sha256" | tr -d ' ')" = "609"

(
  cd "$frontend"
  find . \
    \( -path './node_modules' -o -path './dist*' -o -path './.vite' -o -path '*/__pycache__' \) -prune -o \
    -type f ! -name '*.pyc' ! -name '*.log' ! -name '.DS_Store' \
    ! -name '.candidate-source.sha256' ! -name '.merge-provenance.json' -print \
    | LC_ALL=C sort \
    | while IFS= read -r rel; do sha256sum "$rel"; done
) > "$scratch/frontend.sha256"
(
  cd "$backend"
  find . \
    \( -path './.venv' -o -path '*/__pycache__' -o -path './.pytest_cache' -o -path './.mypy_cache' -o \
       -path './.ruff_cache' -o -path './.cache' -o -path './.playwright-browsers' \) -prune -o \
    -type f ! -name '*.pyc' ! -name '*.log' ! -name '.DS_Store' \
    ! -name '.candidate-source.sha256' ! -name '.merge-provenance.json' -print \
    | LC_ALL=C sort \
    | while IFS= read -r rel; do sha256sum "$rel"; done
) > "$scratch/backend.sha256"
cmp "$scratch/frontend.sha256" "$frontend/.candidate-source.sha256"
cmp "$scratch/backend.sha256" "$backend/.candidate-source.sha256"
(cd "$frontend" && sha256sum -c .candidate-source.sha256 >/dev/null)
(cd "$backend" && sha256sum -c .candidate-source.sha256 >/dev/null)

test "$(sha "$contract")" = "24452e8b621fa3a797b7efba6c03a48aad86f3436193fbef38794bcf4de54f56"
cmp "$contract" "$frontend/contracts/material-parsing-coverage-v1.json"
cmp "$contract" "$backend/contracts/material-parsing-coverage-v1.json"
jq -e '
  .contractId == "media-material-parsing-coverage-v1"
  and (.platforms | length) == 9
  and (.materialTypes | length) == 6
  and (.coverage | length) == 54
  and ((.coverage | map(.platform + ":" + .materialType) | unique | length) == 54)
  and .completionStatuses == ["completed_auto", "completed_manual"]
' "$contract" >/dev/null

jq -e '
  .schemaVersion == "openclaw-media-unique-candidate-v1"
  and .candidateId == "media-production-e2e-v4"
  and .productionState == "not_deployed"
  and .components.frontend.sourceManifestSha256 == "420b4ac3c9a064a21c2511d3b71750bedc3fed1b5a2f85ace236d5930cefccb0"
  and .components.frontend.managedFileCount == 200
  and .components.backend.sourceManifestSha256 == "a5e34064d554fe6a11b93f608b23202e737b40eac9dcedc4388c18dc952710be"
  and .components.backend.managedFileCount == 609
  and .accountWorkspaceGate.sourceManifestSha256 == "a5e34064d554fe6a11b93f608b23202e737b40eac9dcedc4388c18dc952710be"
  and .accountWorkspaceGate.sourceFileCount == 609
  and .accountWorkspaceGate.canonicalMigrationCount == 34
  and .accountWorkspaceGate.nonDatabaseResult == "109 passed, 16 skipped, 16 subtests passed"
  and .accountWorkspaceGate.postgresqlResult == "35 passed"
  and .accountWorkspaceGate.authReceiptGateExitCode == 20
  and .accountWorkspaceGate.taskReceiptGateExitCode == 3
  and .accountWorkspaceGate.productionAccepted == false
  and .materialParsing.coverageCount == 54
  and .materialParsing.productionAccepted == false
  and .boundaries.remoteProductionTouched == false
  and .boundaries.productionDatabaseTouched == false
  and .boundaries.feishuTouched == false
  and .boundaries.realQaAccepted == false
' "$candidate/candidate-manifest.json" >/dev/null
(cd "$candidate" && sha256sum -c candidate-manifest.sha256 >/dev/null)

test "$(sha "$protected_auth")" = "8bf6f33d0917948821f7a6ffbbd3e5f505002fb19d77c4f1d24b9c3261e6ab2e"
test "$(sha "$protected_task")" = "dee8b55304a60b4284462310f68f03099369af15071efc2fe5f39dcc8f67b73d"

PATH="$backend/.venv/bin:$PATH" \
  MPE2E_AUTH_WORKSPACE_CANDIDATE_ROOT="$candidate" \
  "$root/scripts/acceptance/test-mpe2e-auth-workspace-source.sh"

(cd "$frontend" && npm run qa:task-launch && npm run qa:material-parsing)
(cd "$backend" && ./.venv/bin/python -m pytest -q \
  tests/test_account_auth.py \
  tests/test_account_identity_workspace.py \
  tests/test_account_workspace_fail_closed.py \
  tests/test_media_web_tasks.py \
  tests/test_media_task_v3_contract.py \
  tests/test_media_web_tasks_postgres.py \
  tests/test_http_api.py \
  tests/test_media_business_http.py \
  tests/test_postgres_migration_runner.py)

docker run -d --rm \
  --name "$container" \
  -e POSTGRES_HOST_AUTH_METHOD=trust \
  -p 127.0.0.1::5432 \
  postgres:16 >/dev/null
for _ in $(seq 1 60); do
  if docker exec "$container" pg_isready -U postgres >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
docker exec "$container" pg_isready -U postgres >/dev/null
pg_port="$(docker port "$container" 5432/tcp | awk -F: 'NR == 1 {print $NF}')"
test -n "$pg_port"
dsn="postgresql://postgres@127.0.0.1:${pg_port}/postgres"

(cd "$backend" && \
  ./.venv/bin/python scripts/run_postgres_migrations.py apply --source-root "$backend" --dsn "$dsn" --mode empty && \
  OPENCLAW_C2_TEST_DATABASE_URL="$dsn" \
  OPENCLAW_ACCOUNT_IDENTITY_TEST_DATABASE_URL="$dsn" \
  ./.venv/bin/python -m pytest -q \
    tests/test_media_task_repository_postgres.py \
    tests/test_media_web_tasks_postgres.py \
    tests/test_account_identity_postgres.py && \
  ./.venv/bin/python scripts/run_postgres_migrations.py verify --source-root "$backend" --dsn "$dsn")

set +e
MPE2E_AUTH_WEB_MODE=local-candidate "$protected_auth" >/dev/null 2>&1
auth_rc=$?
"$protected_task" >/dev/null 2>&1
task_rc=$?
set -e
test "$auth_rc" -eq 20
test "$task_rc" -eq 3

echo "C5 unique candidate R3 validation passed: $(sha "$candidate/candidate-manifest.json")"
