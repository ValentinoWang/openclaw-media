CREATE SCHEMA IF NOT EXISTS media_product;

CREATE SCHEMA IF NOT EXISTS media_document;

CREATE OR REPLACE FUNCTION media_product.touch_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION media_product.reject_ready_revision_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF OLD.state = 'ready' THEN
        RAISE EXCEPTION 'ready document revisions are immutable' USING ERRCODE = '55000';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION media_product.reject_ready_body_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    revision_state TEXT;
BEGIN
    SELECT state INTO revision_state
      FROM media_product.document_revisions
     WHERE tenant_id = OLD.tenant_id
       AND public_artifact_id = OLD.public_artifact_id
       AND revision = OLD.revision;
    IF revision_state = 'ready' THEN
        RAISE EXCEPTION 'ready document revision bodies are immutable' USING ERRCODE = '55000';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;

DO $$
DECLARE
    table_name TEXT;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'activities',
        'assets',
        'material_deconstructions',
        'creative_patterns',
        'creation_runs',
        'published_posts',
        'business_accounts',
        'business_opportunities',
        'creator_profiles',
        'tracks',
        'material_usages',
        'decision_traces',
        'track_creator_memberships',
        'metric_snapshots',
        'account_metric_snapshots',
        'growth_summaries'
    ] LOOP
        EXECUTE format(
            'CREATE TABLE media_product.%I (
                id BIGSERIAL PRIMARY KEY,
                tenant_id UUID NOT NULL REFERENCES openclaw_account.tenants(id) ON DELETE RESTRICT,
                public_id TEXT NOT NULL CHECK (length(btrim(public_id)) > 0),
                source_version TEXT NOT NULL CHECK (length(btrim(source_version)) > 0),
                revision INTEGER NOT NULL DEFAULT 1 CHECK (revision > 0),
                canonical_data JSONB NOT NULL DEFAULT ''{}''::jsonb CHECK (jsonb_typeof(canonical_data) = ''object''),
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                UNIQUE (tenant_id, public_id)
            )',
            table_name
        );
        EXECUTE format(
            'CREATE INDEX %I ON media_product.%I (tenant_id, updated_at DESC, public_id)',
            table_name || '_tenant_updated_idx',
            table_name
        );
        EXECUTE format(
            'CREATE TRIGGER %I BEFORE UPDATE ON media_product.%I
             FOR EACH ROW EXECUTE FUNCTION media_product.touch_updated_at()',
            table_name || '_touch_updated_at',
            table_name
        );
    END LOOP;
END;
$$;

CREATE TABLE media_product.content_projects (
    id BIGSERIAL PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES openclaw_account.tenants(id) ON DELETE RESTRICT,
    public_id TEXT NOT NULL CHECK (length(btrim(public_id)) > 0),
    title TEXT NOT NULL CHECK (length(btrim(title)) > 0),
    stage TEXT NOT NULL CHECK (length(btrim(stage)) > 0),
    revision INTEGER NOT NULL DEFAULT 1 CHECK (revision > 0),
    canonical_data JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(canonical_data) = 'object'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, public_id)
);

CREATE TABLE media_product.document_artifacts (
    id BIGSERIAL PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES openclaw_account.tenants(id) ON DELETE RESTRICT,
    public_id TEXT NOT NULL CHECK (length(btrim(public_id)) > 0),
    public_project_id TEXT NOT NULL CHECK (length(btrim(public_project_id)) > 0),
    artifact_kind TEXT NOT NULL CHECK (artifact_kind IN (
        'research_snapshot', 'asset_digest', 'decision_brief', 'creation_document',
        'publishing_package', 'review_report', 'project_summary'
    )),
    workspace_mode TEXT NOT NULL CHECK (workspace_mode IN ('personal_web', 'organization_lark')),
    body_authority TEXT NOT NULL CHECK (body_authority IN ('internal', 'lark')),
    current_revision INTEGER NOT NULL DEFAULT 1 CHECK (current_revision > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, public_id),
    FOREIGN KEY (tenant_id, public_project_id)
        REFERENCES media_product.content_projects(tenant_id, public_id) ON DELETE RESTRICT,
    CHECK (workspace_mode <> 'personal_web' OR body_authority = 'internal'),
    CHECK (artifact_kind NOT IN ('publishing_package', 'project_summary') OR body_authority = 'internal')
);

