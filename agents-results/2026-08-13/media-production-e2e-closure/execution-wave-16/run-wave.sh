#!/usr/bin/env bash
set -euo pipefail

root="/Users/vsiyo/Desktop/创业项目/自媒体创作Agent"
wave="$root/agents-results/2026-08-13/media-production-e2e-closure/execution-wave-16"
supervisor="/Users/vsiyo/.codex/skills/codex-explicit-worker-orchestration/scripts/run_lw_luna_with_l3_escalation.py"
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
test "$(shasum -a 256 "$root/agents-results/2026-08-13/media-production-e2e-closure/.ssot/manifest.json" | awk '{print $1}')" = "b611eae801b639e4bb674d9848a672e242496ff46c72fdbc09a2091ee52642df"
test "$(shasum -a 256 "$root/agents-results/2026-08-13/media-production-e2e-closure/.ssot/nodes/D6.json" | awk '{print $1}')" = "5343753dfd9a25af2afc10cc19b5192ef3d9aa34ea5dceacaca8578257b48117"
test "$(shasum -a 256 "$root/agents-results/2026-08-13/media-production-e2e-closure/contracts/material-parsing-coverage-v1.json" | awk '{print $1}')" = "24452e8b621fa3a797b7efba6c03a48aad86f3436193fbef38794bcf4de54f56"

c3_task="$wave/C3-MATERIAL-PARSING-FRONTEND/tasks/C3-MATERIAL-PARSING-FRONTEND.md"
c3_validation="$wave/C3-MATERIAL-PARSING-FRONTEND/validation/C3-MATERIAL-PARSING-FRONTEND.sh"
c3_artifact="$wave/C3-MATERIAL-PARSING-FRONTEND"
c3_supervisor_log="$supervisor_log_dir/$run_id-C3-MATERIAL-PARSING-FRONTEND.log"

c4_task="$wave/C4-MATERIAL-PARSING-BACKEND/tasks/C4-MATERIAL-PARSING-BACKEND.md"
c4_validation="$wave/C4-MATERIAL-PARSING-BACKEND/validation/C4-MATERIAL-PARSING-BACKEND.sh"
c4_artifact="$wave/C4-MATERIAL-PARSING-BACKEND"
c4_supervisor_log="$supervisor_log_dir/$run_id-C4-MATERIAL-PARSING-BACKEND.log"

test "$(shasum -a 256 "$c3_task" | awk '{print $1}')" = "f43f53d87e88df4cd5d2c4731b67a0d8702dd05cc98a0fad122356ef2c1450a2"
test "$(shasum -a 256 "$c3_validation" | awk '{print $1}')" = "32397d19dddb92f06c06f5f28a5b995c0060a2ea61f36db53931601a3ab4d98d"
test "$(shasum -a 256 "$c4_task" | awk '{print $1}')" = "d5f155f47ab08440f80e5e476a1692becb47fe8a22939bead0aec91377e92172"
test "$(shasum -a 256 "$c4_validation" | awk '{print $1}')" = "301e62e40c9dbc68269d5b16395ea8b1dfcf1c042eac835514591a8a30a85bb9"

c3_started="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
python3 "$supervisor" \
  --task-id C3-MATERIAL-PARSING-FRONTEND \
  --task-file "$c3_task" \
  --artifact-dir "$c3_artifact" \
  --project-root "$root" \
  --validation-command-file "$c3_validation" \
  --luna-wrapper "$luna" \
  --l3-wrapper "$l3" \
  --timeout-seconds 3000 \
  >"$c3_supervisor_log" 2>&1 &
c3_pid=$!

c4_started="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
python3 "$supervisor" \
  --task-id C4-MATERIAL-PARSING-BACKEND \
  --task-file "$c4_task" \
  --artifact-dir "$c4_artifact" \
  --project-root "$root" \
  --validation-command-file "$c4_validation" \
  --luna-wrapper "$luna" \
  --l3-wrapper "$l3" \
  --timeout-seconds 3000 \
  >"$c4_supervisor_log" 2>&1 &
c4_pid=$!

append_ledger --arg event started --arg task C3-MATERIAL-PARSING-FRONTEND --argjson pid "$c3_pid" --arg started_at "$c3_started" --arg log "$c3_supervisor_log" '{event:$event,task_id:$task,supervisor_pid:$pid,started_at:$started_at,supervisor_log:$log}'
append_ledger --arg event started --arg task C4-MATERIAL-PARSING-BACKEND --argjson pid "$c4_pid" --arg started_at "$c4_started" --arg log "$c4_supervisor_log" '{event:$event,task_id:$task,supervisor_pid:$pid,started_at:$started_at,supervisor_log:$log}'
append_ledger --arg event all_started_before_first_wait --arg observed_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" --argjson c3_pid "$c3_pid" --argjson c4_pid "$c4_pid" '{event:$event,observed_at:$observed_at,supervisor_pids:[$c3_pid,$c4_pid]}'

status=0
if wait "$c3_pid"; then c3_rc=0; else c3_rc=$?; status=1; fi
c3_ended="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
append_ledger --arg event finished --arg task C3-MATERIAL-PARSING-FRONTEND --argjson pid "$c3_pid" --arg ended_at "$c3_ended" --argjson exit_code "$c3_rc" '{event:$event,task_id:$task,supervisor_pid:$pid,ended_at:$ended_at,exit_code:$exit_code}'

if wait "$c4_pid"; then c4_rc=0; else c4_rc=$?; status=1; fi
c4_ended="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
append_ledger --arg event finished --arg task C4-MATERIAL-PARSING-BACKEND --argjson pid "$c4_pid" --arg ended_at "$c4_ended" --argjson exit_code "$c4_rc" '{event:$event,task_id:$task,supervisor_pid:$pid,ended_at:$ended_at,exit_code:$exit_code}'

printf 'launch_ledger=%s\n' "$ledger"
printf 'C3-MATERIAL-PARSING-FRONTEND supervisor_pid=%s exit=%s\n' "$c3_pid" "$c3_rc"
printf 'C4-MATERIAL-PARSING-BACKEND supervisor_pid=%s exit=%s\n' "$c4_pid" "$c4_rc"
exit "$status"
