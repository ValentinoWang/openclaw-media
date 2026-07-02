from __future__ import annotations

import json
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

from openclaw_app.models.message import Message
from openclaw_app.router import media_creation as media_creation_module
from openclaw_app.router.media_creation import MediaCreationMixin
from openclaw_app.router.unified_creation import UnifiedCreationMixin


class CreationInspirationHarness(MediaCreationMixin):
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
        return "创作-灵感-毕业照打卡路线"

    def _sync_unified_creation_child_doc(self, doc_title: str, record_type: str, content: str) -> dict[str, str]:
        return {"doc": "https://example.feishu.cn/wiki/inspiration-doc"}

    def _sync_unified_creation_record(self, fields: dict[str, object]) -> dict[str, str]:
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
        outer = {"ok": True, "stdout": json.dumps(inner, ensure_ascii=False), "stderr": ""}
        completed = SimpleNamespace(returncode=0, stdout=json.dumps(outer, ensure_ascii=False), stderr="")
        message = Message(
            entry_tag="拆解",
            raw_text="【拆解】https://example.com/video 重点看开头钩子",
            body="https://example.com/video 重点看开头钩子",
            source="feishu",
            chat_type="private",
            created_at=datetime(2026, 6, 28, 10, 0, 0),
            metadata={},
        )

        with patch.object(media_creation_module, "run_media_subprocess_with_watchdog", return_value=completed):
            result = harness.handle_拆解(message)

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
        outer = {"ok": True, "stdout": json.dumps(inner, ensure_ascii=False), "stderr": ""}
        completed = SimpleNamespace(returncode=0, stdout=json.dumps(outer, ensure_ascii=False), stderr="")
        message = Message(
            entry_tag="拆解",
            raw_text="【拆解】https://example.com/video 重点看转场",
            body="https://example.com/video 重点看转场",
            source="feishu",
            chat_type="private",
            created_at=datetime(2026, 6, 28, 10, 0, 0),
            metadata={},
        )

        with patch.object(media_creation_module, "run_media_subprocess_with_watchdog", return_value=completed):
            result = harness.handle_拆解(message)

        self.assertTrue(result.ok)
        self.assertEqual(result.status, "deconstruct_only")
        self.assertIn("【拆解】处理完成。", result.reply)
        self.assertIn("https://example.feishu.cn/wiki/deconstruct-doc", result.reply)
        self.assertIn("rec_deconstruct_001", result.reply)

    def test_material_copywriting_request_returns_publishable_copy_without_subprocess(self) -> None:
        harness = CreationInspirationHarness()
        message = Message(
            entry_tag="素材创作",
            raw_text="【素材创作】平台=抖音 类型=图文 账号=主账号 标题和文案\n素材事实：单张图片，清华校园建筑背景，一群蓝紫斗篷人物围绕发光 AI 芯片，偏清华 + AI + 魔法仪式感视觉素材。",
            body="平台=抖音 类型=图文 账号=主账号 标题和文案\n素材事实：单张图片，清华校园建筑背景，一群蓝紫斗篷人物围绕发光 AI 芯片，偏清华 + AI + 魔法仪式感视觉素材。",
            source="feishu",
            chat_type="private",
            created_at=datetime(2026, 6, 28, 4, 10, 0),
            metadata={},
        )

        with patch.object(media_creation_module.subprocess, "run", side_effect=AssertionError("copywriting path must not call subprocess")):
            result = harness.handle_material_creation(message)

        self.assertTrue(result.ok)
        self.assertEqual(result.status, "material_copywriting_ready")
        self.assertIn("当清华校园遇到 AI 魔法阵", result.reply)
        self.assertIn("正文文案：", result.reply)
        self.assertIn("封面字建议：", result.reply)
        self.assertIn("#抖音图文", result.reply)
        self.assertEqual(result.extra["platform"], "抖音")
        self.assertEqual(result.extra["content_type"], "图文")

    def test_material_copywriting_uses_recent_manifest_context(self) -> None:
        harness = CreationInspirationHarness()
        message = Message(
            entry_tag="素材创作",
            raw_text="【素材创作】平台=抖音 类型=图文 账号=主账号 生成标题文案",
            body="平台=抖音 类型=图文 账号=主账号 生成标题文案",
            source="feishu",
            chat_type="private",
            created_at=datetime(2026, 6, 28, 4, 10, 0),
            metadata={
                "conversation_context": {
                    "items": [
                        {
                            "bot_reply": "识别：清华校园建筑前，一群蓝紫斗篷人物围绕发光 AI 芯片，偏清华 + AI + 魔法仪式感的视觉素材。"
                        }
                    ]
                }
            },
        )

        with patch.object(media_creation_module.subprocess, "run", side_effect=AssertionError("copywriting path must not call subprocess")):
            result = harness.handle_material_creation(message)

        self.assertTrue(result.ok)
        self.assertEqual(result.status, "material_copywriting_ready")
        self.assertIn("清华", result.reply)
        self.assertIn("AI", result.reply)
        self.assertIn("标题候选：", result.reply)

    def test_creation_inspiration_reply_includes_doc_and_creation_run_record(self) -> None:
        harness = CreationInspirationHarness()
        payload = {
            "ok": True,
            "reply": "毕业照创作灵感已整理",
            "record_text": "打卡路线图和视频方向",
            "result": {
                "title": "清华 SIGS 毕业照打卡路线",
                "theme": "课题组毕业照",
                "cleaned_inspiration": "三小时毕业照拍摄路线",
                "material_summary": "导师与 15 位工科硕士毕业生。",
                "platform": "小红书",
                "content_type": "图文",
                "track": "校园生活",
                "tags": ["毕业季", "清华 SIGS"],
                "content_angles": ["路线图", "群像"],
                "reuse_angles": ["毕业照打卡"],
                "created_at": "2026-06-24T12:00:00+08:00",
            },
        }
        completed = SimpleNamespace(returncode=0, stdout=json.dumps(payload, ensure_ascii=False), stderr="")
        message = Message(
            entry_tag="创作-灵感",
            raw_text="【创作-灵感】6月25日下午3点到6点拍毕业照",
            body="6月25日下午3点到6点拍毕业照",
            source="feishu",
            chat_type="private",
            created_at=datetime(2026, 6, 24, 12, 0, 0),
            metadata={"message_id": "om_creation_inspiration_001"},
        )

        with patch.object(media_creation_module, "run_media_subprocess_with_watchdog", return_value=completed):
            result = harness.handle_创作灵感(message)

        self.assertTrue(result.ok)
        self.assertEqual(result.status, "creation_inspiration_saved")
        self.assertIn("任务池文档：https://example.feishu.cn/wiki/inspiration-doc", result.reply)
        self.assertIn("创作运行记录：rec_creation_inspiration_001", result.reply)
        self.assertNotIn("统一同步失败", result.reply)
        self.assertEqual(result.feishu_doc, "https://example.feishu.cn/wiki/inspiration-doc")
        self.assertEqual(result.task_id, "rec_creation_inspiration_001")
        self.assertEqual(harness.synced_fields["灵感文档链接"], "https://example.feishu.cn/wiki/inspiration-doc")
        self.assertEqual(harness.synced_fields["来源消息ID"], "om_creation_inspiration_001")

    def test_creation_run_id_uses_feishu_message_id(self) -> None:
        harness = UnifiedCreationRunHarness()
        base_fields = {
            "记录类型": "创作记录",
            "标题": "创作-灵感-毕业照打卡路线",
            "主题": "课题组毕业照",
            "内容": "同一段创作灵感正文",
            "灵感文档链接": "https://example.feishu.cn/wiki/inspiration-doc",
            "主状态": "已归档",
        }

        first = harness._creation_run_v2_fields({**base_fields, "来源消息ID": "om_first"}, base_fields["灵感文档链接"])
        second = harness._creation_run_v2_fields({**base_fields, "来源消息ID": "om_second"}, base_fields["灵感文档链接"])

        self.assertNotEqual(first["run_id"], second["run_id"])


if __name__ == "__main__":
    unittest.main()
