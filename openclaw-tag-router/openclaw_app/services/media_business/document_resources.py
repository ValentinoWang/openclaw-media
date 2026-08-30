"""Tenant-scoped binary resources referenced by canonical document blocks."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from . import foundation
from .foundation import MediaBusinessError, TenantContext


_CHECKSUM = re.compile(r"^[a-f0-9]{64}$")
_SAFE_CONTENT_TYPES = frozenset(
    {
        "application/octet-stream",
        "application/pdf",
        "image/gif",
        "image/jpeg",
        "image/png",
        "image/webp",
        "text/plain",
    }
)
MAX_RESOURCE_BYTES = 70 * 1024 * 1024


DocumentResourceError = MediaBusinessError


class DocumentResourceInvalid(DocumentResourceError):
    def __init__(self, message: str = "document resource request is invalid") -> None:
        super().__init__(foundation.INVALID_REQUEST, message, status=400)


class DocumentResourceForbidden(foundation.Forbidden):
    def __init__(self) -> None:
        super().__init__("document resource is not available for this session")


class DocumentResourceNotFound(foundation.NotFound):
    def __init__(self) -> None:
        super().__init__("document resource was not found")


class DocumentResourceUnavailable(foundation.InternalError):
    def __init__(self) -> None:
        super().__init__("document resource is unavailable")


class DatabaseConnection(Protocol):
    def execute(self, query: str, params: tuple[Any, ...] = ()) -> Any: ...


ConnectionFactory = Callable[[], AbstractContextManager[DatabaseConnection]]


@dataclass(frozen=True)
class DocumentResource:
    body: bytes
    content_type: str
    file_name: str
    content_checksum: str


class DocumentResourceService:
    _RESOURCE_QUERY = """
        SELECT content_type, file_name, content_checksum, object_ref
          FROM media_document.resources
         WHERE tenant_id = %s
           AND public_resource_id = %s
           AND status = 'active'
    """

    def __init__(self, connection_factory: ConnectionFactory, *, resource_root: str | Path) -> None:
        root = Path(resource_root).expanduser().resolve()
        if not root.is_absolute():
            raise ValueError("document resource root must be absolute")
        self._connection_factory = connection_factory
        self._resource_root = root

    def get_resource(self, context: TenantContext, public_resource_id: str) -> DocumentResource:
        tenant_id = self._tenant_id(context)
        resource_id = self._public_id(public_resource_id)
        try:
            with self._connection_factory() as connection:
                row = connection.execute(self._RESOURCE_QUERY, (tenant_id, resource_id)).fetchone()
        except DocumentResourceError:
            raise
        except Exception as exc:
            raise DocumentResourceUnavailable() from exc
        if row is None:
            raise DocumentResourceNotFound()
        if not isinstance(row, (tuple, list)) or len(row) != 4:
            raise DocumentResourceUnavailable()

        content_type, file_name, content_checksum, object_ref = row
        if content_type not in _SAFE_CONTENT_TYPES:
            raise DocumentResourceUnavailable()
        if not isinstance(file_name, str) or not file_name.strip() or any(
            value in file_name for value in ("/", "\\", "\r", "\n")
        ):
            raise DocumentResourceUnavailable()
        if not isinstance(content_checksum, str) or not _CHECKSUM.fullmatch(content_checksum):
            raise DocumentResourceUnavailable()
        path = self._object_path(object_ref)
        try:
            size = path.stat().st_size
            if not path.is_file() or size < 1 or size > MAX_RESOURCE_BYTES:
                raise DocumentResourceUnavailable()
            body = path.read_bytes()
        except DocumentResourceError:
            raise
        except OSError as exc:
            raise DocumentResourceUnavailable() from exc
        if not hashlib.sha256(body).hexdigest() == content_checksum:
            raise DocumentResourceUnavailable()
        return DocumentResource(body, content_type, file_name.strip(), content_checksum)

    def _object_path(self, object_ref: Any) -> Path:
        if not isinstance(object_ref, str) or not object_ref.strip():
            raise DocumentResourceUnavailable()
        relative = Path(object_ref.strip())
        if relative.is_absolute():
            raise DocumentResourceUnavailable()
        candidate = (self._resource_root / relative).resolve()
        try:
            candidate.relative_to(self._resource_root)
        except ValueError as exc:
            raise DocumentResourceUnavailable() from exc
        return candidate

    @staticmethod
    def _public_id(value: Any) -> str:
        return foundation.public_id(value, "public id", error_type=lambda _message: DocumentResourceInvalid())

    @staticmethod
    def _tenant_id(context: TenantContext | None) -> str:
        return foundation.tenant_id_of(context, error=DocumentResourceForbidden)
