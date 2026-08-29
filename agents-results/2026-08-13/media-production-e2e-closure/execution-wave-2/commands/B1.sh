#!/usr/bin/env bash
set -euo pipefail

cd '/Users/vsiyo/Desktop/创业项目/自媒体创作Agent'
python3 '/Users/vsiyo/Desktop/Opensource_Tool/Harness_Engineering/Core/skills/design-acceptance-contract/scripts/check_acceptance_contract.py' \
  agents-results/2026-08-13/media-production-e2e-closure/acceptance-fragments/MPE2E-AUTH-WEB/acceptance-contract.md \
  --project-root '/Users/vsiyo/Desktop/创业项目/自媒体创作Agent'
rg -F -- '- Contract status: DRAFT' agents-results/2026-08-13/media-production-e2e-closure/acceptance-fragments/MPE2E-AUTH-WEB/acceptance-contract.md
rg -F -- '- Test baseline: PLANNED' agents-results/2026-08-13/media-production-e2e-closure/acceptance-fragments/MPE2E-AUTH-WEB/acceptance-contract.md
rg -F -- 'OP01 尚未确认' agents-results/2026-08-13/media-production-e2e-closure/acceptance-fragments/MPE2E-AUTH-WEB/acceptance-contract.md
