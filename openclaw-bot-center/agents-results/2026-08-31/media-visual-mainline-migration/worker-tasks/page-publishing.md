TASK_ID=page-publishing
Read the common page contract and verify SHA-256 `2cdf6bfd456c83cf5e02b1b5b578133cfab6a93146beb08968f003afd793851a` before editing.

Migrate PublishingPage to DS-06..DS-11 shared primitives while preserving permission/login behavior, publishing-preparation logic, task actions, and errors. Root ownership is `personal`; accent is `campaign`.

Exclusive write scope:
- `openclaw-bot-center/src/media/pages/ordinary/PublishingPage.tsx`
- `openclaw-bot-center/src/media/pages/ordinary/PublishingPage.module.css`

Acceptance command: `git diff --check -- openclaw-bot-center/src/media/pages/ordinary/PublishingPage.tsx openclaw-bot-center/src/media/pages/ordinary/PublishingPage.module.css`.
