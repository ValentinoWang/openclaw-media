set -euo pipefail
project_root=/Users/vsiyo/Desktop/创业项目/自媒体创作Agent
fragment_root="$project_root/agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/acceptance-fragments/P3-ADMIN-OWNER"
contract="$fragment_root/acceptance-contract.md"
protected_test="$project_root/.codex-work/stage1-p3-acceptance/backend/tests/test_stage1_admin_confirmation_acceptance.py"
test -f "$contract"
test -f "$protected_test"
rg -q '^\- Contract status: DRAFT$' "$contract"
rg -q '^\- Test baseline: (LOCKED|PLANNED)$' "$contract"
python3 -m py_compile "$protected_test"
python3 /Users/vsiyo/.codex/skills/design-acceptance-contract/scripts/check_acceptance_contract.py "$contract" --project-root "$project_root"
python3 /Users/vsiyo/.codex/skills/design-acceptance-contract/scripts/manage_acceptance_artifacts.py check "$fragment_root" --project-root "$project_root"
