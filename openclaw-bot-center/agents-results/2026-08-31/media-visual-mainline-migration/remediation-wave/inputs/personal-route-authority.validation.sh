#!/usr/bin/env bash
set -euo pipefail

npx tsx scripts/qa/checkMediaStudioRouteMatrix.ts
npx tsc -b tsconfig.media-u12b.json --pretty false
npx oxlint src/media/mediaStudioRoutePolicy.ts src/media/MediaStudioApp.tsx scripts/qa/checkMediaStudioRouteMatrix.ts
git diff --check -- src/media/mediaStudioRoutePolicy.ts src/media/MediaStudioApp.tsx scripts/qa/checkMediaStudioRouteMatrix.ts agents-results/2026-08-31/media-visual-mainline-migration/remediation-wave/guard-cards/personal-route-authority.md
