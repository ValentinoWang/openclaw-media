set -euo pipefail
root=/Users/vsiyo/Desktop/创业项目/自媒体创作Agent
fragment="$root/agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/acceptance-fragments/P5-RESOURCE-INIT"
python3 /Users/vsiyo/.codex/skills/design-acceptance-contract/scripts/check_acceptance_contract.py "$fragment/acceptance-contract.md" --project-root "$root"
python3 /Users/vsiyo/.codex/skills/design-acceptance-contract/scripts/manage_acceptance_artifacts.py check "$fragment" --project-root "$root"
test -f "$root/acceptance/human/P5-RESOURCE-INIT/checklist.md"
test -f "$root/acceptance/human/P5-RESOURCE-INIT/binding.md"
