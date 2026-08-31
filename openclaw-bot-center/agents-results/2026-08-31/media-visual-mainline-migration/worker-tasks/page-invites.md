TASK_ID=page-invites
Read the common page contract and verify SHA-256 `2cdf6bfd456c83cf5e02b1b5b578133cfab6a93146beb08968f003afd793851a` before editing.

Migrate InvitesPage to DS-06..DS-11 shared primitives while preserving clipboard, invite lifecycle, validation, and status behavior. Invites automatically follow response cursors to complete the intended read; this is deliberate behavior, not a pagination regression. Root ownership is `personal`; accent is `campaign`.

Exclusive write scope:
- `openclaw-bot-center/src/media/pages/ordinary/InvitesPage.tsx`
- `openclaw-bot-center/src/media/pages/ordinary/InvitesPage.module.css`

Acceptance command: `git diff --check -- openclaw-bot-center/src/media/pages/ordinary/InvitesPage.tsx openclaw-bot-center/src/media/pages/ordinary/InvitesPage.module.css`.
