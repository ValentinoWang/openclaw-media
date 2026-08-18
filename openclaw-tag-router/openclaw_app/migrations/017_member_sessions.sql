BEGIN;

ALTER TABLE openclaw_account.sessions
    DROP CONSTRAINT IF EXISTS sessions_tenant_id_user_id_fkey;

ALTER TABLE openclaw_account.sessions
    ADD CONSTRAINT sessions_tenant_member_fkey
    FOREIGN KEY (tenant_id, user_id)
    REFERENCES openclaw_account.tenant_members(tenant_id, user_id)
    ON DELETE CASCADE;

INSERT INTO openclaw_account.schema_migrations(migration_id, checksum, depends_on)
VALUES ('cm1-030-member-sessions', 'f4b26c2f2bd1b4be7df2d8fdb86c6a3ef9c3f44f0a14aaf4d00e4e4eb2e06c99', ARRAY['cm1-029-lark-tenant-binding'])
ON CONFLICT (migration_id) DO NOTHING;

COMMIT;
