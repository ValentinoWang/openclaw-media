ALTER TABLE openclaw_account.users
    ADD COLUMN is_maintainer BOOLEAN NOT NULL DEFAULT FALSE,
    ADD CONSTRAINT users_maintainer_requires_admin
        CHECK (NOT is_maintainer OR role = 'admin');

CREATE TABLE openclaw_account.if2_idempotency_receipts (
    id BIGSERIAL PRIMARY KEY,
    scope_kind TEXT NOT NULL CHECK (scope_kind IN ('tenant', 'admin_actor')),
    scope_id UUID NOT NULL,
    operation_id TEXT NOT NULL CHECK (length(btrim(operation_id)) > 0),
    idempotency_key TEXT NOT NULL CHECK (idempotency_key ~ '^[A-Za-z0-9_-]{8,128}$'),
    path_fingerprint BYTEA NOT NULL CHECK (octet_length(path_fingerprint) = 32),
    request_fingerprint BYTEA NOT NULL CHECK (octet_length(request_fingerprint) = 32),
    state TEXT NOT NULL CHECK (state IN ('reserved', 'completed', 'failed')),
    response_status INTEGER CHECK (response_status IS NULL OR response_status BETWEEN 100 AND 599),
    response_json JSONB CHECK (response_json IS NULL OR jsonb_typeof(response_json) = 'object'),
    lease_owner UUID,
    lease_expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    UNIQUE (scope_kind, scope_id, operation_id, idempotency_key),
    CHECK ((state = 'reserved') = (lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL)),
    CHECK ((state = 'completed') = (response_status IS NOT NULL AND response_json IS NOT NULL AND completed_at IS NOT NULL))
);

CREATE INDEX if2_idempotency_receipts_lease_idx
    ON openclaw_account.if2_idempotency_receipts (state, lease_expires_at)
    WHERE state = 'reserved';

ALTER TABLE openclaw_account.admin_audit
    ADD COLUMN request_id UUID,
    ADD COLUMN operation_id TEXT,
    ADD COLUMN target_tenant_id UUID REFERENCES openclaw_account.tenants(id) ON DELETE RESTRICT,
    ADD COLUMN target_public_tenant_id TEXT,
    ADD COLUMN idempotency_key TEXT,
    ADD COLUMN request_fingerprint BYTEA,
    ADD CONSTRAINT admin_audit_request_fingerprint_sha256
        CHECK (request_fingerprint IS NULL OR octet_length(request_fingerprint) = 32),
    ADD CONSTRAINT admin_audit_target_tenant_pair
        CHECK ((target_tenant_id IS NULL) = (target_public_tenant_id IS NULL));

CREATE INDEX admin_audit_request_operation_idx
    ON openclaw_account.admin_audit (request_id, operation_id);

CREATE INDEX admin_audit_target_tenant_created_idx
    ON openclaw_account.admin_audit (target_tenant_id, created_at DESC)
    WHERE target_tenant_id IS NOT NULL;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM media_product.lark_document_bindings)
       OR EXISTS (SELECT 1 FROM media_product.sync_batches)
       OR EXISTS (SELECT 1 FROM media_product.lark_document_block_mappings) THEN
        RAISE EXCEPTION
            'legacy Lark document state requires connector materialization before 027'
            USING ERRCODE = '55000';
    END IF;
END;
$$;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
          FROM media_document.revision_bodies AS body
          JOIN media_product.document_artifacts AS artifact
            ON artifact.tenant_id = body.tenant_id
           AND artifact.public_id = body.public_artifact_id
         WHERE artifact.body_authority = 'lark'
    ) THEN
        RAISE EXCEPTION
            'Lark-authority artifacts must not retain internal revision bodies'
            USING ERRCODE = '55000';
    END IF;
END;
$$;

CREATE OR REPLACE FUNCTION media_document.enforce_revision_body_authority()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    artifact_authority TEXT;
BEGIN
    SELECT body_authority INTO STRICT artifact_authority
      FROM media_product.document_artifacts
     WHERE tenant_id = NEW.tenant_id
       AND public_id = NEW.public_artifact_id;
    IF artifact_authority <> 'internal' THEN
        RAISE EXCEPTION 'only internal-authority artifacts may store revision bodies'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER revision_bodies_internal_authority_only
    BEFORE INSERT OR UPDATE ON media_document.revision_bodies
    FOR EACH ROW EXECUTE FUNCTION media_document.enforce_revision_body_authority();

