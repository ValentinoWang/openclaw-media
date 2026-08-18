BEGIN;

CREATE TABLE IF NOT EXISTS media_product.b04_decision_confirmations (
    id bigserial PRIMARY KEY,
    tenant_id uuid NOT NULL REFERENCES openclaw_account.tenants(id),
    public_decision_id text NOT NULL,
    revision integer NOT NULL CHECK (revision > 0),
    decision text NOT NULL CHECK (decision IN ('confirmed', 'rejected')),
    reason text NOT NULL,
    actor_public_id text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, public_decision_id, revision)
);

CREATE INDEX IF NOT EXISTS b04_decision_confirmations_tenant_created_idx
    ON media_product.b04_decision_confirmations (tenant_id, created_at DESC);

CREATE TABLE IF NOT EXISTS media_product.b04_idempotency_keys (
    id bigserial PRIMARY KEY,
    tenant_id uuid NOT NULL REFERENCES openclaw_account.tenants(id),
    operation text NOT NULL,
    idempotency_key text NOT NULL,
    request_checksum text NOT NULL,
    response_json jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, operation, idempotency_key)
);

CREATE INDEX IF NOT EXISTS b04_idempotency_keys_created_idx
    ON media_product.b04_idempotency_keys (tenant_id, created_at DESC);

CREATE INDEX IF NOT EXISTS b04_decision_traces_tenant_updated_idx
    ON media_product.decision_traces (tenant_id, updated_at DESC, public_id ASC);

CREATE INDEX IF NOT EXISTS b04_decision_traces_canonical_data_gin_idx
    ON media_product.decision_traces USING gin (canonical_data jsonb_path_ops);

CREATE INDEX IF NOT EXISTS b04_signal_snapshots_tenant_updated_idx
    ON media_product.signal_snapshots (tenant_id, updated_at DESC, public_id ASC);

CREATE INDEX IF NOT EXISTS b04_activities_tenant_updated_idx
    ON media_product.activities (tenant_id, updated_at DESC, public_id ASC);

INSERT INTO media_product.migration_ledger (version, name)
VALUES (14, 'b04_decisions')
ON CONFLICT (version) DO NOTHING;

COMMIT;
