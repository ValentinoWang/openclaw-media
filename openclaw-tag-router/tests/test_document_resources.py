from __future__ import annotations

import hashlib
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import pytest

from openclaw_app.services.media_business.document_resources import (
    DocumentResourceNotFound,
    DocumentResourceService,
    DocumentResourceUnavailable,
)
from openclaw_app.services.media_business.foundation import TenantContext


class _Cursor:
    def __init__(self, row: Any) -> None:
        self._row = row

    def fetchone(self) -> Any:
        return self._row


class _Connection:
    def __init__(self, rows: dict[tuple[str, str], Any]) -> None:
        self.rows = rows
        self.params: tuple[Any, ...] | None = None

    def execute(self, query: str, params: tuple[Any, ...] = ()) -> _Cursor:
        assert "tenant_id = %s" in query
        self.params = params
        return _Cursor(self.rows.get((str(params[0]), str(params[1]))))


def _service(root: Path, rows: dict[tuple[str, str], Any]) -> tuple[DocumentResourceService, _Connection]:
    connection = _Connection(rows)

    @contextmanager
    def factory() -> Iterator[_Connection]:
        yield connection

    return DocumentResourceService(factory, resource_root=root), connection


def test_reads_only_the_session_tenant_resource_and_verifies_checksum(tmp_path: Path) -> None:
    body = b"real-png-bytes"
    checksum = hashlib.sha256(body).hexdigest()
    object_path = tmp_path / "tenant-a" / "image.png"
    object_path.parent.mkdir()
    object_path.write_bytes(body)
    service, connection = _service(
        tmp_path,
        {("tenant-a", "res_d2_image_0001"): ("image/png", "image.png", checksum, "tenant-a/image.png")},
    )

    result = service.get_resource(TenantContext("tenant-a", "user-a"), "res_d2_image_0001")

    assert result.body == body
    assert result.content_type == "image/png"
    assert result.content_checksum == checksum
    assert connection.params == ("tenant-a", "res_d2_image_0001")
    with pytest.raises(DocumentResourceNotFound):
        service.get_resource(TenantContext("tenant-b", "user-b"), "res_d2_image_0001")


def test_rejects_path_escape_checksum_drift_and_unsafe_content_type(tmp_path: Path) -> None:
    body = b"payload"
    checksum = hashlib.sha256(body).hexdigest()
    (tmp_path / "safe.pdf").write_bytes(body)
    cases = {
        "res_escape_0001": ("application/pdf", "safe.pdf", checksum, "../safe.pdf"),
        "res_drift_0001": ("application/pdf", "safe.pdf", "0" * 64, "safe.pdf"),
        "res_html_0001": ("text/html", "unsafe.html", checksum, "safe.pdf"),
    }
    service, _connection = _service(tmp_path, {("tenant-a", key): value for key, value in cases.items()})

    for resource_id in cases:
        with pytest.raises(DocumentResourceUnavailable):
            service.get_resource(TenantContext("tenant-a", "user-a"), resource_id)
