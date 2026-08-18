from __future__ import annotations

import json
import re
import shutil
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from openclaw_app.models.message import Message
from openclaw_app.router.weekly_self_model import WeeklySelfModelMixin
from openclaw_app.services.archive_service import ArchiveService


class FakeWeeklySummaryClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def _call_profile_provider_json(self, profile_name: str, prompt: str, user_content: str, stage: str) -> dict:
        self.calls.append({"profile": profile_name, "prompt": prompt, "stage": stage, "user_content": user_content})
        if stage == "Daily 日记整理":
            data = json.loads(user_content)
            fields = data.get("template_fields") if isinstance(data.get("template_fields"), dict) else {}

            def arranged(field_id: str) -> str:
                value = str(fields.get(field_id) or "").strip()
                return f"整理：{value}" if value else ""

            return {
                "status": "done",
                "arranged_text": "整理后总结：今天把周记改成读取日记，确认日记应先作为原始事实库，再进入周记复盘。",
                "weekly_projection": {
                    "title": "周记投影接入日记保存",
                    "summary": "今天把周记投影接到日记保存。最重要的事实是日记先作为原始事实库。后续周记再读取日记信号做复盘。",
                },
                "sections": {
                    "today_one_sentence": arranged("today_one_sentence") or f"整理：{data.get('raw_text', '').strip()}",
                    "today_most_recordable": arranged("today_most_recordable"),
                    "emotion_pressure": arranged("emotion_pressure"),
                    "avoidance_min_action": arranged("avoidance_min_action"),
                    "development_work": arranged("development_work"),
                    "engineering_experience": arranged("engineering_experience"),
                },
                "missing_fields": [],
            }
        return {
            "status": "done",
            "fixed_sections": {
                "本周一句话": "本周把日记当成原始事实库。",
                "重复情绪触发": "开发路径不收敛时压力升高。",
                "重复逃避模式": "复杂任务容易先拖延。",
                "关键决策复盘": "决定让周记只读日记。",
                "完成/未完成的承诺": "完成日记入口设计。",
                "最值得保留的经验": "先记录事实，再复盘模式。",
                "开发/工作复盘": "Daily bot 增加日记入口。",
                "工程经验沉淀": "entry tree 是投影，不是新 SSOT。",
                "内容/创作信号": "记录可以变成可复用素材。",
                "下周一个行为实验": "每天 22:00 填一条日记。",
            },
            "dynamic_topic_clusters": [
                {"topic": "开发/工作", "summary": "连续记录了 Daily bot 开发工作。", "evidence_dates": ["2026-07-01", "2026-07-02"]},
                {"topic": "工程经验", "summary": "前端展示应从 contract 投影生成。", "evidence_dates": ["2026-07-03"]},
            ],
        }


class WeeklySelfModelHarness(WeeklySelfModelMixin):
    def __init__(self, workspace: Path, journal_root: Path, archive_root: Path, client: object | None = None) -> None:
        self.timezone = "Asia/Shanghai"
        self.archive_service = ArchiveService(workspace)
        self.content_flow_client = client
        self.daily_journal_settings = {
            "journal_root": str(journal_root),
            "weekly_archive_root": str(archive_root),
            "minimum_weekly_samples": 3,
        }


class WeeklySelfModelTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="weekly-self-model-"))
        self.journal_root = self.tmp / "日记"
        self.archive_root = self.tmp / "Archieve"
        self.harness = WeeklySelfModelHarness(self.tmp / "workspace", self.journal_root, self.archive_root, FakeWeeklySummaryClient())

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp)

    def _message(self, tag: str, body: str, created_at: str) -> Message:
        return Message(
            entry_tag=tag,
            raw_text=f"【{tag}】{body}",
            body=body,
            source="feishu",
            chat_type="private",
            created_at=datetime.fromisoformat(created_at).replace(tzinfo=ZoneInfo("Asia/Shanghai")),
            metadata={"account_id": "daily"},
        )

    def _write_diary(self, created_at: str, sentence: str) -> None:
        body = f"""今天一句话：{sentence}
开发/工作：Daily bot 日记开发
工程经验：entry tree 只做前端投影
明天一个最小动作：22:00 填一条日记"""
        result = self.harness.handle_日记(self._message("日记", body, created_at))
        self.assertTrue(result.ok)

    def test_daily_journal_writes_independent_file(self) -> None:
        result = self.harness.handle_日记(
            self._message(
                "日记",
                """今天一句话：把周记改成读取日记
今天最值得记录的一件事：确认日记是原始事实库
情绪/压力：担心能力入口继续发散
明天一个最小动作：晚上 22:00 填模板""",
                "2026-07-03T22:05:00",
            )
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.status, "written")
        path = self.journal_root / "2026-07-03.md"
        self.assertTrue(path.exists())
        text = path.read_text(encoding="utf-8")
        self.assertIn("### 整理后内容", text)
        self.assertIn("整理后总结：今天把周记改成读取日记", text)
        self.assertIn("### 原文", text)
        self.assertIn("```text", text)
        self.assertIn("今天一句话：把周记改成读取日记", text)
        self.assertIn("openclaw-daily-journal-data", text)
        self.assertIn('"arranged_text"', text)
        self.assertIn('"weekly_projection"', text)
        self.assertNotIn("### 结构化字段", text)
        self.assertNotIn("### 整理后字段", text)
        self.assertNotIn("- 今天一句话：", text)
        self.assertNotIn("自我模型候选", text)
        archive_path = self.archive_root / "20260629-20260705.md"
        self.assertTrue(archive_path.exists())
        archive_text = archive_path.read_text(encoding="utf-8")
        self.assertIn("# 20260703", archive_text)
        self.assertIn("## 日记", archive_text)
        self.assertIn("### 周记投影接入日记保存", archive_text)
        self.assertNotIn("openclaw-daily-journal-weekly-projection", archive_text)
        self.assertEqual(self.harness.content_flow_client.calls[0]["stage"], "Daily 日记整理")
        first_call_payload = json.loads(self.harness.content_flow_client.calls[0]["user_content"])
        self.assertIn("raw_text", first_call_payload)
        self.assertIn("template_fields", first_call_payload)
        prompt = self.harness.content_flow_client.calls[0]["prompt"]
        self.assertIn("不是原文缩写", prompt)
        self.assertIn("不是把 template_fields 逐项串成一段", prompt)
        self.assertIn("只能基于原文事实重组", prompt)
        self.assertIn("不能因为内容敏感", prompt)
        self.assertIn("arranged_text 和 weekly_projection.summary 必须原样保留具体 URL", prompt)
        self.assertIn("写入本周 Archieve `#YYYYMMDD -> ## 日记`", prompt)
        self.assertIn("weekly_projection", prompt)

    def test_daily_journal_requires_weekly_projection_before_writing(self) -> None:
        class MissingProjectionClient(FakeWeeklySummaryClient):
            def _call_profile_provider_json(self, profile_name: str, prompt: str, user_content: str, stage: str) -> dict:
                payload = super()._call_profile_provider_json(profile_name, prompt, user_content, stage)
                if stage == "Daily 日记整理":
                    payload.pop("weekly_projection", None)
                return payload

        harness = WeeklySelfModelHarness(self.tmp / "workspace-missing-projection", self.journal_root, self.archive_root, MissingProjectionClient())
        result = harness.handle_日记(self._message("日记", "今天一句话：只写一句日记", "2026-07-03T22:05:00"))

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "pending_manual")
        self.assertFalse((self.journal_root / "2026-07-03.md").exists())
        self.assertFalse((self.archive_root / "20260629-20260705.md").exists())
        self.assertIn("weekly_projection.title / weekly_projection.summary", result.reply)

    def test_daily_journal_preserves_links_and_projects_to_weekly_archive(self) -> None:
        existing_archive = self.archive_root / "20260629-20260705.md"
        existing_archive.parent.mkdir(parents=True, exist_ok=True)
        original_archive_text = "# 20260629-20260705 周记\n\n# 20260703\n\n## 认知\n\n已有认知内容。\n"
        existing_archive.write_text(original_archive_text, encoding="utf-8")

        message = self._message(
            "日记",
            """今天一句话：把日记保存为原始事实库
今天最值得记录的一件事：参考 https://example.com/journal 确认日记不直接写周归档
开发/工作：Daily bot 日记开发""",
            "2026-07-03T22:05:00",
        )
        result = self.harness.handle_日记(message)
        self.assertTrue(result.ok)

        updated_result = self.harness.handle_日记(message)
        self.assertTrue(updated_result.ok)

        daily_text = (self.journal_root / "2026-07-03.md").read_text(encoding="utf-8")
        arranged_part = daily_text.split("### 原文", 1)[0]
        self.assertIn("https://example.com/journal", arranged_part)
        self.assertIn("周归档：", result.reply)
        data_match = re.search(r"<!--\s*openclaw-daily-journal-data:(.*?)\s*-->", daily_text, re.S)
        self.assertIsNotNone(data_match)
        data_comment = data_match.group(1)
        self.assertNotIn("\n", data_comment)
        data = json.loads(data_comment)
        self.assertIn("https://example.com/journal", data["arranged_text"])
        self.assertIn("weekly_projection", data)

        archive_text = existing_archive.read_text(encoding="utf-8")
        self.assertIn("# 20260703\n\n## 日记\n\n### 周记投影接入日记保存", archive_text)
        self.assertIn("相关链接：https://example.com/journal", archive_text)
        self.assertIn("日记链接：[2026-07-03 日记](../日记/2026-07-03.md)", archive_text)
        self.assertIn("## 认知", archive_text)
        self.assertEqual(archive_text.count("### 周记投影接入日记保存"), 1)
        self.assertNotIn("openclaw-daily-journal-weekly-projection", archive_text)

    def test_weekly_summary_insufficient_only_writes_index(self) -> None:
        self._write_diary("2026-07-01T22:00:00", "第一天记录 Daily bot")
        self._write_diary("2026-07-02T22:00:00", "第二天记录 Daily bot")
        path = self.archive_root / "20260629-20260705.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# 20260629-20260705 周记\n\n# 开发\n\n既有开发内容。\n", encoding="utf-8")

        result = self.harness.handle_周记(self._message("周记", "20260629-20260705", "2026-07-05T23:59:00"))

        self.assertTrue(result.ok)
        self.assertEqual(result.status, "insufficient")
        text = path.read_text(encoding="utf-8")
        self.assertIn("样本不足 3 篇", text)
        self.assertIn("2026-07-01", text)
        self.assertIn("未生成重复模式、人格判断或稳定结论", text)
        self.assertLess(text.index("<!-- openclaw-weekly-self-model:20260629-20260705:start -->"), text.index("# 开发"))
        self.assertTrue(text.rstrip().endswith("既有开发内容。"))

    def test_weekly_summary_enough_uses_llm_and_writes_archive(self) -> None:
        self._write_diary("2026-07-01T22:00:00", "第一天记录 Daily bot")
        self._write_diary("2026-07-02T22:00:00", "第二天记录 Daily bot")
        self._write_diary("2026-07-03T22:00:00", "第三天记录 Daily bot")

        result = self.harness.handle_周记(self._message("周记", "20260629-20260705", "2026-07-05T23:59:00"))

        self.assertTrue(result.ok)
        self.assertEqual(result.status, "written")
        stages = [call["stage"] for call in self.harness.content_flow_client.calls]
        self.assertEqual(stages.count("Daily 日记整理"), 3)
        self.assertEqual(stages.count("Daily 周记总结"), 1)
        path = self.archive_root / "20260629-20260705.md"
        text = path.read_text(encoding="utf-8")
        self.assertIn("本周把日记当成原始事实库", text)
        self.assertIn("### 开发/工作", text)
        self.assertIn("### 工程经验", text)
        self.assertNotIn("### 原文", text)

    def test_weekly_self_model_default_week_is_monday_to_sunday(self) -> None:
        self._write_diary("2026-07-01T22:00:00", "第一天记录 Daily bot")
        self._write_diary("2026-07-02T22:00:00", "第二天记录 Daily bot")
        self._write_diary("2026-07-03T22:00:00", "第三天记录 Daily bot")

        result = self.harness.handle_周记(self._message("周记", "", "2026-07-05T23:59:00"))

        self.assertTrue(result.ok)
        self.assertEqual(result.extra["summaries"][0]["week"], "20260629-20260705")
        self.assertTrue((self.archive_root / "20260629-20260705.md").exists())


if __name__ == "__main__":
    unittest.main()
