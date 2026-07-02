from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from openclaw_app.models.message import Message
from openclaw_app.router.deletion import DeletionMixin
from openclaw_app.router.deletion_adapters.base import DeletionContext


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

    def delete_bitable_record(self, app_token: str, table_id: str, record_id: str) -> dict[str, Any]:
        self.records.pop((app_token, table_id, record_id), None)
        return {"ok": True}

    def resolve_document_reference(self, url: str) -> dict[str, str]:
        return {"url": url, "kind": "wiki", "token": "wik1", "document_id": "doc1", "obj_type": "docx"}

    def delete_document_reference(self, ref: dict[str, str]) -> dict[str, Any]:
        self.docs[ref["url"]] = False
        return {"ok": True}

    def read_document_reference(self, ref: dict[str, str]) -> dict[str, Any]:
        if self.docs.get(ref["url"], False):
            return {"ok": True, "text": "still exists"}
        raise RuntimeError("document not found")

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


class DeletionPhase2Harness(DeletionMixin):
    def __init__(self, workspace_root: Path, feishu: FakeFeishuService | None = None, reminder: FakeReminderService | None = None):
        self.workspace_root = workspace_root
        self.feishu_service = feishu
        self.reminder_service = reminder

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
            reminder_service=self.reminder_service,
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
        metadata={"account_id": "media"},
    )


def write_frontmatter(path: Path, frontmatter: dict[str, object], body: str = "") -> None:
    lines = ["---"]
    for key, value in frontmatter.items():
        if isinstance(value, dict):
            lines.append(f"{key}:")
            for child_key, child_value in value.items():
                lines.append(f"  {child_key}: {child_value}")
        else:
            lines.append(f"{key}: {value}")
    lines.extend(["---", body])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


class Phase2DeletionAdaptersTest(unittest.TestCase):
    def test_bitable_record_adapter_deletes_with_readback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = "20260412-030515-qq-内容素材-0056"
            archive = root / "archive" / "materials" / f"{target}.md"
            table_url = "https://example.feishu.cn/base/appToken123?table=tblABC"
            write_frontmatter(archive, {"id": target, "entry_tag": "内容素材", "record_id": "recMaterial", "table_url": table_url})
            feishu = FakeFeishuService()
            feishu.records[("appToken123", "tblABC", "recMaterial")] = {"fields": {"标题": "素材记录"}}

            preview = DeletionPhase2Harness(root, feishu).handle_删除(deletion_message(target))
            applied = DeletionPhase2Harness(root, feishu).handle_删除(deletion_message(f"确认删除 {target}"))

            self.assertTrue(preview.ok)
            self.assertIn("多维表格记录", preview.reply)
            self.assertNotIn(("appToken123", "tblABC", "recMaterial"), feishu.records)
            self.assertTrue(applied.ok)
            self.assertIn("已删除", applied.reply)

    def test_feishu_doc_adapter_deletes_owned_doc_with_readback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = "20260412-030515-qq-创作-0056"
            archive = root / "archive" / "creation" / f"{target}.md"
            url = "https://example.feishu.cn/wiki/wik1"
            write_frontmatter(archive, {"id": target, "entry_tag": "创作", "feishu_doc": url, "feishu_doc_delete_allowed": "true"})
            feishu = FakeFeishuService()
            feishu.docs[url] = True

            result = DeletionPhase2Harness(root, feishu).handle_删除(deletion_message(f"确认删除 {target}"))

            self.assertTrue(result.ok)
            self.assertFalse(feishu.docs[url])
            self.assertIn("飞书文档", result.reply)

    def test_reminder_calendar_adapter_deletes_record_and_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = "20260412-030515-qq-日程-0056"
            archive = root / "archive" / "daily" / f"{target}.md"
            write_frontmatter(archive, {"id": target, "entry_tag": "日程", "record_id": "recReminder", "calendar_id": "cal1", "event_id": "evt1"})
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
            write_frontmatter(archive, {"id": target, "entry_tag": "转写", "weekly_path": note})

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
            write_frontmatter(archive, {"id": target, "entry_tag": "创作", "project_id": project_id, "task_id": task_id})

            result = DeletionPhase2Harness(root).handle_删除(deletion_message(f"确认删除 {target}"))

            self.assertTrue(result.ok)
            self.assertFalse(project_dir.exists())
            self.assertFalse(queue.exists())
            self.assertNotIn(project_id, registry.read_text(encoding="utf-8"))
            self.assertIn("Mac队列任务", result.reply)


if __name__ == "__main__":
    unittest.main()
