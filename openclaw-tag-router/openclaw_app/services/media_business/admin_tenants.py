"""Canonical PostgreSQL read model for the B12 administrator tenant page."""

from __future__ import annotations

import hashlib
import json
import re
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Mapping, Protocol
from urllib.parse import unquote_to_bytes
from uuid import UUID, uuid4

from ...account.admin_audit import write_admin_audit
from . import foundation, sql_pagination

SCHEMA_VERSION = "media_web_business_pages_v2"
DEFAULT_PAGE_SIZE = 30
MAX_PAGE_SIZE = 100
MAX_SEARCH_LENGTH = 200
MAX_REASON_LENGTH = 500
PUBLIC_ID_PATTERN = foundation.PUBLIC_ID_PATTERN
CURSOR_PATTERN = re.compile(r"^[A-Za-z0-9_-]{8,512}$")
_CURSOR_RESOURCE_DIRECTORY = "tenant-directory"
_CURSOR_RESOURCE_RUNS = "tenant-runs"
_UTC = timezone.utc


class AdminTenantsError(RuntimeError):
    status = 500
    field: str | None = None

    def __init__(self, code: str, message: str, *, status: int, field: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.field = field


class AdminTenantsUnauthorized(AdminTenantsError):
    def __init__(self, message: str = "administrator authentication is required") -> None:
        super().__init__(foundation.AUTHENTICATION_REQUIRED, message, status=401)


class AdminTenantsForbidden(AdminTenantsError):
    def __init__(self, message: str = "administrator permission is required") -> None:
        super().__init__(foundation.FORBIDDEN, message, status=403)


class AdminTenantsInvalidRequest(AdminTenantsError):
    def __init__(self, message: str, *, field: str | None = None) -> None:
        super().__init__(foundation.INVALID_REQUEST, message, status=400, field=field)


class AdminTenantsNotFound(AdminTenantsError):
    def __init__(self, message: str = "resource was not found") -> None:
        super().__init__(foundation.RESOURCE_NOT_FOUND, message, status=404)


class AdminTenantsInternalError(AdminTenantsError):
    def __init__(self, message: str = "administrator tenant data is unavailable") -> None:
        super().__init__(foundation.INTERNAL_ERROR, message, status=500)


@dataclass(frozen=True)
class AdminTenantContext:
    actor_user_id: UUID | str
    actor_session_id: UUID | str
    role: str = "admin"
    maintainer: bool = True


class Connection(Protocol):
    def execute(self, query: str, params: tuple[Any, ...] = ()) -> Any: ...


ConnectionFactory = Callable[[], AbstractContextManager[Connection]]


@dataclass(frozen=True)
class _TenantCursor:
    updated_at: datetime
    tenant_id: UUID


@dataclass(frozen=True)
class _RunCursor:
    updated_at: datetime
    public_run_id: str
    tenant_id: UUID


def _as_utc(value: Any, *, allow_none: bool = False) -> datetime | None:
    if value is None and allow_none:
        return None
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, str):
        try:
            result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise AdminTenantsInternalError("database timestamp is invalid") from exc
    else:
        raise AdminTenantsInternalError("database timestamp is invalid")
    if result.tzinfo is None:
        result = result.replace(tzinfo=_UTC)
    return result.astimezone(_UTC)


def _timestamp(value: Any, *, allow_none: bool = False) -> str | None:
    result = _as_utc(value, allow_none=allow_none)
    return None if result is None else result.isoformat().replace("+00:00", "Z")


def _uuid(value: Any, *, not_found: bool = False) -> UUID:
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except (AttributeError, ValueError, TypeError) as exc:
        if not_found:
            raise AdminTenantsNotFound() from exc
        raise AdminTenantsInternalError("database identifier is invalid") from exc


def _nonnegative_int(value: Any, message: str) -> int:
    if isinstance(value, bool):
        raise AdminTenantsInternalError(message)
    try:
        result = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise AdminTenantsInternalError(message) from exc
    if result < 0:
        raise AdminTenantsInternalError(message)
    return result


