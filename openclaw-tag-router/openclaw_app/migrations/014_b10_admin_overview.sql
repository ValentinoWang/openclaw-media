BEGIN;

CREATE INDEX IF NOT EXISTS admin_audit_created_action_idx
    ON openclaw_account.admin_audit (created_at DESC, action);

CREATE INDEX IF NOT EXISTS admin_audit_b10_recent_idx
    ON openclaw_account.admin_audit (created_at DESC, id DESC);

CREATE INDEX IF NOT EXISTS admission_codes_status_idx
    ON openclaw_account.admission_codes (status, batch_id);

CREATE INDEX IF NOT EXISTS affiliate_profiles_expiry_idx
    ON openclaw_account.affiliate_profiles (signup_expires_at)
    WHERE signup_enabled AND signup_expires_at IS NOT NULL;

CREATE INDEX IF NOT EXISTS creation_runs_status_updated_idx
    ON media_product.creation_runs ((canonical_data ->> 'status'), updated_at DESC);

INSERT INTO openclaw_account.schema_migrations (revision)
VALUES ('014_b10_admin_overview')
ON CONFLICT (revision) DO NOTHING;

COMMIT;

