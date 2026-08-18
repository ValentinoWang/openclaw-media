"""Tenant-scoped PostgreSQL read model for the B03 assets page."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import tempfile
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from threading import BoundedSemaphore, Lock
from typing import Any, Callable, Mapping, Protocol
from urllib.parse import urlsplit

from .foundation import MediaBusinessError, TenantContext, public_projection, require_context


SCHEMA_VERSION = "media_web_business_pages_v2"
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100
PREVIEW_PROVIDER_CONCURRENCY = 4
PREVIEW_CACHE_MAX_ENTRIES = 512
PREVIEW_CACHE_MAX_FILE_BYTES = 10 * 1024 * 1024 + 1024
PREVIEW_CACHE_VERSION = "thumbnail-webp-320x180-v1"
PREVIEW_THUMBNAIL_SIZE = (320, 180)
PREVIEW_THUMBNAIL_MAX_BYTES = 256 * 1024
PREVIEW_SOURCE_MAX_PIXELS = 25_000_000
_PUBLIC_ID = re.compile(r"^[A-Za-z0-9_-]{8,160}$")
_SAME_ORIGIN_PREVIEW_URL = re.compile(r"^/openclaw/media/api/assets/[A-Za-z0-9_-]{8,160}/preview$")
_QUALITY_STATUSES = {"verified", "partial", "unverified", "unavailable"}


class AssetsError(MediaBusinessError):
    status = 500
    field: str | None = None

    def __init__(self, code: str, message: str, *, status: int, field: str | None = None) -> None:
        super().__init__(code, message)
        self.status = status
        self.field = field


class AssetInvalidRequest(AssetsError):
    def __init__(self, message: str, *, field: str | None = None) -> None:
        super().__init__("invalid_request", message, status=400, field=field)


class AssetForbidden(AssetsError):
    def __init__(self, message: str = "asset data is not available for this session") -> None:
        super().__init__("forbidden", message, status=403)


class AssetNotFound(AssetsError):
    def __init__(self, message: str = "asset not found") -> None:
        super().__init__("resource_not_found", message, status=404)


class AssetInternalError(AssetsError):
    def __init__(self, message: str = "asset data is unavailable") -> None:
        super().__init__("internal_error", message, status=500)


@dataclass(frozen=True)
class AssetPreview:
    body: bytes
    content_type: str
    filename: str


class DatabaseConnection(Protocol):
    def execute(self, query: str, params: tuple[Any, ...] = ()) -> Any: ...


ConnectionFactory = Callable[[], AbstractContextManager[DatabaseConnection]]


@dataclass(frozen=True)
class AssetCursor:
    created_at: datetime
    public_asset_id: str


class AssetsService:
    """Read canonical asset facts and their explicit B03 relationships."""

    _STATE_QUERY = """
        SELECT COUNT(*)::bigint,
               COALESCE(MAX(a.revision), 0),
               MAX(a.updated_at)
        FROM media_product.assets AS a
        WHERE a.tenant_id = %s
    """

    _LIST_QUERY = """
        SELECT a.public_id,
               a.revision,
               a.canonical_data,
               a.created_at,
               a.updated_at,
               (
                 SELECT COUNT(*)::bigint
                 FROM media_product.material_usages AS u
                 WHERE u.tenant_id = a.tenant_id
                   AND u.canonical_data->>'asset_id' = a.public_id
               ) AS usage_count
        FROM media_product.assets AS a
        WHERE a.tenant_id = %s
          AND (
            %s = ''
            OR a.public_id ILIKE %s ESCAPE '\\'
            OR COALESCE(a.canonical_data::text, '') ILIKE %s ESCAPE '\\'
          )
          AND (
            CAST(%s AS timestamptz) IS NULL
            OR a.created_at < %s
            OR (a.created_at = %s AND a.public_id > %s)
          )
        ORDER BY a.created_at DESC, a.public_id ASC
        LIMIT %s
    """

    _DETAIL_QUERY = """
        SELECT a.public_id,
               a.revision,
               a.canonical_data,
               a.created_at,
               a.updated_at,
               (
                 SELECT COUNT(*)::bigint
                 FROM media_product.material_usages AS u
                 WHERE u.tenant_id = a.tenant_id
                   AND u.canonical_data->>'asset_id' = a.public_id
               ) AS usage_count
        FROM media_product.assets AS a
        WHERE a.tenant_id = %s
          AND a.public_id = %s
    """

    _DECONSTRUCTION_QUERY = """
        SELECT d.public_id, d.revision, d.canonical_data, d.created_at
        FROM media_product.material_deconstructions AS d
        WHERE d.tenant_id = %s
          AND d.canonical_data->>'asset_id' = %s
        ORDER BY d.created_at DESC, d.public_id ASC
    """

    _PATTERN_QUERY = """
        SELECT p.public_id, p.revision, p.canonical_data, p.created_at
        FROM media_product.creative_patterns AS p
        WHERE p.tenant_id = %s
          AND p.canonical_data->'supporting_asset_ids' @> jsonb_build_array(%s::text)
        ORDER BY p.created_at DESC, p.public_id ASC
    """

    _USAGE_QUERY = """
        SELECT u.public_id
        FROM media_product.material_usages AS u
        WHERE u.tenant_id = %s
          AND u.canonical_data->>'asset_id' = %s
        ORDER BY u.created_at DESC, u.public_id ASC
    """

    def __init__(self, connection_factory: ConnectionFactory, *, cursor_secret: bytes) -> None:
        if len(cursor_secret) < 16:
            raise ValueError("B03 cursor secret must be at least 16 bytes")
        self._connection_factory = connection_factory
        self._cursor_key = hashlib.sha256(bytes(cursor_secret)).digest()

    def list_assets(
        self,
        context: TenantContext,
        *,
        cursor: str | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
        search: str | None = None,
    ) -> dict[str, Any]:
        tenant_id = self._tenant_id(context)
        size = _page_size(page_size)
        normalized_search = _search(search)
        position = self._decode_cursor(cursor, tenant_id) if cursor else None
        search_pattern = _search_pattern(normalized_search)

        try:
            with self._connection_factory() as connection:
                state = connection.execute(self._STATE_QUERY, (tenant_id,)).fetchone()
                rows = connection.execute(
                    self._LIST_QUERY,
                    self._list_params(tenant_id, normalized_search, search_pattern, position, size),
                ).fetchall()
        except AssetsError:
            raise
        except Exception as exc:
            raise AssetInternalError() from exc

        count, max_revision, latest_updated_at = self._state_row(state)
        if not isinstance(rows, list):
            rows = list(rows)
        has_next = len(rows) > size
        visible_rows = rows[:size]
        items = [self._summary_from_row(row) for row in visible_rows]
        next_cursor = None
        if has_next:
            last = visible_rows[-1]
            next_cursor = self._encode_cursor(
                tenant_id,
                AssetCursor(
                    created_at=_timestamp_value(last[3]),
                    public_asset_id=_public_id(last[0]),
                ),
            )

        response = {
            "schemaVersion": SCHEMA_VERSION,
            "revision": _list_revision(count, max_revision, latest_updated_at),
            "items": items,
            "nextCursor": next_cursor,
        }
        return public_projection(response)

    def get_asset(self, context: TenantContext, public_asset_id: str) -> dict[str, Any]:
        tenant_id = self._tenant_id(context)
        asset_id = _request_public_id(public_asset_id)
        try:
            with self._connection_factory() as connection:
                row = connection.execute(self._DETAIL_QUERY, (tenant_id, asset_id)).fetchone()
                if row is None:
                    raise AssetNotFound()
                deconstructions = connection.execute(
                    self._DECONSTRUCTION_QUERY,
                    (tenant_id, asset_id),
                ).fetchall()
                patterns = connection.execute(
                    self._PATTERN_QUERY,
                    (tenant_id, asset_id),
                ).fetchall()
                usage_rows = connection.execute(
                    self._USAGE_QUERY,
                    (tenant_id, asset_id),
                ).fetchall()
        except AssetsError:
            raise
        except Exception as exc:
            raise AssetInternalError() from exc

        summary = self._summary_from_row(row)
        detail = {
            "summary": summary,
            "evidenceRefs": self._evidence_refs(row[2], row[3]),
            "previewDescriptor": self._preview_descriptor(row[2]),
            "deconstructions": [self._deconstruction_projection(item) for item in deconstructions],
            "creativePatterns": [self._pattern_projection(item) for item in patterns],
            "usageRefs": [_public_id(item[0]) for item in usage_rows],
            "revision": _positive_revision(row[1]),
        }
        return public_projection(
            {
                "schemaVersion": SCHEMA_VERSION,
                "revision": detail["revision"],
                "item": detail,
            }
        )

    @staticmethod
    def error_response(error: BaseException) -> dict[str, Any]:
        if isinstance(error, AssetsError):
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
                "message": "asset data is unavailable",
                "field": None,
            }
        }

    @staticmethod
    def error_status(error: BaseException) -> int:
        return error.status if isinstance(error, AssetsError) else 500

    def _tenant_id(self, context: TenantContext | None) -> str:
        try:
            checked = require_context(context)
        except Exception as exc:
            raise AssetForbidden() from exc
        tenant_id = str(checked.tenant_id).strip()
        if not tenant_id:
            raise AssetForbidden()
        return tenant_id

    @staticmethod
    def _state_row(row: Any) -> tuple[int, int, Any]:
        if not isinstance(row, (tuple, list)) or len(row) != 3:
            raise AssetInternalError("asset state row shape is invalid")
        count, max_revision, latest_updated_at = row
        if type(count) is not int or count < 0:
            raise AssetInternalError("asset count is invalid")
        return count, _nonnegative_revision(max_revision), latest_updated_at

    @staticmethod
    def _list_params(
        tenant_id: str,
        search_term: str,
        search_pattern: str,
        position: AssetCursor | None,
        size: int,
    ) -> tuple[Any, ...]:
        if position is None:
            return (tenant_id, search_term, search_pattern, search_pattern, None, None, None, "", size + 1)
        return (
            tenant_id,
            search_term,
            search_pattern,
            search_pattern,
            position.created_at,
            position.created_at,
            position.created_at,
            position.public_asset_id,
            size + 1,
        )

    def _encode_cursor(self, tenant_id: str, cursor: AssetCursor) -> str:
        payload = json.dumps(
            {
                "createdAt": _timestamp_text(cursor.created_at),
                "publicAssetId": cursor.public_asset_id,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        signed = hmac.new(self._cursor_key, tenant_id.encode("utf-8") + b"|" + payload, hashlib.sha256).digest()[:18]
        return f"{_b64_encode(payload)}.{_b64_encode(signed)}"

    def _decode_cursor(self, token: str, tenant_id: str) -> AssetCursor:
        if not isinstance(token, str) or not token or token.count(".") != 1:
            raise AssetInvalidRequest("cursor is invalid", field="cursor")
        payload_text, signature_text = token.split(".", 1)
        try:
            payload = _b64_decode(payload_text)
            signature = _b64_decode(signature_text)
            expected = hmac.new(
                self._cursor_key,
                tenant_id.encode("utf-8") + b"|" + payload,
                hashlib.sha256,
            ).digest()[:18]
            if not hmac.compare_digest(signature, expected):
                raise ValueError("signature mismatch")
            data = json.loads(payload.decode("utf-8"))
            return AssetCursor(
                created_at=_timestamp_value(data["createdAt"]),
                public_asset_id=_public_id(data["publicAssetId"]),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise AssetInvalidRequest("cursor is invalid", field="cursor") from exc

    @staticmethod
    def _summary_from_row(row: Any) -> dict[str, Any]:
        if not isinstance(row, (tuple, list)) or len(row) != 6:
            raise AssetInternalError("asset row shape is invalid")
        public_id, revision, canonical_data, created_at, _updated_at, usage_count = row
        data = _object(canonical_data, "asset canonical data")
        summary = {
            "publicAssetId": _public_id(public_id),
            "title": _text(data, "title"),
            "mediaType": _text(data, "mediaType"),
            "platform": _text(data, "platform"),
            "sourceLabel": _text(data, "sourceLabel"),
            "platformHashtags": _string_list(data, "platform_hashtags"),
            "trackNames": _string_list(data, "trackNames"),
            "qualityStatus": _text(data, "qualityStatus"),
            "materialStatus": _text(data, "materialStatus"),
            "createdAt": _timestamp_text(created_at),
            "usageCount": _count(usage_count),
            "thumbnail": AssetsService._thumbnail_descriptor(data),
        }
        _positive_revision(revision)
        return summary

    @staticmethod
    def _evidence_refs(canonical_data: Any, created_at: Any) -> list[dict[str, Any]]:
        data = _object(canonical_data, "asset canonical data")
        raw_refs = data.get("evidenceRefs")
        if raw_refs is not None:
            if not isinstance(raw_refs, list):
                raise AssetInternalError("asset evidence refs are invalid")
            return [_evidence_ref(item) for item in raw_refs]
        source_url = data.get("source_url")
        if source_url is None:
            return []
        if not isinstance(source_url, str) or not source_url.strip():
            raise AssetInternalError("asset source url is invalid")
        return [
            {
                "kind": "source",
                "label": _text(data, "sourceLabel"),
                "publicUrl": _public_url(source_url),
                "capturedAt": _timestamp_text(created_at),
                "qualityStatus": "partial",
            }
        ]

    @staticmethod
    def _preview_descriptor(canonical_data: Any) -> dict[str, Any]:
        data = _object(canonical_data, "asset canonical data")
        preview = data.get("preview")
        if preview is None:
            return {"status": "unavailable"}
        if not isinstance(preview, dict):
            raise AssetInternalError("asset preview descriptor is invalid")
        result: dict[str, Any] = {}
        for key in ("kind", "status"):
            if key in preview:
                value = preview[key]
                if not isinstance(value, str) or not value.strip():
                    raise AssetInternalError("asset preview descriptor is invalid")
                result[key] = value
        if "url" in preview:
            result["url"] = _public_url(preview["url"])
        if not result.get("url"):
            result["status"] = "unavailable"
        return result or {"status": "unavailable"}

    @staticmethod
    def _thumbnail_descriptor(canonical_data: Any) -> dict[str, Any]:
        preview = AssetsService._preview_descriptor(canonical_data)
        result = {key: preview[key] for key in ("url", "kind", "status") if key in preview}
        return result or {"status": "unavailable"}

    @staticmethod
    def _deconstruction_projection(row: Any) -> dict[str, Any]:
        if not isinstance(row, (tuple, list)) or len(row) != 4:
            raise AssetInternalError("deconstruction row shape is invalid")
        public_id, revision, canonical_data, created_at = row
        data = _object(canonical_data, "deconstruction canonical data")
        result: dict[str, Any] = {
            "publicDeconstructionId": _public_id(public_id),
            "revision": _positive_revision(revision),
            "createdAt": _timestamp_text(created_at),
        }
        for output_key, source_key in (
            ("analysisScope", "analysis_scope"),
            ("analysisTimeRange", "analysis_time_range"),
            ("focus", "deconstruction_focus"),
            ("summary", "summary"),
            ("hook", "hook"),
            ("reviewStatus", "review_status"),
        ):
            if source_key in data:
                result[output_key] = _value(data[source_key], source_key)
        return result

    @staticmethod
    def _pattern_projection(row: Any) -> dict[str, Any]:
        if not isinstance(row, (tuple, list)) or len(row) != 4:
            raise AssetInternalError("creative pattern row shape is invalid")
        public_id, revision, canonical_data, created_at = row
        data = _object(canonical_data, "creative pattern canonical data")
        result: dict[str, Any] = {
            "publicPatternId": _public_id(public_id),
            "revision": _positive_revision(revision),
            "createdAt": _timestamp_text(created_at),
        }
        for output_key, source_key in (
            ("patternName", "pattern_name"),
            ("patternStatus", "pattern_status"),
            ("platform", "platform"),
            ("contentType", "content_type"),
        ):
            if source_key in data:
                result[output_key] = _value(data[source_key], source_key)
        return result


class AssetPreviewService:
    """Read a current Base attachment through an authenticated tenant scope.

    The projection stores only an attachment display selector.  A file token is
    looked up from the current Base record for each preview request, keeping
    expiring ``tmp_url`` values and provider tokens out of the read model and
    public payloads.
    """

    _PREVIEW_QUERY = """
        SELECT a.canonical_data,
               a.source_version
        FROM media_product.assets AS a
        WHERE a.tenant_id = %s
          AND a.public_id = %s
    """

    def __init__(
        self,
        connection_factory: ConnectionFactory,
        feishu_service: Any,
        *,
        base_token: str = "",
        base_token_resolver: Callable[[], str] | None = None,
        cache_root: str | Path | None = None,
    ) -> None:
        if not isinstance(base_token, str):
            raise ValueError("asset preview Base token is invalid")
        if not base_token.strip() and base_token_resolver is None:
            raise ValueError("asset preview Base token is required")
        self._connection_factory = connection_factory
        self._feishu = feishu_service
        self._base_token = base_token.strip()
        self._base_token_resolver = base_token_resolver
        self._base_token_lock = Lock()
        self._provider_slots = BoundedSemaphore(PREVIEW_PROVIDER_CONCURRENCY)
        self._cache_lock = Lock()
        self._cache_root = Path(cache_root) if cache_root is not None else None
        if self._cache_root is not None:
            self._cache_root.mkdir(parents=True, exist_ok=True, mode=0o700)
            self._cache_root.chmod(0o700)

    def get_preview(self, context: TenantContext, public_asset_id: str) -> AssetPreview:
        tenant_id = self._tenant_id(context)
        asset_id = _request_public_id(public_asset_id)
        try:
            with self._connection_factory() as connection:
                row = connection.execute(self._PREVIEW_QUERY, (tenant_id, asset_id)).fetchone()
        except AssetsError:
            raise
        except Exception as exc:
            raise AssetInternalError("asset preview is unavailable") from exc
        if row is None or not isinstance(row, (tuple, list)) or len(row) != 2:
            raise AssetNotFound()

        data = _object(row[0], "asset canonical data")
        source_version = _required_string(row[1], "asset source version")
        source = _object(data.get("source"), "asset preview source")
        preview = _object(data.get("preview"), "asset preview descriptor")
        table_id = _required_string(source.get("table_id"), "asset preview source")
        record_id = _required_string(source.get("record_id"), "asset preview source")
        attachment_name = _required_string(preview.get("attachmentName"), "asset preview descriptor")
        cache_key = self._cache_key(tenant_id, asset_id, source_version, attachment_name)
        cached = self._read_cache(cache_key, attachment_name)
        if cached is not None:
            return cached
        try:
            # Each preview makes several provider requests, so cap the burst
            # without forcing every thumbnail on the page through one lock.
            with self._provider_slots:
                base_token = self._resolved_base_token()
                record = self._feishu.read_bitable_record(base_token, table_id, record_id)
                fields = record.get("fields") if isinstance(record, Mapping) else None
                attachment = _named_cover_attachment(fields, attachment_name)
                token = _required_string(attachment.get("file_token"), "asset preview attachment")
                payload = self._feishu.download_bitable_attachment(base_token, table_id, record_id, token)
            result = _thumbnail_payload(payload, attachment_name)
            self._write_cache(cache_key, result)
            return result
        except AssetInternalError:
            raise
        except Exception as exc:
            # Provider payloads often include tokens and temporary URLs. Never
            # allow them to become response text or a public error field.
            raise AssetInternalError("asset preview is unavailable") from exc

    @staticmethod
    def _cache_key(tenant_id: str, asset_id: str, source_version: str, attachment_name: str) -> str:
        identity = json.dumps(
            [tenant_id, asset_id, source_version, attachment_name],
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("ascii")
        return hashlib.sha256(identity).hexdigest()

    def _read_cache(self, cache_key: str, filename: str) -> AssetPreview | None:
        if self._cache_root is None:
            return None
        path = self._cache_root / f"{cache_key}.preview"
        with self._cache_lock:
            try:
                encoded = path.read_bytes()
            except FileNotFoundError:
                return None
        if not encoded or len(encoded) > PREVIEW_CACHE_MAX_FILE_BYTES:
            raise AssetInternalError("asset preview cache is invalid")
        header, separator, body = encoded.partition(b"\n")
        if not separator or len(header) > 1024:
            raise AssetInternalError("asset preview cache is invalid")
        try:
            metadata = json.loads(header.decode("ascii"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AssetInternalError("asset preview cache is invalid") from exc
        if not isinstance(metadata, Mapping):
            raise AssetInternalError("asset preview cache is invalid")
        preview = _preview_payload({"body": body, "contentType": metadata.get("contentType")}, filename)
        if metadata.get("cacheVersion") == PREVIEW_CACHE_VERSION:
            if (
                metadata.get("width") != PREVIEW_THUMBNAIL_SIZE[0]
                or metadata.get("height") != PREVIEW_THUMBNAIL_SIZE[1]
                or metadata.get("bodySha256") != hashlib.sha256(body).hexdigest()
                or preview.content_type != "image/webp"
                or len(body) > PREVIEW_THUMBNAIL_MAX_BYTES
            ):
                raise AssetInternalError("asset preview cache is invalid")
            return AssetPreview(
                body=body,
                content_type=preview.content_type,
                filename=_thumbnail_filename(filename),
            )

        migrated = _thumbnail_payload(
            {"body": preview.body, "contentType": preview.content_type},
            filename,
        )
        self._write_cache(cache_key, migrated, replace_existing=True)
        return migrated

    def _write_cache(
        self,
        cache_key: str,
        preview: AssetPreview,
        *,
        replace_existing: bool = False,
    ) -> None:
        if self._cache_root is None:
            return
        path = self._cache_root / f"{cache_key}.preview"
        header = json.dumps(
            {
                "bodySha256": hashlib.sha256(preview.body).hexdigest(),
                "cacheVersion": PREVIEW_CACHE_VERSION,
                "contentType": preview.content_type,
                "height": PREVIEW_THUMBNAIL_SIZE[1],
                "width": PREVIEW_THUMBNAIL_SIZE[0],
            },
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
        encoded = header + b"\n" + preview.body
        if len(encoded) > PREVIEW_CACHE_MAX_FILE_BYTES:
            raise AssetInternalError("asset preview cache payload is too large")
        temporary_path: str | None = None
        with self._cache_lock:
            if path.is_file() and not replace_existing:
                return
            try:
                with tempfile.NamedTemporaryFile(
                    mode="wb",
                    dir=self._cache_root,
                    prefix=f".{cache_key}.",
                    delete=False,
                ) as handle:
                    temporary_path = handle.name
                    os.fchmod(handle.fileno(), 0o600)
                    handle.write(encoded)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary_path, path)
                temporary_path = None
                self._trim_cache_locked()
            finally:
                if temporary_path is not None:
                    try:
                        Path(temporary_path).unlink()
                    except FileNotFoundError:
                        pass

    def _trim_cache_locked(self) -> None:
        if self._cache_root is None:
            return
        entries = list(self._cache_root.glob("*.preview"))
        if len(entries) <= PREVIEW_CACHE_MAX_ENTRIES:
            return
        entries.sort(key=lambda entry: entry.stat().st_mtime_ns)
        for entry in entries[: len(entries) - PREVIEW_CACHE_MAX_ENTRIES]:
            entry.unlink()

    @staticmethod
    def _tenant_id(context: TenantContext | None) -> str:
        try:
            checked = require_context(context)
        except Exception as exc:
            raise AssetForbidden() from exc
        tenant_id = str(checked.tenant_id).strip()
        if not tenant_id:
            raise AssetForbidden()
        return tenant_id

    def _resolved_base_token(self) -> str:
        if self._base_token:
            return self._base_token
        with self._base_token_lock:
            if self._base_token:
                return self._base_token
            try:
                resolved = self._base_token_resolver() if self._base_token_resolver is not None else ""
            except Exception as exc:
                raise AssetInternalError("asset preview is unavailable") from exc
            if not isinstance(resolved, str) or not resolved.strip():
                raise AssetInternalError("asset preview is unavailable")
            self._base_token = resolved.strip()
            return self._base_token


def _page_size(value: Any) -> int:
    if type(value) is not int or not 1 <= value <= MAX_PAGE_SIZE:
        raise AssetInvalidRequest("pageSize must be between 1 and 100", field="pageSize")
    return value


def _search(value: Any) -> str:
    if value is None:
        return ""
    if not isinstance(value, str) or len(value) > 160:
        raise AssetInvalidRequest("search is invalid", field="search")
    return value.strip()


def _search_pattern(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _public_id(value: Any) -> str:
    if not isinstance(value, str) or _PUBLIC_ID.fullmatch(value) is None:
        raise AssetInternalError("public asset identifier is invalid")
    return value


def _request_public_id(value: Any) -> str:
    if not isinstance(value, str) or _PUBLIC_ID.fullmatch(value) is None:
        raise AssetInvalidRequest("publicAssetId is invalid", field="publicAssetId")
    return value


def _positive_revision(value: Any) -> int:
    if type(value) is not int or value <= 0:
        raise AssetInternalError("asset revision is invalid")
    return value


def _nonnegative_revision(value: Any) -> int:
    if type(value) is not int or value < 0:
        raise AssetInternalError("asset state revision is invalid")
    return value


def _count(value: Any) -> int:
    if type(value) is not int or value < 0:
        raise AssetInternalError("asset usage count is invalid")
    return value


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AssetInternalError(f"{label} is invalid")
    return value


def _required_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 1024:
        raise AssetInternalError(f"{label} is invalid")
    return value.strip()


def _named_cover_attachment(fields: Any, expected_name: str) -> Mapping[str, Any]:
    if not isinstance(fields, Mapping):
        raise AssetInternalError("asset preview attachment is unavailable")
    values = fields.get("封面附件")
    candidates = values if isinstance(values, list) else [values]
    for candidate in candidates:
        if isinstance(candidate, Mapping) and str(candidate.get("name") or "").strip() == expected_name:
            return candidate
    raise AssetInternalError("asset preview attachment is unavailable")


def _preview_payload(payload: Any, filename: str) -> AssetPreview:
    if not isinstance(payload, Mapping):
        raise AssetInternalError("asset preview is unavailable")
    body = payload.get("body")
    content_type = payload.get("contentType")
    if not isinstance(body, bytes) or not body or len(body) > 10 * 1024 * 1024:
        raise AssetInternalError("asset preview is unavailable")
    if not isinstance(content_type, str) or not content_type.lower().startswith("image/"):
        raise AssetInternalError("asset preview is unavailable")
    return AssetPreview(body=body, content_type=content_type.split(";", 1)[0].strip().lower(), filename=filename)


def _thumbnail_payload(payload: Any, filename: str) -> AssetPreview:
    source = _preview_payload(payload, filename)
    try:
        from PIL import Image, ImageOps
    except ImportError as exc:
        raise AssetInternalError("asset preview image processing is unavailable") from exc

    try:
        with Image.open(BytesIO(source.body)) as image:
            if image.width * image.height > PREVIEW_SOURCE_MAX_PIXELS:
                raise AssetInternalError("asset preview source is too large")
            image.seek(0)
            oriented = ImageOps.exif_transpose(image)
            thumbnail = ImageOps.fit(
                oriented.convert("RGB"),
                PREVIEW_THUMBNAIL_SIZE,
                method=Image.Resampling.LANCZOS,
            )
            output = BytesIO()
            thumbnail.save(output, format="WEBP", quality=80, method=4)
    except AssetInternalError:
        raise
    except (OSError, ValueError, Image.DecompressionBombError) as exc:
        raise AssetInternalError("asset preview image is invalid") from exc
    body = output.getvalue()
    if not body or len(body) > PREVIEW_THUMBNAIL_MAX_BYTES:
        raise AssetInternalError("asset preview thumbnail is invalid")
    return AssetPreview(
        body=body,
        content_type="image/webp",
        filename=_thumbnail_filename(filename),
    )


def _thumbnail_filename(filename: str) -> str:
    stem = Path(filename).stem.strip()
    if not stem:
        raise AssetInternalError("asset preview filename is invalid")
    return f"{stem}.webp"


def _text(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise AssetInternalError(f"asset canonical field {key} is missing")
    return value.strip()


def _string_list(data: dict[str, Any], key: str) -> list[str]:
    value = data.get(key)
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise AssetInternalError(f"asset canonical field {key} is invalid")
    return [item.strip() for item in value]


def _value(value: Any, key: str) -> str | int | float | bool | list[Any] | None:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list) and len(value) <= 100 and all(
        item is None or isinstance(item, (str, int, float, bool)) for item in value
    ):
        return value
    raise AssetInternalError(f"asset canonical field {key} has an unsupported value")


def _public_url(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AssetInternalError("public asset URL is invalid")
    if _SAME_ORIGIN_PREVIEW_URL.fullmatch(value):
        return value
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise AssetInternalError("public asset URL is not controlled")
    return value


def _evidence_ref(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AssetInternalError("asset evidence ref is invalid")
    kind = value.get("kind")
    label = value.get("label")
    quality_status = value.get("qualityStatus")
    if not all(isinstance(item, str) and item.strip() for item in (kind, label, quality_status)):
        raise AssetInternalError("asset evidence ref is invalid")
    if quality_status not in _QUALITY_STATUSES:
        raise AssetInternalError("asset evidence quality is invalid")
    public_url = value.get("publicUrl")
    if public_url is not None:
        public_url = _public_url(public_url)
    captured_at = value.get("capturedAt")
    if captured_at is not None:
        captured_at = _timestamp_text(captured_at)
    return {
        "kind": kind.strip(),
        "label": label.strip(),
        "publicUrl": public_url,
        "capturedAt": captured_at,
        "qualityStatus": quality_status,
    }


def _timestamp_value(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise AssetInternalError("asset timestamp is invalid") from exc
    else:
        raise AssetInternalError("asset timestamp is invalid")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise AssetInternalError("asset timestamp must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _timestamp_text(value: Any) -> str:
    return _timestamp_value(value).isoformat().replace("+00:00", "Z")


def _list_revision(count: int, max_revision: int, latest_updated_at: Any) -> int:
    state = f"{count}|{max_revision}|{_timestamp_text(latest_updated_at) if latest_updated_at is not None else ''}"
    return int(hashlib.sha256(state.encode("utf-8")).hexdigest()[:12], 16)


def _b64_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64_decode(value: str) -> bytes:
    if not value or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise ValueError("invalid base64url")
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
