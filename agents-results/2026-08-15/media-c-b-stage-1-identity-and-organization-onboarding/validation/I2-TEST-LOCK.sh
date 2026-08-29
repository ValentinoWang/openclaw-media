#!/usr/bin/env bash
set -euo pipefail

project_root="/Users/vsiyo/Desktop/创业项目/自媒体创作Agent"
bundle="$project_root/agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding"
root="$project_root/.codex-work/stage1-i2/backend"
test_path="$root/tests/test_stage1_personal_auth_lifecycle.py"
result_log="$(mktemp -t i2-test-lock.XXXXXX)"
trap 'rm -f "$result_log"' EXIT

test "$(shasum -a 256 "$bundle/.ssot/manifest.json" | awk '{print $1}')" = "3f08c4cbfa7edbc19a846038cee611888a6952418722ec00857de62bd3e12347"
test "$(shasum -a 256 "$bundle/.ssot/nodes/I2.json" | awk '{print $1}')" = "b98d71040a330c85daaf409d7e2a9c11bc4d35e1e5d9c4675432d8a804513be6"
test "$(shasum -a 256 "$bundle/acceptance-fragments/T1-AUTH-ROUTES/acceptance-contract.md" | awk '{print $1}')" = "d1cc1861d89112729b46f741d33ef2db9b08844c567409779bb16117f02b7858"
test "$(shasum -a 256 "$bundle/acceptance-fragments/T1-AUTH-ROUTES/test-change-requests/TCR-I2-PUBLIC-AUTH-ROUTES.md" | awk '{print $1}')" = "2f6439a77533ffe1a14f04a685a1ced981f988ac50854236ac52b2125ae52fe0"
test "$(shasum -a 256 "$bundle/acceptance-fragments/T1-AUTH-ROUTES/approvals/main-orchestrator-route-contract-v1.md" | awk '{print $1}')" = "6ccaf7929e076e41c6d362931f14a32cd5665d19c3179e2f954833285b95f0bc"
test "$(shasum -a 256 "$root/openclaw_app/account/lifecycle.py" | awk '{print $1}')" = "fee996c70dcb1662a5409416eced0259072689c48c749cd45e2ce96b705324ac"
test "$(shasum -a 256 "$root/openclaw_app/account/__init__.py" | awk '{print $1}')" = "7c715e8291c7c9a36ed1bb4d944692d46a443a6cc9f4e99232a36ca03846fde4"
test "$(shasum -a 256 "$root/openclaw_app/adapters/http_api.py" | awk '{print $1}')" = "f6555e31d0aca19d81d07d13142e9d5ff4b9c6e7c5234889825a9bf9f2c7c20f"
test "$(shasum -a 256 "$test_path" | awk '{print $1}')" != "eb232753cc58e00401e6e697effec60681b7d392ae351dd9b11070304422b4e2"

for test_name in \
  test_public_stage1_routes_fields_csrf_and_legacy_aliases \
  test_public_feishu_scan_routes_use_frozen_contract \
  test_mail_failure_is_enumeration_safe_and_observable; do
  rg -q "def ${test_name}\(" "$test_path"
done

export PYTHONDONTWRITEBYTECODE=1
"$root/.venv/bin/python" -m py_compile "$test_path"
set +e
(
  cd "$root"
  "$root/.venv/bin/python" -m pytest -q -p no:cacheprovider tests/test_stage1_personal_auth_lifecycle.py
) >"$result_log" 2>&1
pytest_exit=$?
set -e
cat "$result_log"
test "$pytest_exit" -ne 0
rg -q 'FAILED .*test_(public_stage1_routes_fields_csrf_and_legacy_aliases|public_feishu_scan_routes_use_frozen_contract|mail_failure_is_enumeration_safe_and_observable)' "$result_log"
echo "I2_TEST_BASELINE=EXPECTED_RED"
