TASK_ID=page-admin-access
Read the common page contract and verify SHA-256 `2cdf6bfd456c83cf5e02b1b5b578133cfab6a93146beb08968f003afd793851a` before editing.

Migrate AdminAccessPage to DS-06..DS-11 shared primitives while preserving admission, suspension, role, audit reason, pagination, and error contracts. Root ownership is `governance`; accent is `campaign`.

Exclusive write scope:
- `openclaw-bot-center/src/media/pages/admin/AdminAccessPage.tsx`
- `openclaw-bot-center/src/media/pages/admin/AdminAccessPage.module.css`

Acceptance command: `git diff --check -- openclaw-bot-center/src/media/pages/admin/AdminAccessPage.tsx openclaw-bot-center/src/media/pages/admin/AdminAccessPage.module.css`.
