from __future__ import annotations

import subprocess
import tempfile
import unittest
import yaml
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

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
            "meeting_info": {
                "meeting_name": "客户会议",
                "meeting_goal": "明确客户会议安排并确定后续确认动作",
                "meeting_time": "未从来源识别",
                "participants": ["未从来源识别"],
                "facilitator": "未从来源识别",
                "minutes_owner": "未从来源识别",
                "related_project": "未从来源识别",
                "related_documents": ["未从来源识别"],
                "version": "v1.0",
            },
            "conclusion_summary": {
                "overall_judgment": "客户会议仍需先确认具体时间，当前没有形成可执行安排。",
                "key_implications": [
                    {
                        "item": "时间确认是后续安排的前置条件。",
                        "rationale": "会议尚未给出时间。",
                        "implications": "未确认前不能进入执行。",
                        "related_ids": ["O-01", "T-01"],
                    }
                ],
            },
            "decision_list": [],
            "topic_cards": [
                {
                    "id": "T-01",
                    "topic": "客户会议安排",
                    "current_facts": ["需要安排客户会议。"],
                    "core_question": "下周何时召开客户会议？",
                    "options": [],
                    "conclusion_status": "pending_decision",
                    "conclusion": "具体时间仍待确认。",
                    "unresolved_questions": ["确认下周具体时间。"],
                    "next_step": "由负责人确认时间。",
                }
            ],
            "pending_decisions": [
                {"id": "O-01", "question": "下周具体时间？", "options": ["未指定"], "decision_owner": "未指定", "deadline": "未指定"}
            ],
            "validation_hypotheses": [],
            "action_items": [],
            "risks_and_constraints": [],
            "next_meeting": {"trigger_conditions": ["时间确认后"], "required_materials": [], "decisions_needed": ["会议时间"]},
            "topical_attachments": [],
            "archive_macro_summary": "这次转写聚焦客户会议安排和后续确认动作。",
            "archive_summary_bullets": ["会议讨论了客户会议安排。", "下周具体时间仍需确认。"],
            "speaker_notes": [
                {
                    "speaker_key": "speaker_a",
                    "display_name": "说话人 A",
                    "meeting_role": "未从来源识别",
                    "identity_evidence": "来源未标注具体身份",
                    "confidence": "低",
                }
            ],
            "labeled_transcript": [
                {
                    "speaker_key": "speaker_a",
                    "speaker": "说话人 A",
                    "role": "未从来源识别",
                    "text": "讨论客户会议安排，并要求下周确认。",
                    "source": "audio-01-u-000000-000020",
                    "confidence": "低",
                }
            ],
            "postprocess_provider": "fake",
            "postprocess_model": "fake-model",
        }

    def complete_analysis_payload(self, body: str, result: dict, wait: bool = False) -> dict:
        return result


class MultiAudioContentFlowClient(FakeContentFlowClient):
    def __init__(self) -> None:
        super().__init__()
        self.transcribe_calls: list[str] = []

    def transcribe_file(self, path: str, output_dir: Path) -> dict[str, object]:
        self.transcribe_calls.append(path)
        output_dir.mkdir(parents=True, exist_ok=True)
        transcript_path = output_dir / "transcript.txt"
        transcript_path.write_text(
            f"说话人：这是 {Path(path).stem} 的讨论内容。\n",
            encoding="utf-8",
        )
        return {
            "status": "done",
            "transcript_path": str(transcript_path),
            "media_dir": str(output_dir),
        }


def make_router(workspace: Path, content_flow_client: FakeContentFlowClient) -> TagRouter:
    feishu_service = FeishuService("local_markdown", str(workspace / "feishu_docs"))
    return TagRouter(
        str(workspace),
        "test",
        "private",
        "Asia/Shanghai",
        ArchiveService(workspace),
        RuleService(workspace / "rules" / "user_rules.yaml"),
        feishu_service,
        content_flow_client,
        ReminderService(False, "/usr/bin/python3", str(workspace / "missing_reminder.py")),
        ObsidianDailyChecklistService(workspace / "obsidian" / "Archieve"),
        ObsidianDailyChecklistService(workspace / "obsidian" / "Archieve", heading_label="开发待办"),
        VlogStorageService(workspace, "Asia/Shanghai"),
        CompletionGuard(content_flow_client),
    )


