TASK_ID=page-personal-workspace
Read the common page contract and verify SHA-256 `2cdf6bfd456c83cf5e02b1b5b578133cfab6a93146beb08968f003afd793851a` before editing.

Migrate PersonalWorkspaceShellPage to DS-06..DS-11 shared primitives and DS-22 metric band while preserving source authority, preview, deletion recovery, task linking, and all state branches. Root ownership is `personal`; accent is `studio`; every PersonalShellState root needs attribution.

Exclusive write scope:
- `openclaw-bot-center/src/media/PersonalWorkspaceShellPage.tsx`

Acceptance command: `git diff --check -- openclaw-bot-center/src/media/PersonalWorkspaceShellPage.tsx`.
