"""Tenant-scoped PostgreSQL projections for the B05 runs page."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from urllib.parse import urlsplit

from . import foundation
from .foundation import IF2_KEY, MediaBusinessError, TenantContext, idempotency_key, public_projection, require_context


SCHEMA_VERSION = "media_web_business_pages_v2"
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100
SOURCE_VERSION = "b05.runs.v1"
PUBLIC_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{8,160}$")
AVAILABLE_SECTIONS = frozenset({"sources", "decisions", "outputs"})
ARTIFACT_KINDS = frozenset(
    {
        "research_snapshot",
        "asset_digest",
        "decision_brief",
        "creation_document",
        "publishing_package",
        "review_report",
        "project_summary",
    }
)
BODY_AUTHORITIES = frozenset({"internal", "lark"})
SYNC_STATUSES = frozenset({"not_applicable", "pending", "synced", "conflict", "failed"})
DECISION_STATUSES = frozenset({"candidate", "recommended", "confirmed", "rejected"})
CANDIDATE_TYPES = frozenset({"activity", "material", "deconstruction", "pattern", "business", "creator"})
EVIDENCE_QUALITIES = frozenset({"verified", "partial", "unverified", "unavailable"})
REVISION_MODES = frozenset({"regenerate", "human_edit", "save_as"})
_CURSOR_VERSION = 1
_CURSOR_AAD = b"media-web-b05-runs-v1"


RunsError = MediaBusinessError


class RunsForbidden(RunsError):
    def __init__(self) -> None:
        super().__init__("forbidden", "run data is not available for this session", status=403)


class RunsNotFound(RunsError):
    def __init__(self) -> None:
        super().__init__("resource_not_found", "run resource was not found", status=404)


class RunsInvalidRequest(RunsError):
    def __init__(self, message: str, *, field: str | None = None) -> None:
        super().__init__("invalid_request", message, status=400, field=field)


class RunsConflict(RunsError):
    def __init__(self, message: str = "revision conflict") -> None:
        super().__init__("revision_conflict", message, status=409)


class RunsUnprocessable(RunsError):
    def __init__(self, message: str, *, field: str | None = None) -> None:
        super().__init__("unprocessable_entity", message, status=422, field=field)


class RunsInternalError(RunsError):
    def __init__(self, message: str = "run data is unavailable") -> None:
        super().__init__("internal_error", message, status=500)


class DatabaseConnection(Protocol):
    def execute(self, query: str, params: tuple[Any, ...] = ()) -> Any: ...


class ConnectionFactory(Protocol):
    def __call__(self) -> AbstractContextManager[DatabaseConnection]: ...


@dataclass(frozen=True)
class _CursorPosition:
    scope: str
    tenant_tag: str
    updated_at: str
    public_id: str


def _as_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _fetchone(cursor: Any) -> Any:
    if hasattr(cursor, "fetchone"):
        return cursor.fetchone()
    if isinstance(cursor, (list, tuple)):
        return cursor[0] if cursor else None
    return None


def _fetchall(cursor: Any) -> list[Any]:
    if hasattr(cursor, "fetchall"):
        return list(cursor.fetchall())
    if isinstance(cursor, (list, tuple)):
        return list(cursor)
    return []


def _row_values(row: Any, fields: tuple[str, ...], label: str) -> tuple[Any, ...]:
    if isinstance(row, Mapping):
        if any(field not in row for field in fields):
            raise RunsInternalError(f"{label} row is malformed")
        return tuple(row[field] for field in fields)
    if not isinstance(row, (tuple, list)) or len(row) < len(fields):
        raise RunsInternalError(f"{label} row is malformed")
    return tuple(row[: len(fields)])


def _json_object(value: Any, label: str) -> dict[str, Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise RunsInternalError(f"{label} is not valid JSON") from exc
    if not isinstance(value, Mapping):
        raise RunsInternalError(f"{label} is not an object")
    return dict(value)


def _json_list(value: Any, label: str) -> list[Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise RunsInternalError(f"{label} is not valid JSON") from exc
    if not isinstance(value, list):
        raise RunsInternalError(f"{label} is not an array")
    return value


def _stored_revision(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise RunsInternalError(f"{label} revision is invalid")
    return value


def _response_revision(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise RunsInternalError(f"{label} revision is invalid")
    return value


def _public_id(value: Any, label: str, error_type: type[RunsError] = RunsInternalError) -> str:
    if not isinstance(value, str) or PUBLIC_ID_PATTERN.fullmatch(value) is None:
        if error_type is RunsInvalidRequest:
            raise RunsInvalidRequest(f"{label} is invalid", field=label)
        raise RunsInternalError(f"{label} is invalid")
    return value


def _required_text(data: Mapping[str, Any], key: str, label: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RunsInternalError(f"{label} field {key} is missing")
    return value.strip()


def _nullable_public_id(data: Mapping[str, Any], key: str, label: str) -> str | None:
    value = data.get(key)
    if value is None:
        return None
    return _public_id(value, f"{label}.{key}")


def _nullable_text(data: Mapping[str, Any], key: str, label: str) -> str | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise RunsInternalError(f"{label} field {key} is invalid")
    return value.strip()


def _timestamp_value(value: Any, label: str, *, request: bool = False) -> datetime:
    def _error(lbl: str, reason: str) -> Exception:
        message = f"{lbl} must include a timezone" if reason == "naive" else f"{lbl} is invalid"
        if request:
            return RunsInvalidRequest(message, field=lbl)
        return RunsInternalError(message)

    return foundation.coerce_utc(value, label, error=_error, allow_naive=False)


def _timestamp_text(value: Any, label: str = "timestamp") -> str:
    return _timestamp_value(value, label).isoformat().replace("+00:00", "Z")


def _public_url(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RunsInternalError(f"{label} is invalid")
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
        raise RunsInternalError(f"{label} is not a public URL")
    return value


def _value(value: Any, label: str) -> str | int | float | bool | list[str | int | float | bool] | None:
    if value is None or type(value) in {str, int, float, bool}:
        return value
    if isinstance(value, list) and len(value) <= 100:
        if any(type(item) not in {str, int, float, bool} for item in value):
            raise RunsInternalError(f"{label} contains an unsupported array value")
        return list(value)
    raise RunsInternalError(f"{label} has an unsupported value")


def _normalized_public_map_key(key: str) -> str:
    key = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", key)
    key = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", key)
    return re.sub(r"[^A-Za-z0-9]+", "_", key).strip("_").lower()


def _assert_public_map_key(key: str, label: str) -> None:
    normalized = _normalized_public_map_key(key)
    if (
        normalized == "tenant"
        or normalized.startswith("tenant_")
        or normalized.startswith(("feishu_", "lark_"))
        or normalized in {
            "record_id",
            "table_id",
            "prompt",
            "raw_prompt",
            "raw_model_response",
            "api_key",
            "private_key",
            "signing_key",
            "secret",
            "credential",
        }
        or normalized.endswith(("_token", "_secret", "_credential", "_credential_value", "_path", "_prompt"))
    ):
        raise RunsInternalError(f"{label} contains a forbidden public field")


def _string_value_map(value: Any, label: str) -> dict[str, Any]:
    data = _json_object(value, label)
    result: dict[str, Any] = {}
    for key, item in data.items():
        if not isinstance(key, str) or not key:
            raise RunsInternalError(f"{label} has an invalid key")
        _assert_public_map_key(key, label)
        result[key] = _value(item, f"{label}.{key}")
    return result


def _string_value_maps(value: Any, label: str) -> list[dict[str, Any]]:
    return [_string_value_map(item, f"{label}[{index}]") for index, item in enumerate(_json_list(value, label))]


def _string_list(value: Any, label: str) -> list[str]:
    values = _json_list(value, label)
    if any(not isinstance(item, str) or not item.strip() for item in values):
        raise RunsInternalError(f"{label} contains an invalid string")
    return [item.strip() for item in values]


def _evidence_ref(value: Any, label: str) -> dict[str, Any]:
    data = _json_object(value, label)
    kind = data.get("kind")
    evidence_label = data.get("label")
    quality = data.get("qualityStatus")
    if not all(isinstance(item, str) and item.strip() for item in (kind, evidence_label)):
        raise RunsInternalError(f"{label} is incomplete")
    if not isinstance(quality, str) or quality not in EVIDENCE_QUALITIES:
        raise RunsInternalError(f"{label}.qualityStatus is invalid")
    public_url = data.get("publicUrl")
    captured_at = data.get("capturedAt")
    return {
        "kind": kind.strip(),
        "label": evidence_label.strip(),
        "publicUrl": None if public_url is None else _public_url(public_url, f"{label}.publicUrl"),
        "capturedAt": None if captured_at is None else _timestamp_text(captured_at, f"{label}.capturedAt"),
        "qualityStatus": quality,
    }


def _evidence_refs(value: Any, label: str) -> list[dict[str, Any]]:
    return [_evidence_ref(item, f"{label}[{index}]") for index, item in enumerate(_json_list(value, label))]


def _decision_summary(value: Any, label: str) -> dict[str, Any]:
    data = _json_object(value, label)
    public_id = _public_id(data.get("publicDecisionId"), f"{label}.publicDecisionId")
    status = data.get("decisionStatus")
    if not isinstance(status, str) or status not in DECISION_STATUSES:
        raise RunsInternalError(f"{label}.decisionStatus is invalid")
    evidence_count = data.get("evidenceCount")
    if isinstance(evidence_count, bool) or not isinstance(evidence_count, int) or evidence_count < 0:
        raise RunsInternalError(f"{label}.evidenceCount is invalid")
    confirmed_at = data.get("humanConfirmedAt")
    candidate_type = data.get("candidateType")
    if not isinstance(candidate_type, str) or candidate_type not in CANDIDATE_TYPES:
        raise RunsInternalError(f"{label}.candidateType is invalid")
    return {
        "publicDecisionId": public_id,
        "candidateTitle": _required_text(data, "candidateTitle", label),
        "candidateType": candidate_type,
        "platform": _required_text(data, "platform", label),
        "trackName": _required_text(data, "trackName", label),
        "decisionStatus": status,
        "evidenceCount": evidence_count,
        "humanConfirmedAt": None
        if confirmed_at is None
        else _timestamp_text(confirmed_at, f"{label}.humanConfirmedAt"),
        "updatedAt": _timestamp_text(data.get("updatedAt"), f"{label}.updatedAt"),
    }


def _artifact_summary_from_row(row: Any, label: str = "artifact") -> dict[str, Any]:
    fields = (
        "public_id",
        "public_project_id",
        "artifact_kind",
        "body_authority",
        "current_revision",
        "updated_at",
        "sync_status",
    )
    if isinstance(row, Mapping) and "sync_status" not in row:
        values = _row_values(row, fields[:-1], label) + (None,)
    elif isinstance(row, (tuple, list)) and len(row) == 6:
        values = tuple(row) + (None,)
    else:
        values = _row_values(row, fields, label)
    public_id, project_id, artifact_kind, body_authority, revision, updated_at, sync_status = values
    public_id = _public_id(public_id, f"{label}.publicId")
    project_id = _public_id(project_id, f"{label}.publicProjectId")
    if not isinstance(artifact_kind, str) or artifact_kind not in ARTIFACT_KINDS:
        raise RunsInternalError(f"{label}.artifactKind is invalid")
    if not isinstance(body_authority, str) or body_authority not in BODY_AUTHORITIES:
        raise RunsInternalError(f"{label}.bodyAuthority is invalid")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise RunsInternalError(f"{label}.currentRevision is invalid")
    if body_authority == "internal":
        sync_status = "not_applicable"
    elif sync_status is None:
        sync_status = "pending"
    if not isinstance(sync_status, str) or sync_status not in SYNC_STATUSES:
        raise RunsInternalError(f"{label}.syncStatus is invalid")
    return {
        "publicArtifactId": public_id,
        "publicProjectId": project_id,
        "artifactType": artifact_kind,
        "bodyAuthority": body_authority,
        "currentRevision": revision,
        "syncStatus": sync_status,
        "updatedAt": _timestamp_text(updated_at, f"{label}.updatedAt"),
        "allowedActions": ["read", "edit", "export"],
    }


def _page_size(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_PAGE_SIZE:
        raise RunsInvalidRequest(f"pageSize must be between 1 and {MAX_PAGE_SIZE}", field="pageSize")
    return value


def _search(value: Any) -> str:
    if value is None:
        return ""
    if not isinstance(value, str) or len(value) > 160:
        raise RunsInvalidRequest("search is invalid", field="search")
    return value.strip()


def _search_pattern(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _list_revision(items: list[Mapping[str, Any]]) -> int:
    return max((int(item["revision"]) for item in items), default=0)


def _public_cursor(secret: bytes, context: TenantContext, scope: str, updated_at: Any, public_id: str) -> str:
    tenant_tag = hmac.new(
        secret,
        (context.tenant_id + "|" + _CURSOR_AAD.decode()).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()[:32]
    payload = {
        "v": _CURSOR_VERSION,
        "scope": scope,
        "tenantTag": tenant_tag,
        "updatedAt": _timestamp_text(updated_at, "cursor.updatedAt"),
        "publicId": public_id,
    }
    return foundation.sign_cursor(payload, key=secret, aad=_CURSOR_AAD)


def _decode_cursor(secret: bytes, context: TenantContext, scope: str, token: str) -> _CursorPosition:
    payload = foundation.verify_cursor(
        token,
        key=secret,
        aad=_CURSOR_AAD,
        error=lambda: RunsInvalidRequest("cursor is invalid", field="cursor"),
    )
    if payload.get("v") != _CURSOR_VERSION or payload.get("scope") != scope:
        raise RunsInvalidRequest("cursor is invalid", field="cursor")
    expected_tag = hmac.new(
        secret,
        (context.tenant_id + "|" + _CURSOR_AAD.decode()).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()[:32]
    if not hmac.compare_digest(str(payload.get("tenantTag", "")), expected_tag):
        raise RunsInvalidRequest("cursor is invalid", field="cursor")
    public_id = payload.get("publicId")
    if not isinstance(public_id, str) or PUBLIC_ID_PATTERN.fullmatch(public_id) is None:
        raise RunsInvalidRequest("cursor is invalid", field="cursor")
    updated_at = _timestamp_value(payload.get("updatedAt"), "cursor.updatedAt", request=True)
    return _CursorPosition(scope, expected_tag, updated_at.isoformat(), public_id)


class RunsService:
    """Read B05 facts and document revision identity from PostgreSQL only."""

    _RUN_LIST_QUERY = """
        SELECT public_id, revision, canonical_data, created_at, updated_at
        FROM media_product.creation_runs
        WHERE tenant_id = %s
          AND (
            %s = ''
            OR public_id ILIKE %s ESCAPE '\\'
            OR COALESCE(canonical_data::text, '') ILIKE %s ESCAPE '\\'
          )
          AND (
            CAST(%s AS timestamptz) IS NULL
            OR updated_at < %s
            OR (updated_at = %s AND public_id > %s)
          )
        ORDER BY updated_at DESC, public_id ASC
        LIMIT %s
    """
    _RUN_DETAIL_QUERY = """
        SELECT public_id, revision, canonical_data, created_at, updated_at
        FROM media_product.creation_runs
        WHERE tenant_id = %s AND public_id = %s
    """
    _SOURCE_QUERY = """
        SELECT public_run_id, revision, items, source_kinds, evidence_refs
        FROM media_product.creation_run_sources
        WHERE tenant_id = %s AND public_run_id = %s
    """
    _DECISION_QUERY = """
        SELECT public_run_id, revision, decision_items, human_state
        FROM media_product.creation_run_decisions
        WHERE tenant_id = %s AND public_run_id = %s
    """
    _OUTPUT_QUERY = """
        SELECT public_run_id, revision, output_variants, artifact_public_ids, verification_reports
        FROM media_product.creation_run_outputs
        WHERE tenant_id = %s AND public_run_id = %s
    """
    _ARTIFACTS_QUERY = """
        SELECT a.public_id, a.public_project_id, a.artifact_kind, a.body_authority,
               a.current_revision, a.updated_at,
               CASE WHEN a.body_authority = 'internal' THEN 'not_applicable'
                    ELSE COALESCE(b.status, 'pending') END AS sync_status
        FROM media_product.document_artifacts AS a
        LEFT JOIN media_product.lark_document_bindings AS b
          ON b.tenant_id = a.tenant_id
         AND b.public_artifact_id = a.public_id
        WHERE a.tenant_id = %s AND a.public_id = ANY(%s)
    """
    _ARTIFACT_QUERY = """
        SELECT a.public_id, a.public_project_id, a.artifact_kind, a.body_authority,
               a.current_revision, a.updated_at,
               CASE WHEN a.body_authority = 'internal' THEN 'not_applicable'
                    ELSE COALESCE(b.status, 'pending') END AS sync_status
        FROM media_product.document_artifacts AS a
        LEFT JOIN media_product.lark_document_bindings AS b
          ON b.tenant_id = a.tenant_id
         AND b.public_artifact_id = a.public_id
        WHERE a.tenant_id = %s AND a.public_id = %s
    """
    _OPPORTUNITY_LIST_QUERY = """
        SELECT public_id, revision, canonical_data, updated_at
        FROM media_product.business_opportunities
        WHERE tenant_id = %s
          AND (
            CAST(%s AS timestamptz) IS NULL
            OR updated_at < %s
            OR (updated_at = %s AND public_id > %s)
          )
        ORDER BY updated_at DESC, public_id ASC
        LIMIT %s
    """
    _IDEMPOTENCY_READ_QUERY = """
        SELECT request_checksum, response_json
        FROM media_product.b05_idempotency_keys
        WHERE tenant_id = %s AND operation = %s AND idempotency_key = %s
    """

    def __init__(
        self,
        connection_factory: ConnectionFactory,
        *,
        cursor_secret: bytes,
        id_factory: Callable[[str], str] | None = None,
    ) -> None:
        if len(cursor_secret) < 16:
            raise ValueError("B05 cursor secret must be at least 16 bytes")
        self._connection_factory = connection_factory
        self._cursor_secret = hashlib.sha256(bytes(cursor_secret)).digest()
        self._public_id_secret = self._cursor_secret
        self._id_factory = id_factory or self._new_public_id

    def _new_public_id(self, prefix: str) -> str:
        digest = hmac.new(
            self._public_id_secret,
            (prefix + "|" + secrets.token_urlsafe(18)).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()[:24]
        return f"{prefix}_{digest}"

    def _context(self, context: TenantContext | None) -> TenantContext:
        try:
            return require_context(context)
        except Exception as exc:
            raise RunsForbidden() from exc

    @staticmethod
    def _safe_projection(response: Mapping[str, Any]) -> dict[str, Any]:
        try:
            projected = public_projection(dict(response))
        except RunsError:
            raise
        except Exception as exc:
            raise RunsInternalError() from exc
        if not isinstance(projected, dict):
            raise RunsInternalError("public response is invalid")
        return projected

    @staticmethod
    def error_response(error: BaseException) -> dict[str, Any]:
        if isinstance(error, RunsError):
            return {
                "error": {
                    "code": error.code,
                    "message": error.message,
                    "field": error.field,
                }
            }
        return {
            "error": {
                "code": "internal_error",
                "message": "run data is unavailable",
                "field": None,
            }
        }

    @staticmethod
    def error_status(error: BaseException) -> int:
        return error.status if isinstance(error, RunsError) else 500

    def list_runs(
        self,
        context: TenantContext | None,
        *,
        cursor: str | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
        search: str | None = None,
    ) -> dict[str, Any]:
        context = self._context(context)
        size = _page_size(page_size)
        search_term = _search(search)
        position = _decode_cursor(self._cursor_secret, context, "runs", cursor) if cursor else None
        pattern = _search_pattern(search_term)
        if position is None:
            params = (context.tenant_id, search_term, pattern, pattern, None, None, None, "", size + 1)
        else:
            params = (
                context.tenant_id,
                search_term,
                pattern,
                pattern,
                position.updated_at,
                position.updated_at,
                position.updated_at,
                position.public_id,
                size + 1,
            )
        try:
            with self._connection_factory() as connection:
                rows = _fetchall(connection.execute(self._RUN_LIST_QUERY, params))
        except RunsError:
            raise
        except Exception as exc:
            raise RunsInternalError() from exc
        has_next = len(rows) > size
        visible = rows[:size]
        items = [_run_summary_from_row(row) for row in visible]
        next_cursor = None
        if has_next and visible:
            last = _row_values(visible[-1], ("public_id", "revision", "canonical_data", "created_at", "updated_at"), "run")
            next_cursor = _public_cursor(self._cursor_secret, context, "runs", last[4], _public_id(last[0], "run.publicId"))
        return self._safe_projection(
            {
                "schemaVersion": SCHEMA_VERSION,
                "revision": _list_revision(items),
                "items": items,
                "nextCursor": next_cursor,
            }
        )

    def get_run(self, context: TenantContext | None, public_run_id: str) -> dict[str, Any]:
        context = self._context(context)
        run_id = _public_id(public_run_id, "publicRunId", RunsInvalidRequest)
        try:
            with self._connection_factory() as connection:
                row = _fetchone(connection.execute(self._RUN_DETAIL_QUERY, (context.tenant_id, run_id)))
        except RunsError:
            raise
        except Exception as exc:
            raise RunsInternalError() from exc
        if row is None:
            raise RunsNotFound()
        run = _run_summary_from_row(row)
        return self._safe_projection(
            {
                "schemaVersion": SCHEMA_VERSION,
                "revision": run["revision"],
                "run": run,
            }
        )

    def get_run_sources(self, context: TenantContext | None, public_run_id: str) -> dict[str, Any]:
        context = self._context(context)
        run_id = _public_id(public_run_id, "publicRunId", RunsInvalidRequest)
        try:
            with self._connection_factory() as connection:
                run_row = _fetchone(connection.execute(self._RUN_DETAIL_QUERY, (context.tenant_id, run_id)))
                if run_row is None:
                    raise RunsNotFound()
                row = _fetchone(connection.execute(self._SOURCE_QUERY, (context.tenant_id, run_id)))
        except RunsError:
            raise
        except Exception as exc:
            raise RunsInternalError() from exc
        section = _source_section(run_id, row)
        return self._safe_projection(
            {"schemaVersion": SCHEMA_VERSION, "revision": section["revision"], "section": section}
        )

    def get_run_decisions(self, context: TenantContext | None, public_run_id: str) -> dict[str, Any]:
        context = self._context(context)
        run_id = _public_id(public_run_id, "publicRunId", RunsInvalidRequest)
        try:
            with self._connection_factory() as connection:
                run_row = _fetchone(connection.execute(self._RUN_DETAIL_QUERY, (context.tenant_id, run_id)))
                if run_row is None:
                    raise RunsNotFound()
                row = _fetchone(connection.execute(self._DECISION_QUERY, (context.tenant_id, run_id)))
        except RunsError:
            raise
        except Exception as exc:
            raise RunsInternalError() from exc
        section = _decision_section(run_id, row)
        return self._safe_projection(
            {"schemaVersion": SCHEMA_VERSION, "revision": section["revision"], "section": section}
        )

    def get_run_outputs(self, context: TenantContext | None, public_run_id: str) -> dict[str, Any]:
        context = self._context(context)
        run_id = _public_id(public_run_id, "publicRunId", RunsInvalidRequest)
        try:
            with self._connection_factory() as connection:
                run_row = _fetchone(connection.execute(self._RUN_DETAIL_QUERY, (context.tenant_id, run_id)))
                if run_row is None:
                    raise RunsNotFound()
                row = _fetchone(connection.execute(self._OUTPUT_QUERY, (context.tenant_id, run_id)))
                section = _output_section(connection, context.tenant_id, run_id, row)
        except RunsError:
            raise
        except Exception as exc:
            raise RunsInternalError() from exc
        return self._safe_projection(
            {"schemaVersion": SCHEMA_VERSION, "revision": section["revision"], "section": section}
        )

    def list_business_opportunities(
        self,
        context: TenantContext | None,
        *,
        cursor: str | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> dict[str, Any]:
        context = self._context(context)
        size = _page_size(page_size)
        position = _decode_cursor(self._cursor_secret, context, "business-opportunities", cursor) if cursor else None
        if position is None:
            params = (context.tenant_id, None, None, None, "", size + 1)
        else:
            params = (
                context.tenant_id,
                position.updated_at,
                position.updated_at,
                position.updated_at,
                position.public_id,
                size + 1,
            )
        try:
            with self._connection_factory() as connection:
                rows = _fetchall(connection.execute(self._OPPORTUNITY_LIST_QUERY, params))
        except RunsError:
            raise
        except Exception as exc:
            raise RunsInternalError() from exc
        has_next = len(rows) > size
        visible = rows[:size]
        items = [_business_opportunity_from_row(row) for row in visible]
        item_revision = max(
            (
                _stored_revision(
                    _row_values(row, ("public_id", "revision", "canonical_data", "updated_at"), "business opportunity")[1],
                    "business opportunity",
                )
                for row in visible
            ),
            default=0,
        )
        next_cursor = None
        if has_next and visible:
            last = _row_values(visible[-1], ("public_id", "revision", "canonical_data", "updated_at"), "business opportunity")
            next_cursor = _public_cursor(
                self._cursor_secret,
                context,
                "business-opportunities",
                last[3],
                _public_id(last[0], "businessOpportunity.publicId"),
            )
        return self._safe_projection(
            {
                "schemaVersion": SCHEMA_VERSION,
                "revision": item_revision,
                "items": items,
                "nextCursor": next_cursor,
            }
        )

    def create_artifact_revision(
        self,
        context: TenantContext | None,
        public_artifact_id: str,
        request: Mapping[str, Any],
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        context = self._context(context)
        artifact_id = _public_id(public_artifact_id, "publicArtifactId", RunsInvalidRequest)
        normalized = _revision_request(request)
        _validate_idempotency_key(idempotency_key)
        request_payload = {"publicArtifactId": artifact_id, **normalized}
        with self._connection_factory() as connection:
            try:
                replay = self._load_idempotent(connection, context, "createArtifactRevision", idempotency_key, request_payload)
                if replay is not None:
                    return self._safe_projection(replay)
                row = _fetchone(
                    connection.execute(
                        """
                        SELECT a.public_id, a.public_project_id, a.artifact_kind, a.body_authority,
                               a.current_revision, a.updated_at,
                               CASE WHEN a.body_authority = 'internal' THEN 'not_applicable'
                                    ELSE COALESCE(b.status, 'pending') END AS sync_status
                        FROM media_product.document_artifacts AS a
                        LEFT JOIN media_product.lark_document_bindings AS b
                          ON b.tenant_id = a.tenant_id
                         AND b.public_artifact_id = a.public_id
                        WHERE a.tenant_id = %s AND a.public_id = %s
                        FOR UPDATE
                        """,
                        (context.tenant_id, artifact_id),
                    )
                )
                if row is None:
                    raise RunsNotFound()
                artifact_values = _row_values(
                    row,
                    ("public_id", "public_project_id", "artifact_kind", "body_authority", "current_revision", "updated_at", "sync_status"),
                    "artifact",
                )
                source_artifact_id, project_id, artifact_kind, body_authority, current, _updated_at, _sync_status = artifact_values
                if isinstance(current, bool) or not isinstance(current, int) or current < 0:
                    raise RunsInternalError("artifact current revision is invalid")
                if current != normalized["expectedRevision"]:
                    raise RunsConflict()
                save_as = normalized["mode"] == "save_as"
                target_artifact_id = self._id_factory("artifact") if save_as else source_artifact_id
                next_revision = 1 if save_as else current + 1
                state = "generating" if normalized["mode"] == "regenerate" else "draft"
                checksum = hashlib.sha256(_as_json(request_payload).encode("utf-8")).hexdigest()
                if save_as:
                    connection.execute(
                        """
                        INSERT INTO media_product.document_artifacts
                            (tenant_id, public_id, public_project_id, artifact_kind,
                             workspace_mode, body_authority, current_revision)
                        VALUES (%s, %s, %s, %s, 'ordinary', %s, %s)
                        """,
                        (
                            context.tenant_id,
                            target_artifact_id,
                            project_id,
                            artifact_kind,
                            body_authority,
                            next_revision,
                        ),
                    )
                connection.execute(
                    """
                    INSERT INTO media_product.document_revisions
                        (tenant_id, public_artifact_id, revision, state, base_revision,
                         body_checksum, actor_public_id, generation_source)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        context.tenant_id,
                        target_artifact_id,
                        next_revision,
                        state,
                        None if save_as else current,
                        checksum,
                        context.user_public_id,
                        f"{SOURCE_VERSION}:{normalized['mode']}",
                    ),
                )
                if not save_as:
                    connection.execute(
                        """
                        UPDATE media_product.document_artifacts
                        SET current_revision = %s, updated_at = now()
                        WHERE tenant_id = %s AND public_id = %s
                        """,
                        (next_revision, context.tenant_id, target_artifact_id),
                    )
                readback = _fetchone(
                    connection.execute(self._ARTIFACT_QUERY, (context.tenant_id, target_artifact_id))
                )
                if readback is None:
                    raise RunsInternalError("artifact revision write was not readable")
                item = _artifact_summary_from_row(readback)
                if item["currentRevision"] != next_revision:
                    raise RunsInternalError("artifact revision readback is stale")
                response = {"schemaVersion": SCHEMA_VERSION, "revision": next_revision, "item": item}
                self._store_idempotent(connection, context, "createArtifactRevision", idempotency_key, request_payload, response)
                self._commit(connection)
                return self._safe_projection(response)
            except RunsError:
                raise
            except Exception as exc:
                raise RunsInternalError() from exc

    def _load_idempotent(
        self,
        connection: DatabaseConnection,
        context: TenantContext,
        operation: str,
        idempotency_key: str,
        request: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        row = _fetchone(connection.execute(self._IDEMPOTENCY_READ_QUERY, (context.tenant_id, operation, idempotency_key)))
        if row is None:
            return None
        checksum, response_json = _row_values(row, ("request_checksum", "response_json"), "idempotency")
        expected = hashlib.sha256(_as_json(request).encode("utf-8")).hexdigest()
        if checksum != expected:
            raise RunsConflict("Idempotency-Key was reused with a different request")
        return _json_object(response_json, "idempotent response")

    @staticmethod
    def _store_idempotent(
        connection: DatabaseConnection,
        context: TenantContext,
        operation: str,
        idempotency_key: str,
        request: Mapping[str, Any],
        response: Mapping[str, Any],
    ) -> None:
        checksum = hashlib.sha256(_as_json(request).encode("utf-8")).hexdigest()
        connection.execute(
            """
            INSERT INTO media_product.b05_idempotency_keys
                (tenant_id, operation, idempotency_key, request_checksum, response_json)
            VALUES (%s, %s, %s, %s, CAST(%s AS jsonb))
            ON CONFLICT (tenant_id, operation, idempotency_key) DO NOTHING
            """,
            (context.tenant_id, operation, idempotency_key, checksum, _as_json(response)),
        )

    @staticmethod
    def _commit(connection: Any) -> None:
        commit = getattr(connection, "commit", None)
        if callable(commit):
            commit()


def _run_summary_from_row(row: Any) -> dict[str, Any]:
    public_id, revision, canonical_data, created_at, updated_at = _row_values(
        row,
        ("public_id", "revision", "canonical_data", "created_at", "updated_at"),
        "run",
    )
    data = _json_object(canonical_data, "run canonical data")
    available = data.get("availableSections")
    if not isinstance(available, list) or any(
        not isinstance(item, str) or item not in AVAILABLE_SECTIONS for item in available
    ):
        raise RunsInternalError("run availableSections is invalid")
    if len(set(available)) != len(available):
        raise RunsInternalError("run availableSections contains duplicates")
    public_id = _public_id(public_id, "run.publicId")
    revision = _stored_revision(revision, "run")
    return {
        "publicRunId": public_id,
        "title": _required_text(data, "title", "run"),
        "platform": _nullable_text(data, "platform", "run"),
        "contentType": _nullable_text(data, "contentType", "run"),
        "trackName": _nullable_text(data, "trackName", "run"),
        "entrypoint": _required_text(data, "entrypoint", "run"),
        "status": _required_text(data, "status", "run"),
        "availableSections": list(available),
        "publicProjectId": _nullable_public_id(data, "publicProjectId", "run"),
        "createdAt": _timestamp_text(created_at, "run.createdAt"),
        "updatedAt": _timestamp_text(updated_at, "run.updatedAt"),
        "revision": revision,
    }


def _source_section(public_run_id: str, row: Any) -> dict[str, Any]:
    if row is None:
        return {
            "publicRunId": public_run_id,
            "items": [],
            "sourceKinds": [],
            "evidenceRefs": [],
            "revision": 0,
        }
    stored_id, revision, items, source_kinds, evidence_refs = _row_values(
        row,
        ("public_run_id", "revision", "items", "source_kinds", "evidence_refs"),
        "run source section",
    )
    if stored_id != public_run_id:
        raise RunsInternalError("run source section identity is invalid")
    return {
        "publicRunId": _public_id(stored_id, "run source section.publicRunId"),
        "items": _string_value_maps(items, "run source section.items"),
        "sourceKinds": _string_list(source_kinds, "run source section.sourceKinds"),
        "evidenceRefs": _evidence_refs(evidence_refs, "run source section.evidenceRefs"),
        "revision": _stored_revision(revision, "run source section"),
    }


def _decision_section(public_run_id: str, row: Any) -> dict[str, Any]:
    if row is None:
        return {"publicRunId": public_run_id, "decisionItems": [], "humanState": "unavailable", "revision": 0}
    stored_id, revision, decision_items, human_state = _row_values(
        row,
        ("public_run_id", "revision", "decision_items", "human_state"),
        "run decision section",
    )
    if stored_id != public_run_id:
        raise RunsInternalError("run decision section identity is invalid")
    if not isinstance(human_state, str) or not human_state.strip():
        raise RunsInternalError("run decision section humanState is invalid")
    return {
        "publicRunId": _public_id(stored_id, "run decision section.publicRunId"),
        "decisionItems": [
            _decision_summary(item, f"run decision section.decisionItems[{index}]")
            for index, item in enumerate(_json_list(decision_items, "run decision section.decisionItems"))
        ],
        "humanState": human_state.strip(),
        "revision": _stored_revision(revision, "run decision section"),
    }


def _output_section(
    connection: DatabaseConnection,
    tenant_id: str,
    public_run_id: str,
    row: Any,
) -> dict[str, Any]:
    if row is None:
        return {
            "publicRunId": public_run_id,
            "outputVariants": [],
            "artifactSummaries": [],
            "verificationReports": [],
            "revision": 0,
        }
    stored_id, revision, output_variants, artifact_ids, verification_reports = _row_values(
        row,
        ("public_run_id", "revision", "output_variants", "artifact_public_ids", "verification_reports"),
        "run output section",
    )
    if stored_id != public_run_id:
        raise RunsInternalError("run output section identity is invalid")
    public_artifact_ids = [
        _public_id(item, f"run output section.artifactPublicIds[{index}]")
        for index, item in enumerate(_json_list(artifact_ids, "run output section.artifactPublicIds"))
    ]
    artifacts: list[dict[str, Any]] = []
    if public_artifact_ids:
        rows = _fetchall(connection.execute(RunsService._ARTIFACTS_QUERY, (tenant_id, tuple(public_artifact_ids))))
        by_id = {}
        for artifact_row in rows:
            summary = _artifact_summary_from_row(artifact_row)
            by_id[summary["publicArtifactId"]] = summary
        if set(by_id) != set(public_artifact_ids):
            raise RunsInternalError("run output artifact readback is incomplete")
        artifacts = [by_id[artifact_id] for artifact_id in public_artifact_ids]
    return {
        "publicRunId": _public_id(stored_id, "run output section.publicRunId"),
        "outputVariants": _string_value_maps(output_variants, "run output section.outputVariants"),
        "artifactSummaries": artifacts,
        "verificationReports": _string_value_maps(verification_reports, "run output section.verificationReports"),
        "revision": _stored_revision(revision, "run output section"),
    }


def _business_opportunity_from_row(row: Any) -> dict[str, Any]:
    public_id, revision, canonical_data, _updated_at = _row_values(
        row,
        ("public_id", "revision", "canonical_data", "updated_at"),
        "business opportunity",
    )
    data = _json_object(canonical_data, "business opportunity canonical data")
    valid_from = data.get("validFrom")
    valid_until = data.get("validUntil")
    return {
        "publicOpportunityId": _public_id(public_id, "businessOpportunity.publicId"),
        "brand": _required_text(data, "brand", "business opportunity"),
        "product": _required_text(data, "product", "business opportunity"),
        "platform": _required_text(data, "platform", "business opportunity"),
        "contentType": _required_text(data, "contentType", "business opportunity"),
        "validFrom": None if valid_from is None else _timestamp_text(valid_from, "businessOpportunity.validFrom"),
        "validUntil": None if valid_until is None else _timestamp_text(valid_until, "businessOpportunity.validUntil"),
        "authorizationScope": _required_text(data, "authorizationScope", "business opportunity"),
        "status": _required_text(data, "status", "business opportunity"),
    }


def _revision_request(request: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(request, Mapping):
        raise RunsInvalidRequest("request must be an object")
    expected = request.get("expectedRevision")
    if isinstance(expected, bool) or not isinstance(expected, int) or expected < 0:
        raise RunsInvalidRequest("expectedRevision is invalid", field="expectedRevision")
    instruction = request.get("instruction")
    if not isinstance(instruction, str) or not instruction.strip():
        raise RunsInvalidRequest("instruction is required", field="instruction")
    mode = request.get("mode")
    if not isinstance(mode, str) or mode not in REVISION_MODES:
        raise RunsInvalidRequest("mode is invalid", field="mode")
    return {"expectedRevision": expected, "instruction": instruction.strip(), "mode": mode}


def _validate_idempotency_key(value: Any) -> str:
    return idempotency_key(
        value,
        error=lambda: RunsInvalidRequest("Idempotency-Key is invalid", field="Idempotency-Key"),
        policy=IF2_KEY,
    )
