#!/usr/bin/env bash
set -euo pipefail

readonly PROJECT_ROOT='/Users/vsiyo/Desktop/创业项目/自媒体创作Agent'
readonly BUNDLE="$PROJECT_ROOT/agents-results/2026-08-13/media-production-e2e-closure"
readonly SUPERVISOR='/Users/vsiyo/Desktop/Opensource_Tool/Harness_Engineering/Core/skills/codex-explicit-worker-orchestration/scripts/run_lw_luna_with_l3_escalation.py'
readonly LUNA='/Users/vsiyo/.codex/workers/run-lw-luna.sh'
readonly L3='/Users/vsiyo/.codex/workers/run-l3.sh'

chmod +x "$BUNDLE/execution-wave-2/commands/B1.sh" "$BUNDLE/execution-wave-2/commands/B2.sh"

python3 "$SUPERVISOR" \
  --task-id B1 \
  --task-file "$BUNDLE/execution-wave-2/tasks/B1.md" \
  --artifact-dir "$BUNDLE/execution-wave-2/B1" \
  --project-root "$PROJECT_ROOT" \
  --validation-command-file "$BUNDLE/execution-wave-2/commands/B1.sh" \
  --luna-wrapper "$LUNA" \
  --l3-wrapper "$L3" \
  --timeout-seconds 600 &
b1_pid=$!

python3 "$SUPERVISOR" \
  --task-id B2 \
  --task-file "$BUNDLE/execution-wave-2/tasks/B2.md" \
  --artifact-dir "$BUNDLE/execution-wave-2/B2" \
  --project-root "$PROJECT_ROOT" \
  --validation-command-file "$BUNDLE/execution-wave-2/commands/B2.sh" \
  --luna-wrapper "$LUNA" \
  --l3-wrapper "$L3" \
  --timeout-seconds 600 &
b2_pid=$!

printf 'B1 supervisor PID: %s\nB2 supervisor PID: %s\n' "$b1_pid" "$b2_pid"

b1_exit=0
b2_exit=0
wait "$b1_pid" || b1_exit=$?
wait "$b2_pid" || b2_exit=$?

printf 'B1 exit: %s\nB2 exit: %s\n' "$b1_exit" "$b2_exit"
if [ "$b1_exit" -ne 0 ] || [ "$b2_exit" -ne 0 ]; then
  exit 1
fi
