from __future__ import annotations

import os
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "openclaw_app/migrations/canonical/039_media_document_workspace_authority.sql"
DATABASE_URL = os.environ.get("A2B_TEST_DATABASE_URL")


def test_migration_is_one_way_and_closes_both_storage_families() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

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
        assert mirror_total == 27
        assert invalid_mirror_total == 0

        organization_revision = connection.execute(
            """
            SELECT artifact.tenant_id, artifact.public_id, revision.revision
              FROM media_product.document_artifacts AS artifact
              JOIN media_product.document_revisions AS revision
                ON (revision.tenant_id, revision.public_artifact_id) =
                   (artifact.tenant_id, artifact.public_id)
             WHERE artifact.workspace_mode = 'organization_lark'
               AND artifact.body_authority = 'lark'
             ORDER BY artifact.public_id, revision.revision
             LIMIT 1
            """
        ).fetchone()
        personal_revision = connection.execute(
            """
            SELECT artifact.tenant_id, artifact.public_id, revision.revision
              FROM media_product.document_artifacts AS artifact
              JOIN media_product.document_revisions AS revision
                ON (revision.tenant_id, revision.public_artifact_id) =
                   (artifact.tenant_id, artifact.public_id)
             WHERE artifact.workspace_mode = 'personal_web'
               AND artifact.body_authority = 'internal'
             ORDER BY artifact.public_id, revision.revision
             LIMIT 1
            """
        ).fetchone()
        assert organization_revision is not None
        assert personal_revision is not None

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
