# Stage 1 independent release review

## Findings

- **BLOCKING, DS-06 and DS-11** - `src/media/pages/ordinary/RunsPage.tsx:777-785`: `RunsEmpty`, `BusinessOpportunityEmpty`, and `CommercialDeliveryEmpty` render local `styles.emptyState` resource-empty surfaces. The searchable and new-delivery actions use local `styles.clearButton` and `styles.submitButton` without `mg-btn`. These branches require the shared empty-state and button primitives.
- **BLOCKING, DS-06** - `src/media/pages/ordinary/RunsPage.tsx:613,724,731,736,741,747,766-767`: the local `SectionEmpty`/`.sectionEmpty` substitute is used for missing persisted delivery output, section responses, sources, decisions, and outputs. These are matching empty-state semantics and should use `SurfaceState`/`ResourceStateView` or `.mg-state` (compact density is available).
- **BLOCKING, DS-06** - `src/media/pages/ordinary/PublishingPage.tsx:215-219`: `EmptyPackageList` renders the successful empty publishing-package list with local `styles.emptyList` instead of a shared empty-state primitive. The refresh icon is separate; it does not make the list state adopted.

## Frozen identity

- HEAD: `84382576a4045a99aea1abb6df848ba95f0bb3d9`
- Tracked diff SHA-256: `ace6f0e42673be77c51de25895232eb88c10259add95c3297d079d17d09aaff9`
- Untracked content-list SHA-256: `78211727684da2613517c1e5ea68d7c17ada7fd1da6ac4a176cd680548430ce4`
- Combined path-set SHA-256: `744982513e6ebd69f0957cb39a19274627fb73869a2ff9778d030cbc209b992d`
- Stage 1 manifest rows: `66`

## Commands and exits

- `npm run qa:media-primitive-adoption` - exit `0`
- `npm run qa:media-primitive-adoption-self-test` - exit `0`
- `npm run qa:media-primitive-coverage` - exit `0`
- `npm run qa:media-page-restoration-structure` - exit `0`
- `npm run qa:media-admin-access-contract` - exit `0`
- `npm run qa:media-reviews-interaction-contract` - exit `0`
- `npm run qa:media-tracks-pagination-contract` - exit `0`
- `npm run qa:media-stage1-workspace-runtime` - exit `0`
- `npm run qa:media-admin-billing-visual-runtime` - exit `0`
- `npx oxlint --deny-warnings` on Stage 1 TS/TSX files - exit `0`; the successful rerun used an explicit Node-resolving `PATH` after the initial launcher attempt exited `127`.
- `git diff --check` on the 66 Stage 1 paths - exit `0`

## Adoption

The aggregate 24-surface report was `100.0%` for `mg-panel` (`24/24`), `mg-btn` (`22/22`), `mg-tabs` (`11/11`), `mg-metric-grid` (`14/14`), `mg-hero` (`22/22`), and state surfaces (`23/23`). This does not prove that every matching empty branch uses a shared primitive; the findings above are branch-level exceptions.

## Runtime evidence

The workspace runtime gate passed at the required `1440x1000`, `1280x900`, `1024x768`, and `390x844` cases, including responsive rails, workspace states, Reviews/Tracks/Media Agent flows, pagination, and deletion recovery checks. The admin billing visual runtime gate passed desktop and stacked layouts. This is local runtime evidence only; no external service or deployed readback was used.

## Protected-test integrity

The adoption self-test passed. No source, test, configuration, git index, commit, or existing evidence file was written by this review. The pre-existing dirty worktree and frozen source/test changes were preserved.

## Residual risk

- `src/media/pages/ordinary/ReviewsPage.tsx:152-158,824-825`: the frontend maps `24h`, `7d`, and `custom`; an upstream `1h` or `2h` value falls back to `时间窗口待确认`.
- `src/media/pages/ordinary/ReviewsPage.tsx:811-821`: the local quality-label wording for `unavailable` differs from the shared label set.
- `src/media/pages/ordinary/RunsPage.tsx:770-773` and `src/media/pages/ordinary/PublishingPage.tsx:222-231`: no-selection inspector/detail placeholders remain local geometry. They are treated as context-specific selection states, not the blocking resource-empty branches above.
- No production, deployed, or external-service evidence was collected under this zero-write review boundary.

## Scope and classification

- Actual write scope: only `agents-results/2026-08-31/media-visual-mainline-migration/final-review/runs/20260831T181536+0800/returns/stage-1.md`.
- `failure_class`: incomplete shared-primitive adoption hidden by aggregate coverage.
- `failure_origin`: page-local empty-state branches in Runs and Publishing; the adoption guard checks aggregate consumer reachability, not semantic coverage of every empty branch.

## Final decision

NOT READY
