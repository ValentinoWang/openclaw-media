ALTER TABLE openclaw_account.users
    ADD COLUMN IF NOT EXISTS display_name TEXT;

UPDATE openclaw_account.users
SET display_name = username
WHERE display_name IS NULL;

ALTER TABLE openclaw_account.users
    ALTER COLUMN display_name SET NOT NULL;

ALTER TABLE openclaw_account.users
    ADD CONSTRAINT users_display_name_length
    CHECK (length(btrim(display_name)) BETWEEN 1 AND 80);

ALTER TABLE openclaw_account.tenants
    ADD COLUMN IF NOT EXISTS tenant_type TEXT NOT NULL DEFAULT 'personal',
    ADD COLUMN IF NOT EXISTS workspace_mode TEXT NOT NULL DEFAULT 'personal_web',
    ADD COLUMN IF NOT EXISTS body_authority TEXT NOT NULL DEFAULT 'internal',
    ADD COLUMN IF NOT EXISTS organization_name TEXT;

ALTER TABLE openclaw_account.tenants
    ADD CONSTRAINT tenants_type_check
    CHECK (tenant_type IN ('personal', 'organization')),
    ADD CONSTRAINT tenants_workspace_mode_check
    CHECK (workspace_mode IN ('personal_web', 'organization_lark')),
    ADD CONSTRAINT tenants_body_authority_check
    CHECK (body_authority IN ('internal', 'lark')),
    ADD CONSTRAINT tenants_type_workspace_consistency
    CHECK (
        (tenant_type = 'personal' AND workspace_mode = 'personal_web' AND body_authority = 'internal' AND organization_name IS NULL)
        OR
        (tenant_type = 'organization' AND workspace_mode = 'organization_lark' AND body_authority = 'lark' AND length(btrim(organization_name)) BETWEEN 1 AND 120)
    );

CREATE TABLE openclaw_account.tenant_members (
    tenant_id UUID NOT NULL REFERENCES openclaw_account.tenants(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES openclaw_account.users(id) ON DELETE RESTRICT,
    role TEXT NOT NULL CHECK (role IN ('owner', 'member')),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled')),
    joined_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, user_id)
);

INSERT INTO openclaw_account.tenant_members(tenant_id, user_id, role)
SELECT id, primary_user_id, 'owner'
FROM openclaw_account.tenants
ON CONFLICT (tenant_id, user_id) DO NOTHING;

CREATE UNIQUE INDEX tenant_members_one_owner
    ON openclaw_account.tenant_members(tenant_id)
    WHERE role = 'owner' AND status = 'active';
