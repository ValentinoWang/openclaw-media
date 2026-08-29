from __future__ import annotations

import gzip
import hashlib
import json
import re
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from media_vault.vault import canonical_tenant_id

from .resource_owner_registry import ResourceOwnerNotFound, ResourceOwnerRegistry


SCHEMA_VERSION = "tenant_media_projection_v1"
RUN_SECTIONS = frozenset({"sources", "decisions", "outputs"})
BASE_MAX_BACKEND_QUERIES = 2
BASE_MAX_GZIP_BYTES = 100 * 1024
SECTION_MAX_BACKEND_QUERIES = 3
SECTION_MAX_GZIP_BYTES = 250 * 1024
MAX_PAGE_SIZE = 100
MAX_SEARCH_BYTES = 256


class TenantProjectionError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class RunOwnerFact:
    tenant_id: str
    revision: str


@dataclass(frozen=True)
class ProjectionRead:
    payload: Mapping[str, Any]
    revision: str
    query_count: int


@dataclass(frozen=True)
class RunSummaryPage:
    items: tuple[Mapping[str, Any], ...]
    next_cursor: str | None
    revision: str
    query_count: int


@dataclass(frozen=True)
class AssetSummaryPage:
    items: tuple[Mapping[str, Any], ...]
    next_cursor: str | None
    revision: str
    query_count: int


@dataclass(frozen=True)
class ProjectionResponse:
    payload: dict[str, Any]
    etag: str
    cache_hit: bool
    query_count: int
    gzip_bytes: int


class CreationRunOwnerAccessor(Protocol):
    def resolve_run_owner(self, public_run_id: str) -> RunOwnerFact | None: ...


class CanonicalCreationRunOwnerAccessor:
    def __init__(self, registry: ResourceOwnerRegistry) -> None:
        self.registry = registry

    def resolve_run_owner(self, public_run_id: str) -> RunOwnerFact | None:
        try:
            owner = self.registry.get("media.creation_run", public_run_id)
        except ResourceOwnerNotFound:
            return None
        if owner.status != "active":
            return None
        return RunOwnerFact(tenant_id=owner.tenant_id, revision=str(owner.owner_revision))


class TenantProjectionReader(Protocol):
    def dashboard_summary(self, tenant_id: str) -> ProjectionRead: ...

    def list_run_summaries(
        self,
        tenant_id: str,
        *,
        cursor: str | None,
        page_size: int,
        search: str,
    ) -> RunSummaryPage: ...

    def list_source_assets(
        self,
        tenant_id: str,
        *,
        cursor: str | None,
        page_size: int,
    ) -> AssetSummaryPage: ...

    def run_base_detail(self, tenant_id: str, public_run_id: str) -> ProjectionRead: ...

    def run_section(self, tenant_id: str, public_run_id: str, section: str) -> ProjectionRead: ...


@dataclass
class _CacheEntry:
    response: ProjectionResponse
    expires_at: float


