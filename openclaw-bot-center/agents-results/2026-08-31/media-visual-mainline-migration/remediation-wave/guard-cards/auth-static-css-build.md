# Auth Static CSS Build Guard

- Stable failure class: Vite/PostCSS treats the root-relative auth token import as a local filesystem import when the fixed auth stylesheet is bundled as a Rollup input.
- Include scope: all eight auth HTML aliases, `media.auth.css`, `src/media.auth.css`, `src/media/mediaDesignTokens.css`, `media.login.js`, and `vite.media.config.ts`.
- Exclude scope: package metadata, unrelated source/tests/evidence, generated `dist-media` content, dependencies, git state, deployment, and network/remotes.
- Red proof: `npx tsx scripts/qa/checkMediaLoginContract.ts --self-test` rejects an in-memory unmarked `<link>`, wrong DS-01 token, unbounded `postJson`, and missing Feishu authorization deduplication.
- Green proof: `npm run qa:media-login-contract`, the same `--self-test`, `npx oxlint media.login.js scripts/qa/checkMediaLoginContract.ts vite.media.config.ts`, `node --check media.login.js`, `git diff --check` on owned files, and `cmp -s media.auth.css src/media.auth.css` pass.
- Failure message: `Failed to resolve /mediaDesignTokens.css from src/media.auth.css` (ENOENT).
- Repair command: `bash agents-results/2026-08-31/media-visual-mainline-migration/remediation-wave/inputs/auth-build.validation.sh`.
- Enforcement point: `scripts/qa/checkMediaLoginContract.ts`, invoked by `qa:media-login-contract` and before the media build contract proceeds.
