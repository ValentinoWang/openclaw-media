#!/usr/bin/env bash
set -euo pipefail

readonly ROOT="/Users/vsiyo/Desktop/创业项目/自媒体创作Agent"
readonly BUNDLE="$ROOT/agents-results/2026-08-13/media-production-e2e-closure"
readonly TASK_ROOT="$BUNDLE/acceptance-fragments/MPE2E-TASK-RUN-V3"
readonly CONTRACT="$TASK_ROOT/acceptance-contract.md"
readonly CHECKLIST="$ROOT/acceptance/human/MPE2E-TASK-RUN-V3/checklist.md"
readonly BINDING="$ROOT/acceptance/human/MPE2E-TASK-RUN-V3/binding.md"
readonly TEST_SCRIPT="$ROOT/scripts/acceptance/test-mpe2e-task-run-v3.sh"
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

check_hash c6bd807376561c25820938b1839f50b633a7e2f4911f3460fea9a6f5e1a0e12b "$BUNDLE/.ssot/nodes/D5.json"
check_hash bc03cff59c504da915380b0357550ff34eaa231a37c5cbd103170c1adb6bbf7d "$BUNDLE/.ssot/nodes/B2.json"
check_hash f2f97099c514b8a9b5570c7626cc5e746ce99394370985000cdddd5094a18bf2 "$BUNDLE/acceptance-fragments/MPE2E-TASK-RUN/acceptance-contract.md"
check_hash 45664f75ee37535b3e67242a4c0550735a131f50281d5fca34f0e6d1e095724f "$ROOT/acceptance/human/MPE2E-TASK-RUN/checklist.md"
check_hash 48b84499da08393953eec17fe7afc0fed209ed908e427522254ef20414c2fe9b "$ROOT/acceptance/human/MPE2E-TASK-RUN/binding.md"
check_hash 334d2393059e54980a8434a99d59bef1b1f82d1466549f540aa40e4f5f0e50d0 "$ROOT/scripts/acceptance/test-mpe2e-task-run.sh"

jq -e '.decision_state == "ACCEPTED" and .decision_version == 1 and .execution_state == "ACCEPTED"' "$BUNDLE/.ssot/nodes/D5.json" >/dev/null
jq -e '.execution_state == "READY" and .readiness_mode == "FORMAL" and (.assumption_ids | length == 0)' "$BUNDLE/.ssot/nodes/B2.json" >/dev/null

test -f "$CONTRACT"
test -f "$CHECKLIST"
test -f "$BINDING"
test -x "$TEST_SCRIPT"

python3 "$DESIGN_SKILL/scripts/check_acceptance_contract.py" "$CONTRACT" --project-root "$ROOT"
python3 "$DESIGN_SKILL/scripts/manage_acceptance_artifacts.py" check "$TASK_ROOT" --project-root "$ROOT" --contract "$CONTRACT"

rg -F -- '- Task ID: MPE2E-TASK-RUN-V3' "$CONTRACT"
rg -F -- '- Contract version: 3' "$CONTRACT"
rg -F -- '- Contract status: APPROVED' "$CONTRACT"
rg -F -- '- Test baseline: LOCKED' "$CONTRACT"
rg -F -- '- Readiness mode: FORMAL' "$CONTRACT"
rg -F -- '- Assumption IDs: none' "$CONTRACT"
rg -F -- 'media.representative-account-binding-input@1' "$CONTRACT"
rg -F -- 'decision.representative-account-binding-input' "$CONTRACT"
rg -F -- '`selfmedia_creation_consultation`' "$CONTRACT"
rg -F -- '`selfmedia_creation`' "$CONTRACT"
rg -F -- '认证用户公开编号' "$CONTRACT"
rg -F -- '规范化平台' "$CONTRACT"
rg -F -- '规范化账号' "$CONTRACT"
rg -F -- '入队前' "$CONTRACT"
rg -F -- '不创建任务' "$CONTRACT"
rg -F -- '其他能力' "$CONTRACT"
rg -F -- 'MPE2E-TASK-RUN-V3' "$CHECKLIST"
rg -F -- '清单状态：已批准' "$CHECKLIST"
rg -F -- 'Contract version: 3' "$BINDING"
rg -F -- 'Binding status: ACTIVE' "$BINDING"
rg -F -- 'scripts/acceptance/test-mpe2e-task-run-v3.sh' "$CONTRACT"

for required in \
  selfmedia_creation_consultation \
  selfmedia_creation \
  userPublicId \
  normalizedPlatform \
  normalizedAccount \
  relationshipRef \
  bindingDigest \
  enqueueAccepted; do
  rg -F -- "$required" "$TEST_SCRIPT"
done

if rg -n -i 'default account|fallback|legacy input|兼容旧输入|默认账号|模糊匹配' "$CONTRACT" "$TEST_SCRIPT"; then
  echo "forbidden fallback or legacy semantics found" >&2
  exit 1
fi

set +e
MPE2E_RECEIPT_DIR="$ROOT/acceptance/production/MPE2E-TASK-RUN-V3/receipts-not-present" "$TEST_SCRIPT" >/tmp/mpe2e-b2-v3-red.log 2>&1
red_exit=$?
set -e
[[ "$red_exit" -eq 3 ]] || {
  cat /tmp/mpe2e-b2-v3-red.log >&2
  echo "expected preimplementation missing-receipt red exit 3, got $red_exit" >&2
  exit 1
}
rg -F -- 'production same-receipt evidence missing' /tmp/mpe2e-b2-v3-red.log

echo 'B2-V3-LOCK validation passed'
