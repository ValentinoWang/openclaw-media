from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from openclaw_app.models.message import Message
from openclaw_app.router.deletion import DeletionMixin
from openclaw_app.router.deletion_adapters.base import (
    DeletionContext,
    resolve_media_registry_table,
)
from openclaw_app.router.deletion_adapters import deletion_adapters
from openclaw_app.services.resource_owner_registry import ResourceOwnerConflict, ResourceOwnerRegistry
from openclaw_app.services.tenant_owned_resources import TenantOwnedResourceService
from selfmedia.growth import review_public_id, source_asset_public_id

from _fixtures.markdown import write_frontmatter

TENANT_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
TENANT_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


class FakeFeishuService:
    def __init__(self) -> None:
        self.records: dict[tuple[str, str, str], dict[str, Any]] = {}
        self.docs: dict[str, bool] = {}
        self.events: dict[tuple[str, str], dict[str, Any]] = {}

    def read_bitable_record(self, app_token: str, table_id: str, record_id: str) -> dict[str, Any]:
        key = (app_token, table_id, record_id)
        if key not in self.records:
            raise RuntimeError("record not found")
        return self.records[key]

    def list_bitable_records(self, app_token: str, table_id: str, *, page_size: int = 500, filter_formula: str = "") -> list[dict[str, Any]]:
        del page_size, filter_formula
        return [
            {"record_id": record_id, **record}
            for (record_app, record_table, record_id), record in self.records.items()
            if record_app == app_token and record_table == table_id
        ]

    def delete_bitable_record(self, app_token: str, table_id: str, record_id: str) -> dict[str, Any]:
        self.records.pop((app_token, table_id, record_id), None)
        return {"ok": True}

    def delete_calendar_event(self, calendar_id: str, event_id: str) -> dict[str, Any]:
        self.events.pop((calendar_id, event_id), None)
        return {"ok": True}

    def read_calendar_event(self, calendar_id: str, event_id: str) -> dict[str, Any]:
        key = (calendar_id, event_id)
        if key not in self.events:
            raise RuntimeError("event not found")
        return self.events[key]


class FakeReminderService:
    def __init__(self) -> None:
        self.records = {"recReminder"}

    def delete(self, *, record_id: str, dry_run: bool = False, delete_calendar: bool = True, config_path_key: str | None = None) -> dict[str, Any]:
        if dry_run:
            return {"ok": True, "data": {"record_id": record_id}}
        self.records.discard(record_id)
        return {"ok": True, "data": {"readback": {"exists": False}}}


class FakeSourceAssetProjection:
    def __init__(self, asset_ids: list[str] | None = None, *, fail_delete: bool = False) -> None:
        self.asset_ids = set(asset_ids or [])
        self.fail_delete = fail_delete
        self.delete_calls: list[tuple[str, str]] = []

    def exists(self, tenant_id: str, public_asset_id: str) -> bool:
        del tenant_id
        return public_asset_id in self.asset_ids

    def delete(self, tenant_id: str, public_asset_id: str) -> bool:
        self.delete_calls.append((tenant_id, public_asset_id))
        if self.fail_delete:
            raise RuntimeError("canonical PostgreSQL asset delete failed")
        existed = public_asset_id in self.asset_ids
        self.asset_ids.discard(public_asset_id)
        return existed


