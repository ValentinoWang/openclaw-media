CREATE TABLE IF NOT EXISTS media_document.lark_read_mirrors (
    tenant_id UUID NOT NULL REFERENCES openclaw_account.tenants(id) ON DELETE RESTRICT,
    public_artifact_id TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision > 0),
    body_json JSONB NOT NULL CHECK (
        jsonb_typeof(body_json) = 'object'
        AND body_json->>'schemaVersion' = 'media.document.body.v1'
        AND jsonb_typeof(body_json->'blocks') = 'array'
    ),
    body_checksum TEXT NOT NULL CHECK (body_checksum ~ '^[a-f0-9]{64}$'),
    source_url TEXT NOT NULL CHECK (source_url ~ '^https://'),
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, public_artifact_id, revision),
    FOREIGN KEY (tenant_id, public_artifact_id, revision)
        REFERENCES media_product.document_revisions(tenant_id, public_artifact_id, revision)
        ON DELETE RESTRICT
);

CREATE OR REPLACE FUNCTION media_document.enforce_lark_read_mirror_authority()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    authority TEXT;
BEGIN
    SELECT body_authority INTO authority
      FROM media_product.document_artifacts
     WHERE tenant_id = NEW.tenant_id
       AND public_id = NEW.public_artifact_id;
    IF authority IS DISTINCT FROM 'lark' THEN
        RAISE EXCEPTION 'only lark-authority artifacts may store lark read mirrors';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS lark_read_mirror_authority ON media_document.lark_read_mirrors;

CREATE TRIGGER lark_read_mirror_authority
    BEFORE INSERT OR UPDATE ON media_document.lark_read_mirrors
    FOR EACH ROW EXECUTE FUNCTION media_document.enforce_lark_read_mirror_authority();
