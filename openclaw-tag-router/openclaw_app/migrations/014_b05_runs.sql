BEGIN;

CREATE TABLE IF NOT EXISTS media_product.creation_run_sources (
    id bigserial PRIMARY KEY,
    tenant_id uuid NOT NULL REFERENCES openclaw_account.tenants(id),
    public_run_id text NOT NULL REFERENCES media_product.creation_runs(public_id),
    revision integer NOT NULL DEFAULT 1 CHECK (revision > 0),
    items jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(items) = 'array'),
    source_kinds jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(source_kinds) = 'array'),
    evidence_refs jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(evidence_refs) = 'array'),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, public_run_id)
);

CREATE INDEX IF NOT EXISTS creation_run_sources_tenant_idx
    ON media_product.creation_run_sources (tenant_id, public_run_id);

CREATE TABLE IF NOT EXISTS media_product.creation_run_decisions (
    id bigserial PRIMARY KEY,
    tenant_id uuid NOT NULL REFERENCES openclaw_account.tenants(id),
    public_run_id text NOT NULL REFERENCES media_product.creation_runs(public_id),
    revision integer NOT NULL DEFAULT 1 CHECK (revision > 0),
    decision_items jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(decision_items) = 'array'),
    human_state text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, public_run_id)
);

CREATE INDEX IF NOT EXISTS creation_run_decisions_tenant_idx
    ON media_product.creation_run_decisions (tenant_id, public_run_id);

CREATE TABLE IF NOT EXISTS media_product.creation_run_outputs (
    id bigserial PRIMARY KEY,
    tenant_id uuid NOT NULL REFERENCES openclaw_account.tenants(id),
    public_run_id text NOT NULL REFERENCES media_product.creation_runs(public_id),
    revision integer NOT NULL DEFAULT 1 CHECK (revision > 0),
    output_variants jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(output_variants) = 'array'),
    artifact_public_ids jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(artifact_public_ids) = 'array'),
    verification_reports jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(verification_reports) = 'array'),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, public_run_id)
);

CREATE INDEX IF NOT EXISTS creation_run_outputs_tenant_idx
    ON media_product.creation_run_outputs (tenant_id, public_run_id);

CREATE TABLE IF NOT EXISTS media_product.b05_idempotency_keys (
    id bigserial PRIMARY KEY,
    tenant_id uuid NOT NULL REFERENCES openclaw_account.tenants(id),
    operation text NOT NULL,
    idempotency_key text NOT NULL CHECK (idempotency_key ~ '^[A-Za-z0-9_-]{8,128}$'),
    request_checksum text NOT NULL CHECK (request_checksum ~ '^[a-f0-9]{64}$'),
    response_json jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, operation, idempotency_key)
);

CREATE INDEX IF NOT EXISTS b05_idempotency_keys_created_idx
    ON media_product.b05_idempotency_keys (tenant_id, created_at DESC);

CREATE INDEX IF NOT EXISTS document_revisions_b05_artifact_idx
    ON media_product.document_revisions (tenant_id, public_artifact_id, revision DESC);

CREATE INDEX IF NOT EXISTS document_artifacts_b05_tenant_idx
    ON media_product.document_artifacts (tenant_id, updated_at DESC, public_id);

ALTER TABLE media_product.lark_document_bindings
    ADD COLUMN IF NOT EXISTS status text NOT NULL DEFAULT 'pending';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'media_product.lark_document_bindings'::regclass
          AND conname = 'lark_document_bindings_status_check'
    ) THEN
        ALTER TABLE media_product.lark_document_bindings
            ADD CONSTRAINT lark_document_bindings_status_check
            CHECK (status IN ('pending', 'synced', 'conflict', 'failed'));
    END IF;
END $$;

INSERT INTO media_product.migration_ledger (version, name)
VALUES (14, 'b05_runs')
ON CONFLICT (version) DO NOTHING;

COMMIT;