ALTER TABLE media_product.sync_batches
    ADD COLUMN public_artifact_id TEXT NOT NULL,
    ADD COLUMN revision INTEGER NOT NULL CHECK (revision > 0),
    ADD COLUMN operation TEXT NOT NULL CHECK (operation IN ('read', 'save')),
    ADD COLUMN idempotency_key TEXT,
    ADD COLUMN request_checksum TEXT,
    ADD COLUMN base_remote_document_version TEXT,
    ADD COLUMN block_count INTEGER,
    ADD COLUMN protected_block_count INTEGER,
    ADD COLUMN completed_at TIMESTAMPTZ,
    ADD COLUMN error_code TEXT,
    ADD COLUMN error_detail JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD CONSTRAINT sync_batches_revision_fk
        FOREIGN KEY (tenant_id, public_artifact_id, revision)
        REFERENCES media_product.document_revisions
            (tenant_id, public_artifact_id, revision) ON DELETE RESTRICT,
    ADD CONSTRAINT sync_batches_error_detail_object
        CHECK (jsonb_typeof(error_detail) = 'object'),
    ADD CONSTRAINT sync_batches_save_shape CHECK (
        operation <> 'save' OR (
            idempotency_key ~ '^[A-Za-z0-9_-]{8,128}$'
            AND request_checksum ~ '^[a-f0-9]{64}$'
            AND length(btrim(base_remote_document_version)) > 0
        )
    ),
    ADD CONSTRAINT sync_batches_counts CHECK (
        (block_count IS NULL AND protected_block_count IS NULL)
        OR (
            block_count >= 0
            AND protected_block_count >= 0
            AND protected_block_count <= block_count
        )
    ),
    ADD CONSTRAINT sync_batches_terminal_shape CHECK (
        (state IN ('queued', 'running') AND completed_at IS NULL)
        OR (
            state = 'succeeded'
            AND completed_at IS NOT NULL
            AND remote_document_version IS NOT NULL
            AND body_checksum IS NOT NULL
            AND block_count IS NOT NULL
            AND protected_block_count IS NOT NULL
            AND error_code IS NULL
        )
        OR (
            state IN ('failed', 'conflict')
            AND completed_at IS NOT NULL
            AND error_code IS NOT NULL
        )
    );

CREATE UNIQUE INDEX sync_batches_save_idempotency_uq
    ON media_product.sync_batches (tenant_id, operation, idempotency_key)
    WHERE operation = 'save';

CREATE UNIQUE INDEX sync_batches_success_snapshot_uq
    ON media_product.sync_batches
        (tenant_id, public_artifact_id, revision, remote_document_version)
    WHERE state = 'succeeded';

CREATE OR REPLACE FUNCTION media_product.validate_sync_batch_artifact_authority()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    artifact_authority TEXT;
BEGIN
    SELECT body_authority INTO STRICT artifact_authority
      FROM media_product.document_artifacts
     WHERE tenant_id = NEW.tenant_id
       AND public_id = NEW.public_artifact_id;
    IF artifact_authority <> 'lark' THEN
        RAISE EXCEPTION 'only Lark-authority artifacts may have document sync batches'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER sync_batches_lark_artifact_only
    BEFORE INSERT OR UPDATE ON media_product.sync_batches
    FOR EACH ROW EXECUTE FUNCTION media_product.validate_sync_batch_artifact_authority();

ALTER TABLE media_product.lark_document_bindings
    ADD COLUMN public_sync_id TEXT NOT NULL,
    DROP COLUMN remote_document_version,
    DROP COLUMN body_checksum,
    DROP COLUMN status,
    ADD CONSTRAINT lark_document_bindings_sync_fk
        FOREIGN KEY (tenant_id, public_sync_id)
        REFERENCES media_product.sync_batches (tenant_id, public_sync_id)
        ON DELETE RESTRICT;

ALTER TABLE media_product.lark_document_block_mappings
    ADD COLUMN public_sync_id TEXT NOT NULL,
    ADD COLUMN is_protected BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN protection_reason TEXT,
    DROP COLUMN public_artifact_id,
    DROP COLUMN remote_document_version,
    ADD CONSTRAINT lark_block_protection_shape CHECK (
        (is_protected AND length(btrim(protection_reason)) > 0)
        OR (NOT is_protected AND protection_reason IS NULL)
    ),
    ADD CONSTRAINT lark_block_mapping_sync_fk
        FOREIGN KEY (tenant_id, public_sync_id)
        REFERENCES media_product.sync_batches (tenant_id, public_sync_id)
        ON DELETE RESTRICT,
    ADD UNIQUE (tenant_id, public_sync_id, public_block_id),
    ADD UNIQUE (tenant_id, public_sync_id, remote_block_id);

CREATE OR REPLACE FUNCTION media_product.reject_terminal_sync_batch_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF OLD.state IN ('succeeded', 'failed', 'conflict') THEN
        RAISE EXCEPTION 'terminal document sync batches are immutable'
            USING ERRCODE = '55000';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER sync_batches_terminal_immutable
    BEFORE UPDATE OR DELETE ON media_product.sync_batches
    FOR EACH ROW EXECUTE FUNCTION media_product.reject_terminal_sync_batch_mutation();

