#!/usr/bin/env bash
set -euo pipefail

project_root="/Users/vsiyo/Desktop/创业项目/自媒体创作Agent/.codex-work/openclaw-mainline-frontend/openclaw-bot-center"
review_root="$project_root/agents-results/2026-08-31/media-visual-mainline-migration/final-review"
wrapper="/Users/vsiyo/.codex/workers/run-l3.sh"
ledger="$review_root/process-ledger.tsv"

printf 'task_id\twrapper\tproject_root\tsandbox\tprompt_sha256\tpid\tstarted_at\texited_at\texit_code\tlog\treturn\n' > "$ledger"

pids=()
tasks=(stage-0 stage-1 stage-2 stage-3)
for task_id in "${tasks[@]}"; do
  prompt="$review_root/prompts/$task_id.txt"
  log="$review_root/logs/$task_id.log"
  return_path="$review_root/returns/$task_id.md"
  prompt_sha="$(shasum -a 256 "$prompt" | awk '{print $1}')"
  started_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  (
    cd "$project_root"
    exec bash "$wrapper" "$(< "$prompt")"
  ) > "$log" 2>&1 &
  pid=$!
  pids+=("$pid")
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t\t\t%s\t%s\n' \
    "$task_id" "$wrapper" "$project_root" "writable sandbox; zero-write authority" \
    "$prompt_sha" "$pid" "$started_at" "$log" "$return_path" >> "$ledger"
done

status=0
for index in "${!pids[@]}"; do
  task_id="${tasks[$index]}"
  pid="${pids[$index]}"
  if wait "$pid"; then
    exit_code=0
  else
    exit_code=$?
    status=1
  fi
  exited_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  awk -F '\t' -v OFS='\t' -v task="$task_id" -v ended="$exited_at" -v code="$exit_code" \
    'NR == 1 { print; next } $1 == task { $8 = ended; $9 = code } { print }' "$ledger" > "$ledger.next"
  mv "$ledger.next" "$ledger"
done

exit "$status"
