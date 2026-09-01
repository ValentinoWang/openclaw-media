# Stage-2 Screenshot Evidence Review

proposed_state: `FAILED`

failure_class: `release-evidence-provenance-and-scope`

failure_origin: `stale-capture-manifest-and-browser-boundary-mock-harness`

## Frozen identity

- Review target and read-only `HEAD`: `main` at `dba33b95e9ca124f22166ca4e34ee6ba27316e31`.
- Manifest: `agents-results/2026-09-01/stage2-document-edit-validation/stage2-document-screenshot-manifest.json:36` records `sourceGitSha=007a7f906af4e23a6a4fa5d041da4cb0641646c2`, not the frozen SHA. Its capture timestamp is `2026-09-01T08:45:35.007Z`; `reviewIdentity` remains `REVIEW_IDENTITY_PLACEHOLDER` (`:41-42`).
- The audited prototype, capture script, slot wrapper, and package-script files are unchanged between the two commits in a read-only Git comparison, but the manifest is still not exactly bound to the frozen source identity. No file-level hash or clean-tree binding repairs that gap.

## Matrix calculation

- The brief declares eight C states and eight B states (`docs/frontend/prototype/stage2-dev-brief.md:5-8`). With four viewports (`1440x900`, `1280x800`, `1024x768`, `390x844`), the declared harness matrix is `(8 + 8) * 4 = 64` cells.
- Independent manifest calculation: `64` unique cells, each state present at all four viewports; `64` primary screenshots plus `8` AI-progress additional screenshots = `72` PNGs. Manifest reports the same (`:9151-9176`).
- C identifiers: `clean`, `dirty`, `conflict`, `unsupported`, `saving`, `aiResultProgress`, `offlineRetry`, `organizationDocument` (`openclaw-bot-center/scripts/qa/captureStage2DocumentScreenshots.ts:169-213`). B identifiers: `synced`, `running`, `unknown`, `conflict`, `unsupported`, `stale`, `aiResultProgress`, `partialApplication`.
- The four `C/organizationDocument` PNGs are byte-for-byte and SHA-256 identical to the four `B/synced` PNGs. Both labels route to `/openclaw/media/organization-workspace/document/stage2b-organization-document` (`captureStage2DocumentScreenshots.ts:611-626, 808-817`; manifest examples `:1024-1056` and `:1166-1198`). This is one captured organization page under two labels, not two independent state proofs.
- The brief says only B `synced` and `stale` are truly achievable in this phase; the other B states must be marked waiting for endpoints (`stage2-dev-brief.md:75-86`). Therefore `24` B cells are scope-overstated as `captured`, although the raw harness matrix is complete.

## Tested conditions and missing conditions

Tested by read-only inspection and independent manifest/filesystem calculation:

- All `64` entries are `captured`; manifest counters are zero for missing, duplicate, unexpected, pending, failed, unexpected-request, unexpected-console, page-error, and failed-check cells (`manifest.json:9151-9167`).
- All `72` listed PNGs exist. Their recorded bytes and SHA-256 values match the files; every width matches its viewport, every height is at least the viewport height, and all pass the nonblank thresholds. The capture checker requires PNG, positive dimensions, at least five colors, and visible pixels (`captureStage2DocumentScreenshots.ts:1006-1079`).
- There are no unexpected request failures or page errors. The manifest nevertheless contains `76` explicitly expected request-failure records across `40` cells and `12` explicitly expected console errors across `12` cells; these are white-listed 409/422, offline, or aborted organization reads, not zero transport events.
- All `506` observed API records are marked `mockedAtBrowserBoundary=true`; no API operation is unmapped. The harness intercepts and synthesizes the session, document, revision, and sync-batch responses (`captureStage2DocumentScreenshots.ts:577-586, 637-757`).

Missing or insufficient conditions:

- No exact frozen-SHA binding, dirty-tree binding, or reviewer identity in the manifest.
- No durable project-local screenshot bundle: the manifest and every PNG path point to `/tmp/openclaw-stage2-document-screenshots-007a7f90` (`manifest.json:8-9, 54-58`). The current host has the files, but the evidence is not portable or self-contained.
- No prototype screenshot hashes, baseline manifest, comparison report, or per-state visual adjudication. The acceptance execution document explicitly requires implementation screenshots to be compared with both prototypes state by state and says that comparison is still pending (`stage2-acceptance-execution.html:397-400`).
- No real B endpoint/device/deployment evidence for the 24 endpoint-dependent B cells. No production or external Feishu proof is present.
- The validator checks recorded metadata and filesystem existence but does not recompute screenshot SHA-256 or pixel metadata for an externally supplied manifest (`captureStage2DocumentScreenshots.ts:1315-1337`). The current files pass an independent recomputation; the reusable gate is weaker than that result.

