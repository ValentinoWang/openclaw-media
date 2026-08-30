from __future__ import annotations

from .content_os_utils import content_os_vault_root
from .tag_router_common import *
from media_vault import MediaVaultError, require_tenant_id

class MediaCreationMixin:
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
                error_code, public_reason, status_code = self._selfmedia_knowledge_failure(result, completion_issue)
                detail, action = self._selfmedia_knowledge_failure_guidance(result, error_code)
                extra["status"] = "pending_manual"
                extra["reason"] = public_reason
                extra["error_code"] = error_code
                extra["stage"] = str(result.get("stage") or "content_flow")
                extra["detail"] = detail
                extra["action"] = action
                if isinstance(result.get("diagnostics"), dict):
                    extra["diagnostics"] = result["diagnostics"]
                return TaskResult(
                    ok=False,
                    status=status_code,
                    reply=f"错误代码：{error_code}\n原因：{public_reason}\n详情：{detail}\n建议：{action}",
                    task_id=task_id,
                    local_path="",
                    feishu_doc="",
                    extra=extra,
                )
        else:
            return TaskResult(
                ok=False,
                status="llm_semantic_persistence_required",
                reply=(
                    "错误代码：LLM_SEMANTIC_PERSISTENCE_REQUIRED\n"
                    "原因：自媒体知识正文未经过结构化 LLM 分析，已拒绝启发式入库。\n"
                    "详情：消息未包含可进入来源提取或 LLM 分析的链接。\n"
                    "建议：请提供公开链接，或提供完整正文后使用适合的知识整理入口。"
                ),
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
        reply_label = "自媒体知识"
        if status == "archived":
            reply = f"{reply_label}已归档"
            content_type = extra_fields.get("内容类型")
            if content_type:
                reply += f"\n内容类型：{content_type}"
            ok = True
        else:
            reply = f"{reply_label}待人工处理\n状态：pending_manual"
            if extra.get("reason"):
                reply += f"\n原因：{extra['reason']}"
            ok = False
        reply += f"\n本地文件：{knowledge_local_path}"
        if not reminder.get("ok") and reminder.get("error"):
            reply += "\n写入未完成，请联系平台管理员处理。"
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
        vault_root = content_os_vault_root()
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
        # Raw source evidence is retained in the media directory; the readable card exposes only LLM analysis and metadata.
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
        ]
        path.write_text(ArchiveService.render_markdown(frontmatter, title, sections), encoding="utf-8")
        cleanup_generated_file_duplicates(path)
        return str(path)

    def handle_自媒体知识(self, message: Message) -> TaskResult:
        return self._handle_selfmedia_knowledge(message)

    def _selfmedia_knowledge_failure(self, result: dict[str, Any], reason: str) -> tuple[str, str, str]:
        public_reason = str(reason or "content-flow 未完成").strip()
        error_code = str(result.get("error_code") or "").strip()
        if not error_code and public_reason.startswith("LLM_SEMANTIC_PERSISTENCE_REQUIRED:"):
            error_code = "LLM_SEMANTIC_PERSISTENCE_REQUIRED"
            public_reason = public_reason.split(":", 1)[1].strip() or "knowledge_structured_analysis_required"
        if not error_code and (
            "结构化分析" in public_reason
            or "LLM" in public_reason
            or public_reason.startswith("content_flow_structured_analysis_required")
            or public_reason.startswith("wechat_article_semantic_analysis_required")
        ):
            error_code = "LLM_SEMANTIC_PERSISTENCE_REQUIRED"
        if not error_code:
            error_code = "CONTENT_FLOW_ANALYSIS_INCOMPLETE"
        status_code = error_code.lower()
        return error_code, public_reason, status_code

    @staticmethod
    def _selfmedia_knowledge_failure_guidance(result: dict[str, Any], error_code: str) -> tuple[str, str]:
        detail = str(result.get("detail") or "").strip()
        action = str(result.get("action") or "").strip()
        if error_code.startswith("WECHAT_ARTICLE_"):
            detail = detail or "公众号来源内容未完成提取，因此未调用后续语义入库。"
            action = action or "请确认链接可公开访问，或提供正文、截图等可读取来源后重试。"
        elif error_code == "LLM_SEMANTIC_PERSISTENCE_REQUIRED":
            detail = detail or "来源内容未形成满足知识入库契约的结构化 LLM 结果，因此没有写入知识表。"
            action = action or "请重试；持续失败时检查分析模型配置和结构化输出。"
        else:
            detail = detail or "content-flow 未返回可验证的完整产物，因此没有写入知识表。"
            action = action or "请重试，并根据错误代码检查来源抓取或分析任务状态。"
        return detail, action

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

        if missing:
            return "拆解未产生完整落地产物，缺少：" + "、".join(missing)
        return ""

    def handle_拆解(self, message: Message) -> TaskResult:
        try:
            tenant_id = require_tenant_id((message.metadata or {}).get("tenant_id"))
        except MediaVaultError as exc:
            return TaskResult(ok=False, status="tenant_context_required", reply=str(exc), task_id="")
        from selfmedia.deconstruct.viral_content.src.runner import run_workflow

        parsed = run_workflow(message.raw_text, tenant_id=tenant_id, write_feishu=True)
        deconstruct = parsed.get("deconstruct") if isinstance(parsed, dict) else {}
        if not isinstance(deconstruct, dict):
            deconstruct = {}
        completion_issue = self._deconstruct_completion_issue(
            {"ok": True}, parsed if isinstance(parsed, dict) else {}
        )
        if completion_issue:
            return TaskResult(
                ok=False,
                status="deconstruct_incomplete",
                reply=f"【拆解】未确认完成。\n原因：{completion_issue}",
                task_id=str(parsed.get("feishu_record_id") or "") if isinstance(parsed, dict) else "",
                extra=parsed if isinstance(parsed, dict) else {},
            )
        links = [
            str(deconstruct.get("deconstruct_doc_url") or "").strip(),
        ]
        links = [link for link in links if link]
        reply_lines = ["【拆解】处理完成。"]
        if links:
            reply_lines.append("文档：" + " / ".join(links))
        if parsed.get("feishu_record_id"):
            reply_lines.append(f"记录ID：{parsed['feishu_record_id']}")
        return TaskResult(
            ok=True,
            status=str(parsed.get("mode") or "deconstruct_done"),
            reply="\n".join(reply_lines),
            task_id=str(parsed.get("feishu_record_id") or ""),
            feishu_doc=links[0] if links else "",
            extra=parsed,
        )

    def handle_creation(self, message: Message) -> TaskResult:
        try:
            tenant_id = require_tenant_id((message.metadata or {}).get("tenant_id"))
        except MediaVaultError as exc:
            return TaskResult(ok=False, status="tenant_context_required", reply=str(exc), task_id="")
        from selfmedia.creation.workflow import handle_creation_command

        parsed = handle_creation_command(
            message.raw_text,
            tenant_id=tenant_id,
            conversation_context=self._conversation_context(message),
        )
        reply = str(parsed.get("reply") or "").strip()
        try:
            creation_run_id = str(parsed.get("creation_record_id") or "").strip()
            if creation_run_id:
                publisher = getattr(self, "publishing_service", None)
                if publisher is None or not callable(getattr(publisher, "project_creation_run", None)):
                    raise RuntimeError("publishing projection service is unavailable")
                parsed["publishing_projection"] = publisher.project_creation_run(tenant_id, creation_run_id)
            content_os_output = self._maybe_write_content_os_creation_output(message, parsed, reply)
            if not content_os_output:
                content_os_output = self._maybe_create_content_os_project_from_creation(message, parsed, reply)
            if not content_os_output:
                content_os_output = self._write_standalone_creation_output(message, parsed, reply)
        except Exception as exc:
            return TaskResult(
                ok=False,
                status="creation_publishing_projection_failed",
                reply=f"【创作】发布包投影失败：{exc}",
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
        try:
            tenant_id = require_tenant_id((message.metadata or {}).get("tenant_id"))
        except MediaVaultError as exc:
            return TaskResult(ok=False, status="tenant_context_required", reply=str(exc), task_id="")
        from selfmedia.creation.shooting_execution import handle_shooting_execution_command

        parsed = handle_shooting_execution_command(
            message.raw_text,
            tenant_id=tenant_id,
            conversation_context=self._conversation_context(message),
        )
        reply = str(parsed.get("reply") or "").strip()
        return TaskResult(
            ok=bool(parsed.get("ok", True)),
            status="shooting_execution_created" if parsed.get("doc_link") else str(parsed.get("mode") or "shooting_execution_done"),
            reply=reply or "【创作-拍摄执行】处理完成",
            task_id=str(parsed.get("creation_record_id") or ""),
            feishu_doc=str(parsed.get("doc_link") or ""),
            extra=parsed,
        )

    def handle_创作咨询(self, message: Message) -> TaskResult:
        try:
            tenant_id = require_tenant_id((message.metadata or {}).get("tenant_id"))
        except MediaVaultError as exc:
            return TaskResult(ok=False, status="tenant_context_required", reply=str(exc), task_id="")
        from selfmedia.creation.consultation import handle_creation_consultation_command

        parsed = handle_creation_consultation_command(
            message.raw_text,
            tenant_id=tenant_id,
            conversation_context=self._conversation_context(message),
        )
        reply = str(parsed.get("reply") or "").strip()
        return TaskResult(
            ok=bool(parsed.get("ok", True)),
            status="creation_consulted",
            reply=reply or "【创作咨询】处理完成",
            task_id="",
            extra=parsed,
        )
