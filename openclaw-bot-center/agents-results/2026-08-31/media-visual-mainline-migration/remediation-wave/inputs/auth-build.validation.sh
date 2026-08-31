#!/usr/bin/env bash
set -euo pipefail
npm run qa:media-login-contract
npx tsx scripts/qa/checkMediaLoginContract.ts --self-test
npx oxlint media.login.js scripts/qa/checkMediaLoginContract.ts vite.media.config.ts
node --check media.login.js
git diff --check -- media.login.html media.register.html media.verify.html media.recover.html media.reset.html src/media.verify.html src/media.recover.html src/media.reset.html media.auth.css src/media.auth.css src/media/mediaDesignTokens.css media.login.js vite.media.config.ts scripts/qa/checkMediaLoginContract.ts
cmp -s media.auth.css src/media.auth.css
