PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS archive_records (
    archive_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    commit_id TEXT NOT NULL,
    manifest_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    pipeline_id TEXT,
    pipeline_version TEXT,
    device_id TEXT,
    artifacts_json TEXT NOT NULL,
    cloud_bytes INTEGER NOT NULL DEFAULT 0 CHECK (cloud_bytes >= 0),
    media_cloud_bytes INTEGER NOT NULL DEFAULT 0 CHECK (media_cloud_bytes = 0),
    state TEXT NOT NULL CHECK (state IN ('active', 'deleting', 'delete_failed')),
    revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 0),
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS archive_records_tenant_created_idx
    ON archive_records (tenant_id, created_at DESC, archive_id DESC);

CREATE TABLE IF NOT EXISTS archive_commits (
    commit_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    archive_id TEXT NOT NULL REFERENCES archive_records(archive_id) ON DELETE CASCADE,
    manifest_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('draft', 'committing', 'verifying', 'archived', 'failed', 'cancelled')),
    artifact_refs_json TEXT NOT NULL,
    total_bytes INTEGER NOT NULL CHECK (total_bytes >= 0),
    cloud_bytes INTEGER NOT NULL CHECK (cloud_bytes >= 0),
    media_cloud_bytes INTEGER NOT NULL DEFAULT 0 CHECK (media_cloud_bytes = 0),
    committed_at REAL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS archive_commits_tenant_idx
    ON archive_commits (tenant_id, created_at DESC, commit_id DESC);

CREATE TABLE IF NOT EXISTS archive_attachments (
    attachment_id TEXT PRIMARY KEY,
    archive_id TEXT NOT NULL REFERENCES archive_records(archive_id) ON DELETE CASCADE,
    artifact_ref TEXT NOT NULL,
    mode TEXT NOT NULL CHECK (mode IN ('content', 'descriptor_only', 'forbidden')),
    mime_type TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    size_bytes INTEGER NOT NULL CHECK (size_bytes >= 0),
    encoding TEXT,
    metadata_json TEXT NOT NULL,
    content BLOB,
    CHECK (mode = 'content' OR content IS NULL),
    CHECK (mode = 'content' OR encoding IS NULL)
);

CREATE INDEX IF NOT EXISTS archive_attachments_archive_idx
    ON archive_attachments (archive_id, attachment_id);

CREATE TABLE IF NOT EXISTS archive_projections (
    projection_id TEXT PRIMARY KEY,
    archive_id TEXT NOT NULL REFERENCES archive_records(archive_id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('db', 'attachment', 'web')),
    ref TEXT NOT NULL,
    artifact_refs_json TEXT NOT NULL,
    consistent INTEGER NOT NULL CHECK (consistent IN (0, 1))
);

CREATE INDEX IF NOT EXISTS archive_projections_archive_idx
    ON archive_projections (archive_id, projection_id);

CREATE TABLE IF NOT EXISTS archive_delete_plans (
    delete_plan_id TEXT PRIMARY KEY,
    archive_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    expires_at REAL NOT NULL,
    created_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS archive_delete_plans_owner_idx
    ON archive_delete_plans (tenant_id, archive_id, expires_at);

CREATE TABLE IF NOT EXISTS archive_readback_receipts (
    readback_receipt_ref TEXT PRIMARY KEY,
    archive_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('commit', 'delete')),
    artifact_refs_json TEXT NOT NULL,
    projection_refs_json TEXT NOT NULL,
    verified INTEGER NOT NULL CHECK (verified IN (0, 1)),
    db_present INTEGER NOT NULL CHECK (db_present IN (0, 1)),
    attachments_present INTEGER NOT NULL CHECK (attachments_present IN (0, 1)),
    projections_present INTEGER NOT NULL CHECK (projections_present IN (0, 1)),
    checked_at REAL NOT NULL,
    created_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS archive_readback_owner_idx
    ON archive_readback_receipts (tenant_id, archive_id, created_at, readback_receipt_ref);

CREATE TABLE IF NOT EXISTS archive_idempotency (
    scope TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    request_fingerprint TEXT NOT NULL,
    archive_id TEXT,
    replay_kind TEXT NOT NULL CHECK (replay_kind IN ('response', 'archive_commit', 'archive_readback')),
    response_json TEXT NOT NULL,
    status_code INTEGER NOT NULL CHECK (status_code BETWEEN 200 AND 599),
    created_at REAL NOT NULL,
    PRIMARY KEY (scope, operation_id, idempotency_key)
);

PRAGMA user_version = 4;
