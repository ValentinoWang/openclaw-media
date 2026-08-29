#!/usr/bin/env bash
set -euo pipefail

project_root="/Users/vsiyo/Desktop/创业项目/自媒体创作Agent"
frontend_root="$project_root/.codex-work/stage1-i1/frontend"
qa_file="$frontend_root/scripts/qa/checkDeletionIntentLifecycle.ts"

cd "$frontend_root"

if rg -n '/home/ubuntu' "$qa_file"; then
  printf 'portable deletion QA output check failed: /home/ubuntu remains\n' >&2
  exit 1
fi
rg -F 'import { tmpdir } from "node:os";' "$qa_file" >/dev/null
rg -F 'join(tmpdir(),' "$qa_file" >/dev/null

test "$(shasum -a 256 scripts/qa/withChromiumSlot.sh | awk '{print $1}')" = "b43072de2367e5c5e41e1d549393976272409ec575baa2d90e53435d0e23581f"
test "$(shasum -a 256 scripts/qa/checkChromiumSlotContract.sh | awk '{print $1}')" = "f9b974921ee1bf3d32e0fd64178252acc5a924a867ddd63f93df337606ae9468"
test "$(shasum -a 256 package.json | awk '{print $1}')" = "2d2a10a68bee189af24811ce4f314d60ae7af7450f61afb4f37ba8c849036c41"
test "$(shasum -a 256 package-lock.json | awk '{print $1}')" = "f3dd4e9e3671ff2d774938b96bfacf083bdfaad454ee19d8effc9d5b96541dd7"

exec bash "$project_root/agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/validation/I1.sh"
