from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from openclaw_app.models.message import Message
from openclaw_app.router.activity_daily import ActivityDailyMixin
from openclaw_app.router.social_archive import SocialArchiveMixin
from openclaw_app.router.tag_capabilities import TAG_LABELS


TZ = ZoneInfo("Asia/Shanghai")


class FakeArchiveService:
    def __init__(self):
        self.calls: list[dict] = []

    def save_archive(self, message, title, sections, extra_frontmatter=None):
        self.calls.append(
            {
                "message": message,
                "title": title,
                "sections": sections,
                "extra_frontmatter": extra_frontmatter or {},
            }
        )
        return SimpleNamespace(frontmatter={"id": "archive-id"}, local_path="/tmp/archive.md")


class ForbiddenReminderService:
    def add(self, **_kwargs):
        raise AssertionError("activity AI-clean failure must not write generated record")


class ForbiddenObsidianDailyChecklistService:
    def append_checklist(self, **_kwargs):
        raise AssertionError("Daily intake failure must not write an Obsidian checklist")


class FakeContentFlowClient:
    def __init__(self, *, profile_result: dict | None = None, activity_result: dict | None = None, raise_on_profile: Exception | None = None):
        self.profile_result = profile_result or {}
        self.activity_result = activity_result or {}
        self.raise_on_profile = raise_on_profile
        self.profile_calls: list[dict] = []

    def clean_activity_brief(self, *_args, **_kwargs):
        return self.activity_result

    def _call_profile_provider_json(self, profile_name: str, prompt: str, user_content: str, stage: str) -> dict:
        if self.raise_on_profile is not None:
            raise self.raise_on_profile
        self.profile_calls.append(
            {
                "profile_name": profile_name,
                "prompt": prompt,
                "user_content": user_content,
                "stage": stage,
            }
        )
        return self.profile_result


class ActivityHarness(ActivityDailyMixin):
    def __init__(self):
        self.timezone = "Asia/Shanghai"
        self.content_flow_client = FakeContentFlowClient(activity_result={"status": "pending_manual", "reason": "LLM down"})
        self.archive_service = FakeArchiveService()
        self.reminder_service = ForbiddenReminderService()
        self.obsidian_daily_checklist_service = ForbiddenObsidianDailyChecklistService()

    def _conversation_context_prompt(self, _message):
        return ""


class SocialHarness(SocialArchiveMixin):
    def __init__(self, result: dict):
        self.content_flow_client = FakeContentFlowClient(profile_result=result)

    def _conversation_context_prompt(self, _message):
        return ""


def make_message(tag: str, body: str) -> Message:
    return Message(
        entry_tag=tag,
        raw_text=f"【{tag}】{body}",
        body=body,
        source="feishu",
        chat_type="private",
        created_at=datetime(2026, 5, 29, 13, 30, tzinfo=TZ),
    )


