CREATE SCHEMA IF NOT EXISTS openclaw_account;

CREATE TABLE openclaw_account.schema_migrations (
    revision TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE openclaw_account.users (
    id UUID PRIMARY KEY,
    username TEXT NOT NULL UNIQUE CHECK (username = lower(btrim(username)) AND length(username) BETWEEN 3 AND 254),
    email TEXT CHECK (email IS NULL OR email = lower(btrim(email))),
    password_hash TEXT NOT NULL CHECK (length(password_hash) >= 32),
    role TEXT NOT NULL CHECK (role IN ('user', 'admin')),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'suspended', 'disabled')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX users_email_unique_when_present
    ON openclaw_account.users (email) WHERE email IS NOT NULL;

CREATE TABLE openclaw_account.tenants (
    id UUID PRIMARY KEY,
    primary_user_id UUID NOT NULL UNIQUE REFERENCES openclaw_account.users(id) ON DELETE RESTRICT,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'suspended')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (id, primary_user_id)
);

CREATE TABLE openclaw_account.sessions (
    id UUID PRIMARY KEY,
    session_token_hash BYTEA NOT NULL UNIQUE CHECK (octet_length(session_token_hash) = 32),
    csrf_token_hash BYTEA NOT NULL CHECK (octet_length(csrf_token_hash) = 32),
    user_id UUID NOT NULL REFERENCES openclaw_account.users(id) ON DELETE CASCADE,
    tenant_id UUID NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'revoked', 'expired')),
    issued_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ,
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (tenant_id, user_id) REFERENCES openclaw_account.tenants(id, primary_user_id) ON DELETE CASCADE,
    CHECK (expires_at > issued_at),
    CHECK ((status = 'revoked') = (revoked_at IS NOT NULL))
);

CREATE INDEX sessions_user_status_idx ON openclaw_account.sessions (user_id, status);
CREATE INDEX sessions_tenant_status_idx ON openclaw_account.sessions (tenant_id, status);

CREATE TABLE openclaw_account.wallet_accounts (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL UNIQUE REFERENCES openclaw_account.tenants(id) ON DELETE RESTRICT,
    available NUMERIC(20, 8) NOT NULL DEFAULT 0 CHECK (available >= 0),
    reserved NUMERIC(20, 8) NOT NULL DEFAULT 0 CHECK (reserved >= 0),
    version BIGINT NOT NULL DEFAULT 0 CHECK (version >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (id, tenant_id)
);

CREATE TABLE openclaw_account.ledger_entries (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES openclaw_account.tenants(id) ON DELETE RESTRICT,
    wallet_account_id UUID NOT NULL,
    entry_type TEXT NOT NULL CHECK (entry_type IN ('credit', 'reserve', 'release', 'settle', 'refund', 'affiliate', 'admin_adjustment')),
    available_delta NUMERIC(20, 8) NOT NULL,
    reserved_delta NUMERIC(20, 8) NOT NULL,
    available_after NUMERIC(20, 8) NOT NULL CHECK (available_after >= 0),
    reserved_after NUMERIC(20, 8) NOT NULL CHECK (reserved_after >= 0),
    source_type TEXT NOT NULL,
    source_id UUID,
    idempotency_key TEXT NOT NULL CHECK (length(idempotency_key) BETWEEN 1 AND 128),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (wallet_account_id, tenant_id) REFERENCES openclaw_account.wallet_accounts(id, tenant_id) ON DELETE RESTRICT,
    UNIQUE (tenant_id, idempotency_key),
    CHECK (available_delta <> 0 OR reserved_delta <> 0)
);

CREATE INDEX ledger_entries_tenant_created_idx ON openclaw_account.ledger_entries (tenant_id, created_at DESC);

CREATE TABLE openclaw_account.fund_holds (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES openclaw_account.tenants(id) ON DELETE RESTRICT,
    wallet_account_id UUID NOT NULL,
    amount NUMERIC(20, 8) NOT NULL CHECK (amount > 0),
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'captured', 'released', 'pending_manual')),
    idempotency_key TEXT NOT NULL CHECK (length(idempotency_key) BETWEEN 1 AND 128),
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (wallet_account_id, tenant_id) REFERENCES openclaw_account.wallet_accounts(id, tenant_id) ON DELETE RESTRICT,
    UNIQUE (tenant_id, idempotency_key),
    UNIQUE (id, tenant_id),
    CHECK (expires_at > created_at)
);

CREATE TABLE openclaw_account.model_price_versions (
    id UUID PRIMARY KEY,
    model TEXT NOT NULL CHECK (length(btrim(model)) > 0),
    input_price_per_million NUMERIC(20, 8) NOT NULL CHECK (input_price_per_million >= 0),
    output_price_per_million NUMERIC(20, 8) NOT NULL CHECK (output_price_per_million >= 0),
    currency TEXT NOT NULL DEFAULT 'credit' CHECK (currency = 'credit'),
    effective_at TIMESTAMPTZ NOT NULL,
    retired_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (model, effective_at),
    CHECK (retired_at IS NULL OR retired_at > effective_at)
);

