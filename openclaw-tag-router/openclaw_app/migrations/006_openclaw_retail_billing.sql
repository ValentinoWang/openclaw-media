ALTER TABLE openclaw_account.model_price_versions
    ADD COLUMN cached_input_price_per_million NUMERIC(20, 8) NOT NULL DEFAULT 0
        CHECK (cached_input_price_per_million >= 0);

ALTER TABLE openclaw_account.model_operations
    ADD COLUMN cached_input_tokens BIGINT CHECK (cached_input_tokens IS NULL OR cached_input_tokens >= 0);

ALTER TABLE openclaw_account.upstream_request_refs
    ADD COLUMN cached_input_tokens BIGINT CHECK (cached_input_tokens IS NULL OR cached_input_tokens >= 0);

DROP TRIGGER model_price_versions_immutable ON openclaw_account.model_price_versions;

CREATE OR REPLACE FUNCTION openclaw_account.enforce_price_version_immutability()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'model_price_versions is append-only' USING ERRCODE = '55000';
    END IF;
    IF OLD.retired_at IS NOT NULL OR NEW.retired_at IS NULL
       OR ROW(NEW.id, NEW.model, NEW.input_price_per_million, NEW.output_price_per_million,
              NEW.currency, NEW.effective_at, NEW.created_at,
              NEW.cached_input_price_per_million)
          IS DISTINCT FROM
          ROW(OLD.id, OLD.model, OLD.input_price_per_million, OLD.output_price_per_million,
              OLD.currency, OLD.effective_at, OLD.created_at,
              OLD.cached_input_price_per_million) THEN
        RAISE EXCEPTION 'model_price_versions immutable fields changed' USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER model_price_versions_immutable
    BEFORE UPDATE OR DELETE ON openclaw_account.model_price_versions
    FOR EACH ROW EXECUTE FUNCTION openclaw_account.enforce_price_version_immutability();

CREATE UNIQUE INDEX model_price_versions_one_active_model
    ON openclaw_account.model_price_versions (model)
    WHERE retired_at IS NULL;

CREATE TABLE openclaw_account.usage_charges (
    id UUID PRIMARY KEY,
    operation_id UUID NOT NULL UNIQUE,
    tenant_id UUID NOT NULL,
    upstream_request_ref_id UUID NOT NULL UNIQUE REFERENCES openclaw_account.upstream_request_refs(id) ON DELETE RESTRICT,
    price_version_id UUID NOT NULL REFERENCES openclaw_account.model_price_versions(id) ON DELETE RESTRICT,
    input_tokens BIGINT NOT NULL CHECK (input_tokens >= 0),
    cached_input_tokens BIGINT NOT NULL CHECK (cached_input_tokens >= 0 AND cached_input_tokens <= input_tokens),
    output_tokens BIGINT NOT NULL CHECK (output_tokens >= 0),
    amount NUMERIC(20, 8) NOT NULL CHECK (amount >= 0),
    currency TEXT NOT NULL DEFAULT 'credit' CHECK (currency = 'credit'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (operation_id, tenant_id) REFERENCES openclaw_account.model_operations(id, tenant_id) ON DELETE RESTRICT
);

CREATE INDEX usage_charges_tenant_created_idx
    ON openclaw_account.usage_charges (tenant_id, created_at DESC);

CREATE TRIGGER usage_charges_immutable
    BEFORE UPDATE OR DELETE ON openclaw_account.usage_charges
    FOR EACH ROW EXECUTE FUNCTION openclaw_account.reject_immutable_mutation();

INSERT INTO openclaw_account.model_price_versions(
    id, model, input_price_per_million, cached_input_price_per_million,
    output_price_per_million, effective_at
) VALUES (
    '60000000-0000-4000-8000-000000000001',
    'gpt-5.6-sol',
    2.00000000,
    0.20000000,
    8.00000000,
    '2026-08-02T00:00:00+08:00'
);

INSERT INTO openclaw_account.schema_migrations (revision)
VALUES ('006_openclaw_retail_billing');
