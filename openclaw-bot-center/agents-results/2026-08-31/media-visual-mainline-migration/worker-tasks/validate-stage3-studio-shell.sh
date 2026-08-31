#!/usr/bin/env bash
set -euo pipefail

git diff --check -- \
  openclaw-bot-center/src/media/MediaStudioApp.tsx \
  openclaw-bot-center/src/media/mediaStudioTheme.css \
  openclaw-bot-center/scripts/qa/checkMediaStudioShellContract.ts

cd openclaw-bot-center
npx tsx scripts/qa/checkMediaStudioRouteMatrix.ts
npx tsx scripts/qa/checkMediaStudioShellContract.ts
! rg -n 'letter-spacing:\s*-' src/media/mediaStudioTheme.css
