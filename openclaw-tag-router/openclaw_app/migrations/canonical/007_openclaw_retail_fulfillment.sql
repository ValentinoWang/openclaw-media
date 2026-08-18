DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM openclaw_account.redemptions) THEN
        RAISE EXCEPTION 'legacy redemptions must be empty before 007 cutover';
    END IF;
END;
$$;

DROP TABLE openclaw_account.redemptions;

CREATE TABLE openclaw_account.product_mappings (
    id UUID PRIMARY KEY,
    external_provider TEXT NOT NULL CHECK (external_provider = 'liandong'),
    external_product_id TEXT NOT NULL CHECK (length(btrim(external_product_id)) BETWEEN 1 AND 128),
    plan_id UUID NOT NULL REFERENCES openclaw_account.plans(id) ON DELETE RESTRICT,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'retired')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    retired_at TIMESTAMPTZ,
    UNIQUE (external_provider, external_product_id),
    CHECK ((status = 'retired') = (retired_at IS NOT NULL))
);

CREATE TABLE openclaw_account.redemption_batches (
    id UUID PRIMARY KEY,
    product_mapping_id UUID NOT NULL REFERENCES openclaw_account.product_mappings(id) ON DELETE RESTRICT,
    code_count INTEGER NOT NULL CHECK (code_count BETWEEN 1 AND 1000),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled')),
    idempotency_key TEXT NOT NULL UNIQUE CHECK (length(idempotency_key) BETWEEN 1 AND 128),
    created_by_user_id UUID NOT NULL REFERENCES openclaw_account.users(id) ON DELETE RESTRICT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    disabled_at TIMESTAMPTZ,
    CHECK ((status = 'disabled') = (disabled_at IS NOT NULL))
);

CREATE TABLE openclaw_account.redemption_codes (
    id UUID PRIMARY KEY,
    batch_id UUID NOT NULL REFERENCES openclaw_account.redemption_batches(id) ON DELETE RESTRICT,
    code_hmac BYTEA NOT NULL UNIQUE CHECK (octet_length(code_hmac) = 32),
    status TEXT NOT NULL DEFAULT 'available' CHECK (status IN ('available', 'redeeming', 'redeemed', 'revoked')),
    redeemed_by_tenant_id UUID REFERENCES openclaw_account.tenants(id) ON DELETE RESTRICT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    redeeming_at TIMESTAMPTZ,
    redeemed_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ,
    CHECK ((status = 'redeeming') = (redeeming_at IS NOT NULL AND redeemed_at IS NULL AND revoked_at IS NULL)),
    CHECK ((status = 'redeemed') = (redeemed_at IS NOT NULL AND redeemed_by_tenant_id IS NOT NULL)),
    CHECK ((status = 'revoked') = (revoked_at IS NOT NULL)),
    CHECK (status <> 'available' OR (redeeming_at IS NULL AND redeemed_at IS NULL AND revoked_at IS NULL))
);

CREATE INDEX redemption_codes_batch_status_idx
    ON openclaw_account.redemption_codes(batch_id, status);

CREATE TABLE openclaw_account.fulfillments (
    id UUID PRIMARY KEY,
    code_id UUID NOT NULL UNIQUE REFERENCES openclaw_account.redemption_codes(id) ON DELETE RESTRICT,
    tenant_id UUID NOT NULL REFERENCES openclaw_account.tenants(id) ON DELETE RESTRICT,
    plan_id UUID NOT NULL REFERENCES openclaw_account.plans(id) ON DELETE RESTRICT,
    wallet_account_id UUID NOT NULL,
    credited_amount NUMERIC(20, 8) NOT NULL CHECK (credited_amount > 0),
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'succeeded', 'refunded')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    refunded_at TIMESTAMPTZ,
    FOREIGN KEY (wallet_account_id, tenant_id) REFERENCES openclaw_account.wallet_accounts(id, tenant_id) ON DELETE RESTRICT,
    UNIQUE (id, tenant_id),
    CHECK ((status = 'pending') = (completed_at IS NULL)),
    CHECK ((status = 'refunded') = (refunded_at IS NOT NULL))
);

CREATE INDEX fulfillments_tenant_created_idx
    ON openclaw_account.fulfillments(tenant_id, created_at DESC);

CREATE TABLE openclaw_account.affiliate_ledger (
    id UUID PRIMARY KEY,
    fulfillment_id UUID NOT NULL UNIQUE REFERENCES openclaw_account.fulfillments(id) ON DELETE RESTRICT,
    inviter_tenant_id UUID NOT NULL REFERENCES openclaw_account.tenants(id) ON DELETE RESTRICT,
    invitee_tenant_id UUID NOT NULL REFERENCES openclaw_account.tenants(id) ON DELETE RESTRICT,
    wallet_account_id UUID NOT NULL,
    ledger_entry_id UUID NOT NULL UNIQUE REFERENCES openclaw_account.ledger_entries(id) ON DELETE RESTRICT,
    reward_rate NUMERIC(5, 4) NOT NULL CHECK (reward_rate = 0.1000),
    amount NUMERIC(20, 8) NOT NULL CHECK (amount > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (wallet_account_id, inviter_tenant_id) REFERENCES openclaw_account.wallet_accounts(id, tenant_id) ON DELETE RESTRICT,
    CHECK (inviter_tenant_id <> invitee_tenant_id)
);

CREATE TABLE openclaw_account.refund_adjustments (
    id UUID PRIMARY KEY,
    fulfillment_id UUID NOT NULL UNIQUE REFERENCES openclaw_account.fulfillments(id) ON DELETE RESTRICT,
    actor_user_id UUID NOT NULL REFERENCES openclaw_account.users(id) ON DELETE RESTRICT,
    principal_requested NUMERIC(20, 8) NOT NULL CHECK (principal_requested > 0),
    principal_debited NUMERIC(20, 8) NOT NULL CHECK (principal_debited >= 0),
    principal_debt NUMERIC(20, 8) NOT NULL CHECK (principal_debt >= 0),
    affiliate_requested NUMERIC(20, 8) NOT NULL CHECK (affiliate_requested >= 0),
    affiliate_debited NUMERIC(20, 8) NOT NULL CHECK (affiliate_debited >= 0),
    affiliate_debt NUMERIC(20, 8) NOT NULL CHECK (affiliate_debt >= 0),
    reason TEXT NOT NULL CHECK (length(btrim(reason)) BETWEEN 1 AND 500),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (principal_requested = principal_debited + principal_debt),
    CHECK (affiliate_requested = affiliate_debited + affiliate_debt)
);

CREATE TRIGGER affiliate_ledger_immutable
    BEFORE UPDATE OR DELETE ON openclaw_account.affiliate_ledger
    FOR EACH ROW EXECUTE FUNCTION openclaw_account.reject_immutable_mutation();

CREATE TRIGGER refund_adjustments_immutable
    BEFORE UPDATE OR DELETE ON openclaw_account.refund_adjustments
    FOR EACH ROW EXECUTE FUNCTION openclaw_account.reject_immutable_mutation();
