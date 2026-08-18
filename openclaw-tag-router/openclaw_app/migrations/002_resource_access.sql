PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS resource_links (
    resource_type TEXT NOT NULL,
    canonical_resource_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    docx_token TEXT NOT NULL,
    policy TEXT NOT NULL CHECK (policy IN ('org_link_edit', 'anyone_editable')),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'revoked', 'archived')),
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    PRIMARY KEY (resource_type, canonical_resource_id),
    FOREIGN KEY (resource_type, canonical_resource_id)
        REFERENCES resource_owners(resource_type, canonical_resource_id)
        ON DELETE RESTRICT,
    CHECK (length(tenant_id) = 36),
    CHECK (tenant_id = lower(tenant_id)),
    CHECK (tenant_id NOT GLOB '*[^0-9a-f-]*'),
    CHECK (substr(tenant_id, 9, 1) = '-' AND substr(tenant_id, 14, 1) = '-' AND substr(tenant_id, 19, 1) = '-' AND substr(tenant_id, 24, 1) = '-')
);

CREATE INDEX IF NOT EXISTS resource_links_tenant_status_idx
    ON resource_links(tenant_id, status, resource_type, canonical_resource_id);

CREATE TABLE IF NOT EXISTS resource_graph_edges (
    parent_resource_type TEXT NOT NULL,
    parent_resource_id TEXT NOT NULL,
    child_resource_type TEXT NOT NULL,
    child_resource_id TEXT NOT NULL,
    relation_type TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    PRIMARY KEY (
        parent_resource_type, parent_resource_id,
        child_resource_type, child_resource_id, relation_type
    ),
    FOREIGN KEY (parent_resource_type, parent_resource_id)
        REFERENCES resource_owners(resource_type, canonical_resource_id)
        ON DELETE RESTRICT,
    FOREIGN KEY (child_resource_type, child_resource_id)
        REFERENCES resource_owners(resource_type, canonical_resource_id)
        ON DELETE RESTRICT,
    CHECK (NOT (
        parent_resource_type = child_resource_type
        AND parent_resource_id = child_resource_id
    ))
);

CREATE INDEX IF NOT EXISTS resource_graph_edges_child_idx
    ON resource_graph_edges(child_resource_type, child_resource_id);
