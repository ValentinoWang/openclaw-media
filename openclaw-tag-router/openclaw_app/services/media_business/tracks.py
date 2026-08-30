"""Tenant-scoped PostgreSQL read models for the B02 tracks page."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import math
import os
import re
from uuid import uuid4
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Protocol
from urllib.parse import urlsplit

from common.platform_links import classify_post_link

from . import foundation, sql_pagination
from .foundation import IF2_KEY, MediaBusinessError, TenantContext, idempotency_key, public_projection


SCHEMA_VERSION = "media_web_business_pages_v2"
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100
_PUBLIC_ID = re.compile(r"^[A-Za-z0-9_-]{8,160}$")
_QUALITY_STATUSES = {"verified", "partial", "unverified", "unavailable"}
_HUMAN_STATUSES = {"pending", "confirmed", "rejected"}
_OPERATIONAL_STATUSES = {"active", "paused", "disabled"}


TracksError = MediaBusinessError


class TrackInvalidRequest(TracksError):
    def __init__(self, message: str, *, field: str | None = None) -> None:
        super().__init__(foundation.INVALID_REQUEST, message, status=400, field=field)


class TrackForbidden(foundation.Forbidden):
    def __init__(self, message: str = "track data is not available for this session") -> None:
        super().__init__(message)


class TrackNotFound(foundation.NotFound):
    pass


class TrackConflict(foundation.Conflict):
    def __init__(self, message: str = "track relationship revision conflict") -> None:
        super().__init__(message)


class TrackInternalError(foundation.InternalError):
    def __init__(self, message: str = "track data is unavailable") -> None:
        super().__init__(message)


class TrackMonitorUnavailable(TracksError):
    """The account monitor adapter is not installed in this runtime."""

    def __init__(self, message: str = "account monitor is unavailable") -> None:
        super().__init__("monitor_unavailable", message, status=503)


class AccountMonitorAdapter(Protocol):
    def get(self, context: TenantContext, public_account_id: str) -> dict[str, Any]: ...
    def update(self, context: TenantContext, public_account_id: str, recent_post_urls: list[str], enabled: bool) -> dict[str, Any]: ...
    def poll(self, context: TenantContext, public_account_id: str) -> dict[str, Any]: ...


class H00AccountMonitorAdapter:
    """Thin boundary around the existing H00 Feishu and daily-poll helpers."""

    def __init__(self, monitor_url: str, *, view_id: str = "", binding_validator: Callable[[str, str], bool] | None = None, account_metadata: Callable[[str, str], Mapping[str, Any] | None] | None = None) -> None:
        self._monitor_url = monitor_url.strip()
        self._view_id = view_id
        self._binding_validator = binding_validator
        self._account_metadata = account_metadata

    def get(self, context: TenantContext, public_account_id: str) -> dict[str, Any]:
        module = self._module()
        records = self._validated_records(module, context)
        record = self._record(records, public_account_id)
        account = module.account_from_record(record)
        fields = record.get("fields") or {}
        return {
            "schemaVersion": SCHEMA_VERSION,
            "revision": 0,
            "status": "available",
            "publicAccountId": public_account_id,
            "accountName": account["account_name"],
            "platform": account["platform"],
            "checkedAt": fields.get("最近运行时间"),
            "detail": fields.get("最近错误") or fields.get("最近日报摘要"),
            "enabled": account["enabled"],
            "recentPostUrls": account["urls"],
            "recentPostLinkResults": _monitor_link_results(account["urls"]),
            "recentStatus": fields.get("最近状态"),
            "recentPostCount": fields.get("最近作品数"),
            "recentTotalInteractions": fields.get("最近总互动"),
            "recentError": fields.get("最近错误"),
            "recentReportSummary": fields.get("最近日报摘要"),
        }

    def update(self, context: TenantContext, public_account_id: str, recent_post_urls: list[str], enabled: bool) -> dict[str, Any]:
        module = self._module()
        records = self._validated_records(module, context)
        record = self._find_record(records, public_account_id)
        if record is None:
            if self._account_metadata is None:
                raise TrackMonitorUnavailable("无法从账号身份源读取 H00 记录创建信息")
            metadata = self._account_metadata(context.tenant_id, public_account_id)
            if not metadata:
                raise TrackNotFound("owned account monitor not found")
            if not str(metadata.get("account_name") or "").strip() or not str(metadata.get("platform") or "").strip():
                raise TrackMonitorUnavailable("账号身份源缺少账号名称或平台")
            record_ids = module.write_feishu_records(
                self._monitor_url,
                [{
                    "public_account_id": public_account_id,
                    "账号名称": str(metadata["account_name"]),
                    "平台": str(metadata["platform"]),
                    "近期作品链接": recent_post_urls,
                    "启用": enabled,
                }],
                module="账号监控",
                require=True,
            )
            if len(record_ids) != 1:
                raise TrackMonitorUnavailable("H00 记录创建未返回唯一 record_id")
        else:
            module.update_account_monitor_record(
                self._monitor_url,
                str(record.get("record_id") or ""),
                {"近期作品链接": recent_post_urls, "启用": enabled},
            )
        response = self.get(context, public_account_id)
        expected_urls = [value.strip() for value in recent_post_urls]
        actual_urls = [str(value).strip() for value in response["recentPostUrls"]]
        if response["enabled"] is not enabled or actual_urls != expected_urls:
            raise TrackMonitorUnavailable("账号监控表写入后读回不一致，已拒绝报告成功")
        return response

    def poll(self, context: TenantContext, public_account_id: str) -> dict[str, Any]:
        module = self._module()
        records = self._validated_records(module, context)
        record = self._record(records, public_account_id)
        account = module.account_from_record(record)
        if not account["enabled"]:
            return self.get(context, public_account_id)
        if not account["urls"]:
            raise TrackInvalidRequest("账号监控表需要填写近期作品链接", field="recentPostUrls")
        try:
            rows = module.refresh_posts(account["urls"])
            summary = module.account_summary(account, rows)
            fields = {
                "最近运行时间": summary["captured_at"],
                "最近状态": module.daily_poll_status_label(summary["overall_status"]),
                "最近作品数": summary["post_count"],
                "最近总互动": summary["total_interactions"],
                "最近错误": "",
            }
        except Exception as exc:
            fields = {"最近运行时间": module.now_iso(), "最近状态": "轮询失败", "最近错误": module.user_visible_poll_error(exc)}
        module.update_account_monitor_record(self._monitor_url, str(record.get("record_id") or ""), fields)
        return self.get(context, public_account_id)

    def _module(self) -> Any:
        from runtime.cli import selfmedia
        return selfmedia

    def _validated_records(self, module: Any, context: TenantContext) -> list[dict[str, Any]]:
        try:
            schema = module.require_valid_schema(self._monitor_url)
            records = module.list_account_monitor_records(self._monitor_url, view_id=self._view_id)
            module.validate_account_monitor_records(
                records,
                tenant_id=context.tenant_id,
                binding_validator=self._binding_validator,
                require_binding=True,
            )
            if not schema["ok"]:
                raise ValueError("H00 schema validation failed")
            return records
        except SystemExit as exc:
            raise TrackMonitorUnavailable("账号监控表 schema、权限或身份绑定不可用") from exc
        except Exception as exc:
            raise TrackMonitorUnavailable("account monitor schema or identity binding is unavailable") from exc

    @staticmethod
    def _find_record(records: list[dict[str, Any]], public_account_id: str) -> dict[str, Any] | None:
        for record in records:
            fields = record.get("fields") or {}
            if str(fields.get("public_account_id") or fields.get("publicAccountId") or "").strip() == public_account_id:
                return record
        return None

    @classmethod
    def _record(cls, records: list[dict[str, Any]], public_account_id: str) -> dict[str, Any]:
        record = cls._find_record(records, public_account_id)
        if record is None:
            raise TrackNotFound("owned account monitor not found")
        return record


def _monitor_link_results(urls: list[str]) -> list[dict[str, Any]]:
    """Expose the shared link classification so clients never reimplement platform rules."""
    return [{"url": url, **classify_post_link(url)} for url in urls]


class DatabaseConnection(Protocol):
    def execute(self, query: str, params: tuple[Any, ...] = ()) -> Any: ...


ConnectionFactory = Callable[[], AbstractContextManager[DatabaseConnection]]


@dataclass(frozen=True)
class TrackCursor:
    scope: str
    updated_at: datetime
    public_id: str


class TracksService:
    """Read explicit B02 product records without inferring business relations."""

    _TRACK_STATE_QUERY = """
        SELECT COUNT(*)::bigint, COALESCE(MAX(t.revision), 0), MAX(t.updated_at)
        FROM media_product.tracks AS t
        WHERE t.tenant_id = %s
    """
    _TRACK_LIST_QUERY = f"""
        SELECT t.public_id, t.revision, t.canonical_data, parent.public_id,
               t.created_at, t.updated_at
        FROM media_product.tracks AS t
        LEFT JOIN media_product.tracks AS parent
          ON parent.tenant_id = t.tenant_id
         AND parent.public_id = COALESCE(
               NULLIF(t.canonical_data->>'parent_track_id', ''),
               NULLIF(t.canonical_data->>'parentPublicTrackId', '')
             )
        WHERE t.tenant_id = %s
          AND (
            %s = ''
            OR t.public_id ILIKE %s ESCAPE '\\'
            OR COALESCE(t.canonical_data::text, '') ILIKE %s ESCAPE '\\'
          )
{sql_pagination.keyset_window("t.", "updated_at", "public_id")}"""
    _TRACK_DETAIL_QUERY = """
        SELECT t.public_id, t.revision, t.canonical_data, parent.public_id,
               t.created_at, t.updated_at
        FROM media_product.tracks AS t
        LEFT JOIN media_product.tracks AS parent
          ON parent.tenant_id = t.tenant_id
         AND parent.public_id = COALESCE(
               NULLIF(t.canonical_data->>'parent_track_id', ''),
               NULLIF(t.canonical_data->>'parentPublicTrackId', '')
             )
        WHERE t.tenant_id = %s AND t.public_id = %s
    """

    _CREATOR_STATE_QUERY = """
        SELECT COUNT(*)::bigint, COALESCE(MAX(c.revision), 0), MAX(c.updated_at)
        FROM media_product.creator_profiles AS c
        WHERE c.tenant_id = %s
    """
    _CREATOR_LIST_QUERY = f"""
        SELECT c.public_id, c.revision, c.canonical_data, c.created_at, c.updated_at
        FROM media_product.creator_profiles AS c
        WHERE c.tenant_id = %s
          AND (
            %s = ''
            OR c.public_id ILIKE %s ESCAPE '\\'
            OR COALESCE(c.canonical_data::text, '') ILIKE %s ESCAPE '\\'
          )
{sql_pagination.keyset_window("c.", "updated_at", "public_id")}"""
    _CREATOR_DETAIL_QUERY = """
        SELECT c.public_id, c.revision, c.canonical_data, c.created_at, c.updated_at
        FROM media_product.creator_profiles AS c
        WHERE c.tenant_id = %s AND c.public_id = %s
    """

    _RELATIONSHIP_STATE_QUERY = """
        SELECT COUNT(*)::bigint, COALESCE(MAX(m.revision), 0), MAX(m.updated_at)
        FROM media_product.track_creator_memberships AS m
        JOIN media_product.tracks AS t
          ON t.tenant_id = m.tenant_id
         AND t.public_id = COALESCE(
               NULLIF(m.canonical_data->>'track_id', ''),
               NULLIF(m.canonical_data->>'public_track_id', '')
             )
        JOIN media_product.creator_profiles AS c
          ON c.tenant_id = m.tenant_id
         AND c.public_id = COALESCE(
               NULLIF(m.canonical_data->>'creator_profile_id', ''),
               NULLIF(m.canonical_data->>'public_creator_id', '')
             )
        WHERE m.tenant_id = %s
    """
    _RELATIONSHIP_LIST_QUERY = f"""
        SELECT m.public_id, m.revision, m.canonical_data, m.created_at, m.updated_at,
               t.public_id, c.public_id
        FROM media_product.track_creator_memberships AS m
        JOIN media_product.tracks AS t
          ON t.tenant_id = m.tenant_id
         AND t.public_id = COALESCE(
               NULLIF(m.canonical_data->>'track_id', ''),
               NULLIF(m.canonical_data->>'public_track_id', '')
             )
        JOIN media_product.creator_profiles AS c
          ON c.tenant_id = m.tenant_id
         AND c.public_id = COALESCE(
               NULLIF(m.canonical_data->>'creator_profile_id', ''),
               NULLIF(m.canonical_data->>'public_creator_id', '')
             )
        WHERE m.tenant_id = %s
{sql_pagination.keyset_window("m.", "updated_at", "public_id")}"""
    _RELATIONSHIP_DETAIL_QUERY = """
        SELECT m.public_id, m.revision, m.canonical_data, m.created_at, m.updated_at,
               t.public_id, c.public_id
        FROM media_product.track_creator_memberships AS m
        JOIN media_product.tracks AS t
          ON t.tenant_id = m.tenant_id
         AND t.public_id = COALESCE(
               NULLIF(m.canonical_data->>'track_id', ''),
               NULLIF(m.canonical_data->>'public_track_id', '')
             )
        JOIN media_product.creator_profiles AS c
          ON c.tenant_id = m.tenant_id
         AND c.public_id = COALESCE(
               NULLIF(m.canonical_data->>'creator_profile_id', ''),
               NULLIF(m.canonical_data->>'public_creator_id', '')
             )
        WHERE m.tenant_id = %s AND m.public_id = %s
    """

    _ACCOUNT_STATE_QUERY = """
        SELECT COUNT(*)::bigint, COALESCE(MAX(a.revision), 0), MAX(a.updated_at)
        FROM media_product.owned_media_accounts AS a
        WHERE a.tenant_id = %s
    """
    _ACCOUNT_LIST_QUERY = f"""
        SELECT a.public_id, a.revision, a.canonical_data, a.created_at, a.updated_at
        FROM media_product.owned_media_accounts AS a
        WHERE a.tenant_id = %s
{sql_pagination.keyset_window("a.", "updated_at", "public_id")}"""
    _ACCOUNT_DETAIL_QUERY = """
        SELECT a.public_id, a.revision, a.canonical_data, a.created_at, a.updated_at
        FROM media_product.owned_media_accounts AS a
        WHERE a.tenant_id = %s AND a.public_id = %s
    """
    _STRATEGY_DETAIL_QUERY = """
        SELECT s.public_id, s.revision, s.canonical_data, a.public_id, s.updated_at
        FROM media_product.account_track_strategies AS s
        JOIN media_product.owned_media_accounts AS a
          ON a.tenant_id = s.tenant_id
         AND a.public_id = COALESCE(
               NULLIF(s.canonical_data->>'public_account_id', ''),
               NULLIF(s.canonical_data->>'account_id', '')
             )
        WHERE s.tenant_id = %s AND a.public_id = %s
        ORDER BY s.updated_at DESC, s.public_id ASC
        LIMIT 1
    """

    def __init__(self, connection_factory: ConnectionFactory, *, cursor_secret: bytes, monitor_adapter: AccountMonitorAdapter | None = None) -> None:
        if len(cursor_secret) < 16:
            raise ValueError("B02 cursor secret must be at least 16 bytes")
        self._connection_factory = connection_factory
        self._cursor_key = hashlib.sha256(bytes(cursor_secret)).digest()
        self._monitor_adapter = monitor_adapter

    def list_tracks(
        self,
        context: TenantContext,
        *,
        cursor: str | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
        search: str | None = None,
    ) -> dict[str, Any]:
        tenant_id = self._tenant_id(context)
        size = _page_size(page_size)
        term = _search(search)
        position = self._decode_cursor(cursor, tenant_id, "tracks") if cursor else None
        state, rows = self._execute_list(
            self._TRACK_STATE_QUERY,
            self._TRACK_LIST_QUERY,
            tenant_id,
            _search_params(tenant_id, term, position, size),
        )
        count, max_revision, latest = _state_row(state, "track")
        visible, has_next = _visible_rows(rows, size)
        items = [_clean(self._track_row(row)) for row in visible]
        return _list_response(
            count,
            max_revision,
            latest,
            items,
            self._next_cursor(tenant_id, "tracks", visible, has_next, 5),
        )

    def get_track(self, context: TenantContext, public_track_id: str) -> dict[str, Any]:
        row = self._detail(context, self._TRACK_DETAIL_QUERY, public_track_id, "track")
        item = self._track_row(row)
        return _detail_response(item["_revision"], _clean(item))

    def list_creators(
        self,
        context: TenantContext,
        *,
        cursor: str | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
        search: str | None = None,
    ) -> dict[str, Any]:
        tenant_id = self._tenant_id(context)
        size = _page_size(page_size)
        term = _search(search)
        position = self._decode_cursor(cursor, tenant_id, "creators") if cursor else None
        state, rows = self._execute_list(
            self._CREATOR_STATE_QUERY,
            self._CREATOR_LIST_QUERY,
            tenant_id,
            _search_params(tenant_id, term, position, size),
        )
        count, max_revision, latest = _state_row(state, "creator")
        visible, has_next = _visible_rows(rows, size)
        items = [_clean(self._creator_row(row)) for row in visible]
        return _list_response(
            count,
            max_revision,
            latest,
            items,
            self._next_cursor(tenant_id, "creators", visible, has_next, 4),
        )

    def get_creator(self, context: TenantContext, public_creator_id: str) -> dict[str, Any]:
        row = self._detail(context, self._CREATOR_DETAIL_QUERY, public_creator_id, "creator")
        item = self._creator_row(row)
        return _detail_response(item["_revision"], _clean(item))

    def list_track_relationships(
        self,
        context: TenantContext,
        *,
        cursor: str | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> dict[str, Any]:
        tenant_id = self._tenant_id(context)
        size = _page_size(page_size)
        position = self._decode_cursor(cursor, tenant_id, "track-relationships") if cursor else None
        state, rows = self._execute_list(
            self._RELATIONSHIP_STATE_QUERY,
            self._RELATIONSHIP_LIST_QUERY,
            tenant_id,
            _simple_params(tenant_id, position, size),
        )
        count, max_revision, latest = _state_row(state, "relationship")
        visible, has_next = _visible_rows(rows, size)
        items = [_clean(self._relationship_row(row)) for row in visible]
        if len({(item["publicTrackId"], item["publicCreatorId"]) for item in items}) != len(items):
            raise TrackInternalError("duplicate explicit track creator relationship")
        return _list_response(
            count,
            max_revision,
            latest,
            items,
            self._next_cursor(tenant_id, "track-relationships", visible, has_next, 4),
        )

    def update_track_relationship_status(
        self,
        context: TenantContext,
        public_relationship_id: str,
        request: Mapping[str, Any],
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        tenant_id = self._tenant_id(context)
        relationship_id = _requested_public_id(public_relationship_id)
        normalized = self._validate_relationship_status_request(request)
        replay_request = {
            "publicRelationshipId": relationship_id,
            **normalized,
        }
        path_fingerprint = hashlib.sha256(
            f"updateTrackRelationshipStatus:{relationship_id}".encode()
        ).digest()
        request_fingerprint = hashlib.sha256(_json_bytes(replay_request)).digest()
        try:
            with self._connection_factory() as connection:
                replay = self._reserve_or_replay_idempotency(
                    connection,
                    tenant_id,
                    "updateTrackRelationshipStatus",
                    idempotency_key,
                    path_fingerprint,
                    request_fingerprint,
                )
                if replay is not None:
                    return public_projection(replay)
                row = connection.execute(
                    self._RELATIONSHIP_DETAIL_QUERY,
                    (tenant_id, relationship_id),
                ).fetchone()
                if row is None:
                    raise TrackNotFound("track relationship not found")
                stored_id, current_revision, data, _created, _updated, _track_id, _creator_id = row
                if normalized["expectedRevision"] != current_revision:
                    raise TrackConflict()
                updated_data = dict(_object(data, "track relationship canonical data"))
                updated_data["status"] = normalized["status"]
                next_revision = current_revision + 1
                now = datetime.now(timezone.utc)
                update_result = connection.execute(
                    """
                    UPDATE media_product.track_creator_memberships
                       SET revision = %s, canonical_data = CAST(%s AS jsonb), updated_at = %s
                     WHERE tenant_id = %s AND public_id = %s AND revision = %s
                    """,
                    (
                        next_revision,
                        json.dumps(updated_data, ensure_ascii=False, separators=(",", ":")),
                        now,
                        tenant_id,
                        stored_id,
                        current_revision,
                    ),
                )
                if hasattr(update_result, "rowcount") and update_result.rowcount == 0:
                    raise TrackConflict()
                readback = connection.execute(
                    self._RELATIONSHIP_DETAIL_QUERY,
                    (tenant_id, stored_id),
                ).fetchone()
                if readback is None:
                    raise TrackInternalError("updated track relationship readback is missing")
                item = self._relationship_row(readback)
                if item["status"] != normalized["status"] or item["_revision"] != next_revision:
                    raise TrackInternalError("updated track relationship readback is stale")
                response = {
                    "schemaVersion": SCHEMA_VERSION,
                    "revision": next_revision,
                    "item": _clean(item),
                }
                self._complete_idempotency(
                    connection,
                    tenant_id,
                    "updateTrackRelationshipStatus",
                    idempotency_key,
                    path_fingerprint,
                    request_fingerprint,
                    response,
                )
                _commit(connection)
                return public_projection(response)
        except TracksError:
            raise
        except Exception as exc:
            raise TrackInternalError() from exc

    @staticmethod
    def _validate_relationship_status_request(request: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(request, Mapping):
            raise TrackInvalidRequest("request must be an object")
        unexpected = set(request) - {"expectedRevision", "status"}
        if unexpected:
            raise TrackInvalidRequest(f"unexpected field: {sorted(unexpected)[0]}")
        expected = request.get("expectedRevision")
        if isinstance(expected, bool) or not isinstance(expected, int) or expected < 1:
            raise TrackInvalidRequest("expectedRevision is invalid", field="expectedRevision")
        status = request.get("status")
        if status not in {"candidate", "active", "rejected"}:
            raise TrackInvalidRequest("status is invalid", field="status")
        return {"expectedRevision": expected, "status": status}

    @staticmethod
    def _reserve_or_replay_idempotency(
        connection: DatabaseConnection,
        tenant_id: str,
        operation: str,
        idempotency_key: str,
        path_fingerprint: bytes,
        request_fingerprint: bytes,
    ) -> dict[str, Any] | None:
        _validate_idempotency_key(idempotency_key)
        lease_owner = str(uuid4())
        inserted = connection.execute(
            """
            INSERT INTO openclaw_account.if2_idempotency_receipts
                (scope_kind, scope_id, operation_id, idempotency_key,
                 path_fingerprint, request_fingerprint, state,
                 lease_owner, lease_expires_at)
            VALUES ('tenant', %s, %s, %s, %s, %s, 'reserved', %s, now() + interval '10 minutes')
            ON CONFLICT (scope_kind, scope_id, operation_id, idempotency_key) DO NOTHING
            RETURNING id
            """,
            (tenant_id, operation, idempotency_key, path_fingerprint, request_fingerprint, lease_owner),
        ).fetchone()
        if inserted is not None:
            return None
        row = connection.execute(
            """
            SELECT path_fingerprint, request_fingerprint, state, response_json
              FROM openclaw_account.if2_idempotency_receipts
             WHERE scope_kind = 'tenant' AND scope_id = %s
               AND operation_id = %s AND idempotency_key = %s
             FOR UPDATE
            """,
            (tenant_id, operation, idempotency_key),
        ).fetchone()
        if row is None:
            raise TrackInternalError("idempotency reservation readback failed")
        stored_path, stored_request, state, response_json = row
        if bytes(stored_path) != path_fingerprint or bytes(stored_request) != request_fingerprint:
            raise TrackConflict("Idempotency-Key was reused with a different request")
        if state == "completed":
            return _json_object(response_json, "idempotent response")
        raise TrackConflict("the same relationship update is already in progress")

    @staticmethod
    def _complete_idempotency(
        connection: DatabaseConnection,
        tenant_id: str,
        operation: str,
        idempotency_key: str,
        path_fingerprint: bytes,
        request_fingerprint: bytes,
        response: Mapping[str, Any],
    ) -> None:
        result = connection.execute(
            """
            UPDATE openclaw_account.if2_idempotency_receipts
               SET state = 'completed', response_status = 200,
                   response_json = CAST(%s AS jsonb), completed_at = now(),
                   lease_owner = NULL, lease_expires_at = NULL
             WHERE scope_kind = 'tenant' AND scope_id = %s
               AND operation_id = %s AND idempotency_key = %s
               AND path_fingerprint = %s AND request_fingerprint = %s
               AND state = 'reserved'
            """,
            (
                json.dumps(dict(response), ensure_ascii=False, separators=(",", ":")),
                tenant_id,
                operation,
                idempotency_key,
                path_fingerprint,
                request_fingerprint,
            ),
        )
        if hasattr(result, "rowcount") and result.rowcount == 0:
            raise TrackInternalError("idempotency completion failed")

    def list_owned_accounts(
        self,
        context: TenantContext,
        *,
        cursor: str | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> dict[str, Any]:
        tenant_id = self._tenant_id(context)
        size = _page_size(page_size)
        position = self._decode_cursor(cursor, tenant_id, "owned-accounts") if cursor else None
        state, rows = self._execute_list(
            self._ACCOUNT_STATE_QUERY,
            self._ACCOUNT_LIST_QUERY,
            tenant_id,
            _simple_params(tenant_id, position, size),
        )
        count, max_revision, latest = _state_row(state, "owned account")
        visible, has_next = _visible_rows(rows, size)
        items = [_clean(self._account_row(row)) for row in visible]
        return _list_response(
            count,
            max_revision,
            latest,
            items,
            self._next_cursor(tenant_id, "owned-accounts", visible, has_next, 4),
        )

    def get_owned_account(self, context: TenantContext, public_account_id: str) -> dict[str, Any]:
        row = self._detail(context, self._ACCOUNT_DETAIL_QUERY, public_account_id, "owned account")
        item = self._account_row(row)
        return _detail_response(item["_revision"], _clean(item))

    def get_account_track_strategy(
        self,
        context: TenantContext,
        public_account_id: str,
    ) -> dict[str, Any]:
        tenant_id = self._tenant_id(context)
        account_id = _requested_public_id(public_account_id)
        try:
            with self._connection_factory() as connection:
                row = connection.execute(self._STRATEGY_DETAIL_QUERY, (tenant_id, account_id)).fetchone()
        except TracksError:
            raise
        except Exception as exc:
            raise TrackInternalError() from exc
        if row is None:
            raise TrackNotFound("account track strategy not found")
        strategy = self._strategy_row(row)
        return public_projection(
            {
                "schemaVersion": SCHEMA_VERSION,
                "revision": strategy["revision"],
                "strategy": strategy,
            }
        )

    def get_account_monitor(self, context: TenantContext, public_account_id: str) -> dict[str, Any]:
        self._tenant_id(context)
        account_id = _requested_public_id(public_account_id)
        if self._monitor_adapter is None:
            raise TrackMonitorUnavailable()
        self._detail(context, self._ACCOUNT_DETAIL_QUERY, account_id, "owned account")
        return self._monitor_adapter.get(context, account_id)

    def update_account_monitor(
        self,
        context: TenantContext,
        public_account_id: str,
        recent_post_urls: list[str],
        enabled: bool,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Validate the tenant-owned account before entering the H00 adapter boundary."""
        self._validate_monitor_input(recent_post_urls, enabled, idempotency_key)
        account_row = self._detail(context, self._ACCOUNT_DETAIL_QUERY, public_account_id, "owned account")
        expected_platform = self._account_row(account_row)["platform"]
        self._validate_monitor_platforms(recent_post_urls, expected_platform)
        if self._monitor_adapter is None:
            raise TrackMonitorUnavailable()
        return self._monitor_adapter.update(context, public_account_id, recent_post_urls, enabled)

    def poll_account_monitor(
        self,
        context: TenantContext,
        public_account_id: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        self._validate_monitor_input([], True, idempotency_key)
        self._detail(context, self._ACCOUNT_DETAIL_QUERY, public_account_id, "owned account")
        if self._monitor_adapter is None:
            raise TrackMonitorUnavailable()
        return self._monitor_adapter.poll(context, public_account_id)

    @staticmethod
    def _validate_monitor_input(
        recent_post_urls: list[str], enabled: bool, idempotency_key: str
    ) -> None:
        if not isinstance(recent_post_urls, list) or len(recent_post_urls) > 100:
            raise TrackInvalidRequest("recentPostUrls must be an array of at most 100 URLs", field="recentPostUrls")
        for value in recent_post_urls:
            if not isinstance(value, str) or not value.strip():
                raise TrackInvalidRequest("recentPostUrls must contain non-empty strings", field="recentPostUrls")
            parsed = urlsplit(value)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise TrackInvalidRequest("recentPostUrls must contain HTTP(S) URLs", field="recentPostUrls")
            if classify_post_link(value)["kind"] == "profile":
                raise TrackInvalidRequest("这是账号主页，需要具体作品页链接", field="recentPostUrls")
        if not isinstance(enabled, bool):
            raise TrackInvalidRequest("enabled must be a boolean", field="enabled")
        if not isinstance(idempotency_key, str) or not idempotency_key:
            raise TrackInvalidRequest("idempotency key is required", field="idempotencyKey")

    @staticmethod
    def _validate_monitor_platforms(recent_post_urls: list[str], expected_platform: str) -> None:
        for value in recent_post_urls:
            classified = classify_post_link(value)
            actual_platform = str(classified["platform"] or "unknown")
            if actual_platform != "unknown" and _platform_key(expected_platform) != actual_platform:
                raise TrackInvalidRequest(
                    f"作品链接平台与账号平台不一致：账号是 {_platform_label(expected_platform)}，链接是 {_platform_label(actual_platform)}",
                    field="recentPostUrls",
                )

    def _execute_list(
        self,
        state_query: str,
        list_query: str,
        tenant_id: str,
        params: tuple[Any, ...],
    ) -> tuple[Any, Any]:
        try:
            with self._connection_factory() as connection:
                state = connection.execute(state_query, (tenant_id,)).fetchone()
                rows = connection.execute(list_query, params).fetchall()
            return state, rows
        except TracksError:
            raise
        except Exception as exc:
            raise TrackInternalError() from exc

    def _detail(
        self,
        context: TenantContext,
        query: str,
        public_id: str,
        label: str,
    ) -> Any:
        tenant_id = self._tenant_id(context)
        resource_id = _requested_public_id(public_id)
        try:
            with self._connection_factory() as connection:
                row = connection.execute(query, (tenant_id, resource_id)).fetchone()
        except TracksError:
            raise
        except Exception as exc:
            raise TrackInternalError() from exc
        if row is None:
            raise TrackNotFound(f"{label} not found")
        return row

    def _next_cursor(
        self,
        tenant_id: str,
        scope: str,
        rows: list[Any],
        has_next: bool,
        updated_index: int,
    ) -> str | None:
        if not has_next:
            return None
        if not rows or not isinstance(rows[-1], (tuple, list)):
            raise TrackInternalError("cursor row shape is invalid")
        row = rows[-1]
        if len(row) <= updated_index:
            raise TrackInternalError("cursor row shape is invalid")
        return self._encode_cursor(
            tenant_id,
            TrackCursor(scope, _timestamp_value(row[updated_index]), _public_id(row[0])),
        )

    def _encode_cursor(self, tenant_id: str, cursor: TrackCursor) -> str:
        payload = json.dumps(
            {
                "publicId": cursor.public_id,
                "scope": cursor.scope,
                "updatedAt": _timestamp_text(cursor.updated_at),
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        signature = hmac.new(
            self._cursor_key,
            tenant_id.encode() + b"|" + payload,
            hashlib.sha256,
        ).digest()[:18]
        return f"{_b64_encode(payload)}.{_b64_encode(signature)}"

    def _decode_cursor(self, token: str, tenant_id: str, scope: str) -> TrackCursor:
        if not isinstance(token, str) or not token or token.count(".") != 1:
            raise TrackInvalidRequest("cursor is invalid", field="cursor")
        payload_text, signature_text = token.split(".", 1)
        try:
            payload = _b64_decode(payload_text)
            signature = _b64_decode(signature_text)
            expected = hmac.new(
                self._cursor_key,
                tenant_id.encode() + b"|" + payload,
                hashlib.sha256,
            ).digest()[:18]
            if not hmac.compare_digest(signature, expected):
                raise ValueError("signature mismatch")
            data = json.loads(payload.decode())
            if data["scope"] != scope:
                raise ValueError("cursor scope mismatch")
            return TrackCursor(scope, _timestamp_value(data["updatedAt"]), _public_id(data["publicId"]))
        except TracksError as exc:
            raise TrackInvalidRequest("cursor is invalid", field="cursor") from exc
        except (KeyError, TypeError, ValueError, json.JSONDecodeError, binascii.Error) as exc:
            raise TrackInvalidRequest("cursor is invalid", field="cursor") from exc

    @staticmethod
    def _track_row(row: Any) -> dict[str, Any]:
        if not isinstance(row, (tuple, list)) or len(row) != 6:
            raise TrackInternalError("track row shape is invalid")
        public_id, revision, data, parent_id, _created, updated = row
        data = _object(data, "track canonical data")
        item = {
            "publicTrackId": _public_id(public_id),
            "name": _text(data, ("track_name", "name"), "track name"),
            "description": _text(data, ("description", "track_description"), "track description", True),
            "parentPublicTrackId": None if parent_id is None else _public_id(parent_id),
            "status": _text(data, ("status",), "track status"),
            "platforms": _list(data, ("platform_scope", "platforms"), "track platforms"),
            "aliases": _list(data, ("alias_names", "aliases"), "track aliases"),
            "artifactCount": _count(data, ("artifact_count", "artifactCount"), "track artifact count"),
            "updatedAt": _timestamp_text(updated),
            "_revision": _positive_revision(revision),
        }
        if item["parentPublicTrackId"] == item["publicTrackId"]:
            raise TrackInternalError("track cannot be its own parent")
        return item

    @staticmethod
    def _creator_row(row: Any) -> dict[str, Any]:
        if not isinstance(row, (tuple, list)) or len(row) != 5:
            raise TrackInternalError("creator row shape is invalid")
        public_id, revision, data, _created, updated = row
        data = _object(data, "creator canonical data")
        return {
            "publicCreatorId": _public_id(public_id),
            "accountName": _text(data, ("account_name", "accountName"), "creator account name"),
            "platform": _text(data, ("platform",), "creator platform"),
            "creatorRole": _text(data, ("creator_role", "creatorRole"), "creator role"),
            "identityTags": _list(data, ("identity_tags", "identityTags"), "creator identity tags"),
            "expertiseDomains": _list(data, ("expertise_domains", "expertiseDomains"), "creator expertise domains"),
            "profileUrl": _nullable_url(data, ("profile_url", "profileUrl"), "creator profile URL"),
            "avatarUrl": _nullable_avatar_url(data, ("avatar_url", "avatarUrl"), "creator avatar URL"),
            "updatedAt": _timestamp_text(updated),
            "_revision": _positive_revision(revision),
        }

    @staticmethod
    def _relationship_row(row: Any) -> dict[str, Any]:
        if not isinstance(row, (tuple, list)) or len(row) != 7:
            raise TrackInternalError("track relationship row shape is invalid")
        public_id, revision, data, _created, _updated, track_id, creator_id = row
        data = _object(data, "track relationship canonical data")
        score = _number(data, ("fit_score", "fitScore"), "relationship fit score")
        return {
            "publicRelationshipId": _public_id(public_id),
            "revision": _positive_revision(revision),
            "publicTrackId": _public_id(track_id),
            "publicCreatorId": _public_id(creator_id),
            "role": _text(data, ("role",), "relationship role"),
            "fitScore": score,
            "fitReason": _text(data, ("fit_reason", "fitReason"), "relationship fit reason", True),
            "status": _text(data, ("status",), "relationship status"),
            "lastEvaluatedAt": _nullable_timestamp(data, ("last_evaluated_at", "lastEvaluatedAt"), "relationship evaluation time"),
            "_revision": _positive_revision(revision),
        }

    @staticmethod
    def _account_row(row: Any) -> dict[str, Any]:
        if not isinstance(row, (tuple, list)) or len(row) != 5:
            raise TrackInternalError("owned account row shape is invalid")
        public_id, revision, data, _created, updated = row
        data = _object(data, "owned account canonical data")
        operational_status = _nullable_text(
            data,
            ("operational_status",),
            "owned account operational status",
        )
        if operational_status is not None and operational_status not in _OPERATIONAL_STATUSES:
            raise TrackInternalError("owned account operational status is invalid")
        return {
            "publicAccountId": _public_id(public_id),
            "platform": _text(data, ("platform",), "owned account platform"),
            "accountName": _text(data, ("account_name", "accountName"), "owned account name"),
            "operationalStatus": operational_status,
            "responsiblePerson": _nullable_text(
                data,
                ("responsible_person",),
                "owned account responsible person",
            ),
            "teamName": _nullable_text(
                data,
                ("team_name",),
                "owned account team name",
            ),
            "accountPositioning": _nullable_text(
                data,
                ("account_positioning",),
                "owned account positioning",
            ),
            "dataSource": _nullable_text(
                data,
                ("data_source",),
                "owned account data source",
            ),
            "platformAccountId": _nullable_text(
                data,
                ("author_id", "authorId"),
                "owned account platform identifier",
            ),
            "profileUrl": _nullable_url(data, ("profile_url", "profileUrl"), "owned account profile URL"),
            "avatarUrl": _nullable_avatar_url(
                data,
                ("avatar_url", "avatarUrl"),
                "owned account avatar URL",
            ),
            "publicTrackIds": _public_ids(data, ("public_track_ids", "publicTrackIds"), "owned account track ids"),
            "lastSyncedAt": _nullable_timestamp(data, ("last_synced_at", "lastSyncedAt"), "owned account sync time"),
            "updatedAt": _timestamp_text(updated),
            "_revision": _positive_revision(revision),
        }

    @staticmethod
    def _strategy_row(row: Any) -> dict[str, Any]:
        if not isinstance(row, (tuple, list)) or len(row) != 5:
            raise TrackInternalError("account strategy row shape is invalid")
        public_id, revision, data, account_id, updated = row
        data = _object(data, "account strategy canonical data")
        status = _text(data, ("human_status", "humanStatus"), "account strategy human status")
        if status not in _HUMAN_STATUSES:
            raise TrackInternalError("account strategy human status is invalid")
        return {
            "publicStrategyId": _public_id(public_id),
            "publicAccountId": _public_id(account_id),
            "targetPublicTrackIds": _public_ids(
                data,
                ("target_public_track_ids", "targetPublicTrackIds"),
                "account strategy target tracks",
            ),
            "evidenceRefs": _evidence_refs(data),
            "recommendations": _list(data, ("recommendations",), "account strategy recommendations"),
            "humanStatus": status,
            "revision": _nonnegative_revision(revision),
            "updatedAt": _timestamp_text(updated),
        }

    @staticmethod
    def error_response(error: BaseException) -> dict[str, Any]:
        if isinstance(error, TracksError):
            return {"error": {"code": error.code, "message": error.message, "field": error.field}}
        return {"error": {"code": "internal_error", "message": "track data is unavailable", "field": None}}

    @staticmethod
    def _tenant_id(context: TenantContext | None) -> str:
        return foundation.require_tenant_id(context, forbidden=TrackForbidden)


TrackService = TracksService


def _search_params(tenant_id: str, term: str, position: TrackCursor | None, size: int) -> tuple[Any, ...]:
    pattern = _search_pattern(term)
    ts = position.updated_at if position is not None else None
    public_id = position.public_id if position is not None else None
    return (tenant_id, term, pattern, pattern, *sql_pagination.keyset_params(ts, public_id), size + 1)


def _simple_params(tenant_id: str, position: TrackCursor | None, size: int) -> tuple[Any, ...]:
    ts = position.updated_at if position is not None else None
    public_id = position.public_id if position is not None else None
    return (tenant_id, *sql_pagination.keyset_params(ts, public_id), size + 1)


def _page_size(value: Any) -> int:
    return foundation.page_size(value, error=lambda m: TrackInvalidRequest(m, field="pageSize"))


def _search(value: Any) -> str:
    if value is None:
        return ""
    if not isinstance(value, str) or len(value) > 160:
        raise TrackInvalidRequest("search is invalid", field="search")
    return value.strip()


def _search_pattern(value: str) -> str:
    return f"%{value.replace(chr(92), chr(92) * 2).replace('%', chr(92) + '%').replace('_', chr(92) + '_')}%"


def _requested_public_id(value: Any) -> str:
    if not isinstance(value, str) or _PUBLIC_ID.fullmatch(value) is None:
        raise TrackInvalidRequest("public identifier is invalid", field="publicId")
    return value


def _platform_key(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    aliases = {
        "抖音": "douyin",
        "douyin": "douyin",
        "dy": "douyin",
        "小红书": "xiaohongshu",
        "xiaohongshu": "xiaohongshu",
        "xhs": "xiaohongshu",
    }
    return aliases.get(normalized, normalized)


def _platform_label(value: Any) -> str:
    return {"douyin": "抖音", "xiaohongshu": "小红书"}.get(_platform_key(value), str(value or "未知平台"))


def _public_id(value: Any) -> str:
    if not isinstance(value, str) or _PUBLIC_ID.fullmatch(value) is None:
        raise TrackInternalError("public identifier is invalid")
    return value


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TrackInternalError(f"{label} is invalid")
    return value


def _json_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(dict(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _json_object(value: Any, label: str) -> dict[str, Any]:
    return foundation.json_object(value, label, error=TrackInternalError)


def _validate_idempotency_key(value: Any) -> None:
    idempotency_key(
        value,
        error=lambda: TrackInvalidRequest("Idempotency-Key is invalid", field="Idempotency-Key"),
        policy=IF2_KEY,
    )


def _commit(connection: Any) -> None:
    commit = getattr(connection, "commit", None)
    if callable(commit):
        commit()


def _field(data: dict[str, Any], keys: tuple[str, ...], label: str) -> Any:
    present = [key for key in keys if key in data]
    if not present:
        raise TrackInternalError(f"{label} is missing")
    values = [data[key] for key in present]
    if any(value != values[0] for value in values[1:]):
        raise TrackInternalError(f"{label} has conflicting aliases")
    return values[0]


def _text(
    data: dict[str, Any],
    keys: tuple[str, ...],
    label: str,
    allow_empty: bool = False,
) -> str:
    value = _field(data, keys, label)
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise TrackInternalError(f"{label} is invalid")
    return value if allow_empty else value.strip()


def _list(data: dict[str, Any], keys: tuple[str, ...], label: str) -> list[str]:
    value = _field(data, keys, label)
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise TrackInternalError(f"{label} is invalid")
    return [item.strip() for item in value]


def _public_ids(data: dict[str, Any], keys: tuple[str, ...], label: str) -> list[str]:
    try:
        return [_public_id(item) for item in _list(data, keys, label)]
    except TracksError as exc:
        raise TrackInternalError(f"{label} contains an invalid public id") from exc


def _count(data: dict[str, Any], keys: tuple[str, ...], label: str) -> int:
    value = _field(data, keys, label)
    if type(value) is not int or value < 0:
        raise TrackInternalError(f"{label} is invalid")
    return value


def _number(data: dict[str, Any], keys: tuple[str, ...], label: str) -> int | float:
    value = _field(data, keys, label)
    if type(value) not in (int, float) or not math.isfinite(float(value)):
        raise TrackInternalError(f"{label} is invalid")
    return value


def _nullable_timestamp(data: dict[str, Any], keys: tuple[str, ...], label: str) -> str | None:
    value = _field(data, keys, label)
    return None if value is None else _timestamp_text(value)


def _nullable_text(data: dict[str, Any], keys: tuple[str, ...], label: str) -> str | None:
    value = _field(data, keys, label)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise TrackInternalError(f"{label} is invalid")
    return value.strip()


def _nullable_url(data: dict[str, Any], keys: tuple[str, ...], label: str) -> str | None:
    value = _field(data, keys, label)
    return None if value is None else _url(value)


def _nullable_avatar_url(data: dict[str, Any], keys: tuple[str, ...], label: str) -> str | None:
    value = _field(data, keys, label)
    if value is None or not isinstance(value, str) or not value.strip():
        return None
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
        return None
    return value.strip()


def _evidence_refs(data: dict[str, Any]) -> list[dict[str, Any]]:
    value = _field(data, ("evidence_refs", "evidenceRefs"), "account strategy evidence refs")
    if not isinstance(value, list):
        raise TrackInternalError("account strategy evidence refs are invalid")
    result = []
    for item in value:
        if not isinstance(item, dict):
            raise TrackInternalError("account strategy evidence ref is invalid")
        result.append(
            {
                "kind": _mapping_text(item, "kind", "evidence kind"),
                "label": _mapping_text(item, "label", "evidence label"),
                "publicUrl": _mapping_url(item, ("publicUrl", "public_url"), "evidence URL"),
                "capturedAt": _mapping_timestamp(item, ("capturedAt", "captured_at"), "evidence captured time"),
                "qualityStatus": _mapping_quality(item),
            }
        )
    return result


def _mapping_text(data: dict[str, Any], key: str, label: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise TrackInternalError(f"{label} is invalid")
    return value.strip()


def _mapping_url(data: dict[str, Any], keys: tuple[str, ...], label: str) -> str | None:
    present = [key for key in keys if key in data]
    if not present:
        raise TrackInternalError(f"{label} is missing")
    value = data[present[0]]
    return None if value is None else _url(value)


def _mapping_timestamp(data: dict[str, Any], keys: tuple[str, ...], label: str) -> str | None:
    present = [key for key in keys if key in data]
    if not present:
        raise TrackInternalError(f"{label} is missing")
    value = data[present[0]]
    return None if value is None else _timestamp_text(value)


def _mapping_quality(data: dict[str, Any]) -> str:
    value = _mapping_text(data, "qualityStatus" if "qualityStatus" in data else "quality_status", "evidence quality")
    if value not in _QUALITY_STATUSES:
        raise TrackInternalError("evidence quality is invalid")
    return value


def _url(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TrackInternalError("public URL is invalid")
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise TrackInternalError("public URL is not controlled")
    return value.strip()


def _timestamp_error(label: str, reason: str) -> Exception:
    if reason == "naive":
        return TrackInternalError("timestamp must be timezone-aware")
    return TrackInternalError("timestamp is invalid")


def _timestamp_value(value: Any) -> datetime:
    return foundation.coerce_utc(value, "timestamp", error=_timestamp_error, allow_naive=False)


def _timestamp_text(value: Any) -> str:
    return _timestamp_value(value).isoformat().replace("+00:00", "Z")


def _positive_revision(value: Any) -> int:
    if type(value) is not int or value <= 0:
        raise TrackInternalError("revision is invalid")
    return value


def _nonnegative_revision(value: Any) -> int:
    if type(value) is not int or value < 0:
        raise TrackInternalError("revision is invalid")
    return value


def _state_row(row: Any, label: str) -> tuple[int, int, Any]:
    if not isinstance(row, (tuple, list)) or len(row) != 3:
        raise TrackInternalError(f"{label} state row shape is invalid")
    count, revision, updated = row
    if type(count) is not int or count < 0:
        raise TrackInternalError(f"{label} count is invalid")
    return count, _nonnegative_revision(revision), updated


def _visible_rows(rows: Any, size: int) -> tuple[list[Any], bool]:
    if not isinstance(rows, (tuple, list)):
        rows = list(rows)
    return list(rows[:size]), len(rows) > size


def _list_revision(count: int, max_revision: int, latest: Any) -> int:
    state = f"{count}|{max_revision}|{_timestamp_text(latest) if latest is not None else ''}"
    return int(hashlib.sha256(state.encode()).hexdigest()[:12], 16)


def _list_response(
    count: int,
    max_revision: int,
    latest: Any,
    items: list[dict[str, Any]],
    next_cursor: str | None,
) -> dict[str, Any]:
    return public_projection(
        {
            "schemaVersion": SCHEMA_VERSION,
            "revision": _list_revision(count, max_revision, latest),
            "items": items,
            "nextCursor": next_cursor,
        }
    )


def _detail_response(revision: int, item: dict[str, Any]) -> dict[str, Any]:
    return public_projection({"schemaVersion": SCHEMA_VERSION, "revision": revision, "item": item})


def _clean(item: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in item.items() if key != "_revision"}


def _b64_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def _b64_decode(value: str) -> bytes:
    if not value or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise ValueError("invalid base64url")
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
