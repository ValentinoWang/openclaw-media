#!/usr/bin/env bash
set -euo pipefail

readonly ROOT="/Users/vsiyo/Desktop/创业项目/自媒体创作Agent"
readonly BUNDLE="$ROOT/agents-results/2026-08-13/media-production-e2e-closure"
readonly TASK_ROOT="$BUNDLE/acceptance-fragments/MPE2E-AUTH-WEB"
readonly CONTRACT="$TASK_ROOT/acceptance-contract.md"
readonly CHECKLIST="$ROOT/acceptance/human/MPE2E-AUTH-WEB/checklist.md"
readonly BINDING="$ROOT/acceptance/human/MPE2E-AUTH-WEB/binding.md"
readonly TEST_SCRIPT="$ROOT/scripts/acceptance/test-mpe2e-auth-web.sh"
readonly DESIGN_SKILL="/Users/vsiyo/Desktop/Opensource_Tool/Harness_Engineering/Core/skills/design-acceptance-contract"

check_hash() {
  local expected="$1"
  local path="$2"
  local actual
  actual="$(shasum -a 256 "$path" | awk '{print $1}')"
  [[ "$actual" == "$expected" ]] || {
    echo "hash drift: $path expected=$expected actual=$actual" >&2
    return 1
  }
}

check_hash e6ac97c7864162751ab8ec1df73b0c5f9cd425b3ac746c550d89bba6382673c3 "$BUNDLE/.ssot/manifest.json"
check_hash 7ff91b1f3cc446c368074f31b3aa8a1f1749eed5efbdf975df4521a747d4d1f3 "$BUNDLE/.ssot/nodes/B1.json"
check_hash 8fafa1208ead99395489353de9bc32560a6b82863bb9028fda670fc3526a9997 "$BUNDLE/.ssot/nodes/D1.json"
check_hash a53cbc80ea0b2010643e20194f2dc115e42b007014e356787e1ede9fa7cb2c47 "$BUNDLE/.ssot/nodes/D3.json"
check_hash f708e01fd4b0e0320ed0eb5c23b8c27f5348eaac4fce82841c21cbb8e94072ae "$BUNDLE/openproblem.md"
check_hash 7e27523e6fbb3f5297a15917672ad03082e3c7b919cb99fccf9cba738bc80f14 "$ROOT/.codex-work/production-baseline-20260814T084319Z/frontend/.source-manifest.sha256"
check_hash bca0dac2e657d0d1fd939c87645ad278fb6e9a049ac18429c11e714b5684e49b "$ROOT/.codex-work/production-baseline-20260814T084319Z/backend/.manifest.sha256"

jq -e '.execution_state == "READY" and .readiness_mode == "FORMAL" and .required_contract_version == 2 and (.assumption_ids | length == 0)' "$BUNDLE/.ssot/nodes/B1.json" >/dev/null

test -f "$CONTRACT"
test -f "$CHECKLIST"
test -f "$BINDING"
test -x "$TEST_SCRIPT"

python3 "$DESIGN_SKILL/scripts/check_acceptance_contract.py" "$CONTRACT" --project-root "$ROOT"
python3 "$DESIGN_SKILL/scripts/manage_acceptance_artifacts.py" check "$TASK_ROOT" --project-root "$ROOT" --contract "$CONTRACT"

rg -F -- '- Task ID: MPE2E-AUTH-WEB' "$CONTRACT"
rg -F -- '- Contract version: 2' "$CONTRACT"
rg -F -- '- Contract status: APPROVED' "$CONTRACT"
rg -F -- '- Test baseline: LOCKED' "$CONTRACT"
rg -F -- '- Readiness mode: FORMAL' "$CONTRACT"
rg -F -- '- Assumption IDs: none' "$CONTRACT"
rg -F -- 'media.no-inference-completion-boundary@1' "$CONTRACT"
rg -F -- 'media.qa-identity@1' "$CONTRACT"
rg -F -- '20260814T084319Z-media-login-canonical' "$CONTRACT"
rg -F -- '20260814T062408Z-opc-feishu-login' "$CONTRACT"
rg -F -- 'local-candidate' "$CONTRACT" "$TEST_SCRIPT"
rg -F -- 'production' "$CONTRACT" "$TEST_SCRIPT"
rg -F -- 'MPE2E_AUTH_WEB_MODE' "$CONTRACT" "$TEST_SCRIPT"
rg -F -- '飞书扫码' "$CONTRACT" "$CHECKLIST"
rg -F -- '账号密码' "$CONTRACT" "$CHECKLIST"
rg -F -- '飞书账号关联' "$CONTRACT"
rg -F -- '租户角色会话' "$CONTRACT"
rg -F -- '未关联' "$CONTRACT" "$CHECKLIST"
rg -F -- '跨租户' "$CONTRACT" "$CHECKLIST"
rg -F -- '权限不足' "$CONTRACT"
rg -F -- '清单状态：已批准' "$CHECKLIST"
rg -F -- '合同版本：2' "$CHECKLIST"
rg -F -- 'Contract version: 2' "$BINDING"
rg -F -- 'Binding status: ACTIVE' "$BINDING"
rg -F -- 'scripts/acceptance/test-mpe2e-auth-web.sh' "$CONTRACT"

for required in \
  schema_version \
  contract_version \
  evidence_level \
  source_revision \
  mock_or_fixture \
  password \
  feishu_qr \
  account_linkage \
  tenant_session \
  role \
  csrf \
  unlinked \
  cross_tenant \
  permission_denied \
  desktop \
  mobile; do
  rg -F -- "$required" "$TEST_SCRIPT"
done

if rg -F -- '20260813T184753CST-media-e2e-b4-label-guard-r2' "$CONTRACT" "$CHECKLIST" "$TEST_SCRIPT"; then
  echo 'stale B4 release identity remains in active v2 artifacts' >&2
  exit 1
fi

bash -n "$TEST_SCRIPT"

set +e
MPE2E_AUTH_WEB_MODE=local-candidate "$TEST_SCRIPT" >/tmp/mpe2e-b1-v2-local-red.log 2>&1
local_red_exit=$?
MPE2E_AUTH_WEB_MODE=production "$TEST_SCRIPT" >/tmp/mpe2e-b1-v2-production-red.log 2>&1
production_red_exit=$?
set -e

[[ "$local_red_exit" -eq 20 ]] || {
  cat /tmp/mpe2e-b1-v2-local-red.log >&2
  echo "expected local-candidate missing-receipt exit 20, got $local_red_exit" >&2
  exit 1
}
[[ "$production_red_exit" -eq 20 ]] || {
  cat /tmp/mpe2e-b1-v2-production-red.log >&2
  echo "expected production missing-receipt exit 20, got $production_red_exit" >&2
  exit 1
}
rg -F -- 'safe_metadata_file_required' /tmp/mpe2e-b1-v2-local-red.log
rg -F -- 'safe_metadata_file_required' /tmp/mpe2e-b1-v2-production-red.log

test_hash="$(shasum -a 256 "$TEST_SCRIPT" | awk '{print $1}')"
rg -F -- "| scripts/acceptance/test-mpe2e-auth-web.sh | $test_hash |" "$CONTRACT"

echo 'B1-V2-LOCK validation passed'
