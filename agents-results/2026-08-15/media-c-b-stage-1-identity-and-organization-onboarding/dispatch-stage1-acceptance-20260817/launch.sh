#!/usr/bin/env bash
set -euo pipefail

project_root=/Users/vsiyo/Desktop/创业项目/自媒体创作Agent
dispatch_root="$project_root/agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/dispatch-stage1-acceptance-20260817"
supervisor=/Users/vsiyo/.codex/skills/codex-explicit-worker-orchestration/scripts/run_lw_luna_with_l3_escalation.py
luna=/Users/vsiyo/.codex/workers/run-lw-luna.sh
l3=/Users/vsiyo/.codex/workers/run-l3.sh
task_ids=(P3-ADMIN-OWNER P5-RESOURCE-INIT P6-PROVISION-ORCHESTRATOR P7-PROVISION-RECOVERY P8-DEPROVISION)
pids=()

: > "$dispatch_root/processes.tsv"
for task_id in "${task_ids[@]}"; do
  python3 "$supervisor" \
    --task-id "stage1-$task_id-20260817" \
    --task-file "$dispatch_root/tasks/$task_id.txt" \
    --artifact-dir "$dispatch_root/artifacts/$task_id" \
    --project-root "$project_root" \
    --validation-command-file "$dispatch_root/validation/$task_id.sh" \
    --luna-wrapper "$luna" \
    --l3-wrapper "$l3" \
    --timeout-seconds 1800 \
    > "$dispatch_root/artifacts-$task_id.outer.log" 2>&1 &
  pid=$!
  pids+=("$pid")
  printf '%s\t%s\t%s\n' "$task_id" "$pid" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$dispatch_root/processes.tsv"
done

: > "$dispatch_root/exits.tsv"
for index in "${!task_ids[@]}"; do
  task_id=${task_ids[$index]}
  pid=${pids[$index]}
  if wait "$pid"; then
    exit_code=0
  else
    exit_code=$?
  fi
  printf '%s\t%s\t%s\t%s\n' "$task_id" "$pid" "$exit_code" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$dispatch_root/exits.tsv"
done
