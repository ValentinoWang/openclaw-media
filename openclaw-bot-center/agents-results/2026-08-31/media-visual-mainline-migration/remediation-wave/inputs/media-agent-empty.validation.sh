#!/usr/bin/env bash
set -euo pipefail

npx tsx scripts/qa/checkMediaAgentTabOrder.ts
npx tsx scripts/qa/checkMediaAgentTabOrder.ts --self-test
npx oxlint src/media/pages/ordinary/MediaAgentPage.tsx scripts/qa/checkMediaAgentTabOrder.ts
git diff --check -- src/media/pages/ordinary/MediaAgentPage.tsx scripts/qa/checkMediaAgentTabOrder.ts
