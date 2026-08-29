#!/usr/bin/env bash
set -euo pipefail

readonly ROOT="/Users/vsiyo/Desktop/创业项目/自媒体创作Agent"
readonly CANDIDATE_ROOT="$ROOT/.codex-work/merge-candidate-v4"
readonly FRONTEND_ROOT="$CANDIDATE_ROOT/frontend"
readonly RUNS_ROOT="$ROOT/agents-results/2026-08-13/media-production-e2e-closure/acceptance-fragments/MPE2E-AUTH-WEB/acceptance/machine/e2e/runs"
readonly CONTRACT="$ROOT/agents-results/2026-08-13/media-production-e2e-closure/acceptance-fragments/MPE2E-AUTH-WEB/acceptance-contract.md"
readonly C5_VALIDATION="$ROOT/agents-results/2026-08-13/media-production-e2e-closure/execution-wave-23/C5-UNIQUE-CANDIDATE-R3/validation/C5-UNIQUE-CANDIDATE-R3.sh"
readonly PROTECTED_RECEIPT_GATE="$ROOT/scripts/acceptance/test-mpe2e-auth-web.sh"
readonly PROTECTED_SOURCE_GATE="$ROOT/scripts/acceptance/test-mpe2e-auth-workspace-source.sh"
readonly CANDIDATE_MANIFEST_SHA256="f1ac786573e76aa40a0d69a10aab6dba5bd6a345596242d93f37773b59f45bcb"
readonly CONTRACT_SHA256="f6978ce556758613eba0e20e4bf42159c04a96531ff2cb806327fcab9aedb5c9"
readonly C5_VALIDATION_SHA256="6b51e3d8f70a4d69ceb2fcc9da2f230666895ec01dd9d3df7b4f3b2856efc8d0"
readonly PROTECTED_RECEIPT_GATE_SHA256="8bf6f33d0917948821f7a6ffbbd3e5f505002fb19d77c4f1d24b9c3261e6ab2e"
readonly PROTECTED_SOURCE_GATE_SHA256="4e73a4b346095d2e9eea998c07562fb8066835dec644211f33afa6998a51430e"

fail_closed() {
  printf 'C1_AUTH_LOCAL_CANDIDATE_RUNNER_FAIL reason=%s\n' "$1" >&2
  exit 1
}

sha256_file() {
  shasum -a 256 "$1" | awk '{print $1}'
}

require_file_hash() {
  local path="$1"
  local expected="$2"
  [[ -f "$path" ]] || fail_closed "required_file_missing"
  [[ "$(sha256_file "$path")" == "$expected" ]] || fail_closed "frozen_hash_mismatch"
}

