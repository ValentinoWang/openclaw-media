TASK_ID=page-studio-campaigns
Read the common page contract and verify SHA-256 `2cdf6bfd456c83cf5e02b1b5b578133cfab6a93146beb08968f003afd793851a` before editing.

Bring CampaignsPage into the DS-06..DS-11 coverage model using current mainline primitives without changing campaign data or actions. Root ownership is `personal`; accent remains `campaign`; mark its true prelude.

Exclusive write scope:
- `openclaw-bot-center/src/media/studio/CampaignsPage.tsx`
- `openclaw-bot-center/src/media/studio/CampaignsPage.module.css`

Acceptance command: `git diff --check -- openclaw-bot-center/src/media/studio/CampaignsPage.tsx openclaw-bot-center/src/media/studio/CampaignsPage.module.css`.
