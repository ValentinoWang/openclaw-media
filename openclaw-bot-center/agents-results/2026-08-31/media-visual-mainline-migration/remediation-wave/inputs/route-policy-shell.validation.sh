#!/usr/bin/env bash
set -euo pipefail
npm run qa:media-route-matrix
npm run qa:media-shell-contract
npx oxlint src/media/mediaStudioRoutePolicy.ts src/media/MediaStudioApp.tsx src/media/WorkspaceShellPage.tsx scripts/qa/checkMediaStudioRouteMatrix.ts scripts/qa/checkMediaStudioShellContract.ts
git diff --check -- src/media/mediaStudioRoutePolicy.ts src/media/MediaStudioApp.tsx src/media/WorkspaceShellPage.tsx src/media/mediaStudioTheme.css scripts/qa/checkMediaStudioRouteMatrix.ts scripts/qa/checkMediaStudioShellContract.ts
