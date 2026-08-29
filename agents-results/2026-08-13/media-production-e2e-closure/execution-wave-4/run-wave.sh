#!/usr/bin/env bash
set -euo pipefail

readonly PROJECT_ROOT='/Users/vsiyo/Desktop/创业项目/自媒体创作Agent'
readonly BUNDLE="$PROJECT_ROOT/agents-results/2026-08-13/media-production-e2e-closure"
readonly SUPERVISOR='/Users/vsiyo/Desktop/Opensource_Tool/Harness_Engineering/Core/skills/codex-explicit-worker-orchestration/scripts/run_lw_luna_with_l3_escalation.py'
readonly LUNA='/Users/vsiyo/.codex/workers/run-lw-luna.sh'
readonly L3='/Users/vsiyo/.codex/workers/run-l3.sh'

python3 "$SUPERVISOR" --task-id B1-LOCK --task-file "$BUNDLE/execution-wave-4/tasks/B1-LOCK.md" --artifact-dir "$BUNDLE/execution-wave-4/B1-LOCK" --project-root "$PROJECT_ROOT" --validation-command-file "$BUNDLE/execution-wave-4/commands/B1-LOCK.sh" --luna-wrapper "$LUNA" --l3-wrapper "$L3" --timeout-seconds 1200 &
b1_pid=$!
python3 "$SUPERVISOR" --task-id B2-LOCK --task-file "$BUNDLE/execution-wave-4/tasks/B2-LOCK.md" --artifact-dir "$BUNDLE/execution-wave-4/B2-LOCK" --project-root "$PROJECT_ROOT" --validation-command-file "$BUNDLE/execution-wave-4/commands/B2-LOCK.sh" --luna-wrapper "$LUNA" --l3-wrapper "$L3" --timeout-seconds 1200 &
b2_pid=$!

printf 'B1-LOCK supervisor PID: %s\nB2-LOCK supervisor PID: %s\n' "$b1_pid" "$b2_pid"
b1_exit=0
b2_exit=0
wait "$b1_pid" || b1_exit=$?
wait "$b2_pid" || b2_exit=$?
printf 'B1-LOCK exit: %s\nB2-LOCK exit: %s\n' "$b1_exit" "$b2_exit"
[[ "$b1_exit" -eq 0 && "$b2_exit" -eq 0 ]]
