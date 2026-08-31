TASK_ID=page-organization-workspace
Read the common page contract and verify SHA-256 `2cdf6bfd456c83cf5e02b1b5b578133cfab6a93146beb08968f003afd793851a` before editing.

Migrate OrganizationWorkspaceShellPage to DS-06..DS-11 shared primitives while preserving Lark authority, preview, organization checks, immutable/read-only constraints, and all state branches. Root ownership is `organization`; accent is `campaign`.

Exclusive write scope:
- `openclaw-bot-center/src/media/OrganizationWorkspaceShellPage.tsx`

Acceptance command: `git diff --check -- openclaw-bot-center/src/media/OrganizationWorkspaceShellPage.tsx`.
