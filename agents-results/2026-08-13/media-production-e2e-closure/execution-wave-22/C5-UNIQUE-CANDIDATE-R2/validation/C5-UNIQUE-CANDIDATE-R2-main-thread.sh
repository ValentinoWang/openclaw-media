#!/usr/bin/env bash
set -euo pipefail

root="/Users/vsiyo/Desktop/创业项目/自媒体创作Agent"
bundle="$root/agents-results/2026-08-13/media-production-e2e-closure"
wave="$bundle/execution-wave-22/C5-UNIQUE-CANDIDATE-R2"
ledger="$wave/ledger/C5-UNIQUE-CANDIDATE-R2.json"
return_file="$wave/returns/C5-UNIQUE-CANDIDATE-R2-luna.json"
result="$wave/result.md"
envelope="$wave/main-thread-acceptance-envelope.json"
candidate="$root/.codex-work/merge-candidate-v4"

sha() {
  sha256sum "$1" | awk '{print $1}'
}

test "$(sha "$wave/tasks/C5-UNIQUE-CANDIDATE-R2.md")" = "f606c0a71f6c015998bd8392acd7e407916e5698bc5ddfaeb973a78d37a477c3"
test "$(sha "$wave/validation/C5-UNIQUE-CANDIDATE-R2.sh")" = "e8ac86d051e84852a90a98818641964af5b4cbef9f0c304a341266d5057baa5e"
test "$(sha "$result")" = "b8b3272186a02fc906dddb35850fb847a2e09716720e84f8546950ac4aab3f59"
test "$(sha "$return_file")" = "f7e13e4e31cc9f4af497ebb8ec7d839abb0ce52bb73493dce9a57c178bfb9b67"
test "$(sha "$ledger")" = "fca3507493470f14170e39513282a9993d4189872c1a7f8acdc1da4a935f761c"
test "$(sha "$wave/logs/C5-UNIQUE-CANDIDATE-R2-luna.validation.log")" = "ab16f40779014180e317b1b208451ca65780b31102c5c21fec55004f8265a968"
test "$(sha "$candidate/candidate-manifest.json")" = "ef8bfb2f251b99bc0b4c262e3e82ecd9a4a4ca0406408b94b5dedae6db7072bc"
test "$(sha "$candidate/candidate-manifest.sha256")" = "3b71c29f977d2293898275635549d7ee6ba3c77abbd167d207cead2c06b36257"

jq -e '
  .task_id == "C5-UNIQUE-CANDIDATE-R2"
  and .terminal_state == "VERIFIED"
  and .final_decision == "complete"
  and (.attempts | length) == 1
  and .attempts[0].attempt_role == "luna"
  and .attempts[0].wrapper_path == "/Users/vsiyo/.codex/workers/run-lw-luna.sh"
  and .attempts[0].pid == 58546
  and .attempts[0].codex_session_identifier == "unavailable-from-wrapper-transport"
  and .attempts[0].exit_code == 0
  and .attempts[0].structured_return_state == "loaded"
  and .attempts[0].validation_exit_code == 0
  and .attempts[0].prompt_cleanup_state == "deleted"
  and (.attempts[0].frozen_input_drift | length) == 0
' "$ledger" >/dev/null

jq -e '
  .task_id == "C5-UNIQUE-CANDIDATE-R2"
  and .proposed_state == "VERIFIED"
  and .acceptance_self_check == "pass"
  and .failure_class == "none"
  and .wrapper == null
  and .pid == null
  and .session == null
  and .candidate_manifests.frontend.managed_file_count == 200
  and .candidate_manifests.frontend.sha256 == "e4b35df091184f2d51be0c5ccb675223ddc7b6fb1df6ebf366956c1ac9619580"
  and .candidate_manifests.backend.managed_file_count == 605
  and .candidate_manifests.backend.sha256 == "80612a3bd5742de73eff2ee1e5fc6b1793ab3cfd071b58e3c3de229effdaa2e6"
  and .candidate_manifests.top_level.sha256 == "ef8bfb2f251b99bc0b4c262e3e82ecd9a4a4ca0406408b94b5dedae6db7072bc"
  and .external_side_effects.remote_host_touched == false
  and .external_side_effects.production_database_touched == false
  and .external_side_effects.feishu_touched == false
  and .external_side_effects.deployment_performed == false
' "$return_file" >/dev/null

jq -e '
  .schema_version == 1
  and .task_id == "C5-UNIQUE-CANDIDATE-R2"
  and .worker_return_sha256 == "f7e13e4e31cc9f4af497ebb8ec7d839abb0ce52bb73493dce9a57c178bfb9b67"
  and .supervisor_ledger_sha256 == "fca3507493470f14170e39513282a9993d4189872c1a7f8acdc1da4a935f761c"
  and .process_identity.source == "supervisor ledger"
  and .process_identity.wrapper == "/Users/vsiyo/.codex/workers/run-lw-luna.sh"
  and .process_identity.pid == 58546
  and .process_identity.codex_session_identifier == "unavailable-from-wrapper-transport"
  and .return_identity_deviation.level == "L1"
  and .return_identity_deviation.worker_return_wrapper == null
  and .return_identity_deviation.worker_return_pid == null
  and .return_identity_deviation.worker_return_session == null
  and .acceptance_boundary.candidate_content_bound == true
  and .acceptance_boundary.remote_production_touched == false
  and .acceptance_boundary.production_database_touched == false
  and .acceptance_boundary.feishu_touched == false
  and .acceptance_boundary.real_qa_accepted == false
' "$envelope" >/dev/null

test ! -e "$wave/prompts/C5-UNIQUE-CANDIDATE-R2-luna.txt"
if ps -p 58546 >/dev/null 2>&1; then
  echo "recorded worker PID is still running" >&2
  exit 1
fi

bash "$wave/validation/C5-UNIQUE-CANDIDATE-R2.sh"
echo "C5 main-thread acceptance evidence passed: ef8bfb2f251b99bc0b4c262e3e82ecd9a4a4ca0406408b94b5dedae6db7072bc"
