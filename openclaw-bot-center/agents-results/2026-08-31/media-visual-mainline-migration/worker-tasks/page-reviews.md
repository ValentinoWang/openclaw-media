TASK_ID=page-reviews
Read the common page contract and verify SHA-256 `2cdf6bfd456c83cf5e02b1b5b578133cfab6a93146beb08968f003afd793851a` before editing.

Migrate ReviewsPage to DS-06..DS-11 shared primitives while preserving inspector geometry, status normalization, deletion confirmation, tabs, and title wrapping. Root ownership is `personal`; accent is `desk`.

Exclusive write scope:
- `openclaw-bot-center/src/media/pages/ordinary/ReviewsPage.tsx`
- `openclaw-bot-center/src/media/pages/ordinary/ReviewsPage.module.css`

Acceptance command: `git diff --check -- openclaw-bot-center/src/media/pages/ordinary/ReviewsPage.tsx openclaw-bot-center/src/media/pages/ordinary/ReviewsPage.module.css`.
