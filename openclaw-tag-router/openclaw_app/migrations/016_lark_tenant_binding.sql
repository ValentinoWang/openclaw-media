BEGIN;

CREATE TABLE IF NOT EXISTS media_product.lark_tenant_bindings (
    id BIGSERIAL PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES openclaw_account.tenants(id) ON DELETE RESTRICT,
    tenant_key TEXT NOT NULL CHECK (length(btrim(tenant_key)) BETWEEN 1 AND 128),
    installation_public_id TEXT NOT NULL CHECK (length(btrim(installation_public_id)) BETWEEN 1 AND 128),
    app_id TEXT NOT NULL CHECK (length(btrim(app_id)) BETWEEN 1 AND 256),
    app_secret_ref TEXT NOT NULL CHECK (length(btrim(app_secret_ref)) BETWEEN 1 AND 256),
    space_id TEXT NOT NULL CHECK (length(btrim(space_id)) BETWEEN 1 AND 256),
    parent_node_token TEXT NOT NULL CHECK (length(btrim(parent_node_token)) BETWEEN 1 AND 256),
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'active', 'disabled', 'revoked')),
    verified_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id),
    UNIQUE (tenant_key),
    UNIQUE (tenant_id, installation_public_id)
);

CREATE TABLE IF NOT EXISTS openclaw_account.tenant_member_identities (
    tenant_id UUID NOT NULL REFERENCES openclaw_account.tenants(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES openclaw_account.users(id) ON DELETE RESTRICT,
    tenant_key TEXT NOT NULL CHECK (length(btrim(tenant_key)) > 0),
    open_id TEXT,
    union_id TEXT,
    external_user_id TEXT NOT NULL CHECK (length(btrim(external_user_id)) > 0),
    display_name TEXT NOT NULL CHECK (length(btrim(display_name)) > 0),
    email TEXT,
    external_status TEXT NOT NULL DEFAULT 'active' CHECK (external_status IN ('active', 'inactive', 'unknown')),
    last_synced_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, external_user_id),
    UNIQUE (tenant_id, user_id),
    CHECK (open_id IS NOT NULL OR union_id IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS tenant_member_identities_lookup_idx
    ON openclaw_account.tenant_member_identities (tenant_key, open_id, union_id);

CREATE TABLE IF NOT EXISTS media_product.lark_member_sync_runs (
    id BIGSERIAL PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES openclaw_account.tenants(id) ON DELETE RESTRICT,
    cursor TEXT,
    fetched_count INTEGER NOT NULL DEFAULT 0 CHECK (fetched_count >= 0),
    upserted_count INTEGER NOT NULL DEFAULT 0 CHECK (upserted_count >= 0),
    disabled_count INTEGER NOT NULL DEFAULT 0 CHECK (disabled_count >= 0),
    status TEXT NOT NULL CHECK (status IN ('running', 'succeeded', 'failed')),
    error_code TEXT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS media_product.tenant_data_migration_audit (
    id BIGSERIAL PRIMARY KEY,
    source_tenant_id UUID NOT NULL REFERENCES openclaw_account.tenants(id) ON DELETE RESTRICT,
    target_tenant_id UUID NOT NULL REFERENCES openclaw_account.tenants(id) ON DELETE RESTRICT,
    table_name TEXT NOT NULL,
    migrated_count INTEGER NOT NULL DEFAULT 0 CHECK (migrated_count >= 0),
    disposition TEXT NOT NULL CHECK (disposition IN ('migrated', 'retained_platform_history', 'retired', 'excluded')),
    reason TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO openclaw_account.schema_migrations(migration_id, checksum, depends_on)
VALUES (
    'cm1-029-lark-tenant-binding',
    '8741722855b3e82a34c49e2a7de4278013e830f9f886be08faee2e36f0c6803e',
    ARRAY['cm1-028-tenant-foundation']
)
ON CONFLICT (migration_id) DO NOTHING;

COMMIT;