CREATE TABLE openclaw_account.model_operations (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES openclaw_account.tenants(id) ON DELETE RESTRICT,
    scope TEXT NOT NULL CHECK (length(scope) BETWEEN 1 AND 128),
    idempotency_key TEXT NOT NULL CHECK (length(idempotency_key) BETWEEN 1 AND 128),
    request_fingerprint TEXT NOT NULL CHECK (request_fingerprint ~ '^[0-9a-f]{64}$'),
    fund_hold_id UUID NOT NULL,
    price_version_id UUID NOT NULL REFERENCES openclaw_account.model_price_versions(id) ON DELETE RESTRICT,
    requested_model TEXT NOT NULL,
    upstream_model TEXT,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'succeeded', 'failed', 'unknown_reconcile')),
    input_tokens BIGINT CHECK (input_tokens IS NULL OR input_tokens >= 0),
    output_tokens BIGINT CHECK (output_tokens IS NULL OR output_tokens >= 0),
    actual_charge NUMERIC(20, 8) CHECK (actual_charge IS NULL OR actual_charge >= 0),
    safe_result JSONB,
    error_code TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    FOREIGN KEY (fund_hold_id, tenant_id) REFERENCES openclaw_account.fund_holds(id, tenant_id) ON DELETE RESTRICT,
    UNIQUE (fund_hold_id),
    UNIQUE (tenant_id, scope, idempotency_key),
    UNIQUE (tenant_id, scope, request_fingerprint),
    UNIQUE (id, tenant_id),
    CHECK ((status = 'pending') = (completed_at IS NULL))
);

CREATE INDEX model_operations_tenant_created_idx ON openclaw_account.model_operations (tenant_id, created_at DESC);

CREATE TABLE openclaw_account.upstream_request_refs (
    id UUID PRIMARY KEY,
    operation_id UUID NOT NULL,
    tenant_id UUID NOT NULL,
    provider TEXT NOT NULL CHECK (provider = 'sub2api'),
    correlation_key TEXT NOT NULL CHECK (length(correlation_key) BETWEEN 16 AND 128),
    upstream_request_id TEXT,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'succeeded', 'failed', 'unknown_reconcile')),
    input_tokens BIGINT CHECK (input_tokens IS NULL OR input_tokens >= 0),
    output_tokens BIGINT CHECK (output_tokens IS NULL OR output_tokens >= 0),
    actual_cost NUMERIC(20, 8) CHECK (actual_cost IS NULL OR actual_cost >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (operation_id, tenant_id) REFERENCES openclaw_account.model_operations(id, tenant_id) ON DELETE RESTRICT,
    UNIQUE (provider, correlation_key)
);

CREATE UNIQUE INDEX upstream_request_refs_provider_request_unique
    ON openclaw_account.upstream_request_refs (provider, upstream_request_id)
    WHERE upstream_request_id IS NOT NULL;

CREATE TABLE openclaw_account.plans (
    id UUID PRIMARY KEY,
    code TEXT NOT NULL UNIQUE CHECK (code = lower(btrim(code)) AND length(code) BETWEEN 1 AND 64),
    name TEXT NOT NULL CHECK (length(btrim(name)) > 0),
    price_cny NUMERIC(20, 2) NOT NULL CHECK (price_cny >= 0),
    credit_amount NUMERIC(20, 8) NOT NULL CHECK (credit_amount > 0),
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'active', 'retired')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE openclaw_account.redemptions (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES openclaw_account.tenants(id) ON DELETE RESTRICT,
    plan_id UUID NOT NULL REFERENCES openclaw_account.plans(id) ON DELETE RESTRICT,
    wallet_account_id UUID NOT NULL,
    credited_amount NUMERIC(20, 8) NOT NULL CHECK (credited_amount > 0),
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'succeeded', 'reversed')),
    idempotency_key TEXT NOT NULL CHECK (length(idempotency_key) BETWEEN 1 AND 128),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (wallet_account_id, tenant_id) REFERENCES openclaw_account.wallet_accounts(id, tenant_id) ON DELETE RESTRICT,
    UNIQUE (tenant_id, idempotency_key)
);

CREATE TABLE openclaw_account.affiliate_edges (
    id UUID PRIMARY KEY,
    inviter_user_id UUID NOT NULL REFERENCES openclaw_account.users(id) ON DELETE RESTRICT,
    invitee_user_id UUID NOT NULL UNIQUE REFERENCES openclaw_account.users(id) ON DELETE RESTRICT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (inviter_user_id <> invitee_user_id)
);

CREATE OR REPLACE FUNCTION openclaw_account.reject_immutable_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION '% is append-only', TG_TABLE_NAME USING ERRCODE = '55000';
END;
$$;

CREATE TRIGGER ledger_entries_immutable
    BEFORE UPDATE OR DELETE ON openclaw_account.ledger_entries
    FOR EACH ROW EXECUTE FUNCTION openclaw_account.reject_immutable_mutation();

CREATE TRIGGER model_price_versions_immutable
    BEFORE UPDATE OR DELETE ON openclaw_account.model_price_versions
    FOR EACH ROW EXECUTE FUNCTION openclaw_account.reject_immutable_mutation();

CREATE TRIGGER affiliate_edges_immutable
    BEFORE UPDATE OR DELETE ON openclaw_account.affiliate_edges
    FOR EACH ROW EXECUTE FUNCTION openclaw_account.reject_immutable_mutation();

INSERT INTO openclaw_account.schema_migrations (revision)
VALUES ('003_openclaw_account_billing');
