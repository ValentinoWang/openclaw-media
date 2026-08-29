#!/usr/bin/env bash
set -euo pipefail

project_root="/Users/vsiyo/Desktop/创业项目/自媒体创作Agent"
dispatch_root="$project_root/agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/dispatch-stage1-lw"
supervisor="/Users/vsiyo/.codex/skills/codex-explicit-worker-orchestration/scripts/run_lw_luna_with_l3_escalation.py"
luna="/Users/vsiyo/.codex/workers/run-lw-luna.sh"
l3="/Users/vsiyo/.codex/workers/run-l3.sh"
wave_ledger="$dispatch_root/wave-lw-20260817.tsv"

python3 "$supervisor" \
  --task-id stage1-P2-candidate-lw-20260817 \
  --task-file "$dispatch_root/tasks/P2-candidate.txt" \
  --artifact-dir "$dispatch_root/artifacts-P2-candidate" \
  --project-root "$project_root/.codex-work/stage1-lw-P2-candidate" \
  --validation-command-file "$dispatch_root/validation/P2-candidate.sh" \
  --luna-wrapper "$luna" \
  --l3-wrapper "$l3" \
  --timeout-seconds 1200 \
  > "$dispatch_root/P2-candidate.supervisor.log" 2>&1 &
p2_pid=$!

python3 "$supervisor" \
  --task-id stage1-OAS-document-lw-20260817 \
  --task-file "$dispatch_root/tasks/OAS-document.txt" \
  --artifact-dir "$dispatch_root/artifacts-OAS-document" \
  --project-root "$project_root/.codex-work/stage1-lw-OAS-document" \
  --validation-command-file "$dispatch_root/validation/OAS-document.sh" \
  --luna-wrapper "$luna" \
  --l3-wrapper "$l3" \
  --timeout-seconds 1200 \
  > "$dispatch_root/OAS-document.supervisor.log" 2>&1 &
oas_pid=$!

python3 "$supervisor" \
  --task-id stage1-P3-map-lw-20260817 \
  --task-file "$dispatch_root/tasks/P3-map.txt" \
  --artifact-dir "$dispatch_root/artifacts-P3-map" \
  --project-root "$project_root/.codex-work/stage1-lw-P3-map" \
  --validation-command-file "$dispatch_root/validation/P3-map.sh" \
  --luna-wrapper "$luna" \
  --l3-wrapper "$l3" \
  --timeout-seconds 1200 \
  > "$dispatch_root/P3-map.supervisor.log" 2>&1 &
p3_pid=$!

printf 'task_id\tsupervisor_pid\tproject_root\n' > "$wave_ledger"
printf 'stage1-P2-candidate-lw-20260817\t%s\t%s\n' "$p2_pid" "$project_root/.codex-work/stage1-lw-P2-candidate" >> "$wave_ledger"
printf 'stage1-OAS-document-lw-20260817\t%s\t%s\n' "$oas_pid" "$project_root/.codex-work/stage1-lw-OAS-document" >> "$wave_ledger"
printf 'stage1-P3-map-lw-20260817\t%s\t%s\n' "$p3_pid" "$project_root/.codex-work/stage1-lw-P3-map" >> "$wave_ledger"

set +e
wait "$p2_pid"
p2_rc=$?
wait "$oas_pid"
oas_rc=$?
wait "$p3_pid"
p3_rc=$?
set -e

printf 'stage1-P2-candidate-lw-20260817\t%s\n' "$p2_rc" > "$dispatch_root/wave-lw-20260817-results.tsv"
printf 'stage1-OAS-document-lw-20260817\t%s\n' "$oas_rc" >> "$dispatch_root/wave-lw-20260817-results.tsv"
printf 'stage1-P3-map-lw-20260817\t%s\n' "$p3_rc" >> "$dispatch_root/wave-lw-20260817-results.tsv"

if (( p2_rc != 0 || oas_rc != 0 || p3_rc != 0 )); then
  exit 20
fi
