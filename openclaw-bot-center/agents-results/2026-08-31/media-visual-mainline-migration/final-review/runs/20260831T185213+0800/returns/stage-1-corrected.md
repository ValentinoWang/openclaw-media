# Corrected Stage 1 independent release review

## Findings

- RESOLVED BLOCKING (prior), `src/media/pages/ordinary/RunsPage.tsx:470,539,590,721-785`: list, opportunity, delivery, section, source, decision, and output empty branches now render through `SurfaceState`; actionable empty branches use `mg-btn`.
- RESOLVED BLOCKING (prior), `src/media/pages/ordinary/PublishingPage.tsx:204-224`: empty publishing-package list and detail branches now render through `SurfaceState`; the list refresh control uses the shared `mg-btn` class family.
- No current blocking finding.

## Frozen identity

- HEAD: `84382576a4045a99aea1abb6df848ba95f0bb3d9` (re-read with `git rev-parse HEAD`).
- Tracked diff SHA-256: `a6b20db4742c0571b1dfb3cec690c380afac0e7859ab205907665407673e556a` (re-read from the current binary diff).
- Untracked source content-list SHA-256: `379184757152e404c32bc9675ae81d6eb4e83d1a2f3df26c1b826b2a9701b916`.
- Combined path-set SHA-256: `744982513e6ebd69f0957cb39a19274627fb73869a2ff9778d030cbc209b992d`.
- Stage 1 manifest count: `66`.

## DS-06 to DS-17

- DS-06: `RunsPage.tsx:470,539,590,721-785` and `PublishingPage.tsx:204-224` use `SurfaceState` for matching resource-empty branches; `InvitesPage.tsx:419-421` uses an explicit `.mg-state` wrapper plus `SurfaceState`.
- DS-07: shared `Metric` consumer is present in `src/media/ui/Metric.tsx:25-45` and route consumers, including Runs facts at `RunsPage.tsx:692-704`.
- DS-08 through DS-11: shared panel, button, tab, hero, and eyebrow markers are present in the declared route sources; the adoption and restoration gates are green.
- DS-12 through DS-16: declared consumers carry accent/tone, badge, pill-tab, and shared-button markers; the adoption coverage gate reports complete eligible-surface coverage.
- DS-17: `CanonicalDocumentRenderer.tsx:57` uses `.mg-state` with `.mg-state-art` for unavailable image resources; `SurfaceState.tsx:61-75` is the canonical state renderer.
- Runs resource-state actions at `RunsPage.tsx:776,784,803-813` and Publishing actions at `PublishingPage.tsx:156,160,162,246` use `mg-btn` classes where actions exist.

## Commands and exits

- `npm run qa:media-primitive-adoption` - exit `0`.
- `npm run qa:media-primitive-adoption-self-test` - exit `0`.
- `npm run qa:media-primitive-coverage` - exit `0`.
- `npm run qa:media-page-restoration-structure` - exit `0`; B-GATE self-test PASS and real-source GREEN.
- `npm run qa:media-admin-access-contract` - exit `0`; PASS, IF2 operations=8, mutations=5, plaintextCodes=0.
- `npm run qa:media-reviews-interaction-contract` - exit `0`.
- `npm run qa:media-tracks-pagination-contract` - exit `0`; red fixture rejected and cursor safeguards passed.
- `npm run qa:media-stage1-workspace-runtime` - exit `0`.
- `npm run qa:media-admin-billing-visual-runtime` - exit `0`.
- `npx oxlint --deny-warnings` on the 44 declared Stage 1 TS/TSX files - exit `0`.
- `git diff --check` on the 66 declared Stage 1 paths - exit `0`.

## Adoption

The aggregate report is `100.0%` for `mg-panel` (`24/24`), `mg-btn` (`22/22`), `mg-tabs` (`11/11`), `mg-metric-grid` (`14/14`), `mg-hero` (`22/22`), and state surfaces (`23/23`). Admin and ordinary family button/tab consumer checks are both `1`.

## Runtime evidence

- Workspace runtime output `/tmp/openclaw-stage1-workspace-runtime`: `ok=true`, 12 personal/organization active/disabled cases across `1440x1000`, `1280x900`, `1024x768`, and `390x844`; requests stayed within the declared local runtime fixtures.
- Admin billing output `/tmp/openclaw-admin-billing-visual-runtime`: `ok=true` at all four viewports. Desktop layouts were two-column; `1024x768` and `390x844` stacked, with document width equal to viewport width.
- Evidence is local runtime evidence only. No external service, deployed environment, production readback, or build gate was used under this review boundary.

## Protected-test integrity

The adoption self-test passed its marker, helper-reachability, provenance, and bidirectional route-drift red cases. The git index remained empty during review. No source, test, configuration, commit, or existing evidence file was changed by the review.

## Residual risk

- `src/media/pages/ordinary/ReviewsPage.tsx:152-158,824-825`: backend `1h`/`2h` review windows still fall back to `时间窗口待确认`.
- `src/media/pages/ordinary/ReviewsPage.tsx:811-821`: the local `unavailable` quality label remains `不可用` rather than the shared `暂不可用` wording.
- `src/media/pages/ordinary/RunsPage.tsx:769-772` and `src/media/pages/ordinary/PublishingPage.tsx:222-225`: selection/detail placeholders remain context-specific geometry, not resource-empty branches.
- No external, deployed, production, or device evidence was collected.

## Actual write scope

- Repository write scope: only `agents-results/2026-08-31/media-visual-mainline-migration/final-review/runs/20260831T185213+0800/returns/stage-1-corrected.md`; its `returns` directory was created because it was absent.
- No source, test, configuration, git index, commit, or prior evidence path was modified.

## Classification

- `failure_class`: corrected incomplete shared-primitive adoption hidden by aggregate coverage.
- `failure_origin`: page-local resource-empty branches in Runs and Publishing; the prior aggregate guard did not establish semantic coverage of every empty branch.

## Final decision

READY
