TASK_ID=page-runs
Read the common page contract and verify SHA-256 `2cdf6bfd456c83cf5e02b1b5b578133cfab6a93146beb08968f003afd793851a` before editing.

Migrate RunsPage to DS-06..DS-11 shared primitives while preserving commercial-delivery presentation, route aliases, cursor behavior, task actions, and statuses. Root ownership is `personal`; accent is `studio`.

Exclusive write scope:
- `openclaw-bot-center/src/media/pages/ordinary/RunsPage.tsx`
- `openclaw-bot-center/src/media/pages/ordinary/RunsPage.module.css`

Acceptance command: `git diff --check -- openclaw-bot-center/src/media/pages/ordinary/RunsPage.tsx openclaw-bot-center/src/media/pages/ordinary/RunsPage.module.css`.
