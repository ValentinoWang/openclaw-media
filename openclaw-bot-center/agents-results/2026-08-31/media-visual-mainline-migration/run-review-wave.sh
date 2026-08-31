#!/usr/bin/env bash
set -euo pipefail

project_root="/Users/vsiyo/Desktop/创业项目/自媒体创作Agent/.codex-work/openclaw-mainline-frontend"
app_root="$project_root/openclaw-bot-center"
evidence_root="$app_root/agents-results/2026-08-31/media-visual-mainline-migration"
manifest="$evidence_root/review-manifest.tsv"
wrapper="/Users/vsiyo/.codex/workers/run-l2.sh"
baseline="84382576a4045a99aea1abb6df848ba95f0bb3d9"
review_root="$evidence_root/review-artifacts-l2"

test -x "$wrapper"
test "$(wc -l < "$manifest" | tr -d ' ')" = "30"
mkdir -p "$review_root/prompts" "$review_root/logs" "$review_root/returns" "$review_root/runtime"
: > "$review_root/runtime/launch.tsv"

source_hash_before="$(git -C "$project_root" diff --no-ext-diff --binary -- openclaw-bot-center/src openclaw-bot-center/scripts openclaw-bot-center/contracts openclaw-bot-center/deploy openclaw-bot-center/media.auth.css openclaw-bot-center/media.login.js openclaw-bot-center/package.json openclaw-bot-center/vite.media.config.ts | shasum -a 256 | awk '{print $1}')"
printf '%s\n' "$source_hash_before" > "$review_root/runtime/source-diff-before.sha256"

pids=()
ids=()
while IFS=$'\t' read -r task_id relative_paths; do
  task_spec="$evidence_root/worker-tasks/$task_id.md"
  implementation_return_root="$evidence_root/worker-artifacts/$task_id/returns"
  test -s "$task_spec"
  implementation_returns="$(find "$implementation_return_root" -maxdepth 1 -name '*.json' -type f 2>/dev/null | sort | tr '\n' ' ')"
  if [ -z "$implementation_returns" ]; then
    implementation_returns="none; review the frozen source diff and task acceptance commands directly"
  fi

  prompt="$review_root/prompts/review-$task_id.txt"
  return_path="$review_root/returns/review-$task_id.json"
  log_path="$review_root/logs/review-$task_id.log"
  rm -f "$return_path"
  owned_paths=""
  for relative_path in $relative_paths; do
    owned_paths="$owned_paths openclaw-bot-center/$relative_path"
  done
  scoped_diff_hash="$(git -C "$project_root" diff --no-ext-diff --binary "$baseline" -- $owned_paths | shasum -a 256 | awk '{print $1}')"

  printf '%s\n' \
    "TASK_ID=review-$task_id" \
    "AUTHORITY=zero-write independent review" \
    "PROJECT_ROOT=$project_root" \
    "BASELINE=$baseline" \
    "TASK_SPEC=$task_spec" \
    "IMPLEMENTATION_RETURNS=$implementation_returns" \
    "OWNED_PATHS=$owned_paths" \
    "SCOPED_DIFF_SHA256=$scoped_diff_hash" \
    "STRUCTURED_RETURN_PATH=$return_path" \
    "" \
    "Review only this frozen implementation lane. Do not edit, create, delete, format, stage, or commit source, tests, contracts, evidence, or git state; the sole authorized write is STRUCTURED_RETURN_PATH. Read only TASK_SPEC, the listed implementation-return JSON files, OWNED_PATHS, src/media/mediaPrimitives.css, src/media/mediaDesignTokens.css, src/media/mediaStudioTheme.css, and direct imported helpers or types needed to judge this lane. Do not run repository-wide rg, find, git status, or inspect agents-results logs, ledgers, prompts, or sibling task artifacts. Check behavior preservation, required state branches, shared-primitive semantic fit, ownership/accent/prelude attribution, accessibility, responsive risks, and out-of-scope changes. Run git diff --check for OWNED_PATHS and at most the task's narrow acceptance command. Do not claim browser or release proof from static review. Finish promptly with the structured return; do not dump whole source files into the log." \
    "" \
    "Write exactly one JSON object to STRUCTURED_RETURN_PATH with: task_id, decision (PASS or FAIL), scoped_diff_sha256, findings (array of objects with severity, path, line, title, detail), checks (array), and residual_risks (array). A warning that does not violate the task may remain residual risk; any behavior regression, missing required state/attribute, invalid primitive use, or scope violation is FAIL." \
    > "$prompt"
  prompt_hash="$(shasum -a 256 "$prompt" | awk '{print $1}')"

  (
    cd "$project_root"
    exec bash "$wrapper" "$(< "$prompt")"
  ) </dev/null > "$log_path" 2>&1 &
  pids+=("$!")
  ids+=("$task_id")
  printf '%s\t%s\t%s\t%s\t%s\n' "$task_id" "$!" "$scoped_diff_hash" "$prompt_hash" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$review_root/runtime/launch.tsv"
done < "$manifest"

expected_count="$(wc -l < "$manifest" | tr -d ' ')"
if [ "${#pids[@]}" -ne "$expected_count" ]; then
  printf 'review launch count mismatch: expected=%s actual=%s\n' "$expected_count" "${#pids[@]}" >&2
  kill "${pids[@]}" 2>/dev/null || true
  wait "${pids[@]}" 2>/dev/null || true
  exit 1
fi
printf 'REVIEW_LAUNCH_BARRIER count=%s\n' "${#pids[@]}"
failed=0
for index in "${!pids[@]}"; do
  if wait "${pids[$index]}"; then
    printf 'REVIEW_FINISHED %s exit=0\n' "${ids[$index]}"
  else
    code=$?
    printf 'REVIEW_FINISHED %s exit=%s\n' "${ids[$index]}" "$code"
    failed=1
  fi
done

source_hash_after="$(git -C "$project_root" diff --no-ext-diff --binary -- openclaw-bot-center/src openclaw-bot-center/scripts openclaw-bot-center/contracts openclaw-bot-center/deploy openclaw-bot-center/media.auth.css openclaw-bot-center/media.login.js openclaw-bot-center/package.json openclaw-bot-center/vite.media.config.ts | shasum -a 256 | awk '{print $1}')"
printf '%s\n' "$source_hash_after" > "$review_root/runtime/source-diff-after.sha256"
if [ "$source_hash_before" != "$source_hash_after" ]; then
  printf 'source diff changed during zero-write review wave\n' >&2
  failed=1
fi

while IFS=$'\t' read -r task_id _relative_paths; do
  return_path="$review_root/returns/review-$task_id.json"
  if ! jq -e --arg task_id "review-$task_id" '.task_id == $task_id and (.decision == "PASS" or .decision == "FAIL") and (.findings | type == "array") and (.checks | type == "array") and (.residual_risks | type == "array")' "$return_path" >/dev/null; then
    printf 'invalid review return: %s\n' "$return_path" >&2
    failed=1
  fi
  rm -f "$review_root/prompts/review-$task_id.txt"
done < "$manifest"

exit "$failed"
