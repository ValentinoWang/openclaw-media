#!/usr/bin/env bash
# shellcheck disable=SC2016 # jq programs use variables supplied through --arg/--argjson.
set -euo pipefail

root="/Users/vsiyo/Desktop/创业项目/自媒体创作Agent"
wave="$root/agents-results/2026-08-13/media-production-e2e-closure/execution-wave-15"
supervisor="/Users/vsiyo/Desktop/Opensource_Tool/Harness_Engineering/Core/skills/codex-explicit-worker-orchestration/scripts/run_lw_luna_with_l3_escalation.py"
luna="/Users/vsiyo/.codex/workers/run-lw-luna.sh"
l3="/Users/vsiyo/.codex/workers/run-l3.sh"
run_id="$(date -u +%Y%m%dT%H%M%SZ)-$$"
launch_dir="$wave/launch-ledgers"
supervisor_log_dir="$wave/supervisor-logs"
ledger="$launch_dir/$run_id.ndjson"

mkdir -p "$launch_dir" "$supervisor_log_dir"

append_ledger() {
  jq -nc "$@" >>"$ledger"
}

test "$(shasum -a 256 "$luna" | awk '{print $1}')" = "a88abe5cdbb376cb1d9e37706f202f60c48292c3ed337b1e31c1820720b1742c"
test "$(shasum -a 256 "$l3" | awk '{print $1}')" = "67b6c79390710c106431e22cb542b346737d60dd0338e8f7c2f14e2fc73268df"
test "$(shasum -a 256 "$supervisor" | awk '{print $1}')" = "1cc6b73fdb63c9f3a330d33a9e2bebab9bfb46db6635208cbebda083301ad7e0"

c3_task="$wave/C3-FRONTEND-VERIFY-R4/tasks/C3-FRONTEND-VERIFY-R4.md"
c3_validation="$wave/C3-FRONTEND-VERIFY-R4/validation/C3-FRONTEND-VERIFY-R4.sh"
c3_artifact="$wave/C3-FRONTEND-VERIFY-R4"
c3_supervisor_log="$supervisor_log_dir/$run_id-C3-FRONTEND-VERIFY-R4.log"

c4_task="$wave/C4-BACKEND-VERIFY-R4/tasks/C4-BACKEND-VERIFY-R4.md"
c4_validation="$wave/C4-BACKEND-VERIFY-R4/validation/C4-BACKEND-VERIFY-R4.sh"
c4_artifact="$wave/C4-BACKEND-VERIFY-R4"
c4_supervisor_log="$supervisor_log_dir/$run_id-C4-BACKEND-VERIFY-R4.log"

test "$(shasum -a 256 "$c3_task" | awk '{print $1}')" = "e7997825dd6de960b1dbe2dd28d25be9f3f38e0983a41ec4204b7ce37dead712"
test "$(shasum -a 256 "$c3_validation" | awk '{print $1}')" = "a0f8e239f3d0509e868ed5ed6cdff04d5f5775594ba31192c18d50fc7e934d76"
test "$(shasum -a 256 "$c4_task" | awk '{print $1}')" = "1fafaf9bdb64dbc95a837b8450afa1ad2f68a93a56384917e72a15bbb92608bb"
test "$(shasum -a 256 "$c4_validation" | awk '{print $1}')" = "02b2e5bc2e8cc0a9e3e6561773054e3d2c85af0411a4ac84a16eb5a5ccbb8c67"

c3_started="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
python3 "$supervisor" \
  --task-id C3-FRONTEND-VERIFY-R4 \
  --task-file "$c3_task" \
  --artifact-dir "$c3_artifact" \
  --project-root "$root" \
  --validation-command-file "$c3_validation" \
  --luna-wrapper "$luna" \
  --l3-wrapper "$l3" \
  --timeout-seconds 2400 \
  >"$c3_supervisor_log" 2>&1 &
c3_pid=$!

c4_started="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
python3 "$supervisor" \
  --task-id C4-BACKEND-VERIFY-R4 \
  --task-file "$c4_task" \
  --artifact-dir "$c4_artifact" \
  --project-root "$root" \
  --validation-command-file "$c4_validation" \
  --luna-wrapper "$luna" \
  --l3-wrapper "$l3" \
  --timeout-seconds 2400 \
  >"$c4_supervisor_log" 2>&1 &
c4_pid=$!

append_ledger \
  --arg event "started" --arg task "C3-FRONTEND-VERIFY-R4" --argjson pid "$c3_pid" \
  --arg started_at "$c3_started" --arg log "$c3_supervisor_log" \
  '{event:$event,task_id:$task,supervisor_pid:$pid,started_at:$started_at,supervisor_log:$log}'
append_ledger \
  --arg event "started" --arg task "C4-BACKEND-VERIFY-R4" --argjson pid "$c4_pid" \
  --arg started_at "$c4_started" --arg log "$c4_supervisor_log" \
  '{event:$event,task_id:$task,supervisor_pid:$pid,started_at:$started_at,supervisor_log:$log}'
append_ledger \
  --arg event "all_started_before_first_wait" --arg observed_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --argjson c3_pid "$c3_pid" --argjson c4_pid "$c4_pid" \
  '{event:$event,observed_at:$observed_at,supervisor_pids:[$c3_pid,$c4_pid]}'

status=0
if wait "$c3_pid"; then c3_rc=0; else c3_rc=$?; status=1; fi
c3_ended="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
append_ledger \
  --arg event "finished" --arg task "C3-FRONTEND-VERIFY-R4" --argjson pid "$c3_pid" \
  --arg ended_at "$c3_ended" --argjson exit_code "$c3_rc" \
  '{event:$event,task_id:$task,supervisor_pid:$pid,ended_at:$ended_at,exit_code:$exit_code}'

if wait "$c4_pid"; then c4_rc=0; else c4_rc=$?; status=1; fi
c4_ended="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
append_ledger \
  --arg event "finished" --arg task "C4-BACKEND-VERIFY-R4" --argjson pid "$c4_pid" \
  --arg ended_at "$c4_ended" --argjson exit_code "$c4_rc" \
  '{event:$event,task_id:$task,supervisor_pid:$pid,ended_at:$ended_at,exit_code:$exit_code}'

printf 'launch_ledger=%s\n' "$ledger"
printf 'C3-FRONTEND-VERIFY-R4 supervisor_pid=%s exit=%s\n' "$c3_pid" "$c3_rc"
printf 'C4-BACKEND-VERIFY-R4 supervisor_pid=%s exit=%s\n' "$c4_pid" "$c4_rc"
exit "$status"
