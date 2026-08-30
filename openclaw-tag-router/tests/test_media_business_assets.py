from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from threading import Barrier, Lock
from time import sleep
from typing import Any

import pytest
from PIL import Image

from openclaw_app.services.media_business.assets import (
    AssetInternalError,
    AssetInvalidRequest,
    AssetNotFound,
    AssetPreview,
    AssetPreviewService,
    AssetsService,
)
from openclaw_app.services.media_business.foundation import TenantContext, error_status


TENANT_A = "00000000-0000-0000-0000-00000000000a"
TENANT_B = "00000000-0000-0000-0000-00000000000b"
CREATED = datetime(2026, 8, 5, 1, 2, 3, tzinfo=timezone.utc)


def source_image_bytes() -> bytes:
    output = BytesIO()
    image = Image.new("RGB", (768, 1365), color=(22, 112, 79))
    image.save(output, format="JPEG", quality=95)
    return output.getvalue()


SOURCE_IMAGE_BYTES = source_image_bytes()


def assert_thumbnail(preview: AssetPreview) -> None:
    assert preview.content_type == "image/webp"
    assert preview.filename == "cover.webp"
    assert len(preview.body) <= 256 * 1024
    with Image.open(BytesIO(preview.body)) as image:
        assert image.format == "WEBP"
        assert image.size == (320, 180)


def asset_data(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "asset_id": "asset_123456",
        "title": "A real source asset",
        "mediaType": "video",
        "platform": "xiaohongshu",
        "sourceLabel": "creator source",
        "source_url": "https://example.test/source/asset_123456",
        "platform_hashtags": ["hook", "training"],
        "trackNames": ["strength training"],
        "qualityStatus": "verified",
        "materialStatus": "parsed",
        "preview": {
            "kind": "image",
            "status": "available",
            "url": "https://cdn.example.test/preview/asset_123456.jpg",
            "expiresAt": "2026-08-05T02:02:03Z",
        },
        "evidenceRefs": [
            {
                "kind": "source",
                "label": "source link",
                "publicUrl": "https://example.test/source/asset_123456",
                "capturedAt": "2026-08-05T01:02:03Z",
                "qualityStatus": "verified",
            }
        ],
    }
    data.update(overrides)
    return data


ASSET_ROW = ("asset_123456", 3, asset_data(), CREATED, CREATED, 2)
DECONSTRUCTION_ROW = (
    "decon_123456",
    1,
    {
        "asset_id": "asset_123456",
        "analysis_scope": "全片",
        "analysis_time_range": "全部",
        "deconstruction_focus": "opening",
        "summary": "Source-backed summary",
        "hook": "Source-backed hook",
        "review_status": "reviewed",
    },
    CREATED,
)
PATTERN_ROW = (
    "pattern_123456",
    2,
    {
        "supporting_asset_ids": ["asset_123456"],
        "pattern_name": "validated opening",
        "pattern_status": "validated_pattern",
        "platform": "xiaohongshu",
        "content_type": "video",
    },
    CREATED,
)
USAGE_ROWS = [("usage_123456",), ("usage_234567",)]


class FakeResult:
    def __init__(self, rows: list[Any]) -> None:
        self.rows = rows

    def fetchone(self) -> Any:
        return self.rows[0] if self.rows else None

    def fetchall(self) -> list[Any]:
        return list(self.rows)


class FakeConnection:
    def __init__(self, *, rows: list[Any] | None = None, source_version: str = "source-version-1") -> None:
        self.rows = rows if rows is not None else [ASSET_ROW]
        self.source_version = source_version
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def execute(self, query: str, params: tuple[Any, ...] = ()) -> FakeResult:
        self.calls.append((query, params))
        if "MAX(a.updated_at)" in query:
            return FakeResult([(len(self.rows), 3 if self.rows else 0, CREATED if self.rows else None)])
        if "FROM media_product.assets" in query and "canonical_data::text" in query:
            return FakeResult(self.rows)
        if "SELECT a.canonical_data" in query and "FROM media_product.assets" in query:
            if not self.rows:
                return FakeResult([])
            result = (self.rows[0][2], self.source_version) if "a.source_version" in query else (self.rows[0][2],)
            return FakeResult([result])
        if "FROM media_product.assets" in query:
            return FakeResult(self.rows[:1])
        if "FROM media_product.material_deconstructions" in query:
            return FakeResult([DECONSTRUCTION_ROW])
        if "FROM media_product.creative_patterns" in query:
            return FakeResult([PATTERN_ROW])
        if "FROM media_product.material_usages" in query:
            return FakeResult(USAGE_ROWS)
        raise AssertionError(f"unexpected query: {query}")


