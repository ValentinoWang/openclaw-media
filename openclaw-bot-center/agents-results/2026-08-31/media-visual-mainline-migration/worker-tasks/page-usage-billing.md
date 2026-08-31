TASK_ID=page-usage-billing
Read the common page contract and verify SHA-256 `2cdf6bfd456c83cf5e02b1b5b578133cfab6a93146beb08968f003afd793851a` before editing.

Migrate UsageBillingPage to DS-06..DS-11 shared primitives while preserving quota, ledger, cursor, money/usage labels, and error behavior. Root ownership is `personal`; accent is `business`.

Exclusive write scope:
- `openclaw-bot-center/src/media/pages/ordinary/UsageBillingPage.tsx`
- `openclaw-bot-center/src/media/pages/ordinary/UsageBillingPage.module.css`

Acceptance command: `git diff --check -- openclaw-bot-center/src/media/pages/ordinary/UsageBillingPage.tsx openclaw-bot-center/src/media/pages/ordinary/UsageBillingPage.module.css`.