[[ $# -eq 1 ]] || fail_closed "exactly_one_run_directory_required"
run_dir="$1"
[[ "$run_dir" == /* ]] || fail_closed "absolute_run_directory_required"
[[ -d "$run_dir" ]] || fail_closed "run_directory_missing"
[[ -d "$run_dir/evidence" ]] || fail_closed "run_evidence_directory_missing"

run_dir="$(cd "$run_dir" && pwd -P)"
case "$run_dir" in
  "$RUNS_ROOT"/*) ;;
  *) fail_closed "run_directory_outside_mpe2e_auth_e2e_runs" ;;
esac
run_leaf="${run_dir#"$RUNS_ROOT/"}"
[[ -n "$run_leaf" && "$run_leaf" != */* ]] || fail_closed "run_directory_must_be_direct_child"

command -v shasum >/dev/null 2>&1 || fail_closed "shasum_unavailable"
command -v awk >/dev/null 2>&1 || fail_closed "awk_unavailable"
command -v curl >/dev/null 2>&1 || fail_closed "curl_unavailable"
command -v jq >/dev/null 2>&1 || fail_closed "jq_unavailable"
command -v node >/dev/null 2>&1 || fail_closed "node_unavailable"
[[ -x "$FRONTEND_ROOT/node_modules/.bin/vite" ]] || fail_closed "candidate_vite_unavailable"

require_file_hash "$CANDIDATE_ROOT/candidate-manifest.json" "$CANDIDATE_MANIFEST_SHA256"
require_file_hash "$CONTRACT" "$CONTRACT_SHA256"
require_file_hash "$C5_VALIDATION" "$C5_VALIDATION_SHA256"
require_file_hash "$PROTECTED_RECEIPT_GATE" "$PROTECTED_RECEIPT_GATE_SHA256"
require_file_hash "$PROTECTED_SOURCE_GATE" "$PROTECTED_SOURCE_GATE_SHA256"

evidence_dir="$run_dir/evidence"
backend_validation_log="$evidence_dir/backend-validation.log"
server_log="$evidence_dir/vite-server.log"
browser_log="$evidence_dir/browser-run.log"
receipt_gate_log="$evidence_dir/receipt-gate.log"
summary_file="$evidence_dir/browser-summary.json"
receipt_file="$evidence_dir/auth-web-local-candidate-receipt.json"
manifest_file="$evidence_dir/evidence-manifest.sha256"

"$C5_VALIDATION" >"$backend_validation_log" 2>&1 || fail_closed "c5_validation_failed"

local_port="${MPE2E_AUTH_WEB_LOCAL_PORT:-5189}"
[[ "$local_port" =~ ^[0-9]+$ ]] || fail_closed "invalid_local_port"
(( local_port >= 1 && local_port <= 65535 )) || fail_closed "invalid_local_port"

server_pid=""
cleanup() {
  if [[ -n "$server_pid" ]] && kill -0 "$server_pid" >/dev/null 2>&1; then
    kill "$server_pid" >/dev/null 2>&1 || true
    wait "$server_pid" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT
trap 'exit 143' INT TERM

(
  cd "$FRONTEND_ROOT"
  exec "$FRONTEND_ROOT/node_modules/.bin/vite" --host 127.0.0.1 --port "$local_port" --strictPort
) >"$server_log" 2>&1 &
server_pid=$!

base_url="http://127.0.0.1:$local_port"
server_ready=0
for _ in $(seq 1 80); do
  if curl --silent --fail --max-time 2 "$base_url/media.login.html" -o /dev/null 2>/dev/null; then
    server_ready=1
    break
  fi
  if ! kill -0 "$server_pid" >/dev/null 2>&1; then
    break
  fi
  sleep 0.25
done
(( server_ready == 1 )) || fail_closed "vite_server_not_ready"

MPE2E_AUTH_WEB_BASE_URL="$base_url" \
MPE2E_AUTH_WEB_CANDIDATE_ROOT="$CANDIDATE_ROOT" \
MPE2E_AUTH_WEB_EVIDENCE_DIR="$evidence_dir" \
MPE2E_AUTH_WEB_BACKEND_VALIDATED=1 \
MPE2E_AUTH_WEB_BACKEND_VALIDATION_LOG="$backend_validation_log" \
node "$ROOT/agents-results/2026-08-13/media-production-e2e-closure/execution-wave-24/C1-AUTH-LOCAL-CANDIDATE-R1/runner/runMediaAuthLocalCandidate.mjs" \
  "$base_url" "$evidence_dir" "$CANDIDATE_ROOT" >"$browser_log" 2>&1 || fail_closed "browser_runner_failed"

jq -e '
  type == "object"
  and .status == "PASS"
  and .browser == "chromium"
  and .viewports.desktop.width == 1440
  and .viewports.desktop.height == 1000
  and .viewports.mobile.width == 390
  and .viewports.mobile.height == 844
  and .console_error_count == 0
  and .page_error_count == 0
  and .horizontal_overflow == false
  and (.screenshots | length) == 4
  and all(.screenshots[]; .status == "pass")
' "$summary_file" >/dev/null || fail_closed "browser_summary_contract_failed"

for screenshot in \
  login-desktop-feishu-qr.png \
  login-desktop-account.png \
  login-mobile-feishu-qr.png \
  login-mobile-account.png; do
  [[ -s "$evidence_dir/$screenshot" ]] || fail_closed "required_screenshot_missing"
done

jq -e '
  type == "object"
  and .schema_version == 3
  and .contract_version == 3
  and .evidence_level == "local-candidate"
  and .mock_or_fixture == true
  and .evidence_boundary.production_claim == false
  and .evidence_boundary.real_qa == false
  and .evidence_boundary.promotable_to_production == false
' "$receipt_file" >/dev/null || fail_closed "local_candidate_receipt_contract_failed"

MPE2E_AUTH_WEB_MODE=local-candidate \
MPE2E_AUTH_WEB_SAFE_METADATA_FILE="$receipt_file" \
  "$PROTECTED_RECEIPT_GATE" >"$receipt_gate_log" 2>&1 || fail_closed "protected_receipt_gate_failed"

(
  cd "$evidence_dir"
  find . -type f ! -name 'evidence-manifest.sha256' -print \
    | LC_ALL=C sort \
    | while IFS= read -r relative_path; do
        relative_path="${relative_path#./}"
        printf '%s  %s\n' "$(sha256_file "$relative_path")" "$relative_path"
      done
) >"$manifest_file"

printf 'C1_AUTH_LOCAL_CANDIDATE_RUNNER_PASS\n'
