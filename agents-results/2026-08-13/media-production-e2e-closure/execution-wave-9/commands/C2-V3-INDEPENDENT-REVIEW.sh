#!/usr/bin/env bash
set -euo pipefail

root="/Users/vsiyo/Desktop/创业项目/自媒体创作Agent"
bundle="$root/agents-results/2026-08-13/media-production-e2e-closure"
review="$bundle/execution-wave-9/C2-V3-INDEPENDENT-REVIEW"
return_file="$review/returns/C2-V3-INDEPENDENT-REVIEW.json"
source_manifest="$bundle/execution-wave-8/C2-V3-IMPLEMENT/postimplementation-source.sha256"
contract="$bundle/acceptance-fragments/MPE2E-TASK-RUN-V3/acceptance-contract.md"
protected_test="$root/scripts/acceptance/test-mpe2e-task-run-v3.sh"
validation="$bundle/execution-wave-8/validation/C2-V3-IMPLEMENT.sh"
validation_log="$bundle/execution-wave-8/C2-V3-IMPLEMENT/logs/C2-V3-IMPLEMENT-main-thread.validation.log"

test "$(shasum -a 256 "$source_manifest" | awk '{print $1}')" = \
  "f36330fc9dd994df878e2d4a37deb3bed8fe02ca32c75464a69c786e1691d337"
test "$(shasum -a 256 "$contract" | awk '{print $1}')" = \
  "35143a0fb22218ebdcf969ee3a137431c37f21f90781db15572909e1dba0ca8b"
test "$(shasum -a 256 "$protected_test" | awk '{print $1}')" = \
  "dee8b55304a60b4284462310f68f03099369af15071efc2fe5f39dcc8f67b73d"
test "$(shasum -a 256 "$validation" | awk '{print $1}')" = \
  "c4761038d60531b50bd0a1f13df8ed287833237172507bb6b1c37501a133248e"
test "$(shasum -a 256 "$validation_log" | awk '{print $1}')" = \
  "97849f27db4084181b2370c2e9bdcacfb8525b3ed7279b219b99b255e53c9dba"

cd "$root"
shasum -a 256 -c "$source_manifest" >/dev/null

jq -e --arg return_file "$return_file" '
  def expected_criteria:
    [
      "fail-closed-errors",
      "forbidden-scope",
      "frontend-projection",
      "frozen-identity",
      "independent-runner",
      "lease-recovery-idempotency",
      "legacy-path-removal",
      "local-evidence-boundary",
      "postgres-task-ssot",
      "pre-enqueue-binding",
      "protected-test-integrity",
      "same-receipt-projection"
    ];

  .task_id == "C2-V3-INDEPENDENT-REVIEW"
  and .node_id == "C2"
  and .review_scope == "frozen-31-file-c2-v3-candidate"
  and .write_authority == "zero-write"
  and .versions == {plan: 3, dag: 3, interface_freeze: 3, node_contract: 3, ssot_schema: 1}
  and .source_and_evidence_identity.source_manifest_sha256 == "f36330fc9dd994df878e2d4a37deb3bed8fe02ca32c75464a69c786e1691d337"
  and .source_and_evidence_identity.source_file_count == 31
  and .source_and_evidence_identity.contract_sha256 == "35143a0fb22218ebdcf969ee3a137431c37f21f90781db15572909e1dba0ca8b"
  and .source_and_evidence_identity.protected_test_sha256 == "dee8b55304a60b4284462310f68f03099369af15071efc2fe5f39dcc8f67b73d"
  and .source_and_evidence_identity.validation_command_sha256 == "c4761038d60531b50bd0a1f13df8ed287833237172507bb6b1c37501a133248e"
  and .source_and_evidence_identity.validation_log_sha256 == "97849f27db4084181b2370c2e9bdcacfb8525b3ed7279b219b99b255e53c9dba"
  and (.review_completion | IN("done", "partial", "blocked"))
  and (.findings | type == "array")
  and (.criteria | type == "array" and length == 12)
  and (([.criteria[].id] | sort) == expected_criteria)
  and all(.criteria[]; (.status | IN("pass", "finding", "blocked")) and (.evidence | type == "string" and length > 0))
  and (.commands | type == "array" and length > 0)
  and all(.commands[]; (.command | type == "string" and length > 0) and (.exit_code | type == "number") and (.result | type == "string" and length > 0))
  and .actual_write_scope == [$return_file]
  and .forbidden_scope_touched == false
  and (.unverified_items | type == "array")
  and (.acceptance_recommendation | IN("accept-c2-implementation", "repair-c2", "blocked"))
  and (.proposed_state | IN("VERIFIED", "FAILED", "BLOCKED"))
  and (.acceptance_self_check | IN("pass", "fail", "partial"))
  and (.failure_class | IN("none", "implementation", "runtime", "verification", "transport", "architecture-conflict", "authority-conflict", "interface-freeze", "permission", "product-decision", "scope-conflict"))
  and (
    if .acceptance_recommendation == "accept-c2-implementation" then
      .review_completion == "done"
      and .proposed_state == "VERIFIED"
      and .acceptance_self_check == "pass"
      and .failure_class == "none"
      and all(.criteria[]; .status == "pass")
      and all(.findings[]; .blocking == false)
    else true
    end
  )
' "$return_file" >/dev/null

echo "C2_V3_INDEPENDENT_REVIEW_RETURN_VALID"
