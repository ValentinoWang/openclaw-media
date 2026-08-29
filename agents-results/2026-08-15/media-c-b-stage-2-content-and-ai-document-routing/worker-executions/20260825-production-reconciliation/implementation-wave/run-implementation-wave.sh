#!/usr/bin/env bash
set -u

root='/Users/vsiyo/Desktop/创业项目/自媒体创作Agent'
wave="$root/agents-results/2026-08-15/media-c-b-stage-2-content-and-ai-document-routing/worker-executions/20260825-production-reconciliation/implementation-wave"
supervisor='/Users/vsiyo/.codex/skills/codex-explicit-worker-orchestration/scripts/run_primary_with_l3_escalation.py'
luna='/Users/vsiyo/.codex/workers/run-lw-luna.sh'
l3='/Users/vsiyo/.codex/workers/run-l3.sh'

python3 "$supervisor" \
  --task-id PR-REL-MANIFEST-IMPLEMENT \
  --task-file "$wave/tasks/PR-REL-MANIFEST-IMPLEMENT.txt" \
  --artifact-dir "$wave/artifacts/manifest" \
  --project-root "$root/.codex-work/pr-rel-manifest-impl" \
  --validation-command-file "$wave/validation/PR-REL-MANIFEST-IMPLEMENT.sh" \
  --primary-executor lw-luna \
  --primary-wrapper "$luna" \
  --l3-wrapper "$l3" \
  --timeout-seconds 2400 \
  >"$wave/manifest-supervisor.out" 2>&1 &
manifest_pid=$!

python3 "$supervisor" \
  --task-id PR-REL-READBACK-IMPLEMENT \
  --task-file "$wave/tasks/PR-REL-READBACK-IMPLEMENT.txt" \
  --artifact-dir "$wave/artifacts/readback" \
  --project-root "$root/.codex-work/pr-rel-readback-impl" \
  --validation-command-file "$wave/validation/PR-REL-READBACK-IMPLEMENT.sh" \
  --primary-executor lw-luna \
  --primary-wrapper "$luna" \
  --l3-wrapper "$l3" \
  --timeout-seconds 2400 \
  >"$wave/readback-supervisor.out" 2>&1 &
readback_pid=$!

python3 "$supervisor" \
  --task-id PR-REL-PLANNER-IMPLEMENT \
  --task-file "$wave/tasks/PR-REL-PLANNER-IMPLEMENT.txt" \
  --artifact-dir "$wave/artifacts/planner" \
  --project-root "$root/.codex-work/pr-rel-planner-impl" \
  --validation-command-file "$wave/validation/PR-REL-PLANNER-IMPLEMENT.sh" \
  --primary-executor lw-luna \
  --primary-wrapper "$luna" \
  --l3-wrapper "$l3" \
  --timeout-seconds 2400 \
  >"$wave/planner-supervisor.out" 2>&1 &
planner_pid=$!

printf 'launch_barrier manifest=%s readback=%s planner=%s\n' "$manifest_pid" "$readback_pid" "$planner_pid"

wait "$manifest_pid"
manifest_rc=$?
wait "$readback_pid"
readback_rc=$?
wait "$planner_pid"
planner_rc=$?

printf 'completed manifest=%s readback=%s planner=%s\n' "$manifest_rc" "$readback_rc" "$planner_rc"

if (( manifest_rc != 0 || readback_rc != 0 || planner_rc != 0 )); then
  exit 20
fi
