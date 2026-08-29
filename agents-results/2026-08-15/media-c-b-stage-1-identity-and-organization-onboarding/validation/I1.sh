#!/usr/bin/env bash
set -euo pipefail

root="/Users/vsiyo/Desktop/创业项目/自媒体创作Agent/.codex-work/stage1-i1/frontend"
cd "$root"
npx tsx scripts/qa/checkStage1IdentityEntry.ts
exec npm run build:media