CREATE TABLE media_product.document_revisions (
    id BIGSERIAL PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES openclaw_account.tenants(id) ON DELETE RESTRICT,
    public_artifact_id TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision > 0),
    state TEXT NOT NULL CHECK (state IN ('draft', 'generating', 'ready', 'failed', 'conflict', 'archived')),
    base_revision INTEGER CHECK (base_revision IS NULL OR base_revision > 0),
    body_checksum TEXT NOT NULL CHECK (body_checksum ~ '^[a-f0-9]{64}$'),
    actor_public_id TEXT NOT NULL CHECK (length(btrim(actor_public_id)) > 0),
    generation_source TEXT NOT NULL CHECK (length(btrim(generation_source)) > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, public_artifact_id, revision),
    FOREIGN KEY (tenant_id, public_artifact_id)
        REFERENCES media_product.document_artifacts(tenant_id, public_id) ON DELETE RESTRICT,
    CHECK (base_revision IS NULL OR base_revision < revision)
);

CREATE TRIGGER document_revisions_ready_immutable
    BEFORE UPDATE OR DELETE ON media_product.document_revisions
    FOR EACH ROW EXECUTE FUNCTION media_product.reject_ready_revision_mutation();

CREATE TABLE media_document.revision_bodies (
    id BIGSERIAL PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES openclaw_account.tenants(id) ON DELETE RESTRICT,
    public_artifact_id TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision > 0),
    schema_version TEXT NOT NULL CHECK (schema_version = 'media.document.body.v1'),
    body_json JSONB NOT NULL CHECK (
        jsonb_typeof(body_json) = 'object'
        AND body_json->>'schemaVersion' = 'media.document.body.v1'
        AND jsonb_typeof(body_json->'blocks') = 'array'
    ),
    body_checksum TEXT NOT NULL CHECK (body_checksum ~ '^[a-f0-9]{64}$'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, public_artifact_id, revision),
    FOREIGN KEY (tenant_id, public_artifact_id, revision)
        REFERENCES media_product.document_revisions(tenant_id, public_artifact_id, revision) ON DELETE RESTRICT
);

CREATE TRIGGER revision_bodies_ready_immutable
    BEFORE UPDATE OR DELETE ON media_document.revision_bodies
    FOR EACH ROW EXECUTE FUNCTION media_product.reject_ready_body_mutation();

CREATE TABLE media_document.exports (
    id BIGSERIAL PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES openclaw_account.tenants(id) ON DELETE RESTRICT,
    public_export_id TEXT NOT NULL CHECK (length(btrim(public_export_id)) > 0),
    public_artifact_id TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision > 0),
    format TEXT NOT NULL CHECK (format IN ('docx', 'pdf')),
    state TEXT NOT NULL CHECK (state IN ('queued', 'rendering', 'ready', 'failed')),
    template_version TEXT NOT NULL CHECK (length(btrim(template_version)) > 0),
    renderer_version TEXT NOT NULL CHECK (length(btrim(renderer_version)) > 0),
    idempotency_identity TEXT NOT NULL CHECK (length(btrim(idempotency_identity)) > 0),
    source_body_checksum TEXT NOT NULL CHECK (source_body_checksum ~ '^[a-f0-9]{64}$'),
    content_checksum TEXT CHECK (content_checksum IS NULL OR content_checksum ~ '^[a-f0-9]{64}$'),
    object_ref TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, public_export_id),
    UNIQUE (tenant_id, idempotency_identity),
    FOREIGN KEY (tenant_id, public_artifact_id, revision)
        REFERENCES media_product.document_revisions(tenant_id, public_artifact_id, revision) ON DELETE RESTRICT,
    CHECK ((state = 'ready') = (content_checksum IS NOT NULL AND object_ref IS NOT NULL))
);

