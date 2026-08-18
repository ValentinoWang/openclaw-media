PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS resource_owners (
    resource_type TEXT NOT NULL,
    canonical_resource_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    owner_revision INTEGER NOT NULL DEFAULT 1 CHECK (owner_revision >= 1),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'archived')),
    created_at INTEGER NOT NULL,
    archived_at INTEGER,
    PRIMARY KEY (resource_type, canonical_resource_id),
    CHECK (length(tenant_id) = 36),
    CHECK (tenant_id = lower(tenant_id)),
    CHECK (tenant_id NOT GLOB '*[^0-9a-f-]*'),
    CHECK (substr(tenant_id, 9, 1) = '-' AND substr(tenant_id, 14, 1) = '-' AND substr(tenant_id, 19, 1) = '-' AND substr(tenant_id, 24, 1) = '-')
);

CREATE INDEX IF NOT EXISTS resource_owners_tenant_status_idx
    ON resource_owners(tenant_id, status, resource_type, canonical_resource_id);

CREATE TABLE IF NOT EXISTS creation_run_summaries (
    resource_type TEXT NOT NULL DEFAULT 'media.creation_run'
        CHECK (resource_type = 'media.creation_run'),
    canonical_resource_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    status TEXT NOT NULL,
    entrypoint TEXT NOT NULL,
    created_at_text TEXT NOT NULL,
    updated_at_text TEXT NOT NULL,
    sort_at INTEGER NOT NULL CHECK (sort_at >= 0),
    search_text TEXT NOT NULL,
    summary_revision INTEGER NOT NULL DEFAULT 1 CHECK (summary_revision >= 1),
    indexed_at INTEGER NOT NULL,
    FOREIGN KEY (resource_type, canonical_resource_id)
        REFERENCES resource_owners(resource_type, canonical_resource_id)
        ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS creation_run_summaries_recent_idx
    ON creation_run_summaries(sort_at DESC, canonical_resource_id DESC);

CREATE TRIGGER IF NOT EXISTS resource_owner_is_immutable
BEFORE UPDATE OF tenant_id, owner_revision ON resource_owners
WHEN OLD.tenant_id <> NEW.tenant_id OR OLD.owner_revision <> NEW.owner_revision
BEGIN
    SELECT RAISE(ABORT, 'resource owner is immutable');
END;

CREATE TRIGGER IF NOT EXISTS resource_owner_status_transition
BEFORE UPDATE OF status ON resource_owners
WHEN OLD.status <> NEW.status
  AND NOT (OLD.status = 'active' AND NEW.status = 'archived')
BEGIN
    SELECT RAISE(ABORT, 'invalid resource owner status transition');
END;

CREATE TABLE IF NOT EXISTS resource_owner_repairs (
    repair_id TEXT PRIMARY KEY,
    resource_type TEXT NOT NULL,
    canonical_resource_id TEXT NOT NULL,
    projection_source TEXT NOT NULL,
    mismatch_kind TEXT NOT NULL CHECK (mismatch_kind IN ('missing', 'invalid', 'mismatch')),
    canonical_tenant_id TEXT NOT NULL,
    observed_tenant_id TEXT,
    owner_revision INTEGER NOT NULL CHECK (owner_revision >= 1),
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'resolved')),
    created_at INTEGER NOT NULL,
    resolved_at INTEGER,
    resolved_by_user_id TEXT,
    resolution_note TEXT,
    FOREIGN KEY (resource_type, canonical_resource_id)
        REFERENCES resource_owners(resource_type, canonical_resource_id)
        ON DELETE RESTRICT
);

CREATE UNIQUE INDEX IF NOT EXISTS resource_owner_one_pending_repair_idx
    ON resource_owner_repairs(resource_type, canonical_resource_id, projection_source)
    WHERE status = 'pending';

CREATE INDEX IF NOT EXISTS resource_owner_repairs_status_idx
    ON resource_owner_repairs(status, created_at);

PRAGMA user_version = 2;
