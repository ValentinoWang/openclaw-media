"""Tenant-scoped B04 decision and sourced-signal projections."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol
from urllib.parse import urlsplit

from . import foundation, sql_pagination
from .foundation import MediaBusinessError, TenantContext, _fetchall, _fetchone, public_projection


SCHEMA_VERSION = "media_web_business_pages_v2"
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100
PUBLIC_ID_PATTERN = foundation.PUBLIC_ID_PATTERN
SIGNAL_KINDS = {"hotlist", "activity", "research"}
CANDIDATE_TYPES = {"activity", "material", "deconstruction", "pattern", "business", "creator"}
DECISION_STATUSES = {"candidate", "recommended", "confirmed", "rejected"}
_CURSOR_VERSION = 1
_CURSOR_AAD = b"media-web-b04-decisions-v1"


DecisionsError = MediaBusinessError


class DecisionsForbidden(foundation.Forbidden):
    def __init__(self) -> None:
        super().__init__("decision data is not available for this session")


class DecisionsNotFound(foundation.NotFound):
    def __init__(self) -> None:
        super().__init__("decision resource was not found")


class DecisionsInvalidRequest(DecisionsError):
    def __init__(self, message: str, *, field: str | None = None) -> None:
        super().__init__(foundation.INVALID_REQUEST, message, status=400, field=field)


class DecisionsConflict(foundation.Conflict):
    def __init__(self, message: str = "decision revision conflict") -> None:
        super().__init__(message)


class DecisionsUnprocessable(foundation.Unprocessable):
    def __init__(self, message: str) -> None:
        super().__init__(message)


class DecisionsInternalError(foundation.InternalError):
    def __init__(self, message: str = "decision data is unavailable") -> None:
        super().__init__(message)


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
    return foundation.canonical_json(value)


def _json_object(value: Any, label: str) -> dict[str, Any]:
    return foundation.json_object(value, label, error=DecisionsInternalError)


def _timestamp_error(label: str, reason: str) -> Exception:
    if reason == "missing":
        return DecisionsInternalError(f"{label} is missing")
    return DecisionsInternalError(f"{label} is invalid")


def _timestamp(value: Any, label: str = "timestamp") -> str:
    return foundation.coerce_utc(value, label, error=_timestamp_error, allow_naive=True).isoformat()


def _parse_timestamp_error(field: str, reason: str) -> Exception:
    if reason == "naive":
        return DecisionsInvalidRequest(f"{field} must include a timezone")
    return DecisionsInvalidRequest(f"{field} is invalid")


def _parse_timestamp(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DecisionsInvalidRequest(f"{field} is invalid")
    return foundation.coerce_utc(value, field, error=_parse_timestamp_error, allow_naive=False).isoformat()


def _public_id(value: Any, field: str) -> str:
    return foundation.public_id(value, field, error_type=DecisionsInternalError)


def _request_public_id(value: Any, field: str) -> str:
    return foundation.public_id(value, field, error_type=DecisionsInvalidRequest)


def _page_size(value: Any) -> int:
    return foundation.page_size(value, error=lambda m: DecisionsInvalidRequest(m, field="pageSize"))


def _search(value: Any) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise DecisionsInvalidRequest("search must be a string")
    normalized = value.strip()
    if len(normalized) > 160:
        raise DecisionsInvalidRequest("search is too long")
    return normalized


def _search_pattern(value: str) -> str:
    return "%" + value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _row_parts(row: Any, label: str) -> tuple[str, int, dict[str, Any], Any, Any]:
    if isinstance(row, Mapping):
        public_id = row.get("public_id")
        revision = row.get("revision", 1)
        canonical_data = row.get("canonical_data", {})
        created_at = row.get("created_at")
        updated_at = row.get("updated_at")
    else:
        try:
            public_id, revision, canonical_data, created_at, updated_at = row[:5]
        except (IndexError, TypeError) as exc:
            raise DecisionsInternalError(f"{label} row is malformed") from exc
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise DecisionsInternalError(f"{label} revision is invalid")
    return (
        _public_id(public_id, f"{label} public id"),
        revision,
        _json_object(canonical_data, label),
        created_at,
        updated_at,
    )


def _signal_row_parts(row: Any, label: str) -> tuple[str, int, dict[str, Any], Any, Any, str]:
    if isinstance(row, Mapping):
        public_id = row.get("public_id")
        revision = row.get("revision", 1)
        canonical_data = row.get("canonical_data", {})
        created_at = row.get("created_at")
        updated_at = row.get("updated_at")
        source_kind = row.get("source_kind", "snapshot")
    else:
        try:
            public_id, revision, canonical_data, created_at, updated_at, source_kind = row[:6]
        except (IndexError, TypeError) as exc:
            raise DecisionsInternalError(f"{label} row is malformed") from exc
    if not isinstance(source_kind, str):
        raise DecisionsInternalError(f"{label} source kind is invalid")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise DecisionsInternalError(f"{label} revision is invalid")
    return (
        _public_id(public_id, f"{label} public id"),
        revision,
        _json_object(canonical_data, label),
        created_at,
        updated_at,
        source_kind,
    )


def _value(data: Mapping[str, Any], *names: str, default: Any = None) -> Any:
    for name in names:
        if name in data:
            return data[name]
    return default


def _required_text(data: Mapping[str, Any], label: str, *names: str) -> str:
    value = _value(data, *names)
    if not isinstance(value, str) or not value.strip():
        raise DecisionsInternalError(f"stored decision {label} is missing")
    return value.strip()


def _optional_text(data: Mapping[str, Any], *names: str) -> str | None:
    value = _value(data, *names)
    if value is None:
        return None
    if not isinstance(value, str):
        raise DecisionsInternalError("stored decision text field is invalid")
    return value.strip() or None


def _int_value(
    data: Mapping[str, Any],
    label: str,
    *names: str,
    default: int | None = None,
) -> int | None:
    value = _value(data, *names, default=default)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise DecisionsInternalError(f"stored decision {label} is invalid")
    return value




def _timestamp_optional(data: Mapping[str, Any], *names: str) -> str | None:
    value = _value(data, *names)
    if value is None:
        return None
    return _timestamp(value, "stored decision timestamp")


def _public_url(value: Any, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise DecisionsInternalError(f"{label} url is invalid")
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise DecisionsInternalError(f"{label} url is not controlled")
    return value.strip()


def _source_ref(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise DecisionsInternalError(f"stored {label} source reference is invalid")
    kind = value.get("kind")
    ref_label = value.get("label")
    public_url = value.get("publicUrl", value.get("public_url"))
    captured_at = value.get("capturedAt", value.get("captured_at"))
    quality = value.get("qualityStatus", value.get("quality_status", "unavailable"))
    if not isinstance(kind, str) or not kind.strip():
        raise DecisionsInternalError(f"stored {label} source reference kind is missing")
    if not isinstance(ref_label, str) or not ref_label.strip():
        raise DecisionsInternalError(f"stored {label} source reference label is missing")
    return {
        "kind": kind.strip(),
        "label": ref_label.strip(),
        "publicUrl": _public_url(public_url, f"{label} source reference"),
        "capturedAt": None if captured_at is None else _timestamp(captured_at, f"{label} source reference"),
        "qualityStatus": str(quality).strip()
        if isinstance(quality, str) and quality.strip()
        else "unavailable",
    }


def _source_refs(data: Mapping[str, Any], label: str = "decision") -> list[dict[str, Any]]:
    value = _value(data, "source_refs", "sourceRefs", "evidence_refs", "evidenceRefs", default=[])
    if value is None:
        return []
    if not isinstance(value, list):
        raise DecisionsInternalError(f"stored {label} source references are invalid")
    return [_source_ref(item, label) for item in value]


def _decision_status(data: Mapping[str, Any]) -> str:
    human = _optional_text(data, "human_decision", "humanDecision")
    if human in {"confirmed", "rejected"}:
        return human
    value = _value(data, "decision_status", "decisionStatus", "status")
    if value is None:
        value = _value(data, "model_status", "modelStatus")
    if not isinstance(value, str) or value not in DECISION_STATUSES:
        raise DecisionsInternalError("stored decision status is invalid")
    return value


def _evidence_count(data: Mapping[str, Any]) -> int:
    explicit = _int_value(data, "evidence count", "evidence_count", "evidenceCount")
    if explicit is not None:
        return explicit
    if _value(data, "source_refs", "sourceRefs", "evidence_refs", "evidenceRefs") is None:
        raise DecisionsInternalError("stored decision evidence count is missing")
    return len(_source_refs(data))


def _facts(data: Mapping[str, Any]) -> dict[str, Any]:
    candidate_type = _required_text(data, "candidate type", "candidate_type", "candidateType")
    if candidate_type not in CANDIDATE_TYPES:
        raise DecisionsInternalError("stored candidate type is invalid")
    return {
        "candidateTitle": _required_text(data, "candidate title", "candidate_title", "candidateTitle"),
        "candidateType": candidate_type,
        "platform": _required_text(data, "platform", "platform"),
        "trackName": _required_text(data, "track name", "track_name", "trackName"),
        "evidenceCount": _evidence_count(data),
        "sourceRefs": _source_refs(data),
    }




def _human(data: Mapping[str, Any]) -> dict[str, Any]:
    decision = _optional_text(data, "human_decision", "humanDecision")
    if decision is not None and decision not in {"confirmed", "rejected"}:
        raise DecisionsInternalError("stored human decision is invalid")
    return {
        "status": decision or "pending",
        "decision": decision,
        "reason": _optional_text(data, "human_reason", "humanReason", "confirmation_reason"),
        "confirmedAt": _timestamp_optional(
            data,
            "human_confirmed_at",
            "humanConfirmedAt",
            "confirmed_at",
            "confirmedAt",
        ),
    }




def _public_cursor(
    secret: bytes,
    context: TenantContext,
    scope: str,
    updated_at: Any,
    public_id: str,
) -> str:
    timestamp = _timestamp(updated_at, "cursor timestamp")
    tenant_tag = hmac.new(
        secret,
        (context.tenant_id + "|" + _CURSOR_AAD.decode()).encode(),
        hashlib.sha256,
    ).hexdigest()[:32]
    payload = {
        "v": _CURSOR_VERSION,
        "scope": scope,
        "tenantTag": tenant_tag,
        "updatedAt": timestamp,
        "publicId": public_id,
    }
    return foundation.sign_cursor(payload, key=secret, aad=_CURSOR_AAD)


def _decode_cursor(
    secret: bytes,
    context: TenantContext,
    scope: str,
    token: str,
) -> _CursorPosition:
    payload = foundation.verify_cursor(
        token,
        key=secret,
        aad=_CURSOR_AAD,
        error=lambda: DecisionsInvalidRequest("cursor is invalid"),
    )
    if payload.get("v") != _CURSOR_VERSION or payload.get("scope") != scope:
        raise DecisionsInvalidRequest("cursor is invalid")
    expected_tag = hmac.new(
        secret,
        (context.tenant_id + "|" + _CURSOR_AAD.decode()).encode(),
        hashlib.sha256,
    ).hexdigest()[:32]
    if not hmac.compare_digest(str(payload.get("tenantTag", "")), expected_tag):
        raise DecisionsInvalidRequest("cursor is invalid")
    public_id = payload.get("publicId")
    if not isinstance(public_id, str) or not PUBLIC_ID_PATTERN.fullmatch(public_id):
        raise DecisionsInvalidRequest("cursor is invalid")
    return _CursorPosition(
        scope,
        expected_tag,
        _parse_timestamp(payload.get("updatedAt"), "cursor.updatedAt"),
        public_id,
    )


def _decision_summary(
    public_id: str,
    data: Mapping[str, Any],
    updated_at: Any,
) -> dict[str, Any]:
    facts = _facts(data)
    return {
        "publicDecisionId": _public_id(public_id, "decision public id"),
        "candidateTitle": facts["candidateTitle"],
        "candidateType": facts["candidateType"],
        "platform": facts["platform"],
        "trackName": facts["trackName"],
        "decisionStatus": _decision_status(data),
        "evidenceCount": facts["evidenceCount"],
        "humanConfirmedAt": _human(data)["confirmedAt"],
        "updatedAt": _timestamp(updated_at, "decision updated_at"),
    }




def _signal_projection(
    public_id: str,
    data: Mapping[str, Any],
    updated_at: Any,
    source_kind: str,
) -> dict[str, Any]:
    kind_value = _value(data, "kind", "signal_kind", "signalKind")
    if kind_value is None:
        kind_value = "activity" if source_kind == "activity" else "hotlist"
    if not isinstance(kind_value, str) or kind_value not in SIGNAL_KINDS:
        raise DecisionsInternalError("stored signal kind is invalid")
    platform = _required_text(data, "signal platform", "platform")
    title = _required_text(data, "signal title", "title")
    rank = _int_value(data, "signal rank", "rank")
    if rank is None:
        raise DecisionsInternalError("stored signal rank is missing")
    captured_at = _value(data, "captured_at", "capturedAt", "collected_at", "collectedAt")
    if captured_at is None:
        raise DecisionsInternalError("stored signal captured_at is missing")
    source_url = _public_url(_value(data, "source_url", "sourceUrl"), "signal source")
    if source_url is None:
        raise DecisionsInternalError("stored signal source_url is missing")
    quality = _value(data, "quality_status", "qualityStatus", default="unavailable")
    if not isinstance(quality, str) or not quality.strip():
        raise DecisionsInternalError("stored signal quality status is invalid")
    return {
        "publicSignalId": _public_id(public_id, "signal public id"),
        "kind": kind_value,
        "platform": platform,
        "title": title,
        "rank": rank,
        "sourceUrl": source_url,
        "capturedAt": _timestamp(captured_at, "signal captured_at"),
        "qualityStatus": quality.strip(),
    }


class DecisionsService:
    """Read and confirm B04 decisions within the authenticated tenant."""

    _STATE_QUERY = """
        SELECT COUNT(*)::bigint, COALESCE(MAX(revision), 0), MAX(updated_at)
        FROM media_product.decision_traces
        WHERE tenant_id = %s
    """
    _LIST_QUERY = """
        SELECT public_id, revision, canonical_data, created_at, updated_at
        FROM media_product.decision_traces
        WHERE tenant_id = %s
          AND (
            %s = ''
            OR public_id ILIKE %s ESCAPE '\\'
            OR canonical_data::text ILIKE %s ESCAPE '\\'
          )
    """
    _DETAIL_QUERY = """
        SELECT public_id, revision, canonical_data, created_at, updated_at
        FROM media_product.decision_traces
        WHERE tenant_id = %s AND public_id = %s
    """
    _SIGNAL_LIST_QUERY = f"""
        SELECT public_id, revision, canonical_data, created_at, updated_at, 'snapshot' AS source_kind
        FROM media_product.signal_snapshots
        WHERE tenant_id = %s
{sql_pagination.keyset_window("", "updated_at", "public_id", include_tail=False)}        UNION ALL
        SELECT public_id, revision, canonical_data, created_at, updated_at, 'activity' AS source_kind
        FROM media_product.activities
        WHERE tenant_id = %s
{sql_pagination.keyset_window("", "updated_at", "public_id")}"""

    def __init__(
        self,
        connection_factory: ConnectionFactory,
        *,
        cursor_secret: bytes = b"",
        public_id_secret: bytes = b"",
        id_factory: Callable[[str], str] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not cursor_secret:
            cursor_secret = secrets.token_bytes(32)
        if not public_id_secret:
            public_id_secret = cursor_secret
        if len(cursor_secret) < 16 or len(public_id_secret) < 16:
            raise ValueError("B04 secrets must be at least 16 bytes")
        self._connection_factory = connection_factory
        # c3/c5: public_id_secret keeps the exact old raw-bytes value
        # (durable public decision ids must not be invalidated -- note this
        # is captured from `public_id_secret` BEFORE cursor_secret's own
        # derivation below, so the "defaults to cursor_secret" branch above
        # still defaults to the original, un-derived input). cursor_secret
        # moves to a purpose-tagged derivation distinct from every other
        # service's, deliberately invalidating any cursor a client is
        # holding across the deploy.
        self._public_id_secret = bytes(public_id_secret)
        self._cursor_secret = foundation.derive_namespace_secret(cursor_secret, "decisions-cursor")
        self._id_factory = id_factory or self._new_public_id
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def _new_public_id(self, prefix: str) -> str:
        digest = hmac.new(
            self._public_id_secret,
            (prefix + "|" + secrets.token_urlsafe(18)).encode(),
            hashlib.sha256,
        ).hexdigest()[:24]
        return f"{prefix}_{digest}"

    def _context(self, context: TenantContext | None) -> TenantContext:
        return foundation.require_context_branded(context, DecisionsForbidden)

    def _now(self) -> str:
        return _timestamp(self._clock(), "clock")

    def list_decisions(
        self,
        context: TenantContext,
        *,
        cursor: str | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
        search: str | None = None,
    ) -> dict[str, Any]:
        context = self._context(context)
        size = _page_size(page_size)
        normalized_search = _search(search)
        position = _decode_cursor(self._cursor_secret, context, "decisions", cursor) if cursor else None
        pattern = _search_pattern(normalized_search)
        query = self._LIST_QUERY
        if position is None:
            query += """
                AND CAST(%s AS timestamptz) IS NULL
                ORDER BY updated_at DESC, public_id ASC
                LIMIT %s
            """
            params = (context.tenant_id, normalized_search, pattern, pattern, None, size + 1)
        else:
            query += f"""
{sql_pagination.keyset_window(
                "", "updated_at", "public_id",
                and_indent=" " * 16, inner_indent=" " * 20, tail_indent=" " * 16, closing_indent=" " * 12,
            )}"""
            params = (
                context.tenant_id,
                normalized_search,
                pattern,
                pattern,
                *sql_pagination.keyset_params(position.updated_at, position.public_id),
                size + 1,
            )
        try:
            with self._connection_factory() as connection:
                state = _fetchone(connection.execute(self._STATE_QUERY, (context.tenant_id,)))
                rows = _fetchall(connection.execute(query, params))
        except DecisionsError:
            raise
        except Exception as exc:
            raise DecisionsInternalError() from exc
        _, max_revision, _ = _state_parts(state)
        has_next = len(rows) > size
        visible = rows[:size]
        items: list[dict[str, Any]] = []
        for row in visible:
            public_id, _, data, _, updated_at = _row_parts(row, "decision")
            items.append(_decision_summary(public_id, data, updated_at))
        next_cursor = None
        if has_next and visible:
            public_id, _, _, _, updated_at = _row_parts(visible[-1], "decision")
            next_cursor = _public_cursor(
                self._cursor_secret,
                context,
                "decisions",
                updated_at,
                public_id,
            )
        response = {
            "schemaVersion": SCHEMA_VERSION,
            "revision": max_revision,
            "items": items,
            "nextCursor": next_cursor,
        }
        return public_projection(response)

    def get_decision(self, context: TenantContext, public_decision_id: str) -> dict[str, Any]:
        context = self._context(context)
        decision_id = _request_public_id(public_decision_id, "publicDecisionId")
        try:
            with self._connection_factory() as connection:
                row = _fetchone(connection.execute(self._DETAIL_QUERY, (context.tenant_id, decision_id)))
        except DecisionsError:
            raise
        except Exception as exc:
            raise DecisionsInternalError() from exc
        if row is None:
            raise DecisionsNotFound()
        public_id, revision, data, _, updated_at = _row_parts(row, "decision")
        return public_projection(
            {
                "schemaVersion": SCHEMA_VERSION,
                "revision": revision,
                "decision": _decision_summary(public_id, data, updated_at),
            }
        )

    def list_decision_signals(
        self,
        context: TenantContext,
        *,
        cursor: str | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> dict[str, Any]:
        context = self._context(context)
        size = _page_size(page_size)
        position = _decode_cursor(self._cursor_secret, context, "decision-signals", cursor) if cursor else None
        timestamp = None if position is None else position.updated_at
        public_id = "" if position is None else position.public_id
        window = sql_pagination.keyset_params(timestamp, public_id)
        params = (
            context.tenant_id,
            *window,
            context.tenant_id,
            *window,
            size + 1,
        )
        try:
            with self._connection_factory() as connection:
                rows = _fetchall(connection.execute(self._SIGNAL_LIST_QUERY, params))
        except DecisionsError:
            raise
        except Exception as exc:
            raise DecisionsInternalError() from exc
        has_next = len(rows) > size
        visible = rows[:size]
        items: list[dict[str, Any]] = []
        for row in visible:
            public_id, _, data, _, updated_at, source_kind = _signal_row_parts(row, "decision signal")
            items.append(_signal_projection(public_id, data, updated_at, source_kind))
        next_cursor = None
        if has_next and visible:
            public_id, _, _, _, updated_at, _ = _signal_row_parts(visible[-1], "decision signal")
            next_cursor = _public_cursor(
                self._cursor_secret,
                context,
                "decision-signals",
                updated_at,
                public_id,
            )
        response = {
            "schemaVersion": SCHEMA_VERSION,
            "revision": max((_row_revision(row) for row in visible), default=0),
            "items": items,
            "nextCursor": next_cursor,
        }
        return public_projection(response)

    def confirm_decision(
        self,
        context: TenantContext,
        public_decision_id: str,
        request: Mapping[str, Any],
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        context = self._context(context)
        decision_id = _request_public_id(public_decision_id, "publicDecisionId")
        normalized = self._validate_confirmation(request)
        replay_request = dict(normalized)
        replay_request["publicDecisionId"] = decision_id
        with self._connection_factory() as connection:
            try:
                replay = self._load_idempotent(
                    connection,
                    context,
                    "confirmDecision",
                    idempotency_key,
                    replay_request,
                )
                if replay is not None:
                    return public_projection(replay)
                row = _fetchone(connection.execute(self._DETAIL_QUERY, (context.tenant_id, decision_id)))
                if row is None:
                    raise DecisionsNotFound()
                stored_id, current_revision, data, _, _ = _row_parts(row, "decision")
                if normalized["expectedRevision"] != current_revision:
                    raise DecisionsConflict()
                now = self._now()
                next_revision = current_revision + 1
                updated = dict(data)
                updated.update(
                    {
                        "human_decision": normalized["decision"],
                        "human_reason": normalized["reason"],
                        "human_confirmed_at": now,
                        "decision_status": normalized["decision"],
                    }
                )
                update_result = connection.execute(
                    """
                    UPDATE media_product.decision_traces
                    SET revision = %s, canonical_data = CAST(%s AS jsonb), updated_at = %s
                    WHERE tenant_id = %s AND public_id = %s AND revision = %s
                    """,
                    (
                        next_revision,
                        _as_json(updated),
                        now,
                        context.tenant_id,
                        stored_id,
                        current_revision,
                    ),
                )
                if hasattr(update_result, "rowcount") and update_result.rowcount == 0:
                    raise DecisionsConflict()
                connection.execute(
                    """
                    INSERT INTO media_product.b04_decision_confirmations
                        (tenant_id, public_decision_id, revision, decision, reason, actor_public_id)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (tenant_id, public_decision_id, revision) DO NOTHING
                    """,
                    (
                        context.tenant_id,
                        stored_id,
                        next_revision,
                        normalized["decision"],
                        normalized["reason"],
                        context.user_public_id,
                    ),
                )
                self._write_decision_revision(
                    connection,
                    context,
                    data=updated,
                    revision=next_revision,
                    actor_public_id=context.user_public_id,
                    reason=normalized["reason"],
                    updated_at=now,
                )
                readback = _fetchone(
                    connection.execute(self._DETAIL_QUERY, (context.tenant_id, stored_id))
                )
                if readback is None:
                    raise DecisionsInternalError("confirmed decision readback is missing")
                readback_id, readback_revision, readback_data, _, readback_updated_at = _row_parts(
                    readback,
                    "confirmed decision",
                )
                if readback_revision != next_revision:
                    raise DecisionsInternalError("confirmed decision readback revision is stale")
                response = {
                    "schemaVersion": SCHEMA_VERSION,
                    "revision": readback_revision,
                    "decision": _decision_summary(
                        readback_id,
                        readback_data,
                        readback_updated_at,
                    ),
                }
                self._store_idempotent(
                    connection,
                    context,
                    "confirmDecision",
                    idempotency_key,
                    replay_request,
                    response,
                )
                _commit(connection)
                return public_projection(response)
            except DecisionsError:
                raise
            except Exception as exc:
                raise DecisionsInternalError() from exc

    @staticmethod
    def error_response(error: BaseException) -> dict[str, Any]:
        return _error_response(error)

    def _validate_confirmation(self, request: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(request, Mapping):
            raise DecisionsInvalidRequest("request must be an object")
        unexpected = set(request) - {"expectedRevision", "decision", "reason"}
        if unexpected:
            raise DecisionsInvalidRequest(f"unexpected field: {sorted(unexpected)[0]}")
        expected = request.get("expectedRevision")
        if isinstance(expected, bool) or not isinstance(expected, int) or expected < 0:
            raise DecisionsInvalidRequest("expectedRevision is invalid")
        decision = request.get("decision")
        if decision not in {"confirmed", "rejected"}:
            raise DecisionsInvalidRequest("decision is invalid")
        reason = request.get("reason")
        if not isinstance(reason, str) or not reason.strip() or len(reason.strip()) > 2000:
            raise DecisionsInvalidRequest("reason is required")
        return {"expectedRevision": expected, "decision": decision, "reason": reason.strip()}

    def _load_idempotent(
        self,
        connection: DatabaseConnection,
        context: TenantContext,
        operation: str,
        idempotency_key: str,
        request: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        _validate_idempotency_key(idempotency_key)
        row = _fetchone(
            connection.execute(
                """
                SELECT request_checksum, response_json
                FROM media_product.b04_idempotency_keys
                WHERE tenant_id = %s AND operation = %s AND idempotency_key = %s
                """,
                (context.tenant_id, operation, idempotency_key),
            )
        )
        if row is None:
            return None
        if isinstance(row, Mapping):
            checksum = row.get("request_checksum")
            response_json = row.get("response_json")
        else:
            checksum, response_json = row[:2]
        expected = hashlib.sha256(_as_json(request).encode()).hexdigest()
        if checksum != expected:
            raise DecisionsConflict("Idempotency-Key was reused with a different request")
        return _json_object(response_json, "idempotent response")

    def _store_idempotent(
        self,
        connection: DatabaseConnection,
        context: TenantContext,
        operation: str,
        idempotency_key: str,
        request: Mapping[str, Any],
        response: Mapping[str, Any],
    ) -> None:
        _validate_idempotency_key(idempotency_key)
        checksum = hashlib.sha256(_as_json(request).encode()).hexdigest()
        connection.execute(
            """
            INSERT INTO media_product.b04_idempotency_keys
                (tenant_id, operation, idempotency_key, request_checksum, response_json)
            VALUES (%s, %s, %s, %s, CAST(%s AS jsonb))
            ON CONFLICT (tenant_id, operation, idempotency_key) DO NOTHING
            """,
            (
                context.tenant_id,
                operation,
                idempotency_key,
                checksum,
                _as_json(response),
            ),
        )

    def _write_decision_revision(
        self,
        connection: DatabaseConnection,
        context: TenantContext,
        *,
        data: Mapping[str, Any],
        revision: int,
        actor_public_id: str,
        reason: str,
        updated_at: str,
    ) -> None:
        artifact_id = _value(data, "public_artifact_id", "publicArtifactId")
        project_id = _value(data, "public_project_id", "publicProjectId")
        if artifact_id is None and project_id is None:
            return
        if not isinstance(artifact_id, str) or not PUBLIC_ID_PATTERN.fullmatch(artifact_id):
            raise DecisionsInternalError("decision artifact id is invalid")
        if not isinstance(project_id, str) or not PUBLIC_ID_PATTERN.fullmatch(project_id):
            raise DecisionsInternalError("decision project id is invalid")
        connection.execute(
            """
            UPDATE media_product.document_artifacts
            SET current_revision = %s, updated_at = %s
            WHERE tenant_id = %s AND public_id = %s
            """,
            (revision, updated_at, context.tenant_id, artifact_id),
        )
        body = _decision_body(data, reason)
        checksum = hashlib.sha256(_as_json(body).encode()).hexdigest()
        connection.execute(
            """
            INSERT INTO media_product.document_revisions
                (tenant_id, public_artifact_id, revision, state, base_revision,
                 body_checksum, actor_public_id, generation_source)
            VALUES (%s, %s, %s, 'ready', %s, %s, %s, 'creation_decision_brief')
            ON CONFLICT (tenant_id, public_artifact_id, revision) DO NOTHING
            """,
            (
                context.tenant_id,
                artifact_id,
                revision,
                revision - 1 if revision > 1 else None,
                checksum,
                actor_public_id,
            ),
        )
        connection.execute(
            """
            INSERT INTO media_document.revision_bodies
                (tenant_id, public_artifact_id, revision, schema_version,
                 body_json, body_checksum)
            VALUES (%s, %s, %s, 'media.document.body.v1',
                    CAST(%s AS jsonb), %s)
            ON CONFLICT (tenant_id, public_artifact_id, revision) DO NOTHING
            """,
            (context.tenant_id, artifact_id, revision, _as_json(body), checksum),
        )


def _decision_body(data: Mapping[str, Any], reason: str) -> dict[str, Any]:
    candidate = _required_text(data, "candidate title", "candidate_title", "candidateTitle")
    return {
        "schemaVersion": "media.document.body.v1",
        "blocks": [
            {
                "id": "b04_decision_heading",
                "type": "heading_1",
                "attrs": {},
                "content": [{"type": "text", "text": candidate, "marks": []}],
            },
            {
                "id": "b04_decision_confirmation",
                "type": "paragraph",
                "attrs": {},
                "content": [{"type": "text", "text": reason, "marks": []}],
            },
        ],
    }


def _validate_idempotency_key(value: Any) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > 200:
        raise DecisionsInvalidRequest("Idempotency-Key is required")


def _state_parts(row: Any) -> tuple[int, int, Any]:
    if not isinstance(row, (tuple, list)) or len(row) != 3:
        raise DecisionsInternalError("decision state row is malformed")
    count, max_revision, latest = row
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise DecisionsInternalError("decision count is invalid")
    if isinstance(max_revision, bool) or not isinstance(max_revision, int) or max_revision < 0:
        raise DecisionsInternalError("decision state revision is invalid")
    return count, max_revision, latest


def _row_revision(row: Any) -> int:
    if isinstance(row, Mapping):
        value = row.get("revision")
    else:
        value = row[1] if isinstance(row, (tuple, list)) and len(row) > 1 else None
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 1 else 0


def _commit(connection: Any) -> None:
    commit = getattr(connection, "commit", None)
    if callable(commit):
        commit()


def _error_response(error: BaseException) -> dict[str, Any]:
    if isinstance(error, DecisionsError):
        return {"error": {"code": error.code, "message": error.message, "field": None}}
    return {
        "error": {
            "code": "internal_error",
            "message": "decision data is unavailable",
            "field": None,
        }
    }


__all__ = [
    "DecisionsConflict",
    "DecisionsError",
    "DecisionsForbidden",
    "DecisionsInternalError",
    "DecisionsInvalidRequest",
    "DecisionsNotFound",
    "DecisionsService",
    "DecisionsUnprocessable",
]
