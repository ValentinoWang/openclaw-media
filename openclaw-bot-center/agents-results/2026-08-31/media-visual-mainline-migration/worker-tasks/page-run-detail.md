TASK_ID=page-run-detail
Read the common page contract and verify SHA-256 `2cdf6bfd456c83cf5e02b1b5b578133cfab6a93146beb08968f003afd793851a` before editing.

Migrate CreationRunDetailPage to DS-06..DS-11 shared primitives while preserving run identifier validation, metadata, status, export/delivery actions, and error behavior. Root ownership is `personal`; accent is `studio`. Attribute Gate and DetailLoading branches.

Exclusive write scope:
- `openclaw-bot-center/src/media/CreationRunDetailPage.tsx`
- `openclaw-bot-center/src/media/CreationRunDetailPage.module.css`

Acceptance command: `git diff --check -- openclaw-bot-center/src/media/CreationRunDetailPage.tsx openclaw-bot-center/src/media/CreationRunDetailPage.module.css`.
