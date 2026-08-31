#!/usr/bin/env bash
set -euo pipefail

npx tsx scripts/qa/checkMediaPageRestorationStructure.ts
npx tsx scripts/qa/checkMediaPageRestorationStructure.ts --self-test
npx oxlint src/media/pages/admin/AdminOverviewPage.tsx scripts/qa/checkMediaPageRestorationStructure.ts
git diff --check -- src/media/pages/admin/AdminOverviewPage.tsx scripts/qa/checkMediaPageRestorationStructure.ts
