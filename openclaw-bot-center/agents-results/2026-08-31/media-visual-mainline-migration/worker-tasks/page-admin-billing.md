TASK_ID=page-admin-billing
Read the common page contract and verify SHA-256 `2cdf6bfd456c83cf5e02b1b5b578133cfab6a93146beb08968f003afd793851a` before editing.

Migrate AdminBillingPage to DS-06..DS-11 shared primitives while preserving billing adjustments, audit reasons, pagination, tabs, money labels, and errors. Root ownership is `governance`; accent is `business`.

Exclusive write scope:
- `openclaw-bot-center/src/media/pages/admin/AdminBillingPage.tsx`
- `openclaw-bot-center/src/media/pages/admin/AdminBillingPage.module.css`

Acceptance command: `git diff --check -- openclaw-bot-center/src/media/pages/admin/AdminBillingPage.tsx openclaw-bot-center/src/media/pages/admin/AdminBillingPage.module.css`.
