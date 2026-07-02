from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from openclaw_app.adapters.mac_agent_client import MacAgentClient
from openclaw_app.router.tag_router import TagRouter
from openclaw_app.services.archive_service import ArchiveService
from openclaw_app.services.completion_guard import CompletionGuard
from openclaw_app.services.feishu_service import FeishuService
from openclaw_app.services.knowledge_archive_bridge import (
    KnowledgeArchiveBridgeResult,
    _archive_entry_markdown,
    _demote_content_headings,
    archive_meeting_content_section,
    extract_markdown_heading_section,
)
from openclaw_app.services.obsidian_daily_checklist_service import ObsidianDailyChecklistService
from openclaw_app.services.reminder_service import ReminderService
from openclaw_app.services.rule_service import RuleService
from openclaw_app.services.schedule_service import ScheduleService
from openclaw_app.services.vlog_storage_service import VlogStorageService
import openclaw_app.router.transcription_storage as transcription_storage


class FakeContentFlowClient:
    def __init__(self) -> None:
        self.summarize_calls: list[dict[str, object]] = []

    def summarize_dialogue_transcript(self, transcript: str, source_hint: str = "", artifact_dir: str | Path | None = None) -> dict[str, object]:
        self.summarize_calls.append({"transcript": transcript, "source_hint": source_hint, "artifact_dir": str(artifact_dir or "")})
        return {
            "status": "done",
            "title": "客户会议文字稿整理",
            "summary": ["讨论客户会议安排和后续确认动作。"],
            "archive_macro_summary": "这次转写聚焦客户会议安排和后续确认动作。",
            "archive_summary_bullets": ["会议讨论了客户会议安排。", "下周具体时间仍需确认。"],
            "pending_questions": ["确认下周具体时间。"],
            "speaker_notes": [{"speaker": "说话人 A", "description": "未区分具体身份。"}],
            "labeled_transcript": [{"speaker": "说话人 A", "text": "讨论客户会议安排，并要求下周确认。"}],
            "postprocess_provider": "fake",
            "postprocess_model": "fake-model",
        }

    def complete_analysis_payload(self, body: str, result: dict, wait: bool = False) -> dict:
        return result


def make_router(workspace: Path, content_flow_client: FakeContentFlowClient) -> TagRouter:
    feishu_service = FeishuService("local_markdown", str(workspace / "feishu_docs"))
    mac_agent = MacAgentClient("queue", str(workspace / "mac_queue"), str(workspace / "obsidian"), str(workspace / "obsidian-local"))
    return TagRouter(
        str(workspace),
        "test",
        "private",
        "Asia/Shanghai",
        ArchiveService(workspace),
        RuleService(workspace / "rules" / "user_rules.yaml"),
        feishu_service,
        content_flow_client,
        ScheduleService("Asia/Shanghai", mac_agent, str(workspace / "obsidian")),
        ReminderService(False, "/usr/bin/python3", str(workspace / "missing_reminder.py")),
        ObsidianDailyChecklistService(workspace / "obsidian" / "Archieve"),
        VlogStorageService(workspace, "Asia/Shanghai"),
        CompletionGuard(content_flow_client),
    )


