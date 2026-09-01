-- This migration is intentionally one-way. Generated document edits capture
-- user instructions and model plans needed to make a retry deterministic.
CREATE TABLE media_product.document_edit_jobs (
    id BIGSERIAL PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES openclaw_account.tenants(id) ON DELETE RESTRICT,
    public_artifact_id TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision > 0),
    actor_public_id TEXT NOT NULL CHECK (length(btrim(actor_public_id)) > 0),
    instruction TEXT NOT NULL CHECK (length(btrim(instruction)) > 0),
    generated_plan JSONB,
    execution_receipt JSONB,
    state TEXT NOT NULL DEFAULT 'pending' CHECK (state IN ('pending', 'running', 'succeeded', 'failed')),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, public_artifact_id, revision),
    FOREIGN KEY (tenant_id, public_artifact_id, revision)
        REFERENCES media_product.document_revisions(tenant_id, public_artifact_id, revision)
        ON DELETE RESTRICT,
    CHECK ((generated_plan IS NULL OR jsonb_typeof(generated_plan) = 'object')
       AND (execution_receipt IS NULL OR jsonb_typeof(execution_receipt) = 'object')),
    CHECK ((state IN ('pending', 'running') AND completed_at IS NULL)
       OR (state IN ('succeeded', 'failed') AND completed_at IS NOT NULL))
);

CREATE TRIGGER document_edit_jobs_touch_updated_at
    BEFORE UPDATE ON media_product.document_edit_jobs
    FOR EACH ROW EXECUTE FUNCTION media_product.touch_updated_at();

CREATE INDEX document_edit_jobs_recovery_idx
    ON media_product.document_edit_jobs (tenant_id, created_at, id)
    WHERE state IN ('pending', 'running');
