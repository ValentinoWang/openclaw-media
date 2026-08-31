#!/usr/bin/env bash
set -euo pipefail
cd /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/.codex-work/openclaw-mainline-frontend/openclaw-bot-center
git diff --check -- scripts/qa/checkMediaPrimitiveAdoption.ts
npx tsx scripts/qa/checkMediaPrimitiveAdoption.ts
npx tsx scripts/qa/checkMediaPrimitiveAdoption.ts --self-test
