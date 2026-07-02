# Runtime Data

This directory is the default runtime root for local media memory and media vault
artifacts.

Do not commit real runtime contents from these paths:

- `data/media_memory/`
- `data/media_vault/`

Those directories can contain account memory, Feishu readbacks, evidence bundles,
downloaded source metadata, creator profile evidence, and other private or
operational artifacts. They are intentionally excluded from GitHub releases.