class DeletionPhase2Harness(DeletionMixin):
    def __init__(
        self,
        workspace_root: Path,
        feishu: FakeFeishuService | None = None,
        reminder: FakeReminderService | None = None,
        media_feishu: FakeFeishuService | None = None,
        source_asset_projection: FakeSourceAssetProjection | None = None,
    ):
        self.workspace_root = workspace_root
        self.feishu_service = feishu
        self.media_source_feishu_service = media_feishu
        self.reminder_service = reminder
        self.tenant_id = TENANT_A
        self.tenant_owned_resources = TenantOwnedResourceService(
            ResourceOwnerRegistry(workspace_root / "resource_owners.sqlite3")
        )
        owner_source = media_feishu or feishu
        source_asset_ids = []
        for record in (owner_source.records.values() if owner_source is not None else []):
            fields = record.get("fields") or {}
            if fields.get("素材ID"):
                source_asset_ids.append(str(fields["素材ID"]))
            identities = (
                ("media.source_asset", fields.get("素材ID")),
                ("media.post_review", fields.get("发布作品ID")),
                ("media.metric_snapshot", fields.get("快照ID")),
            )
            for resource_type, resource_id in identities:
                if not resource_id:
                    continue
                try:
                    self.tenant_owned_resources.registry.create(
                        resource_type,
                        str(resource_id),
                        session_tenant_id=self.tenant_id,
                    )
                except ResourceOwnerConflict:
                    pass
        self.source_asset_projection = source_asset_projection or FakeSourceAssetProjection(
            source_asset_ids
        )

    def _creation_cleanup_script_path(self) -> Path:
        return Path(__file__).resolve()

    def _deletion_allowed_roots(self) -> list[Path]:
        return [self.workspace_root]

    def _deletion_context(self) -> DeletionContext:
        return DeletionContext(
            workspace_root=self.workspace_root,
            allowed_roots=[self.workspace_root],
            creation_cleanup_script_path=self._creation_cleanup_script_path(),
            feishu_service=self.feishu_service,
            media_feishu_service=self.media_source_feishu_service,
            reminder_service=self.reminder_service,
            tenant_id=self.tenant_id,
            tenant_owned_resources=self.tenant_owned_resources,
            source_asset_projection=self.source_asset_projection,
            media_registry_path=self.workspace_root / "media-bitable-registry.json",
            content_os_vault_root=self.workspace_root,
        )


def deletion_message(body: str) -> Message:
    return Message(
        entry_tag="删除",
        raw_text=f"【删除】{body}",
        body=body,
        source="feishu",
        chat_type="private",
        created_at=datetime.now(),
        metadata={"account_id": "media", "tenant_id": TENANT_A},
    )


