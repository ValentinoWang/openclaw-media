#!/usr/bin/env bash
set -euo pipefail

project_root="/Users/vsiyo/Desktop/创业项目/自媒体创作Agent/.codex-work/openclaw-mainline-frontend/openclaw-bot-center"
wave_root="$project_root/agents-results/2026-08-31/media-visual-mainline-migration/remediation-wave"
inputs="$wave_root/inputs"
workers="$wave_root/workers"
supervisor="/Users/vsiyo/.codex/skills/codex-explicit-worker-orchestration/scripts/run_primary_with_l3_escalation.py"
primary_wrapper="/Users/vsiyo/.codex/workers/run-lw-terra.sh"
l3_wrapper="/Users/vsiyo/.codex/workers/run-l3.sh"
ledger="$wave_root/outer-process-ledger.tsv"

tasks=(auth-build workspace-runtime route-policy-shell adoption-guard stage2-tones pagination-regression)
mkdir -p "$workers"
printf 'task_id\tprimary_executor\tprimary_wrapper\tproject_root\tsandbox\tpid\tstarted_at\texited_at\texit_code\tartifact_dir\n' > "$ledger"

pids=()
for task_id in "${tasks[@]}"; do
  artifact_dir="$workers/$task_id"
  started_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  (
    exec python3 "$supervisor" \
      --task-id "$task_id" \
      --task-file "$inputs/$task_id.task.txt" \
      --artifact-dir "$artifact_dir" \
      --project-root "$project_root" \
      --validation-command-file "$inputs/$task_id.validation.sh" \
      --primary-executor lw-terra \
      --primary-wrapper "$primary_wrapper" \
      --l3-wrapper "$l3_wrapper" \
      --timeout-seconds 1200
  ) > "$workers/$task_id.supervisor.log" 2>&1 &
  pid=$!
  pids+=("$pid")
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t\t\t%s\n' \
    "$task_id" "lw-terra" "$primary_wrapper" "$project_root" "writable sandbox; bounded exclusive write scope" \
    "$pid" "$started_at" "$artifact_dir" >> "$ledger"
done

status=0
for index in "${!pids[@]}"; do
  task_id="${tasks[$index]}"
  pid="${pids[$index]}"
  if wait "$pid"; then
    exit_code=0
  else
    exit_code=$?
    status=1
  fi
  exited_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  awk -F '\t' -v OFS='\t' -v task="$task_id" -v ended="$exited_at" -v code="$exit_code" \
    'NR == 1 { print; next } $1 == task { $8 = ended; $9 = code } { print }' "$ledger" > "$ledger.next"
  mv "$ledger.next" "$ledger"
done

exit "$status"