def service(connection: FakeConnection) -> AssetsService:
    @contextmanager
    def factory() -> Any:
        yield connection

    return AssetsService(factory, cursor_secret=b"b03-test-cursor-secret")


def context(tenant_id: str = TENANT_A) -> TenantContext:
    return TenantContext(tenant_id=tenant_id, user_public_id="user-123456")


class PreviewFeishu:
    def __init__(self) -> None:
        self.download_tokens: list[str] = []

    def read_bitable_record(self, app_token: str, table_id: str, record_id: str) -> dict[str, Any]:
        assert (app_token, table_id, record_id) == ("base-token", "tbl_assets", "rec_asset")
        return {"fields": {"封面附件": [{"name": "cover.jpg", "file_token": "fresh-provider-token"}]}}

    def download_bitable_attachment(
        self, app_token: str, table_id: str, record_id: str, file_token: str
    ) -> dict[str, Any]:
        self.download_tokens.append(file_token)
        return {"body": SOURCE_IMAGE_BYTES, "contentType": "image/jpeg"}


class ConcurrentPreviewFeishu:
    def __init__(self) -> None:
        self._state_lock = Lock()
        self._next_token = 0
        self._active = 0
        self.max_active = 0
        self.read_tokens: list[str] = []
        self.download_tokens: list[str] = []

    def read_bitable_record(self, app_token: str, table_id: str, record_id: str) -> dict[str, Any]:
        assert (app_token, table_id, record_id) == ("base-token", "tbl_assets", "rec_asset")
        with self._state_lock:
            self._active += 1
            self.max_active = max(self.max_active, self._active)
            self._next_token += 1
            token = f"fresh-provider-token-{self._next_token}"
            self.read_tokens.append(token)
        sleep(0.01)
        return {"fields": {"封面附件": [{"name": "cover.jpg", "file_token": token}]}}

    def download_bitable_attachment(
        self, app_token: str, table_id: str, record_id: str, file_token: str
    ) -> dict[str, Any]:
        assert (app_token, table_id, record_id) == ("base-token", "tbl_assets", "rec_asset")
        sleep(0.01)
        with self._state_lock:
            self.download_tokens.append(file_token)
            self._active -= 1
        return {"body": SOURCE_IMAGE_BYTES, "contentType": "image/jpeg"}


def preview_service(
    connection: FakeConnection,
    feishu: Any,
    *,
    cache_root: Path | None = None,
) -> AssetPreviewService:
    @contextmanager
    def factory() -> Any:
        yield connection

    return AssetPreviewService(factory, feishu, base_token="base-token", cache_root=cache_root)


def test_list_projects_the_full_summary_and_keeps_scope_in_sql() -> None:
    connection = FakeConnection()
    response = service(connection).list_assets(context(), page_size=20, search="source")

    assert response["schemaVersion"] == "media_web_business_pages_v2"
    assert response["items"] == [
        {
            "publicAssetId": "asset_123456",
            "title": "A real source asset",
            "mediaType": "video",
            "platform": "xiaohongshu",
            "sourceLabel": "creator source",
            "platformHashtags": ["hook", "training"],
            "trackNames": ["strength training"],
            "qualityStatus": "verified",
            "materialStatus": "parsed",
            "createdAt": "2026-08-05T01:02:03Z",
            "usageCount": 2,
            "thumbnail": {
                "url": "https://cdn.example.test/preview/asset_123456.jpg",
                "kind": "image",
                "status": "available",
            },
        }
    ]
    list_query, list_params = next(
        (query, params) for query, params in connection.calls if "canonical_data::text" in query
    )
    assert "a.tenant_id = %s" in list_query
    assert "CAST(%s AS timestamptz) IS NULL" in list_query
    assert list_params[:3] == (TENANT_A, "source", "%source%")
    assert "media_vault" not in str(response)
    assert "local_path" not in str(response)