DO $$
DECLARE
    table_name TEXT;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'owned_media_accounts',
        'account_track_strategies',
        'signal_snapshots',
        'publishing_packages',
        'publishing_checks',
        'review_records'
    ] LOOP
        EXECUTE format(
            'CREATE TABLE media_product.%I (
                id BIGSERIAL PRIMARY KEY,
                tenant_id UUID NOT NULL REFERENCES openclaw_account.tenants(id) ON DELETE RESTRICT,
                public_id TEXT NOT NULL CHECK (length(btrim(public_id)) > 0),
                revision INTEGER NOT NULL DEFAULT 1 CHECK (revision > 0),
                canonical_data JSONB NOT NULL DEFAULT ''{}''::jsonb CHECK (jsonb_typeof(canonical_data) = ''object''),
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                UNIQUE (tenant_id, public_id)
            )',
            table_name
        );
        EXECUTE format(
            'CREATE INDEX %I ON media_product.%I (tenant_id, updated_at DESC, public_id)',
            table_name || '_tenant_updated_idx',
            table_name
        );
    END LOOP;
END;
$$;

CREATE TABLE media_product.lark_tenant_installations (
    id BIGSERIAL PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES openclaw_account.tenants(id) ON DELETE RESTRICT,
    installation_public_id TEXT NOT NULL CHECK (length(btrim(installation_public_id)) > 0),
    status TEXT NOT NULL CHECK (status IN ('active', 'disabled', 'revoked')),
    config JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(config) = 'object'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, installation_public_id)
);

CREATE TABLE media_product.lark_document_bindings (
    id BIGSERIAL PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES openclaw_account.tenants(id) ON DELETE RESTRICT,
    public_artifact_id TEXT NOT NULL,
    remote_document_version TEXT NOT NULL CHECK (length(btrim(remote_document_version)) > 0),
    body_checksum TEXT NOT NULL CHECK (body_checksum ~ '^[a-f0-9]{64}$'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, public_artifact_id),
    FOREIGN KEY (tenant_id, public_artifact_id)
        REFERENCES media_product.document_artifacts(tenant_id, public_id) ON DELETE RESTRICT
);

CREATE TABLE media_product.lark_document_block_mappings (
    id BIGSERIAL PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES openclaw_account.tenants(id) ON DELETE RESTRICT,
    public_artifact_id TEXT NOT NULL,
    public_block_id TEXT NOT NULL CHECK (length(btrim(public_block_id)) > 0),
    remote_block_id TEXT NOT NULL CHECK (length(btrim(remote_block_id)) > 0),
    remote_document_version TEXT NOT NULL CHECK (length(btrim(remote_document_version)) > 0),
    block_checksum TEXT NOT NULL CHECK (block_checksum ~ '^[a-f0-9]{64}$'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, public_artifact_id, public_block_id),
    UNIQUE (tenant_id, public_artifact_id, remote_block_id),
    FOREIGN KEY (tenant_id, public_artifact_id)
        REFERENCES media_product.document_artifacts(tenant_id, public_id) ON DELETE RESTRICT
);

CREATE TABLE media_product.sync_batches (
    id BIGSERIAL PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES openclaw_account.tenants(id) ON DELETE RESTRICT,
    public_sync_id TEXT NOT NULL CHECK (length(btrim(public_sync_id)) > 0),
    state TEXT NOT NULL CHECK (state IN ('queued', 'running', 'succeeded', 'failed', 'conflict')),
    remote_document_version TEXT,
    body_checksum TEXT CHECK (body_checksum IS NULL OR body_checksum ~ '^[a-f0-9]{64}$'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, public_sync_id)
);

CREATE TABLE openclaw_account.usage_events (
    id BIGSERIAL PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES openclaw_account.tenants(id) ON DELETE RESTRICT,
    event_public_id TEXT NOT NULL CHECK (length(btrim(event_public_id)) > 0),
    kind TEXT NOT NULL CHECK (length(btrim(kind)) > 0),
    quantity NUMERIC NOT NULL CHECK (quantity > 0),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(metadata) = 'object'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, event_public_id)
);