class TenantProjectionService:
    """Authenticated tenant projections; never a compatibility reader for public JSON."""

    def __init__(
        self,
        reader: TenantProjectionReader,
        owner_accessor: CreationRunOwnerAccessor,
        *,
        cache_ttl_seconds: int = 30,
        max_cache_entries: int = 1024,
        clock=time.monotonic,
    ) -> None:
        if cache_ttl_seconds < 1 or max_cache_entries < 1:
            raise ValueError("projection cache bounds must be positive")
        self.reader = reader
        self.owner_accessor = owner_accessor
        self.cache_ttl_seconds = cache_ttl_seconds
        self.max_cache_entries = max_cache_entries
        self.clock = clock
        self._cache: OrderedDict[tuple[str, str, str, str, str], _CacheEntry] = OrderedDict()
        self._lock = threading.RLock()

    def dashboard(self, tenant_id: str, *, scope: str = "user") -> ProjectionResponse:
        tenant_id = self._tenant(tenant_id)
        read = self.reader.dashboard_summary(tenant_id)
        self._read_contract(read, max_queries=2)
        payload = {
            "schemaVersion": SCHEMA_VERSION,
            "revision": read.revision,
            "summary": dict(read.payload),
        }
        return self._finalize(payload, cache_hit=False, query_count=read.query_count, max_gzip_bytes=BASE_MAX_GZIP_BYTES)

    def runs(
        self,
        tenant_id: str,
        *,
        cursor: str | None,
        page_size: int,
        search: str = "",
        scope: str = "user",
    ) -> ProjectionResponse:
        tenant_id = self._tenant(tenant_id)
        if not 1 <= page_size <= MAX_PAGE_SIZE:
            raise TenantProjectionError("invalid_request", "分页大小无效。")
        search = str(search or "").strip()
        if len(search.encode("utf-8")) > MAX_SEARCH_BYTES:
            raise TenantProjectionError("invalid_request", "检索条件过长。")
        if cursor is not None and (not cursor or len(cursor) > 512):
            raise TenantProjectionError("invalid_request", "分页游标无效。")
        page = self.reader.list_run_summaries(
            tenant_id,
            cursor=cursor,
            page_size=page_size,
            search=search,
        )
        if page.query_count < 1 or page.query_count > 2 or not page.revision:
            raise TenantProjectionError("projection_contract_violation", "运行摘要读取超出契约。")
        if len(page.items) > page_size:
            raise TenantProjectionError("projection_contract_violation", "运行摘要分页超出契约。")
        items = [self._run_summary(item) for item in page.items]
        payload = {
            "schemaVersion": SCHEMA_VERSION,
            "revision": page.revision,
            "items": items,
            "nextCursor": page.next_cursor,
            "pageSize": page_size,
        }
        return self._finalize(payload, cache_hit=False, query_count=page.query_count, max_gzip_bytes=BASE_MAX_GZIP_BYTES)

    def assets(
        self,
        tenant_id: str,
        *,
        cursor: str | None,
        page_size: int,
        scope: str = "user",
    ) -> ProjectionResponse:
        tenant_id = self._tenant(tenant_id)
        if not 1 <= page_size <= MAX_PAGE_SIZE:
            raise TenantProjectionError("invalid_request", "分页大小无效。")
        if cursor is not None and (not cursor or len(cursor) > 512):
            raise TenantProjectionError("invalid_request", "分页游标无效。")
        page = self.reader.list_source_assets(
            tenant_id,
            cursor=cursor,
            page_size=page_size,
        )
        if page.query_count != 1 or not page.revision:
            raise TenantProjectionError("projection_contract_violation", "素材摘要读取超出契约。")
        if len(page.items) > page_size:
            raise TenantProjectionError("projection_contract_violation", "素材摘要分页超出契约。")
        payload = {
            "schemaVersion": SCHEMA_VERSION,
            "revision": page.revision,
            "items": [self._asset_summary(item) for item in page.items],
            "nextCursor": page.next_cursor,
            "pageSize": page_size,
        }
        return self._finalize(payload, cache_hit=False, query_count=page.query_count, max_gzip_bytes=BASE_MAX_GZIP_BYTES)

    def run_base(
        self,
        tenant_id: str,
        public_run_id: str,
        *,
        scope: str = "user",
    ) -> ProjectionResponse:
        tenant_id = self._tenant(tenant_id)
        run_id = self._run_id(public_run_id)
        owner = self._authorize_run(tenant_id, run_id)
        key = (scope, tenant_id, run_id, "base", owner.revision)
        cached = self._get(key)
        if cached is not None:
            return cached
        read = self.reader.run_base_detail(tenant_id, run_id)
        self._read_contract(read, max_queries=1, expected_revision=owner.revision)
        payload = {
            "schemaVersion": SCHEMA_VERSION,
            "publicRunId": run_id,
            "revision": read.revision,
            "base": dict(read.payload),
            "availableSections": sorted(RUN_SECTIONS),
        }
        response = self._finalize(
            payload,
            cache_hit=False,
            query_count=1 + read.query_count,
            max_gzip_bytes=BASE_MAX_GZIP_BYTES,
        )
        self._put(key, response)
        return response

    def run_section(
        self,
        tenant_id: str,
        public_run_id: str,
        section: str,
        *,
        scope: str = "user",
    ) -> ProjectionResponse:
        tenant_id = self._tenant(tenant_id)
        run_id = self._run_id(public_run_id)
        section = str(section or "").strip()
        if section not in RUN_SECTIONS:
            raise TenantProjectionError("resource_not_found", "未找到该运行详情分区。")
        owner = self._authorize_run(tenant_id, run_id)
        key = (scope, tenant_id, run_id, section, owner.revision)
        cached = self._get(key)
        if cached is not None:
            return cached
        read = self.reader.run_section(tenant_id, run_id, section)
        self._read_contract(read, max_queries=2, expected_revision=owner.revision)
        payload = {
            "schemaVersion": SCHEMA_VERSION,
            "publicRunId": run_id,
            "revision": read.revision,
            "section": section,
            "data": dict(read.payload),
        }
        response = self._finalize(
            payload,
            cache_hit=False,
            query_count=1 + read.query_count,
            max_gzip_bytes=SECTION_MAX_GZIP_BYTES,
        )
        self._put(key, response)
        return response

    def invalidate_run(self, tenant_id: str, public_run_id: str) -> int:
        tenant_id = self._tenant(tenant_id)
        run_id = self._run_id(public_run_id)
        with self._lock:
            keys = [key for key in self._cache if key[1] == tenant_id and key[2] == run_id]
            for key in keys:
                self._cache.pop(key, None)
        return len(keys)

    def invalidate_tenant(self, tenant_id: str) -> int:
        tenant_id = self._tenant(tenant_id)
        with self._lock:
            keys = [key for key in self._cache if key[1] == tenant_id]
            for key in keys:
                self._cache.pop(key, None)
        return len(keys)

    def _authorize_run(self, tenant_id: str, run_id: str) -> RunOwnerFact:
        try:
            fact = self.owner_accessor.resolve_run_owner(run_id)
        except Exception as exc:
            raise TenantProjectionError("projection_unavailable", "运行归属暂时不可用。") from exc
        if fact is None or fact.tenant_id != tenant_id:
            raise TenantProjectionError("resource_not_found", "未找到该资源。")
        if not fact.revision:
            raise TenantProjectionError("projection_contract_violation", "运行归属缺少版本。")
        return fact

    def _get(self, key: tuple[str, str, str, str, str]) -> ProjectionResponse | None:
        now = self.clock()
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            if entry.expires_at <= now:
                self._cache.pop(key, None)
                return None
            self._cache.move_to_end(key)
            response = entry.response
        return ProjectionResponse(response.payload, response.etag, True, 1, response.gzip_bytes)

    def _put(self, key: tuple[str, str, str, str, str], response: ProjectionResponse) -> None:
        with self._lock:
            self._cache[key] = _CacheEntry(response=response, expires_at=self.clock() + self.cache_ttl_seconds)
            self._cache.move_to_end(key)
            while len(self._cache) > self.max_cache_entries:
                self._cache.popitem(last=False)

    @staticmethod
    def _read_contract(read: ProjectionRead, *, max_queries: int, expected_revision: str = "") -> None:
        if not read.revision or read.query_count < 1 or read.query_count > max_queries:
            raise TenantProjectionError("projection_contract_violation", "投影读取超出契约。")
        if expected_revision and read.revision != expected_revision:
            raise TenantProjectionError("projection_revision_conflict", "运行数据已更新，请重试。")

    @staticmethod
    def _run_summary(item: Mapping[str, Any]) -> dict[str, Any]:
        allowed = {"publicRunId", "title", "status", "entrypoint", "createdAt", "updatedAt"}
        if not isinstance(item, Mapping) or set(item) - allowed or not item.get("publicRunId"):
            raise TenantProjectionError("projection_contract_violation", "运行摘要字段超出契约。")
        return dict(item)

    @staticmethod
    def _asset_summary(item: Mapping[str, Any]) -> dict[str, Any]:
        allowed = {"publicAssetId", "createdAt"}
        public_id = str(item.get("publicAssetId") or "") if isinstance(item, Mapping) else ""
        if (
            not isinstance(item, Mapping)
            or set(item) - allowed
            or not re.fullmatch(r"asset_[a-f0-9]{16}", public_id)
        ):
            raise TenantProjectionError("projection_contract_violation", "素材摘要字段超出契约。")
        return dict(item)

    @classmethod
    def _finalize(
        cls,
        payload: dict[str, Any],
        *,
        cache_hit: bool,
        query_count: int,
        max_gzip_bytes: int,
    ) -> ProjectionResponse:
        cls._assert_public_payload(payload)
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        compressed_size = len(gzip.compress(encoded, compresslevel=6))
        if compressed_size > max_gzip_bytes:
            raise TenantProjectionError("projection_too_large", "投影响应超过大小限制。")
        etag = '"' + hashlib.sha256(encoded).hexdigest() + '"'
        return ProjectionResponse(payload, etag, cache_hit, query_count, compressed_size)

    @classmethod
    def _assert_public_payload(cls, value: Any, *, key: str = "") -> None:
        forbidden_keys = {
            "tenant_id", "tenantid", "owner_id", "record_id", "recordid", "table_id", "tableid",
            "view_id", "viewid", "app_token", "apptoken", "base_id", "baseid", "raw_prompt",
            "raw_response", "traceback", "stack_trace", "access_token", "refresh_token", "cookie",
        }
        if key.replace("-", "").replace("_", "").lower() in {item.replace("_", "") for item in forbidden_keys}:
            raise TenantProjectionError("projection_contract_violation", "投影包含禁止字段。")
        if isinstance(value, Mapping):
            for child_key, item in value.items():
                cls._assert_public_payload(item, key=str(child_key))
            return
        if isinstance(value, (list, tuple)):
            for item in value:
                cls._assert_public_payload(item)
            return
        if isinstance(value, str):
            lowered = value.lower()
            forbidden_tokens = ("/home/", "media://", "raw_prompt", "raw_response", "traceback", "stack_trace")
            if any(token in lowered for token in forbidden_tokens):
                raise TenantProjectionError("projection_contract_violation", "投影包含禁止内容。")
            if "feishu.cn/base/" in lowered or "feishu.cn/bitable/" in lowered:
                raise TenantProjectionError("projection_contract_violation", "投影包含禁止的 Base 链接。")

    @staticmethod
    def _tenant(value: str) -> str:
        tenant_id = str(value or "").strip()
        return canonical_tenant_id(
            tenant_id,
            error=lambda: TenantProjectionError("invalid_tenant", "租户身份无效。"),
        )

    @staticmethod
    def _run_id(value: str) -> str:
        run_id = str(value or "").strip()
        if not run_id.startswith("run_") or len(run_id) > 160 or not all(char.isalnum() or char in "_-" for char in run_id):
            raise TenantProjectionError("resource_not_found", "未找到该资源。")
        return run_id
