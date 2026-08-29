#!/usr/bin/env bash
set -euo pipefail

root="/Users/vsiyo/Desktop/创业项目/自媒体创作Agent"
bundle="$root/agents-results/2026-08-13/media-production-e2e-closure"
image_wave="$bundle/execution-wave-14"
baseline="$root/.codex-work/production-baseline-20260814T084319Z/backend"
candidate="$root/.codex-work/merge-candidate-v4/backend"
c2_manifest="$bundle/execution-wave-10/C2-V3-FINDINGS-REPAIR/baseline/postrepair-source.sha256"
task_contract="$bundle/acceptance-fragments/MPE2E-TASK-RUN-V3/acceptance-contract.md"
task_guard="$root/scripts/acceptance/test-mpe2e-task-run-v3.sh"
auth_guard="$root/scripts/acceptance/test-mpe2e-auth-web.sh"
image="sha256:edb4dc9c110bb4b0303d7e85d2f3e73e9dd1a777282c10c73fc664c6d6557db3"
network="c4-backend-verify-r4-net-$$"
postgres_container="c4-backend-verify-r4-pg-$$"
verify_container="c4-backend-verify-r4-runner-$$"
scratch=""

sha() { shasum -a 256 "$1" | awk '{print $1}'; }

cleanup() {
  docker rm -f "$verify_container" >/dev/null 2>&1 || true
  docker rm -f "$postgres_container" >/dev/null 2>&1 || true
  docker network rm "$network" >/dev/null 2>&1 || true
  if [ -n "$scratch" ] && [ -d "$scratch" ]; then
    case "$scratch" in
      /tmp/c4-backend-verify-r4.*) rm -rf -- "$scratch" ;;
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
test "$(sha "$image_wave/image/Dockerfile")" = "b1b7ea34b23463f79bed155c30e112f440d908baa8eb1c768522b26b3baf952d"
test "$(sha "$image_wave/image/build-receipt.json")" = "d8741b8c05a0ee5b36cb4fc8f748eccb3225e535d84180168335f8f1749cae2a"

scratch="$(mktemp -d /tmp/c4-backend-verify-r4.XXXXXX)"
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

if find "$candidate" -type l -print -quit | grep -q .; then
  echo "candidate must not contain symlinks" >&2
  exit 1
fi
assert_no_candidate_residue
(cd "$candidate" && shasum -a 256 -c .candidate-source.sha256 >/dev/null)

image_json="$(docker image inspect "$image")"
test "$(jq -r '.[0].Id' <<<"$image_json")" = "$image"
test "$(jq -r '.[0].Architecture' <<<"$image_json")" = "arm64"
test "$(jq -r '.[0].Os' <<<"$image_json")" = "linux"
jq -e --arg expected "sha256:824f1a789072e648c62541c2cfa4479c4061a290d5c27766d67dc1dcbc19b321" \
  '.[0].Config.Labels["org.opencontainers.image.base.digest"] == $expected' <<<"$image_json" >/dev/null
jq -e --arg expected "f3dd4e9e3671ff2d774938b96bfacf083bdfaad454ee19d8effc9d5b96541dd7" \
  '.[0].Config.Labels["media.verify.frontend-lock.sha256"] == $expected' <<<"$image_json" >/dev/null

backend_copy="$scratch/backend"
fixture="$scratch/openclaw_bots.json"
external_modules="$scratch/openclaw-feishu-reminder"
mkdir -p "$backend_copy" "$external_modules"
cp -a "$candidate/." "$backend_copy/"
: > "$external_modules/reminder.py"
: > "$external_modules/setup_media_bitable_registry.py"
chmod 0444 "$external_modules/reminder.py" "$external_modules/setup_media_bitable_registry.py"

jq -n '
  {
    defaults: {
      bin: "/usr/bin/false",
      agent: "knowledge",
      timeout: 1,
      cwd: "/tmp",
      codex_home: "/tmp/codex"
    },
    model_tiers: {
      qa: {model: "qa-model", reasoning: "off"}
    },
    bots: {
      knowledge: {provider: "qa", model_tier: "qa"}
    },
    profiles: {
      knowledge_delegate: {bot: "knowledge", provider: "qa", model_tier: "qa"},
      media_creation: {bot: "knowledge", provider: "qa", model_tier: "qa"},
      media_analysis: {bot: "knowledge", provider: "qa", model_tier: "qa"},
      content_cleaner: {
        bot: "knowledge",
        provider: "qa",
        model_tier: "qa",
        enabled: false,
        max_chars: 20000,
        max_tokens: 8192
      }
    },
    providers: {
      qa: {
        base_url: "http://127.0.0.1:9",
        api_key: "qa-no-secret",
        api_type: "openai_chat_completions",
        timeout: 1,
        default_model_tier: "qa"
      }
    }
  }
' > "$fixture"
chmod 0444 "$fixture"
test "$(jq -r '.bots | keys | join(",")' "$fixture")" = "knowledge"
test "$(jq -r '.profiles | keys | sort | join(",")' "$fixture")" = "content_cleaner,knowledge_delegate,media_analysis,media_creation"
test "$(jq -r '.providers.qa.base_url' "$fixture")" = "http://127.0.0.1:9"
test "$(jq -r '.profiles.content_cleaner.enabled' "$fixture")" = "false"
test ! -s "$external_modules/reminder.py"
test ! -s "$external_modules/setup_media_bitable_registry.py"