class Phase2DeletionAdaptersTest(unittest.TestCase):
    def test_current_list_registry_requires_one_exact_binding(self) -> None:
        with self.assertRaisesRegex(ValueError, "未登记 source_asset"):
            resolve_media_registry_table(
                {
                    "tables": [{
                        "table_key": "source_assets",
                        "base_token": "appWrong",
                        "table_id": "tblWrong",
                    }]
                },
                legacy_key="source_assets",
                table_key="source_asset",
            )

        with self.assertRaisesRegex(ValueError, "重复登记 source_asset"):
            resolve_media_registry_table(
                {
                    "tables": [
                        {
                            "table_key": "source_asset",
                            "base_token": "appMedia",
                            "table_id": "tblSourceAssets1",
                        },
                        {
                            "table_key": "source_asset",
                            "base_token": "appMedia",
                            "table_id": "tblSourceAssets2",
                        },
                    ]
                },
                legacy_key="source_assets",
                table_key="source_asset",
            )

    def test_registry_rejects_conflicting_token_aliases(self) -> None:
        with self.assertRaisesRegex(ValueError, "app_token/base_token 冲突"):
            resolve_media_registry_table(
                {
                    "tables": [{
                        "table_key": "source_asset",
                        "app_token": "appLegacy",
                        "base_token": "appCurrent",
                        "table_id": "tblSourceAssets",
                    }]
                },
                legacy_key="source_assets",
                table_key="source_asset",
            )

    def test_source_asset_previews_with_current_list_registry_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "media-bitable-registry.json").write_text(json.dumps({
                "tables": [{
                    "table_key": "source_asset",
                    "base_token": "appMedia",
                    "table_id": "tblSourceAssets",
                }]
            }), encoding="utf-8")
            public_id = "asset_item_20260729_list_registry"
            feishu = FakeFeishuService()
            record_key = ("appMedia", "tblSourceAssets", "recListRegistryAsset")
            feishu.records[record_key] = {
                "fields": {"素材ID": public_id, "标题": "当前注册表素材", "租户ID": TENANT_A}
            }

            preview = DeletionPhase2Harness(root, media_feishu=feishu).handle_删除(
                deletion_message(public_id)
            )

            self.assertTrue(preview.ok)
            self.assertIn("删除预览", preview.reply)
            self.assertIn(public_id, preview.reply)
            self.assertIn(record_key, feishu.records)

    def test_source_asset_page_id_previews_without_user_feishu_binding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "media-bitable-registry.json").write_text(json.dumps({
                "tables": {"source_assets": {"app_token": "appMedia", "table_id": "tblSourceAssets"}}
            }), encoding="utf-8")
            public_id = "asset_item_20260729_fixture"
            feishu = FakeFeishuService()
            record_key = ("appMedia", "tblSourceAssets", "recSourceAssetPageId")
            feishu.records[record_key] = {
                "fields": {"素材ID": public_id, "标题": "C端素材", "租户ID": TENANT_A}
            }

            preview = DeletionPhase2Harness(root, media_feishu=feishu).handle_删除(deletion_message(public_id))

            self.assertTrue(preview.ok)
            self.assertIn("删除预览", preview.reply)
            self.assertIn(public_id, preview.reply)
            self.assertIn(record_key, feishu.records)

    def test_review_previews_with_current_list_registry_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "media-bitable-registry.json").write_text(json.dumps({
                "tables": [
                    {
                        "table_key": "post_review",
                        "base_token": "appMedia",
                        "table_id": "tblPostReviews",
                    },
                    {
                        "table_key": "post_metric_snapshot",
                        "base_token": "appMedia",
                        "table_id": "tblMetrics",
                    },
                ]
            }), encoding="utf-8")
            post_id = "post_review_20260730_list_registry"
            review_key = ("appMedia", "tblPostReviews", "recListRegistryReview")
            metric_key = ("appMedia", "tblMetrics", "recListRegistryMetric")
            feishu = FakeFeishuService()
            feishu.records[review_key] = {
                "fields": {"发布作品ID": post_id, "平台": "小红书", "租户ID": TENANT_A}
            }
            feishu.records[metric_key] = {
                "fields": {"快照ID": "snapshot_list_registry", "发布作品ID": post_id, "租户ID": TENANT_A}
            }

            preview = DeletionPhase2Harness(root, feishu).handle_删除(
                deletion_message(review_public_id(post_id))
            )

            self.assertTrue(preview.ok)
            self.assertIn("级联 1 条 H01 指标快照", preview.reply)
            self.assertIn(review_key, feishu.records)
            self.assertIn(metric_key, feishu.records)

    def test_source_asset_public_reference_previews_then_deletes_with_readback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry = {
                "tables": {
                    "source_assets": {
                        "app_token": "appMedia",
                        "table_id": "tblSourceAssets",
                    }
                }
            }
            (root / "media-bitable-registry.json").write_text(json.dumps(registry), encoding="utf-8")
            raw_asset_id = "asset_item_20260729_fixture"
            public_id = source_asset_public_id(raw_asset_id)
            feishu = FakeFeishuService()
            record_key = ("appMedia", "tblSourceAssets", "recSourceAsset")
            feishu.records[record_key] = {"fields": {"素材ID": raw_asset_id, "标题": "删除契约测试素材", "租户ID": TENANT_A}}
            projection = FakeSourceAssetProjection([raw_asset_id])
            harness = DeletionPhase2Harness(
                root,
                feishu,
                source_asset_projection=projection,
            )

            preview = harness.handle_删除(deletion_message(public_id))

            self.assertTrue(preview.ok)
            self.assertIn("删除预览", preview.reply)
            self.assertIn(public_id, preview.reply)
            self.assertNotIn("recSourceAsset", preview.reply)
            self.assertIn(record_key, feishu.records)

            applied = harness.handle_删除(deletion_message(f"确认删除 {public_id}"))

            self.assertTrue(applied.ok)
            self.assertIn("已删除", applied.reply)
            self.assertNotIn(record_key, feishu.records)
            self.assertFalse(projection.exists(TENANT_A, raw_asset_id))

    def test_source_asset_delete_fails_if_postgres_projection_remains(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "media-bitable-registry.json").write_text(json.dumps({
                "tables": {"source_assets": {"app_token": "appMedia", "table_id": "tblSourceAssets"}}
            }), encoding="utf-8")
            asset_id = "asset_item_20260729_projection_failure"
            record_key = ("appMedia", "tblSourceAssets", "recProjectionFailure")
            feishu = FakeFeishuService()
            feishu.records[record_key] = {
                "fields": {"素材ID": asset_id, "标题": "投影删除失败", "租户ID": TENANT_A}
            }
            projection = FakeSourceAssetProjection([asset_id], fail_delete=True)
            harness = DeletionPhase2Harness(
                root,
                media_feishu=feishu,
                source_asset_projection=projection,
            )

            applied = harness.handle_删除(deletion_message(f"确认删除 {asset_id}"))

            self.assertFalse(applied.ok)
            self.assertEqual(applied.status, "deletion_failed")
            self.assertTrue(projection.exists(TENANT_A, asset_id))
            owner = harness.tenant_owned_resources.registry.get("media.source_asset", asset_id)
            self.assertEqual(owner.status, "active")

    def test_source_asset_retry_cleans_postgres_residue_after_owner_was_archived(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "media-bitable-registry.json").write_text(json.dumps({
                "tables": {"source_assets": {"app_token": "appMedia", "table_id": "tblSourceAssets"}}
            }), encoding="utf-8")
            asset_id = "asset_item_20260729_archived_residue"
            projection = FakeSourceAssetProjection([asset_id])
            harness = DeletionPhase2Harness(
                root,
                media_feishu=FakeFeishuService(),
                source_asset_projection=projection,
            )
            harness.tenant_owned_resources.registry.create(
                "media.source_asset",
                asset_id,
                session_tenant_id=TENANT_A,
            )
            harness.tenant_owned_resources.registry.archive(
                "media.source_asset",
                asset_id,
                session_tenant_id=TENANT_A,
            )

            applied = harness.handle_删除(deletion_message(f"确认删除 {asset_id}"))

            self.assertTrue(applied.ok)
            self.assertIn("已删除", applied.reply)
            self.assertFalse(projection.exists(TENANT_A, asset_id))

    def test_source_asset_delete_uses_media_service_for_delete_and_readback(self) -> None:
        class ForbiddenGeneralFeishuService(FakeFeishuService):
            def __init__(self) -> None:
                super().__init__()
                self.delete_calls = 0

            def delete_bitable_record(self, app_token: str, table_id: str, record_id: str) -> dict[str, Any]:
                del app_token, table_id, record_id
                self.delete_calls += 1
                raise RuntimeError("status=403 permission denied")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "media-bitable-registry.json").write_text(json.dumps({
                "tables": [{
                    "table_key": "source_asset",
                    "base_token": "appMedia",
                    "table_id": "tblSourceAssets",
                }]
            }), encoding="utf-8")
            public_id = "asset_item_20260729_media_service_delete"
            record_key = ("appMedia", "tblSourceAssets", "recMediaServiceDelete")
            media_feishu = FakeFeishuService()
            media_feishu.records[record_key] = {
                "fields": {"素材ID": public_id, "标题": "媒体服务删除测试", "租户ID": TENANT_A}
            }
            general_feishu = ForbiddenGeneralFeishuService()
            harness = DeletionPhase2Harness(
                root,
                feishu=general_feishu,
                media_feishu=media_feishu,
            )

            preview = harness.handle_删除(deletion_message(public_id))
            applied = harness.handle_删除(deletion_message(f"确认删除 {public_id}"))

            self.assertTrue(preview.ok)
            self.assertTrue(applied.ok)
            self.assertIn("已删除", applied.reply)
            self.assertNotIn(record_key, media_feishu.records)
            self.assertEqual(general_feishu.delete_calls, 0)

    def test_source_asset_public_reference_cannot_cross_tenant_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry = {
                "tables": {
                    "source_assets": {
                        "app_token": "appMedia",
                        "table_id": "tblSourceAssets",
                    }
                }
            }
            (root / "media-bitable-registry.json").write_text(json.dumps(registry), encoding="utf-8")
            raw_asset_id = "asset_owned_by_tenant_202"
            public_id = source_asset_public_id(raw_asset_id)
            feishu = FakeFeishuService()
            harness = DeletionPhase2Harness(root, feishu)
            harness.tenant_owned_resources.registry.create(
                "media.source_asset",
                raw_asset_id,
                session_tenant_id=TENANT_B,
            )
            record_key = ("appMedia", "tblSourceAssets", "recOtherTenant")
            feishu.records[record_key] = {
                "fields": {
                    "素材ID": raw_asset_id,
                    "标题": "其他租户私有素材",
                    "租户ID": TENANT_B,
                }
            }

            preview = harness.handle_删除(deletion_message(public_id))

            self.assertTrue(preview.ok)
            self.assertIn("已无此记录", preview.reply)
            self.assertNotIn("其他租户私有素材", preview.reply)
            self.assertNotIn("recOtherTenant", preview.reply)
            self.assertIn(record_key, feishu.records)

    def test_review_public_reference_cascade_deletes_metrics_before_main_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry = {
                "tables": {
                    "post_reviews": {"app_token": "appMedia", "table_id": "tblPostReviews"},
                    "metric_snapshot": {"app_token": "appMedia", "table_id": "tblMetrics"},
                }
            }
            (root / "media-bitable-registry.json").write_text(json.dumps(registry), encoding="utf-8")
            post_id = "post_review_20260730_fixture"
            public_id = review_public_id(post_id)
            review_key = ("appMedia", "tblPostReviews", "recReview")
            metric_keys = [
                ("appMedia", "tblMetrics", "recMetricLikes"),
                ("appMedia", "tblMetrics", "recMetricSaves"),
            ]
            feishu = FakeFeishuService()
            feishu.records[review_key] = {
                "fields": {"发布作品ID": post_id, "平台": "小红书", "复盘节点": "发布后 24 小时", "租户ID": TENANT_A}
            }
            for index, key in enumerate(metric_keys, start=1):
                feishu.records[key] = {"fields": {"快照ID": f"snapshot_{index}", "发布作品ID": post_id, "租户ID": TENANT_A}}

            preview = DeletionPhase2Harness(root, feishu).handle_删除(deletion_message(public_id))

            self.assertTrue(preview.ok)
            self.assertIn("级联 2 条 H01 指标快照", preview.reply)
            self.assertNotIn("recReview", preview.reply)
            self.assertIn(review_key, feishu.records)
            self.assertTrue(all(key in feishu.records for key in metric_keys))

            applied = DeletionPhase2Harness(root, feishu).handle_删除(deletion_message(f"确认删除 {public_id}"))

            self.assertTrue(applied.ok)
            self.assertIn("复盘主记录和 2 条关联指标", applied.reply)
            self.assertNotIn(review_key, feishu.records)
            self.assertTrue(all(key not in feishu.records for key in metric_keys))

    def test_review_cascade_keeps_main_record_when_metric_delete_fails(self) -> None:
        class FailingMetricFeishuService(FakeFeishuService):
            def delete_bitable_record(self, app_token: str, table_id: str, record_id: str) -> dict[str, Any]:
                if table_id == "tblMetrics":
                    raise RuntimeError("metric delete failed")
                return super().delete_bitable_record(app_token, table_id, record_id)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry = {
                "tables": {
                    "post_reviews": {"app_token": "appMedia", "table_id": "tblPostReviews"},
                    "metric_snapshot": {"app_token": "appMedia", "table_id": "tblMetrics"},
                }
            }
            (root / "media-bitable-registry.json").write_text(json.dumps(registry), encoding="utf-8")
            post_id = "post_review_20260730_metric_failure"
            review_key = ("appMedia", "tblPostReviews", "recReview")
            metric_key = ("appMedia", "tblMetrics", "recMetric")
            feishu = FailingMetricFeishuService()
            feishu.records[review_key] = {"fields": {"发布作品ID": post_id, "租户ID": TENANT_A}}
            feishu.records[metric_key] = {"fields": {"快照ID": "snapshot_failure", "发布作品ID": post_id, "租户ID": TENANT_A}}

            applied = DeletionPhase2Harness(root, feishu).handle_删除(
                deletion_message(f"确认删除 {review_public_id(post_id)}")
            )

            self.assertFalse(applied.ok)
            self.assertIn("主记录已保留", applied.reply)
            self.assertIn(review_key, feishu.records)
            self.assertIn(metric_key, feishu.records)

    def test_unowned_generic_bitable_record_delete_path_is_retired(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = "20260412-030515-qq-source-asset-0056"
            archive = root / "archive" / "materials" / f"{target}.md"
            table_url = "https://example.feishu.cn/base/appToken123?table=tblABC"
            write_frontmatter(archive, {"id": target, "entry_tag": "素材", "tenant_id": TENANT_A, "record_id": "recMaterial", "table_url": table_url})
            feishu = FakeFeishuService()
            feishu.records[("appToken123", "tblABC", "recMaterial")] = {"fields": {"标题": "素材记录"}}

            applied = DeletionPhase2Harness(root, feishu).handle_删除(deletion_message(f"确认删除 {target}"))

            self.assertTrue(applied.ok)
            self.assertIn(("appToken123", "tblABC", "recMaterial"), feishu.records)
            self.assertNotIn("多维表格记录", applied.reply)
            self.assertNotIn("bitable_record", {adapter.adapter_id for adapter in deletion_adapters()})

    def test_generic_feishu_doc_delete_path_is_retired(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = "20260412-030515-qq-创作-0056"
            archive = root / "archive" / "creation" / f"{target}.md"
            url = "https://example.feishu.cn/wiki/wik1"
            write_frontmatter(archive, {"id": target, "entry_tag": "创作", "tenant_id": TENANT_A, "feishu_doc": url, "feishu_doc_delete_allowed": "true"})
            feishu = FakeFeishuService()
            feishu.docs[url] = True

            result = DeletionPhase2Harness(root, feishu).handle_删除(deletion_message(f"确认删除 {target}"))

            self.assertTrue(result.ok)
            self.assertTrue(feishu.docs[url])
            self.assertNotIn("feishu_doc", {adapter.adapter_id for adapter in deletion_adapters()})
            operations = {
                entity["operation"]
                for plan in result.extra["deletion"]
                for entity in plan["entities"]
            }
            self.assertNotIn("feishu_delete_document_reference", operations)

    def test_reminder_calendar_adapter_deletes_record_and_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = "20260412-030515-qq-日程-0056"
            archive = root / "archive" / "daily" / f"{target}.md"
            write_frontmatter(archive, {"id": target, "entry_tag": "日程", "tenant_id": TENANT_A, "record_id": "recReminder", "calendar_id": "cal1", "event_id": "evt1"})
            feishu = FakeFeishuService()
            feishu.events[("cal1", "evt1")] = {"summary": "test"}
            reminder = FakeReminderService()

            result = DeletionPhase2Harness(root, feishu, reminder).handle_删除(deletion_message(f"确认删除 {target}"))

            self.assertTrue(result.ok)
            self.assertNotIn("recReminder", reminder.records)
            self.assertNotIn(("cal1", "evt1"), feishu.events)
            self.assertIn("提醒记录", result.reply)
            self.assertIn("日历事件", result.reply)

    def test_obsidian_block_adapter_deletes_only_anchored_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = "20260412-030515-qq-转写-0056"
            note = root / "obsidian" / "weekly.md"
            note.parent.mkdir(parents=True)
            note.write_text(
                "keep before\n<!-- openclaw-delete:20260412-030515-qq-转写-0056:start capability=转写 -->\nremove me\n<!-- openclaw-delete:20260412-030515-qq-转写-0056:end -->\nkeep after\n",
                encoding="utf-8",
            )
            archive = root / "archive" / "transcripts" / f"{target}.md"
            write_frontmatter(archive, {"id": target, "entry_tag": "转写", "tenant_id": TENANT_A, "weekly_path": note})

            preview = DeletionPhase2Harness(root).handle_删除(deletion_message(target))
            self.assertIn("remove me", note.read_text(encoding="utf-8"))
            applied = DeletionPhase2Harness(root).handle_删除(deletion_message(f"确认删除 {target}"))

            text = note.read_text(encoding="utf-8")
            self.assertTrue(preview.ok)
            self.assertTrue(applied.ok)
            self.assertIn("keep before", text)
            self.assertIn("keep after", text)
            self.assertNotIn("remove me", text)

    def test_content_os_adapter_deletes_project_queue_and_registry_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = "20260412-030515-qq-创作-0056"
            project_id = "20260412_test_project"
            task_id = "task_20260412_001"
            project_dir = root / "08_内容项目" / project_id
            queue = root / "98_Agent任务队列" / "01_cloud_to_mac_ready" / f"{task_id}_material_match.yaml"
            registry = root / "90_索引与注册表" / "project_registry.md"
            project_dir.mkdir(parents=True)
            (project_dir / "00_项目总览.md").write_text("project", encoding="utf-8")
            queue.parent.mkdir(parents=True)
            queue.write_text(yaml.safe_dump({"task_id": task_id, "project_id": project_id, "status": "ready"}, allow_unicode=True), encoding="utf-8")
            registry.parent.mkdir(parents=True)
            registry.write_text(f"| project_id | status |\n| --- | --- |\n| {project_id} | ready |\n", encoding="utf-8")
            archive = root / "archive" / "creation" / f"{target}.md"
            write_frontmatter(archive, {"id": target, "entry_tag": "创作", "tenant_id": TENANT_A, "project_id": project_id, "task_id": task_id})

            result = DeletionPhase2Harness(root).handle_删除(deletion_message(f"确认删除 {target}"))

            self.assertTrue(result.ok)
            self.assertFalse(project_dir.exists())
            self.assertFalse(queue.exists())
            self.assertNotIn(project_id, registry.read_text(encoding="utf-8"))
            self.assertIn("Mac队列任务", result.reply)


if __name__ == "__main__":
    unittest.main()
