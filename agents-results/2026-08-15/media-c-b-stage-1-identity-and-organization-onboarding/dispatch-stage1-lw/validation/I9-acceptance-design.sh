set -euo pipefail
project_root=/Users/vsiyo/Desktop/创业项目/自媒体创作Agent
fragment_root="$project_root/agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/acceptance-fragments/I9-WRITER-FAIL-CLOSED"
contract="$fragment_root/acceptance-contract.md"
backend_test="$project_root/.codex-work/stage1-i9-acceptance/backend/tests/test_stage1_writer_entrypoint_acceptance.py"
frontend_test="$project_root/.codex-work/stage1-i9-acceptance/frontend/scripts/qa/checkStage1WriterFailClosed.ts"
test -f "$contract"
test -f "$backend_test"
test -f "$frontend_test"
rg -q '^\- Contract status: DRAFT$' "$contract"
rg -q '^\- Test baseline: (LOCKED|PLANNED)$' "$contract"
python3 -m py_compile "$backend_test"
cd "$project_root/.codex-work/stage1-i9-acceptance/frontend"
if ./node_modules/.bin/tsx scripts/qa/checkStage1WriterFailClosed.ts >/dev/null 2>&1; then
  echo 'I9 frontend acceptance baseline unexpectedly passed before implementation' >&2
  exit 1
fi
python3 /Users/vsiyo/.codex/skills/design-acceptance-contract/scripts/check_acceptance_contract.py "$contract" --project-root "$project_root"
python3 /Users/vsiyo/.codex/skills/design-acceptance-contract/scripts/manage_acceptance_artifacts.py check "$fragment_root" --project-root "$project_root"
