from __future__ import annotations

import os
import unittest
from datetime import datetime
from typing import Any

from openclaw_app.models.message import Message
from openclaw_app.router.commercial_delivery import CommercialDeliveryMixin, COMMERCIAL_DELIVERY_FIELD_SPECS
from openclaw_app.services.feishu_docx_renderer import NATIVE_TABLE_KIND
from openclaw_app.services.feishu_service import FeishuService


BITABLE_PREFIX = "/bitable" + "/v1/apps/"
COMMERCIAL_RECORD_WRITE_CALL = "POST " + BITABLE_PREFIX + "appTest/tables/tblTest/records"


def delivery_payload(*, content_form: str = "图文", script_type: str = "图片脚本") -> dict[str, Any]:
    return {
        "status": "done",
        "document_name_summary": "运动补剂真实体验",
        "brand": "测试品牌",
        "product": "测试补剂",
        "work_info": {
            "draft_due": "7月8日 18:00 前提交初稿",
            "publish_time": "7月10日 20:00-22:00 发布",
            "blogger_name": "小王",
            "account_positioning": "清华短跑运动员 / AI创业者",
            "platform": "小红书",
            "content_form": content_form,
            "content_spec": "5张图" if content_form == "图文" else "60-90秒",
        },
            "content": {
                "creative_direction": "训练日补剂收纳的真实体验分享",
                "title": "训练日的轻负担补给",
                "publish_copy": "训练日最怕补剂带一堆。\n\n我这次把补剂提前分装好，从通勤包到训练场都能顺手带，容量和分隔都很清楚，不用每次翻半天。比较适合我这种要赶训练、又不想把包塞满的人。\n\n如果你也经常训练前临时找补剂，可以按自己的节奏试试这种分装方式。",
                "opening_hook": "训练日最怕补剂带一堆。",
                "experience_process": "从通勤包到训练场都能顺手带。",
                "product_selling_points": "便携、分隔、容量清楚。",
                "personal_feeling": "比较适合我这种要赶训练的人。",
                "soft_conversion_sentence": "可以按自己的训练节奏试试。",
                "tags": ["#训练日", "#补剂收纳"],
                "platform_requirements": "",
                "poll": "你训练会提前分装补剂吗？",
        },
        "script_type": script_type,
        "shooting_script": [
            {
                "index": "1",
                "scene": "训练包内的补剂小盒",
                "timing": "0-3秒",
                "shooting_guidance": "俯拍，保持自然光，产品在画面中心偏右。",
                "copy_or_voiceover": "训练日不用带整瓶。",
                "product_exposure": "展示分隔格。",
                "props_notes": "训练包、水杯。",
            }
        ],
        "pr_notes": "初稿给 PR 审核。",
        "source_summary": "测试商单交付输入",
    }


class FakeContentFlowClient:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.calls: list[dict[str, str]] = []

    def _call_profile_provider_json(self, profile_name: str, prompt: str, user_content: str, stage: str) -> dict[str, Any]:
        self.calls.append({"profile_name": profile_name, "prompt": prompt, "user_content": user_content, "stage": stage})
        return dict(self.payload)


