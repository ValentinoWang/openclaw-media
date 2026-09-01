from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "openclaw_app/migrations/canonical/039_media_document_workspace_authority.sql"
DATABASE_URL = os.environ.get("A2B_TEST_DATABASE_URL")


def test_migration_is_one_way_and_closes_both_storage_families() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    manifest = json.loads(
        (ROOT / "openclaw_app/migrations/postgres_manifest.json").read_text(encoding="utf-8")
    )
    entry = next(
        item
        for item in manifest["migrations"]
        if item["id"] == "cm1-039-media-document-workspace-authority"
    )

    for fragment in (
        "document_artifacts_workspace_authority_pair",
        "document_artifacts_tenant_workspace_authority_fkey",
        "tenants_id_workspace_authority_key",
        "only personal Web artifacts may store revision bodies",
        "only organization Lark artifacts may store Lark read mirrors",
        "DROP CONSTRAINT document_artifacts_check1",
    ):
        assert fragment in source

    upper_source = source.upper()
    assert "BEGIN;" not in upper_source
    assert "COMMIT;" not in upper_source
    assert entry["sourceSha256"] == hashlib.sha256(MIGRATION.read_bytes()).hexdigest()
    assert entry["ledgerChecksum"] == "75406fe41b882704a687c22097630483d9e5117c25788b38af0d11622fdb4467"
    assert "CREATE VIEW" not in upper_source
    assert "INSERT INTO MEDIA_DOCUMENT.REVISION_BODIES" not in upper_source
    assert "INSERT INTO MEDIA_DOCUMENT.LARK_READ_MIRRORS" not in upper_source
    assert "FALLBACK" not in upper_source


