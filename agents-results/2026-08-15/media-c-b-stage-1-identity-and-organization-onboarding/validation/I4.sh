#!/usr/bin/env bash
set -euo pipefail
cd /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/.codex-work/stage1-i4/frontend
npm run build:media
npx tsx scripts/qa/checkPersonalWorkspaceShell.ts
