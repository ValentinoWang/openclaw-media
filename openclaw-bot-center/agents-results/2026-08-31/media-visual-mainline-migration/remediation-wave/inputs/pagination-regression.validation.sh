#!/usr/bin/env bash
set -euo pipefail
npm run qa:track-relationship-presentation
npm run qa:media-ordinary-presentation
npx oxlint src/media/pages/ordinary/TracksPage.tsx src/media/pages/ordinary/PublishingPage.tsx src/media/pages/ordinary/InvitesPage.tsx
git diff --check -- src/media/pages/ordinary/TracksPage.tsx src/media/pages/ordinary/PublishingPage.tsx src/media/pages/ordinary/InvitesPage.tsx
