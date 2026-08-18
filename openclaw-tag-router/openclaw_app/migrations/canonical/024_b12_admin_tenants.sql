CREATE INDEX IF NOT EXISTS admin_audit_b12_tenant_read_idx
    ON openclaw_account.admin_audit (target_user_id, created_at DESC, id DESC)
    WHERE action IN ('admin_tenant_detail_read', 'admin_tenant_runs_read');

CREATE INDEX IF NOT EXISTS admin_audit_b12_created_idx
    ON openclaw_account.admin_audit (created_at DESC, id DESC)
    WHERE action IN ('admin_tenant_detail_read', 'admin_tenant_runs_read');

CREATE INDEX IF NOT EXISTS creation_runs_b12_tenant_updated_public_idx
    ON media_product.creation_runs (tenant_id, updated_at DESC, public_id ASC);

CREATE INDEX IF NOT EXISTS assets_b12_tenant_updated_public_idx
    ON media_product.assets (tenant_id, updated_at DESC, public_id ASC);

CREATE INDEX IF NOT EXISTS document_revisions_b12_tenant_updated_artifact_idx
    ON media_product.document_revisions (tenant_id, updated_at DESC, public_artifact_id ASC);

CREATE INDEX IF NOT EXISTS model_operations_b12_tenant_updated_idx
    ON openclaw_account.model_operations (tenant_id, updated_at DESC, id ASC);
