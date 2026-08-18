CREATE INDEX IF NOT EXISTS content_projects_b01_tenant_updated_idx
    ON media_product.content_projects (tenant_id, updated_at DESC, public_id DESC);

CREATE INDEX IF NOT EXISTS document_artifacts_b01_tenant_project_updated_idx
    ON media_product.document_artifacts (tenant_id, public_project_id, updated_at DESC, public_id DESC);

CREATE INDEX IF NOT EXISTS document_revisions_b01_tenant_artifact_revision_idx
    ON media_product.document_revisions (tenant_id, public_artifact_id, revision DESC);

CREATE INDEX IF NOT EXISTS decision_traces_b01_tenant_status_idx
    ON media_product.decision_traces (tenant_id, ((canonical_data->>'status')));

CREATE INDEX IF NOT EXISTS published_posts_b01_tenant_status_idx
    ON media_product.published_posts (tenant_id, ((canonical_data->>'status')));

CREATE INDEX IF NOT EXISTS review_records_b01_tenant_status_idx
    ON media_product.review_records (tenant_id, ((canonical_data->>'status')));

CREATE TABLE IF NOT EXISTS media_product.project_summary_idempotency (
    id bigserial PRIMARY KEY,
    tenant_id uuid NOT NULL REFERENCES openclaw_account.tenants(id),
    operation text NOT NULL,
    idempotency_key text NOT NULL,
    request_fingerprint text NOT NULL,
    public_artifact_id text NOT NULL,
    response_json jsonb NOT NULL,
    response_status integer NOT NULL DEFAULT 200 CHECK (response_status BETWEEN 200 AND 299),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, operation, idempotency_key)
);

CREATE INDEX IF NOT EXISTS project_summary_idempotency_b01_tenant_created_idx
    ON media_product.project_summary_idempotency (tenant_id, created_at DESC);