class FakeFeishuService:
    def __init__(self, *, fail_permission: bool = False) -> None:
        self.calls: list[str] = []
        self.fail_permission = fail_permission
        self.record_written = False
        self.record_fields: dict[str, Any] = {}
        self.blocks: list[dict[str, Any]] = []
        self.rendered_markdown = ""
        self.renderer = FeishuService("local_markdown", "/tmp/openclaw-commercial-delivery-unit")

    def render_docx_blocks_from_markdown(self, content: str) -> list[dict[str, Any]]:
        self.calls.append("render_blocks")
        self.rendered_markdown = content
        blocks = self.renderer.render_docx_blocks_from_markdown(content)
        self.blocks = blocks
        return blocks

    def create_docx_with_blocks(self, doc_name: str, children: list[dict[str, Any]]) -> dict[str, str]:
        self.calls.append("create_doc")
        self.blocks = children
        return {"status": "synced", "doc": "https://tcnwueberajc.feishu.cn/docx/doc-test", "document_id": "doc-test", "doc_name": doc_name}

    def replace_child_entry_under_node_blocks(self, *_args: Any, **_kwargs: Any) -> dict[str, str]:
        raise AssertionError("unit smoke uses base table URL and should create standalone doc")

    def set_docx_public_editable(self, _document_id: str) -> dict[str, Any]:
        self.calls.append("permission")
        if self.fail_permission:
            raise RuntimeError("permission readback failed")
        return {"permission_public": {"external_access": True, "link_share_entity": "anyone_editable"}}

    def document_has_native_table(self, _document_id: str) -> bool:
        self.calls.append("native_table")
        return any(block.get("_openclaw_kind") == NATIVE_TABLE_KIND for block in self.blocks)

    def _request(self, method: str, path: str, *, json_body: dict | None = None, params: dict | None = None) -> dict[str, Any]:
        self.calls.append(f"{method} {path}")
        if method == "GET" and path.endswith("/fields"):
            return {
                "data": {
                    "items": [
                        {"field_name": name, "field_id": f"fld-{index}", "type": field_type, "property": {"options": []}}
                        for index, (name, field_type) in enumerate(COMMERCIAL_DELIVERY_FIELD_SPECS.items(), 1)
                    ]
                }
            }
        if method == "PUT" and "/fields/fld-" in path:
            return {"data": {}}
        if method == "POST" and path.endswith("/records"):
            self.record_written = True
            self.record_fields = dict((json_body or {}).get("fields") or {})
            return {"data": {"record": {"record_id": "rec-test"}}}
        raise AssertionError(f"unexpected request: {method} {path}")

    def read_bitable_record(self, *_args: Any) -> dict[str, Any]:
        self.calls.append("record_readback")
        return {"record_id": "rec-test", "fields": dict(self.record_fields)}


class FakeOwnerService:
    registered_docx: dict[str, Any] = {}

    @staticmethod
    def create_projection(resource_type: str, resource_id: str, *, session_tenant_id: str, fields: dict[str, Any], writer):
        assert resource_type == "media.commercial_delivery"
        assert resource_id
        return writer({**fields, "租户ID": session_tenant_id})

    @staticmethod
    def assert_projection_read(resource_type: str, resource_id: str, *, session_tenant_id: str, fields: dict[str, Any], projection_source: str):
        assert resource_type == "media.commercial_delivery"
        assert resource_id and projection_source
        assert fields.get("租户ID") == session_tenant_id
        return fields

    @classmethod
    def register_docx_link(
        cls,
        resource_type: str,
        resource_id: str,
        *,
        session_tenant_id: str,
        document_url: str,
        policy: str,
    ) -> None:
        cls.registered_docx = {
            "resource_type": resource_type,
            "resource_id": resource_id,
            "tenant_id": session_tenant_id,
            "document_url": document_url,
            "policy": policy,
        }


class CommercialDeliveryHarness(CommercialDeliveryMixin):
    def __init__(self, payload: dict[str, Any], *, fail_permission: bool = False, profile_records: list[dict[str, Any]] | None = None) -> None:
        self.content_flow_client = FakeContentFlowClient(payload)
        self.feishu_service = FakeFeishuService(fail_permission=fail_permission)
        self.tenant_owned_resources = FakeOwnerService()
        self.profile_records = profile_records or []

    def _creator_profile_records(self) -> list[dict[str, Any]]:
        return self.profile_records

    def _filter_creator_profile_records(self, records: list[dict[str, Any]], _query: dict[str, Any]) -> list[dict[str, Any]]:
        return records


