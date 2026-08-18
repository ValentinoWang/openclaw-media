# Runtime Data

This directory is the default runtime root for local media memory and media vault
artifacts.

Do not commit real runtime contents from these paths:

- `data/media_memory/tenants/<tenant_id>/`
- `data/media_vault/tenants/<tenant_id>/`

Those directories can contain account memory, Feishu readbacks, evidence bundles,
downloaded source metadata, creator profile evidence, and other private or
operational artifacts. They are intentionally excluded from GitHub releases.
Tenant ids come from the authenticated Sub2API session; callers must not choose
another tenant's directory or supply an owner field in business payloads.
