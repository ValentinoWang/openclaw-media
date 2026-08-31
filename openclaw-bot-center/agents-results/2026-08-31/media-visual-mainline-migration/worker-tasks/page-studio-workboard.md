TASK_ID=page-studio-workboard
Read the common page contract and verify SHA-256 `2cdf6bfd456c83cf5e02b1b5b578133cfab6a93146beb08968f003afd793851a` before editing.

Bring the current Studio WorkboardPage into the DS-06..DS-11 coverage model using the existing mainline primitives, without changing workboard presentation logic or task actions. Root ownership is `personal`; accent remains `studio`; mark its true prelude.

Exclusive write scope:
- `openclaw-bot-center/src/media/studio/WorkboardPage.tsx`
- `openclaw-bot-center/src/media/studio/WorkboardPage.module.css`

Acceptance command: `git diff --check -- openclaw-bot-center/src/media/studio/WorkboardPage.tsx openclaw-bot-center/src/media/studio/WorkboardPage.module.css`.
