ALTER TABLE openclaw_account.plans
    ADD COLUMN IF NOT EXISTS text_quota NUMERIC(20, 0) NOT NULL DEFAULT 0
        CHECK (text_quota >= 0),
    ADD COLUMN IF NOT EXISTS image_quota NUMERIC(20, 0) NOT NULL DEFAULT 0
        CHECK (image_quota >= 0),
    ADD COLUMN IF NOT EXISTS currency TEXT NOT NULL DEFAULT 'credit'
        CHECK (currency = 'credit'),
    ADD COLUMN IF NOT EXISTS revision BIGINT NOT NULL DEFAULT 1
        CHECK (revision >= 0);

CREATE OR REPLACE FUNCTION openclaw_account.enforce_plan_catalog_immutability()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP = 'INSERT' OR TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'plan catalog is closed' USING ERRCODE = '55000';
    END IF;
    IF OLD.status = 'active'
       AND NEW.status = 'retired'
       AND ROW(
            NEW.id, NEW.code, NEW.name, NEW.price_cny, NEW.credit_amount,
            NEW.text_quota, NEW.image_quota, NEW.currency, NEW.revision, NEW.created_at
       ) IS NOT DISTINCT FROM ROW(
            OLD.id, OLD.code, OLD.name, OLD.price_cny, OLD.credit_amount,
            OLD.text_quota, OLD.image_quota, OLD.currency, OLD.revision, OLD.created_at
       )
       AND NEW.updated_at >= OLD.updated_at THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'plan catalog immutable fields changed' USING ERRCODE = '55000';
END;
$$;

CREATE TABLE IF NOT EXISTS openclaw_account.tenant_billing_plans (
    tenant_id UUID PRIMARY KEY REFERENCES openclaw_account.tenants(id) ON DELETE RESTRICT,
    plan_id UUID NOT NULL REFERENCES openclaw_account.plans(id) ON DELETE RESTRICT,
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'expired', 'suspended')),
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ,
    revision BIGINT NOT NULL DEFAULT 1 CHECK (revision >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (expires_at IS NULL OR expires_at > started_at)
);

CREATE UNIQUE INDEX IF NOT EXISTS tenant_billing_plans_one_active_idx
    ON openclaw_account.tenant_billing_plans (tenant_id)
    WHERE status = 'active';

CREATE INDEX IF NOT EXISTS tenant_billing_plans_plan_idx
    ON openclaw_account.tenant_billing_plans (plan_id, status);

ALTER TABLE openclaw_account.usage_events
    ADD COLUMN IF NOT EXISTS model TEXT,
    ADD COLUMN IF NOT EXISTS unit TEXT,
    ADD COLUMN IF NOT EXISTS charge NUMERIC(20, 8),
    ADD COLUMN IF NOT EXISTS currency TEXT DEFAULT 'credit',
    ADD COLUMN IF NOT EXISTS status TEXT,
    ADD COLUMN IF NOT EXISTS source_type TEXT,
    ADD COLUMN IF NOT EXISTS source_id UUID,
    ADD COLUMN IF NOT EXISTS price_version_id UUID
        REFERENCES openclaw_account.model_price_versions(id) ON DELETE RESTRICT;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'usage_events_b08_image_contract'
          AND conrelid = 'openclaw_account.usage_events'::regclass
    ) THEN
        ALTER TABLE openclaw_account.usage_events
            ADD CONSTRAINT usage_events_b08_image_contract
            CHECK (
                kind <> 'image'
                OR (
                    event_public_id ~ '^[A-Za-z0-9_-]{8,160}$'
                    AND model IS NOT NULL
                    AND length(btrim(model)) > 0
                    AND quantity > 0
                    AND unit = 'images'
                    AND currency = 'credit'
                    AND status IN ('succeeded', 'compensated', 'pending_reconciliation')
                    AND source_type IS NOT NULL
                    AND length(btrim(source_type)) BETWEEN 1 AND 96
                    AND source_id IS NOT NULL
                    AND (status = 'pending_reconciliation' OR charge IS NOT NULL)
                    AND (charge IS NULL OR charge >= 0)
                )
            );
    END IF;
END;
$$;

