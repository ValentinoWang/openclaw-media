#!/usr/bin/env bash
set -euo pipefail

project_root="/Users/vsiyo/Desktop/创业项目/自媒体创作Agent"
bundle="$project_root/agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding"
root="$project_root/.codex-work/stage1-t1/backend"
test_path="$root/tests/test_media_stage1_shared_contract.py"

test "$(shasum -a 256 "$bundle/.ssot/manifest.json" | awk '{print $1}')" = "3f08c4cbfa7edbc19a846038cee611888a6952418722ec00857de62bd3e12347"
test "$(shasum -a 256 "$bundle/.ssot/nodes/T1.json" | awk '{print $1}')" = "613e2d5bbe52227f38c321d4f243e772efa02309bda4a97084916f8a3b66c910"
test "$(shasum -a 256 "$bundle/acceptance-fragments/T1-AUTH-ROUTES/acceptance-contract.md" | awk '{print $1}')" = "d1cc1861d89112729b46f741d33ef2db9b08844c567409779bb16117f02b7858"
test "$(shasum -a 256 "$bundle/acceptance-fragments/T1-AUTH-ROUTES/test-change-requests/TCR-T1-ROUTE-CARRIER.md" | awk '{print $1}')" = "27047ecb06196f6b1a6300a99b4db9298432d53608f858aa6187fd77cb0a9dcc"
test "$(shasum -a 256 "$bundle/acceptance-fragments/T1-AUTH-ROUTES/approvals/main-orchestrator-route-contract-v1.md" | awk '{print $1}')" = "6ccaf7929e076e41c6d362931f14a32cd5665d19c3179e2f954833285b95f0bc"
test "$(shasum -a 256 "$root/openclaw_app/contracts/media_web_business_pages.openapi.yaml" | awk '{print $1}')" = "f4f4cd16bf3e4ad3ddfd0080da6ccfb7fd7f2ba6469871edcb45e957c2854790"
test "$(shasum -a 256 "$root/contracts/stage1_acceptance_contract.json" | awk '{print $1}')" = "775ddfa6fcfb5e04a931dfa5e03dfd08891365fc4491c16d8a6e49ede1c58611"
test "$(shasum -a 256 "$root/tests/test_stage1_acceptance_harness.py" | awk '{print $1}')" = "13219785db38866e00387d4ce09553ef05c34ab21b5c6a4fbf9709f583d73009"
test "$(shasum -a 256 "$root/tests/check_stage1_auth_route_alignment.py" | awk '{print $1}')" = "6fa14dc5655ac77bd1a78bad0a132ff8ed81ac2fca8aafb2d5bb69448086f236"
test "$(shasum -a 256 "$test_path" | awk '{print $1}')" != "c1fbb5b6655ff2f4bb6f90152a8ab6705d77f6d2744744014f99e0d9dafa01a8"

cd "$root"
export PYTHONDONTWRITEBYTECODE=1
"$root/.venv/bin/python" -m pytest -q -p no:cacheprovider tests/test_media_stage1_shared_contract.py
echo "T1_TEST_BASELINE=GREEN"
