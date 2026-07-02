from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from openclaw_app.models.message import Message
from openclaw_app.router.development import DevelopmentMixin
from openclaw_app.services.archive_service import ArchiveService
from openclaw_app.services.obsidian_daily_checklist_service import ObsidianDailyChecklistService


TZ = ZoneInfo("Asia/Shanghai")


class FakeReminderService:
    bitable_url = "https://bitable.default"

    def __init__(self):
        self.calls: list[dict] = []

    def add(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "ok": True,
            "data": {
                "record_id": "rec-dev-task",
                "table_url": "https://bitable.dev",
            },
        }


class DevelopmentHarness(DevelopmentMixin):
    def __init__(self, root: Path):
        self.timezone = "Asia/Shanghai"
        self.archive_service = ArchiveService(root / "workspace")
        self.reminder_service = FakeReminderService()
        self.obsidian_daily_checklist_service = ObsidianDailyChecklistService(root / "Archieve")

    def _configured_bitable_url(self, _kind: str) -> str:
        return "https://bitable.configured"


class DevelopmentTraceabilityTest(unittest.TestCase):
    def test_development_todo_writes_base_and_obsidian_checklist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            harness = DevelopmentHarness(Path(tmp))
            message = Message(
                entry_tag="待办-开发",
                raw_text="【待办-开发】\n机器：VM-0-14-ubuntu\n地址：ubuntu@106.52.146.37\n任务：修复同步\n验收：Mac 能看到新周记条目\n补充：先看日志",
                body="机器：VM-0-14-ubuntu\n地址：ubuntu@106.52.146.37\n任务：修复同步\n验收：Mac 能看到新周记条目\n补充：先看日志",
                source="feishu",
                chat_type="private",
                created_at=datetime(2026, 6, 29, 19, 15, tzinfo=TZ),
            )

            result = harness.handle_待办_开发(message)

            self.assertTrue(result.ok)
            self.assertEqual(result.status, "archived")
            self.assertEqual(result.task_id, "rec-dev-task")
            self.assertIn("飞书多维表格：https://bitable.dev", result.reply)
            self.assertIn("Obsidian checklist：", result.reply)
            call = harness.reminder_service.calls[0]
            self.assertEqual(call["kind"], "待办-开发")
            self.assertEqual(call["title"], "修复同步")
            self.assertEqual(call["due_at"], message.created_at)
            self.assertEqual(call["remind_at"], message.created_at)
            self.assertEqual(call["extra_fields"]["机器"], "VM-0-14-ubuntu")
            self.assertEqual(call["extra_fields"]["地址"], "ubuntu@106.52.146.37")
            self.assertEqual(call["extra_fields"]["验收"], "Mac 能看到新周记条目")
            self.assertEqual(call["extra_fields"]["补充"], "先看日志")
            self.assertEqual(call["extra_fields"]["飞书写入时间"], "2026-06-29 19:15:00 CST")
            self.assertEqual(call["extra_fields"]["checklist状态"], "pending")
            self.assertEqual(call["extra_fields"]["environment_kind"], "cloud_server")
            self.assertEqual(call["extra_fields"]["创建来源"], "feishu_bot/openclaw")

            archive = harness.archive_service.load_archive(result.local_path)
            self.assertTrue(archive.frontmatter["feishu_synced"])
            self.assertEqual(archive.frontmatter["feishu_base_record_id"], "rec-dev-task")
            self.assertEqual(archive.frontmatter["obsidian_path"], result.extra["obsidian_path"])

            checklist_text = Path(result.extra["obsidian_path"]).read_text(encoding="utf-8")
            self.assertIn("【待办-开发】修复同步", checklist_text)
            self.assertIn("openclaw:feishu_record=rec-dev-task", checklist_text)


if __name__ == "__main__":
    unittest.main()
