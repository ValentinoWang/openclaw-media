#!/usr/bin/env bash
set -euo pipefail

readonly EVIDENCE="/Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-13/media-production-e2e-closure/evidence/A1/current-production-chain.md"
test -s "$EVIDENCE"
for marker in \
  AUTHENTICATION_CURRENT_STATE \
  CONTEXT_LAUNCH_CURRENT_STATE \
  TASK_CREATION_CURRENT_STATE \
  RUNNER_CURRENT_STATE \
  RESULT_AND_PROJECTION_CURRENT_STATE \
  FEISHU_AND_DATABASE_READBACK_CURRENT_STATE \
  WEB_READBACK_CURRENT_STATE \
  DEPLOYMENT_GUARD_CURRENT_STATE \
  GAPS_TO_IMPLEMENT \
  CLAIM_BOUNDARY \
  not-proven-for-current-task
do
  grep -F "$marker" "$EVIDENCE" >/dev/null
done
if grep -Eqi '(access[_-]?token|refresh[_-]?token|authorization|cookie|password|secret)[[:space:]]*[:=][[:space:]]*[^<[:space:]]+' "$EVIDENCE"; then
  echo "secret-like value found in evidence" >&2
  exit 1
fi
echo "A1 evidence contract passed"
