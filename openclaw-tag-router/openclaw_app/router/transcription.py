from __future__ import annotations

from .tag_router_common import *


TRANSCRIPTION_TEXT_EXTS = {".txt", ".text", ".md", ".markdown"}


class TranscriptionMixin:
    def _emit_transcription_progress(self, message: Message, stage: str, **details: object) -> None:
        path_value = str((message.metadata or {}).get("transcription_progress_path") or "").strip()
        if not path_value:
            return
        path = Path(path_value)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "stage": stage,
            "at": datetime.now().astimezone().isoformat(),
            "job_id": str((message.metadata or {}).get("transcription_job_id") or ""),
            **{key: value for key, value in details.items() if value not in (None, "", [], {})},
        }
        line = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
        descriptor = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
        try:
            os.write(descriptor, line)
        finally:
            os.close(descriptor)

    def _transcription_postprocess_artifact_dir(self, message: Message, default: Path) -> Path:
        candidate_value = str((message.metadata or {}).get("transcription_resume_postprocess_dir") or "").strip()
        if not candidate_value:
            return default
        candidate = Path(candidate_value)
        try:
            resolved = candidate.resolve(strict=True)
            content_flow_root = (self.workspace_root / "content_flow").resolve(strict=True)
            if resolved.name == "postprocess" and resolved.is_relative_to(content_flow_root):
                return resolved
        except (AttributeError, OSError):
            pass
        return default

    def handle_转写_文字(self, message: Message) -> TaskResult:
        body = message.body.strip()
        title_hint, body_transcript = self._transcription_text_body_parts(body)
        text_paths = self._transcription_text_attachment_paths(message)
        transcript_blocks: list[str] = []
        if body_transcript:
            transcript_blocks.append(body_transcript)

        text_names: list[str] = []
        unreadable_paths: list[str] = []
        for index, text_path in enumerate(text_paths, start=1):
            path = Path(text_path)
            text = self._knowledge_read_text_file(str(path))
            if not text:
                unreadable_paths.append(str(path))
                continue
            display_name = path.name or f"文字稿{index}"
            text_names.append(display_name)
            transcript_blocks.append(f"### 文字稿 {index}：{display_name}\n{text}")

        combined_transcript = "\n\n".join(item.strip() for item in transcript_blocks if item.strip()).strip()
        if not combined_transcript:
            entry = self.archive_service.save_archive(
                message,
                "转写文字待处理",
                [
                    ("来源", body or "未提供文字稿"),
                    ("处理状态", "pending_manual\n原因：未检测到可整理的语音转文字稿"),
                ],
                {"status": "pending_manual", "tags": ["转写", "转写-文字", "语音转文字"]},
            )
            return TaskResult(
                ok=False,
                status="missing_input",
                reply=(
                    "转写文字整理未开始\n"
                    "原因：未检测到可整理的语音转文字稿\n"
                    "请发送 `【转写-文字】\\n主题：...\\n文字稿：...`，或上传 `.txt`/`.md` 文字稿附件后再发送 `【转写-文字】`。"
                ),
                task_id=entry.frontmatter["id"],
                local_path=entry.local_path,
            )

        task_dir = ensure_dir(
            self.workspace_root
            / "content_flow"
            / "text_transcripts"
            / make_record_id(message.created_at, message.source, message.entry_tag)
        )
        raw_path = task_dir / "combined_transcript.txt"
        raw_path.write_text(combined_transcript.strip() + "\n", encoding="utf-8")
        transcript_for_postprocess = self._clean_transcript_for_postprocess(combined_transcript)
        clean_path = task_dir / "clean_transcript.txt"
        clean_path.write_text(transcript_for_postprocess.strip() + "\n", encoding="utf-8")
        product_lines = [
            "- 输入类型：已转写文字稿（不做原始音频 ASR）",
            f"- 文字稿任务目录：{task_dir}",
            f"- 合并文字稿：{raw_path}",
            f"- 清理稿路径：{clean_path}",
        ]
        if body_transcript:
            product_lines.append("- 正文文字稿：已合并")
        if text_paths:
            product_lines.append("- 文字稿附件：\n" + "\n".join(f"- {item}" for item in text_paths))
        if unreadable_paths:
            product_lines.append("- 无法读取的文字稿附件：\n" + "\n".join(f"- {item}" for item in unreadable_paths))

        source_hint = f"主题：{title_hint}" if title_hint else ""
        self._emit_transcription_progress(
            message,
            "postprocess_started",
            transcript_count=len(text_paths) + (1 if body_transcript else 0),
        )
        artifact_dir = self._transcription_postprocess_artifact_dir(message, task_dir / "postprocess")
        formatted = self._format_dialogue_transcription(transcript_for_postprocess, source_hint or body, artifact_dir=artifact_dir)
        product_lines.extend(self._postprocess_artifact_lines(formatted))
        if not self._transcription_postprocess_succeeded(formatted):
            self._emit_transcription_progress(message, "postprocess_failed")
            reason = formatted["reason"] or "转写后处理摘要/说话人整理失败"
            entry = self.archive_service.save_archive(
                message,
                f"转写文字后处理失败：{title_hint}",
                [
                    ("来源", source_hint or "已转写文字稿"),
                    ("产物", "\n".join(product_lines)),
                    ("处理状态", f"pending_manual\n原因：{reason}"),
                ],
                {
                    "status": "pending_manual",
                    "tags": ["转写", "转写-文字", "语音转文字", "后处理失败"],
                    "transcript_paths": [str(raw_path), str(clean_path)],
                    "text_attachment_paths": text_paths,
                    "media_dir": str(task_dir),
                    "postprocess_status": formatted["status"],
                    "postprocess_reason": reason,
                    "postprocess_artifacts": formatted.get("postprocess_artifacts", {}),
                },
            )
            return TaskResult(
                ok=False,
                status="pending_manual",
                reply=(
                    "转写文字整理未完成\n"
                    f"原因：转写后处理摘要/说话人整理失败：{reason}\n"
                    f"文字稿任务目录：{task_dir}\n"
                    f"本地归档：{entry.local_path}"
                ),
                task_id=entry.frontmatter["id"],
                local_path=entry.local_path,
                extra={"postprocess": formatted, "text_attachment_paths": text_paths},
            )

        self._emit_transcription_progress(
            message,
            "postprocess_completed",
            chunk_count=formatted.get("chunk_count", 0),
            attachment_count=formatted.get("attachment_count", 0),
        )

        topic = self._meeting_note_topic(title_hint, source_hint, formatted, text_names)
        obsidian_path = self._save_transcription_meeting_note(
            message,
            topic,
            source_hint,
            product_lines,
            formatted,
            transcript_for_postprocess,
            audio_names=text_names,
            failures=unreadable_paths,
        )
        obsidian_transcript_path = str(formatted.get("obsidian_transcript_path") or "")
        obsidian_topical_attachments_path = str(formatted.get("obsidian_topical_attachments_path") or "")
        entry = self.archive_service.save_archive(
            message,
            f"转写文字：{topic}",
            [
                ("来源", source_hint or "已转写文字稿"),
                ("产物", "\n".join(product_lines)),
                ("Obsidian 会议纪要", obsidian_path),
                ("Obsidian 原字稿", obsidian_transcript_path),
                ("Obsidian 专题附件", obsidian_topical_attachments_path or "无独立专题附件"),
                ("Knowledge 归档", self._transcription_knowledge_archive_summary(formatted)),
                ("结论摘要", formatted["conclusion_summary"]),
                ("决策清单", formatted["decision_list"]),
                ("待拍板问题", formatted["pending_decisions"]),
                ("待验证假设", formatted["validation_hypotheses"]),
                ("行动项", formatted["action_items"]),
            ],
            {
                "status": "archived" if not unreadable_paths else "partial",
                "tags": ["转写", "转写-文字", "语音转文字", "会议纪要", "决策接口"],
                "transcript_paths": [str(raw_path), str(clean_path)],
                "text_attachment_paths": text_paths,
                "media_dir": str(task_dir),
                "postprocess_status": formatted["status"],
                "obsidian_path": obsidian_path,
                "obsidian_transcript_path": obsidian_transcript_path,
                "obsidian_topical_attachments_path": obsidian_topical_attachments_path,
                "knowledge_archive": formatted.get("knowledge_archive", {}),
                "postprocess_artifacts": formatted.get("postprocess_artifacts", {}),
            },
        )
        self._emit_transcription_progress(
            message,
            "persisted",
            task_id=entry.frontmatter["id"],
        )
        preview = self._truncate_transcript_reply(
            "\n".join(
                [
                    "结论摘要：",
                    formatted["conclusion_summary"],
                    "",
                    "行动项：",
                    formatted["action_items"],
                ]
            )
        )
        reply_lines = [
            "转写文字整理完成" if not unreadable_paths else "转写文字整理部分完成",
            f"任务ID：{entry.frontmatter['id']}",
            f"本地归档：{entry.local_path}",
            f"Obsidian：{obsidian_path}",
            f"Obsidian原字稿：{obsidian_transcript_path}",
            *([f"Obsidian专题附件：{obsidian_topical_attachments_path}"] if obsidian_topical_attachments_path else []),
            *self._transcription_knowledge_archive_reply_lines(formatted),
            f"文字稿任务目录：{task_dir}",
            "",
            preview,
        ]
        if unreadable_paths:
            reply_lines.extend(["", "未读取文字稿附件：", "\n".join(f"- {item}" for item in unreadable_paths)])
        return TaskResult(
            ok=not unreadable_paths,
            status="archived" if not unreadable_paths else "partial",
            reply="\n".join(reply_lines),
            task_id=entry.frontmatter["id"],
            local_path=entry.local_path,
            extra={"postprocess": formatted, "text_attachment_paths": text_paths},
        )

    def handle_转写(self, message: Message) -> TaskResult:
        body = message.body.strip()
        audio_paths = self._transcription_attachment_paths(message)
        if audio_paths:
            return self._handle_transcription_files(message, body, audio_paths)

        if not body:
            return TaskResult(
                ok=False,
                status="missing_input",
                reply="请上传录音文件并发送 `【转写】`；也可以临时发送 `【转写】` + content-flow 可处理的视频/音频链接。",
                task_id="",
            )
        if not contains_link(body):
            entry = self.archive_service.save_archive(
                message,
                "转写待处理",
                [
                    ("原始内容", body),
                    ("处理状态", "未检测到上传录音文件或可处理链接。请把录音文件作为附件上传，并在正文发送 `【转写】`。"),
                ],
                {"status": "pending_manual", "tags": ["转写"]},
            )
            return TaskResult(
                ok=False,
                status="pending_manual",
                reply=f"转写未开始\n原因：未检测到上传录音文件或可处理链接\n本地归档：{entry.local_path}",
                task_id=entry.frontmatter["id"],
                local_path=entry.local_path,
            )

        result = self.content_flow_client.analyze(body)
        transcript = self._knowledge_read_text_file(str(result.get("transcript_path") or ""))
        product_lines = []
        for label, key in [
            ("素材目录", "media_dir"),
            ("逐字稿路径", "transcript_path"),
            ("音频路径", "audio_path"),
            ("视频路径", "video_path"),
        ]:
            value = str(result.get(key) or "").strip()
            if value:
                product_lines.append(f"- {label}：{value}")

        if result.get("status") == "done" and transcript:
            title = self._knowledge_title_from_share_text(body) or "视频音频转写"
            transcript_for_postprocess = self._clean_transcript_for_postprocess(transcript)
            if result.get("media_dir"):
                clean_path = Path(str(result["media_dir"])) / "clean_transcript.txt"
                try:
                    clean_path.write_text(transcript_for_postprocess.strip() + "\n", encoding="utf-8")
                    product_lines.append(f"- 清理稿路径：{clean_path}")
                except OSError:
                    pass
            artifact_base = Path(str(result.get("media_dir") or "")) if result.get("media_dir") else self.workspace_root / "content_flow" / "postprocess"
            artifact_dir = self._transcription_postprocess_artifact_dir(message, artifact_base / "postprocess")
            formatted = self._format_dialogue_transcription(transcript_for_postprocess, body, artifact_dir=artifact_dir)
            product_lines.extend(self._postprocess_artifact_lines(formatted))
            if not self._transcription_postprocess_succeeded(formatted):
                reason = formatted["reason"] or "转写后处理摘要/说话人整理失败"
                entry = self.archive_service.save_archive(
                    message,
                    f"转写后处理失败：{title}",
                    [
                        ("来源", body),
                        ("产物", "\n".join(product_lines) or "content-flow 未返回本地产物路径"),
                        ("处理状态", f"pending_manual\n原因：{reason}"),
                    ],
                    {
                        "status": "pending_manual",
                        "tags": ["转写", "语音转文字", "后处理失败"],
                        "transcript_path": result.get("transcript_path", ""),
                        "media_dir": result.get("media_dir", ""),
                        "postprocess_status": formatted["status"],
                        "postprocess_reason": reason,
                        "postprocess_artifacts": formatted.get("postprocess_artifacts", {}),
                    },
                )
                return TaskResult(
                    ok=False,
                    status="pending_manual",
                    reply=(
                        "转写未完成\n"
                        f"原因：转写后处理摘要/说话人整理失败：{reason}\n"
                        f"逐字稿路径：{result.get('transcript_path', '')}\n"
                        f"本地归档：{entry.local_path}"
                    ),
                    task_id=entry.frontmatter["id"],
                    local_path=entry.local_path,
                    extra={"transcription": result, "postprocess": formatted},
                )
            topic = self._meeting_note_topic(title, body, formatted, [])
            obsidian_path = self._save_transcription_meeting_note(
                message,
                topic,
                body,
                product_lines,
                formatted,
                transcript_for_postprocess,
            )
            obsidian_transcript_path = str(formatted.get("obsidian_transcript_path") or "")
            obsidian_topical_attachments_path = str(formatted.get("obsidian_topical_attachments_path") or "")
            entry = self.archive_service.save_archive(
                message,
                f"转写：{topic}",
                [
                    ("来源", body),
                    ("产物", "\n".join(product_lines) or "content-flow 未返回本地产物路径"),
                    ("Obsidian 会议纪要", obsidian_path),
                    ("Obsidian 原字稿", obsidian_transcript_path),
                    ("Obsidian 专题附件", obsidian_topical_attachments_path or "无独立专题附件"),
                    ("Knowledge 归档", self._transcription_knowledge_archive_summary(formatted)),
                    ("结论摘要", formatted["conclusion_summary"]),
                    ("决策清单", formatted["decision_list"]),
                    ("待拍板问题", formatted["pending_decisions"]),
                    ("待验证假设", formatted["validation_hypotheses"]),
                    ("行动项", formatted["action_items"]),
                ],
                {
                    "status": "archived",
                    "tags": ["转写", "语音转文字", "会议纪要", "决策接口"],
                    "transcript_path": result.get("transcript_path", ""),
                    "media_dir": result.get("media_dir", ""),
                    "postprocess_status": formatted["status"],
                    "obsidian_path": obsidian_path,
                    "obsidian_transcript_path": obsidian_transcript_path,
                    "obsidian_topical_attachments_path": obsidian_topical_attachments_path,
                    "knowledge_archive": formatted.get("knowledge_archive", {}),
                    "postprocess_artifacts": formatted.get("postprocess_artifacts", {}),
                },
            )
            preview = self._truncate_transcript_reply(
                "\n".join(
                    [
                        "结论摘要：",
                        formatted["conclusion_summary"],
                        "",
                        "行动项：",
                        formatted["action_items"],
                    ]
                )
            )
            reply = "\n".join(
                [
                    "转写完成",
                    f"任务ID：{entry.frontmatter['id']}",
                    f"本地归档：{entry.local_path}",
                    f"Obsidian：{obsidian_path}",
                    f"Obsidian原字稿：{obsidian_transcript_path}",
                    *([f"Obsidian专题附件：{obsidian_topical_attachments_path}"] if obsidian_topical_attachments_path else []),
                    *self._transcription_knowledge_archive_reply_lines(formatted),
                    f"逐字稿路径：{result.get('transcript_path', '')}",
                    "",
                    preview,
                ]
            )
            return TaskResult(
                ok=True,
                status="archived",
                reply=reply,
                task_id=entry.frontmatter["id"],
                local_path=entry.local_path,
                extra=result,
            )

        reason = str(result.get("reason") or "content-flow 未产出逐字稿；可能是非视频、DashScope ASR 失败，或音频提取失败")
        entry = self.archive_service.save_archive(
            message,
            "转写待处理",
            [
                ("来源", body),
                ("处理状态", f"pending_manual\n原因：{reason}"),
                ("产物", "\n".join(product_lines) or "content-flow 未返回本地产物路径"),
            ],
            {
                "status": "pending_manual",
                "tags": ["转写", "语音转文字"],
                "transcript_path": result.get("transcript_path", ""),
                "media_dir": result.get("media_dir", ""),
            },
        )
        return TaskResult(
            ok=False,
            status="pending_manual",
            reply=f"转写未完成\n原因：{reason}\n本地归档：{entry.local_path}",
            task_id=entry.frontmatter["id"],
            local_path=entry.local_path,
            extra=result,
        )

    def _handle_transcription_files(self, message: Message, body: str, audio_paths: list[str]) -> TaskResult:
        attachment_names = {
            str(item.get("path") or ""): str(item.get("name") or "").strip()
            for item in (message.metadata or {}).get("transcription_attachments", [])
            if isinstance(item, dict) and str(item.get("path") or "").strip()
        }
        task_dir = ensure_dir(
            self.workspace_root
            / "content_flow"
            / "uploaded_transcripts"
            / make_record_id(message.created_at, message.source, message.entry_tag)
        )
        manifest_path = task_dir / "batch-manifest.json"
        manifest: dict[str, Any] = {
            "schema_version": "1.0",
            "created_at": format_display_time(message.created_at),
            "task_dir": str(task_dir),
            "original_count": len(audio_paths),
            "unique_count": 0,
            "duplicate_count": 0,
            "attachments": [],
        }
        sha_to_attachment_id: dict[str, str] = {}
        unique_entries: list[dict[str, Any]] = []
        manifest_failures: list[str] = []
        for original_index, audio_path in enumerate(audio_paths, start=1):
            source_path = Path(audio_path)
            display_name = attachment_names.get(str(source_path)) or source_path.name or f"录音{original_index}"
            size_bytes = source_path.stat().st_size if source_path.exists() and source_path.is_file() else 0
            sha256 = self._file_sha256(source_path) if source_path.exists() and source_path.is_file() else ""
            duplicate_of = sha_to_attachment_id.get(sha256) if sha256 else ""
            if duplicate_of:
                attachment_id = duplicate_of
                status = "duplicate"
            else:
                attachment_id = f"audio-{len(unique_entries) + 1:02d}"
                status = "queued" if source_path.exists() and source_path.is_file() else "missing"
                if sha256:
                    sha_to_attachment_id[sha256] = attachment_id
                unique_entries.append(
                    {
                        "attachment_id": attachment_id,
                        "original_index": original_index,
                        "path": str(source_path),
                        "filename": display_name,
                        "sha256": sha256,
                        "size_bytes": size_bytes,
                    }
                )
                if status == "missing":
                    manifest_failures.append(f"{display_name}：录音文件不存在")
            manifest["attachments"].append(
                {
                    "original_index": original_index,
                    "attachment_id": attachment_id,
                    "filename": display_name,
                    "path": str(source_path),
                    "size_bytes": size_bytes,
                    "sha256": sha256,
                    "status": status,
                    "duplicate_of": duplicate_of,
                }
            )
        manifest["unique_count"] = len(unique_entries)
        manifest["duplicate_count"] = sum(1 for item in manifest["attachments"] if item.get("status") == "duplicate")
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        transcript_blocks: list[str] = []
        product_lines: list[str] = [
            f"- Batch Manifest：{manifest_path}",
            f"- 原始附件数：{manifest['original_count']}",
            f"- 唯一附件数：{manifest['unique_count']}",
            f"- 重复附件数：{manifest['duplicate_count']}",
        ]
        results: list[dict[str, Any]] = []
        failures: list[str] = list(manifest_failures)
        delete_statuses: list[str] = []
        delete_status_values: list[str] = []
        if manifest["duplicate_count"]:
            duplicate_lines = [
                f"- {item['filename']} → {item['duplicate_of']}"
                for item in manifest["attachments"]
                if item.get("status") == "duplicate"
            ]
            product_lines.append("- 重复附件去重：\n" + "\n".join(duplicate_lines))

        self._emit_transcription_progress(
            message,
            "asr_started",
            attachment_count=len(unique_entries),
            task_dir=str(task_dir),
        )

        for entry in unique_entries:
            source_path = Path(str(entry["path"]))
            attachment_id = str(entry["attachment_id"])
            output_dir = task_dir / f"{attachment_id}-{safe_slug(source_path.stem)}"
            result = self.content_flow_client.transcribe_file(str(source_path), output_dir)
            result["attachment_id"] = attachment_id
            result["original_indexes"] = [
                item["original_index"]
                for item in manifest["attachments"]
                if item.get("attachment_id") == attachment_id
            ]
            results.append(result)
            transcript_path = str(result.get("transcript_path") or "").strip()
            display_name = str(entry.get("filename") or source_path.name or attachment_id)
            product_lines.append(f"- 录音文件 {attachment_id}：{display_name}")
            if result.get("transcript_path"):
                product_lines.append(f"- 逐字稿路径 {attachment_id}：{transcript_path}")
            for item in manifest["attachments"]:
                if item.get("attachment_id") == attachment_id and not item.get("duplicate_of"):
                    item["transcription_status"] = result.get("status")
                    item["transcript_path"] = transcript_path
                    item["media_dir"] = str(result.get("media_dir") or "")
            if result.get("status") != "done":
                failures.append(f"{display_name}：{result.get('reason') or '转写失败'}")
                continue
            transcript = self._knowledge_read_text_file(transcript_path)
            if transcript:
                transcript = self._clean_transcript_for_postprocess(transcript)
                clean_path = output_dir / "clean_transcript.txt"
                clean_path.write_text(transcript.strip() + "\n", encoding="utf-8")
                result["clean_transcript_path"] = str(clean_path)
                product_lines.append(f"- 清理稿路径 {attachment_id}：{clean_path}")
                for item in manifest["attachments"]:
                    if item.get("attachment_id") == attachment_id and not item.get("duplicate_of"):
                        item["clean_transcript_path"] = str(clean_path)
                audio_number = int(attachment_id.rsplit("-", 1)[-1]) if attachment_id.rsplit("-", 1)[-1].isdigit() else len(transcript_blocks) + 1
                transcript_blocks.append(f"### 录音 {audio_number}：{display_name}\n{transcript}")
                self._emit_transcription_progress(
                    message,
                    "asr_file_completed",
                    attachment_id=attachment_id,
                    completed_count=len(transcript_blocks),
                    attachment_count=len(unique_entries),
                    clean_transcript_path=str(clean_path),
                    display_name=display_name,
                )
            else:
                failures.append(f"{display_name}：ASR 完成但逐字稿为空")

        for item in manifest["attachments"]:
            source_path = Path(str(item.get("path") or ""))
            display_name = str(item.get("filename") or source_path.name or f"附件{item.get('original_index')}")
            if item.get("transcription_status") != "done" and not item.get("duplicate_of"):
                delete_status = "否（转写未完成，保留用于重试）"
            elif bool((message.metadata or {}).get("transcription_defer_source_delete")):
                delete_status = "否（异步任务完成后删除）"
            else:
                delete_status = self._delete_uploaded_audio_file(source_path)
            item["delete_status"] = delete_status
            delete_status_values.append(delete_status)
            delete_statuses.append(f"- {display_name}：{delete_status}")
        for item in manifest["attachments"]:
            if item.get("status") == "duplicate":
                original = next((other for other in manifest["attachments"] if other.get("attachment_id") == item.get("duplicate_of") and not other.get("duplicate_of")), {})
                item["transcription_status"] = "skipped_duplicate"
                item["transcript_path"] = original.get("transcript_path", "")
                item["clean_transcript_path"] = original.get("clean_transcript_path", "")
                item["media_dir"] = original.get("media_dir", "")
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        product_lines.append(
            "- 原始录音转写后删除："
            + ("全部成功" if delete_status_values and all(item == "是" for item in delete_status_values) else "\n" + "\n".join(delete_statuses))
        )

        combined_transcript = "\n\n".join(transcript_blocks).strip()
        if not combined_transcript:
            entry = self.archive_service.save_archive(
                message,
                "转写待处理",
                [
                    ("来源", body or "上传录音文件"),
                    ("产物", "\n".join(product_lines) or "无"),
                    ("处理状态", "pending_manual\n" + "\n".join(failures or ["未产出逐字稿"])),
                ],
                {
                    "status": "pending_manual",
                    "tags": ["转写", "语音转文字"],
                    "raw_audio_deleted": delete_statuses,
                    "batch_manifest": str(manifest_path),
                },
            )
            return TaskResult(
                ok=False,
                status="pending_manual",
                reply=f"转写未完成\n原因：{'; '.join(failures or ['未产出逐字稿'])}\n本地归档：{entry.local_path}",
                task_id=entry.frontmatter["id"],
                local_path=entry.local_path,
                extra={"results": results, "batch_manifest": manifest},
            )

        self._emit_transcription_progress(
            message,
            "postprocess_started",
            transcript_count=len(transcript_blocks),
        )
        artifact_dir = self._transcription_postprocess_artifact_dir(message, task_dir / "postprocess")
        formatted = self._format_dialogue_transcription(combined_transcript, body, artifact_dir=artifact_dir)
        product_lines.extend(self._postprocess_artifact_lines(formatted))
        title_hint = self._knowledge_title_from_share_text(body) if body else ""
        if not self._transcription_postprocess_succeeded(formatted):
            self._emit_transcription_progress(message, "postprocess_failed")
            reason = formatted["reason"] or "转写后处理摘要/说话人整理失败"
            entry = self.archive_service.save_archive(
                message,
                f"转写后处理失败：{title_hint}",
                [
                    ("来源", body or "上传录音文件"),
                    ("产物", "\n".join(product_lines) or "content-flow 未返回本地产物路径"),
                    ("处理状态", f"pending_manual\n原因：{reason}"),
                ],
                {
                    "status": "pending_manual",
                    "tags": ["转写", "语音转文字", "后处理失败"],
                    "raw_audio_deleted": delete_statuses,
                    "transcript_paths": [str(result.get("transcript_path") or "") for result in results if result.get("transcript_path")],
                    "media_dir": str(task_dir),
                    "postprocess_status": formatted["status"],
                    "postprocess_reason": reason,
                    "batch_manifest": str(manifest_path),
                    "postprocess_artifacts": formatted.get("postprocess_artifacts", {}),
                },
            )
            return TaskResult(
                ok=False,
                status="pending_manual",
                reply=(
                    "转写未完成\n"
                    f"原因：转写后处理摘要/说话人整理失败：{reason}\n"
                    f"素材目录：{task_dir}\n"
                    f"本地归档：{entry.local_path}"
                ),
                task_id=entry.frontmatter["id"],
                local_path=entry.local_path,
                extra={"results": results, "postprocess": formatted, "batch_manifest": manifest},
            )
        self._emit_transcription_progress(
            message,
            "postprocess_completed",
            chunk_count=formatted.get("chunk_count", 0),
            attachment_count=formatted.get("attachment_count", 0),
        )
        audio_names = [str(entry.get("filename") or Path(str(entry.get("path") or "")).name) for entry in unique_entries]
        topic = self._meeting_note_topic(title_hint, body, formatted, audio_names)
        obsidian_path = self._save_transcription_meeting_note(
            message,
            topic,
            body,
            product_lines,
            formatted,
            combined_transcript,
            audio_names=audio_names,
            failures=failures,
            delete_statuses=delete_statuses,
        )
        obsidian_transcript_path = str(formatted.get("obsidian_transcript_path") or "")
        obsidian_topical_attachments_path = str(formatted.get("obsidian_topical_attachments_path") or "")
        entry = self.archive_service.save_archive(
            message,
            f"转写：{topic}",
            [
                ("来源", body or "上传录音文件"),
                ("产物", "\n".join(product_lines) or "content-flow 未返回本地产物路径"),
                ("Obsidian 会议纪要", obsidian_path),
                ("Obsidian 原字稿", obsidian_transcript_path),
                ("Obsidian 专题附件", obsidian_topical_attachments_path or "无独立专题附件"),
                ("Knowledge 归档", self._transcription_knowledge_archive_summary(formatted)),
                ("结论摘要", formatted["conclusion_summary"]),
                ("决策清单", formatted["decision_list"]),
                ("待拍板问题", formatted["pending_decisions"]),
                ("待验证假设", formatted["validation_hypotheses"]),
                ("行动项", formatted["action_items"]),
            ],
            {
                "status": "archived" if not failures else "partial",
                "tags": ["转写", "语音转文字", "会议纪要", "决策接口"],
                "raw_audio_deleted": delete_statuses,
                "transcript_paths": [str(result.get("transcript_path") or "") for result in results if result.get("transcript_path")],
                "media_dir": str(task_dir),
                "postprocess_status": formatted["status"],
                "obsidian_path": obsidian_path,
                "obsidian_transcript_path": obsidian_transcript_path,
                "obsidian_topical_attachments_path": obsidian_topical_attachments_path,
                "knowledge_archive": formatted.get("knowledge_archive", {}),
                "batch_manifest": str(manifest_path),
                "postprocess_artifacts": formatted.get("postprocess_artifacts", {}),
            },
        )
        self._emit_transcription_progress(
            message,
            "persisted",
            task_id=entry.frontmatter["id"],
        )
        preview = self._truncate_transcript_reply(
            "\n".join(
                [
                    "结论摘要：",
                    formatted["conclusion_summary"],
                    "",
                    "行动项：",
                    formatted["action_items"],
                ]
            )
        )
        reply_lines = [
            "转写完成" if not failures else "转写部分完成",
            f"任务ID：{entry.frontmatter['id']}",
            f"本地归档：{entry.local_path}",
            f"Obsidian：{obsidian_path}",
            f"Obsidian原字稿：{obsidian_transcript_path}",
            *([f"Obsidian专题附件：{obsidian_topical_attachments_path}"] if obsidian_topical_attachments_path else []),
            *self._transcription_knowledge_archive_reply_lines(formatted),
            f"素材目录：{task_dir}",
            "原始录音转写后删除：是" if delete_status_values and all(item == "是" for item in delete_status_values) else f"原始录音转写后删除：{'; '.join(delete_statuses) or '不适用'}",
            "",
            preview,
        ]
        if failures:
            reply_lines.extend(["", "未完成文件：", "\n".join(f"- {item}" for item in failures)])
        return TaskResult(
            ok=not failures,
            status="archived" if not failures else "partial",
            reply="\n".join(reply_lines),
            task_id=entry.frontmatter["id"],
            local_path=entry.local_path,
            extra={"results": results, "postprocess": formatted, "batch_manifest": manifest},
        )

    def _transcription_knowledge_archive_summary(self, formatted: dict[str, Any]) -> str:
        result = formatted.get("knowledge_archive") if isinstance(formatted.get("knowledge_archive"), dict) else {}
        status = str(result.get("status") or "not_run")
        path = str(result.get("path") or "")
        if result.get("ok") and path:
            return f"{status}\nObsidian 周记：{path}\n小节：# {result.get('section') or '知识'}"
        error = str(result.get("error") or result.get("stderr") or "")
        return f"{status}" + (f"\n原因：{error}" if error else "")

    def _transcription_knowledge_archive_reply_lines(self, formatted: dict[str, Any]) -> list[str]:
        result = formatted.get("knowledge_archive") if isinstance(formatted.get("knowledge_archive"), dict) else {}
        path = str(result.get("path") or "")
        status = str(result.get("status") or "")
        if result.get("ok") and path:
            label = "Knowledge归档"
            if status == "skipped_existing":
                label = "Knowledge归档：已存在"
            return [f"{label}：{path}"]
        if status:
            return [f"Knowledge归档：未完成（{status}）"]
        return []

    def _transcription_text_body_parts(self, body: str) -> tuple[str, str]:
        lines = str(body or "").splitlines()
        title = ""
        transcript_start: int | None = None
        transcript_first_line = ""
        metadata_re = re.compile(r"^(?:会议主题|主题|标题|会议|纪要|日期|参与人|要求|整理目标|补充要求|来源|备注)\s*[:：]\s*(.*)$")
        transcript_re = re.compile(r"^(?:文字稿|转写稿|逐字稿|原文|内容)\s*[:：]\s*(.*)$")
        for index, line in enumerate(lines):
            clean_line = line.strip()
            title_match = re.match(r"^(?:会议主题|主题|标题|会议|纪要)\s*[:：]\s*(.+)$", clean_line)
            if title_match and not title:
                title = self._clean_meeting_topic_candidate(title_match.group(1))
            transcript_match = transcript_re.match(clean_line)
            if transcript_match:
                transcript_start = index
                transcript_first_line = transcript_match.group(1).strip()
                break

        if transcript_start is not None:
            transcript_lines = [transcript_first_line, *lines[transcript_start + 1 :]]
            transcript = "\n".join(line for line in transcript_lines if line is not None).strip()
            return title, transcript

        stripped_nonempty = [line for line in lines if line.strip()]
        body_has_metadata = any(metadata_re.match(line.strip()) for line in stripped_nonempty)
        if body_has_metadata:
            transcript = "\n".join(line for line in lines if not metadata_re.match(line.strip())).strip()
            return title, transcript
        return title, body.strip()

    def _transcription_text_attachment_paths(self, message: Message) -> list[str]:
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
            "local_paths",
            "file_paths",
            "conversation_context",
            "previous_attachments",
        ):
            if key in metadata:
                walk(metadata.get(key))
        for text in (message.body, message.raw_text):
            add(text)

        seen: set[str] = set()
        paths: list[str] = []
        for item in candidates:
            path = Path(item)
            if not path.is_absolute() or not path.is_file():
                continue
            if path.suffix.lower() not in TRANSCRIPTION_TEXT_EXTS:
                continue
            normalized = str(path)
            if normalized in seen:
                continue
            seen.add(normalized)
            paths.append(normalized)
        return paths
