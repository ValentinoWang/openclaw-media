# Stage 0 Independent Zero-Write Review

## Findings

- [P1] Mobile organization P2 has an incoherent overlap. The `:has()` selected-state rule keeps `.choice-grid` at `minmax(0, 1fr) auto` (`media.auth.css:339`), which outranks the mobile `grid-template-columns: 1fr` override (`media.auth.css:701`). The unselected personal option remains in the narrow auto track and is visibly painted behind the selected organization card in `runtime-auth/green-final/login-organization-expired-390x844.png` (390x1203). The deployed `src/media.auth.css:339` is byte-identical.
- [P1] The required visual runtime gate did not execute (`scripts/qa/checkMediaLoginVisualRuntime.ts:443`). The exact command exited 1 before the test started: `lockf: tsx: No such file or directory`. This is a review-environment launch failure, not a passing runtime result.
- [P2] The protected visual assertion does not detect the reported defect (`scripts/qa/checkMediaLoginVisualRuntime.ts:124`). It checks horizontal bounds, interactive-control centers, and initial P1 height, but does not compare visible content boxes or detect noninteractive text overlap. The contract mutation self-tests exist at `scripts/qa/checkMediaLoginContract.ts:82`, but are conditional on `--self-test` and were not part of the required npm invocation.

## Frozen Identity

- HEAD (verified): `84382576a4045a99aea1abb6df848ba95f0bb3d9`.
- Tracked binary diff SHA-256 (recomputed): `ace6f0e42673be77c51de25895232eb88c10259add95c3297d079d17d09aaff9`.
- Frozen untracked source/QA content-list SHA-256: `78211727684da2613517c1e5ea68d7c17ada7fd1da6ac4a176cd680548430ce4`.
- Frozen combined task path-set SHA-256: `744982513e6ebd69f0957cb39a19274627fb73869a2ff9778d030cbc209b992d`.

## Scope And Gates

- `stage-paths.tsv` contains 17 `stage-0` paths. Scoped status is 16 modified tracked paths plus the untracked visual QA script.
- `npm run qa:media-login-contract` -> exit 0: passed.
- `MEDIA_LOGIN_VISUAL_QA_OUTPUT=/tmp/openclaw-review-181536-stage0 bash scripts/qa/withChromiumSlot.sh -- tsx scripts/qa/checkMediaLoginVisualRuntime.ts` -> exit 1: wrapper could not resolve `tsx`; no substitute gate was run.
- `npx oxlint --deny-warnings media.login.js scripts/qa/checkMediaLoginContract.ts scripts/qa/checkMediaLoginVisualRuntime.ts vite.media.config.ts` -> exit 0.
- `git diff --check --` the 17 manifest paths -> exit 0.
- No `build:media`, broad repository scan, history lookup, external service, or prior reviewer log was used.

## DS-01 To DS-05

- Token aliases: static pass. Both auth CSS aliases import `/mediaDesignTokens.css` (`media.auth.css:1`); Vite resolves and copies the source token file (`vite.media.config.ts:11`, `vite.media.config.ts:42`); Nginx serves the same root asset (`deploy/nginx-openclaw-bot-center.conf:67`). Approved token values are present in `src/media/mediaDesignTokens.css:20` and `:75`.
- Five auth surfaces: static surface set is present: login, register, verify, recover, and reset. Canonical routes and static assets are declared in `contracts/media-auth-route-contract.json:4`; Vite inputs and post-build names are wired in `vite.media.config.ts:54`; exact Nginx routes are present at `deploy/nginx-openclaw-bot-center.conf:26`.
- P1/P2 semantics: source and contract assertions cover choice-before-query, selected entry-state fallback/match, keyboard mode selection, and fallback controls (`media.login.js:231`, `media.login.js:361`, `scripts/qa/checkMediaLoginVisualRuntime.ts:183`). Supplied P1 and personal P2 PNGs render without visible overlap; organization P2 exposes the P1 finding above.
- History and deep links: same-origin media-only `next` fencing is implemented (`media.login.js:19`); mode uses push/replace state and popstate restoration (`media.login.js:165`, `media.login.js:449`). Nginx exact routes and Vite inputs are statically aligned. Root/source verify, recover, and reset differences are only font preload tags.
- Timeout and stale-request fences: the 5-second `AbortController` helper is used by POST and session reads (`media.login.js:58`, `media.login.js:138`); entry-state and organization authorization runs are checked (`media.login.js:177`, `media.login.js:257`). The visual test source includes timeout, stale-entry, and reselection scenarios (`scripts/qa/checkMediaLoginVisualRuntime.ts:275`). Current execution evidence is unavailable because the required visual gate failed to launch.
- Repeat-organization authorization: deduplication, busy-state locking, run invalidation, and fresh reselection are present (`media.login.js:247`, `media.login.js:257`, `media.login.js:394`); the dedicated scenario is defined at `scripts/qa/checkMediaLoginVisualRuntime.ts:334`.

## Visual Evidence

The permitted `runtime-auth/green-final` directory contains 19 PNGs. Inspected representatives include desktop/mobile P1, personal P2 mobile, organization matched desktop, organization expired mobile, reselection desktop, and register/verify/reset mobile. The auth surfaces are generally bounded and legible; only organization expired mobile shows the documented overlap. These are supplied evidence, not a replacement for the failed current visual gate.

## Protected-Test Integrity

The required contract gate passed and checks all eight HTML aliases, byte-identical auth CSS aliases, token wiring, bounded requests, and organization authorization locking. The scoped test files were not removed or bypassed. Residual integrity risk is that mutation fixtures require an optional flag and the visual layout assertion omits noninteractive overlap.

## Residual Risk

`roleLanding()` only special-cases admin and otherwise returns `safeUserNext()` (`media.login.js:138`); it does not itself select the blueprint default `/organization-workspace` for an organization session. The later dispatcher was outside the permitted Stage 0 read set, so this route handoff remains unverified. No backend, deployed, or device readback was performed.

## Actual Write Scope

Only this report was intentionally written: `agents-results/2026-08-31/media-visual-mainline-migration/final-review/runs/20260831T181536+0800/returns/stage-0.md`. No source, test, config, git index, commit, or existing evidence was modified. The requested `/tmp/openclaw-review-181536-stage0` output was not populated because the visual wrapper failed before test startup.

failure_class: mobile-auth-layout-regression; required-visual-gate-launch-failure
failure_origin: CSS cascade in the frozen source; review-shell PATH resolution for local `tsx`

Final decision: NOT READY