class TranscriptionTextTest(unittest.TestCase):
    def test_extract_content_section_stops_at_next_h2(self) -> None:
        markdown = "# 会议\n\n## 内容整理\n\n### A\n\n- 关键内容\n\n## 行动项\n\n- 做事\n"
        self.assertEqual(extract_markdown_heading_section(markdown, "内容整理"), "### A\n\n- 关键内容")

    def test_archive_entry_keeps_markdown_hierarchy_readable(self) -> None:
        rendered = _demote_content_headings("## 1. 主题\n\n### 具体背景\n\n正文")
        self.assertIn("#### 1. 主题", rendered)
        self.assertIn("##### 具体背景", rendered)
        self.assertNotIn("- ##", rendered)

    def test_archive_entry_title_links_to_meeting_note(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            note_path = root / "会议纪要" / "整理版" / "2026-06-22-会议.md"
            transcript_path = root / "会议纪要" / "原字稿" / "2026-06-22-会议-原字稿.md"
            note_path.parent.mkdir(parents=True)
            transcript_path.parent.mkdir(parents=True)
            note_path.write_text("# 会议", encoding="utf-8")
            transcript_path.write_text("# 原字稿", encoding="utf-8")
            rendered = _archive_entry_markdown(
                datetime(2026, 6, 22).date(),
                "会议 内容整理",
                note_path,
                "## 1. 主题\n\n正文",
                root,
                macro_summary="这次转写聚焦会议安排。",
                summary_bullets=["会议明确了后续安排。", "仍需确认具体时间。"],
                raw_transcript_path=transcript_path,
            )
        self.assertIn("### 26-06-22 会议 内容整理", rendered)
        self.assertIn("宏观总结：这次转写聚焦会议安排。", rendered)
        self.assertIn("- 会议明确了后续安排。", rendered)
        self.assertIn("详细链接：[2026-06-22-会议](../会议纪要/整理版/2026-06-22-会议.md)", rendered)
        self.assertIn("原字稿链接：[2026-06-22-会议-原字稿](../会议纪要/原字稿/2026-06-22-会议-原字稿.md)", rendered)
        self.assertNotIn("## 1. 主题", rendered)

    def test_archive_meeting_content_section_requires_raw_transcript(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            note_path = root / "会议纪要" / "整理版" / "2026-06-22-会议.md"
            note_path.parent.mkdir(parents=True)
            note_path.write_text(
                "---\n"
                "raw_transcript_path: /tmp/not-exists/raw.md\n"
                "archive_macro_summary: 这次转写聚焦会议安排。\n"
                "archive_summary_bullets:\n"
                "  - 会议明确了后续安排。\n"
                "---\n\n"
                "# 2026-06-22 会议\n\n"
                "## 内容整理\n\n"
                "- 会议明确了后续安排。\n",
                encoding="utf-8",
            )

            result = archive_meeting_content_section(note_path, obsidian_root=root, dry_run=True)

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "missing_raw_transcript")

    def test_transcription_text_body_uses_existing_postprocess_and_meeting_storage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            meeting_dir = root / "会议纪要" / "整理版"
            transcript_dir = root / "会议纪要" / "原字稿"
            client = FakeContentFlowClient()
            router = make_router(workspace, client)

            archive_result = KnowledgeArchiveBridgeResult(ok=True, status="archived", path=str(root / "Archieve" / "20260601-20260607.md"))
            with (
                patch.object(transcription_storage, "MEETING_MINUTES_DIR", meeting_dir),
                patch.object(transcription_storage, "MEETING_TRANSCRIPTS_DIR", transcript_dir),
                patch.object(transcription_storage, "archive_meeting_content_section", return_value=archive_result),
            ):
                result = router.route(
                    "转写-文字",
                    "主题：客户会议\n文字稿：张三：今天讨论报价。\n李四：下周确认。",
                    created_at=datetime(2026, 6, 2, 10, 0),
                )

            self.assertTrue(result.ok)
            self.assertEqual(result.status, "archived")
            self.assertIn("转写文字整理完成", result.reply)
            self.assertIn("Knowledge归档：", result.reply)
            self.assertIn("张三：今天讨论报价。", str(client.summarize_calls[0]["transcript"]))
            self.assertNotIn("主题：客户会议", str(client.summarize_calls[0]["transcript"]))
            self.assertTrue(Path(result.local_path).is_file())
            self.assertIn("/archive/transcripts/", result.local_path)
            obsidian_path = Path(result.extra["postprocess"]["obsidian_transcript_path"])
            self.assertTrue(obsidian_path.is_file())
            obsidian_text = obsidian_path.read_text(encoding="utf-8")
            self.assertIn("entry_tag: 转写-文字", obsidian_text)
            self.assertIn("文字稿整理", obsidian_text)
            note_text = next(meeting_dir.glob("*.md")).read_text(encoding="utf-8")
            self.assertIn("raw_transcript_path:", note_text)
            self.assertIn("archive_macro_summary:", note_text)
            self.assertIn("archive_summary_bullets:", note_text)

    def test_transcription_text_attachment_is_processed_without_body_transcript(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            attachment = root / "transcript.md"
            attachment.write_text("主持人：先整理投放计划。\n成员：今天补齐预算。", encoding="utf-8")
            client = FakeContentFlowClient()
            router = make_router(workspace, client)

            archive_result = KnowledgeArchiveBridgeResult(ok=True, status="skipped_existing", path=str(root / "Archieve" / "20260601-20260607.md"))
            with (
                patch.object(transcription_storage, "MEETING_MINUTES_DIR", root / "会议纪要" / "整理版"),
                patch.object(transcription_storage, "MEETING_TRANSCRIPTS_DIR", root / "会议纪要" / "原字稿"),
                patch.object(transcription_storage, "archive_meeting_content_section", return_value=archive_result),
            ):
                result = router.route(
                    "转写-文字",
                    "主题：投放计划会",
                    created_at=datetime(2026, 6, 2, 11, 0),
                    metadata={"downloaded_paths": [str(attachment)]},
                )

            self.assertTrue(result.ok)
            self.assertIn(str(attachment), result.extra["text_attachment_paths"])
            self.assertIn("主持人：先整理投放计划。", str(client.summarize_calls[0]["transcript"]))


if __name__ == "__main__":
    unittest.main()
