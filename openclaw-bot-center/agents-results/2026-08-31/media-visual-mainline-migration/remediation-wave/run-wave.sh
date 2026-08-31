#!/usr/bin/env bash
set -euo pipefail
root="$(pwd -P)"
wrapper="/Users/vsiyo/.codex/workers/run-lw-luna.sh"
wave="$root/agents-results/2026-08-31/media-visual-mainline-migration/remediation-wave"
ledger="$wave/ledger/processes.tsv"
: > "$ledger"
: > "$wave/ledger/exits.tsv"
printf 'task\tpid\tstarted_at\tprompt_sha256\tlog\n' >> "$ledger"
printf 'task\texit_code\texited_at\n' >> "$wave/ledger/exits.tsv"
tasks=(foundation-visual canonical-renderer admin-billing admin-upstreams archives publishing personal-metric-router organization-pagegate adoption-contract)
pids=()
for task in "${tasks[@]}"; do
  prompt="$wave/prompts/$task.txt"
  log="$wave/logs/$task.log"
  prompt_hash="$(shasum -a 256 "$prompt" | awk '{print $1}')"
  (
    cd "$root"
    exec bash "$wrapper" "$(< "$prompt")"
  ) > "$log" 2>&1 &
  pid=$!
  pids+=("$pid")
  printf '%s\t%s\t%s\t%s\t%s\n' "$task" "$pid" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$prompt_hash" "$log" >> "$ledger"
done
status=0
for index in "${!tasks[@]}"; do
  task="${tasks[$index]}"
  pid="${pids[$index]}"
  if wait "$pid"; then
    code=0
  else
    code=$?
    status=1
  fi
  printf '%s\t%s\t%s\n' "$task" "$code" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$wave/ledger/exits.tsv"
done
exit "$status"