CREATE UNIQUE INDEX IF NOT EXISTS usage_events_b08_source_idx
    ON openclaw_account.usage_events (tenant_id, source_type, source_id);

CREATE INDEX IF NOT EXISTS billing_usage_events_tenant_created_idx
    ON openclaw_account.usage_events (tenant_id, created_at DESC, event_public_id ASC);

DROP TRIGGER IF EXISTS usage_billing_events_immutable ON openclaw_account.usage_events;

CREATE TRIGGER usage_billing_events_immutable
    BEFORE UPDATE OR DELETE ON openclaw_account.usage_events
    FOR EACH ROW EXECUTE FUNCTION openclaw_account.reject_immutable_mutation();

DROP TRIGGER IF EXISTS ledger_entries_immutable ON openclaw_account.ledger_entries;

CREATE TRIGGER ledger_entries_immutable
    BEFORE UPDATE OR DELETE ON openclaw_account.ledger_entries
    FOR EACH ROW EXECUTE FUNCTION openclaw_account.reject_immutable_mutation();

CREATE TABLE IF NOT EXISTS media_product.b08_redemption_idempotency (
    id BIGSERIAL PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES openclaw_account.tenants(id) ON DELETE RESTRICT,
    operation TEXT NOT NULL CHECK (operation = 'redeemBillingCode'),
    idempotency_key TEXT NOT NULL CHECK (length(idempotency_key) BETWEEN 8 AND 128),
    request_checksum TEXT NOT NULL CHECK (request_checksum ~ '^[0-9a-f]{64}$'),
    response_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, operation, idempotency_key)
);

CREATE INDEX IF NOT EXISTS b08_redemption_idempotency_created_idx
    ON media_product.b08_redemption_idempotency (tenant_id, created_at DESC);

DROP TRIGGER IF EXISTS b08_redemption_idempotency_immutable ON media_product.b08_redemption_idempotency;

CREATE TRIGGER b08_redemption_idempotency_immutable
    BEFORE UPDATE OR DELETE ON media_product.b08_redemption_idempotency
    FOR EACH ROW EXECUTE FUNCTION openclaw_account.reject_immutable_mutation();

DROP VIEW IF EXISTS openclaw_account.billing_usage_events;

CREATE VIEW openclaw_account.billing_usage_events AS
SELECT
    c.tenant_id,
    'usage_' || replace(c.id::text, '-', '') AS public_usage_id,
    'text'::TEXT AS kind,
    COALESCE(NULLIF(o.upstream_model, ''), o.requested_model) AS model,
    (c.input_tokens + c.output_tokens)::NUMERIC AS quantity,
    'tokens'::TEXT AS unit,
    c.amount AS charge,
    'succeeded'::TEXT AS status,
    c.created_at,
    c.price_version_id
FROM openclaw_account.usage_charges AS c
JOIN openclaw_account.model_operations AS o
  ON o.id = c.operation_id
 AND o.tenant_id = c.tenant_id
JOIN openclaw_account.model_price_versions AS price_version
  ON price_version.id = c.price_version_id
UNION ALL
SELECT
    e.tenant_id,
    e.event_public_id AS public_usage_id,
    e.kind,
    e.model,
    e.quantity,
    e.unit,
    e.charge,
    e.status,
    e.created_at,
    e.price_version_id
FROM openclaw_account.usage_events AS e
WHERE e.kind IN ('image', 'compensation')
UNION ALL
SELECT
    f.tenant_id,
    'credit_' || replace(f.id::text, '-', '') AS public_usage_id,
    CASE WHEN f.status = 'refunded' THEN 'compensation' ELSE 'credit' END::TEXT AS kind,
    p.code AS model,
    CASE WHEN f.status = 'refunded' THEN -f.credited_amount ELSE f.credited_amount END AS quantity,
    'credit'::TEXT AS unit,
    0::NUMERIC AS charge,
    CASE
        WHEN f.status = 'refunded' THEN 'compensated'
        WHEN f.status = 'pending' THEN 'pending_reconciliation'
        ELSE 'succeeded'
    END::TEXT AS status,
    f.created_at,
    NULL::UUID AS price_version_id
FROM openclaw_account.fulfillments AS f
JOIN openclaw_account.plans AS p ON p.id = f.plan_id;
