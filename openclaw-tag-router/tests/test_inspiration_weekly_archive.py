from __future__ import annotations

import unittest
from datetime import date
from datetime import datetime
from zoneinfo import ZoneInfo

from openclaw_app.models.message import Message
from openclaw_app.router.business_vlog import BusinessVlogMixin


class InspirationWeeklyHarness(BusinessVlogMixin):
    timezone = "Asia/Shanghai"


class InspirationWeeklyArchiveTest(unittest.TestCase):
    def test_inspiration_weekly_entry_uses_summary_card_with_detail_link(self) -> None:
        harness = InspirationWeeklyHarness()
        message = Message(
            entry_tag="灵感",
            raw_text="【灵感】测试",
            body="测试",
            created_at=datetime(2026, 6, 17, 17, 25, tzinfo=ZoneInfo("Asia/Shanghai")),
        )
        result = {
            "archive_macro_summary": "这条灵感用于验证周记短卡格式。",
            "archive_summary_bullets": ["周记只保留摘要。", "详细内容进入灵感归档。"],
        }

        entry = harness._build_inspiration_weekly_entry(
            message,
            "验证灵感周记短卡格式",
            "../灵感/归档/20260617-172550-feishu-灵感-c92f.md",
            result,
        )

        self.assertIn("#### 验证灵感周记短卡格式", entry)
        self.assertIn("宏观总结：这条灵感用于验证周记短卡格式。", entry)
        self.assertIn("- 周记只保留摘要。", entry)
        self.assertIn("详细链接：[20260617-172550-feishu-灵感-c92f](../灵感/归档/20260617-172550-feishu-灵感-c92f.md)", entry)
        self.assertNotIn("0617｜[", entry)

    def test_inspiration_weekly_entries_use_date_first_sections(self) -> None:
        text = "# 20260602\n\n## 灵感\n\n### 灵感\n\n#### 旧灵感\n\n宏观总结：旧。\n- 旧。\n\n详细链接：[old](../灵感/归档/old.md)\n"
        entry = "#### 新灵感\n\n宏观总结：新。\n- 新。\n\n详细链接：[new](../灵感/归档/new.md)\n"

        updated = InspirationWeeklyHarness._append_entry_to_weekly_date_section(text, date(2026, 6, 17), "灵感", "灵感", entry)
        sorted_text = InspirationWeeklyHarness._sort_weekly_date_sections(updated)

        self.assertIn("# 20260617\n\n## 灵感\n\n### 灵感\n\n#### 新灵感", sorted_text)
        self.assertLess(sorted_text.find("# 20260617"), sorted_text.find("# 20260602"))

    def test_inspiration_archive_requires_llm_weekly_summary_fields(self) -> None:
        self.assertEqual(
            InspirationWeeklyHarness._inspiration_archive_validation_issue({"archive_summary_bullets": ["一条"]}),
            "LLM 灵感整理缺少周记宏观总结",
        )
        self.assertEqual(
            InspirationWeeklyHarness._inspiration_archive_validation_issue({"archive_macro_summary": "宏观"}),
            "LLM 灵感整理缺少周记分点摘要",
        )


if __name__ == "__main__":
    unittest.main()
