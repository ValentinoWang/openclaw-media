TASK_ID=page-tracks
Read the common page contract and verify SHA-256 `2cdf6bfd456c83cf5e02b1b5b578133cfab6a93146beb08968f003afd793851a` before editing.

Migrate TracksPage to DS-06..DS-11 shared primitives without changing account-monitoring, pagination, filtering, task launch, or error behavior. Tracks automatically follow response cursors to complete the intended read; this is deliberate behavior, not a pagination regression. Root ownership is `personal`; accent is `desk`. Preserve organization-session rendering as current behavior requires.

Exclusive write scope:
- `openclaw-bot-center/src/media/pages/ordinary/TracksPage.tsx`
- `openclaw-bot-center/src/media/pages/ordinary/TracksPage.module.css`

Acceptance command: `git diff --check -- openclaw-bot-center/src/media/pages/ordinary/TracksPage.tsx openclaw-bot-center/src/media/pages/ordinary/TracksPage.module.css`.
