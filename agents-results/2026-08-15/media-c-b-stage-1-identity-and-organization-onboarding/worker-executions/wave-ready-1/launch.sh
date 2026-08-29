#!/usr/bin/env bash
set -uo pipefail

project_root="/Users/vsiyo/Desktop/创业项目/自媒体创作Agent"
bundle_root="$project_root/agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding"
wave_root="$bundle_root/worker-executions/wave-ready-1"
supervisor="/Users/vsiyo/.codex/skills/codex-explicit-worker-orchestration/scripts/run_lw_luna_with_l3_escalation.py"
luna_wrapper="/Users/vsiyo/.codex/workers/run-lw-luna.sh"
l3_wrapper="/Users/vsiyo/.codex/workers/run-l3.sh"

task_ids=(MA1 T1 I1 I2)
development_roots=(
  "$project_root/.codex-work/stage1-ma1-migration"
  "$project_root/.codex-work/stage1-t1"
  "$project_root/.codex-work/stage1-i1"
  "$project_root/.codex-work/stage1-i2"
)
pids=()

mkdir -p "$wave_root"
printf 'task_id\tsupervisor_pid\tstarted_at_utc\tproject_root\tartifact_dir\n' > "$wave_root/supervisors.tsv"

for index in "${!task_ids[@]}"; do
  task_id="${task_ids[$index]}"
  development_root="${development_roots[$index]}"
  artifact_dir="$wave_root/$task_id"
  mkdir -p "$artifact_dir"

  python3 "$supervisor" \
    --task-id "$task_id" \
    --task-file "$bundle_root/worker-tasks/$task_id.txt" \
    --artifact-dir "$artifact_dir" \
    --project-root "$development_root" \
    --validation-command-file "$bundle_root/validation/$task_id.sh" \
    --luna-wrapper "$luna_wrapper" \
    --l3-wrapper "$l3_wrapper" \
    --timeout-seconds 1800 \
    > "$artifact_dir/outer-supervisor.log" 2>&1 &
  supervisor_pid=$!
  pids+=("$supervisor_pid")
  printf '%s\t%s\t%s\t%s\t%s\n' \
    "$task_id" \
    "$supervisor_pid" \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    "$development_root" \
    "$artifact_dir" \
    >> "$wave_root/supervisors.tsv"
done

if [ "$(printf '%s\n' "${pids[@]}" | sort -u | wc -l | tr -d ' ')" -ne 4 ]; then
  printf 'launch barrier failed: supervisor PIDs are not distinct\n' >&2
  exit 64
fi

printf 'launch barrier crossed: %s\n' "${pids[*]}"
printf 'task_id\tsupervisor_pid\texit_code\tfinished_at_utc\n' > "$wave_root/exits.tsv"

overall_exit=0
for index in "${!task_ids[@]}"; do
  task_id="${task_ids[$index]}"
  supervisor_pid="${pids[$index]}"
  if wait "$supervisor_pid"; then
    exit_code=0
  else
    exit_code=$?
    overall_exit=1
  fi
  printf '%s\t%s\t%s\t%s\n' \
    "$task_id" \
    "$supervisor_pid" \
    "$exit_code" \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    >> "$wave_root/exits.tsv"
  printf '%s supervisor exit=%s\n' "$task_id" "$exit_code"
done

exit "$overall_exit"
