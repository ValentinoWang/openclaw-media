BEGIN;

CREATE INDEX IF NOT EXISTS admin_audit_b13_idempotency_idx
    ON openclaw_account.admin_audit (
        actor_user_id,
        action,
        (metadata ->> 'idempotencyKey'),
        created_at DESC
    )
    WHERE action IN (
        'media_b13_product_mapping',
        'media_b13_grant',
        'media_b13_redemption_batch',
        'media_b13_fulfillment_recover',
        'media_b13_fulfillment_refund'
    );

CREATE INDEX IF NOT EXISTS admin_audit_b13_created_idx
    ON openclaw_account.admin_audit (created_at DESC, id DESC)
    WHERE action IN (
        'media_b13_product_mapping',
        'media_b13_grant',
        'media_b13_redemption_batch',
        'media_b13_fulfillment_recover',
        'media_b13_fulfillment_refund'
    );

CREATE INDEX IF NOT EXISTS product_mappings_b13_plan_status_idx
    ON openclaw_account.product_mappings (plan_id, status, created_at DESC);

CREATE INDEX IF NOT EXISTS redemption_batches_b13_created_idx
    ON openclaw_account.redemption_batches (created_at DESC, id DESC);

CREATE INDEX IF NOT EXISTS fulfillments_b13_created_status_idx
    ON openclaw_account.fulfillments (created_at DESC, status, id DESC);

CREATE INDEX IF NOT EXISTS ledger_entries_b13_admin_grant_idx
    ON openclaw_account.ledger_entries (created_at DESC, id DESC)
    WHERE entry_type = 'admin_grant' AND source_type = 'admin_grant';

INSERT INTO openclaw_account.schema_migrations (revision)
VALUES ('014_b13_admin_billing')
ON CONFLICT (revision) DO NOTHING;

COMMIT;

