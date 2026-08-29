#!/usr/bin/env bash
set -euo pipefail

return_file=agents-results/2026-08-13/media-production-e2e-closure/execution-wave-3/B4-REVIEW/returns/B4-REVIEW.json

jq -e '
  .task_id == "B4-REVIEW" and
  .review_scope == "B4-only" and
  .write_authority == "zero-write" and
  .completion == "done" and
  .acceptance_recommendation == "accept-B4" and
  .acceptance_self_check == "pass" and
  .failure_class == "none" and
  .forbidden_scope_touched == false and
  (.actual_write_scope | type == "array" and length == 1) and
  (.criteria | type == "array" and length >= 10) and
  (all(.criteria[]; .status == "pass")) and
  (.commands | type == "array" and length >= 1) and
  (any(.commands[]; (.command | contains("(first invocation)")) and .exit_code == 4)) and
  (any(.commands[]; (.command | contains("(unchanged retry)")) and .exit_code == 0)) and
  (any(.commands[]; (.command | startswith("bash agents-results/2026-08-13/media-production-e2e-closure/execution-wave-3/commands/B4-R2.sh")) and .exit_code == 0)) and
  (.unverified_items | type == "array" and length >= 5)
' "$return_file" >/dev/null

bash agents-results/2026-08-13/media-production-e2e-closure/execution-wave-3/commands/B4-R2.sh

printf 'B4_REVIEW_VALIDATION_PASS\n'
