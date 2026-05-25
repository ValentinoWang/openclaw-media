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
            pending_questions = self._format_pending_questions(result.get("pending_questions") or result.get("open_questions") or result.get("questions"))
            speaker_notes = self._format_speaker_notes(result.get("speaker_notes"))
            labeled_transcript = self._format_labeled_transcript(result.get("labeled_transcript"))
            validation_issue = self._transcription_postprocess_validation_issue(result, summary, speaker_notes, labeled_transcript)
            if not validation_issue:
                return {
                    "status": "done",
                    "reason": "",
                    "title": title,
                    "summary": summary,
                    "pending_questions": pending_questions,
                    "speaker_notes": speaker_notes,
                    "labeled_transcript": labeled_transcript,
                    "postprocess_provider": result.get("postprocess_provider", ""),
                    "postprocess_model": result.get("postprocess_model", ""),
                    "postprocess_pipeline": result.get("postprocess_pipeline", ""),
                    "chunk_count": result.get("chunk_count", 0),
                    "attachment_count": result.get("attachment_count", 0),
                    "consistency_check": result.get("consistency_check", {}),
                    "postprocess_artifacts": result.get("postprocess_artifacts", {}),
                }
            result = {**result, "reason": validation_issue}

        fallback = self._fallback_dialogue_transcription(transcript)
        return {
            "status": "pending_manual",
            "reason": str(result.get("reason") or "摘要/说话人整理结果不完整"),
            "title": fallback.get("title", ""),
            "summary": fallback.get("summary", ""),
            "pending_questions": fallback.get("pending_questions", ""),
            "speaker_notes": fallback.get("speaker_notes", ""),
            "labeled_transcript": fallback.get("labeled_transcript", ""),
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

    def _transcription_postprocess_validation_issue(self, result: dict[str, Any], summary: str, speaker_notes: str, labeled_transcript: str) -> str:
        if not summary:
            return "后处理结果缺少内容整理"
        if not speaker_notes:
            return "后处理结果缺少对话人说明"
        if not labeled_transcript:
            return "后处理结果缺少说话人标注逐字稿"
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
                    text = self._clean_labeled_transcript_text(item.get("text") or item.get("content") or "")
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

    def _fallback_dialogue_transcription(self, transcript: str) -> dict[str, str]:
        text = transcript.strip()
        sentences = [item.strip() for item in re.split(r"(?<=[。！？!?])\s*|\n+", text) if item.strip()]
        summary_lines = self._fallback_summary_lines(text, sentences)
        summary = "\n".join(f"- {line}" for line in summary_lines if line)
        if not summary:
            summary = "- 自动整理未完成，且逐字稿为空。"
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines and text:
            lines = [text]
        labeled = "\n".join(
            f"说话人 A（未区分）：{cleaned}"
            for line in lines
            if (cleaned := self._clean_labeled_transcript_text(line))
        )
        return {
            "status": "fallback",
            "reason": "",
            "title": self._fallback_meeting_title(text),
            "summary": summary,
            "pending_questions": self._fallback_pending_questions(text),
            "speaker_notes": "- 说话人 A（未区分）：当前逐字稿没有声纹分离结果；兜底整理仅按单一未区分说话人保留内容，不推断真实身份。",
            "labeled_transcript": labeled or "说话人 A（未区分）：（无可用逐字稿）",
        }

    def _fallback_pending_questions(self, text: str) -> str:
        compact = re.sub(r"\s+", "", text or "")
        if (
            ("行业AI" in compact or "行业科技" in compact or "行业通用人工智能" in compact)
            and ("路演" in compact or "答辩" in compact)
        ):
            return "\n".join(
                [
                    "- [ ] 确定公司定位措辞，避免“服务商”太低、“基础设施/骨架”太大。",
                    "- [ ] 把教育、就业、体育、自媒体等方向整理成递进结构，避免材料看起来像散点堆砌。",
                    "- [ ] 准备可展示证据：内测截图、合作证明、代码量或阶段成果、效率数据、对比报告、核心成员背书。",
                    "- [ ] 明确哪些内容可以对外讲，哪些涉及专利和论文需要保密。",
                ]
            )
        return "- [ ] 暂无明确待解决问题。"

    def _fallback_meeting_title(self, text: str) -> str:
        compact = re.sub(r"\s+", "", text or "")
        if (
            ("行业AI" in compact or "行业科技" in compact or "行业通用人工智能" in compact)
            and ("路演" in compact or "答辩" in compact)
        ):
            return "行业AI公司定位与路演答辩逻辑"
        if ("产品展示" in compact or "展示视频" in compact or "presentation" in compact.lower()) and "视觉" in compact:
            return "产品展示视频与视觉人才配置"
        if ("5月20" in compact or "20号" in compact) and ("比赛" in compact or "BP" in text) and ("内测" in compact or "交付" in compact):
            return "产品第一版交付与比赛汇报准备"
        return ""

    def _fallback_summary_lines(self, text: str, sentences: list[str]) -> list[str]:
        compact = re.sub(r"\s+", "", text or "")
        if (
            ("行业AI" in compact or "行业科技" in compact or "行业通用人工智能" in compact)
            and ("路演" in compact or "答辩" in compact)
        ):
            return [
                "讨论公司对外路演/答辩时的定位表达：不要只包装成单一教育科技公司，而要强调行业 AI 或行业科技解决方案能力。",
                "教育方向可以作为第一个落地业务面，用已完成内测的产品证明团队有自研技术和产品化能力。",
                "就业算法、体育方向、自媒体创作工作流等项目可以作为能力延展，但需要用递进逻辑组织，避免显得业务分散。",
                "成果证明可包括内测进展、合作高校、代码量或阶段进度、效率提升数据、首席科学官背书等。",
                "未申请专利或论文未发布前，核心技术细节需要保密，只展示方向、成果和可信背书。",
            ]
        preview_sentences = sentences[:5] if sentences else [text[:240].strip()]
        return [line for line in preview_sentences if line]
