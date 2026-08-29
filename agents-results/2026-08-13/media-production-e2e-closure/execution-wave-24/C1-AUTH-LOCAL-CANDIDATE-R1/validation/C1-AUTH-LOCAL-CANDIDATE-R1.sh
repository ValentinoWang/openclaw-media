#!/usr/bin/env bash
set -euo pipefail

root="/Users/vsiyo/Desktop/创业项目/自媒体创作Agent"
runner="$root/agents-results/2026-08-13/media-production-e2e-closure/execution-wave-24/C1-AUTH-LOCAL-CANDIDATE-R1/runner"

test "$(shasum -a 256 "$root/.codex-work/merge-candidate-v4/candidate-manifest.json" | awk '{print $1}')" = "f1ac786573e76aa40a0d69a10aab6dba5bd6a345596242d93f37773b59f45bcb"
test "$(shasum -a 256 "$root/scripts/acceptance/test-mpe2e-auth-web.sh" | awk '{print $1}')" = "8bf6f33d0917948821f7a6ffbbd3e5f505002fb19d77c4f1d24b9c3261e6ab2e"
test "$(shasum -a 256 "$root/scripts/acceptance/test-mpe2e-auth-workspace-source.sh" | awk '{print $1}')" = "4e73a4b346095d2e9eea998c07562fb8066835dec644211f33afa6998a51430e"

test -f "$runner/run-local-candidate-e2e.sh"
test -f "$runner/runMediaAuthLocalCandidate.mjs"
bash -n "$runner/run-local-candidate-e2e.sh"
node --check "$runner/runMediaAuthLocalCandidate.mjs"

test "$(find "$runner" -maxdepth 1 -type f | wc -l | tr -d ' ')" = "2"
rg -F -- '1440, height: 1000' "$runner/runMediaAuthLocalCandidate.mjs" >/dev/null
rg -F -- '390, height: 844' "$runner/runMediaAuthLocalCandidate.mjs" >/dev/null
rg -F -- 'organization_lark' "$runner/runMediaAuthLocalCandidate.mjs" >/dev/null
rg -F -- 'personal_web' "$runner/runMediaAuthLocalCandidate.mjs" >/dev/null
rg -F -- 'qr_expired_rejected' "$runner/runMediaAuthLocalCandidate.mjs" >/dev/null
rg -F -- 'external_creator_same_name' "$runner/runMediaAuthLocalCandidate.mjs" >/dev/null
rg -F -- 'MPE2E_AUTH_WEB_MODE=local-candidate' "$runner/run-local-candidate-e2e.sh" >/dev/null
rg -F -- 'C5-UNIQUE-CANDIDATE-R3.sh' "$runner/run-local-candidate-e2e.sh" >/dev/null

echo 'C1_AUTH_LOCAL_CANDIDATE_RUNNER_VALIDATION_PASS'
