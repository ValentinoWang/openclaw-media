from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from openclaw_app.services.obsidian_daily_checklist_service import ObsidianDailyChecklistService


TZ = ZoneInfo("Asia/Shanghai")


class ObsidianDailyChecklistServiceTest(unittest.TestCase):
    def test_defaults_to_message_date_and_writes_purchase_checklist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = ObsidianDailyChecklistService(Path(tmp) / "Archieve")
            result = service.append_checklist(
                text="购买\n1. 整理\n2. 杠铃杆\n3. 起泡器",
                now=datetime(2026, 6, 29, 10, 0, tzinfo=TZ),
                checklist_tree=[
                    {"text": "整理购买清单", "children": []},
                    {"text": "购买杠铃杆", "children": []},
                    {"text": "购买起泡器", "children": []},
                ],
            )
            self.assertEqual(result.target_date.isoformat(), "2026-06-29")
            self.assertTrue(result.path.endswith("20260629-20260705.md"))
            content = Path(result.path).read_text(encoding="utf-8")
            self.assertTrue(content.startswith("# 待办\n"))
            self.assertIn("- [ ] 整理购买清单", content)
            self.assertIn("- [ ] 购买杠铃杆", content)
            self.assertIn("- [ ] 购买起泡器", content)

    def test_explicit_date_routes_to_matching_week(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = ObsidianDailyChecklistService(Path(tmp) / "Archieve")
            result = service.append_checklist(
                text="20260628 购买\n1. 杠铃杆",
                now=datetime(2026, 6, 29, 10, 0, tzinfo=TZ),
                checklist_tree=[{"text": "购买杠铃杆", "children": []}],
            )
            self.assertEqual(result.target_date.isoformat(), "2026-06-28")
            self.assertTrue(result.path.endswith("20260622-20260628.md"))
            self.assertTrue(Path(result.path).read_text(encoding="utf-8").startswith("# 待办\n"))

    def test_decimal_measurement_does_not_parse_as_date(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = ObsidianDailyChecklistService(Path(tmp) / "Archieve")
            result = service.append_checklist(
                text="购买：2.2m, 20kg杠铃杆、全掌起跑器",
                now=datetime(2026, 6, 29, 10, 0, tzinfo=TZ),
                checklist_tree=[{"text": "购买", "children": [{"text": "购买2.2m 20kg杠铃杆", "children": []}]}],
            )
            self.assertEqual(result.target_date.isoformat(), "2026-06-29")
            self.assertTrue(result.path.endswith("20260629-20260705.md"))

    def test_invalid_eight_digit_url_fragment_does_not_crash_or_override_message_date(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = ObsidianDailyChecklistService(Path(tmp) / "Archieve")
            result = service.append_checklist(
                text="拆解视频\nhttps://example.com/watch?share_id=20261345",
                now=datetime(2026, 7, 12, 10, 0, tzinfo=TZ),
                checklist_tree=[{"text": "拆解视频", "children": []}],
            )

            self.assertEqual(result.target_date.isoformat(), "2026-07-12")
            self.assertTrue(result.path.endswith("20260706-20260712.md"))

    def test_inserts_todo_section_at_file_top(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Archieve"
            root.mkdir(parents=True)
            path = root / "20260622-20260628.md"
            path.write_text("# 知识\n\n内容\n\n# 开发\n\n开发记录\n", encoding="utf-8")
            service = ObsidianDailyChecklistService(root)
            service.append_checklist(text="20260628 购买\n1. 起泡器", now=datetime(2026, 6, 29, 10, 0, tzinfo=TZ), checklist_tree=[{"text": "购买起泡器", "children": []}])
            content = path.read_text(encoding="utf-8")
            self.assertTrue(content.startswith("# 待办\n- [ ] 购买起泡器\n\n# 知识"))
            self.assertLess(content.index("# 待办"), content.index("# 开发"))

    def test_existing_todo_section_gets_newest_item_first(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Archieve"
            root.mkdir(parents=True)
            path = root / "20260629-20260705.md"
            path.write_text("# 待办\n- [ ] 旧事项\n\n# 20260629\n\n内容\n", encoding="utf-8")
            service = ObsidianDailyChecklistService(root)
            service.append_checklist(text="新事项", now=datetime(2026, 6, 29, 10, 0, tzinfo=TZ), checklist_tree=[{"text": "新事项", "children": []}])
            content = path.read_text(encoding="utf-8")
            self.assertTrue(content.startswith("# 待办\n- [ ] 新事项\n\n- [ ] 旧事项"))

    def test_existing_todo_section_is_moved_to_file_top(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Archieve"
            root.mkdir(parents=True)
            path = root / "20260629-20260705.md"
            path.write_text("# 20260703\n\n## 灵感\n\n内容\n\n# 待办\n- [ ] 旧事项\n\n# 开发\n\n开发记录\n", encoding="utf-8")
            service = ObsidianDailyChecklistService(root)
            service.append_checklist(text="新事项", now=datetime(2026, 7, 3, 10, 0, tzinfo=TZ), checklist_tree=[{"text": "新事项", "children": []}])
            content = path.read_text(encoding="utf-8")
            self.assertTrue(content.startswith("# 待办\n- [ ] 新事项\n\n- [ ] 旧事项\n\n# 20260703"))
            self.assertLess(content.index("# 待办"), content.index("# 20260703"))

    def test_development_todo_stays_after_primary_todo_heading(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Archieve"
            root.mkdir(parents=True)
            path = root / "20260629-20260705.md"
            path.write_text("# 待办\n- [ ] 普通事项\n\n# 20260703\n\n内容\n", encoding="utf-8")
            service = ObsidianDailyChecklistService(root, heading_label="开发待办")
            service.append_checklist(text="开发事项", now=datetime(2026, 7, 3, 10, 0, tzinfo=TZ), checklist_tree=[{"text": "开发事项", "children": []}])
            content = path.read_text(encoding="utf-8")
            self.assertTrue(content.startswith("# 待办\n- [ ] 普通事项\n\n# 开发待办\n- [ ] 开发事项\n\n# 20260703"))
            self.assertLess(content.index("# 待办"), content.index("# 开发待办"))

    def test_renders_nested_checklist_with_indentation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = ObsidianDailyChecklistService(Path(tmp) / "Archieve")
            result = service.append_checklist(
                text="购买\n1. 整理\n2. 杠铃杆\n3. 起泡器",
                now=datetime(2026, 6, 29, 10, 0, tzinfo=TZ),
                checklist_tree=[
                    {
                        "text": "购买",
                        "children": [
                            {"text": "整理购买清单", "children": []},
                            {"text": "购买杠铃杆", "children": []},
                            {"text": "购买起泡器", "children": []},
                        ],
                    }
                ],
            )
            self.assertEqual(
                result.markdown_lines,
                [
                    "- [ ] 购买",
                    "  - [ ] 整理购买清单",
                    "  - [ ] 购买杠铃杆",
                    "  - [ ] 购买起泡器",
                ],
            )
            content = Path(result.path).read_text(encoding="utf-8")
            self.assertIn("  - [ ] 购买杠铃杆", content)

    def test_feishu_record_metadata_only_for_single_mirror_item(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = ObsidianDailyChecklistService(Path(tmp) / "Archieve")
            result = service.append_checklist(
                text="2026-06-28 18:00 前买杠铃杆",
                now=datetime(2026, 6, 29, 10, 0, tzinfo=TZ),
                checklist_tree=[{"text": "购买杠铃杆", "children": []}],
                feishu_record="rec123",
            )
            content = Path(result.path).read_text(encoding="utf-8")
            self.assertIn("- [ ] 购买杠铃杆 <!-- openclaw:feishu_record=rec123;sync=todo_complete_v1 -->", content)

    def test_requires_llm_items_from_caller(self) -> None:
        service = ObsidianDailyChecklistService("/tmp/unused")
        with self.assertRaises(ValueError):
            service.append_checklist(text="购买\n1. 杠铃杆\n2. 起泡器", now=datetime(2026, 6, 29, 10, 0, tzinfo=TZ), checklist_tree=[])


if __name__ == "__main__":
    unittest.main()
