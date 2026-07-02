from __future__ import annotations

from .tag_router_common import *
from ..services.media_text_cleaner import MEDIA_TEXT_CLEANER


class TranscriptionFormattersMixin:
    def _postprocess_artifact_lines(self, formatted: dict[str, Any]) -> list[str]:
        artifacts = formatted.get("postprocess_artifacts")
        if not isinstance(artifacts, dict) or not artifacts:
            return []
        lines = []
        if artifacts.get("dir"):
            lines.append(f"- 后处理产物目录：{artifacts['dir']}")
        for label, key in (
            ("全局整理草稿", "global_note_draft"),
            ("一致性检查", "consistency_check"),
        ):
            value = str(artifacts.get(key) or "").strip()
            if value:
                lines.append(f"- {label}：{value}")
        for label, key in (
            ("分片产物", "chunks"),
            ("单附件合并产物", "attachments"),
            ("中间合并产物", "groups"),
        ):
            values = artifacts.get(key)
            if isinstance(values, list) and values:
                lines.append(f"- {label}：{len(values)} 个")
        return lines

    def _format_consistency_check(self, value: Any) -> str:
        if not isinstance(value, dict) or not value:
            return ""
        approved_value = value.get("approved")
        approved = approved_value is True or str(approved_value).strip().lower() == "true"
        lines = [f"- 通过：{'是' if approved else '否'}"]
        blocking = value.get("blocking_issues")
        if isinstance(blocking, list) and blocking:
            lines.append("- 阻断问题：")
            lines.extend(f"  - {str(item).strip()}" for item in blocking if str(item).strip())
        warnings = value.get("warnings")
        if isinstance(warnings, list) and warnings:
            lines.append("- 警告：")
            lines.extend(f"  - {str(item).strip()}" for item in warnings if str(item).strip())
        notes = str(value.get("revision_notes") or "").strip()
        if notes:
            lines.append(f"- 修订说明：{notes}")
        return "\n".join(lines)

    def _format_dialogue_transcription(self, transcript: str, source_hint: str = "", artifact_dir: str | Path | None = None) -> dict[str, Any]:
        result = self.content_flow_client.summarize_dialogue_transcript(transcript, source_hint=source_hint, artifact_dir=artifact_dir)
        if result.get("status") == "done":
            title = self._clean_meeting_topic_candidate(result.get("title", ""))
            summary = self._format_summary_items(result.get("summary"))
            theme_sections = self._format_theme_sections(self._postprocess_items(result, "theme_sections"))
            decisions = self._format_transcription_records(self._postprocess_items(result, "decisions"), empty_label="暂无明确决定或判断。")
            action_items = self._format_transcription_records(self._postprocess_items(result, "action_items"), empty_label="暂无明确行动项。")
            pending_questions = self._format_pending_questions(result.get("pending_questions") or result.get("open_questions") or result.get("questions"))
            speaker_notes = self._format_speaker_notes(result.get("speaker_notes"))
            labeled_transcript = self._format_labeled_transcript(result.get("labeled_transcript"))
            archive_macro_summary = self._format_archive_macro_summary(result.get("archive_macro_summary"))
            archive_summary_bullets = self._format_archive_summary_bullets(result.get("archive_summary_bullets"))
            validation_issue = self._transcription_postprocess_validation_issue(
                result,
                summary,
                speaker_notes,
                labeled_transcript,
                archive_macro_summary,
                archive_summary_bullets,
            )
            if not validation_issue:
                return {
                    "status": "done",
                    "reason": "",
                    "title": title,
                    "summary": summary,
                    "theme_sections": theme_sections,
                    "decisions": decisions,
                    "action_items": action_items,
                    "pending_questions": pending_questions,
                    "speaker_notes": speaker_notes,
                    "labeled_transcript": labeled_transcript,
                    "archive_macro_summary": archive_macro_summary,
                    "archive_summary_bullets": archive_summary_bullets,
                    "postprocess_provider": result.get("postprocess_provider", ""),
                    "postprocess_model": result.get("postprocess_model", ""),
                    "postprocess_pipeline": result.get("postprocess_pipeline", ""),
                    "chunk_count": result.get("chunk_count", 0),
                    "attachment_count": result.get("attachment_count", 0),
                    "consistency_check": result.get("consistency_check", {}),
                    "postprocess_artifacts": result.get("postprocess_artifacts", {}),
                }
            result = {**result, "reason": validation_issue}

        return {
            "status": "pending_manual",
            "reason": str(result.get("reason") or "摘要/说话人整理结果不完整"),
            "title": "",
            "summary": "",
            "theme_sections": "",
            "decisions": "",
            "action_items": "",
            "pending_questions": "",
            "speaker_notes": "",
            "labeled_transcript": "",
            "archive_macro_summary": "",
            "archive_summary_bullets": [],
            "postprocess_provider": result.get("postprocess_provider", ""),
            "postprocess_model": result.get("postprocess_model", ""),
            "postprocess_pipeline": result.get("postprocess_pipeline", ""),
            "chunk_count": result.get("chunk_count", 0),
            "attachment_count": result.get("attachment_count", 0),
            "consistency_check": result.get("consistency_check", {}),
            "postprocess_artifacts": result.get("postprocess_artifacts", {}),
        }

    def _transcription_postprocess_succeeded(self, formatted: dict[str, Any]) -> bool:
        return formatted.get("status") == "done"

    def _transcription_postprocess_validation_issue(
        self,
        result: dict[str, Any],
        summary: str,
        speaker_notes: str,
        labeled_transcript: str,
        archive_macro_summary: str,
        archive_summary_bullets: list[str],
    ) -> str:
        if not summary:
            return "后处理结果缺少内容整理"
        if not speaker_notes:
            return "后处理结果缺少对话人说明"
        if not labeled_transcript:
            return "后处理结果缺少说话人标注逐字稿"
        if not archive_macro_summary:
            return "后处理结果缺少周记宏观总结"
        if not archive_summary_bullets:
            return "后处理结果缺少周记分点摘要"
        if len(archive_summary_bullets) > 5:
            return "后处理结果周记分点摘要超过 5 条"
        if result.get("postprocess_pipeline") == "chunked-map-reduce-final":
            max_chars = 12000
            if len(labeled_transcript) > max_chars:
                return f"后处理结果把过长逐字稿放进主纪要，超过 {max_chars} 字符"
            consistency = result.get("consistency_check", {})
            approved_value = consistency.get("approved") if isinstance(consistency, dict) else None
            approved = approved_value is True or str(approved_value).strip().lower() == "true"
            if not approved:
                issues = consistency.get("blocking_issues") if isinstance(consistency, dict) else []
                if isinstance(issues, list) and issues:
                    return "一致性检查未通过：" + "；".join(str(item) for item in issues[:5])
                return "一致性检查未通过或缺失"
        return ""

    def _format_archive_macro_summary(self, value: Any) -> str:
        text = str(value or "").strip()
        text = re.sub(r"\s+", " ", text).strip()
        return text[:500]

    def _format_archive_summary_bullets(self, value: Any) -> list[str]:
        if isinstance(value, str):
            candidates = value.splitlines()
        elif isinstance(value, list):
            candidates = [str(item) for item in value]
        else:
            candidates = []
        bullets: list[str] = []
        for item in candidates:
            text = re.sub(r"^\s*[-*•\d.、]+\s*", "", str(item or "")).strip()
            text = re.sub(r"\s+", " ", text).strip()
            if text:
                bullets.append(text[:500])
            if len(bullets) >= 5:
                break
        return bullets

    def _format_summary_items(self, value: Any) -> str:
        if isinstance(value, list):
            lines = [str(item).strip() for item in value if str(item).strip()]
            return "\n".join(f"- {line.lstrip('- ').strip()}" for line in lines)
        text = str(value or "").strip()
        if not text:
            return ""
        if "\n" in text:
            return text
        return f"- {text}"

    def _postprocess_items(self, result: dict[str, Any], key: str) -> list[Any]:
        value = result.get(key)
        if isinstance(value, list) and value:
            return value
        items: list[Any] = []
        attachments = result.get("attachment_summaries_compact")
        if isinstance(attachments, list):
            for attachment in attachments:
                if not isinstance(attachment, dict):
                    continue
                nested = attachment.get(key)
                if isinstance(nested, list):
                    items.extend(nested)
        return items

    def _format_theme_sections(self, value: list[Any]) -> str:
        lines: list[str] = []
        for index, item in enumerate(value, start=1):
            if isinstance(item, dict):
                topic = str(item.get("topic") or item.get("title") or item.get("name") or f"主题 {index}").strip()
                lines.append(f"### {index}. {topic}")
                summary = str(item.get("summary") or item.get("main_value") or "").strip()
                if summary:
                    lines.append(summary)
                for label, key in (
                    ("细节", "detail_points"),
                    ("依据", "evidence"),
                    ("风险", "risks"),
                    ("后续", "followups"),
                ):
                    details = item.get(key)
                    if isinstance(details, list) and details:
                        lines.append(f"- {label}：")
                        lines.extend(f"  - {self._stringify_transcription_record(detail)}" for detail in details if self._stringify_transcription_record(detail))
                source = item.get("source_chunks") or item.get("source_ranges")
                if isinstance(source, list) and source:
                    lines.append("- 来源：" + "；".join(self._stringify_transcription_record(part) for part in source if self._stringify_transcription_record(part)))
            else:
                text = str(item).strip()
                if text:
                    lines.append(f"### {index}. 主题 {index}\n{text}")
            if lines and lines[-1]:
                lines.append("")
        return "\n".join(lines).strip()

    def _format_transcription_records(self, value: list[Any], *, empty_label: str) -> str:
        if not value:
            return empty_label
        lines: list[str] = []
        for item in value:
            text = self._stringify_transcription_record(item)
            if text:
                lines.append(f"- {text}")
        return "\n".join(lines) if lines else empty_label

    def _stringify_transcription_record(self, value: Any) -> str:
        if isinstance(value, dict):
            primary = str(
                value.get("item")
                or value.get("task")
                or value.get("point")
                or value.get("summary")
                or value.get("text")
                or value.get("content")
                or value.get("question")
                or ""
            ).strip()
            extras: list[str] = []
            for label, key in (
                ("状态", "status"),
                ("负责人", "assignee"),
                ("节点", "deadline_or_node"),
                ("上下文", "context"),
                ("依据", "rationale"),
            ):
                text = str(value.get(key) or "").strip()
                if text:
                    extras.append(f"{label}：{text}")
            source = value.get("source_range") or value.get("source_ranges")
            source_text = self._format_source_range(source)
            if source_text:
                extras.append(f"来源：{source_text}")
            if not primary:
                primary = "；".join(extras)
                extras = []
            return primary + (f"（{'；'.join(extras)}）" if extras else "")
        return str(value or "").strip()

    def _format_source_range(self, value: Any) -> str:
        if isinstance(value, dict):
            parts = [
                str(value.get("source_audio") or "").strip(),
                str(value.get("chunk_id") or "").strip(),
            ]
            start = value.get("char_start")
            end = value.get("char_end")
            if start is not None and end is not None:
                parts.append(f"{start}-{end}")
            return "/".join(part for part in parts if part)
        if isinstance(value, list):
            return "；".join(self._format_source_range(item) or str(item).strip() for item in value if item)
        return str(value or "").strip()

    def _format_pending_questions(self, value: Any) -> str:
        items: list[str] = []
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    text = str(item.get("question") or item.get("task") or item.get("text") or item.get("content") or "").strip()
                else:
                    text = str(item).strip()
                if text:
                    items.append(text)
        else:
            text = str(value or "").strip()
            if text:
                for line in text.splitlines():
                    clean = re.sub(r"^[-*+]\s*(?:\[[ xX]\]\s*)?", "", line).strip()
                    if clean:
                        items.append(clean)
        if not items:
            items = ["暂无明确待解决问题。"]
        return "\n".join(f"- [ ] {item}" for item in items)

    def _format_speaker_notes(self, value: Any) -> str:
        if isinstance(value, list):
            lines: list[str] = []
            for item in value:
                if isinstance(item, dict):
                    speaker = str(item.get("speaker") or item.get("name") or "说话人 A").strip()
                    description = str(item.get("description") or item.get("note") or item.get("evidence") or "").strip()
                    lines.append(f"- {speaker}：{description}" if description else f"- {speaker}")
                else:
                    text = str(item).strip()
                    if text:
                        lines.append(f"- {text.lstrip('- ').strip()}")
            return "\n".join(lines)
        if isinstance(value, dict):
            return "\n".join(f"- {str(key).strip()}：{str(val).strip()}" for key, val in value.items() if str(val).strip())
        return str(value or "").strip()

    def _format_labeled_transcript(self, value: Any) -> str:
        if isinstance(value, list):
            lines: list[str] = []
            for item in value:
                if isinstance(item, dict):
                    speaker = str(item.get("speaker") or item.get("role") or "说话人 A").strip()
                    text = self._clean_labeled_transcript_text(
                        item.get("text") or item.get("content") or item.get("key_thread") or ""
                    )
                    if not text:
                        source = str(item.get("source") or item.get("source_audio") or "").strip()
                        key_flow = item.get("key_flow")
                        flow_lines = []
                        if isinstance(key_flow, list):
                            flow_lines = [self._clean_labeled_transcript_text(flow) for flow in key_flow]
                            flow_lines = [flow for flow in flow_lines if flow]
                        full_transcript = self._clean_labeled_transcript_text(item.get("full_transcript") or "")
                        if source and flow_lines:
                            lines.append(f"{source}：")
                            lines.extend(f"- {flow}" for flow in flow_lines)
                            if full_transcript:
                                lines.append(f"- {full_transcript}")
                            continue
                        if flow_lines:
                            lines.extend(f"- {flow}" for flow in flow_lines)
                            if full_transcript:
                                lines.append(f"- {full_transcript}")
                            continue
                        text = full_transcript
                    if text:
                        lines.append(f"{speaker}：{text}")
                else:
                    text = self._clean_labeled_transcript_text(item)
                    if text:
                        lines.append(text)
            return "\n".join(lines)
        return self._clean_labeled_transcript_text(value)

    def _clean_labeled_transcript_text(self, value: Any) -> str:
        return MEDIA_TEXT_CLEANER.clean_spoken_line(value)

    def _clean_transcript_for_postprocess(self, transcript: str) -> str:
        return MEDIA_TEXT_CLEANER.clean_transcript_for_copy(transcript)
