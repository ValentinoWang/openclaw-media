TASK_ID=page-admin-upstreams
Read the common page contract and verify SHA-256 `2cdf6bfd456c83cf5e02b1b5b578133cfab6a93146beb08968f003afd793851a` before editing.

Migrate AdminUpstreamsPage to DS-06..DS-11 shared primitives while preserving upstream health, configuration, destructive-action confirmations, audit reasons, and errors. Root ownership is `governance`; accent is `agent`.

Exclusive write scope:
- `openclaw-bot-center/src/media/pages/admin/AdminUpstreamsPage.tsx`
- `openclaw-bot-center/src/media/pages/admin/AdminUpstreamsPage.module.css`

Acceptance command: `git diff --check -- openclaw-bot-center/src/media/pages/admin/AdminUpstreamsPage.tsx openclaw-bot-center/src/media/pages/admin/AdminUpstreamsPage.module.css`.
