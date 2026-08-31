#!/usr/bin/env bash
set -euo pipefail

npm run qa:media-admin-access-contract
npx tsx scripts/qa/checkMediaAdminAccessContract.ts --self-test
npx oxlint src/media/pages/admin/AdminAccessPage.tsx scripts/qa/checkMediaAdminAccessContract.ts
git diff --check -- src/media/pages/admin/AdminAccessPage.tsx scripts/qa/checkMediaAdminAccessContract.ts
