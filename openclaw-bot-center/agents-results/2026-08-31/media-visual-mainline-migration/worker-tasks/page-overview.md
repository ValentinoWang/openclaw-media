TASK_ID=page-overview
Read `openclaw-bot-center/agents-results/2026-08-31/media-visual-mainline-migration/worker-tasks/common-page-instructions.md` and verify SHA-256 `2cdf6bfd456c83cf5e02b1b5b578133cfab6a93146beb08968f003afd793851a` before editing.

Migrate OverviewPage to DS-06..DS-11 shared primitives while preserving current mainline behavior. Root ownership is `personal`; accent is `studio`. Reconcile the historical final page only as a reference. Ensure all route-level state branches retain ownership/accent/prelude attribution.

Exclusive write scope:
- `openclaw-bot-center/src/media/pages/ordinary/OverviewPage.tsx`
- `openclaw-bot-center/src/media/pages/ordinary/OverviewPage.module.css`

Acceptance command: `git diff --check -- openclaw-bot-center/src/media/pages/ordinary/OverviewPage.tsx openclaw-bot-center/src/media/pages/ordinary/OverviewPage.module.css`.
