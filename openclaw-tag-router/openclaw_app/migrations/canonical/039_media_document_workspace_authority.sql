DO $$
BEGIN
    IF EXISTS (
        SELECT 1
          FROM media_product.document_artifacts AS artifact
          JOIN openclaw_account.tenants AS tenant
            ON tenant.id = artifact.tenant_id
         WHERE (artifact.workspace_mode, artifact.body_authority)
                   NOT IN (('personal_web', 'internal'), ('organization_lark', 'lark'))
            OR (artifact.workspace_mode, artifact.body_authority)
                   IS DISTINCT FROM (tenant.workspace_mode, tenant.body_authority)
    ) THEN
        RAISE EXCEPTION 'document artifact workspace authority requires data repair before 039'
            USING ERRCODE = '55000';
    END IF;

    IF EXISTS (
        SELECT 1
          FROM media_document.revision_bodies AS body
          JOIN media_product.document_artifacts AS artifact
            ON (artifact.tenant_id, artifact.public_id) =
               (body.tenant_id, body.public_artifact_id)
          JOIN openclaw_account.tenants AS tenant
            ON tenant.id = artifact.tenant_id
         WHERE (artifact.workspace_mode, artifact.body_authority,
                tenant.workspace_mode, tenant.body_authority)
                   IS DISTINCT FROM
               ('personal_web', 'internal', 'personal_web', 'internal')
    ) THEN
        RAISE EXCEPTION 'non-personal artifacts must not retain internal revision bodies before 039'
            USING ERRCODE = '55000';
    END IF;

    IF EXISTS (
        SELECT 1
          FROM media_document.lark_read_mirrors AS mirror
          JOIN media_product.document_artifacts AS artifact
            ON (artifact.tenant_id, artifact.public_id) =
               (mirror.tenant_id, mirror.public_artifact_id)
          JOIN openclaw_account.tenants AS tenant
            ON tenant.id = artifact.tenant_id
         WHERE (artifact.workspace_mode, artifact.body_authority,
                tenant.workspace_mode, tenant.body_authority)
                   IS DISTINCT FROM
               ('organization_lark', 'lark', 'organization_lark', 'lark')
    ) THEN
        RAISE EXCEPTION 'non-organization artifacts must not retain Lark read mirrors before 039'
            USING ERRCODE = '55000';
    END IF;
END;
$$;

ALTER TABLE media_product.document_artifacts
    DROP CONSTRAINT document_artifacts_check,
    DROP CONSTRAINT document_artifacts_check1,
    ADD CONSTRAINT document_artifacts_workspace_authority_pair CHECK (
        (workspace_mode = 'personal_web' AND body_authority = 'internal')
        OR
        (workspace_mode = 'organization_lark' AND body_authority = 'lark')
    );

ALTER TABLE openclaw_account.tenants
    ADD CONSTRAINT tenants_id_workspace_authority_key
    UNIQUE (id, workspace_mode, body_authority);

ALTER TABLE media_product.document_artifacts
    ADD CONSTRAINT document_artifacts_tenant_workspace_authority_fkey
    FOREIGN KEY (tenant_id, workspace_mode, body_authority)
    REFERENCES openclaw_account.tenants (id, workspace_mode, body_authority)
    ON DELETE RESTRICT;

CREATE OR REPLACE FUNCTION media_document.enforce_revision_body_authority()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    artifact_workspace TEXT;
    artifact_authority TEXT;
    tenant_workspace TEXT;
    tenant_authority TEXT;
BEGIN
    SELECT artifact.workspace_mode,
           artifact.body_authority,
           tenant.workspace_mode,
           tenant.body_authority
      INTO STRICT artifact_workspace,
                  artifact_authority,
                  tenant_workspace,
                  tenant_authority
      FROM media_product.document_artifacts AS artifact
      JOIN openclaw_account.tenants AS tenant
        ON tenant.id = artifact.tenant_id
     WHERE artifact.tenant_id = NEW.tenant_id
       AND artifact.public_id = NEW.public_artifact_id;

    IF (artifact_workspace, artifact_authority, tenant_workspace, tenant_authority)
           IS DISTINCT FROM
       ('personal_web', 'internal', 'personal_web', 'internal') THEN
        RAISE EXCEPTION 'only personal Web artifacts may store revision bodies'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION media_document.enforce_lark_read_mirror_authority()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    artifact_workspace TEXT;
    artifact_authority TEXT;
    tenant_workspace TEXT;
    tenant_authority TEXT;
BEGIN
    SELECT artifact.workspace_mode,
           artifact.body_authority,
           tenant.workspace_mode,
           tenant.body_authority
      INTO STRICT artifact_workspace,
                  artifact_authority,
                  tenant_workspace,
                  tenant_authority
      FROM media_product.document_artifacts AS artifact
      JOIN openclaw_account.tenants AS tenant
        ON tenant.id = artifact.tenant_id
     WHERE artifact.tenant_id = NEW.tenant_id
       AND artifact.public_id = NEW.public_artifact_id;

    IF (artifact_workspace, artifact_authority, tenant_workspace, tenant_authority)
           IS DISTINCT FROM
       ('organization_lark', 'lark', 'organization_lark', 'lark') THEN
        RAISE EXCEPTION 'only organization Lark artifacts may store Lark read mirrors'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
