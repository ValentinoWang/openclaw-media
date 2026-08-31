TASK_ID=foundation-auth

Frozen identities: current behavioral authority `84382576a4045a99aea1abb6df848ba95f0bb3d9`; historical visual reference `152206f6` and final stage branch `a0580dec5a33ae5893ad30c551ec7b76ec8ed7ef`; ledger DS-01, DS-03, DS-04, DS-05.

Implement only the missing stage-0 visual foundation on top of current GitHub login behavior. Preserve every current entry-state, history navigation, fallback visibility, safe-next, session parsing, Feishu, timeout, and double-click guard. Do not replace current login JS or HTML with historical files. The current two-column narrative layout, segmented identity choice, bounded form, and full-width primary action should remain.

Make the two auth stylesheets consume the mainline design token source using environment-correct imports and `--auth-*` aliases. Ensure the built release contains the token stylesheet and Nginx plus the auth route contract expose that exact static asset. Keep source/root auth CSS synchronized apart from the one documented import-path difference. Set all letter spacing touched by this lane to `0`; do not introduce negative letter spacing.

Exclusive write scope:
- `openclaw-bot-center/src/media.auth.css`
- `openclaw-bot-center/media.auth.css`
- `openclaw-bot-center/vite.media.config.ts`
- `openclaw-bot-center/deploy/nginx-openclaw-bot-center.conf`
- `openclaw-bot-center/contracts/media-auth-route-contract.json`

Forbidden: `media.login.js`, all auth HTML, package/lockfiles, shared SPA CSS, backend, QA scripts, and git operations.

Acceptance command: `git diff --check -- openclaw-bot-center/src/media.auth.css openclaw-bot-center/media.auth.css openclaw-bot-center/vite.media.config.ts openclaw-bot-center/deploy/nginx-openclaw-bot-center.conf openclaw-bot-center/contracts/media-auth-route-contract.json && diff -u <(tail -n +2 openclaw-bot-center/src/media.auth.css) <(tail -n +2 openclaw-bot-center/media.auth.css)`; adjust the synchronization check only if imports intentionally occupy different line counts, while preserving byte equality after removing exactly those imports.

Do not commit. Write the required structured return.
