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
        bitable_url = ((reminder.get("data") or {}).get("table_url") or self.reminder_service.bitable_url) if reminder.get("ok") else self.reminder_service.bitable_url
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
                record_text = self._knowledge_full_text(body, result, allow_body_fallback=False) or body
                extra_fields = self._knowledge_extra_fields(body, result, allow_body_fallback=False)
                status = "archived"
            else:
                extra["status"] = "pending_manual"
                extra["reason"] = completion_issue
                if result.get("media_dir"):
                    extra["assets_dir"] = result.get("media_dir", "")
                record_text = f"{body}\n\n处理状态：pending_manual\n原因：{completion_issue}"
                extra_fields = self._knowledge_extra_fields(body, result, allow_body_fallback=False)
                status = "pending_manual"
        else:
            record_text = body
            extra_fields = self._knowledge_extra_fields(body, {})
            status = "archived"

        analysis = result.get("analysis") if isinstance(result.get("analysis"), dict) else {}
        title = self._knowledge_title(body, analysis)
        reminder = self.reminder_service.add(
            kind="自媒体知识",
            title=title,
            text=record_text,
            due_at=None,
            remind_at=None,
            source=message.source,
            ref_id=task_id,
            local_path="",
            extra_fields=extra_fields,
        )
        bitable_url = ((reminder.get("data") or {}).get("table_url") or self.reminder_service.bitable_url) if reminder.get("ok") else self.reminder_service.bitable_url
        reply_label = "自媒体知识"
        if status == "archived":
            reply = f"{reply_label}已写入多维表格"
            content_type = extra_fields.get("内容类型")
            if content_type:
                reply += f"\n内容类型：{content_type}"
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
        return TaskResult(ok=ok, status=status if ok else "pending_manual", reply=reply, task_id=record_id, local_path="", feishu_doc="", extra=extra)

    def handle_自媒体知识(self, message: Message) -> TaskResult:
        return self._handle_selfmedia_knowledge(message)

    def handle_拆解(self, message: Message) -> TaskResult:
        command = [
            "/home/ubuntu/openclaw-agents/media/scripts/selfmedia.py",
            "run",
            "deconstruct",
            "--text",
            message.raw_text,
        ]
        try:
            proc = subprocess.run(command, text=True, capture_output=True, timeout=1860, env=self._subprocess_env_with_context(message))
        except subprocess.TimeoutExpired as exc:
            return TaskResult(ok=False, status="deconstruct_timeout", reply=f"【拆解】处理超时：{exc}", task_id="")
        except OSError as exc:
            return TaskResult(ok=False, status="deconstruct_failed", reply=f"【拆解】无法调用 media 工作流：{exc}", task_id="")
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
            proc = subprocess.run(command, text=True, capture_output=True, timeout=1860, env=env)
        except subprocess.TimeoutExpired as exc:
            return TaskResult(ok=False, status="creation_timeout", reply=f"【创作】处理超时：{exc}", task_id="")
        except OSError as exc:
            return TaskResult(ok=False, status="creation_failed", reply=f"【创作】无法调用 media 工作流：{exc}", task_id="")
        parsed = self._parse_openclaw_json(proc.stdout)
        reply = str(parsed.get("reply") or "").strip()
        if proc.returncode != 0:
            error_text = proc.stderr.strip() or proc.stdout.strip() or f"creation exited with {proc.returncode}"
            return TaskResult(ok=False, status="creation_failed", reply=error_text[-2000:], task_id="")
        content_os_output = self._maybe_write_content_os_creation_output(message, parsed, reply)
        if content_os_output.get("reply"):
            reply = f"{reply}\n{content_os_output['reply']}" if reply else content_os_output["reply"]
        return TaskResult(
            ok=bool(parsed.get("ok", True)),
            status="created" if parsed.get("doc_link") else str(parsed.get("mode") or "creation_done"),
            reply=reply or "【创作】处理完成",
            task_id=str(parsed.get("creation_record_id") or ""),
            feishu_doc=str(parsed.get("doc_link") or ""),
            extra={**parsed, "content_os_output": content_os_output},
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
            proc = subprocess.run(command, text=True, capture_output=True, timeout=1260, env=self._subprocess_env_with_context(message))
        except subprocess.TimeoutExpired as exc:
            return TaskResult(ok=False, status="creation_consultation_timeout", reply=f"【创作咨询】处理超时：{exc}", task_id="")
        except OSError as exc:
            return TaskResult(ok=False, status="creation_consultation_failed", reply=f"【创作咨询】无法调用 media 工作流：{exc}", task_id="")
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
            proc = subprocess.run(command, text=True, capture_output=True, timeout=1860, env=self._subprocess_env_for_content_os_script_generation(message))
        except subprocess.TimeoutExpired as exc:
            return TaskResult(ok=False, status="creation_inspiration_timeout", reply=f"【创作-灵感】处理超时：{exc}", task_id="")
        except OSError as exc:
            return TaskResult(ok=False, status="creation_inspiration_failed", reply=f"【创作-灵感】无法调用 media 工作流：{exc}", task_id="")
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
            table_url = str(parsed.get("table_url") or UNIFIED_CREATION_TABLE_URL)
            ingested_at = result.get("created_at") or self._unified_now_iso()
            unified_index = self._sync_unified_creation_record(
                {
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
                    "文档链接JSON": {"inspiration_doc": doc_fs.get("doc", "")},
                    "主状态": "已归档",
                    "入库时间": ingested_at,
                    "创建时间": ingested_at,
                    "更新时间": ingested_at,
                    "核心数据JSON": {
                        "score": result.get("score"),
                        "score_reason": result.get("score_reason", ""),
                    },
                    "爆点分析JSON": {
                        "recreation_direction": result.get("recreation_direction", ""),
                        "content_angles": result.get("content_angles") or [],
                        "strengths": result.get("strengths") or [],
                        "risks": result.get("risks") or [],
                        "publishable_formats": result.get("publishable_formats") or [],
                    },
                    "详情JSON": {
                        "workflow": "creation_inspiration",
                        "workflow_tag": "创作-灵感",
                        "attachment_paths": result.get("attachment_paths") or [],
                        "target": "\n".join(item for item in (result.get("platform"), result.get("content_type"), result.get("theme")) if item),
                        "next_actions": result.get("next_actions") or [],
                        "result": result,
                    },
                },
                table_url=table_url,
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
            reply = f"{reply}\n创作任务总表记录：{unified_index.get('record_id')}" if reply else f"创作任务总表记录：{unified_index.get('record_id')}"
        if content_os_project.get("project_id"):
            reply_lines = [
                reply or "【创作-灵感】处理完成",
                f"Content OS 项目：{content_os_project.get('project_id')}",
                f"项目包：{content_os_project.get('project_path')}",
                f"Mac 任务：{content_os_project.get('task_path')}",
            ]
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

    def handle_material_creation(self, message: Message) -> TaskResult:
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
            proc = subprocess.run(command, text=True, capture_output=True, timeout=1860, env=self._subprocess_env_for_content_os_script_generation(message))
        except subprocess.TimeoutExpired as exc:
            return TaskResult(ok=False, status="material_creation_timeout", reply=f"【素材创作】处理超时：{exc}", task_id="")
        except OSError as exc:
            return TaskResult(ok=False, status="material_creation_failed", reply=f"【素材创作】无法调用 media 工作流：{exc}", task_id="")
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
                report_text = json.dumps(
                    {
                        "creation_request": creation_request,
                        "analysis": analysis,
                        "draft": parsed.get("draft") or {},
                        "validation": parsed.get("validation") or {},
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            doc_fs = self._sync_unified_creation_child_doc(doc_title, "素材创作", report_text)
            source_paths = evidence.get("source_paths") or request.get("attachments") or []
            if not isinstance(source_paths, list):
                source_paths = [source_paths]
            ingested_at = self._unified_now_iso()
            unified_index = self._sync_unified_creation_record(
                {
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
                    "文档链接JSON": {
                        "material_doc": doc_fs.get("doc", ""),
                        "creation_doc": parsed.get("doc_link", ""),
                    },
                    "主状态": "已完成" if parsed.get("doc_link") else "已归档",
                    "入库时间": ingested_at,
                    "创建时间": ingested_at,
                    "更新时间": ingested_at,
                    "校验结果JSON": parsed.get("validation") or {},
                    "复盘状态": "待复盘",
                    "详情JSON": {
                        "workflow": "material_creation",
                        "workflow_tag": "素材创作",
                        "source_paths": [str(item) for item in source_paths if str(item).strip()],
                        "target": "\n".join(
                            str(item)
                            for item in (
                                creation_request.get("platform") or request.get("platform", ""),
                                creation_request.get("content_type") or request.get("content_type", ""),
                                creation_request.get("topic") or request.get("topic", ""),
                            )
                            if str(item).strip()
                        ),
                        "positioning": analysis.get("positioning") or "",
                        "creation_doc_link": parsed.get("doc_link", ""),
                        "creation_record_id": parsed.get("creation_record_id", ""),
                        "local_report": parsed.get("local_report", ""),
                    },
                }
            )
        except Exception as exc:
            unified_warning = f"素材创作统一同步失败：{exc}"
        if doc_fs.get("doc"):
            reply = f"{reply}\n任务池文档：{doc_fs.get('doc')}" if reply else f"任务池文档：{doc_fs.get('doc')}"
        if unified_index.get("record_id"):
            reply = f"{reply}\n创作任务总表记录：{unified_index.get('record_id')}" if reply else f"创作任务总表记录：{unified_index.get('record_id')}"
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
