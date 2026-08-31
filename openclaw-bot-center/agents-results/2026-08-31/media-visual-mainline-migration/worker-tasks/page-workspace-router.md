TASK_ID=page-workspace-router
Read the common page contract and verify SHA-256 `2cdf6bfd456c83cf5e02b1b5b578133cfab6a93146beb08968f003afd793851a` before editing.

Migrate WorkspaceShellPage route-level states to the shared state primitive without altering authority dispatch. Use dynamic ownership derived from the valid session and a matching accent; the unavailable/invalid state must remain explicitly attributed as `router`.

Exclusive write scope:
- `openclaw-bot-center/src/media/WorkspaceShellPage.tsx`

Acceptance command: `git diff --check -- openclaw-bot-center/src/media/WorkspaceShellPage.tsx`.
