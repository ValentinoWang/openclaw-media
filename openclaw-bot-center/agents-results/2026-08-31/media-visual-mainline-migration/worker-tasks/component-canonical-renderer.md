TASK_ID=component-canonical-renderer
Read the common page contract and verify SHA-256 `2cdf6bfd456c83cf5e02b1b5b578133cfab6a93146beb08968f003afd793851a` before editing.

Migrate CanonicalDocumentRenderer repeated panels/statuses/actions onto compatible global primitives while preserving document semantics, field ordering, URLs, and source-authority presentation. It is embedded, so do not add route ownership or a page prelude.

Exclusive write scope:
- `openclaw-bot-center/src/media/pages/ordinary/CanonicalDocumentRenderer.tsx`
- `openclaw-bot-center/src/media/pages/ordinary/CanonicalDocumentRenderer.module.css`

Acceptance command: `git diff --check -- openclaw-bot-center/src/media/pages/ordinary/CanonicalDocumentRenderer.tsx openclaw-bot-center/src/media/pages/ordinary/CanonicalDocumentRenderer.module.css`.