def test_invalid_page_size_and_search_are_rejected_before_database_access() -> None:
    connection = FakeConnection()

    with pytest.raises(AssetInvalidRequest, match="pageSize"):
        service(connection).list_assets(context(), page_size=0)
    with pytest.raises(AssetInvalidRequest, match="search"):
        service(connection).list_assets(context(), search="x" * 161)
    assert connection.calls == []


def test_empty_list_is_a_real_empty_success() -> None:
    response = service(FakeConnection(rows=[])).list_assets(context())

    assert response["items"] == []
    assert response["nextCursor"] is None
    assert response["schemaVersion"] == "media_web_business_pages_v2"


def test_cursor_is_opaque_and_bound_to_the_current_tenant() -> None:
    connection = FakeConnection(rows=[ASSET_ROW, ("asset_234567", 1, asset_data(asset_id="asset_234567"), CREATED, CREATED, 0)])
    first = service(connection).list_assets(context(), page_size=1)
    assert first["nextCursor"]

    with pytest.raises(AssetInvalidRequest, match="cursor"):
        service(connection).list_assets(context(TENANT_B), cursor=first["nextCursor"])


def test_detail_contains_evidence_preview_relations_and_usage_refs() -> None:
    connection = FakeConnection()
    response = service(connection).get_asset(context(), "asset_123456")
    detail = response["item"]

    assert response["revision"] == 3
    assert detail["summary"]["usageCount"] == 2
    pattern_query = next(query for query, _params in connection.calls if "creative_patterns" in query)
    assert "jsonb_build_array(%s::text)" in pattern_query
    assert detail["evidenceRefs"][0]["publicUrl"].startswith("https://")
    assert detail["previewDescriptor"]["url"].startswith("https://")
    assert detail["deconstructions"][0]["publicDeconstructionId"] == "decon_123456"
    assert detail["creativePatterns"][0]["publicPatternId"] == "pattern_123456"
    assert detail["usageRefs"] == ["usage_123456", "usage_234567"]


def test_missing_preview_is_explicitly_unavailable_not_fabricated() -> None:
    row = (ASSET_ROW[0], ASSET_ROW[1], asset_data(preview=None), CREATED, CREATED, 0)
    detail = service(FakeConnection(rows=[row])).get_asset(context(), "asset_123456")["item"]

    assert detail["previewDescriptor"] == {"status": "unavailable"}


def test_uncontrolled_preview_url_fails_closed() -> None:
    row = (
        ASSET_ROW[0],
        ASSET_ROW[1],
        asset_data(preview={"kind": "image", "url": "http://unsafe.test/preview.jpg"}),
        CREATED,
        CREATED,
        0,
    )

    with pytest.raises(AssetInternalError, match="controlled"):
        service(FakeConnection(rows=[row])).get_asset(context(), "asset_123456")


def test_preview_descriptor_never_returns_file_token_or_tmp_url() -> None:
    row = (
        ASSET_ROW[0],
        ASSET_ROW[1],
        asset_data(preview={
            "kind": "image",
            "status": "available",
            "url": "/openclaw/media/api/assets/asset_123456/preview",
            "file_token": "secret-file-token",
            "tmp_url": "https://open.feishu.cn/temporary/expired",
        }),
        CREATED,
        CREATED,
        0,
    )

    detail = service(FakeConnection(rows=[row])).get_asset(context(), "asset_123456")["item"]
    encoded = __import__("json").dumps(detail, ensure_ascii=False)
    assert "file_token" not in encoded
    assert "tmp_url" not in encoded
    assert detail["previewDescriptor"]["url"] == "/openclaw/media/api/assets/asset_123456/preview"


