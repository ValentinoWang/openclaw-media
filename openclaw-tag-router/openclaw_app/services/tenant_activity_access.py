"""Fail-closed access to tenant-private recent activity.

The migration owns the visibility decision. This module only reads the
canonical tenant-private view and never trusts a tenant id supplied by a
browser or a serialized activity record.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID


class TenantActivityAccessError(RuntimeError):
    """Raised when recent activity cannot be proven private to a tenant."""

    def __init__(self, code: str, message: str = "近期活动不可用。") -> None:
        self.code = code
        super().__init__(message)


class TenantActivityReader(Protocol):
    def list_recent_activity(self, tenant_id: UUID, *, limit: int) -> list[Mapping[str, Any]]: ...

    def recent_activity(self, tenant_id: UUID, activity_id: int) -> Mapping[str, Any] | None: ...


def _tenant_id(value: UUID | str) -> UUID:
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value).strip())
    except (ValueError, AttributeError, TypeError) as exc:
        raise TenantActivityAccessError("tenant_required") from exc


@dataclass(frozen=True)
class SqlTenantActivityReader:
    connection_factory: Any

    def list_recent_activity(self, tenant_id: UUID, *, limit: int) -> list[Mapping[str, Any]]:
        with self.connection_factory() as connection:
            cursor = connection.execute(
                """
                SELECT public_id, tenant_id, title, platform, updated_at, canonical_data
                FROM media_product.tenant_private_recent_activities
                WHERE tenant_id = %s
                ORDER BY updated_at DESC, public_id DESC
                LIMIT %s
                """,
                (tenant_id, limit),
            )
            rows = cursor.fetchall()
        return [_row_to_mapping(row) for row in rows]

    def recent_activity(self, tenant_id: UUID, activity_id: int) -> Mapping[str, Any] | None:
        with self.connection_factory() as connection:
            row = connection.execute(
                """
                SELECT public_id, tenant_id, title, platform, updated_at, canonical_data
                FROM media_product.tenant_private_recent_activities
                WHERE tenant_id = %s AND id = %s
                LIMIT 1
                """,
                (tenant_id, activity_id),
            ).fetchone()
        return None if row is None else _row_to_mapping(row)


def _row_to_mapping(row: Any) -> Mapping[str, Any]:
    if isinstance(row, Mapping):
        result = dict(row)
    else:
        values = tuple(row)
        if len(values) != 6:
            raise TenantActivityAccessError("activity_contract_invalid")
        result = dict(zip(("public_id", "tenant_id", "title", "platform", "updated_at", "canonical_data"), values))
    if result.get("tenant_id") is None or result.get("public_id") in (None, ""):
        raise TenantActivityAccessError("activity_owner_unproven")
    return result


class TenantActivityAccessService:
    def __init__(self, reader: TenantActivityReader, *, max_limit: int = 100) -> None:
        if max_limit < 1:
            raise ValueError("max_limit must be positive")
        self._reader = reader
        self._max_limit = max_limit

    def list(self, session_tenant_id: UUID | str, *, requested_tenant_id: UUID | str | None = None, limit: int = 20) -> list[Mapping[str, Any]]:
        tenant_id = _tenant_id(session_tenant_id)
        if requested_tenant_id is not None and _tenant_id(requested_tenant_id) != tenant_id:
            raise TenantActivityAccessError("cross_tenant_forbidden")
        if not 1 <= limit <= self._max_limit:
            raise TenantActivityAccessError("invalid_limit")
        rows = self._reader.list_recent_activity(tenant_id, limit=limit)
        for row in rows:
            if _tenant_id(row.get("tenant_id")) != tenant_id:
                raise TenantActivityAccessError("cross_tenant_forbidden")
        return rows

    def get(self, session_tenant_id: UUID | str, activity_id: int) -> Mapping[str, Any]:
        tenant_id = _tenant_id(session_tenant_id)
        if not isinstance(activity_id, int) or activity_id < 1:
            raise TenantActivityAccessError("activity_not_found")
        row = self._reader.recent_activity(tenant_id, activity_id)
        if row is None or _tenant_id(row.get("tenant_id")) != tenant_id:
            raise TenantActivityAccessError("activity_not_found")
        return row