## Screenshot/prototype comparison coverage

- The C prototype exposes `clean`, `dirty`, `conflict`, `unsupported`, `saving`, `plan`, `offline`, and `org` (`personal-document-editor.html:346-354`). The B prototype exposes `ok`, `run`, `unknown`, `conflict`, `unsupported`, `stale`, `plan`, and `partial` (`organization-document-mirror.html:335-343`).
- The capture harness substitutes `aiResultProgress`/`offlineRetry`/`organizationDocument` for the prototype names and never records a direct `plan` comparison. Its C organization path deliberately calls the B mirror selectors and route (`captureStage2DocumentScreenshots.ts:808-817`). The brief permits a first-phase AI behavior downgrade, but no report records that mapping or its visual differences (`stage2-dev-brief.md:64-68`).
- Result: structural state/selector coverage exists for the generated implementation matrix, but visual comparison coverage is `0/64` documented implementation-to-prototype comparisons. The prototype itself being described as verified is not evidence that these implementation screenshots were compared.

## Severity-first findings

1. **Critical: provenance failure.** The only supplied manifest identifies capture source `007a7f90`, while the required review source is `dba33b95`. This prevents the screenshot set from being released as evidence for the frozen identity.
2. **High: state and scope overclaim.** `C/organizationDocument` is the same organization mirror image as `B/synced` at every viewport. In addition, all six endpoint-dependent B states are marked captured despite the brief requiring them to remain waiting until their integrations exist.
3. **High: required visual comparison is absent.** There is no baseline/reference artifact or per-cell comparison result for the 16 prototype states across four viewports. Nonblank pixels and selector assertions cannot establish layout, copy, or state-machine fidelity.
4. **Medium: evidence is volatile and the generic gate is incomplete.** Screenshots live under `/tmp`; manifest validation verifies existence and self-reported metadata, not digest recomputation. `reviewIdentity` is also a placeholder.
5. **Medium: release automation gap.** `qa:media-stage2-document-screenshots` exists and is wrapped by the Chromium slot helper, but it is not in `build:media` (`openclaw-bot-center/package.json:41-42, 86`). A green media build therefore does not imply this screenshot lane ran.

## Protected-test/harness integrity disposition

**PARTIAL; insufficient for release.** The runtime path uses strict Playwright root, heading, state-anchor, action, and attribute assertions (`captureStage2DocumentScreenshots.ts:778-975`). A capture exception becomes a `failed` entry, and the validator rejects missing cells, duplicate cells, missing screenshots, failed checks, request failures, unexpected console errors, and page errors (`:1340-1431`). The static self-test contains negative fixtures for absent screenshots, missing cells, failed selectors, failures, pending entries, request failures, console errors, page errors, and absent filesystem files (`:1750-1780`).

The Chromium wrapper also propagates child status and fails on invalid concurrency settings, missing `flock`/`lockf`, or slot timeout (`scripts/qa/withChromiumSlot.sh:12-19, 43-50, 53-82`). However, the `renderedCStates` and `renderedBStates` sets are hard-coded to equal the required sets, so pending integration is empty by construction (`captureStage2DocumentScreenshots.ts:190-213`). The harness is fail-closed for absent selectors/screenshots in a captured cell, but it is not fail-closed for stale provenance, visual comparison, digest mutation, or dynamic integration scope.

## Source versus real-device/external boundary

The capture is a local Vite app on `127.0.0.1` with headless Chromium; the script can optionally use an external URL, but this manifest uses the local base URL (`manifest.json:8`, `captureStage2DocumentScreenshots.ts:1565-1624`). API responses are Playwright route fulfillments, and Google Fonts are replaced with an empty CSS response (`:1455-1458`). This proves a reproducible browser-render/selector exercise with synthetic data only. It does not prove a deployed service, real Feishu tenant, real external API, persisted session, physical device, or production behavior. The acceptance document itself keeps these evidence layers separate and says local tests cannot replace real deployment readback (`stage2-acceptance-execution.html:491`).

## Status record

- Business project status observed at final readback: `main...github/main` at the frozen SHA, with existing `M agents-results/2026-08-15/media-c-b-stage-2-content-and-ai-document-routing/.ssot/manifest.json`, existing `M openclaw-tag-router/tests/test_stage2_feishu_hardening.py`, and existing untracked `acceptance/release/`; this lane did not alter those existing changes.
- Harness SSOT status: no separate Harness Git root was discoverable from the project overlay; `develop/Harness` and `.agents/skills` are ordinary project paths rather than symlinks. No Harness source was modified.

Final proposed state: `FAILED`.