def test_preview_reads_current_attachment_only_after_tenant_scoped_lookup() -> None:
    row = (
        ASSET_ROW[0],
        ASSET_ROW[1],
        asset_data(
            source={"provider": "feishu", "table_id": "tbl_assets", "record_id": "rec_asset"},
            preview={
                "kind": "image",
                "status": "available",
                "url": "/openclaw/media/api/assets/asset_123456/preview",
                "attachmentName": "cover.jpg",
            },
        ),
        CREATED,
        CREATED,
        0,
    )
    connection = FakeConnection(rows=[row])
    feishu = PreviewFeishu()

    preview = preview_service(connection, feishu).get_preview(context(), "asset_123456")

    assert_thumbnail(preview)
    assert preview.body != SOURCE_IMAGE_BYTES
    assert feishu.download_tokens == ["fresh-provider-token"]
    query, params = connection.calls[0]
    assert "a.tenant_id = %s" in query
    assert params == (TENANT_A, "asset_123456")


def test_preview_caps_provider_concurrency_without_serializing_the_page() -> None:
    row = (
        ASSET_ROW[0],
        ASSET_ROW[1],
        asset_data(
            source={"provider": "feishu", "table_id": "tbl_assets", "record_id": "rec_asset"},
            preview={
                "kind": "image",
                "status": "available",
                "url": "/openclaw/media/api/assets/asset_123456/preview",
                "attachmentName": "cover.jpg",
            },
        ),
        CREATED,
        CREATED,
        0,
    )
    feishu = ConcurrentPreviewFeishu()
    preview = preview_service(FakeConnection(rows=[row]), feishu)
    callers_ready = Barrier(7)

    def load_preview() -> AssetPreview:
        callers_ready.wait()
        return preview.get_preview(context(), "asset_123456")

    with ThreadPoolExecutor(max_workers=7) as executor:
        results = list(executor.map(lambda _index: load_preview(), range(7)))

    assert len(results) == 7
    assert all(result.content_type == "image/webp" for result in results)
    assert all(len(result.body) <= 256 * 1024 for result in results)
    assert len(feishu.read_tokens) == 7
    assert len(set(feishu.read_tokens)) == 7
    assert sorted(feishu.download_tokens) == sorted(feishu.read_tokens)
    assert feishu.max_active == 4


def test_preview_cache_survives_service_instances_and_remains_tenant_scoped(tmp_path: Path) -> None:
    row = (
        ASSET_ROW[0],
        ASSET_ROW[1],
        asset_data(
            source={"provider": "feishu", "table_id": "tbl_assets", "record_id": "rec_asset"},
            preview={
                "kind": "image",
                "status": "available",
                "url": "/openclaw/media/api/assets/asset_123456/preview",
                "attachmentName": "cover.jpg",
            },
        ),
        CREATED,
        CREATED,
        0,
    )
    first_feishu = PreviewFeishu()
    first = preview_service(FakeConnection(rows=[row]), first_feishu, cache_root=tmp_path)

    first_preview = first.get_preview(context(), "asset_123456")
    assert_thumbnail(first_preview)
    assert first_feishu.download_tokens == ["fresh-provider-token"]

    cached_feishu = PreviewFeishu()
    cached = preview_service(FakeConnection(rows=[row]), cached_feishu, cache_root=tmp_path)
    cached_preview = cached.get_preview(context(), "asset_123456")
    assert_thumbnail(cached_preview)
    assert cached_preview.body == first_preview.body
    assert cached_feishu.download_tokens == []

    other_tenant_feishu = PreviewFeishu()
    other_tenant = preview_service(FakeConnection(rows=[row]), other_tenant_feishu, cache_root=tmp_path)
    other_tenant_preview = other_tenant.get_preview(context(TENANT_B), "asset_123456")
    assert_thumbnail(other_tenant_preview)
    assert other_tenant_feishu.download_tokens == ["fresh-provider-token"]


