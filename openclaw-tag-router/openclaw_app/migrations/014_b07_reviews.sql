BEGIN;

CREATE TABLE IF NOT EXISTS media_product.b07_idempotency_keys (
    id bigserial PRIMARY KEY,
    tenant_id uuid NOT NULL REFERENCES openclaw_account.tenants(id),
    operation text NOT NULL,
    idempotency_key text NOT NULL,
    request_checksum text NOT NULL,
    response_json jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, operation, idempotency_key)
);

CREATE INDEX IF NOT EXISTS b07_idempotency_keys_created_idx
    ON media_product.b07_idempotency_keys (tenant_id, created_at DESC);

CREATE INDEX IF NOT EXISTS b07_review_records_tenant_updated_idx
    ON media_product.review_records (tenant_id, updated_at DESC, public_id);

DROP INDEX IF EXISTS media_product.b07_review_records_post_window_idx;

CREATE UNIQUE INDEX IF NOT EXISTS b07_review_records_post_idx
    ON media_product.review_records (
        tenant_id,
        (canonical_data->>'public_post_id')
    )
    WHERE canonical_data ? 'public_post_id';

CREATE INDEX IF NOT EXISTS b07_metric_snapshots_content_idx
    ON media_product.metric_snapshots (
        tenant_id,
        (canonical_data->>'subject_type'),
        (canonical_data->>'public_subject_id'),
        updated_at DESC,
        public_id
    );

CREATE UNIQUE INDEX IF NOT EXISTS b07_metric_snapshots_dedupe_idx
    ON media_product.metric_snapshots (
        tenant_id,
        (canonical_data->>'public_subject_id'),
        (canonical_data->>'review_window'),
        (canonical_data->>'metric_key'),
        (canonical_data->>'collected_at')
    )
    WHERE canonical_data ? 'public_subject_id'
      AND canonical_data ? 'review_window'
      AND canonical_data ? 'metric_key'
      AND canonical_data ? 'collected_at';

CREATE INDEX IF NOT EXISTS b07_account_metric_snapshots_tenant_updated_idx
    ON media_product.account_metric_snapshots (
        tenant_id,
        (COALESCE(canonical_data->>'public_account_id', canonical_data->>'public_subject_id')),
        updated_at DESC,
        public_id
    );

CREATE UNIQUE INDEX IF NOT EXISTS b07_account_metric_snapshots_dedupe_idx
    ON media_product.account_metric_snapshots (
        tenant_id,
        (COALESCE(canonical_data->>'public_account_id', canonical_data->>'public_subject_id')),
        (canonical_data->>'review_window'),
        (canonical_data->>'metric_key'),
        (canonical_data->>'collected_at')
    )
    WHERE (canonical_data ? 'public_account_id' OR canonical_data ? 'public_subject_id')
      AND canonical_data ? 'review_window'
      AND canonical_data ? 'metric_key'
      AND canonical_data ? 'collected_at';

INSERT INTO media_product.migration_ledger (version, name)
VALUES (14, 'b07_reviews')
ON CONFLICT (version) DO NOTHING;

COMMIT;
