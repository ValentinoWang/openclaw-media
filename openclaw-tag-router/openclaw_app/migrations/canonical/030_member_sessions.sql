ALTER TABLE openclaw_account.sessions
    DROP CONSTRAINT IF EXISTS sessions_tenant_id_user_id_fkey;

ALTER TABLE openclaw_account.sessions
    ADD CONSTRAINT sessions_tenant_member_fkey
    FOREIGN KEY (tenant_id, user_id)
    REFERENCES openclaw_account.tenant_members(tenant_id, user_id)
    ON DELETE CASCADE;
