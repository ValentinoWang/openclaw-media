from datetime import datetime, timezone

import pytest

from openclaw_app.services.media_business.documents import DocumentsService, DocumentInvalidRequest, DocumentNotFound
from openclaw_app.services.media_business.foundation import TenantContext


TENANT_A = "tenant-a"
TENANT_B = "tenant-b"
ARTIFACT = "artifact_sync_1"
NOW = datetime(2026, 8, 31, tzinfo=timezone.utc)


class _Cursor:
    def __init__(self, rows):
        self.rows = rows

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return list(self.rows)


class _Db:
    def __init__(self):
        self.rows = {
            TENANT_A: [
                (1, "sync_queued", ARTIFACT, 2, "read", "queued", None, None, None, None, None, NOW, NOW, None, None, {}),
                (2, "sync_failed", ARTIFACT, 2, "save", "failed", "v1", "v0", None, None, None, NOW, NOW, NOW, "remote_error", {"detail": "timeout"}),
            ]
        }

    def __call__(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, query, params=()):
        if "FROM media_product.document_artifacts" in query:
            return _Cursor([(ARTIFACT, "project_1", "creation_document", "organization_lark", "lark", 2, NOW)] if params[0] == TENANT_A and params[1] == ARTIFACT else [])
        if "FROM media_product.sync_batches" in query:
            return _Cursor(self.rows.get(params[0], []))
        raise AssertionError(query)


def test_sync_batches_project_camel_case_state_and_error_fields():
    service = DocumentsService(_Db(), cursor_secret=b"x" * 32)
    result = service.list_sync_batches(TenantContext(TENANT_A, "user"), ARTIFACT, page_size=10)
    assert [item["state"] for item in result["items"]] == ["queued", "failed"]
    assert result["items"][1]["remoteDocumentVersion"] == "v1"
    assert result["items"][1]["baseRemoteDocumentVersion"] == "v0"
    assert result["items"][1]["completedAt"] == NOW.isoformat()
    assert result["items"][1]["errorCode"] == "remote_error"
    assert result["items"][1]["errorDetail"] == {"detail": "timeout"}


def test_sync_batches_are_tenant_scoped_and_cursor_is_signed():
    service = DocumentsService(_Db(), cursor_secret=b"x" * 32)
    result = service.list_sync_batches(TenantContext(TENANT_A, "user"), ARTIFACT, page_size=1)
    assert result["nextCursor"] is not None
    with pytest.raises(DocumentInvalidRequest):
        service.list_sync_batches(TenantContext(TENANT_B, "user"), ARTIFACT, cursor=result["nextCursor"])
    with pytest.raises(DocumentInvalidRequest):
        service.list_sync_batches(TenantContext(TENANT_A, "user"), ARTIFACT, cursor=result["nextCursor"][:-1] + "A")


def test_sync_batches_hide_unknown_artifacts():
    with pytest.raises(DocumentNotFound):
        DocumentsService(_Db(), cursor_secret=b"x" * 32).list_sync_batches(TenantContext(TENANT_B, "user"), ARTIFACT)
