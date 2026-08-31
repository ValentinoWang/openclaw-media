TASK_ID=page-archives
Read the common page contract and verify SHA-256 `2cdf6bfd456c83cf5e02b1b5b578133cfab6a93146beb08968f003afd793851a` before editing.

Migrate ArchivesPage to DS-06..DS-11 shared primitives while preserving archive readback, restore/delete behavior, cursor semantics, and status presentation. Root ownership is `personal`; accent is `archive`. Attribute every ArchiveStateShell branch.

Exclusive write scope:
- `openclaw-bot-center/src/media/pages/ordinary/ArchivesPage.tsx`
- `openclaw-bot-center/src/media/pages/ordinary/ArchivesPage.module.css`

Acceptance command: `git diff --check -- openclaw-bot-center/src/media/pages/ordinary/ArchivesPage.tsx openclaw-bot-center/src/media/pages/ordinary/ArchivesPage.module.css`.
