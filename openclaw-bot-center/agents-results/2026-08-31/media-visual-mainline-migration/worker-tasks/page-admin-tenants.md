TASK_ID=page-admin-tenants
Read the common page contract and verify SHA-256 `2cdf6bfd456c83cf5e02b1b5b578133cfab6a93146beb08968f003afd793851a` before editing.

Migrate AdminTenantsPage to DS-06..DS-11 shared primitives while preserving tenant resource, cursor, action, identifier, and error behavior. Root ownership is `governance`; accent is `studio`.

Exclusive write scope:
- `openclaw-bot-center/src/media/pages/admin/AdminTenantsPage.tsx`
- `openclaw-bot-center/src/media/pages/admin/AdminTenantsPage.module.css`

Acceptance command: `git diff --check -- openclaw-bot-center/src/media/pages/admin/AdminTenantsPage.tsx openclaw-bot-center/src/media/pages/admin/AdminTenantsPage.module.css`.
