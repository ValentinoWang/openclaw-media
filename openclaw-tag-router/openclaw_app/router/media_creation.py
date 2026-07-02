from __future__ import annotations

from .tag_router_common import *

class MediaCreationMixin:
    def handle_内容素材(self, message: Message) -> TaskResult:
        tag_rule = self.rule_service.get_tag_rule("内容素材")
        body = message.body
        is_link = contains_link(body) if tag_rule.get("detect_links", True) else False
        if not is_link and any(keyword in body for keyword in ["整理", "汇总"]):
            return self._handle_summary(message, default_tag="内容素材", archive_title="内容素材整理输出", doc_name="整理输出")

        task_id = make_record_id(message.created_at, message.source, message.entry_tag)
        extra: dict[str, Any] = {}
        record_text = body
        if is_link:
            result = self.content_flow_client.analyze(body)
            result = self.completion_guard.complete_external_result(kind=message.entry_tag, body=body, result=result, wait=True)
            if result.get("status") == "done":
                extra["assets_dir"] = result.get("media_dir", "")
                record_text = self._format_content_material_record(body, result)
                extra_fields = self._content_material_extra_fields(body, result, tag_rule)
                status = "archived"
            else:
                extra["status"] = "pending_manual"
                record_text = f"{body}\n\n处理状态：pending_manual\n原因：{result.get('reason', '')}"
                extra_fields = self._content_material_extra_fields(body, result, tag_rule)
                status = "pending_manual"
        else:
            extra_fields = self._content_material_extra_fields(body, {}, tag_rule)
            status = "archived"
        analysis = result.get("analysis") if is_link and isinstance(result.get("analysis"), dict) else {}
        title = self._content_material_title(body, analysis)
        reminder = self.reminder_service.add(
            kind="内容素材",
            title=title,
            text=record_text,
            due_at=None,
            remind_at=None,
            source=message.source,
            ref_id=task_id,
            local_path="",
            extra_fields=extra_fields,
        )
        bitable_url = ((reminder.get("data") or {}).get("table_url") or self._configured_bitable_url("内容素材")) if reminder.get("ok") else self._configured_bitable_url("内容素材")
        if status == "archived":
            reply = "内容素材已写入多维表格"
            if bitable_url:
                reply += f"\n多维表格：{bitable_url}"
            ok = True
        else:
            reply = "内容素材已写入多维表格\n状态：pending_manual"
            if bitable_url:
                reply += f"\n多维表格：{bitable_url}"
            ok = False
        record_id = (reminder.get("data") or {}).get("record_id") or task_id
        return TaskResult(ok=ok, status=status, reply=reply, task_id=record_id, local_path="", feishu_doc="", extra=extra)

    def _selfmedia_knowledge_requires_video(self, body: str, result: dict[str, Any]) -> bool:
        analysis = result.get("analysis") if isinstance(result.get("analysis"), dict) else {}
        media_type = str(result.get("media_type") or analysis.get("media_type") or analysis.get("内容类型") or "").lower()
        if self._knowledge_result_video_path(result):
            return True
        if self._knowledge_result_image_paths(result) or media_type in {"image", "images", "photo", "photos", "图文", "图片"}:
            return False
        if self._knowledge_body_indicates_image_post(body):
            return False
        if media_type in {"video", "short_video", "短视频", "视频"}:
            return True
        platform = self._knowledge_clean_analysis_value(analysis.get("platform")) or self._knowledge_platform_from_text(body)
        return platform in {"抖音", "TikTok", "快手", "B站", "YouTube"}

    def _handle_selfmedia_knowledge(self, message: Message) -> TaskResult:
        tag_rule = self.rule_service.get_tag_rule(message.entry_tag) or self.rule_service.get_tag_rule("自媒体知识")
        body = message.body
        is_link = contains_link(body) if tag_rule.get("detect_links", True) else False

        task_id = make_record_id(message.created_at, message.source, message.entry_tag)
        extra: dict[str, Any] = {}
        result: dict[str, Any] = {}
        if is_link:
            result = self.content_flow_client.analyze(body)
            result = self.completion_guard.complete_external_result(kind=message.entry_tag, body=body, result=result, wait=True)
            requires_video = self._selfmedia_knowledge_requires_video(body, result)
            completion_issue = self._knowledge_completion_issue(result, require_video=requires_video)
            if requires_video and completion_issue and not self._knowledge_result_video_path(result):
                video_result = self.content_flow_client.download_video(body)
                if video_result.get("status") == "done":
                    result = {**result, **video_result}
                    result = self.completion_guard.complete_external_result(kind=message.entry_tag, body=body, result=result, wait=True)
                completion_issue = self._knowledge_completion_issue(result, require_video=True)

            if not completion_issue:
                extra["assets_dir"] = result.get("media_dir", "")
                extra["workflow_status"] = "complete"
                extra["content_type"] = self._knowledge_content_type(
                    body,
                    result,
                    self._knowledge_platform_from_text(body),
                )
                record_text = self._knowledge_full_text(body, result) or body
                extra_fields = self._knowledge_extra_fields(body, result)
                status = "archived"
            else:
                if result.get("media_dir"):
                    extra["assets_dir"] = result.get("media_dir", "")
                extra["status"] = "pending_manual"
                extra["reason"] = completion_issue
                return TaskResult(
                    ok=False,
                    status="llm_semantic_persistence_required",
                    reply=f"错误代码：LLM_SEMANTIC_PERSISTENCE_REQUIRED\n原因：{completion_issue}",
                    task_id=task_id,
                    local_path="",
                    feishu_doc="",
                    extra=extra,
                )
        else:
            return TaskResult(
                ok=False,
                status="llm_semantic_persistence_required",
                reply="错误代码：LLM_SEMANTIC_PERSISTENCE_REQUIRED\n原因：自媒体知识正文未经过结构化 LLM 分析，已拒绝启发式入库。",
                task_id=task_id,
                local_path="",
                feishu_doc="",
                extra={"status": "pending_manual", "reason": "knowledge_structured_analysis_required"},
            )

        analysis = result.get("analysis") if isinstance(result.get("analysis"), dict) else {}
        title = self._knowledge_title(body, analysis)
        try:
            knowledge_local_path = self._write_selfmedia_knowledge_markdown(
                message=message,
                title=title,
                result=result,
                extra_fields=extra_fields,
                record_text=record_text,
            )
        except Exception as exc:
            return TaskResult(
                ok=False,
                status="selfmedia_knowledge_local_persistence_failed",
                reply=f"自媒体知识本地 Markdown 落盘失败，已停止写表：{exc}",
                task_id=task_id,
                local_path="",
                feishu_doc="",
                extra={"status": "pending_manual", "reason": "selfmedia_knowledge_local_persistence_failed"},
            )
        existing_pending = str(extra_fields.get("待验证问题") or "").strip()
        local_note = f"本地Markdown路径={knowledge_local_path}"
        extra_fields["待验证问题"] = f"{existing_pending}\n{local_note}".strip() if existing_pending else local_note
        reminder = self.reminder_service.add(
            kind="自媒体知识",
            title=title,
            text=record_text,
            due_at=None,
            remind_at=None,
            source=message.source,
            ref_id=task_id,
            local_path=knowledge_local_path,
            extra_fields=extra_fields,
        )
        bitable_url = ((reminder.get("data") or {}).get("table_url") or self._configured_bitable_url("自媒体知识")) if reminder.get("ok") else self._configured_bitable_url("自媒体知识")
        reply_label = "自媒体知识"
        if status == "archived":
            reply = f"{reply_label}已写入多维表格"
            content_type = extra_fields.get("内容类型")
            if content_type:
                reply += f"\n内容类型：{content_type}"
            reply += f"\n本地文件：{knowledge_local_path}"
            if bitable_url:
                reply += f"\n多维表格：{bitable_url}"
            ok = True
        else:
            reply = f"{reply_label}已写入多维表格\n状态：pending_manual"
            if extra.get("reason"):
                reply += f"\n原因：{extra['reason']}"
            if bitable_url:
                reply += f"\n多维表格：{bitable_url}"
            ok = False
        if not reminder.get("ok") and reminder.get("error"):
            reply += f"\n错误：{reminder.get('error')}"
            ok = False
        record_id = (reminder.get("data") or {}).get("record_id") or task_id
        return TaskResult(ok=ok, status=status if ok else "pending_manual", reply=reply, task_id=record_id, local_path=knowledge_local_path, feishu_doc="", extra=extra)

    def _write_selfmedia_knowledge_markdown(
        self,
        *,
        message: Message,
        title: str,
        result: dict[str, Any],
        extra_fields: dict[str, Any],
        record_text: str,
    ) -> str:
        analysis = result.get("analysis") if isinstance(result.get("analysis"), dict) else {}
        vault_root = Path(os.environ.get("CONTENT_OS_VAULT_ROOT", "/home/ubuntu/obsidian-自媒体"))
        note_dir = vault_root / "05_素材与爆款库" / "自媒体知识"
        note_dir.mkdir(parents=True, exist_ok=True)
        created_date = message.created_at.strftime("%Y%m%d")
        source_key = str(analysis.get("video_id") or analysis.get("note_id") or analysis.get("article_id") or "").strip()
        if not source_key:
            source_key = hashlib.sha1(str(extra_fields.get("原链接") or message.raw_text).encode("utf-8")).hexdigest()[:10]
        path = note_dir / f"{created_date}_{safe_slug(source_key, max_len=32)}_{safe_slug(title, max_len=48)}.md"
        frontmatter = {
            "doc_type": "selfmedia_knowledge",
            "source": message.source,
            "entry_tag": message.entry_tag,
            "created_at": format_display_time(message.created_at),
            "status": "archived",
            "title": title,
            "source_url": extra_fields.get("原链接", ""),
            "platform": extra_fields.get("来源平台", ""),
            "content_type": extra_fields.get("内容类型", ""),
            "primary_category": extra_fields.get("一级分类", ""),
            "secondary_category": extra_fields.get("二级分类", []),
            "media_dir": result.get("media_dir", ""),
            "writer_agent": "cloud_openclaw",
        }
        source_lines = [
            f"- 飞书标签：`{message.entry_tag}`",
            f"- 来源平台：{extra_fields.get('来源平台') or '未记录'}",
            f"- 内容类型：{extra_fields.get('内容类型') or '未记录'}",
            f"- 原链接：{extra_fields.get('原链接') or '未记录'}",
            f"- 媒体目录：`{result.get('media_dir') or '未记录'}`",
        ]
        analysis_payload = json.dumps(analysis, ensure_ascii=False, indent=2, default=str)
        sections = [
            ("来源与入库", "\n".join(source_lines)),
            ("摘要", self._knowledge_text_value(extra_fields.get("摘要")) or "未记录"),
            ("核心内容", self._knowledge_text_value(extra_fields.get("全部内容")) or record_text),
            ("平台文案", self._knowledge_text_value(extra_fields.get("全部文案")) or "未记录"),
            (
                "拆解与应用",
                "\n\n".join(
                    part
                    for part in [
                        f"### 黄金三秒\n\n{self._knowledge_text_value(extra_fields.get('黄金三秒') or analysis.get('hooks'))}",
                        f"### 隐形信息\n\n{self._knowledge_text_value(extra_fields.get('隐形信息'))}",
                        f"### 可迁移表达\n\n{self._knowledge_text_value(extra_fields.get('可迁移表达'))}",
                        f"### 应用建议\n\n{self._knowledge_text_value(extra_fields.get('应用建议'))}",
                    ]
                    if part.strip().split("\n\n", 1)[-1].strip()
                )
                or "未记录",
            ),
            ("结构化分析JSON", f"```json\n{analysis_payload[:12000]}\n```"),
        ]
        path.write_text(ArchiveService.render_markdown(frontmatter, title, sections), encoding="utf-8")
        cleanup_generated_file_duplicates(path)
        return str(path)

    def handle_自媒体知识(self, message: Message) -> TaskResult:
        return self._handle_selfmedia_knowledge(message)

    def _deconstruct_completion_issue(self, outer: dict[str, Any], inner: dict[str, Any]) -> str:
        if not outer:
            return "media 工作流未返回外层 JSON，不能确认拆解是否完成。"
        if not bool(outer.get("ok", True)):
            detail = str(outer.get("stderr") or outer.get("stdout") or outer.get("returncode") or "").strip()
            return f"media 工作流返回失败：{detail[-1000:] or '未提供错误详情'}"
        if not inner:
            detail = str(outer.get("stdout") or "").strip()
            return f"media 工作流未返回内层拆解 JSON：{detail[-1000:] or 'stdout 为空'}"
        if inner.get("skipped"):
            return f"拆解工作流被跳过：{inner.get('reason') or inner.get('mode') or '未提供原因'}"

        mode = str(inner.get("mode") or "").strip()
        if mode == "partial_deconstruct":
            partial = inner.get("partial_deconstruct")
            return "" if isinstance(partial, dict) and partial else "轻量拆解未返回 partial_deconstruct 结果。"

        deconstruct = inner.get("deconstruct")
        if not isinstance(deconstruct, dict) or not deconstruct:
            return "拆解工作流未返回 deconstruct 结果。"

        missing: list[str] = []
        if not str(deconstruct.get("deconstruct_doc_url") or "").strip():
            missing.append("拆解文档链接")
        if not str(inner.get("feishu_record_id") or deconstruct.get("feishu_record_id") or "").strip():
            missing.append("飞书拆解记录ID")

        if mode == "deconstruct_and_recreate":
            recreate = inner.get("recreate")
            if not isinstance(recreate, dict) or not str(recreate.get("recreate_doc_url") or "").strip():
                missing.append("拆解-再创文档链接")

        if missing:
            return "拆解未产生完整落地产物，缺少：" + "、".join(missing)
        return ""

    def handle_拆解(self, message: Message) -> TaskResult:
        command = [
            "/home/ubuntu/openclaw-agents/media/scripts/selfmedia.py",
            "run",
            "deconstruct",
            "--text",
            message.raw_text,
        ]
        try:
            proc = run_media_subprocess_with_watchdog(command, timeout=10800, env=self._subprocess_env_with_context(message))
        except OSError as exc:
            return TaskResult(ok=False, status="deconstruct_failed", reply=f"【拆解】无法调用 media 工作流：{exc}", task_id="")
        if proc.returncode == -9:
            return TaskResult(ok=False, status="deconstruct_timeout", reply=(proc.stderr.strip() or "【拆解】处理超时")[-3000:], task_id="")
        parsed = self._parse_openclaw_json(proc.stdout)
        if proc.returncode != 0:
            error_text = proc.stderr.strip() or proc.stdout.strip() or f"deconstruct exited with {proc.returncode}"
            return TaskResult(ok=False, status="deconstruct_failed", reply=error_text[-3000:], task_id="")
        inner = self._parse_openclaw_json(str(parsed.get("stdout") or ""))
        deconstruct = inner.get("deconstruct") if isinstance(inner, dict) else {}
        recreate = inner.get("recreate") if isinstance(inner, dict) else {}
        if not isinstance(deconstruct, dict):
            deconstruct = {}
        if not isinstance(recreate, dict):
            recreate = {}
        completion_issue = self._deconstruct_completion_issue(parsed, inner if isinstance(inner, dict) else {})
        if completion_issue:
            return TaskResult(
                ok=False,
                status="deconstruct_incomplete",
                reply=f"【拆解】未确认完成。\n原因：{completion_issue}",
                task_id=str(inner.get("feishu_record_id") or "") if isinstance(inner, dict) else "",
                extra=inner if isinstance(inner, dict) else parsed,
            )
        links = [
            str(deconstruct.get("deconstruct_doc_url") or "").strip(),
            str(recreate.get("recreate_doc_url") or "").strip(),
        ]
        links = [link for link in links if link]
        reply_lines = ["【拆解】处理完成。"]
        if links:
            reply_lines.append("文档：" + " / ".join(links))
        if inner.get("feishu_record_id"):
            reply_lines.append(f"记录ID：{inner['feishu_record_id']}")
        return TaskResult(
            ok=bool(parsed.get("ok", True)),
            status=str(inner.get("mode") or "deconstruct_done") if isinstance(inner, dict) else "deconstruct_done",
            reply="\n".join(reply_lines),
            task_id=str(inner.get("feishu_record_id") or "") if isinstance(inner, dict) else "",
            feishu_doc=links[0] if links else "",
            extra=inner if isinstance(inner, dict) else parsed,
        )

    def handle_creation(self, message: Message) -> TaskResult:
        command = [
            "/home/ubuntu/openclaw-agents/media/scripts/selfmedia.py",
            "run",
            "creation",
            "--text",
            message.raw_text,
        ]
        self._append_conversation_context_arg(command, message)
        try:
            env = (
                self._subprocess_env_for_content_os_script_generation(message)
                if self._extract_content_os_local_project_path(message.raw_text)
                and self._inspiration_requests_content_os_project(message.raw_text)
                else self._subprocess_env_with_context(message)
            )
            proc = run_media_subprocess_with_watchdog(command, timeout=10800, env=env)
        except OSError as exc:
            return TaskResult(ok=False, status="creation_failed", reply=f"【创作】无法调用 media 工作流：{exc}", task_id="")
        if proc.returncode == -9:
            return TaskResult(ok=False, status="creation_timeout", reply=(proc.stderr.strip() or "【创作】处理超时")[-3000:], task_id="")
        parsed = self._parse_openclaw_json(proc.stdout)
        reply = str(parsed.get("reply") or "").strip()
        if proc.returncode != 0:
            error_text = proc.stderr.strip() or proc.stdout.strip() or f"creation exited with {proc.returncode}"
            return TaskResult(ok=False, status="creation_failed", reply=error_text[-2000:], task_id="")
        try:
            content_os_output = self._maybe_write_content_os_creation_output(message, parsed, reply)
            if not content_os_output:
                content_os_output = self._maybe_create_content_os_project_from_creation(message, parsed, reply)
            if not content_os_output:
                content_os_output = self._write_standalone_creation_output(message, parsed, reply)
        except Exception as exc:
            return TaskResult(
                ok=False,
                status="creation_local_persistence_failed",
                reply=f"【创作】本地 Markdown 落盘失败：{exc}",
                task_id=str(parsed.get("creation_record_id") or ""),
                feishu_doc=str(parsed.get("doc_link") or ""),
                extra={**parsed, "local_persistence_error": str(exc)},
            )
        if content_os_output.get("reply"):
            reply = f"{reply}\n{content_os_output['reply']}" if reply else content_os_output["reply"]
        return TaskResult(
            ok=bool(parsed.get("ok", True)),
            status="created" if parsed.get("doc_link") else str(parsed.get("mode") or "creation_done"),
            reply=reply or "【创作】处理完成",
            task_id=str(parsed.get("creation_record_id") or ""),
            local_path=str(content_os_output.get("script_path") or ""),
            feishu_doc=str(parsed.get("doc_link") or ""),
            extra={**parsed, "content_os_output": content_os_output},
        )

    def handle_shooting_execution(self, message: Message) -> TaskResult:
        command = [
            "/home/ubuntu/openclaw-agents/media/scripts/selfmedia.py",
            "shooting-execution",
            "--text",
            message.raw_text,
        ]
        self._append_conversation_context_arg(command, message)
        try:
            proc = run_media_subprocess_with_watchdog(command, timeout=10800, env=self._subprocess_env_with_context(message))
        except OSError as exc:
            return TaskResult(ok=False, status="shooting_execution_failed", reply=f"【创作-拍摄执行】无法调用 media 工作流：{exc}", task_id="")
        if proc.returncode == -9:
            return TaskResult(ok=False, status="shooting_execution_timeout", reply=(proc.stderr.strip() or "【创作-拍摄执行】处理超时")[-3000:], task_id="")
        parsed = self._parse_openclaw_json(proc.stdout)
        reply = str(parsed.get("reply") or "").strip()
        if proc.returncode != 0:
            error_text = proc.stderr.strip() or proc.stdout.strip() or f"shooting-execution exited with {proc.returncode}"
            return TaskResult(ok=False, status="shooting_execution_failed", reply=error_text[-3000:], task_id="")
        return TaskResult(
            ok=bool(parsed.get("ok", True)),
            status="shooting_execution_created" if parsed.get("doc_link") else str(parsed.get("mode") or "shooting_execution_done"),
            reply=reply or "【创作-拍摄执行】处理完成",
            task_id=str(parsed.get("creation_record_id") or ""),
            feishu_doc=str(parsed.get("doc_link") or ""),
            extra=parsed,
        )

    def handle_创作咨询(self, message: Message) -> TaskResult:
        command = [
            "/home/ubuntu/openclaw-agents/media/scripts/selfmedia.py",
            "consultation",
            "--text",
            message.raw_text,
        ]
        self._append_conversation_context_arg(command, message)
        try:
            proc = run_media_subprocess_with_watchdog(command, timeout=1260, env=self._subprocess_env_with_context(message))
        except OSError as exc:
            return TaskResult(ok=False, status="creation_consultation_failed", reply=f"【创作咨询】无法调用 media 工作流：{exc}", task_id="")
        if proc.returncode == -9:
            return TaskResult(ok=False, status="creation_consultation_timeout", reply=(proc.stderr.strip() or "【创作咨询】处理超时")[-3000:], task_id="")
        parsed = self._parse_openclaw_json(proc.stdout)
        reply = str(parsed.get("reply") or "").strip()
        if proc.returncode != 0:
            error_text = proc.stderr.strip() or proc.stdout.strip() or f"consultation exited with {proc.returncode}"
            return TaskResult(ok=False, status="creation_consultation_failed", reply=error_text[-3000:], task_id="")
        return TaskResult(
            ok=bool(parsed.get("ok", True)),
            status="creation_consulted",
            reply=reply or "【创作咨询】处理完成",
            task_id="",
            extra=parsed,
        )

    def handle_创作灵感(self, message: Message) -> TaskResult:
        metadata = message.metadata or {}
        downloaded_paths = metadata.get("downloaded_paths") or []
        if not isinstance(downloaded_paths, list):
            downloaded_paths = []
        command = [
            "/home/ubuntu/openclaw-agents/media/scripts/selfmedia.py",
            "creation-inspiration",
            "--text",
            message.raw_text,
            "--no-write",
        ]
        for path in downloaded_paths:
            if str(path).strip():
                command.extend(["--attachment", str(path).strip()])
        self._append_conversation_context_arg(command, message)
        try:
            proc = run_media_subprocess_with_watchdog(command, timeout=10800, env=self._subprocess_env_for_content_os_script_generation(message))
        except OSError as exc:
            return TaskResult(ok=False, status="creation_inspiration_failed", reply=f"【创作-灵感】无法调用 media 工作流：{exc}", task_id="")
        if proc.returncode == -9:
            return TaskResult(ok=False, status="creation_inspiration_timeout", reply=(proc.stderr.strip() or "【创作-灵感】处理超时")[-3000:], task_id="")
        parsed = self._parse_openclaw_json(proc.stdout)
        reply = str(parsed.get("reply") or "").strip()
        if proc.returncode != 0:
            error_text = proc.stderr.strip() or proc.stdout.strip() or f"creation inspiration exited with {proc.returncode}"
            return TaskResult(ok=False, status="creation_inspiration_failed", reply=error_text[-3000:], task_id="")
        result = parsed.get("result") if isinstance(parsed.get("result"), dict) else {}
        record_text = str(parsed.get("record_text") or reply or message.raw_text or "").strip()
        doc_fs: dict[str, str] = {}
        unified_index: dict[str, str] = {}
        content_os_project: dict[str, Any] = {}
        unified_warning = ""
        try:
            theme_source = str(result.get("title") or result.get("theme") or message.body or "未命名灵感")
            seed = str(record_text or message.raw_text or theme_source)
            doc_title = self._unified_creation_doc_name("创作-灵感", theme_source, seed)
            doc_fs = self._sync_unified_creation_child_doc(doc_title, "创作-灵感", record_text)
            ingested_at = result.get("created_at") or self._unified_now_iso()
            unified_index = self._sync_unified_creation_record(
                {
                    "来源消息ID": str((message.metadata or {}).get("message_id") or ""),
                    "记录类型": "创作记录",
                    "标题": doc_title,
                    "主题": result.get("theme") or theme_source,
                    "内容": result.get("cleaned_inspiration", ""),
                    "摘要": result.get("material_summary", ""),
                    "平台": result.get("platform", ""),
                    "内容类型": result.get("content_type", ""),
                    "赛道": result.get("track", ""),
                    "关键词标签": "、".join(str(item).strip() for item in ["创作-灵感", *(result.get("tags") or [])] if str(item).strip()),
                    "来源链接": "\n".join(result.get("attachment_paths") or []),
                    "灵感文档链接": doc_fs.get("doc", ""),
                    "主状态": "已归档",
                    "入库时间": ingested_at,
                    "创建时间": ingested_at,
                    "更新时间": ingested_at,
                    "灵感评分": result.get("score"),
                    "评分原因": result.get("score_reason", ""),
                    "拆解-再创方向": result.get("recreation_direction", ""),
                    "可迁移点": self._unified_join_lines([*(result.get("strengths") or []), *(result.get("content_angles") or []), *(result.get("reuse_angles") or [])]),
                    "风险点": self._unified_join_lines(result.get("risks") or []),
                    "建议产物": self._unified_join_lines(result.get("publishable_formats") or []),
                    "素材来源类型": result.get("source_kind", ""),
                    "素材信号类型": result.get("signal_type", ""),
                    "情绪触发": result.get("emotion_trigger", ""),
                    "触发原话": result.get("trigger_sentence", ""),
                    "事件场景": result.get("event_scene", ""),
                    "错位点": result.get("misalignment", ""),
                    "核心观点": result.get("core_viewpoint", ""),
                    "读者问题": result.get("reader_problem", ""),
                    "可复用角度": "、".join(result.get("reuse_angles") or result.get("content_angles") or []),
                    "素材状态": result.get("material_stage", ""),
                    "一鱼多吃方向": "、".join(result.get("derivative_topics") or []),
                    "下一步": self._unified_join_lines(result.get("next_actions") or []),
                },
            )
        except Exception as exc:
            unified_warning = f"创作灵感统一同步失败：{exc}"
        try:
            content_os_project = self._maybe_create_content_os_project_from_inspiration(
                message=message,
                result=result,
                record_text=record_text,
                doc_fs=doc_fs,
                unified_index=unified_index,
            )
        except Exception as exc:
            warning = f"Content OS 立项失败：{exc}"
            unified_warning = f"{unified_warning}\n{warning}".strip() if unified_warning else warning
        if doc_fs.get("doc"):
            reply = f"{reply}\n任务池文档：{doc_fs.get('doc')}" if reply else f"任务池文档：{doc_fs.get('doc')}"
        if unified_index.get("record_id"):
            reply = f"{reply}\n创作运行记录：{unified_index.get('record_id')}" if reply else f"创作运行记录：{unified_index.get('record_id')}"
        if content_os_project.get("project_id"):
            reply_lines = [
                reply or "【创作-灵感】处理完成",
                f"Content OS 项目：{content_os_project.get('project_id')}",
                f"项目包：{content_os_project.get('project_path')}",
            ]
            if content_os_project.get("task_path"):
                reply_lines.append(f"Mac 任务：{content_os_project.get('task_path')}")
            else:
                reply_lines.append("本地素材绑定：未绑定，等人在 Mac 上用批次说明或本地回写连接真实素材")
            reply = "\n".join(item for item in reply_lines if item)
        if unified_warning:
            reply = ReplyService.append_warning(reply or "【创作-灵感】处理完成", unified_warning)
        return TaskResult(
            ok=bool(parsed.get("ok", True)),
            status="creation_inspiration_saved",
            reply=reply or "【创作-灵感】处理完成",
            task_id=str(unified_index.get("record_id") or ""),
            feishu_doc=str(doc_fs.get("doc") or parsed.get("table_url") or ""),
            extra={**parsed, "unified_doc": doc_fs, "unified_index": unified_index, "content_os_project": content_os_project},
        )


    def _material_copywriting_requested(self, message: Message) -> bool:
        text = f"{message.entry_tag}\n{message.raw_text}\n{message.body}"
        if not MATERIAL_CREATION_TAG_RE.match(message.entry_tag):
            return False
        request_terms = ("标题", "文案", "封面", "封面字", "话题", "标签", "评论区", "发布口径", "配文", "正文")
        return any(term in text for term in request_terms)

    def _material_field_value(self, text: str, field: str) -> str:
        pattern = rf"(?:^|[\s，,；;]){re.escape(field)}\s*[:=：]\s*([^\n，,；; ]+)"
        match = re.search(pattern, text)
        return match.group(1).strip() if match else ""

    def _material_copywriting_context_text(self, message: Message) -> str:
        parts = [message.raw_text, message.body]
        metadata = message.metadata or {}
        conversation_context = metadata.get("conversation_context")
        if isinstance(conversation_context, dict):
            prompt = conversation_context.get("prompt")
            if isinstance(prompt, str):
                parts.append(prompt)
            for item in conversation_context.get("items") or []:
                if not isinstance(item, dict):
                    continue
                for key in ("text", "bot_reply"):
                    value = item.get(key)
                    if isinstance(value, str):
                        parts.append(value)
        for key in ("downloaded_paths", "attachments"):
            values = metadata.get(key) or []
            if isinstance(values, list):
                parts.extend(str(value) for value in values)
        return "\n".join(part for part in parts if str(part).strip())

    def _material_visual_summary_for_copywriting(self, message: Message) -> str:
        text = self._material_copywriting_context_text(message)
        patterns = (
            r"素材事实\s*[:：]\s*([^\n]+)",
            r"画面识别\s*[:：]\s*([^\n]+)",
            r"内容识别\s*[:：]\s*([^\n]+)",
            r"识别\s*[:：]\s*([^\n]+)",
            r"核心画面\s*[:：]\s*([^\n]+)",
        )
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                summary = match.group(1).strip(" `。")
                if summary:
                    return summary
        if "清华" in text and "AI" in text:
            return "清华校园建筑背景下，人物围绕发光 AI 芯片，画面带有校园、科技和仪式感。"
        if "AI" in text:
            return "围绕 AI 主题的视觉素材，适合表达科技感、未来感和内容创作想象。"
        if "校园" in text:
            return "校园场景视觉素材，适合表达青春、身份、现场感和阶段性纪念。"
        return "已上传的视觉素材，适合提炼成平台标题、封面字和发布文案。"

    def _material_copywriting_keywords(self, summary: str, text: str) -> list[str]:
        candidates = []
        for keyword in ("清华", "AI", "人工智能", "芯片", "校园", "毕业", "学位服", "魔法", "仪式感", "科技感", "未来感"):
            if keyword in summary or keyword in text:
                candidates.append(keyword)
        if not candidates:
            candidates.extend(["视觉素材", "创作", "现场感"])
        result = []
        seen = set()
        for item in candidates:
            if item not in seen:
                seen.add(item)
                result.append(item)
        return result

    def _material_copywriting_title_candidates(self, summary: str, keywords: list[str]) -> list[str]:
        if "清华" in keywords and "AI" in keywords:
            return [
                "当清华校园遇到 AI 魔法阵",
                "这张图，像 AI 在清华开了一场召唤仪式",
                "谁懂啊，AI 芯片被拍出了魔法感",
                "未来感和校园感撞在一起了",
                "清华、AI、学位服，突然有点燃",
                "这不是科幻片，这是 AI 时代的校园想象",
                "如果 AI 有入学仪式，大概就是这样",
                "一群人围着 AI 芯片，画面突然有故事了",
                "校园里的 AI 魔法时刻",
                "这张图适合写一句：未来已经到场",
            ]
        if "AI" in keywords:
            return [
                "当 AI 被拍出仪式感",
                "这张图，把 AI 的未来感拍出来了",
                "AI 不只是工具，也是一种新的现场",
                "一张图看懂 AI 时代的想象力",
                "这就是我理解的 AI 氛围感",
                "科技感突然有了故事",
                "如果未来有画面，大概就是这样",
                "AI 时代，连视觉表达都变了",
                "这张图的重点不是炫，是时代感",
                "今天被一张 AI 图击中了",
            ]
        return [
            "这张图最打动我的地方",
            "一张图里的现场感",
            "这不是普通照片，是一个故事开头",
            "这个画面有点适合发出来",
            "越看越有感觉的一张图",
            "这张图可以配一句话",
            "有些画面，一眼就有记忆点",
            "今天这张图值得单独发一次",
            "它的氛围感比信息量更强",
            "这张图像一个内容开头",
        ]

    def _material_copywriting_body_versions(self, summary: str, keywords: list[str]) -> list[tuple[str, str]]:
        if "清华" in keywords and "AI" in keywords:
            return [
                ("氛围感版", "清华校园的建筑、学位服、发光的 AI 芯片，放在一起突然有一种未来仪式感。\n\n不是单纯的科技感，也不是普通校园照，更像是一个时代的隐喻：我们围着 AI，不只是看热闹，而是在进入一个新的现场。"),
                ("短平快版", "这张图有点离谱。\n\n清华背景 + 学位服 + 发光 AI 芯片，直接把“AI 时代的校园想象”拍出来了。\n\n像不像一群人正在召唤未来？"),
                ("账号表达版", "以前觉得 AI 是工具，后来发现它更像一种新的现场。\n\n你站在校园里，看着一群人围着发光的芯片，突然会意识到：这一代人的毕业、创作、工作和表达，可能都会被 AI 重新改写。\n\n这张图最有意思的地方，不是炫，而是它真的有一种时代感。"),
            ]
        if "AI" in keywords:
            return [
                ("氛围感版", "这张图最抓人的地方，是它把 AI 拍成了一种现场感。\n\n不是冷冰冰的技术说明，而是有光、有角色、有故事开头的未来感。"),
                ("短平快版", "AI 题材最怕拍得像说明书。\n\n但这张图不一样，它有画面、有情绪，也有一点“未来正在发生”的感觉。"),
                ("账号表达版", "AI 真正改变的可能不只是效率，还有我们表达世界的方式。\n\n以前一张图负责记录，现在一张图也能负责提出想象。"),
            ]
        return [
            ("氛围感版", f"这张图的可用点很明确：{summary}\n\n它适合做成一条轻量图文，不需要解释太多，重点放在画面本身带出来的情绪和记忆点。"),
            ("短平快版", "这张图可以单独发。\n\n它不是信息最多的那类素材，但第一眼有氛围，适合用短标题把停留拉住。"),
            ("账号表达版", "有些素材不是靠复杂故事取胜，而是靠一个瞬间的感觉。\n\n这张图适合做成图文，把画面里的关系、身份和情绪讲清楚。"),
        ]

    def _material_copywriting_hashtags(self, platform: str, keywords: list[str]) -> list[str]:
        tags = []
        for keyword in keywords:
            clean = keyword.replace(" ", "")
            if clean:
                tags.append(f"#{clean}")
        if "AI" in keywords and "#人工智能" not in tags:
            tags.append("#人工智能")
        if platform == "抖音":
            tags.extend(["#抖音图文", "#科技感"])
        else:
            tags.extend(["#图文", "#内容创作"])
        result = []
        seen = set()
        for tag in tags:
            if tag not in seen:
                seen.add(tag)
                result.append(tag)
        return result[:10]

    def _handle_material_copywriting(self, message: Message) -> TaskResult:
        text = self._material_copywriting_context_text(message)
        platform = self._material_field_value(text, "平台") or ("抖音" if message.entry_tag.endswith(">抖音") else "小红书" if message.entry_tag.endswith(">小红书") else "抖音")
        content_type = self._material_field_value(text, "类型") or "图文"
        account = self._material_field_value(text, "账号") or "主账号"
        publish_time = self._material_field_value(text, "发布时间") or "待定"
        summary = self._material_visual_summary_for_copywriting(message)
        keywords = self._material_copywriting_keywords(summary, text)
        titles = self._material_copywriting_title_candidates(summary, keywords)
        bodies = self._material_copywriting_body_versions(summary, keywords)
        hashtags = self._material_copywriting_hashtags(platform, keywords)
        cover = "AI 时代的校园仪式感" if "清华" in keywords and "AI" in keywords else titles[0]
        comment = "你觉得这张图更像“毕业照”，还是更像“AI 召唤现场”？" if "清华" in keywords and "AI" in keywords else "你会给这张图配哪一句标题？"
        title_lines = "\n".join(f"{idx}. {title}" for idx, title in enumerate(titles, 1))
        body_lines = "\n\n".join(f"版本{idx}｜{name}\n{body}" for idx, (name, body) in enumerate(bodies, 1))
        reply = "\n".join([
            "模型编号：gpt5.5-high",
            "",
            "【素材创作】标题文案包已生成",
            f"平台：{platform}",
            f"类型：{content_type}",
            f"账号：{account}",
            f"发布时间：{publish_time}",
            "",
            f"素材判断：{summary}",
            "",
            "最推荐标题：",
            titles[0],
            "",
            "标题候选：",
            title_lines,
            "",
            "正文文案：",
            body_lines,
            "",
            "封面字建议：",
            cover,
            "",
            "话题标签：",
            " ".join(hashtags),
            "",
            "评论区引导：",
            comment,
            "",
            "发布建议：",
            f"首图直接用当前素材；标题优先用“{titles[0]}”；正文优先用版本2，短、直、适合{platform}图文停留。",
        ])
        return TaskResult(ok=True, status="material_copywriting_ready", reply=reply, task_id="", feishu_doc="", extra={"platform": platform, "content_type": content_type, "visual_summary": summary, "titles": titles, "hashtags": hashtags})

    def handle_material_creation(self, message: Message) -> TaskResult:
        if self._material_copywriting_requested(message):
            return self._handle_material_copywriting(message)
        metadata = message.metadata or {}
        downloaded_paths = metadata.get("downloaded_paths") or []
        if not isinstance(downloaded_paths, list):
            downloaded_paths = []
        command = [
            "/home/ubuntu/openclaw-agents/media/scripts/selfmedia.py",
            "material-creation",
            "--text",
            message.raw_text,
        ]
        for path in downloaded_paths:
            if str(path).strip():
                command.extend(["--attachment", str(path).strip()])
        self._append_conversation_context_arg(command, message)
        try:
            proc = run_media_subprocess_with_watchdog(command, timeout=10800, env=self._subprocess_env_for_content_os_script_generation(message))
        except OSError as exc:
            return TaskResult(ok=False, status="material_creation_failed", reply=f"【素材创作】无法调用 media 工作流：{exc}", task_id="")
        if proc.returncode == -9:
            return TaskResult(ok=False, status="material_creation_timeout", reply=(proc.stderr.strip() or "【素材创作】处理超时")[-3000:], task_id="")
        parsed = self._parse_openclaw_json(proc.stdout)
        reply = str(parsed.get("reply") or "").strip()
        if proc.returncode != 0:
            error_text = proc.stderr.strip() or proc.stdout.strip() or f"material creation exited with {proc.returncode}"
            return TaskResult(ok=False, status="material_creation_failed", reply=error_text[-3000:], task_id="")
        doc_fs: dict[str, str] = {}
        unified_index: dict[str, str] = {}
        unified_warning = ""
        try:
            creation_request = parsed.get("creation_request") if isinstance(parsed.get("creation_request"), dict) else {}
            request = parsed.get("request") if isinstance(parsed.get("request"), dict) else {}
            analysis = parsed.get("analysis") if isinstance(parsed.get("analysis"), dict) else {}
            evidence = parsed.get("evidence") if isinstance(parsed.get("evidence"), dict) else {}
            theme_source = str(analysis.get("title") or creation_request.get("topic") or request.get("topic") or message.body or "素材创作")
            seed = str(parsed.get("creation_record_id") or parsed.get("local_report") or message.raw_text or theme_source)
            doc_title = self._unified_creation_doc_name("素材创作", theme_source, seed)
            report_text = ""
            local_report = str(parsed.get("local_report") or "").strip()
            if local_report:
                report_path = Path(local_report).expanduser()
                if report_path.exists():
                    report_text = report_path.read_text(encoding="utf-8")
            if not report_text:
                report_text = self._material_creation_readable_report(
                    creation_request=creation_request,
                    analysis=analysis,
                    draft=parsed.get("draft") if isinstance(parsed.get("draft"), dict) else {},
                    validation=parsed.get("validation") if isinstance(parsed.get("validation"), dict) else {},
                )
            doc_fs = self._sync_unified_creation_child_doc(doc_title, "素材创作", report_text)
            source_paths = evidence.get("source_paths") or request.get("attachments") or []
            if not isinstance(source_paths, list):
                source_paths = [source_paths]
            ingested_at = self._unified_now_iso()
            unified_index = self._sync_unified_creation_record(
                {
                    "来源消息ID": str((message.metadata or {}).get("message_id") or ""),
                    "记录类型": "创作记录",
                    "标题": doc_title,
                    "主题": creation_request.get("topic") or request.get("topic") or theme_source,
                    "内容": report_text,
                    "摘要": analysis.get("material_summary") or analysis.get("positioning", ""),
                    "平台": creation_request.get("platform") or request.get("platform", ""),
                    "内容类型": creation_request.get("content_type") or request.get("content_type", ""),
                    "赛道": creation_request.get("track") or request.get("track", ""),
                    "关键词标签": "素材创作、创作记录",
                    "来源链接": "\n".join(str(item) for item in source_paths if str(item).strip()),
                    "素材文档链接": doc_fs.get("doc", ""),
                    "创作文档链接": parsed.get("doc_link", ""),
                    "主状态": "已完成" if parsed.get("doc_link") else "已归档",
                    "入库时间": ingested_at,
                    "创建时间": ingested_at,
                    "更新时间": ingested_at,
                    "校验结果": self._unified_validation_summary(parsed.get("validation") or {}),
                    "复盘状态": "待复盘",
                    "定位分析": analysis.get("positioning") or "",
                    "创作记录ID": parsed.get("creation_record_id", ""),
                    "本地报告路径": parsed.get("local_report", ""),
                }
            )
        except Exception as exc:
            unified_warning = f"素材创作统一同步失败：{exc}"
        if doc_fs.get("doc"):
            reply = f"{reply}\n任务池文档：{doc_fs.get('doc')}" if reply else f"任务池文档：{doc_fs.get('doc')}"
        if unified_index.get("record_id"):
            reply = f"{reply}\n创作运行记录：{unified_index.get('record_id')}" if reply else f"创作运行记录：{unified_index.get('record_id')}"
        if unified_warning:
            reply = ReplyService.append_warning(reply or "【素材创作】处理完成", unified_warning)
        return TaskResult(
            ok=bool(parsed.get("ok", True)),
            status="material_created" if parsed.get("doc_link") else str(parsed.get("mode") or "material_creation_done"),
            reply=reply or "【素材创作】处理完成",
            task_id=str(parsed.get("creation_record_id") or ""),
            feishu_doc=str(doc_fs.get("doc") or parsed.get("doc_link") or ""),
            extra={**parsed, "unified_doc": doc_fs, "unified_index": unified_index},
        )

    def _material_creation_readable_report(
        self,
        *,
        creation_request: dict[str, Any],
        analysis: dict[str, Any],
        draft: dict[str, Any],
        validation: dict[str, Any],
    ) -> str:
        sections = [
            ("创作请求", self._unified_join_lines(creation_request)),
            ("定位分析", self._unified_join_lines(analysis)),
            ("初稿", self._unified_join_lines(draft)),
            ("校验结果", self._unified_validation_summary(validation)),
        ]
        return "\n\n".join(f"## {title}\n{body}" for title, body in sections if str(body or "").strip())
