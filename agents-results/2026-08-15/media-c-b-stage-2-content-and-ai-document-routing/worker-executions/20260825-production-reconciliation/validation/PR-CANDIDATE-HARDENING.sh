#!/usr/bin/env bash
set -euo pipefail
repo='/Users/vsiyo/Desktop/创业项目/自媒体创作Agent/.codex-work/production-reconciliation-20260825'
candidate='/tmp/openclaw-stage2-handoff-final-20260819/openclaw-tag-router'
test "$(git -C "$repo" rev-parse HEAD)" = '5f06780569568ccc3197f0ab16aad74bdf9d1c6f'
test -z "$(git -C "$repo" status --porcelain=v1)"
actual="$(ssh -o BatchMode=yes ubuntu@106.52.146.37 "git -C '$candidate' diff --binary" | shasum -a 256 | awk '{print $1}')"
test "$actual" = 'ed9021a266600014bf1efe287b9dd10a38854059dbd4b2305a58285877c9e7e9'