class LlmRequiredRoutesTest(unittest.TestCase):
    def test_activity_ai_clean_failure_does_not_use_rule_generated_fields(self) -> None:
        harness = ActivityHarness()

        result = harness.handle_活动(make_message("活动", "小红书活动 Brief 链接：https://example.com"))

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "activity_ai_clean_pending_manual")
        self.assertIn("不会用规则生成", result.reply)
        self.assertEqual(harness.archive_service.calls[0]["extra_frontmatter"]["postprocess_status"], "pending_manual")

    def test_todo_llm_failure_returns_pending_manual_reply(self) -> None:
        harness = ActivityHarness()
        harness.content_flow_client = FakeContentFlowClient(raise_on_profile=RuntimeError("fetch failed"))

        result = harness.handle_待办(
            make_message(
                "待办",
                "组件从局部 semantic widget、先留 feature shared、三组稳定后晋升 DS molecule 的抽象化skills和体系过程；以及前端怎么瘦身，哪些要抽象为后端",
            )
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "pending_manual")
        self.assertIn("待办没有创建", result.reply)
        self.assertIn("LLM分流异常", result.reply)
        self.assertNotIn("错误代码：", result.reply)
        self.assertNotIn("fetch failed", result.reply)
        self.assertEqual(result.extra["error_code"], "DAILY_TODO_INTAKE_PENDING_MANUAL")
        self.assertFalse(result.extra["persisted"])

    def test_todo_capacity_failure_returns_capacity_reply(self) -> None:
        harness = ActivityHarness()
        harness.content_flow_client = FakeContentFlowClient(
            profile_result={
                "status": "pending_manual",
                "error_code": "DAILY_LLM_MODEL_AT_CAPACITY",
                "reason": "模型当前容量已满，待办未创建、未落盘。",
                "detail": "Selected model is at capacity. Retry after 90 seconds.",
                "suggested_action": "请稍后直接重试原消息。",
            }
        )

        result = harness.handle_待办(make_message("待办", "整理本周工作计划"))

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "pending_manual")
        self.assertIn("待办没有创建", result.reply)
        self.assertIn("原因：模型当前容量已满", result.reply)
        self.assertIn("建议：请稍后直接重试原消息", result.reply)
        self.assertNotIn("错误代码：", result.reply)
        self.assertNotIn("Selected model is at capacity", result.reply)
        self.assertNotIn("缺少/不确定", result.reply)
        self.assertNotIn("DAILY_TODO_INTAKE_PENDING_MANUAL", result.reply)
        self.assertEqual(result.extra["error_code"], "DAILY_LLM_MODEL_AT_CAPACITY")
        self.assertEqual(
            result.extra["detail"], "Selected model is at capacity. Retry after 90 seconds."
        )
        self.assertFalse(result.extra["persisted"])
        self.assertEqual(harness.archive_service.calls, [])

    def test_todo_direct_capacity_exception_returns_capacity_reply(self) -> None:
        harness = ActivityHarness()
        harness.content_flow_client = FakeContentFlowClient(
            raise_on_profile=RuntimeError(
                "GatewayClientRequestError: Selected model is at capacity. Retry after 90 seconds.\n"
                "internal transport trace must not reach the user"
            )
        )

        result = harness.handle_待办(make_message("待办", "整理本周工作计划"))

        self.assertEqual(result.extra["error_code"], "DAILY_LLM_MODEL_AT_CAPACITY")
        self.assertIn("待办没有创建", result.reply)
        self.assertNotIn("GatewayClientRequestError", result.reply)
        self.assertNotIn("internal transport trace", result.reply)
        self.assertNotIn("DAILY_TODO_INTAKE_PENDING_MANUAL", result.reply)
        self.assertNotIn("错误代码：", result.reply)
        self.assertEqual(
            result.extra["detail"], "Selected model is at capacity. Retry after 90 seconds."
        )
        self.assertFalse(result.extra["persisted"])
        self.assertEqual(harness.archive_service.calls, [])

    def test_social_metadata_uses_llm_profile(self) -> None:
        harness = SocialHarness(
            {
                "person": "Jessica",
                "gender": "女",
                "relationship_category": "异性关系",
                "confidence": 0.9,
                "missing_fields": [],
                "evidence": "对象：Jessica；性别：女；关系：异性关系",
                "reason": "字段明确",
            }
        )

        result = harness._extract_social_metadata_with_llm(make_message("社交", "对象：Jessica\n性别：女\n关系：异性关系"), archive_kind="社交", forced_category="")

        self.assertTrue(result["ok"])
        self.assertEqual(result["person"], "Jessica")
        self.assertEqual(result["gender"], "女")
        self.assertEqual(result["relationship_category"], "异性关系")
        self.assertEqual(harness.content_flow_client.profile_calls[0]["profile_name"], "content_cleaner")

    def test_social_metadata_defaults_to_female_heterosexual_when_person_is_known(self) -> None:
        harness = SocialHarness(
            {
                "person": "赵紫薇",
                "gender": "女",
                "relationship_category": "异性关系",
                "confidence": 0.8,
                "missing_fields": [],
                "evidence": "对象：赵紫薇",
                "reason": "对象明确，用户未特殊说明，按默认女性和异性关系处理",
            }
        )

        result = harness._extract_social_metadata_with_llm(make_message("社交", "对象：赵紫薇 这张图说明什么"), archive_kind="社交", forced_category="")

        self.assertTrue(result["ok"])
        self.assertEqual(result["person"], "赵紫薇")
        self.assertEqual(result["gender"], "女")
        self.assertEqual(result["relationship_category"], "异性关系")

    def test_social_archive_prefers_downloaded_image_input_over_text_stub(self) -> None:
        harness = SocialHarness({})
        media_root = Path("/home/ubuntu/.openclaw/media/inbound")
        media_root.mkdir(parents=True, exist_ok=True)
        image_path = media_root / "social-route-test.jpg"
        image_path.write_bytes(b"fake-image")
        self.addCleanup(lambda: image_path.unlink(missing_ok=True))
        with tempfile.NamedTemporaryFile("w", suffix=".txt") as text_file:
            message = make_message("社交", "对象：赵紫薇 这张图说明什么")
            message.metadata = {"downloaded_paths": [str(image_path)]}

            selected = harness._social_person_archive_input_path(message, Path(text_file.name))

        self.assertEqual(selected, image_path.resolve())

    def test_social_archive_reply_summary_uses_latest_material_content(self) -> None:
        harness = SocialHarness({})
        with tempfile.TemporaryDirectory() as tmp_dir:
            archive_path = Path(tmp_dir) / "archive.md"
            archive_path.write_text(
                """
## 001｜【人物照片】2026-06-13｜旧记录

> 待归入本表的提纯材料如下。后续编辑时应拆成逐行聊天记录、事实摘要和分析证据；原始音频/截图/图片不进入档案。

旧内容

| 日期/时间 | 发言人 | 内容 | 备注 |

## 002｜【人物照片】2026-06-13｜新记录

> 待归入本表的提纯材料如下。后续编辑时应拆成逐行聊天记录、事实摘要和分析证据；原始音频/截图/图片不进入档案。

图中主体可见，画面重点是穿搭和姿态；可判断项有限。

| 日期/时间 | 发言人 | 内容 | 备注 |
""".strip(),
                encoding="utf-8",
            )
            message = make_message("社交", "对象：赵紫薇 这张图说明什么")

            summary = harness._social_archive_reply_summary(
                message,
                {"archive_path": str(archive_path), "input_path": "/home/ubuntu/.openclaw/media/inbound/current.jpg"},
            )

        self.assertIn("图中主体可见", summary)
        self.assertNotIn("旧内容", summary)

    def test_recreation_depth_tags_are_retired_from_active_registry(self) -> None:
        self.assertNotIn("拆解-再创", TAG_LABELS)
        self.assertNotIn("拆解-再创-简略", TAG_LABELS)
        self.assertNotIn("拆解-再创-详细", TAG_LABELS)


if __name__ == "__main__":
    unittest.main()