def test_preview_lazily_migrates_legacy_original_cache_without_provider_call(tmp_path: Path) -> None:
    row = (
        ASSET_ROW[0],
        ASSET_ROW[1],
        asset_data(
            source={"provider": "feishu", "table_id": "tbl_assets", "record_id": "rec_asset"},
            preview={
                "kind": "image",
                "status": "available",
                "url": "/openclaw/media/api/assets/asset_123456/preview",
                "attachmentName": "cover.jpg",
            },
        ),
        CREATED,
        CREATED,
        0,
    )
    cache_key = AssetPreviewService._cache_key(
        TENANT_A,
        "asset_123456",
        "source-version-1",
        "cover.jpg",
    )
    cache_path = tmp_path / f"{cache_key}.preview"
    cache_path.write_bytes(b'{"contentType":"image/jpeg"}\n' + SOURCE_IMAGE_BYTES)
    feishu = PreviewFeishu()

    preview = preview_service(FakeConnection(rows=[row]), feishu, cache_root=tmp_path).get_preview(
        context(),
        "asset_123456",
    )

    assert_thumbnail(preview)
    assert feishu.download_tokens == []
    header, body = cache_path.read_bytes().split(b"\n", 1)
    assert b'"cacheVersion":"thumbnail-webp-320x180-v1"' in header
    assert len(body) <= 256 * 1024


def test_preview_cache_invalidates_when_source_version_changes(tmp_path: Path) -> None:
    row = (
        ASSET_ROW[0],
        ASSET_ROW[1],
        asset_data(
            source={"provider": "feishu", "table_id": "tbl_assets", "record_id": "rec_asset"},
            preview={
                "kind": "image",
                "status": "available",
                "url": "/openclaw/media/api/assets/asset_123456/preview",
                "attachmentName": "cover.jpg",
            },
        ),
        CREATED,
        CREATED,
        0,
    )
    first_feishu = PreviewFeishu()
    preview_service(
        FakeConnection(rows=[row], source_version="source-version-1"),
        first_feishu,
        cache_root=tmp_path,
    ).get_preview(context(), "asset_123456")

    changed_feishu = PreviewFeishu()
    preview_service(
        FakeConnection(rows=[row], source_version="source-version-2"),
        changed_feishu,
        cache_root=tmp_path,
    ).get_preview(context(), "asset_123456")

    assert first_feishu.download_tokens == ["fresh-provider-token"]
    assert changed_feishu.download_tokens == ["fresh-provider-token"]
    assert len(list(tmp_path.glob("*.preview"))) == 2


def test_preview_cross_tenant_is_not_found_without_calling_feishu() -> None:
    feishu = PreviewFeishu()
    with pytest.raises(AssetNotFound):
        preview_service(FakeConnection(rows=[]), feishu).get_preview(context(TENANT_B), "asset_123456")
    assert feishu.download_tokens == []


def test_preview_resolves_the_base_token_once_when_not_configured_directly() -> None:
    row = (
        ASSET_ROW[0],
        ASSET_ROW[1],
        asset_data(
            source={"provider": "feishu", "table_id": "tbl_assets", "record_id": "rec_asset"},
            preview={"kind": "image", "status": "available", "attachmentName": "cover.jpg"},
        ),
        CREATED,
        CREATED,
        0,
    )
    resolved: list[str] = []
    feishu = PreviewFeishu()

    @contextmanager
    def factory() -> Any:
        yield FakeConnection(rows=[row])

    preview = AssetPreviewService(
        factory,
        feishu,
        base_token_resolver=lambda: resolved.append("called") or "base-token",
    ).get_preview(context(), "asset_123456")

    assert_thumbnail(preview)
    assert resolved == ["called"]


def test_cross_tenant_detail_is_masked_as_not_found() -> None:
    with pytest.raises(AssetNotFound):
        service(FakeConnection(rows=[])).get_asset(context(TENANT_B), "asset_123456")


def test_malformed_canonical_row_fails_closed_instead_of_filling_fields() -> None:
    malformed = (ASSET_ROW[0], ASSET_ROW[1], {"asset_id": "asset_123456"}, CREATED, CREATED, 0)
    with pytest.raises(AssetInternalError, match="canonical"):
        service(FakeConnection(rows=[malformed])).list_assets(context())


def test_error_payload_has_the_if2_error_shape() -> None:
    error = AssetNotFound()
    assert AssetsService.error_response(error) == {
        "error": {
            "code": "resource_not_found",
            "message": "asset not found",
            "field": None,
        }
    }
    assert error_status(error) == 404
