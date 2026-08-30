"""Tenant-scoped B07 review and metric projections.

The service deliberately reads only the PostgreSQL product model. Existing
review runners remain responsible for recognition and model generation; this
module validates and projects their persisted facts for the Media Web API.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Protocol
from urllib.parse import urlparse

from . import foundation
from .foundation import MediaBusinessError, TenantContext, _fetchall, _fetchone, public_projection


SCHEMA_VERSION = "media_web_business_pages_v2"
DEFAULT_PAGE_SIZE = 30
MAX_PAGE_SIZE = 100
SOURCE_VERSION = "b07.reviews.v1"
PUBLIC_ID_PATTERN = foundation.PUBLIC_ID_PATTERN
REVIEW_WINDOWS = {"24h", "7d"}
METRIC_WINDOWS = {"24h", "7d", "custom"}
METRIC_SOURCES = {"authorized_api", "structured_file", "image", "manual"}
EVIDENCE_QUALITY = {"verified", "partial", "unverified", "unavailable"}
_QUALITY_RANK = {"verified": 0, "partial": 1, "unverified": 2, "unavailable": 3}
_CURSOR_VERSION = 1
_CURSOR_AAD = b"media-web-b07-reviews-v1"
_LARK_DOCUMENT_ROOT_HOSTS = frozenset({"feishu.cn", "larksuite.com", "larkoffice.com"})
_LARK_DOCUMENT_HOST_SUFFIXES = (".feishu.cn", ".larksuite.com", ".larkoffice.com")
_LARK_DOCUMENT_PATH = re.compile(r"^/(wiki|docx)/([A-Za-z0-9_-]{8,160})$")


ReviewsError = MediaBusinessError


class ReviewsForbidden(foundation.Forbidden):
    def __init__(self) -> None:
        super().__init__("review data is not available for this session")


class ReviewsNotFound(foundation.NotFound):
    def __init__(self) -> None:
        super().__init__("review resource was not found")


class ReviewsInvalidRequest(ReviewsError):
    def __init__(self, message: str, *, field: str | None = None) -> None:
        super().__init__(foundation.INVALID_REQUEST, message, status=400, field=field)


class ReviewsConflict(foundation.Conflict):
    def __init__(self, message: str = "review revision conflict") -> None:
        super().__init__(message)


class ReviewsUnprocessable(foundation.Unprocessable):
    def __init__(self, message: str) -> None:
        super().__init__(message)


class ReviewsInternalError(foundation.InternalError):
    def __init__(self, message: str = "review data is unavailable") -> None:
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


def _timestamp_error(label: str, reason: str) -> Exception:
    if reason == "missing":
        return ReviewsInternalError("stored timestamp is missing")
    return ReviewsInternalError("stored timestamp is invalid")


def _timestamp(value: Any) -> str:
    return foundation.coerce_utc(value, "stored timestamp", error=_timestamp_error, allow_naive=True).isoformat()


def _parse_timestamp_error(field: str, reason: str) -> Exception:
    if reason == "naive":
        return ReviewsInvalidRequest(f"{field} must include a timezone")
    return ReviewsInvalidRequest(f"{field} must be an ISO timestamp")


def _parse_timestamp(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ReviewsInvalidRequest(f"{field} must be an ISO timestamp")
    return foundation.coerce_utc(value, field, error=_parse_timestamp_error, allow_naive=False).isoformat()


def _json_object(value: Any, label: str) -> dict[str, Any]:
    return foundation.json_object(value, label, error=ReviewsInternalError)


def _row_parts(row: Any, label: str) -> tuple[str, int, dict[str, Any], Any]:
    if isinstance(row, Mapping):
        public_id = row.get("public_id")
        revision = row.get("revision", 1)
        canonical_data = row.get("canonical_data", {})
        updated_at = row.get("updated_at")
    else:
        try:
            public_id, revision, canonical_data, updated_at = row[:4]
        except (IndexError, TypeError) as exc:
            raise ReviewsInternalError(f"{label} row is malformed") from exc
    if not isinstance(public_id, str) or not PUBLIC_ID_PATTERN.fullmatch(public_id):
        raise ReviewsInternalError(f"{label} public id is invalid")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise ReviewsInternalError(f"{label} revision is invalid")
    return public_id, revision, _json_object(canonical_data, label), updated_at


def _value(data: Mapping[str, Any], *names: str, default: Any = None) -> Any:
    for name in names:
        if name in data:
            return data[name]
    return default


def _public_lark_document_url(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = urlparse(value.strip())
        host = str(parsed.hostname or "").lower()
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
        or parsed.query
        or parsed.fragment
        or parsed.params
    ):
        return None
    if not (
        host in _LARK_DOCUMENT_ROOT_HOSTS
        or any(host.endswith(suffix) for suffix in _LARK_DOCUMENT_HOST_SUFFIXES)
    ):
        return None
    path_match = _LARK_DOCUMENT_PATH.fullmatch(parsed.path)
    if path_match is None:
        return None
    document_type, token = path_match.groups()
    return f"https://{host}/{document_type}/{token}"


def _require_public_id(value: Any, field: str) -> str:
    if not isinstance(value, str) or not PUBLIC_ID_PATTERN.fullmatch(value):
        raise ReviewsInvalidRequest(f"{field} is invalid")
    return value


def _as_json(value: Any) -> str:
    return foundation.canonical_json(value)


def _safe_number(value: Any, field: str) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ReviewsUnprocessable(f"{field} must be numeric")
    if isinstance(value, Decimal):
        value = float(value)
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise ReviewsUnprocessable(f"{field} must be finite")
    return value


def _unit_for_metric(metric_key: str) -> str:
    normalized = metric_key.lower()
    if any(token in normalized for token in ("rate", "ratio", "percent", "completion", "retention")):
        return "percent"
    if any(token in normalized for token in ("second", "duration", "time")):
        return "seconds"
    return "count"


def _public_cursor(secret: bytes, context: TenantContext, scope: str, updated_at: Any, public_id: str) -> str:
    timestamp = _timestamp(updated_at)
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


def _decode_cursor(secret: bytes, context: TenantContext, scope: str, token: str) -> _CursorPosition:
    payload = foundation.verify_cursor(
        token,
        key=secret,
        aad=_CURSOR_AAD,
        error=lambda: ReviewsInvalidRequest("cursor is invalid"),
    )
    if payload.get("v") != _CURSOR_VERSION or payload.get("scope") != scope:
        raise ReviewsInvalidRequest("cursor is invalid")
    expected_tag = hmac.new(
        secret,
        (context.tenant_id + "|" + _CURSOR_AAD.decode()).encode(),
        hashlib.sha256,
    ).hexdigest()[:32]
    if not hmac.compare_digest(str(payload.get("tenantTag", "")), expected_tag):
        raise ReviewsInvalidRequest("cursor is invalid")
    public_id = payload.get("publicId")
    updated_at = payload.get("updatedAt")
    if not isinstance(public_id, str) or not PUBLIC_ID_PATTERN.fullmatch(public_id):
        raise ReviewsInvalidRequest("cursor is invalid")
    return _CursorPosition(scope, expected_tag, _parse_timestamp(updated_at, "cursor.updatedAt"), public_id)


def _page_size(value: int) -> int:
    return foundation.page_size(value, error=lambda m: ReviewsInvalidRequest(m, field="pageSize"))


def _artifact_summary(
    artifact_id: str,
    project_id: str,
    revision: int,
    updated_at: str,
) -> dict[str, Any]:
    return {
        "publicArtifactId": artifact_id,
        "publicProjectId": project_id,
        "artifactType": "review_report",
        "bodyAuthority": "internal",
        "currentRevision": revision,
        "syncStatus": "not_applicable",
        "updatedAt": updated_at,
        "allowedActions": ["read", "edit", "export", "confirm"],
    }


class ReviewsService:
    """Read and write B07 facts within the authenticated tenant projection."""

    _REVIEW_SELECT = """
        SELECT r.public_id,
               r.revision,
               r.canonical_data,
               r.updated_at,
               NULLIF(package.canonical_data->'content_fields'->>'title', '') AS post_title
        FROM media_product.review_records AS r
        LEFT JOIN media_product.published_posts AS post
          ON post.tenant_id = r.tenant_id
         AND post.public_id = r.canonical_data->>'public_post_id'
        LEFT JOIN media_product.publishing_packages AS package
          ON package.tenant_id = post.tenant_id
         AND package.public_id = post.canonical_data->>'public_package_id'
        WHERE r.tenant_id = %s
    """
    _METRIC_SELECT = """
        SELECT public_id, revision, canonical_data, updated_at
        FROM {table}
        WHERE tenant_id = %s
          {subject_filter}
    """

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
            raise ValueError("B07 secrets must be at least 16 bytes")
        self._connection_factory = connection_factory
        # c3/c5: public_id_secret keeps the exact old raw-bytes value
        # (durable public review ids must not be invalidated -- captured
        # from `public_id_secret` BEFORE cursor_secret's own derivation
        # below, so the "defaults to cursor_secret" branch above still
        # defaults to the original, un-derived input). cursor_secret moves
        # to a purpose-tagged derivation distinct from every other
        # service's, deliberately invalidating any cursor a client is
        # holding across the deploy.
        self._public_id_secret = bytes(public_id_secret)
        self._cursor_secret = foundation.derive_namespace_secret(cursor_secret, "reviews-cursor")
        self._id_factory = id_factory or self._new_public_id
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def _new_public_id(self, prefix: str) -> str:
        digest = hmac.new(
            self._public_id_secret,
            (prefix + "|" + secrets.token_urlsafe(18)).encode(),
            hashlib.sha256,
        ).hexdigest()[:24]
        return f"{prefix}_{digest}"

    def _context(self, context: TenantContext) -> TenantContext:
        return foundation.require_context_branded(context, ReviewsForbidden)

    def _now(self) -> str:
        return _timestamp(self._clock())

    def _load_idempotent(
        self,
        connection: DatabaseConnection,
        context: TenantContext,
        operation: str,
        idempotency_key: str,
        request: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        if not isinstance(idempotency_key, str) or not idempotency_key.strip() or len(idempotency_key) > 200:
            raise ReviewsInvalidRequest("Idempotency-Key is required")
        cursor = connection.execute(
            """
            SELECT request_checksum, response_json
            FROM media_product.b07_idempotency_keys
            WHERE tenant_id = %s AND operation = %s AND idempotency_key = %s
            """,
            (context.tenant_id, operation, idempotency_key),
        )
        row = _fetchone(cursor)
        if row is None:
            return None
        if isinstance(row, Mapping):
            checksum = row.get("request_checksum")
            response_json = row.get("response_json")
        else:
            checksum, response_json = row[:2]
        request_checksum = hashlib.sha256(_as_json(request).encode()).hexdigest()
        if checksum != request_checksum:
            raise ReviewsConflict("Idempotency-Key was reused with a different request")
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
        checksum = hashlib.sha256(_as_json(request).encode()).hexdigest()
        connection.execute(
            """
            INSERT INTO media_product.b07_idempotency_keys
                (tenant_id, operation, idempotency_key, request_checksum, response_json)
            VALUES (%s, %s, %s, %s, CAST(%s AS jsonb))
            ON CONFLICT (tenant_id, operation, idempotency_key) DO NOTHING
            """,
            (context.tenant_id, operation, idempotency_key, checksum, _as_json(response)),
        )

    def _commit(self, connection: Any) -> None:
        commit = getattr(connection, "commit", None)
        if callable(commit):
            commit()

    def list_reviews(
        self,
        context: TenantContext,
        *,
        cursor: str | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> dict[str, Any]:
        context = self._context(context)
        size = _page_size(page_size)
        position = _decode_cursor(self._cursor_secret, context, "reviews", cursor) if cursor else None
        query = self._REVIEW_SELECT
        params: tuple[Any, ...]
        if position is None:
            query += " ORDER BY r.updated_at DESC, r.public_id ASC LIMIT %s"
            params = (context.tenant_id, size + 1)
        else:
            query += """
                AND (
                    r.updated_at < %s
                    OR (r.updated_at = %s AND r.public_id > %s)
                )
                ORDER BY r.updated_at DESC, r.public_id ASC
                LIMIT %s
            """
            params = (context.tenant_id, position.updated_at, position.updated_at, position.public_id, size + 1)
        try:
            with self._connection_factory() as connection:
                rows = _fetchall(connection.execute(query, params))
        except ReviewsError:
            raise
        except Exception as exc:
            raise ReviewsInternalError() from exc

        has_next = len(rows) > size
        visible = rows[:size]
        items = []
        for row in visible:
            public_id, revision, data, _ = _row_parts(row, "review")
            if isinstance(row, Mapping):
                post_title = row.get("post_title")
            elif isinstance(row, (tuple, list)) and len(row) >= 5:
                post_title = row[4]
            else:
                post_title = None
            items.append(self._review_projection(public_id, revision, data, post_title))
        next_cursor = None
        if has_next and visible:
            _, _, _, updated_at = _row_parts(visible[-1], "review")
            next_cursor = _public_cursor(
                self._cursor_secret,
                context,
                "reviews",
                updated_at,
                _row_parts(visible[-1], "review")[0],
            )
        response = {
            "schemaVersion": SCHEMA_VERSION,
            "revision": max((item["revision"] for item in items), default=0),
            "items": items,
            "nextCursor": next_cursor,
        }
        return public_projection(response)

    def _review_projection(
        self,
        public_id: str,
        revision: int,
        data: Mapping[str, Any],
        post_title: Any = None,
    ) -> dict[str, Any]:
        post_id = _value(data, "public_post_id", "publicPostId")
        platform = _value(data, "platform")
        evidence_quality = _value(data, "evidence_quality", "evidenceQuality")
        status = _value(data, "status")
        if not all(isinstance(value, str) and value for value in (post_id, platform, evidence_quality, status)):
            raise ReviewsInternalError("stored review projection is incomplete")
        snapshot24h = _value(data, "snapshot_24h", "snapshot24h")
        snapshot7d = _value(data, "snapshot_7d", "snapshot7d")
        for value in (snapshot24h, snapshot7d):
            if value is not None and not isinstance(value, str):
                raise ReviewsInternalError("stored review snapshot is invalid")
        model_suggestion = _value(data, "model_suggestion", "modelSuggestion")
        human_decision = _value(data, "human_decision", "humanDecision")
        document_url = _value(data, "document_url", "documentUrl")
        for value in (model_suggestion, human_decision):
            if value is not None and not isinstance(value, str):
                raise ReviewsInternalError("stored review conclusion is invalid")
        if document_url is not None and not isinstance(document_url, str):
            raise ReviewsInternalError("stored review document URL is invalid")
        if post_title is not None and not isinstance(post_title, str):
            raise ReviewsInternalError("stored post title is invalid")
        normalized_post_title = post_title.strip() if isinstance(post_title, str) else None
        normalized_document_url = _public_lark_document_url(document_url)
        return {
            "publicReviewId": public_id,
            "publicPostId": _require_public_id(post_id, "publicPostId"),
            "postTitle": normalized_post_title or None,
            "documentUrl": normalized_document_url or None,
            "platform": platform,
            "snapshot24h": snapshot24h,
            "snapshot7d": snapshot7d,
            "evidenceQuality": evidence_quality,
            "modelSuggestion": model_suggestion,
            "humanDecision": human_decision,
            "status": status,
            "revision": revision,
        }

    def get_reviews_summary(self, context: TenantContext) -> dict[str, Any]:
        context = self._context(context)
        try:
            with self._connection_factory() as connection:
                row = _fetchone(
                    connection.execute(
                        """
                        SELECT
                            COUNT(*)::int,
                            COUNT(*) FILTER (
                                WHERE NULLIF(canonical_data->>'snapshot_24h', '') IS NULL
                            )::int,
                            COUNT(*) FILTER (
                                WHERE NULLIF(canonical_data->>'snapshot_7d', '') IS NULL
                            )::int,
                            COUNT(*) FILTER (
                                WHERE canonical_data->>'human_decision' IS NOT NULL
                            )::int,
                            COALESCE(AVG(
                                CASE
                                    WHEN canonical_data->>'evidence_quality' = 'verified' THEN 1.0
                                    WHEN canonical_data->>'evidence_quality' = 'partial' THEN 0.5
                                    ELSE 0.0
                                END
                            ), 0.0),
                            COALESCE(MAX(revision), 0)::int
                        FROM media_product.review_records
                        WHERE tenant_id = %s
                        """,
                        (context.tenant_id,),
                    )
                )
        except ReviewsError:
            raise
        except Exception as exc:
            raise ReviewsInternalError() from exc
        if row is None:
            raise ReviewsInternalError("review summary is unavailable")
        values = list(row.values()) if isinstance(row, Mapping) else list(row)
        if len(values) < 5:
            raise ReviewsInternalError("review summary row is malformed")
        try:
            review_count, pending24h, pending7d, confirmed_count = [int(value) for value in values[:4]]
            evidence_coverage = float(values[4])
        except (TypeError, ValueError) as exc:
            raise ReviewsInternalError("review summary values are invalid") from exc
        revision = int(values[5]) if len(values) > 5 and isinstance(values[5], int) else (1 if review_count else 0)
        return public_projection(
            {
                "schemaVersion": SCHEMA_VERSION,
                "revision": revision,
                "summary": {
                    "reviewCount": review_count,
                    "pending24h": pending24h,
                    "pending7d": pending7d,
                    "confirmedCount": confirmed_count,
                    "evidenceCoverage": evidence_coverage,
                    "generatedAt": self._now(),
                },
            }
        )

    def list_content_metrics(
        self,
        context: TenantContext,
        *,
        cursor: str | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> dict[str, Any]:
        return self._list_metrics(
            context,
            "content",
            table="media_product.metric_snapshots",
            cursor=cursor,
            page_size=page_size,
        )

    def list_account_metrics(
        self,
        context: TenantContext,
        *,
        cursor: str | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> dict[str, Any]:
        return self._list_metrics(
            context,
            "account",
            table="media_product.account_metric_snapshots",
            cursor=cursor,
            page_size=page_size,
        )

    def _list_metrics(
        self,
        context: TenantContext,
        subject_type: str,
        *,
        table: str,
        cursor: str | None,
        page_size: int,
    ) -> dict[str, Any]:
        context = self._context(context)
        size = _page_size(page_size)
        scope = f"metrics:{subject_type}"
        position = _decode_cursor(self._cursor_secret, context, scope, cursor) if cursor else None
        if table not in {
            "media_product.metric_snapshots",
            "media_product.account_metric_snapshots",
        }:
            raise ReviewsInternalError("metric table is invalid")
        subject_filter = (
            "AND canonical_data->>'subject_type' = %s"
            if table == "media_product.metric_snapshots"
            else ""
        )
        query = self._METRIC_SELECT.format(table=table, subject_filter=subject_filter)
        params_prefix: tuple[Any, ...] = (
            (context.tenant_id, subject_type)
            if table == "media_product.metric_snapshots"
            else (context.tenant_id,)
        )
        if position is None:
            query += " ORDER BY updated_at DESC, public_id ASC LIMIT %s"
            params = params_prefix + (size + 1,)
        else:
            query += """
                AND (
                    updated_at < %s
                    OR (updated_at = %s AND public_id > %s)
                )
                ORDER BY updated_at DESC, public_id ASC
                LIMIT %s
            """
            params = params_prefix + (
                position.updated_at,
                position.updated_at,
                position.public_id,
                size + 1,
            )
        try:
            with self._connection_factory() as connection:
                rows = _fetchall(connection.execute(query, params))
        except ReviewsError:
            raise
        except Exception as exc:
            raise ReviewsInternalError() from exc
        has_next = len(rows) > size
        visible = rows[:size]
        items = []
        for row in visible:
            public_id, revision, data, _ = _row_parts(row, "metric")
            items.append(self._metric_projection(public_id, data, subject_type))
        next_cursor = None
        if has_next and visible:
            last_id, _, _, last_updated = _row_parts(visible[-1], "metric")
            next_cursor = _public_cursor(
                self._cursor_secret,
                context,
                scope,
                last_updated,
                last_id,
            )
        response = {
            "schemaVersion": SCHEMA_VERSION,
            "revision": max((_metric_revision(row) for row in visible), default=0),
            "items": items,
            "nextCursor": next_cursor,
        }
        return public_projection(response)

    def _metric_projection(
        self,
        public_id: str,
        data: Mapping[str, Any],
        subject_type_hint: str | None = None,
    ) -> dict[str, Any]:
        subject_type = _value(data, "subject_type", "subjectType", default=subject_type_hint)
        subject_id = _value(
            data,
            "public_subject_id",
            "publicSubjectId",
            "public_account_id" if subject_type == "account" else "public_post_id",
        )
        review_window = _value(data, "review_window", "reviewWindow")
        metric_key = _value(data, "metric_key", "metricKey")
        metric_value = _safe_number(_value(data, "metric_value", "metricValue"), "metricValue")
        unit = _value(data, "unit")
        evidence_quality = _value(data, "evidence_quality", "evidenceQuality")
        collected_at = _value(data, "collected_at", "collectedAt")
        if subject_type not in {"content", "account"}:
            raise ReviewsInternalError("stored metric subject type is invalid")
        if not isinstance(subject_id, str) or not PUBLIC_ID_PATTERN.fullmatch(subject_id):
            raise ReviewsInternalError("stored metric subject id is invalid")
        if review_window not in METRIC_WINDOWS:
            raise ReviewsInternalError("stored metric review window is invalid")
        if not isinstance(metric_key, str) or not metric_key.strip():
            raise ReviewsInternalError("stored metric key is invalid")
        if not isinstance(unit, str) or not unit.strip():
            raise ReviewsInternalError("stored metric unit is missing")
        if evidence_quality not in EVIDENCE_QUALITY:
            raise ReviewsInternalError("stored metric evidence quality is invalid")
        return {
            "publicSnapshotId": public_id,
            "subjectType": subject_type,
            "publicSubjectId": subject_id,
            "reviewWindow": review_window,
            "metricKey": metric_key,
            "metricValue": metric_value,
            "unit": unit,
            "evidenceQuality": evidence_quality,
            "collectedAt": _timestamp(collected_at),
        }

    def create_metric_import(
        self,
        context: TenantContext,
        request: Mapping[str, Any],
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        context = self._context(context)
        normalized = self._validate_metric_import(request)
        with self._connection_factory() as connection:
            try:
                replay = self._load_idempotent(
                    connection, context, "createMetricImport", idempotency_key, normalized
                )
                if replay is not None:
                    return public_projection(replay)
                self._published_post(connection, context, normalized["publicPostId"])
                collected_at, evidence_quality = self._evidence_summary(normalized["evidenceRefs"])
                readback_rows: list[Any] = []
                for metric_key, value in sorted(normalized["values"].items()):
                    metric_value = _safe_number(value, f"values.{metric_key}")
                    public_id = self._id_factory("metric")
                    canonical_data = {
                        "subject_type": "content",
                        "public_subject_id": normalized["publicPostId"],
                        "review_window": normalized["reviewWindow"],
                        "metric_key": metric_key,
                        "metric_value": metric_value,
                        "unit": _unit_for_metric(metric_key),
                        "evidence_quality": evidence_quality,
                        "collected_at": collected_at,
                        "source_type": normalized["sourceType"],
                        "evidence_refs": normalized["evidenceRefs"],
                    }
                    inserted = _fetchone(
                        connection.execute(
                            """
                            INSERT INTO media_product.metric_snapshots
                                (tenant_id, public_id, source_version, revision, canonical_data)
                            VALUES (%s, %s, %s, 1, CAST(%s AS jsonb))
                            ON CONFLICT DO NOTHING
                            RETURNING public_id, revision, canonical_data, updated_at
                            """,
                            (
                                context.tenant_id,
                                public_id,
                                SOURCE_VERSION,
                                _as_json(canonical_data),
                            ),
                        )
                    )
                    if inserted is None:
                        inserted = _fetchone(
                            connection.execute(
                                """
                                SELECT public_id, revision, canonical_data, updated_at
                                FROM media_product.metric_snapshots
                                WHERE tenant_id = %s
                                  AND canonical_data->>'public_subject_id' = %s
                                  AND canonical_data->>'review_window' = %s
                                  AND canonical_data->>'metric_key' = %s
                                  AND canonical_data->>'collected_at' = %s
                                """,
                                (
                                    context.tenant_id,
                                    normalized["publicPostId"],
                                    normalized["reviewWindow"],
                                    metric_key,
                                    collected_at,
                                ),
                            )
                        )
                        if inserted is None:
                            raise ReviewsInternalError("metric snapshot write was not readable")
                        _, _, existing_data, _ = _row_parts(inserted, "metric")
                        existing_value = _safe_number(
                            _value(existing_data, "metric_value", "metricValue"),
                            "metricValue",
                        )
                        if (
                            existing_value != metric_value
                            or _value(existing_data, "unit") != _unit_for_metric(metric_key)
                            or _value(existing_data, "evidence_quality", "evidenceQuality")
                            != evidence_quality
                            or _value(existing_data, "collected_at", "collectedAt") != collected_at
                            or _value(existing_data, "source_type", "sourceType")
                            != normalized["sourceType"]
                            or _value(existing_data, "evidence_refs", "evidenceRefs")
                            != normalized["evidenceRefs"]
                        ):
                            raise ReviewsConflict(
                                "metric snapshot already exists with different facts"
                            )
                    readback_rows.append(inserted)
                if not readback_rows:
                    raise ReviewsInvalidRequest("values must contain at least one metric")
                for row in readback_rows:
                    public_id, _, data, _ = _row_parts(row, "metric")
                    self._metric_projection(public_id, data, "content")
                response = {
                    "schemaVersion": SCHEMA_VERSION,
                    "revision": max((_metric_revision(row) for row in readback_rows), default=0),
                    "ok": True,
                    "updatedAt": max(
                        (_timestamp(_row_parts(row, "metric")[3]) for row in readback_rows),
                        default=self._now(),
                    ),
                }
                self._store_idempotent(
                    connection, context, "createMetricImport", idempotency_key, normalized, response
                )
                self._commit(connection)
                return public_projection(response)
            except ReviewsError:
                raise
            except Exception as exc:
                raise ReviewsInternalError() from exc

    def _validate_metric_import(self, request: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(request, Mapping):
            raise ReviewsInvalidRequest("request must be an object")
        post_id = _require_public_id(request.get("publicPostId"), "publicPostId")
        window = request.get("reviewWindow")
        if window not in METRIC_WINDOWS:
            raise ReviewsInvalidRequest("reviewWindow is invalid")
        source_type = request.get("sourceType")
        if source_type not in METRIC_SOURCES:
            raise ReviewsInvalidRequest("sourceType is invalid")
        values = request.get("values")
        if not isinstance(values, Mapping):
            raise ReviewsInvalidRequest("values must be an object")
        if not values:
            raise ReviewsInvalidRequest("values must contain at least one metric")
        normalized_values: dict[str, Any] = {}
        for key, value in values.items():
            if not isinstance(key, str) or not key.strip():
                raise ReviewsInvalidRequest("metric keys must be non-empty strings")
            key = key.strip()
            if key in normalized_values:
                raise ReviewsInvalidRequest("metric keys must be unique")
            if isinstance(value, (list, tuple, dict)) or value is None or isinstance(value, bool):
                raise ReviewsUnprocessable(f"values.{key} must be numeric")
            normalized_values[key] = value
        evidence_refs = request.get("evidenceRefs")
        if not isinstance(evidence_refs, list) or not evidence_refs:
            raise ReviewsUnprocessable("evidenceRefs must contain at least one item")
        clean_evidence = []
        for index, evidence in enumerate(evidence_refs):
            if not isinstance(evidence, Mapping):
                raise ReviewsInvalidRequest(f"evidenceRefs[{index}] must be an object")
            kind = evidence.get("kind")
            label = evidence.get("label")
            quality = evidence.get("qualityStatus")
            if not isinstance(kind, str) or not kind.strip():
                raise ReviewsInvalidRequest(f"evidenceRefs[{index}].kind is required")
            if not isinstance(label, str) or not label.strip():
                raise ReviewsInvalidRequest(f"evidenceRefs[{index}].label is required")
            if quality not in EVIDENCE_QUALITY:
                raise ReviewsInvalidRequest(f"evidenceRefs[{index}].qualityStatus is invalid")
            captured_at = _parse_timestamp(evidence.get("capturedAt"), f"evidenceRefs[{index}].capturedAt")
            public_url = evidence.get("publicUrl")
            if public_url is not None and not isinstance(public_url, str):
                raise ReviewsInvalidRequest(f"evidenceRefs[{index}].publicUrl is invalid")
            clean_evidence.append(
                {
                    "kind": kind.strip(),
                    "label": label.strip(),
                    "publicUrl": public_url,
                    "capturedAt": captured_at,
                    "qualityStatus": quality,
                }
            )
        return {
            "publicPostId": post_id,
            "reviewWindow": window,
            "sourceType": source_type,
            "values": normalized_values,
            "evidenceRefs": clean_evidence,
        }

    def _evidence_summary(self, evidence_refs: list[Mapping[str, Any]]) -> tuple[str, str]:
        quality = max(
            (str(item["qualityStatus"]) for item in evidence_refs),
            key=lambda item: _QUALITY_RANK[item],
        )
        collected_at = max(
            (str(item["capturedAt"]) for item in evidence_refs),
            key=lambda value: datetime.fromisoformat(value.replace("Z", "+00:00")),
        )
        return collected_at, quality

    def _published_post(
        self,
        connection: DatabaseConnection,
        context: TenantContext,
        public_post_id: str,
    ) -> tuple[str, int, dict[str, Any]]:
        row = _fetchone(
            connection.execute(
                """
                SELECT public_id, revision, canonical_data, updated_at
                FROM media_product.published_posts
                WHERE tenant_id = %s AND public_id = %s
                """,
                (context.tenant_id, public_post_id),
            )
        )
        if row is None:
            raise ReviewsNotFound()
        return _row_parts(row, "published post")[:3]

    def _existing_review(
        self,
        connection: DatabaseConnection,
        context: TenantContext,
        public_post_id: str,
    ) -> tuple[str, int, dict[str, Any], Any] | None:
        row = _fetchone(
            connection.execute(
                """
                SELECT public_id, revision, canonical_data, updated_at
                FROM media_product.review_records
                WHERE tenant_id = %s
                  AND canonical_data->>'public_post_id' = %s
                ORDER BY revision DESC
                LIMIT 1
                """,
                (context.tenant_id, public_post_id),
            )
        )
        return None if row is None else _row_parts(row, "review")

    def _content_metric_facts(
        self,
        connection: DatabaseConnection,
        context: TenantContext,
        public_post_id: str,
    ) -> dict[str, list[dict[str, Any]]]:
        rows = _fetchall(
            connection.execute(
                """
                SELECT public_id, revision, canonical_data, updated_at
                FROM media_product.metric_snapshots
                WHERE tenant_id = %s
                  AND canonical_data->>'subject_type' = 'content'
                  AND canonical_data->>'public_subject_id' = %s
                  AND canonical_data->>'review_window' IN ('24h', '7d')
                """,
                (context.tenant_id, public_post_id),
            )
        )
        facts: dict[str, list[dict[str, Any]]] = {"24h": [], "7d": []}
        for row in rows:
            public_id, _, data, _ = _row_parts(row, "metric")
            projection = self._metric_projection(public_id, data, "content")
            if projection["reviewWindow"] in facts:
                facts[projection["reviewWindow"]].append(projection)
        for window in facts:
            facts[window].sort(
                key=lambda item: (
                    datetime.fromisoformat(item["collectedAt"].replace("Z", "+00:00")),
                    item["publicSnapshotId"],
                ),
                reverse=True,
            )
        return facts

    def _review_evidence_quality(
        self,
        facts: Mapping[str, list[Mapping[str, Any]]],
    ) -> str:
        qualities = [
            str(item["evidenceQuality"])
            for window in ("24h", "7d")
            for item in facts.get(window, [])
        ]
        return (
            max(qualities, key=lambda item: _QUALITY_RANK[item])
            if qualities
            else "unavailable"
        )

    def _review_facts_from_data(
        self,
        data: Mapping[str, Any],
    ) -> dict[str, list[dict[str, Any]]]:
        stored = _value(data, "metric_facts", "metricFacts", default={})
        if not isinstance(stored, Mapping):
            return {"24h": [], "7d": []}
        facts: dict[str, list[dict[str, Any]]] = {"24h": [], "7d": []}
        for window in facts:
            values = stored.get(window)
            if isinstance(values, list):
                facts[window] = [
                    dict(item)
                    for item in values
                    if isinstance(item, Mapping)
                ]
        return facts

    def _readback_review(
        self,
        connection: DatabaseConnection,
        context: TenantContext,
        public_review_id: str,
        expected_revision: int,
    ) -> tuple[str, int, dict[str, Any], Any]:
        row = _fetchone(
            connection.execute(
                """
                SELECT public_id, revision, canonical_data, updated_at
                FROM media_product.review_records
                WHERE tenant_id = %s AND public_id = %s
                """,
                (context.tenant_id, public_review_id),
            )
        )
        if row is None:
            raise ReviewsInternalError("review write was not readable")
        readback = _row_parts(row, "review")
        if readback[0] != public_review_id or readback[1] != expected_revision:
            raise ReviewsInternalError("review write returned an unexpected revision")
        return readback

    def _readback_artifact(
        self,
        connection: DatabaseConnection,
        context: TenantContext,
        artifact_id: str,
        project_id: str,
        expected_revision: int,
    ) -> dict[str, Any]:
        row = _fetchone(
            connection.execute(
                """
                SELECT public_id, public_project_id, artifact_kind, body_authority,
                       current_revision, updated_at
                FROM media_product.document_artifacts
                WHERE tenant_id = %s AND public_id = %s
                """,
                (context.tenant_id, artifact_id),
            )
        )
        if row is None:
            raise ReviewsInternalError("artifact write was not readable")
        if isinstance(row, Mapping):
            values = [
                row.get("public_id"),
                row.get("public_project_id"),
                row.get("artifact_kind"),
                row.get("body_authority"),
                row.get("current_revision"),
                row.get("updated_at"),
            ]
        else:
            values = list(row)
        if len(values) < 6:
            raise ReviewsInternalError("artifact readback row is malformed")
        readback_id, readback_project, kind, authority, revision, updated_at = values[:6]
        if readback_id != artifact_id or readback_project != project_id:
            raise ReviewsInternalError("artifact write returned an unexpected identity")
        if kind != "review_report" or authority != "internal":
            raise ReviewsInternalError("artifact write returned an unexpected type")
        if isinstance(revision, bool) or not isinstance(revision, int) or revision != expected_revision:
            raise ReviewsInternalError("artifact write returned an unexpected revision")
        return _artifact_summary(
            artifact_id,
            project_id,
            revision,
            _timestamp(updated_at),
        )
    def _ensure_artifact(
        self,
        connection: DatabaseConnection,
        context: TenantContext,
        *,
        artifact_id: str,
        project_id: str,
        revision: int,
        updated_at: str,
        create: bool,
    ) -> None:
        if create:
            connection.execute(
                """
                INSERT INTO media_product.document_artifacts
                    (tenant_id, public_id, public_project_id, artifact_kind,
                     workspace_mode, body_authority, current_revision)
                VALUES (%s, %s, %s, 'review_report', 'ordinary', 'internal', %s)
                """,
                (context.tenant_id, artifact_id, project_id, revision),
            )
        else:
            connection.execute(
                """
                UPDATE media_product.document_artifacts
                SET current_revision = %s, updated_at = %s
                WHERE tenant_id = %s AND public_id = %s
                """,
                (revision, updated_at, context.tenant_id, artifact_id),
            )

    def _ensure_revision(
        self,
        connection: DatabaseConnection,
        context: TenantContext,
        *,
        artifact_id: str,
        revision: int,
        actor_public_id: str,
        body: Mapping[str, Any],
    ) -> None:
        checksum = hashlib.sha256(_as_json(body).encode()).hexdigest()
        connection.execute(
            """
            INSERT INTO media_product.document_revisions
                (tenant_id, public_artifact_id, revision, state, base_revision,
                 body_checksum, actor_public_id, generation_source)
            VALUES (%s, %s, %s, 'ready', %s, %s, %s, 'media_growth_review')
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

    def _review_body(
        self,
        public_post_id: str,
        review_window: str,
        reason: str,
        facts: Mapping[str, list[Mapping[str, Any]]],
        model_suggestion: str | None,
        human_decision: str | None,
        decision_reason: str | None = None,
    ) -> dict[str, Any]:
        return {
            "schemaVersion": "media.document.body.v1",
            "blocks": [
                {
                    "id": f"b07_{public_post_id}_heading",
                    "type": "heading_1",
                    "attrs": {},
                    "content": [{"type": "text", "text": f"{review_window} 发布复盘", "marks": []}],
                },
                {
                    "id": f"b07_{public_post_id}_reason",
                    "type": "paragraph",
                    "attrs": {},
                    "content": [{"type": "text", "text": reason, "marks": []}],
                },
            ],
            "sourceFacts": {
                "publicPostId": public_post_id,
                "windows": {
                    window: [dict(item) for item in facts.get(window, [])]
                    for window in ("24h", "7d")
                },
            },
            "modelOutput": {"suggestion": model_suggestion},
            "humanDecision": (
                None
                if human_decision is None
                else {"decision": human_decision, "reason": decision_reason}
            ),
        }

    def create_review(
        self,
        context: TenantContext,
        request: Mapping[str, Any],
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        context = self._context(context)
        normalized = self._validate_review_request(request)
        with self._connection_factory() as connection:
            try:
                replay = self._load_idempotent(connection, context, "createReview", idempotency_key, normalized)
                if replay is not None:
                    return public_projection(replay)
                post_id = normalized["publicPostId"]
                _, _, post_data = self._published_post(connection, context, post_id)
                existing = self._existing_review(connection, context, post_id)
                if existing is not None:
                    review_id, current_revision, current_data, _ = existing
                    if normalized["expectedRevision"] != current_revision:
                        raise ReviewsConflict()
                    revision = current_revision + 1
                    artifact_id = _require_public_id(
                        _value(current_data, "public_artifact_id", "publicArtifactId"),
                        "publicArtifactId",
                    )
                    create_artifact = False
                else:
                    if normalized["expectedRevision"] != 0:
                        raise ReviewsConflict()
                    review_id = self._id_factory("review")
                    revision = 1
                    artifact_id = self._id_factory("artifact")
                    create_artifact = True
                    current_data = {}
                platform = _value(post_data, "platform")
                project_id = _value(post_data, "public_project_id", "publicProjectId")
                if not isinstance(platform, str) or not platform:
                    raise ReviewsUnprocessable("published post platform is missing")
                if not isinstance(project_id, str) or not PUBLIC_ID_PATTERN.fullmatch(project_id):
                    raise ReviewsUnprocessable("published post project is missing")
                now = self._now()
                facts = self._content_metric_facts(connection, context, post_id)
                snapshot24h = facts["24h"][0]["publicSnapshotId"] if facts["24h"] else None
                snapshot7d = facts["7d"][0]["publicSnapshotId"] if facts["7d"] else None
                model_suggestion = _value(current_data, "model_suggestion", "modelSuggestion")
                if model_suggestion is not None and not isinstance(model_suggestion, str):
                    raise ReviewsInternalError("stored model suggestion is invalid")
                review_data = dict(current_data)
                review_data.update(
                    {
                        "public_post_id": post_id,
                        "platform": platform,
                        "review_window": normalized["reviewWindow"],
                        "snapshot_24h": snapshot24h,
                        "snapshot_7d": snapshot7d,
                        "metric_facts": facts,
                        "evidence_quality": self._review_evidence_quality(facts),
                        "model_suggestion": model_suggestion,
                        "human_decision": None,
                        "status": "pending",
                        "reason": normalized["reason"],
                        "public_artifact_id": artifact_id,
                        "public_project_id": project_id,
                    }
                )
                if existing is None:
                    connection.execute(
                        """
                        INSERT INTO media_product.review_records
                            (tenant_id, public_id, revision, canonical_data)
                        VALUES (%s, %s, %s, CAST(%s AS jsonb))
                        """,
                        (context.tenant_id, review_id, revision, _as_json(review_data)),
                    )
                else:
                    connection.execute(
                        """
                        UPDATE media_product.review_records
                        SET revision = %s, canonical_data = CAST(%s AS jsonb), updated_at = %s
                        WHERE tenant_id = %s AND public_id = %s
                        """,
                        (revision, _as_json(review_data), now, context.tenant_id, review_id),
                    )
                self._ensure_artifact(
                    connection,
                    context,
                    artifact_id=artifact_id,
                    project_id=project_id,
                    revision=revision,
                    updated_at=now,
                    create=create_artifact,
                )
                self._ensure_revision(
                    connection,
                    context,
                    artifact_id=artifact_id,
                    revision=revision,
                    actor_public_id=context.user_public_id,
                    body=self._review_body(
                        post_id,
                        normalized["reviewWindow"],
                        normalized["reason"],
                        facts,
                        model_suggestion,
                        None,
                    ),
                )
                readback_review = self._readback_review(connection, context, review_id, revision)
                artifact_summary = self._readback_artifact(
                    connection, context, artifact_id, project_id, revision
                )
                response = {
                    "schemaVersion": SCHEMA_VERSION,
                    "revision": readback_review[1],
                    "item": artifact_summary,
                }
                self._store_idempotent(connection, context, "createReview", idempotency_key, normalized, response)
                self._commit(connection)
                return public_projection(response)
            except ReviewsError:
                raise
            except Exception as exc:
                raise ReviewsInternalError() from exc

    def _validate_review_request(self, request: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(request, Mapping):
            raise ReviewsInvalidRequest("request must be an object")
        post_id = _require_public_id(request.get("publicPostId"), "publicPostId")
        expected = request.get("expectedRevision")
        if isinstance(expected, bool) or not isinstance(expected, int) or expected < 0:
            raise ReviewsInvalidRequest("expectedRevision is invalid")
        window = request.get("reviewWindow")
        if window not in REVIEW_WINDOWS:
            raise ReviewsInvalidRequest("reviewWindow is invalid")
        reason = request.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise ReviewsInvalidRequest("reason is required")
        return {
            "publicPostId": post_id,
            "expectedRevision": expected,
            "reviewWindow": window,
            "reason": reason.strip(),
        }

    def confirm_review(
        self,
        context: TenantContext,
        public_review_id: str,
        request: Mapping[str, Any],
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        context = self._context(context)
        review_id = _require_public_id(public_review_id, "publicReviewId")
        normalized = self._validate_confirmation(request)
        idempotent_request = dict(normalized)
        idempotent_request["publicReviewId"] = review_id
        with self._connection_factory() as connection:
            try:
                replay = self._load_idempotent(
                    connection, context, "confirmReview", idempotency_key, idempotent_request
                )
                if replay is not None:
                    return public_projection(replay)
                row = _fetchone(
                    connection.execute(
                        """
                        SELECT public_id, revision, canonical_data, updated_at
                        FROM media_product.review_records
                        WHERE tenant_id = %s AND public_id = %s
                        """,
                        (context.tenant_id, review_id),
                    )
                )
                if row is None:
                    raise ReviewsNotFound()
                stored_id, current_revision, data, _ = _row_parts(row, "review")
                if normalized["expectedRevision"] != current_revision:
                    raise ReviewsConflict()
                artifact_id = _require_public_id(
                    _value(data, "public_artifact_id", "publicArtifactId"),
                    "publicArtifactId",
                )
                project_id = _require_public_id(
                    _value(data, "public_project_id", "publicProjectId"),
                    "publicProjectId",
                )
                revision = current_revision + 1
                now = self._now()
                updated = dict(data)
                post_id = _require_public_id(
                    _value(updated, "public_post_id", "publicPostId"), "publicPostId"
                )
                facts = self._content_metric_facts(connection, context, post_id)
                if not any(facts.values()):
                    facts = self._review_facts_from_data(data)
                updated.update(
                    {
                        "human_decision": normalized["humanDecision"],
                        "human_decision_reason": normalized["reason"],
                        "metric_facts": facts,
                        "status": "confirmed",
                        "confirmed_at": now,
                    }
                )
                connection.execute(
                    """
                    UPDATE media_product.review_records
                    SET revision = %s, canonical_data = CAST(%s AS jsonb), updated_at = %s
                    WHERE tenant_id = %s AND public_id = %s
                    """,
                    (revision, _as_json(updated), now, context.tenant_id, stored_id),
                )
                self._ensure_artifact(
                    connection,
                    context,
                    artifact_id=artifact_id,
                    project_id=project_id,
                    revision=revision,
                    updated_at=now,
                    create=False,
                )
                self._ensure_revision(
                    connection,
                    context,
                    artifact_id=artifact_id,
                    revision=revision,
                    actor_public_id=context.user_public_id,
                    body=self._review_body(
                        post_id,
                        str(_value(updated, "review_window", "reviewWindow", default="7d")),
                        normalized["reason"],
                        facts,
                        _value(updated, "model_suggestion", "modelSuggestion"),
                        normalized["humanDecision"],
                        normalized["reason"],
                    ),
                )
                readback_review = self._readback_review(connection, context, stored_id, revision)
                artifact_summary = self._readback_artifact(
                    connection, context, artifact_id, project_id, revision
                )
                response = {
                    "schemaVersion": SCHEMA_VERSION,
                    "revision": readback_review[1],
                    "item": artifact_summary,
                }
                self._store_idempotent(
                    connection, context, "confirmReview", idempotency_key, idempotent_request, response
                )
                self._commit(connection)
                return public_projection(response)
            except ReviewsError:
                raise
            except Exception as exc:
                raise ReviewsInternalError() from exc

    def _validate_confirmation(self, request: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(request, Mapping):
            raise ReviewsInvalidRequest("request must be an object")
        expected = request.get("expectedRevision")
        if isinstance(expected, bool) or not isinstance(expected, int) or expected < 0:
            raise ReviewsInvalidRequest("expectedRevision is invalid")
        decision = request.get("humanDecision")
        reason = request.get("reason")
        if not isinstance(decision, str) or not decision.strip():
            raise ReviewsInvalidRequest("humanDecision is required")
        if not isinstance(reason, str) or not reason.strip():
            raise ReviewsInvalidRequest("reason is required")
        return {
            "expectedRevision": expected,
            "humanDecision": decision.strip(),
            "reason": reason.strip(),
        }


def _metric_revision(row: Any) -> int:
    if isinstance(row, Mapping):
        value = row.get("revision", 0)
    else:
        value = row[1] if len(row) > 1 else 0
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


__all__ = [
    "ReviewsConflict",
    "ReviewsError",
    "ReviewsForbidden",
    "ReviewsInternalError",
    "ReviewsInvalidRequest",
    "ReviewsNotFound",
    "ReviewsService",
    "ReviewsUnprocessable",
]