CREATE OR REPLACE FUNCTION media_product.reject_terminal_sync_mapping_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    batch_state TEXT;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        SELECT state INTO STRICT batch_state
          FROM media_product.sync_batches
         WHERE tenant_id = OLD.tenant_id
           AND public_sync_id = OLD.public_sync_id;
        IF batch_state IN ('succeeded', 'failed', 'conflict') THEN
            RAISE EXCEPTION 'terminal document sync mappings are immutable'
                USING ERRCODE = '55000';
        END IF;
    END IF;
    IF TG_OP <> 'DELETE' THEN
        SELECT state INTO STRICT batch_state
          FROM media_product.sync_batches
         WHERE tenant_id = NEW.tenant_id
           AND public_sync_id = NEW.public_sync_id;
        IF batch_state IN ('succeeded', 'failed', 'conflict') THEN
            RAISE EXCEPTION 'terminal document sync mappings are immutable'
                USING ERRCODE = '55000';
        END IF;
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER lark_document_block_mappings_terminal_immutable
    BEFORE INSERT OR UPDATE OR DELETE ON media_product.lark_document_block_mappings
    FOR EACH ROW EXECUTE FUNCTION media_product.reject_terminal_sync_mapping_mutation();

CREATE OR REPLACE FUNCTION media_product.validate_lark_document_binding()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    selected_batch media_product.sync_batches%ROWTYPE;
    old_completed_at TIMESTAMPTZ;
    old_batch_id BIGINT;
    artifact_authority TEXT;
BEGIN
    SELECT * INTO STRICT selected_batch
      FROM media_product.sync_batches
     WHERE tenant_id = NEW.tenant_id
       AND public_sync_id = NEW.public_sync_id;
    IF selected_batch.state <> 'succeeded'
       OR selected_batch.public_artifact_id <> NEW.public_artifact_id THEN
        RAISE EXCEPTION 'Lark binding must select a succeeded batch for the same artifact'
            USING ERRCODE = '23514';
    END IF;
    SELECT body_authority INTO STRICT artifact_authority
      FROM media_product.document_artifacts
     WHERE tenant_id = NEW.tenant_id
       AND public_id = NEW.public_artifact_id;
    IF artifact_authority <> 'lark' THEN
        RAISE EXCEPTION 'only Lark-authority artifacts may have a Lark binding'
            USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'UPDATE' AND NEW.public_sync_id <> OLD.public_sync_id THEN
        SELECT completed_at, id INTO STRICT old_completed_at, old_batch_id
          FROM media_product.sync_batches
         WHERE tenant_id = OLD.tenant_id
           AND public_sync_id = OLD.public_sync_id;
        IF (selected_batch.completed_at, selected_batch.id) <= (old_completed_at, old_batch_id) THEN
            RAISE EXCEPTION 'Lark binding cannot move backward'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER lark_document_bindings_valid_pointer
    BEFORE INSERT OR UPDATE ON media_product.lark_document_bindings
    FOR EACH ROW EXECUTE FUNCTION media_product.validate_lark_document_binding();

CREATE OR REPLACE FUNCTION media_product.validate_terminal_sync_mapping_counts()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    actual_block_count INTEGER;
    actual_protected_count INTEGER;
BEGIN
    IF NEW.state <> 'succeeded' THEN
        RETURN NULL;
    END IF;
    SELECT COUNT(*)::INTEGER,
           COUNT(*) FILTER (WHERE is_protected)::INTEGER
      INTO actual_block_count, actual_protected_count
      FROM media_product.lark_document_block_mappings
     WHERE tenant_id = NEW.tenant_id
       AND public_sync_id = NEW.public_sync_id;
    IF actual_block_count <> NEW.block_count
       OR actual_protected_count <> NEW.protected_block_count THEN
        RAISE EXCEPTION 'document sync mapping inventory is incomplete'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$;

CREATE CONSTRAINT TRIGGER sync_batches_mapping_counts_complete
    AFTER INSERT OR UPDATE ON media_product.sync_batches
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION media_product.validate_terminal_sync_mapping_counts();

CREATE INDEX document_exports_worker_queue_idx
    ON media_document.exports (state, created_at, id)
    WHERE state IN ('queued', 'rendering');

CREATE OR REPLACE FUNCTION media_document.reject_ready_export_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF OLD.state = 'ready' THEN
        RAISE EXCEPTION 'ready document exports are immutable' USING ERRCODE = '55000';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER document_exports_ready_immutable
    BEFORE UPDATE OR DELETE ON media_document.exports
    FOR EACH ROW EXECUTE FUNCTION media_document.reject_ready_export_mutation();
