CREATE TABLE openclaw_account.password_reset_tokens (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES openclaw_account.users(id) ON DELETE CASCADE,
    token_hash BYTEA NOT NULL UNIQUE CHECK (octet_length(token_hash) = 32),
    issued_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    consumed_at TIMESTAMPTZ,
    CHECK (expires_at > issued_at),
    CHECK (consumed_at IS NULL OR consumed_at >= issued_at)
);

CREATE INDEX password_reset_tokens_user_expiry_idx
    ON openclaw_account.password_reset_tokens (user_id, expires_at);

CREATE TABLE openclaw_account.admin_audit (
    id UUID PRIMARY KEY,
    actor_user_id UUID NOT NULL REFERENCES openclaw_account.users(id) ON DELETE RESTRICT,
    actor_session_id UUID NOT NULL REFERENCES openclaw_account.sessions(id) ON DELETE RESTRICT,
    action TEXT NOT NULL CHECK (action = lower(btrim(action)) AND length(action) BETWEEN 3 AND 128),
    target_user_id UUID REFERENCES openclaw_account.users(id) ON DELETE RESTRICT,
    reason TEXT NOT NULL CHECK (length(btrim(reason)) BETWEEN 1 AND 500),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(metadata) = 'object'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX admin_audit_actor_created_idx
    ON openclaw_account.admin_audit (actor_user_id, created_at DESC);

CREATE INDEX admin_audit_target_created_idx
    ON openclaw_account.admin_audit (target_user_id, created_at DESC)
    WHERE target_user_id IS NOT NULL;

CREATE TRIGGER admin_audit_immutable
    BEFORE UPDATE OR DELETE ON openclaw_account.admin_audit
    FOR EACH ROW EXECUTE FUNCTION openclaw_account.reject_immutable_mutation();