class TranscriptionTextTest(unittest.TestCase):
    def test_three_audio_files_and_keywords_reach_one_global_postprocess(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            audio_paths = [root / f"downloaded-{index}.m4a" for index in range(1, 4)]
            display_names = [f"多人讨论{index}.m4a" for index in range(1, 4)]
            for index, path in enumerate(audio_paths, start=1):
                path.write_bytes(f"audio-{index}".encode())
            client = MultiAudioContentFlowClient()
            router = make_router(workspace, client)
            archive_result = KnowledgeArchiveBridgeResult(
                ok=True,
                status="archived",
                path=str(root / "Archieve" / "20260713-20260719.md"),
            )
            keywords = "重点关注多人分工、争议点和后续行动，不要遗漏时间节点"

            with (
                patch.object(transcription_storage, "MEETING_MINUTES_DIR", root / "会议纪要" / "整理版"),
                patch.object(transcription_storage, "MEETING_TRANSCRIPTS_DIR", root / "会议纪要" / "原字稿"),
                patch.object(transcription_storage, "archive_meeting_content_section", return_value=archive_result),
            ):
                result = router.route(
                    "转写",
                    keywords,
                    created_at=datetime(2026, 7, 18, 3, 27),
                    metadata={
                        "downloaded_paths": [str(path) for path in audio_paths],
                        "transcription_batch_id": "tx-three-audio",
                        "transcription_batch_confirmed": True,
                        "transcription_attachments": [
                            {"path": str(path), "name": name, "message_id": f"om_audio_{index}"}
                            for index, (path, name) in enumerate(zip(audio_paths, display_names), start=1)
                        ],
                    },
                )

            self.assertTrue(result.ok)
            self.assertEqual(client.transcribe_calls, [str(path) for path in audio_paths])
            self.assertEqual(len(client.summarize_calls), 1)
            self.assertEqual(client.summarize_calls[0]["source_hint"], keywords)
            combined = str(client.summarize_calls[0]["transcript"])
            for index, display_name in enumerate(display_names, start=1):
                self.assertIn(f"### 录音 {index}：{display_name}", combined)
                self.assertIn(f"这是 downloaded-{index} 的讨论内容", combined)

    def test_extract_content_section_stops_at_next_h2(self) -> None:
        markdown = "# 会议\n\n## 1. 结论摘要\n\n### A\n\n- 关键内容\n\n## 2. 决策清单\n\n- 做事\n"
        self.assertEqual(extract_markdown_heading_section(markdown, "1. 结论摘要"), "### A\n\n- 关键内容")

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
                "会议 会议纪要",
                note_path,
                "## 1. 主题\n\n正文",
                root,
                macro_summary="这次转写聚焦会议安排。",
                summary_bullets=["会议明确了后续安排。", "仍需确认具体时间。"],
                raw_transcript_path=transcript_path,
            )
        self.assertIn("### 26-06-22 会议 会议纪要", rendered)
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
                "## 1. 结论摘要\n\n"
                "- 会议明确了后续安排。\n",
                encoding="utf-8",
            )

            result = archive_meeting_content_section(note_path, obsidian_root=root, dry_run=True)

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "missing_raw_transcript")

    def test_archive_meeting_content_section_times_out_archive_script(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw_path = root / "会议纪要" / "原字稿" / "2026-06-22-会议-原字稿.md"
            note_path = root / "会议纪要" / "整理版" / "2026-06-22-会议.md"
            script_path = root / "archive_to_obsidian.py"
            raw_path.parent.mkdir(parents=True)
            note_path.parent.mkdir(parents=True)
            raw_path.write_text("# 原字稿", encoding="utf-8")
            script_path.write_text("print('unused')", encoding="utf-8")
            note_path.write_text(
                "---\n"
                f"raw_transcript_path: {raw_path}\n"
                "archive_macro_summary: 这次转写聚焦会议安排。\n"
                "archive_summary_bullets:\n"
                "  - 会议明确了后续安排。\n"
                "---\n\n"
                "# 2026-06-22 会议\n\n"
                "## 1. 结论摘要\n\n"
                "- 会议明确了后续安排。\n",
                encoding="utf-8",
            )

            with patch(
                "openclaw_app.services.knowledge_archive_bridge.subprocess.run",
                side_effect=subprocess.TimeoutExpired(
                    cmd=["python3", str(script_path)],
                    timeout=1,
                    output="partial stdout",
                    stderr="partial stderr",
                ),
            ):
                result = archive_meeting_content_section(
                    note_path,
                    archive_script=script_path,
                    obsidian_root=root,
                )

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "archive_timeout")
        self.assertIn("timed out", result.error)
        self.assertEqual(result.stdout, "partial stdout")
        self.assertEqual(result.stderr, "partial stderr")

    def test_transcription_text_body_uses_existing_postprocess_and_meeting_storage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            meeting_dir = root / "会议纪要" / "整理版"
            transcript_dir = root / "会议纪要" / "原字稿"
            topical_dir = root / "会议纪要" / "专题附件"
            client = FakeContentFlowClient()
            router = make_router(workspace, client)

            archive_result = KnowledgeArchiveBridgeResult(ok=True, status="archived", path=str(root / "Archieve" / "20260601-20260607.md"))
            with (
                patch.object(transcription_storage, "MEETING_MINUTES_DIR", meeting_dir),
                patch.object(transcription_storage, "MEETING_TRANSCRIPTS_DIR", transcript_dir),
                patch.object(transcription_storage, "MEETING_TOPICAL_ATTACHMENTS_DIR", topical_dir),
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
            note_frontmatter = yaml.safe_load(note_text.split("---", 2)[1])
            self.assertEqual(note_frontmatter["meeting_name"], "客户会议")
            self.assertEqual(note_frontmatter["meeting_goal"], "明确客户会议安排并确定后续确认动作")
            self.assertEqual(note_frontmatter["participants"], ["未从来源识别"])
            self.assertEqual(note_frontmatter["version"], "v1.0")
            for heading in (
                "## 1. 结论摘要",
                "## 2. 决策清单",
                "## 3. 议题分析与行动项",
                "## 4. 下次会议",
                "## 5. 细节保全附录（受限）",
                "## 6. 关联文档",
            ):
                self.assertIn(heading, note_text)
            self.assertEqual(note_frontmatter["detail_fidelity_appendix_visibility"], "restricted")
            self.assertEqual(note_frontmatter["detail_fidelity_appendix_public_use"], "forbidden")
            self.assertIn("visibility=restricted | public_use=forbidden", note_text)
            self.assertIn("### 1.3 开放问题与待拍板事项", note_text)
            self.assertIn("### 1.4 验证假设", note_text)
            self.assertIn("### 1.5 风险与约束", note_text)
            self.assertIn("### 3.2 行动项", note_text)
            self.assertNotIn("## 8. 专题附件", note_text)
            self.assertFalse(topical_dir.exists())
            self.assertNotIn("## 0. 基本信息", note_text)
            self.assertNotIn("## 说话人标注逐字稿", note_text)

    def test_transcription_topical_attachments_are_written_to_a_separate_linked_note(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            meeting_dir = root / "会议纪要" / "整理版"
            transcript_dir = root / "会议纪要" / "原字稿"
            topical_dir = root / "会议纪要" / "专题附件"
            client = FakeContentFlowClient()
            base_summarize = client.summarize_dialogue_transcript

            def summarize_with_topical_attachment(
                transcript: str,
                source_hint: str = "",
                artifact_dir: str | Path | None = None,
            ) -> dict[str, object]:
                result = base_summarize(transcript, source_hint, artifact_dir)
                result["topical_attachments"] = [
                    {
                        "id": "S-01",
                        "title": "交付验收细则",
                        "status_note": "结构化整理；尚未形成正式决策。",
                        "summary": "交付验收需要单独展开。",
                        "details": ["专题独有细节：逐项核对交付物。"],
                        "source_ranges": ["audio-01"],
                    }
                ]
                return result

            client.summarize_dialogue_transcript = summarize_with_topical_attachment
            router = make_router(workspace, client)
            archive_result = KnowledgeArchiveBridgeResult(
                ok=True,
                status="archived",
                path=str(root / "Archieve" / "20260601-20260607.md"),
            )
            with (
                patch.object(transcription_storage, "MEETING_MINUTES_DIR", meeting_dir),
                patch.object(transcription_storage, "MEETING_TRANSCRIPTS_DIR", transcript_dir),
                patch.object(transcription_storage, "MEETING_TOPICAL_ATTACHMENTS_DIR", topical_dir),
                patch.object(transcription_storage, "archive_meeting_content_section", return_value=archive_result),
            ):
                result = router.route(
                    "转写-文字",
                    "主题：客户会议\n文字稿：说话人 A：讨论交付验收。",
                    created_at=datetime(2026, 6, 2, 10, 0),
                )

            self.assertTrue(result.ok)
            main_path = next(meeting_dir.glob("*.md"))
            topical_path = next(topical_dir.glob("*.md"))
            main_text = main_path.read_text(encoding="utf-8")
            topical_text = topical_path.read_text(encoding="utf-8")
            self.assertIn(f"../专题附件/{topical_path.name}", main_text)
            self.assertNotIn("专题独有细节：逐项核对交付物。", main_text)
            self.assertIn("专题独有细节：逐项核对交付物。", topical_text)
            self.assertEqual(
                result.extra["postprocess"]["obsidian_topical_attachments_path"],
                str(topical_path),
            )

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
