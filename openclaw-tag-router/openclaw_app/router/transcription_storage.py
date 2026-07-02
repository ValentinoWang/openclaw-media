from __future__ import annotations

from ..services.knowledge_archive_bridge import archive_meeting_content_section
from .tag_router_common import *


class TranscriptionStorageMixin:
    def _save_transcription_meeting_note(
        self,
        message: Message,
        title_hint: str,
        source_text: str,
        product_lines: list[str],
        formatted: dict[str, Any],
        raw_transcript: str,
        *,
        audio_names: list[str] | None = None,
        failures: list[str] | None = None,
        delete_statuses: list[str] | None = None,
    ) -> str:
        topic = self._meeting_note_topic(title_hint, source_text, formatted, audio_names or [])
        date_prefix = message.created_at.strftime("%Y-%m-%d")
        note_dir = ensure_dir(MEETING_MINUTES_DIR)
        note_path = self._unique_markdown_path(note_dir / f"{date_prefix}-{safe_slug(topic, max_len=60)}.md")
        transcript_dir = ensure_dir(MEETING_TRANSCRIPTS_DIR)
        transcript_path = self._unique_markdown_path(transcript_dir / f"{note_path.stem}-原字稿.md")
        note_tags = ["会议纪要", "转写", "语音转文字"]
        transcript_tags = ["原字稿", "转写", "语音转文字"]
        if message.entry_tag == "转写-文字":
            note_tags.append("文字稿整理")
            transcript_tags.append("文字稿整理")
        frontmatter = {
            "source": message.source,
            "entry_tag": message.entry_tag,
            "created_at": format_display_time(message.created_at),
            "status": "archived" if not failures else "partial",
            "tags": note_tags,
            "raw_transcript_path": str(transcript_path),
            "raw_audio_deleted": delete_statuses or [],
            "archive_macro_summary": formatted.get("archive_macro_summary", ""),
            "archive_summary_bullets": formatted.get("archive_summary_bullets", []),
            "postprocess_pipeline": formatted.get("postprocess_pipeline", ""),
            "postprocess_artifacts": formatted.get("postprocess_artifacts", {}),
        }
        transcript_frontmatter = {
            "source": message.source,
            "entry_tag": message.entry_tag,
            "created_at": format_display_time(message.created_at),
            "status": "archived" if not failures else "partial",
            "tags": transcript_tags,
            "meeting_note_path": str(note_path),
            "audio_names": audio_names or [],
            "raw_audio_deleted": delete_statuses or [],
        }
        source_lines = []
        if source_text.strip():
            source_lines.append(f"- 来源说明：{source_text.strip()}")
        if product_lines:
            source_lines.extend(product_lines)
        if not source_lines:
            source_lines.append("- 来源说明：上传录音文件")
        source_lines.extend(
            [
                f"- Obsidian 会议纪要：{note_path}",
                f"- Obsidian 原字稿：{transcript_path}",
            ]
        )

        transcript_source_lines = list(source_lines)
        transcript_source_lines.append(f"- 对应会议纪要：{note_path}")
        transcript_content = ArchiveService.render_markdown(
            transcript_frontmatter,
            f"{date_prefix} {topic} 原字稿",
            [
                ("来源与产物", "\n".join(transcript_source_lines)),
                ("原字稿", raw_transcript.strip() or formatted["labeled_transcript"]),
            ],
        )
        transcript_path.write_text(transcript_content, encoding="utf-8")
        cleanup_generated_file_duplicates(transcript_path)
        self._assert_transcription_raw_transcript_path(transcript_path)
        formatted["obsidian_transcript_path"] = str(transcript_path)

        sections = [
            ("待解决的问题", formatted.get("pending_questions") or self._format_pending_questions("")),
            ("内容整理", formatted["summary"]),
            ("主题细节", formatted.get("theme_sections") or "暂无额外主题细节。"),
            ("决定与判断", formatted.get("decisions") or "暂无明确决定或判断。"),
            ("行动项", formatted.get("action_items") or "暂无明确行动项。"),
            ("对话人说明", formatted["speaker_notes"]),
            ("说话人标注逐字稿", formatted["labeled_transcript"]),
            ("来源与产物", "\n".join(source_lines)),
        ]
        consistency_section = self._format_consistency_check(formatted.get("consistency_check"))
        if consistency_section:
            sections.append(("一致性检查", consistency_section))
        if failures:
            sections.append(("未完成文件", "\n".join(f"- {item}" for item in failures)))
        content = ArchiveService.render_markdown(frontmatter, f"{date_prefix} {topic}", sections)
        content = content.replace("\n## 待解决的问题\n", "\n# 待解决的问题\n", 1)
        note_path.write_text(content, encoding="utf-8")
        cleanup_generated_file_duplicates(note_path)
        self._assert_transcription_meeting_note_path(note_path)
        knowledge_archive = archive_meeting_content_section(note_path)
        formatted["knowledge_archive"] = knowledge_archive.to_dict()
        return str(note_path)

    def _assert_transcription_meeting_note_path(self, note_path: Path) -> None:
        try:
            resolved_note = note_path.resolve(strict=True)
            resolved_dir = MEETING_MINUTES_DIR.resolve(strict=True)
        except OSError as exc:
            raise RuntimeError(f"转写会议纪要落盘失败：{exc}") from exc
        try:
            is_under_meeting_dir = resolved_note.is_relative_to(resolved_dir)
        except AttributeError:
            is_under_meeting_dir = str(resolved_note).startswith(str(resolved_dir) + os.sep)
        if not is_under_meeting_dir:
            raise RuntimeError(f"转写会议纪要必须写入 {resolved_dir}，实际写入：{resolved_note}")
        if resolved_note.suffix != ".md":
            raise RuntimeError(f"转写会议纪要必须是 Markdown 文件：{resolved_note}")

    def _assert_transcription_raw_transcript_path(self, transcript_path: Path) -> None:
        try:
            resolved_note = transcript_path.resolve(strict=True)
            resolved_dir = MEETING_TRANSCRIPTS_DIR.resolve(strict=True)
        except OSError as exc:
            raise RuntimeError(f"转写原字稿落盘失败：{exc}") from exc
        try:
            is_under_transcript_dir = resolved_note.is_relative_to(resolved_dir)
        except AttributeError:
            is_under_transcript_dir = str(resolved_note).startswith(str(resolved_dir) + os.sep)
        if not is_under_transcript_dir:
            raise RuntimeError(f"转写原字稿必须写入 {resolved_dir}，实际写入：{resolved_note}")
        if resolved_note.suffix != ".md":
            raise RuntimeError(f"转写原字稿必须是 Markdown 文件：{resolved_note}")

    def _meeting_note_topic(self, title_hint: str, source_text: str, formatted: dict[str, Any], audio_names: list[str]) -> str:
        body = (source_text or "").strip()
        is_batch_context = self._looks_like_transcription_batch_context(body)
        for line in body.splitlines():
            clean_line = line.strip()
            match = re.match(r"^(?:会议主题|主题|标题|会议|纪要)\s*[:：]\s*(.+)$", clean_line)
            if match:
                topic = self._clean_meeting_topic_candidate(match.group(1))
                if topic:
                    return topic
        if body and not is_batch_context and not contains_link(body) and not re.search(r"/home/ubuntu/", body):
            topic = self._clean_meeting_topic_candidate(body.splitlines()[0])
            if topic:
                return topic
        topic = self._clean_meeting_topic_candidate(formatted.get("title", ""))
        if topic:
            return topic
        topic = self._clean_meeting_topic_candidate(title_hint)
        if topic:
            return topic
        summary_topic = self._topic_from_summary(formatted.get("summary", ""))
        if summary_topic:
            return summary_topic
        for audio_name in audio_names:
            stem = Path(audio_name).stem.strip()
            if stem and not self._looks_like_generated_filename(stem):
                topic = self._knowledge_compact_title(stem, limit=36)
                if topic:
                    return topic
        return "录音转写"

    def _topic_from_summary(self, summary: str) -> str:
        for line in str(summary or "").splitlines():
            text = line.strip().lstrip("-*•0123456789.、 ").strip()
            if text:
                text = re.sub(r"^(后半段讨论偏向|讨论围绕|主要围绕|讨论认为|主要讨论|有人提出|讨论了|讨论|提到|围绕)", "", text).strip()
                topic = self._clean_meeting_topic_candidate(text)
                if topic:
                    return topic
        return ""

    def _clean_meeting_topic_candidate(self, value: Any) -> str:
        topic = self._knowledge_compact_title(str(value or ""), limit=36)
        if not topic:
            return ""
        if topic in {"视频音频转写", "录音转写", "上传录音文件"}:
            return ""
        if self._looks_like_transcription_batch_context(topic):
            return ""
        if re.match(r"^(?:附件上传顺序|等待池已结束|处理方式|输出最终结果时|来源补充|本批次包含|未提供可访问|当前仅基于)", topic):
            return ""
        return topic

    def _looks_like_transcription_batch_context(self, text: str) -> bool:
        body = str(text or "").strip()
        if not body:
            return False
        if body.startswith("这是一组连续上传的附件素材"):
            return True
        markers = (
            "附件上传顺序",
            "等待池已结束",
            "本批附件作为同一个 batch",
            "处理方式：先按上传顺序建立 manifest",
            "输出最终结果时保留附件顺序",
        )
        return sum(1 for marker in markers if marker in body) >= 2

    def _looks_like_generated_filename(self, stem: str) -> bool:
        text = stem.strip().lower()
        return bool(
            re.fullmatch(r"[0-9a-f]{8,}(?:-[0-9a-f]{4,}){2,}", text)
            or re.fullmatch(r"[0-9a-f-]{24,}", text)
            or re.fullmatch(r"\d{10,}", text)
        )

    def _unique_markdown_path(self, path: Path) -> Path:
        if not path.exists():
            return path
        for index in range(2, 1000):
            candidate = path.with_name(f"{path.stem}-{index}{path.suffix}")
            if not candidate.exists():
                return candidate
        raise RuntimeError(f"无法生成不冲突的会议纪要文件名：{path}")

    def _delete_uploaded_audio_file(self, path: Path) -> str:
        try:
            resolved = path.resolve(strict=False)
        except OSError as exc:
            return f"否（路径解析失败：{exc}）"
        is_uploaded = False
        for root_path in UPLOADED_MEDIA_ROOTS:
            try:
                root = root_path.resolve()
            except OSError:
                continue
            try:
                is_uploaded = resolved.is_relative_to(root)
            except AttributeError:
                is_uploaded = str(resolved).startswith(str(root) + os.sep)
            if is_uploaded:
                break
        if not is_uploaded:
            return "不适用（不是上传缓存文件）"
        try:
            if resolved.exists() and resolved.is_file():
                resolved.unlink()
            return "是"
        except OSError as exc:
            return f"否（删除失败：{exc}）"

    def _file_sha256(self, path: Path) -> str:
        digest = hashlib.sha256()
        try:
            with path.open("rb") as handle:
                for block in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(block)
        except OSError:
            return ""
        return digest.hexdigest()

    def _transcription_attachment_paths(self, message: Message) -> list[str]:
        candidates: list[str] = []

        def add(value: object) -> None:
            if not isinstance(value, str):
                return
            text = value.strip()
            if not text:
                return
            path_matches = re.findall(r"/[^\s\]\)\|`'\"<>]+", text)
            if path_matches:
                candidates.extend(match.rstrip("，。；;,.:：") for match in path_matches)
            else:
                candidates.append(text)

        def walk(value: object) -> None:
            if isinstance(value, dict):
                for key in (
                    "path",
                    "file_path",
                    "filePath",
                    "local_path",
                    "localPath",
                    "downloaded_path",
                    "downloadedPath",
                    "url",
                ):
                    add(value.get(key))
                for nested in value.values():
                    if isinstance(nested, (dict, list, tuple)):
                        walk(nested)
                    elif isinstance(nested, str):
                        add(nested)
            elif isinstance(value, (list, tuple)):
                for item in value:
                    walk(item)
            else:
                add(value)

        metadata = message.metadata or {}
        for key in (
            "downloaded_paths",
            "attachment_paths",
            "attachments",
            "files",
            "media",
            "local_paths",
            "file_paths",
            "conversation_context",
            "cached_media",
            "previous_media",
            "previous_attachments",
        ):
            if key in metadata:
                walk(metadata.get(key))
        context = self._conversation_context(message)
        if context:
            walk(context)
        for text in (message.body, message.raw_text, self._conversation_context_prompt(message)):
            add(text)

        for recent_path in self._recent_uploaded_audio_paths(message.created_at):
            add(str(recent_path))

        seen: set[str] = set()
        paths: list[str] = []
        for item in candidates:
            path = Path(item)
            if not path.is_absolute() or not path.is_file():
                continue
            if path.suffix.lower() not in TRANSCRIPTION_AUDIO_EXTS:
                continue
            normalized = str(path)
            if normalized in seen:
                continue
            seen.add(normalized)
            paths.append(normalized)
        return paths

    def _recent_uploaded_audio_paths(self, created_at: datetime) -> list[Path]:
        try:
            created_ts = created_at.timestamp()
        except Exception:
            created_ts = datetime.now().timestamp()
        start_ts = created_ts - TRANSCRIPTION_BATCH_WINDOW_SECONDS
        # Allow a small positive skew for files whose mtime lands just after the tag message.
        end_ts = created_ts + 10
        paths: list[Path] = []
        seen: set[str] = set()
        for root in UPLOADED_MEDIA_ROOTS:
            if not root.is_dir():
                continue
            try:
                entries = list(root.iterdir())
            except OSError:
                continue
            for path in entries:
                if not path.is_file() or path.suffix.lower() not in TRANSCRIPTION_AUDIO_EXTS:
                    continue
                try:
                    mtime = path.stat().st_mtime
                except OSError:
                    continue
                normalized = str(path)
                if start_ts <= mtime <= end_ts and normalized not in seen:
                    seen.add(normalized)
                    paths.append(path)
        paths.sort(key=lambda item: item.stat().st_mtime if item.exists() else 0)
        return paths
