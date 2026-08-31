TASK_ID=page-media-agent
Read the common page contract and verify SHA-256 `2cdf6bfd456c83cf5e02b1b5b578133cfab6a93146beb08968f003afd793851a` before editing.

Migrate MediaAgentPage to DS-06..DS-11 shared primitives while preserving device-pairing, local/remote task behavior, statuses, and actions. The empty state intentionally retains the device-pairing entry. Root ownership is `personal`; accent is `agent`.

Exclusive write scope:
- `openclaw-bot-center/src/media/pages/ordinary/MediaAgentPage.tsx`
- `openclaw-bot-center/src/media/pages/ordinary/MediaAgentPage.module.css`

Acceptance command: `git diff --check -- openclaw-bot-center/src/media/pages/ordinary/MediaAgentPage.tsx openclaw-bot-center/src/media/pages/ordinary/MediaAgentPage.module.css`.
