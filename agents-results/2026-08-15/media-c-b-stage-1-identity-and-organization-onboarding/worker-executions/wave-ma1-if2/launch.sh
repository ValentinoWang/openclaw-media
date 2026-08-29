#!/usr/bin/env bash
set -uo pipefail

project_root="/Users/vsiyo/Desktop/创业项目/自媒体创作Agent"
bundle_root="$project_root/agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding"
artifact_dir="$bundle_root/worker-executions/wave-ma1-if2/MA1-IF2"
supervisor="/Users/vsiyo/.codex/skills/codex-explicit-worker-orchestration/scripts/run_lw_luna_with_l3_escalation.py"
mkdir -p "$artifact_dir"

python3 "$supervisor" \
  --task-id MA1-IF2 \
  --task-file "$bundle_root/worker-tasks/MA1-IF2.txt" \
  --artifact-dir "$artifact_dir" \
  --project-root "$project_root/.codex-work/stage1-ma1-migration" \
  --validation-command-file "$bundle_root/validation/MA1-IF2.sh" \
  --luna-wrapper /Users/vsiyo/.codex/workers/run-lw-luna.sh \
  --l3-wrapper /Users/vsiyo/.codex/workers/run-l3.sh \
  --timeout-seconds 1800 \
  > "$artifact_dir/outer-supervisor.log" 2>&1 &
supervisor_pid=$!
printf 'task_id\tsupervisor_pid\tstarted_at_utc\nMA1-IF2\t%s\t%s\n' \
  "$supervisor_pid" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  > "$bundle_root/worker-executions/wave-ma1-if2/supervisors.tsv"
printf 'launch barrier crossed: %s\n' "$supervisor_pid"
if wait "$supervisor_pid"; then
  exit_code=0
else
  exit_code=$?
fi
printf 'task_id\tsupervisor_pid\texit_code\tfinished_at_utc\nMA1-IF2\t%s\t%s\t%s\n' \
  "$supervisor_pid" "$exit_code" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  > "$bundle_root/worker-executions/wave-ma1-if2/exits.tsv"
printf 'MA1-IF2 supervisor exit=%s\n' "$exit_code"
exit "$exit_code"
