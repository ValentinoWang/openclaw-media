#!/usr/bin/env bash
set -euo pipefail

root="/Users/vsiyo/Desktop/创业项目/自媒体创作Agent"
fragment="$root/agents-results/2026-08-13/media-production-e2e-closure/acceptance-fragments/MPE2E-MATERIAL-PARSING"
manager="/Users/vsiyo/.codex/skills/design-acceptance-contract/scripts/manage_acceptance_artifacts.py"
checker="/Users/vsiyo/.codex/skills/design-acceptance-contract/scripts/check_acceptance_contract.py"

test "$(shasum -a 256 "$root/agents-results/2026-08-13/media-production-e2e-closure/contracts/material-parsing-coverage-v1.json" | awk '{print $1}')" = "24452e8b621fa3a797b7efba6c03a48aad86f3436193fbef38794bcf4de54f56"
test -f "$fragment/acceptance-contract.md"
test -f "$fragment/acceptance/production/monitoring-plan.md"
test -f "$root/acceptance/human/MPE2E-MATERIAL-PARSING/checklist.md"
test -f "$root/acceptance/human/MPE2E-MATERIAL-PARSING/binding.md"
test -x "$root/scripts/acceptance/test-mpe2e-material-parsing.sh"
rg -q '^\- Contract status: APPROVED$' "$fragment/acceptance-contract.md"
rg -q '^\- Test baseline: LOCKED$' "$fragment/acceptance-contract.md"
rg -q '^\- SSOT node: D6$' "$fragment/acceptance-contract.md"
rg -q '^\- 清单状态：已批准$' "$root/acceptance/human/MPE2E-MATERIAL-PARSING/checklist.md"
python3 "$manager" bind-human "$fragment" --project-root "$root" --replace
python3 "$checker" "$fragment/acceptance-contract.md" --project-root "$root"
python3 "$manager" index "$fragment" --project-root "$root"
python3 "$manager" check "$fragment" --project-root "$root"
bash "$root/scripts/acceptance/test-mpe2e-material-parsing.sh"

echo "MPE2E material parsing acceptance design passed"
