TASK_ID=page-decisions
Read the common page contract and verify SHA-256 `2cdf6bfd456c83cf5e02b1b5b578133cfab6a93146beb08968f003afd793851a` before editing.

Migrate DecisionsPage to DS-06..DS-11 shared primitives while preserving its state machine, decision actions, tabs, filters, pagination, and error contracts. Root ownership is `personal`; accent is `campaign`. Use the pill tab variant only where the current tab semantics remain unchanged.

Exclusive write scope:
- `openclaw-bot-center/src/media/pages/ordinary/DecisionsPage.tsx`
- `openclaw-bot-center/src/media/pages/ordinary/DecisionsPage.module.css`

Acceptance command: `git diff --check -- openclaw-bot-center/src/media/pages/ordinary/DecisionsPage.tsx openclaw-bot-center/src/media/pages/ordinary/DecisionsPage.module.css`.