class CommercialDeliveryTest(unittest.TestCase):
    def setUp(self) -> None:
        FakeOwnerService.registered_docx = {}
        self.old_url = os.environ.get("MEDIA_OS_COMMERCIAL_DELIVERY_URL")
        self.old_parent = os.environ.get("MEDIA_OS_COMMERCIAL_DELIVERY_PARENT_NODE_TOKEN")
        os.environ["MEDIA_OS_COMMERCIAL_DELIVERY_URL"] = "https://tcnwueberajc.feishu.cn/base/appTest?table=tblTest"
        os.environ.pop("MEDIA_OS_COMMERCIAL_DELIVERY_PARENT_NODE_TOKEN", None)

    def tearDown(self) -> None:
        if self.old_url is None:
            os.environ.pop("MEDIA_OS_COMMERCIAL_DELIVERY_URL", None)
        else:
            os.environ["MEDIA_OS_COMMERCIAL_DELIVERY_URL"] = self.old_url
        if self.old_parent is None:
            os.environ.pop("MEDIA_OS_COMMERCIAL_DELIVERY_PARENT_NODE_TOKEN", None)
        else:
            os.environ["MEDIA_OS_COMMERCIAL_DELIVERY_PARENT_NODE_TOKEN"] = self.old_parent

    def test_graphic_success_writes_public_doc_native_table_and_summary_record(self) -> None:
        harness = CommercialDeliveryHarness(delivery_payload())

        result = harness.handle_商单交付(self._message("【商单交付】测试图文商单"))

        self.assertTrue(result.ok, result.reply)
        self.assertIn("互联网所有人可编辑", result.reply)
        self.assertIn("图片脚本", result.reply)
        self.assertTrue(harness.feishu_service.record_written)
        self.assertLess(harness.feishu_service.calls.index("permission"), harness.feishu_service.calls.index(COMMERCIAL_RECORD_WRITE_CALL))
        self.assertLess(harness.feishu_service.calls.index("native_table"), harness.feishu_service.calls.index(COMMERCIAL_RECORD_WRITE_CALL))
        self.assertEqual(harness.feishu_service.record_fields["脚本类型"], "图片脚本")
        self.assertEqual(harness.feishu_service.record_fields["权限状态"], "互联网所有人可编辑")
        self.assertEqual(harness.feishu_service.record_fields["初稿时间"], "7月8日 18:00 前提交初稿")
        self.assertEqual(harness.feishu_service.record_fields["作品初稿链接"]["link"], "https://tcnwueberajc.feishu.cn/docx/doc-test")
        self.assertIn("#### 正文（可直接发布）", harness.feishu_service.rendered_markdown)
        self.assertIn("训练日最怕补剂带一堆。", harness.feishu_service.rendered_markdown)
        self.assertNotIn("轻 CTA", harness.feishu_service.rendered_markdown)
        self.assertTrue(any(block.get("_openclaw_kind") == NATIVE_TABLE_KIND for block in harness.feishu_service.blocks))

    def test_missing_persona_uses_creator_profile_context_without_blocking(self) -> None:
        payload = delivery_payload()
        payload["work_info"]["account_positioning"] = ""
        harness = CommercialDeliveryHarness(
            payload,
            profile_records=[
                {
                    "record_id": "rec-creator",
                    "fields": {
                        "账号名称": "小王",
                        "平台": "小红书",
                        "身份定位": "清华短跑运动员",
                        "创作者角色": "AI创业者",
                        "可创作身份卖点": "真实训练场景",
                    },
                }
            ],
        )

        result = harness.handle_商单交付(
            self._message("【商单交付】\n博主名称：小王\n平台：小红书\n品牌：测试品牌\n产品：测试补剂")
        )

        self.assertTrue(result.ok, result.reply)
        self.assertIn("【可用博主档案上下文】", harness.content_flow_client.calls[0]["user_content"])
        self.assertIn("清华短跑运动员", harness.feishu_service.record_fields["账号定位"])
        self.assertIn("AI创业者", harness.feishu_service.record_fields["账号定位"])

    def test_missing_pr_notes_defaults_without_blocking(self) -> None:
        payload = delivery_payload()
        payload["pr_notes"] = ""
        payload["content"]["platform_requirements"] = ""
        harness = CommercialDeliveryHarness(payload)

        result = harness.handle_商单交付(self._message("【商单交付】缺少 PR 备注"))

        self.assertTrue(result.ok, result.reply)
        self.assertEqual(harness.feishu_service.record_fields["PR备注"], "无特殊要求")
        self.assertTrue(harness.feishu_service.record_written)

    def test_pending_only_pr_notes_missing_defaults_and_continues(self) -> None:
        payload = delivery_payload()
        payload["status"] = "pending_manual"
        payload["reason"] = "缺少 PR 备注"
        payload["missing_fields"] = ["PR备注"]
        payload["pr_notes"] = ""
        harness = CommercialDeliveryHarness(payload)

        result = harness.handle_商单交付(self._message("【商单交付】只缺 PR 备注"))

        self.assertTrue(result.ok, result.reply)
        self.assertEqual(harness.feishu_service.record_fields["PR备注"], "无特殊要求")

    def test_pending_product_fields_does_not_report_pr_notes_as_blocker(self) -> None:
        payload = delivery_payload()
        payload["status"] = "pending_manual"
        payload["reason"] = "产品名称、产品卖点、PR备注为空"
        payload["missing_fields"] = ["产品名称", "产品卖点", "PR备注"]
        payload["pr_notes"] = ""
        harness = CommercialDeliveryHarness(payload)

        result = harness.handle_商单交付(self._message("【商单交付】缺少产品和卖点"))

        self.assertFalse(result.ok)
        self.assertIn("产品名称", result.reply)
        self.assertIn("产品卖点", result.reply)
        self.assertNotIn("PR备注", result.reply)
        self.assertFalse(harness.feishu_service.record_written)

    def test_required_creative_fields_missing_does_not_write(self) -> None:
        payload = delivery_payload()
        payload["content"]["creative_direction"] = ""
        payload["content"]["tags"] = []
        payload["content"]["product_selling_points"] = ""
        harness = CommercialDeliveryHarness(payload)

        result = harness.handle_商单交付(self._message("【商单交付】缺少创作方向"))

        self.assertFalse(result.ok)
        self.assertIn("创作方向", result.reply)
        self.assertIn("产品卖点", result.reply)
        self.assertIn("Tags", result.reply)
        self.assertFalse(harness.feishu_service.calls)
        self.assertFalse(harness.feishu_service.record_written)

    def test_video_uses_storyboard_script_name(self) -> None:
        harness = CommercialDeliveryHarness(delivery_payload(content_form="视频", script_type="分镜脚本"))

        result = harness.handle_商单交付(self._message("【商单交付】测试视频商单"))

        self.assertTrue(result.ok, result.reply)
        self.assertIn("分镜脚本", result.reply)
        self.assertEqual(harness.feishu_service.record_fields["脚本类型"], "分镜脚本")
        self.assertEqual("media.commercial_delivery", FakeOwnerService.registered_docx["resource_type"])
        self.assertEqual("101", FakeOwnerService.registered_docx["tenant_id"])
        self.assertEqual("anyone_editable", FakeOwnerService.registered_docx["policy"])

    def test_pending_payload_does_not_write_doc_or_record(self) -> None:
        harness = CommercialDeliveryHarness({"status": "pending_manual", "reason": "缺少品牌", "missing_fields": ["品牌"]})

        result = harness.handle_商单交付(self._message("【商单交付】缺少字段"))

        self.assertFalse(result.ok)
        self.assertIn("未创建飞书文档", result.reply)
        self.assertFalse(harness.feishu_service.calls)
        self.assertFalse(harness.feishu_service.record_written)

    def test_permission_failure_stops_before_bitable_write(self) -> None:
        harness = CommercialDeliveryHarness(delivery_payload(), fail_permission=True)

        result = harness.handle_商单交付(self._message("【商单交付】权限失败"))

        self.assertFalse(result.ok)
        self.assertIn("错误类型：commercial_delivery_failed", result.reply)
        self.assertIn("permission readback failed", result.reply)
        self.assertFalse(harness.feishu_service.record_written)

    @staticmethod
    def _message(text: str) -> Message:
        return Message(
            entry_tag="商单交付",
            raw_text=text,
            body=text.removeprefix("【商单交付】"),
            source="qq",
            chat_type="private",
            created_at=datetime(2026, 7, 5, 12, 0, 0),
            metadata={"tenant_id": "101"},
        )


if __name__ == "__main__":
    unittest.main()
