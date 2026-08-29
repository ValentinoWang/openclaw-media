from __future__ import annotations

import json
import unittest
from datetime import datetime
from unittest.mock import patch

from openclaw_app.models.message import Message
from openclaw_app.router.media_creation import MediaCreationMixin
from openclaw_app.router.unified_creation import UnifiedCreationMixin


TENANT_ID = "00000000-0000-4000-8000-000000000101"


class CreationInspirationHarness(UnifiedCreationMixin, MediaCreationMixin):
    def __init__(self) -> None:
        self.synced_fields: dict[str, object] = {}

    def _append_conversation_context_arg(self, command: list[str], message: Message) -> None:
        return None

    def _subprocess_env_for_content_os_script_generation(self, message: Message) -> dict[str, str]:
        return {}

    def _subprocess_env_with_context(self, message: Message) -> dict[str, str]:
        return {}

    def _parse_openclaw_json(self, text: str) -> dict[str, object]:
        return json.loads(text)

    def _unified_creation_doc_name(self, record_type: str, theme_source: str, seed: str) -> str:
        return "创作-毕业照打卡路线"

    def _sync_unified_creation_child_doc(self, doc_title: str, record_type: str, content: str) -> dict[str, str]:
        return {"doc": "https://example.feishu.cn/wiki/inspiration-doc"}

    def _sync_unified_creation_record(self, fields: dict[str, object], *, session_tenant_id: str) -> dict[str, str]:
        assert session_tenant_id == TENANT_ID
        self.synced_fields = fields
        return {"record_id": "rec_creation_inspiration_001", "table_url": "https://example.feishu.cn/base/table"}

    def _unified_now_iso(self) -> str:
        return "2026-06-24T12:00:00+08:00"

    def _unified_join_lines(self, values: list[object]) -> str:
        return "\n".join(str(value) for value in values if str(value).strip())

    def _maybe_create_content_os_project_from_inspiration(
        self,
        *,
        message: Message,
        result: dict[str, object],
        record_text: str,
        doc_fs: dict[str, str],
        unified_index: dict[str, str],
    ) -> dict[str, str]:
        return {}


class UnifiedCreationRunHarness(UnifiedCreationMixin):
    pass


class CreationInspirationRouteTest(unittest.TestCase):
    def test_deconstruct_route_rejects_empty_success_without_landing_artifacts(self) -> None:
        harness = CreationInspirationHarness()
        inner = {
            "mode": "deconstruct_only",
            "deconstruct": {"content_summary": "只有摘要，没有落地文档"},
        }
        message = Message(
            entry_tag="拆解",
            raw_text="【拆解】https://example.com/video 重点看开头钩子",
            body="https://example.com/video 重点看开头钩子",
            source="feishu",
            chat_type="private",
            created_at=datetime(2026, 6, 28, 10, 0, 0),
            metadata={"tenant_id": TENANT_ID},
        )

        with patch(
            "selfmedia.deconstruct.viral_content.src.runner.run_workflow",
            return_value=inner,
        ) as workflow:
            result = harness.handle_拆解(message)

        workflow.assert_called_once_with(message.raw_text, tenant_id=TENANT_ID, write_feishu=True)
        self.assertFalse(result.ok)
        self.assertEqual(result.status, "deconstruct_incomplete")
        self.assertIn("未确认完成", result.reply)
        self.assertIn("拆解文档链接", result.reply)
        self.assertIn("飞书拆解记录ID", result.reply)

    def test_deconstruct_route_reports_completed_only_with_doc_and_record(self) -> None:
        harness = CreationInspirationHarness()
        inner = {
            "mode": "deconstruct_only",
            "deconstruct": {
                "content_summary": "毕业季蓝袍黄领翻拍结构",
                "deconstruct_doc_url": "https://example.feishu.cn/wiki/deconstruct-doc",
            },
            "feishu_record_id": "rec_deconstruct_001",
        }
        message = Message(
            entry_tag="拆解",
            raw_text="【拆解】https://example.com/video 重点看转场",
            body="https://example.com/video 重点看转场",
            source="feishu",
            chat_type="private",
            created_at=datetime(2026, 6, 28, 10, 0, 0),
            metadata={"tenant_id": TENANT_ID},
        )

        with patch(
            "selfmedia.deconstruct.viral_content.src.runner.run_workflow",
            return_value=inner,
        ) as workflow:
            result = harness.handle_拆解(message)

        workflow.assert_called_once_with(message.raw_text, tenant_id=TENANT_ID, write_feishu=True)
        self.assertTrue(result.ok)
        self.assertEqual(result.status, "deconstruct_only")
        self.assertIn("【拆解】处理完成。", result.reply)
        self.assertIn("https://example.feishu.cn/wiki/deconstruct-doc", result.reply)
        self.assertIn("rec_deconstruct_001", result.reply)

    def test_creation_run_id_uses_feishu_message_id(self) -> None:
        harness = UnifiedCreationRunHarness()
        base_fields = {
            "记录类型": "创作记录",
            "标题": "创作-毕业照打卡路线",
            "主题": "课题组毕业照",
            "内容": "同一段创作正文",
            "创作文档链接": "https://example.feishu.cn/wiki/creation-doc",
            "主状态": "已归档",
        }

        first = harness._creation_run_v2_fields({**base_fields, "来源消息ID": "om_first"}, base_fields["创作文档链接"])
        second = harness._creation_run_v2_fields({**base_fields, "来源消息ID": "om_second"}, base_fields["创作文档链接"])

        self.assertNotEqual(first["run_id"], second["run_id"])


if __name__ == "__main__":
    unittest.main()
