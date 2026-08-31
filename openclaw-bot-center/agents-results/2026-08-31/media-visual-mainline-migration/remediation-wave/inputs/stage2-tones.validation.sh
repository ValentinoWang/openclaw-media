#!/usr/bin/env bash
set -euo pipefail
npm run qa:media-primitive-enhancements
npx tsx scripts/qa/checkMediaPrimitiveEnhancements.ts --self-test
npx oxlint src/media/studio/WorkboardPage.tsx scripts/qa/checkMediaPrimitiveEnhancements.ts
git diff --check -- src/media/studio/WorkboardPage.tsx src/media/studio/WorkboardPage.module.css scripts/qa/checkMediaPrimitiveEnhancements.ts
