from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from integrations.feishu.media_writer import (
    MediaModelFeishuWriterError,
    _register_entity_docx_link,
    upsert_entity_record,
    upsert_global_entity_record,
    write_entity_record,
)
from openclaw_app.services.resource_owner_registry import (
    ResourceOwnerProjectionMismatch,
    ResourceOwnerRegistry,
)
from openclaw_app.services.tenant_owned_resources import TenantOwnedResourceService


TENANT_A = "618ff8c4-cc5a-4034-a2c5-226e3ad6cd37"
TENANT_B = "775e0c03-febc-4a39-8ad0-3e18bb8a6d45"


def source_asset_payload() -> dict[str, object]:
    return {
        "asset_id": "asset_feishu_1",
        "source_asset_id": "source_asset_101",
        "content_fingerprint": "sha256:" + "a" * 64,
        "title": "租户素材",
        "platform": "抖音",
        "source_url": "https://example.test/video/1",
        "evidence_uri": f"media://tenants/{TENANT_A}/source_assets/source_asset_101/evidence.json",
        "status": "candidate",
        "enabled": True,
    }


def owner_service(tmp_path: Path) -> TenantOwnedResourceService:
    return TenantOwnedResourceService(ResourceOwnerRegistry(tmp_path / "owners.sqlite3"))


def test_upsert_creates_owner_before_exact_canonical_key_query(tmp_path: Path) -> None:
    service = owner_service(tmp_path)
    observed: dict[str, object] = {}

    def list_records(table_url: str, *, page_size: int, filter_formula: str):
        observed.update(
            table_url=table_url,
            page_size=page_size,
            filter_formula=filter_formula,
            owner=service.registry.get("media.source_asset", "asset_feishu_1"),
        )
        return []

    with (
        patch("integrations.feishu.media_writer.canonical_tenant_owned_resources", return_value=service),
        patch("integrations.feishu.media_writer.feishu_list_records", side_effect=list_records),
        patch("integrations.feishu.media_writer.write_entity_record", return_value={"mode": "write", "record_id": "rec_1"}),
    ):
        result = upsert_entity_record(
            "SourceAsset",
            "https://example.test/base/app?table=source",
            source_asset_payload(),
            session_tenant_id=TENANT_A,
            key_field="asset_id",
        )

    assert result["mode"] == "write"
    assert observed["page_size"] == 10
    assert observed["filter_formula"] == 'CurrentValue.[素材ID] = "asset_feishu_1"'
    assert observed["owner"].tenant_id == TENANT_A


def test_write_projection_mismatch_queues_repair_and_fails_closed(tmp_path: Path) -> None:
    service = owner_service(tmp_path)
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "code": 0,
        "data": {"record": {"record_id": "rec_mismatch"}},
    }
    field_types = {
        "素材ID": 1,
        "SourceAsset来源ID": 1,
        "内容指纹": 1,
        "标题": 1,
        "平台": 3,
        "来源链接": 15,
        "证据URI": 1,
        "素材状态": 3,
        "启用": 7,
        "租户ID": 1,
    }

    with (
        patch("integrations.feishu.media_writer.canonical_tenant_owned_resources", return_value=service),
        patch("integrations.feishu.media_writer.feishu_bitable_refs", return_value=("app", "table", "token")),
        patch("integrations.feishu.media_writer.feishu_field_types", return_value=field_types),
        patch("integrations.feishu.media_writer.requests.post", return_value=response),
        patch(
            "integrations.feishu.media_writer.read_entity_record",
            return_value={"record_id": "rec_mismatch", "fields": {"租户ID": TENANT_B}},
        ),
    ):
        with pytest.raises(ResourceOwnerProjectionMismatch):
            write_entity_record(
                "SourceAsset",
                "https://example.test/base/app?table=source",
                source_asset_payload(),
                session_tenant_id=TENANT_A,
            )

    repairs = service.registry.list_repairs()
    assert len(repairs) == 1
    assert repairs[0].canonical_tenant_id == TENANT_A
    assert repairs[0].observed_tenant_id == TENANT_B


def test_global_track_registry_is_read_only_before_network_access(tmp_path: Path) -> None:
    service = owner_service(tmp_path)
    with patch("integrations.feishu.media_writer.canonical_tenant_owned_resources", return_value=service):
        with pytest.raises(MediaModelFeishuWriterError, match="global read-only"):
            upsert_entity_record(
                "TrackRegistry",
                "https://example.test/base/app?table=tracks",
                {"track_id": "track_global"},
                session_tenant_id=TENANT_A,
                key_field="track_id",
            )


def test_global_track_registry_writer_requires_maintainer_before_network_access() -> None:
    with patch("integrations.feishu.media_writer.feishu_bitable_refs") as refs:
        with pytest.raises(MediaModelFeishuWriterError, match="maintainer authorization"):
            upsert_global_entity_record(
                "TrackRegistry",
                "https://example.test/base/app?table=tracks",
                {"track_id": "track_global", "track_name": "全局赛道", "status": "active"},
                key_field="track_id",
                maintainer_authorized=False,
            )
    refs.assert_not_called()


def test_global_track_registry_writer_reads_back_exact_key() -> None:
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {"code": 0, "data": {"record": {"record_id": "rec_track"}}}
    payload = {
        "track_id": "track_global",
        "track_name": "全局赛道",
        "platform_scope": ["小红书", "抖音"],
        "status": "active",
        "alias_names": [],
    }
    with (
        patch("integrations.feishu.media_writer.feishu_bitable_refs", return_value=("app", "table", "token")),
        patch(
            "integrations.feishu.media_writer.feishu_field_types",
            return_value={"赛道ID": 1, "赛道名称": 1, "适用平台": 4, "状态": 3, "赛道别名": 4},
        ),
        patch("integrations.feishu.media_writer.feishu_list_records", return_value=[]),
        patch("integrations.feishu.media_writer.requests.post", return_value=response),
        patch(
            "integrations.feishu.media_writer.read_entity_record",
            return_value={
                "record_id": "rec_track",
                "fields": {"赛道ID": "track_global", "赛道名称": "全局赛道", "适用平台": ["小红书", "抖音"], "状态": "active"},
            },
        ),
    ):
        result = upsert_global_entity_record(
            "TrackRegistry",
            "https://example.test/base/app?table=tracks",
            payload,
            key_field="track_id",
            maintainer_authorized=True,
        )

    assert result["mode"] == "write"
    assert result["readback_payload"]["track_id"] == "track_global"


def test_media_model_docx_fields_route_to_canonical_resource_access() -> None:
    service = Mock()
    _register_entity_docx_link(
        service,
        "PublishedPost",
        "media.post_review",
        "post_review_101",
        TENANT_A,
        {"review_doc_link": "https://tenant.feishu.cn/docx/DoxcnReviewOwned101"},
    )
    service.register_docx_link.assert_called_once_with(
        "media.post_review",
        "post_review_101",
        session_tenant_id=TENANT_A,
        document_url="https://tenant.feishu.cn/docx/DoxcnReviewOwned101",
        policy="org_link_edit",
    )


def test_non_document_entity_does_not_register_resource_link() -> None:
    service = Mock()
    _register_entity_docx_link(
        service,
        "MetricSnapshot",
        "media.metric_snapshot",
        "snapshot_101",
        TENANT_A,
        {"evidence_uri": f"media://tenants/{TENANT_A}/reviews/evidence.json"},
    )
    service.register_docx_link.assert_not_called()
