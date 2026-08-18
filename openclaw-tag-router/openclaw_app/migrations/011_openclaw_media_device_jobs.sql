PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS pair_codes (
    pair_code_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    pair_code_hash BLOB NOT NULL UNIQUE CHECK (length(pair_code_hash) = 32),
    device_label TEXT NOT NULL CHECK (length(trim(device_label)) BETWEEN 1 AND 200),
    expires_at REAL NOT NULL,
    created_at REAL NOT NULL,
    consumed_at REAL,
    consumed_device_id TEXT,
    consumed_fingerprint TEXT,
    consumed_idempotency_key TEXT,
    UNIQUE (tenant_id, consumed_idempotency_key)
);

CREATE INDEX IF NOT EXISTS pair_codes_tenant_created_idx
    ON pair_codes (tenant_id, created_at DESC);

CREATE TABLE IF NOT EXISTS devices (
    device_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    device_label TEXT NOT NULL CHECK (length(trim(device_label)) BETWEEN 1 AND 200),
    device_platform TEXT NOT NULL CHECK (device_platform = 'macos'),
    client_version TEXT NOT NULL CHECK (length(trim(client_version)) BETWEEN 1 AND 100),
    api_version TEXT NOT NULL DEFAULT '1',
    reported_catalog_digest TEXT NOT NULL DEFAULT '',
    api_compatible INTEGER NOT NULL DEFAULT 0 CHECK (api_compatible IN (0, 1)),
    catalog_compatible INTEGER NOT NULL DEFAULT 0 CHECK (catalog_compatible IN (0, 1)),
    capabilities_json TEXT NOT NULL DEFAULT '[]',
    credential_hash BLOB NOT NULL CHECK (length(credential_hash) = 32),
    credential_version INTEGER NOT NULL DEFAULT 1 CHECK (credential_version >= 1),
    state TEXT NOT NULL CHECK (state IN ('paired', 'online', 'revoked')),
    revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
    last_observed_at REAL,
    last_seen_at REAL,
    created_at REAL NOT NULL,
    revoked_at REAL
);

CREATE INDEX IF NOT EXISTS devices_tenant_state_idx
    ON devices (tenant_id, state, created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS devices_credential_hash_idx
    ON devices (credential_hash);

CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    pipeline_id TEXT NOT NULL CHECK (length(trim(pipeline_id)) BETWEEN 1 AND 200),
    pipeline_version TEXT NOT NULL CHECK (length(trim(pipeline_version)) BETWEEN 1 AND 100),
    catalog_digest TEXT NOT NULL CHECK (length(trim(catalog_digest)) BETWEEN 1 AND 300),
    device_id TEXT NOT NULL REFERENCES devices(device_id) ON DELETE RESTRICT,
    input_refs_json TEXT NOT NULL,
    output_selection_json TEXT NOT NULL,
    confirmation_ref TEXT,
    state TEXT NOT NULL CHECK (state IN ('queued', 'leased', 'acknowledged', 'running', 'succeeded', 'blocked', 'failed', 'expired', 'cancelled')),
    revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
    lease_id TEXT,
    lease_expires_at REAL,
    lease_device_id TEXT,
    leased_at REAL,
    ack_ref TEXT,
    acknowledged_at REAL,
    start_ref TEXT,
    started_at REAL,
    result_status TEXT CHECK (result_status IS NULL OR result_status IN ('succeeded', 'blocked', 'failed')),
    result_refs_json TEXT,
    artifact_refs_json TEXT,
    failure_code TEXT,
    result_fingerprint TEXT,
    completed_at REAL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS jobs_tenant_state_created_idx
    ON jobs (tenant_id, state, created_at DESC);
CREATE INDEX IF NOT EXISTS jobs_device_state_idx
    ON jobs (device_id, state, created_at DESC);

CREATE TABLE IF NOT EXISTS device_job_idempotency (
    scope TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    request_fingerprint TEXT NOT NULL,
    response_json TEXT NOT NULL,
    status_code INTEGER NOT NULL CHECK (status_code BETWEEN 200 AND 599),
    created_at REAL NOT NULL,
    PRIMARY KEY (scope, operation_id, idempotency_key)
);

PRAGMA user_version = 1;