def _revision(*parts: Any) -> int:
    encoded: list[str] = []
    for part in parts:
        if isinstance(part, datetime):
            encoded.append(_timestamp(part) or "")
        elif isinstance(part, UUID):
            encoded.append(str(part))
        else:
            encoded.append(json.dumps(part, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    digest = hashlib.sha256("|".join(encoded).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") & ((1 << 63) - 1)


def _json_object(value: Any) -> dict[str, Any]:
    return foundation.json_object(value, "run canonical data", error=AdminTenantsInternalError)


def _text(value: Any) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise AdminTenantsInternalError("run canonical field is invalid")
    return value


def _first_text(data: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        if key in data and data[key] is not None:
            return _text(data[key])
    return ""


def _usage_text(value: Any) -> str:
    if value is None:
        return "0"
    try:
        amount = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise AdminTenantsInternalError("tenant usage aggregate is invalid") from exc
    if not amount.is_finite():
        raise AdminTenantsInternalError("tenant usage aggregate is invalid")
    text = format(amount, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _page_size(value: Any) -> int:
    return foundation.page_size(value, error=lambda m: AdminTenantsInvalidRequest(m, field="pageSize"))


def _search(value: Any) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise AdminTenantsInvalidRequest("search must be a string", field="search")
    result = value.strip()
    if len(result) > MAX_SEARCH_LENGTH:
        raise AdminTenantsInvalidRequest("search is too long", field="search")
    return result


def _reason(value: Any) -> str:
    if not isinstance(value, str):
        raise AdminTenantsInvalidRequest("audit reason is required", field="auditReason")
    try:
        result = unquote_to_bytes(value).decode("utf-8").strip()
    except UnicodeDecodeError as exc:
        raise AdminTenantsInvalidRequest("audit reason encoding is invalid", field="auditReason") from exc
    if not result:
        raise AdminTenantsInvalidRequest("audit reason is required", field="auditReason")
    if len(result) < 8:
        raise AdminTenantsInvalidRequest("audit reason must contain at least 8 characters", field="auditReason")
    if len(result) > MAX_REASON_LENGTH:
        raise AdminTenantsInvalidRequest("audit reason is too long", field="auditReason")
    return result


_TENANT_CTE = """
WITH tenant_rows AS (
    SELECT
        tenant.id AS tenant_id,
        tenant.primary_user_id,
        tenant.status,
        primary_user.username AS primary_username,
        (SELECT COUNT(*)::bigint
           FROM openclaw_account.users AS tenant_user
          WHERE tenant_user.id = tenant.primary_user_id) AS user_count,
        (SELECT COUNT(*)::bigint
           FROM media_product.creation_runs AS run
          WHERE run.tenant_id = tenant.id) AS run_count,
        (SELECT COUNT(*)::bigint
           FROM media_product.assets AS asset
          WHERE asset.tenant_id = tenant.id) AS asset_count,
        (SELECT COUNT(DISTINCT revision.public_artifact_id)::bigint
           FROM media_product.document_revisions AS revision
          WHERE revision.tenant_id = tenant.id
            AND revision.state = 'archived') AS archive_count,
        (SELECT COALESCE(SUM(operation.actual_charge) FILTER (WHERE operation.status = 'succeeded'), 0)::numeric
           FROM openclaw_account.model_operations AS operation
          WHERE operation.tenant_id = tenant.id) AS usage_charge,
        GREATEST(
            tenant.updated_at,
            primary_user.updated_at,
            COALESCE((SELECT MAX(run.updated_at) FROM media_product.creation_runs AS run WHERE run.tenant_id = tenant.id), tenant.updated_at),
            COALESCE((SELECT MAX(asset.updated_at) FROM media_product.assets AS asset WHERE asset.tenant_id = tenant.id), tenant.updated_at),
            COALESCE((SELECT MAX(revision.updated_at) FROM media_product.document_revisions AS revision WHERE revision.tenant_id = tenant.id), tenant.updated_at),
            COALESCE((SELECT MAX(operation.updated_at) FROM openclaw_account.model_operations AS operation WHERE operation.tenant_id = tenant.id), tenant.updated_at)
        ) AS last_active_at
    FROM openclaw_account.tenants AS tenant
    JOIN openclaw_account.users AS primary_user ON primary_user.id = tenant.primary_user_id
)
"""

_TENANT_LIST_QUERY = _TENANT_CTE + f"""
SELECT tenant_id, primary_user_id, status, primary_username, user_count,
       run_count, asset_count, archive_count, usage_charge, last_active_at
  FROM tenant_rows
 WHERE (%s = '' OR primary_username ILIKE %s OR status ILIKE %s)
{sql_pagination.keyset_window(
    "", "last_active_at", "tenant_id",
    and_indent="   ", inner_indent="        ", tail_indent=" ", closing_indent="",
)}"""

_TENANT_DETAIL_QUERY = _TENANT_CTE + """
SELECT tenant_id, primary_user_id, status, primary_username, user_count,
       run_count, asset_count, archive_count, usage_charge, last_active_at
  FROM tenant_rows
 WHERE tenant_id = %s
"""

_TENANT_EXISTS_QUERY = """
SELECT tenant.primary_user_id
  FROM openclaw_account.tenants AS tenant
 WHERE tenant.id = %s
"""

_RUN_LIST_QUERY = f"""
SELECT run.public_id, run.canonical_data, run.created_at, run.updated_at, run.revision
  FROM media_product.creation_runs AS run
 WHERE run.tenant_id = %s
{sql_pagination.keyset_window(
    "run.", "updated_at", "public_id",
    and_indent="   ", inner_indent="        ", tail_indent=" ", closing_indent="",
)}"""

class AdminTenantsService:
    """Expose B12's redacted tenant directory and audited tenant reads."""

    def __init__(
        self,
        database_or_factory: Any,
        *,
        public_id_secret: bytes,
        cursor_secret: bytes,
    ) -> None:
        if hasattr(database_or_factory, "connect"):
            self._connection_factory: ConnectionFactory = database_or_factory.connect
        elif callable(database_or_factory):
            self._connection_factory = database_or_factory
        else:
            raise TypeError("B12 requires an AccountDatabase or connection factory")
        self._public_id_secret = foundation.derive_namespace_secret(public_id_secret, "public-id-secret")
        self._cursor_secret = foundation.derive_namespace_secret(cursor_secret, "cursor-secret")

    @staticmethod
    def error_response(error: BaseException) -> dict[str, Any]:
        if isinstance(error, AdminTenantsError):
            return {"error": {"code": error.code, "message": error.message, "field": error.field}}
        return {"error": {"code": "internal_error", "message": "administrator tenant data is unavailable", "field": None}}

    def public_tenant_id(self, tenant_id: UUID | str) -> str:
        return foundation.encode_signed({"namespace": "b12-tenant", "tenantId": str(_uuid(tenant_id))}, self._public_id_secret)

    def decode_public_tenant_id(self, public_tenant_id: str) -> UUID:
        decoded = foundation.decode_signed(public_tenant_id, self._public_id_secret, error=AdminTenantsNotFound)
        if decoded.get("namespace") != "b12-tenant":
            raise AdminTenantsNotFound()
        return _uuid(decoded.get("tenantId"), not_found=True)

    def list_admin_tenants(
        self,
        context: AdminTenantContext | Any,
        *,
        cursor: str | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
        search: str | None = None,
    ) -> dict[str, Any]:
        checked = self._context(context)
        size = _page_size(page_size)
        normalized_search = _search(search)
        position = self._decode_tenant_cursor(cursor, normalized_search) if cursor else None
        position_time = _timestamp(position.updated_at) if position else None
        position_tenant = position.tenant_id if position else None
        pattern = f"%{normalized_search}%"
        params = (
            normalized_search,
            pattern,
            pattern,
            *sql_pagination.keyset_params(position_time, position_tenant, no_position_id=None),
            size + 1,
        )
        try:
            with self._connection_factory() as connection:
                self._ensure_admin_read(checked)
                rows = list(connection.execute(_TENANT_LIST_QUERY, params).fetchall())
        except AdminTenantsError:
            raise
        except Exception as exc:
            raise AdminTenantsInternalError() from exc
        visible = rows[:size]
        items = [self._tenant_summary(row) for row in visible]
        next_cursor = None
        if len(rows) > size:
            last = visible[-1]
            next_cursor = self._encode_tenant_cursor(
                normalized_search,
                _TenantCursor(updated_at=self._row_last_active(last), tenant_id=_uuid(last[0])),
            )
        return {
            "schemaVersion": SCHEMA_VERSION,
            "revision": _revision("tenant-directory", normalized_search, items),
            "items": items,
            "nextCursor": next_cursor,
        }

    def get_admin_tenant(
        self,
        context: AdminTenantContext | Any,
        public_tenant_id: str,
        *,
        audit_reason: str | None = None,
    ) -> dict[str, Any]:
        checked = self._context(context)
        target_id = self.decode_public_tenant_id(public_tenant_id)
        reason = _reason(audit_reason)
        try:
            with self._connection_factory() as connection:
                row = connection.execute(_TENANT_DETAIL_QUERY, (target_id,)).fetchone()
                if row is None:
                    raise AdminTenantsNotFound()
                summary = self._tenant_summary(row)
                self._write_read_audit(
                    connection,
                    checked,
                    action="admin_tenant_detail_read",
                    target_tenant_id=target_id,
                    target_user_id=_uuid(row[1]),
                    reason=reason,
                    metadata={
                        "targetTenantId": str(target_id),
                        "targetPublicTenantId": public_tenant_id,
                        "targetType": "tenant",
                        "readModel": "admin_tenant_summary",
                        "pageSize": 1,
                    },
                )
        except AdminTenantsError:
            raise
        except Exception as exc:
            raise AdminTenantsInternalError() from exc
        return {"schemaVersion": SCHEMA_VERSION, "revision": _revision("tenant-detail", summary), "tenant": summary}

    def list_admin_tenant_runs(
        self,
        context: AdminTenantContext | Any,
        public_tenant_id: str,
        *,
        audit_reason: str | None = None,
        cursor: str | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> dict[str, Any]:
        checked = self._context(context)
        target_id = self.decode_public_tenant_id(public_tenant_id)
        reason = _reason(audit_reason)
        size = _page_size(page_size)
        position = self._decode_run_cursor(cursor, target_id) if cursor else None
        position_time = _timestamp(position.updated_at) if position else None
        position_run = position.public_run_id if position else None
        params = (
            target_id,
            *sql_pagination.keyset_params(position_time, position_run, no_position_id=None),
            size + 1,
        )
        try:
            with self._connection_factory() as connection:
                target_row = connection.execute(_TENANT_EXISTS_QUERY, (target_id,)).fetchone()
                if target_row is None:
                    raise AdminTenantsNotFound()
                rows = list(connection.execute(_RUN_LIST_QUERY, params).fetchall())
                visible = rows[:size]
                items = [self._run_summary(row) for row in visible]
                next_cursor = None
                if len(rows) > size:
                    last = visible[-1]
                    next_cursor = self._encode_run_cursor(
                        target_id,
                        _RunCursor(
                            updated_at=_as_utc(last[3]) or datetime.min.replace(tzinfo=_UTC),
                            public_run_id=self._public_run(last[0]),
                            tenant_id=target_id,
                        ),
                    )
                self._write_read_audit(
                    connection,
                    checked,
                    action="admin_tenant_runs_read",
                    target_tenant_id=target_id,
                    target_user_id=_uuid(target_row[0]),
                    reason=reason,
                    metadata={
                        "targetTenantId": str(target_id),
                        "targetPublicTenantId": public_tenant_id,
                        "targetType": "tenant",
                        "readModel": "creation_runs",
                        "pageSize": size,
                        "cursorPresent": cursor is not None,
                        "returnedCount": len(visible),
                    },
                )
        except AdminTenantsError:
            raise
        except Exception as exc:
            raise AdminTenantsInternalError() from exc
        return {"schemaVersion": SCHEMA_VERSION, "revision": _revision("tenant-runs", str(target_id), items), "items": items, "nextCursor": next_cursor}

    def _context(self, value: AdminTenantContext | Any) -> AdminTenantContext:
        if value is None:
            raise AdminTenantsUnauthorized()
        role = getattr(value, "role", None)
        if role != "admin" or getattr(value, "maintainer", True) is False:
            raise AdminTenantsForbidden()
        actor_user_id = getattr(value, "actor_user_id", None)
        actor_session_id = getattr(value, "actor_session_id", None)
        if actor_user_id is None or actor_session_id is None:
            raise AdminTenantsUnauthorized()
        try:
            _uuid(actor_user_id)
            _uuid(actor_session_id)
        except AdminTenantsError as exc:
            raise AdminTenantsUnauthorized() from exc
        return AdminTenantContext(actor_user_id=actor_user_id, actor_session_id=actor_session_id, role="admin", maintainer=True)

    @staticmethod
    def _ensure_admin_read(context: AdminTenantContext) -> None:
        if context.role != "admin" or context.maintainer is False:
            raise AdminTenantsForbidden()

    def _tenant_summary(self, row: Any) -> dict[str, Any]:
        if not isinstance(row, (tuple, list)) or len(row) < 10:
            raise AdminTenantsInternalError("tenant aggregate is incomplete")
        tenant_id = _uuid(row[0])
        status = row[2]
        if not isinstance(status, str) or not status:
            raise AdminTenantsInternalError("tenant status is invalid")
        return {
            "publicTenantId": self.public_tenant_id(tenant_id),
            "status": status,
            "userCount": _nonnegative_int(row[4], "tenant user aggregate is invalid"),
            "runCount": _nonnegative_int(row[5], "tenant run aggregate is invalid"),
            "assetCount": _nonnegative_int(row[6], "tenant asset aggregate is invalid"),
            "archiveCount": _nonnegative_int(row[7], "tenant archive aggregate is invalid"),
            "usageCharge": _usage_text(row[8]),
            "lastActiveAt": _timestamp(row[9], allow_none=True),
        }

    @staticmethod
    def _row_last_active(row: Any) -> datetime:
        if not isinstance(row, (tuple, list)) or len(row) < 10:
            raise AdminTenantsInternalError("tenant aggregate is incomplete")
        value = _as_utc(row[9])
        if value is None:
            raise AdminTenantsInternalError("tenant activity timestamp is missing")
        return value

    @staticmethod
    def _public_run(value: Any) -> str:
        if not isinstance(value, str) or PUBLIC_ID_PATTERN.fullmatch(value) is None:
            raise AdminTenantsInternalError("run public id is invalid")
        return value

    def _run_summary(self, row: Any) -> dict[str, Any]:
        if not isinstance(row, (tuple, list)) or len(row) < 5:
            raise AdminTenantsInternalError("run projection is incomplete")
        public_run_id = self._public_run(row[0])
        data = _json_object(row[1])
        available = data.get("availableSections")
        if isinstance(available, list):
            sections = [item for item in available if item in {"sources", "decisions", "outputs"}]
        else:
            sections = []
            section_keys = {
                "sources": ("sources", "sourceItems", "sourceKinds", "sourceRefs"),
                "decisions": ("decisions", "decisionItems", "decisionRefs"),
                "outputs": ("outputs", "outputVariants", "artifactSummaries", "outputRefs"),
            }
            for section, keys in section_keys.items():
                if any(key in data and data[key] not in (None, "", [], {}) for key in keys):
                    sections.append(section)
        return {
            "publicRunId": public_run_id,
            "title": _first_text(data, "title", "name"),
            "entrypoint": _first_text(data, "entrypoint", "capabilityId", "capability"),
            "status": _first_text(data, "status", "state") or "unknown",
            "availableSections": sections,
            "publicProjectId": _first_text(data, "publicProjectId", "projectId", "public_project_id") or None,
            "createdAt": _timestamp(row[2]),
            "updatedAt": _timestamp(row[3]),
            "revision": _nonnegative_int(row[4], "run revision is invalid"),
        }

    def _encode_tenant_cursor(self, search: str, position: _TenantCursor) -> str:
        return foundation.encode_signed(
            {"resource": _CURSOR_RESOURCE_DIRECTORY, "search": search, "updatedAt": _timestamp(position.updated_at), "tenantId": str(position.tenant_id)},
            self._cursor_secret,
        )

    def _decode_tenant_cursor(self, value: str, search: str) -> _TenantCursor:
        try:
            decoded = foundation.decode_signed(value, self._cursor_secret, error=AdminTenantsNotFound, pattern=CURSOR_PATTERN)
        except AdminTenantsNotFound as exc:
            raise AdminTenantsInvalidRequest("cursor is invalid", field="cursor") from exc
        if decoded.get("resource") != _CURSOR_RESOURCE_DIRECTORY or decoded.get("search") != search:
            raise AdminTenantsInvalidRequest("cursor is invalid", field="cursor")
        try:
            updated_at = _as_utc(decoded["updatedAt"])
            tenant_id = _uuid(decoded["tenantId"])
        except (KeyError, AdminTenantsError) as exc:
            raise AdminTenantsInvalidRequest("cursor is invalid", field="cursor") from exc
        if updated_at is None:
            raise AdminTenantsInvalidRequest("cursor is invalid", field="cursor")
        return _TenantCursor(updated_at=updated_at, tenant_id=tenant_id)

    def _encode_run_cursor(self, target_id: UUID, position: _RunCursor) -> str:
        return foundation.encode_signed(
            {"resource": _CURSOR_RESOURCE_RUNS, "tenantId": str(target_id), "updatedAt": _timestamp(position.updated_at), "publicRunId": position.public_run_id},
            self._cursor_secret,
        )

    def _decode_run_cursor(self, value: str, target_id: UUID) -> _RunCursor:
        try:
            decoded = foundation.decode_signed(value, self._cursor_secret, error=AdminTenantsNotFound, pattern=CURSOR_PATTERN)
        except AdminTenantsNotFound as exc:
            raise AdminTenantsInvalidRequest("cursor is invalid", field="cursor") from exc
        if decoded.get("resource") != _CURSOR_RESOURCE_RUNS or decoded.get("tenantId") != str(target_id):
            raise AdminTenantsInvalidRequest("cursor is invalid", field="cursor")
        try:
            updated_at = _as_utc(decoded["updatedAt"])
            public_run_id = decoded["publicRunId"]
        except (KeyError, AdminTenantsError) as exc:
            raise AdminTenantsInvalidRequest("cursor is invalid", field="cursor") from exc
        if updated_at is None or not isinstance(public_run_id, str) or PUBLIC_ID_PATTERN.fullmatch(public_run_id) is None:
            raise AdminTenantsInvalidRequest("cursor is invalid", field="cursor")
        return _RunCursor(updated_at=updated_at, public_run_id=public_run_id, tenant_id=target_id)

    def _write_read_audit(
        self,
        connection: Connection,
        context: AdminTenantContext,
        *,
        action: str,
        target_tenant_id: UUID,
        target_user_id: UUID,
        reason: str,
        metadata: Mapping[str, Any],
    ) -> None:
        if not target_tenant_id:
            raise AdminTenantsInternalError("audit target is missing")
        # NOTE: target_tenant_id is validated above but, as in the code this
        # replaces, is never bound to the admin_audit.target_tenant_id column
        # -- only target_user_id is. Callers already fold targetTenantId into
        # `metadata` themselves. Left as-is: a real gap, but a correctness
        # question independent of this consolidation (see HIGH-26 audit).
        write_admin_audit(
            connection,
            audit_id=uuid4(),
            actor_user_id=_uuid(context.actor_user_id),
            actor_session_id=_uuid(context.actor_session_id),
            action=action,
            target_user_id=target_user_id,
            reason=reason,
            metadata=dict(metadata),
        )
