TASK_ID=page-admin-overview
Read the common page contract and verify SHA-256 `2cdf6bfd456c83cf5e02b1b5b578133cfab6a93146beb08968f003afd793851a` before editing.

Migrate AdminOverviewPage to DS-06..DS-11 shared primitives while preserving governance metrics, alerts, filters, and admin action semantics. Root ownership is `governance`; accent is `desk`.

Exclusive write scope:
- `openclaw-bot-center/src/media/pages/admin/AdminOverviewPage.tsx`
- `openclaw-bot-center/src/media/pages/admin/AdminOverviewPage.module.css`

Acceptance command: `git diff --check -- openclaw-bot-center/src/media/pages/admin/AdminOverviewPage.tsx openclaw-bot-center/src/media/pages/admin/AdminOverviewPage.module.css`.
