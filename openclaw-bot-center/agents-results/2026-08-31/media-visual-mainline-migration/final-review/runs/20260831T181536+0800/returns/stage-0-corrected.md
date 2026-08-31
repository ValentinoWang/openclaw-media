# Stage 0 Corrected Independent Zero-Write Review

## Findings

None. No blocking findings remain within the frozen Stage 0 scope. Fresh evidence closes all prior findings in the reviewed return.

## Frozen hashes

- Baseline HEAD: `84382576a4045a99aea1abb6df848ba95f0bb3d9`; live `git rev-parse HEAD` matches.
- Tracked binary diff SHA-256: `ff23fd7f474f04529781e48d17b83f0a0ae43bea0b6c732b1a17ea8a0a25e146`.
- Untracked source/QA content-list SHA-256: `c9790d4ecbc2a51dc659bc24d948b026809d6ac9cf305e8b1e5798a7075886ca`.
- Combined 93-path set SHA-256: `744982513e6ebd69f0957cb39a19274627fb73869a2ff9778d030cbc209b992d`.
- Stage 0 scoped content/diff stream SHA-256: `1611be335b942d49bf17f9d000cac759c32d3a20717b4551ba411299bc6c3538`.
- Freeze records Stage 0 as the only invalidated review surface.

## 17-path scope

Frozen manifest `.../final-review/runs/20260831T162602+0800/stage-paths.tsv:1-17`; unified ledger Stage 0 block `.../final-review/process-ledger.tsv:2`.

1. `contracts/media-auth-route-contract.json`
2. `deploy/nginx-openclaw-bot-center.conf`
3. `media.auth.css`
4. `media.login.html`
5. `media.login.js`
6. `media.recover.html`
7. `media.register.html`
8. `media.reset.html`
9. `media.verify.html`
10. `scripts/qa/checkMediaLoginContract.ts`
11. `scripts/qa/checkMediaLoginVisualRuntime.ts`
12. `src/media.auth.css`
13. `src/media.recover.html`
14. `src/media.reset.html`
15. `src/media.verify.html`
16. `src/media/mediaDesignTokens.css`
17. `vite.media.config.ts`

## Commands and exits

- `npm run qa:media-login-contract` -> `0` (`media login contract QA passed`).
- `MEDIA_LOGIN_VISUAL_QA_OUTPUT=/tmp/openclaw-review-stage0-corrected bash scripts/qa/withChromiumSlot.sh -- npx tsx scripts/qa/checkMediaLoginVisualRuntime.ts` -> `0`; output reports `ok: true`, viewports `1440x900` and `390x844`, `authPageSmoke: 8`.
- `npx oxlint --deny-warnings media.login.js scripts/qa/checkMediaLoginContract.ts scripts/qa/checkMediaLoginVisualRuntime.ts vite.media.config.ts` -> `0`.
- `cmp media.auth.css src/media.auth.css` -> `0`.
- `git diff --check --` the 17 manifest paths -> `0`.
- No `build:media` or external service was run.

## DS-01..DS-05

- `DS-01`: pass. Exact approved token values are present in `src/media/mediaDesignTokens.css:75-97`; auth aliases import them at `media.auth.css:1-17`, Vite resolves/copies them (`vite.media.config.ts:9-12`, `:35-42`), and Nginx serves the root token asset (`deploy/nginx-openclaw-bot-center.conf:67-71`). The contract checker asserts the three values (`checkMediaLoginContract.ts:34-44`).
- `DS-02`: pass. The five login surfaces and canonical route/static-asset declarations are aligned in the route contract, Vite inputs, Nginx exact routes, and the eight HTML aliases checked by `checkMediaLoginContract.ts:4-24,119-130`.
- `DS-03`: pass. Login starts at P1 without entry or Feishu requests, then covers personal/organization P2 states, fallback controls, keyboard selection, and history (`checkMediaLoginVisualRuntime.ts:200-227,252-305`; `media.login.js:361-458`).
- `DS-04`: pass. Same-origin media-only `next` fencing and mode `pushState`/`replaceState` plus `popstate` restoration are implemented (`media.login.js:19-34,165-175,449-458`) and statically routed.
- `DS-05`: pass. Five-second aborts cover shared POST/session/entry requests; stale entry and organization runs are fenced and organization starts are deduplicated/busy-locked (`media.login.js:58-76,177-189,231-303`; `checkMediaLoginVisualRuntime.ts:311-408`).

## Red / green visual evidence

- Red baseline: `runtime-auth/green-final/login-organization-expired-390x844.png` visibly paints the personal option behind the selected organization card at 390px.
- Green capture: `/tmp/openclaw-stage0-overlap-green-final/login-organization-expired-390x844.png` places the personal option and selected organization card in separate vertical rows with no visible intersection.
- Current runtime geometry filters visible, nonzero `.identity-choice-button` elements and rejects pairwise intersections on both axes greater than 1px (`checkMediaLoginVisualRuntime.ts:124-169`). The organization expired 390px case is included in the matrix (`:252-272`).
- The synthetic old-CSS injection restores `minmax(0, 1fr) auto` with `!important`; `assert.rejects` requires the layout assertion to report identity-choice overlap (`:233-246`). The green exit proves this negative proof ran and passed.

## Prior-finding disposition

- Mobile cascade overlap: closed. The more-specific selected-state rule at `media.auth.css:339-342` is overridden by the later mobile rule at `:705-707`; `cmp` proves the `src/` copy is identical.
- Malformed reviewer launch: closed. The mandated command resolves the local runner through `npx tsx` and exits 0.
- Assertion gap: closed. Runtime visible-choice intersection checks and the synthetic old-CSS rejection are now protected in the executed gate.

## Integrity

The frozen source/test/config scope remained intact: scoped status was the expected 16 modified tracked paths plus the untracked visual checker; the five required gates passed, CSS aliases are byte-identical, and scoped whitespace validation passed. No source, test, config, git index, history, or existing evidence was modified by this review.

## Residual risk

This is mocked local Chromium evidence, not authenticated backend, deployed-host, real Feishu, production, or physical-device readback. `roleLanding()` ordinary-user routing beyond the fenced `next` target remains outside the 17-path scope. These limits are deliberately unverified because the request forbids builds, external services, and broader reads.

## Actual write scope

Only `agents-results/2026-08-31/media-visual-mainline-migration/final-review/runs/20260831T181536+0800/returns/stage-0-corrected.md` was intentionally written. The required visual command emitted its declared temporary output under `/tmp/openclaw-review-stage0-corrected`; no repository source/test/config/git write occurred.

failure_class: mobile-auth-layout-regression; visual-gate-launch-resolution-failure; runtime-assertion-gap (all closed)
failure_origin: selected-state `:has()` cascade outranked the old mobile rule; the prior launch used bare `tsx`; the prior geometry guard omitted visible identity-choice intersections.

Final decision: READY