docker network create --internal "$network" >/dev/null
test "$(docker network inspect "$network" --format '{{.Internal}}')" = "true"
docker run -d --rm \
  --name "$postgres_container" \
  --network "$network" \
  --network-alias postgres \
  -e POSTGRES_USER=c4qa \
  -e POSTGRES_PASSWORD=c4qa-local-only \
  -e POSTGRES_DB=c4qa \
  postgres:16 >/dev/null

ready=0
for _ in $(seq 1 60); do
  if docker exec "$postgres_container" pg_isready -U c4qa -d c4qa >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 1
done
test "$ready" = "1"

docker run --rm \
  --name "$verify_container" \
  --network "$network" \
  -e PYTHONDONTWRITEBYTECODE=1 \
  -e PYTHONPATH=/work/backend \
  -e C4_DATABASE_URL=postgresql://c4qa:c4qa-local-only@postgres:5432/c4qa \
  -v "$backend_copy:/work/backend" \
  -v "$fixture:/home/ubuntu/selfmedia-tools/config/openclaw_bots.json:ro" \
  -v "$external_modules:/home/ubuntu/openclaw-feishu-reminder:ro" \
  -v "$root:/project:ro" \
  -w /work/backend \
  "$image" \
  bash -lc '
    set -euo pipefail
    python=/opt/c4-venv/bin/python
    "$python" - <<"PY"
import bcrypt
import cryptography
import playwright
import psycopg
import pytest
import requests
import yaml
assert pytest.__version__ == "8.4.1"
assert psycopg.__version__ == "3.2.9"
assert bcrypt.__version__ == "4.3.0"
assert cryptography.__version__ == "45.0.5"
assert requests.__version__ == "2.32.5"
assert yaml.__version__ == "6.0.3"
PY
    test "$(jq -r .providers.qa.base_url /home/ubuntu/selfmedia-tools/config/openclaw_bots.json)" = "http://127.0.0.1:9"
    test ! -s /home/ubuntu/openclaw-feishu-reminder/reminder.py
    test ! -s /home/ubuntu/openclaw-feishu-reminder/setup_media_bitable_registry.py
    PYTHONPYCACHEPREFIX=/tmp/c4-pycache "$python" -m py_compile \
      openclaw_app/account/auth.py \
      openclaw_app/account/opc_login.py \
      openclaw_app/adapters/http_api.py \
      openclaw_app/services/media_task_repository.py \
      openclaw_app/services/media_task_runner.py \
      openclaw_app/services/media_web_tasks.py \
      openclaw_app/server_cli.py
    "$python" -m pytest -q -p no:cacheprovider \
      tests/test_account_auth.py \
      tests/test_http_api.py \
      tests/test_media_business_http.py \
      tests/test_media_task_v3_contract.py \
      tests/test_media_web_tasks.py \
      tests/test_media_task_runner.py \
      tests/test_postgres_migration_runner.py \
      tests/test_tenant_projection_http.py
    "$python" scripts/run_postgres_migrations.py \
      apply --source-root /work/backend --dsn "$C4_DATABASE_URL" --mode empty
    OPENCLAW_ACCOUNT_TEST_DATABASE_URL="$C4_DATABASE_URL" \
    OPENCLAW_C2_TEST_DATABASE_URL="$C4_DATABASE_URL" \
    A2B_TEST_DATABASE_URL="$C4_DATABASE_URL" \
      "$python" -m pytest -q -p no:cacheprovider \
        tests/test_account_auth.py \
        tests/test_account_registration.py \
        tests/test_account_registration_http_postgres.py \
        tests/test_media_task_repository_postgres.py \
        tests/test_media_web_tasks_postgres.py \
        tests/test_media_task_runner.py \
        tests/test_media_document_workspace_authority_migration.py
    "$python" scripts/run_postgres_migrations.py \
      verify --source-root /work/backend --dsn "$C4_DATABASE_URL"
    set +e
    /project/scripts/acceptance/test-mpe2e-task-run-v3.sh >/tmp/task-guard.log 2>&1
    task_rc=$?
    MPE2E_AUTH_WEB_MODE=local-candidate /project/scripts/acceptance/test-mpe2e-auth-web.sh >/tmp/auth-local-guard.log 2>&1
    auth_local_rc=$?
    MPE2E_AUTH_WEB_MODE=production /project/scripts/acceptance/test-mpe2e-auth-web.sh >/tmp/auth-production-guard.log 2>&1
    auth_production_rc=$?
    set -e
    cat /tmp/task-guard.log /tmp/auth-local-guard.log /tmp/auth-production-guard.log
    test "$task_rc" -eq 3
    test "$auth_local_rc" -eq 20
    test "$auth_production_rc" -eq 20
  '

docker rm -f "$postgres_container" >/dev/null
docker network rm "$network" >/dev/null

test "$(sha "$bundle/.ssot/manifest.json")" = "c6aca57fc2676e8a51704bb607c84245a0e55681bd4202270e659a8290ce9782"
test "$(sha "$task_contract")" = "35143a0fb22218ebdcf969ee3a137431c37f21f90781db15572909e1dba0ca8b"
test "$(sha "$task_guard")" = "dee8b55304a60b4284462310f68f03099369af15071efc2fe5f39dcc8f67b73d"
test "$(sha "$baseline/.manifest.sha256")" = "bca0dac2e657d0d1fd939c87645ad278fb6e9a049ac18429c11e714b5684e49b"
test "$(sha "$candidate/.candidate-source.sha256")" = "9519c707bb842bea97e46eb770300417467c10fc5f5c8ce6916182e1f7600018"
(cd "$candidate" && shasum -a 256 -c .candidate-source.sha256 >/dev/null)
assert_no_candidate_residue
echo "C4 backend candidate validation passed in frozen internal-network Linux/ARM64 image"
