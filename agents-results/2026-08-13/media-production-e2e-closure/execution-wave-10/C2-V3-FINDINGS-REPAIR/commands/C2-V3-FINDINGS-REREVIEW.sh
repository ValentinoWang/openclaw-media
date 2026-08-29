#!/usr/bin/env bash
set -euo pipefail

project_root="/Users/vsiyo/Desktop/创业项目/自媒体创作Agent"
run_root="$project_root/agents-results/2026-08-13/media-production-e2e-closure/execution-wave-10/C2-V3-FINDINGS-REPAIR"
task_file="$run_root/tasks/C2-V3-FINDINGS-REREVIEW.md"
prompt_file="$run_root/prompts/C2-V3-FINDINGS-REREVIEW.txt"
log_file="$run_root/logs/C2-V3-FINDINGS-REREVIEW.log"
return_file="$run_root/returns/C2-V3-FINDINGS-REREVIEW.json"
launch_ledger="$run_root/ledger/C2-V3-FINDINGS-REREVIEW.launch.json"
complete_ledger="$run_root/ledger/C2-V3-FINDINGS-REREVIEW.complete.json"
wrapper="/Users/vsiyo/.codex/workers/run-l3.sh"
source_manifest="$run_root/baseline/repair-source.sha256"
protected_manifest="$run_root/baseline/protected-assets.sha256"

test ! -e "$return_file"
test "$(shasum -a 256 "$source_manifest" | awk '{print $1}')" = "e70cb4be1ea5d6b75855d87b9680d0d55ff2cd54883e7245348d18844054b55d"
test "$(shasum -a 256 "$protected_manifest" | awk '{print $1}')" = "c3b1b270f0c3348a8614af0b951d03790e2653d33182e6713160db56c7a4b4f2"
test "$(shasum -a 256 "$run_root/logs/C2-V3-FINDINGS-REPAIR.validation.log" | awk '{print $1}')" = "64c2f0dea27589868b6f63b6aec50d7056b05db2f598f218564c3f09e726161b"
test "$(shasum -a 256 "$project_root/agents-results/2026-08-13/media-production-e2e-closure/execution-wave-9/C2-V3-INDEPENDENT-REVIEW/returns/C2-V3-INDEPENDENT-REVIEW.json" | awk '{print $1}')" = "78d3f460f83a10baf4d3d2da5a6dc134bc0e67e2e1a32ac0d1919ce946e7dd2f"
test "$(shasum -a 256 "$wrapper" | awk '{print $1}')" = "67b6c79390710c106431e22cb542b346737d60dd0338e8f7c2f14e2fc73268df"

cd "$project_root"
shasum -a 256 -c "$source_manifest"
shasum -a 256 -c "$protected_manifest"
cp "$task_file" "$prompt_file"
prompt_sha256="$(shasum -a 256 "$prompt_file" | awk '{print $1}')"
started_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

bash "$wrapper" "$(< "$prompt_file")" >"$log_file" 2>&1 &
worker_pid=$!

jq -n \
  --arg task_id "C2-V3-FINDINGS-REREVIEW" \
  --arg wrapper "$wrapper" \
  --arg project_root "$project_root" \
  --arg prompt "$prompt_file" \
  --arg prompt_sha256 "$prompt_sha256" \
  --arg log "$log_file" \
  --arg return_path "$return_file" \
  --arg started_at "$started_at" \
  --argjson pid "$worker_pid" \
  '{task_id:$task_id,attempt:1,wrapper:$wrapper,project_root:$project_root,actual_invocation:"codex exec -C /Users/vsiyo/Desktop/创业项目/自媒体创作Agent --skip-git-repo-check --sandbox danger-full-access",sandbox_authority:"writable sandbox",write_authority:"zero-write",prompt_path:$prompt,prompt_sha256:$prompt_sha256,log_path:$log,return_path:$return_path,pid:$pid,started_at:$started_at,retry_limit:0,launch_barrier:"single independent finding-specific review process registered before wait"}' >"$launch_ledger"

if wait "$worker_pid"; then
  exit_code=0
else
  exit_code=$?
fi

ended_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
session_id="$(sed -n 's/.*session id: *//p' "$log_file" | tail -n 1)"
if test -f "$return_file"; then
  return_state="present"
  return_sha256="$(shasum -a 256 "$return_file" | awk '{print $1}')"
else
  return_state="missing"
  return_sha256=""
fi

rm "$prompt_file"

jq -n \
  --arg task_id "C2-V3-FINDINGS-REREVIEW" \
  --arg prompt_sha256 "$prompt_sha256" \
  --arg log "$log_file" \
  --arg return_path "$return_file" \
  --arg return_state "$return_state" \
  --arg return_sha256 "$return_sha256" \
  --arg session_id "$session_id" \
  --arg started_at "$started_at" \
  --arg ended_at "$ended_at" \
  --argjson pid "$worker_pid" \
  --argjson exit_code "$exit_code" \
  '{task_id:$task_id,attempt:1,pid:$pid,codex_session_id:$session_id,started_at:$started_at,ended_at:$ended_at,exit_code:$exit_code,prompt_sha256:$prompt_sha256,prompt_cleanup:"deleted",runtime_handle_cleanup:"wait completed",codex_transcript_retention:"preserved",log_path:$log,return_path:$return_path,return_state:$return_state,return_sha256:$return_sha256}' >"$complete_ledger"

exit "$exit_code"