@pytest.mark.skipif(not DATABASE_URL, reason="A2B_TEST_DATABASE_URL is required")
def test_migrated_clone_rejects_cross_workspace_storage() -> None:
    import psycopg

    connection = psycopg.connect(DATABASE_URL, autocommit=False)
    try:
        constraints = {
            row[0]
            for row in connection.execute(
                """
                SELECT conname
                  FROM pg_constraint
                 WHERE conname IN (
                    'document_artifacts_workspace_authority_pair',
                    'document_artifacts_tenant_workspace_authority_fkey',
                    'tenants_id_workspace_authority_key'
                 )
                """
            )
        }
        assert constraints == {
            "document_artifacts_workspace_authority_pair",
            "document_artifacts_tenant_workspace_authority_fkey",
            "tenants_id_workspace_authority_key",
        }

        personal_user = "a2000000-0000-4000-8000-000000000001"
        organization_user = "a2000000-0000-4000-8000-000000000002"
        personal_tenant = "a2000000-0000-4000-8000-000000000011"
        organization_tenant = "a2000000-0000-4000-8000-000000000012"
        for user_id, username in (
            (personal_user, "a2b-personal"),
            (organization_user, "a2b-organization"),
        ):
            connection.execute(
                """
                INSERT INTO openclaw_account.users (
                    id, username, password_hash, role, display_name
                ) VALUES (%s, %s, %s, 'user', %s)
                """,
                (user_id, username, "x" * 32, username),
            )
        connection.execute(
            """
            INSERT INTO openclaw_account.tenants (
                id, primary_user_id, tenant_type, workspace_mode,
                body_authority, organization_name
            ) VALUES
                (%s, %s, 'personal', 'personal_web', 'internal', NULL),
                (%s, %s, 'organization', 'organization_lark', 'lark', 'A2B Test')
            """,
            (personal_tenant, personal_user, organization_tenant, organization_user),
        )
        connection.execute(
            """
            INSERT INTO openclaw_account.tenant_members (
                tenant_id, user_id, role, status
            ) VALUES
                (%s, %s, 'owner', 'active'),
                (%s, %s, 'owner', 'active')
            """,
            (personal_tenant, personal_user, organization_tenant, organization_user),
        )
        for tenant_id, project_id, artifact_id, workspace_mode, authority in (
            (personal_tenant, "project_a2b_personal", "artifact_a2b_personal", "personal_web", "internal"),
            (organization_tenant, "project_a2b_org", "artifact_a2b_org", "organization_lark", "lark"),
        ):
            connection.execute(
                """
                INSERT INTO media_product.content_projects (
                    tenant_id, public_id, title, stage
                ) VALUES (%s, %s, 'A2B authority test', 'test')
                """,
                (tenant_id, project_id),
            )
            connection.execute(
                """
                INSERT INTO media_product.document_artifacts (
                    tenant_id, public_id, public_project_id, artifact_kind,
                    workspace_mode, body_authority
                ) VALUES (%s, %s, %s, 'creation_document', %s, %s)
                """,
                (tenant_id, artifact_id, project_id, workspace_mode, authority),
            )
            connection.execute(
                """
                INSERT INTO media_product.document_revisions (
                    tenant_id, public_artifact_id, revision, state,
                    body_checksum, actor_public_id, generation_source
                ) VALUES (%s, %s, 1, 'ready', %s, 'a2b-test', 'migration-test')
                """,
                (tenant_id, artifact_id, "c" * 64),
            )
        body = '{"schemaVersion":"media.document.body.v1","blocks":[]}'
        connection.execute(
            """
            INSERT INTO media_document.revision_bodies (
                tenant_id, public_artifact_id, revision, schema_version,
                body_json, body_checksum
            ) VALUES (%s, 'artifact_a2b_personal', 1,
                      'media.document.body.v1', %s::jsonb, %s)
            """,
            (personal_tenant, body, "c" * 64),
        )
        connection.execute(
            """
            INSERT INTO media_document.lark_read_mirrors (
                tenant_id, public_artifact_id, revision, body_json,
                body_checksum, source_url
            ) VALUES (%s, 'artifact_a2b_org', 1, %s::jsonb, %s,
                      'https://example.feishu.cn/wiki/a2btest01')
            """,
            (organization_tenant, body, "c" * 64),
        )

        invalid_body_total = connection.execute(
            """
            SELECT count(*) FILTER (WHERE
                       (artifact.workspace_mode, artifact.body_authority,
                        tenant.workspace_mode, tenant.body_authority)
                           IS DISTINCT FROM
                       ('personal_web', 'internal', 'personal_web', 'internal'))
              FROM media_document.revision_bodies AS body
              JOIN media_product.document_artifacts AS artifact
                ON (artifact.tenant_id, artifact.public_id) =
                   (body.tenant_id, body.public_artifact_id)
              JOIN openclaw_account.tenants AS tenant
                ON tenant.id = artifact.tenant_id
            """
        ).fetchone()[0]
        mirror_total, invalid_mirror_total = connection.execute(
            """
            SELECT count(*),
                   count(*) FILTER (WHERE
                       (artifact.workspace_mode, artifact.body_authority,
                        tenant.workspace_mode, tenant.body_authority)
                           IS DISTINCT FROM
                       ('organization_lark', 'lark', 'organization_lark', 'lark'))
              FROM media_document.lark_read_mirrors AS mirror
              JOIN media_product.document_artifacts AS artifact
                ON (artifact.tenant_id, artifact.public_id) =
                   (mirror.tenant_id, mirror.public_artifact_id)
              JOIN openclaw_account.tenants AS tenant
                ON tenant.id = artifact.tenant_id
            """
        ).fetchone()
        assert invalid_body_total == 0
        assert mirror_total >= 1
        assert invalid_mirror_total == 0

        organization_revision = (organization_tenant, "artifact_a2b_org", 1)
        personal_revision = (personal_tenant, "artifact_a2b_personal", 1)

        connection.execute("SAVEPOINT reject_organization_body")
        with pytest.raises(psycopg.errors.CheckViolation, match="personal Web artifacts"):
            connection.execute(
                """
                INSERT INTO media_document.revision_bodies (
                    tenant_id, public_artifact_id, revision, schema_version,
                    body_json, body_checksum
                ) VALUES (%s, %s, %s, 'media.document.body.v1', %s::jsonb, %s)
                """,
                (
                    *organization_revision,
                    '{"schemaVersion":"media.document.body.v1","blocks":[]}',
                    "a" * 64,
                ),
            )
        connection.execute("ROLLBACK TO SAVEPOINT reject_organization_body")

        connection.execute("SAVEPOINT reject_personal_mirror")
        with pytest.raises(psycopg.errors.CheckViolation, match="organization Lark artifacts"):
            connection.execute(
                """
                INSERT INTO media_document.lark_read_mirrors (
                    tenant_id, public_artifact_id, revision, body_json,
                    body_checksum, source_url
                ) VALUES (%s, %s, %s, %s::jsonb, %s, %s)
                """,
                (
                    *personal_revision,
                    '{"schemaVersion":"media.document.body.v1","blocks":[]}',
                    "b" * 64,
                    "https://example.invalid/a2b",
                ),
            )
        connection.execute("ROLLBACK TO SAVEPOINT reject_personal_mirror")

        organization_tenant_id, organization_artifact_id, _ = organization_revision
        connection.execute("SAVEPOINT allow_lark_publishing_package")
        connection.execute(
            """
            UPDATE media_product.document_artifacts
               SET artifact_kind = 'publishing_package'
             WHERE tenant_id = %s AND public_id = %s
            """,
            (organization_tenant_id, organization_artifact_id),
        )
        assert connection.execute(
            """
            SELECT artifact_kind
              FROM media_product.document_artifacts
             WHERE tenant_id = %s AND public_id = %s
            """,
            (organization_tenant_id, organization_artifact_id),
        ).fetchone() == ("publishing_package",)
        connection.execute("ROLLBACK TO SAVEPOINT allow_lark_publishing_package")
    finally:
        connection.rollback()
        connection.close()
