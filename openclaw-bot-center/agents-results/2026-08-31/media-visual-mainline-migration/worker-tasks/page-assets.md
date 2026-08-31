TASK_ID=page-assets
Read the common page contract and verify SHA-256 `2cdf6bfd456c83cf5e02b1b5b578133cfab6a93146beb08968f003afd793851a` before editing.

Migrate AssetsPage to DS-06..DS-11 shared primitives while preserving thumbnails, contextual launches, cursor semantics, deletion workflows, and current errors. Root ownership is `personal`; accent is `studio`.

Exclusive write scope:
- `openclaw-bot-center/src/media/pages/ordinary/AssetsPage.tsx`
- `openclaw-bot-center/src/media/pages/ordinary/AssetsPage.module.css`

Acceptance command: `git diff --check -- openclaw-bot-center/src/media/pages/ordinary/AssetsPage.tsx openclaw-bot-center/src/media/pages/ordinary/AssetsPage.module.css`.
