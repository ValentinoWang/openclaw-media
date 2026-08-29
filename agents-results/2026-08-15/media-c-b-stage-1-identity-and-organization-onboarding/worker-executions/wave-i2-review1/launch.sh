#!/usr/bin/env bash
set -uo pipefail

project_root="/Users/vsiyo/Desktop/创业项目/自媒体创作Agent"
bundle_root="$project_root/agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding"
artifact_dir="$bundle_root/worker-executions/wave-i2-review1/I2-REVIEW1"
supervisor="/Users/vsiyo/.codex/skills/codex-explicit-worker-orchestration/scripts/run_lw_luna_with_l3_escalation.py"
mkdir -p "$artifact_dir"
python3 "$supervisor" \
  --task-id I2-REVIEW1 \
  --task-file "$bundle_root/worker-tasks/I2-REVIEW1.txt" \
  --artifact-dir "$artifact_dir" \
  --project-root "$project_root/.codex-work/stage1-i2" \
  --validation-command-file "$bundle_root/validation/I2-REVIEW1.sh" \
  --luna-wrapper /Users/vsiyo/.codex/workers/run-lw-luna.sh \
  --l3-wrapper /Users/vsiyo/.codex/workers/run-l3.sh \
  --timeout-seconds 1800 \
  > "$artifact_dir/outer-supervisor.log" 2>&1 &
supervisor_pid=$!
printf 'task_id\tsupervisor_pid\tstarted_at_utc\nI2-REVIEW1\t%s\t%s\n' \
  "$supervisor_pid" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  > "$bundle_root/worker-executions/wave-i2-review1/supervisors.tsv"
printf 'launch barrier crossed: %s\n' "$supervisor_pid"
if wait "$supervisor_pid"; then exit_code=0; else exit_code=$?; fi
printf 'task_id\tsupervisor_pid\texit_code\tfinished_at_utc\nI2-REVIEW1\t%s\t%s\t%s\n' \
  "$supervisor_pid" "$exit_code" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  > "$bundle_root/worker-executions/wave-i2-review1/exits.tsv"
printf 'I2-REVIEW1 supervisor exit=%s\n' "$exit_code"
exit "$exit_code"
