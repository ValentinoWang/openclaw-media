CREATE TABLE media_document.resources (
    id BIGSERIAL PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES openclaw_account.tenants(id) ON DELETE RESTRICT,
    public_resource_id TEXT NOT NULL CHECK (public_resource_id ~ '^[A-Za-z0-9_-]{8,160}$'),
    content_type TEXT NOT NULL CHECK (content_type IN (
        'application/octet-stream',
        'application/pdf',
        'image/gif',
        'image/jpeg',
        'image/png',
        'image/webp',
        'text/plain'
    )),
    file_name TEXT NOT NULL CHECK (
        length(btrim(file_name)) BETWEEN 1 AND 255
        AND file_name !~ '[/\\\\\\r\\n]'
    ),
    content_checksum TEXT NOT NULL CHECK (content_checksum ~ '^[a-f0-9]{64}$'),
    object_ref TEXT NOT NULL CHECK (
        length(btrim(object_ref)) BETWEEN 1 AND 1024
        AND object_ref !~ '^/'
        AND object_ref !~ '(^|/)\\.\\.(/|$)'
    ),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'archived')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    archived_at TIMESTAMPTZ,
    UNIQUE (tenant_id, public_resource_id),
    CHECK ((status = 'archived') = (archived_at IS NOT NULL))
);

CREATE INDEX document_resources_tenant_status_idx
    ON media_document.resources (tenant_id, status, public_resource_id);
