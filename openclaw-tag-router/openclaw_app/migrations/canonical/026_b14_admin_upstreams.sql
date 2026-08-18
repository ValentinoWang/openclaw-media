CREATE INDEX IF NOT EXISTS admin_audit_b14_idempotency_idx
    ON openclaw_account.admin_audit (
        actor_user_id,
        action,
        (metadata ->> 'idempotencyKey'),
        created_at DESC
    )
    WHERE action IN (
        'media_b14_reconcile',
        'media_b14_rotate',
        'media_b14_revoke'
    );

CREATE INDEX IF NOT EXISTS admin_audit_b14_sync_idx
    ON openclaw_account.admin_audit (created_at DESC, id DESC)
    WHERE action IN (
        'media_b14_reconcile',
        'media_b14_rotate',
        'media_b14_revoke'
    );
