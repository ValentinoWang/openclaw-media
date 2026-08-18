BEGIN;

ALTER TABLE media_product.document_artifacts
    ADD COLUMN IF NOT EXISTS docx_url text,
    ADD COLUMN IF NOT EXISTS docx_url_expires_at timestamptz;

CREATE TABLE IF NOT EXISTS media_product.b06_idempotency_keys (
    id bigserial PRIMARY KEY,
    tenant_id uuid NOT NULL REFERENCES openclaw_account.tenants(id),
    operation text NOT NULL,
    idempotency_key text NOT NULL,
    request_checksum text NOT NULL,
    response_json jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, operation, idempotency_key)
);

CREATE INDEX IF NOT EXISTS b06_idempotency_keys_created_idx
    ON media_product.b06_idempotency_keys (tenant_id, created_at DESC);

CREATE INDEX IF NOT EXISTS publishing_checks_b06_package_idx
    ON media_product.publishing_checks (
        tenant_id,
        (canonical_data->>'public_package_id'),
        revision DESC
    );

CREATE UNIQUE INDEX IF NOT EXISTS published_posts_b06_package_idx
    ON media_product.published_posts (
        tenant_id,
        (canonical_data->>'public_package_id')
    )
    WHERE canonical_data ? 'public_package_id';

CREATE UNIQUE INDEX IF NOT EXISTS published_posts_b06_url_idx
    ON media_product.published_posts (
        tenant_id,
        (canonical_data->>'platform'),
        (canonical_data->>'published_url')
    )
    WHERE canonical_data ? 'platform'
      AND canonical_data ? 'published_url';

CREATE INDEX IF NOT EXISTS publishing_packages_b06_status_idx
    ON media_product.publishing_packages (
        tenant_id,
        (canonical_data->>'status'),
        updated_at DESC
    );

INSERT INTO media_product.migration_ledger (version, name)
VALUES (14, 'b06_publishing')
ON CONFLICT (version) DO NOTHING;

COMMIT;
