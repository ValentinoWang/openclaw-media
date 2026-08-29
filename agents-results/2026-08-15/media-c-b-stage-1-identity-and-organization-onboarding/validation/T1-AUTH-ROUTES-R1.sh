#!/usr/bin/env bash
set -euo pipefail

project_root="/Users/vsiyo/Desktop/创业项目/自媒体创作Agent"
t1_root="$project_root/.codex-work/stage1-t1"
i1_root="$project_root/.codex-work/stage1-i1"
i2_root="$project_root/.codex-work/stage1-i2"
bundle="$project_root/agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding"
fragment="$bundle/acceptance-fragments/T1-AUTH-ROUTES"
design_skill="/Users/vsiyo/.codex/skills/design-acceptance-contract"

test "$(shasum -a 256 "$bundle/.ssot/manifest.json" | awk '{print $1}')" = "3f08c4cbfa7edbc19a846038cee611888a6952418722ec00857de62bd3e12347"
test "$(shasum -a 256 "$bundle/.ssot/nodes/B.json" | awk '{print $1}')" = "9cb6aba94cc23066579ec65ea57d6771c98425aff14ea6267f403e52373948e6"
test "$(shasum -a 256 "$bundle/.ssot/nodes/K6.json" | awk '{print $1}')" = "a827ede3e6d5da4d6be4ee4a7604c5b6e6045bc69c5f647bdb772a5b0f923f90"
test "$(shasum -a 256 "$bundle/.ssot/nodes/T1.json" | awk '{print $1}')" = "613e2d5bbe52227f38c321d4f243e772efa02309bda4a97084916f8a3b66c910"
test "$(shasum -a 256 "$i1_root/frontend/media.login.js" | awk '{print $1}')" = "18f64fcdce9c30341491788e53c7df16fb49cf6a03421725244375f875ddbe47"
test "$(shasum -a 256 "$i1_root/frontend/deploy/nginx-openclaw-bot-center.conf" | awk '{print $1}')" = "4410457643280b3ac967bcd06971e2300e1499ed15edb2c6677fd38d103ac728"
test "$(shasum -a 256 "$i2_root/backend/openclaw_app/adapters/http_api.py" | awk '{print $1}')" = "f6555e31d0aca19d81d07d13142e9d5ff4b9c6e7c5234889825a9bf9f2c7c20f"
test "$(shasum -a 256 "$i2_root/backend/tests/test_stage1_personal_auth_lifecycle.py" | awk '{print $1}')" = "eb232753cc58e00401e6e697effec60681b7d392ae351dd9b11070304422b4e2"

bash "$bundle/validation/T1.sh"

python3 "$t1_root/backend/tests/check_stage1_auth_route_alignment.py" \
  --t1-root "$t1_root" \
  --i1-root "$i1_root" \
  --i2-root "$i2_root" \
  --expect-red

python3 "$design_skill/scripts/check_acceptance_contract.py" \
  "$fragment/acceptance-contract.md" \
  --project-root "$project_root"

python3 "$design_skill/scripts/manage_acceptance_artifacts.py" index \
  "$fragment" \
  --project-root "$project_root"

python3 "$design_skill/scripts/manage_acceptance_artifacts.py" check \
  "$fragment" \
  --project-root "$project_root"

echo "t1_auth_routes_candidate=PASS"
