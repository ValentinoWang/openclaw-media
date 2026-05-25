from __future__ import annotations

from .tag_router_common import *

class BusinessVlogMixin:
    def handle_id_business(self, message: Message) -> TaskResult:
        script = Path("/home/ubuntu/openclaw-agents/media/scripts/id_business.py")
        if not script.exists():
            return TaskResult(
                ok=False,
                status="id_business_script_missing",
                reply=f"商务-ID脚本不存在：{script}",
                task_id="",
            )

        cmd = [sys.executable, str(script), "ingest", "--stdin", "--require-feishu", "--notify-confirmation"]
        try:
            proc = subprocess.run(
                cmd,
                input=message.raw_text,
                text=True,
                capture_output=True,
                timeout=960,
                cwd=str(script.parent),
                env=self._subprocess_env_with_context(message),
            )
        except subprocess.TimeoutExpired as exc:
            return TaskResult(
                ok=False,
                status="id_business_timeout",
                reply=f"商务-ID处理超时，账号截图或飞书写入未完成。\n错误：{exc}",
                task_id="",
            )
        except OSError as exc:
            return TaskResult(
                ok=False,
                status="id_business_failed",
                reply=f"无法调用 商务-ID脚本。\n错误：{exc}",
                task_id="",
            )

        parsed = self._parse_openclaw_json(proc.stdout)
        if proc.returncode != 0:
            error_text = (
                str(parsed.get("error") or parsed.get("reply") or "").strip()
                or proc.stderr.strip()
                or self._summarize_process_output(parsed, proc.stdout)
                or f"id_business.py exited with {proc.returncode}"
            )
            return TaskResult(ok=False, status="id_business_failed", reply=error_text[-3000:], task_id="")

        fields = parsed.get("fields") if isinstance(parsed.get("fields"), dict) else {}
        feishu = parsed.get("feishu") if isinstance(parsed.get("feishu"), dict) else {}
        capture = parsed.get("capture") if isinstance(parsed.get("capture"), dict) else {}
        record_id = str(feishu.get("record_id") or "")
        action = {"created": "新建", "updated": "更新"}.get(str(feishu.get("action") or ""), "写入")
        reply_lines = [
            f"商务-ID已{action}到商务账号多维表格",
            f"平台：{fields.get('平台') or '未识别'}",
            f"作者ID：{fields.get('作者ID') or '未提取到'}",
            f"平台账号：{fields.get('账号名称') or '未提取到'}",
            f"项目：{fields.get('项目') or '未提取到'}",
            f"品牌：{fields.get('品牌') or '未提取到'}",
            f"产品：{fields.get('产品') or '未提取到'}",
        ]
        if feishu.get("table_url"):
            reply_lines.append(f"多维表格：{feishu['table_url']}")
        if record_id:
            reply_lines.append(f"记录 ID：{record_id}")
        if fields.get("主页链接"):
            reply_lines.append(f"主页链接：{fields['主页链接']}")
        if fields.get("Brief链接"):
            reply_lines.append(f"Brief链接：{fields['Brief链接']}")
        if fields.get("主页截图路径"):
            reply_lines.append(f"截图：{fields['主页截图路径']}")
        if fields.get("账号数据摘要"):
            reply_lines.append(f"账号数据：{fields['账号数据摘要']}")
        if capture.get("status") or fields.get("截图状态"):
            reply_lines.append(f"截图状态：{capture.get('status') or fields.get('截图状态')}")
        if fields.get("需反问博主字段"):
            reply_lines.append(f"需反问博主：{fields['需反问博主字段']}")
        if fields.get("反问博主状态"):
            reply_lines.append(f"反问状态：{fields['反问博主状态']}")
        if fields.get("待补充字段"):
            reply_lines.append(f"待补充字段：{fields['待补充字段']}")
        if fields.get("最近错误"):
            reply_lines.append(f"最近错误：{fields['最近错误']}")
        return TaskResult(
            ok=True,
            status="id_business_archived",
            reply="\n".join(reply_lines),
            task_id=record_id,
            local_path=str(parsed.get("local_path") or ""),
            extra={"id_business": parsed},
        )

    def handle_灵感(self, message: Message) -> TaskResult:
        tag_rule = self.rule_service.get_tag_rule("灵感")
        result = self.content_flow_client.summarize_inspiration(
            message.body,
            source_hint=self._conversation_context_prompt(message),
            artifact_dir=self.workspace_root / "content_flow" / "inspirations" / make_record_id(message.created_at, message.source, message.entry_tag),
        )
        if result.get("status") == "done":
            title = self._inspiration_title(result, message.body)
            sections = self._inspiration_sections(message.body, result)
            tags = self._inspiration_tags(result, tag_rule)
            extra = {
                "tags": tags,
                "postprocess_status": "done",
                "postprocess_provider": result.get("postprocess_provider", ""),
                "postprocess_model": result.get("postprocess_model", ""),
                "postprocess_artifacts": result.get("postprocess_artifacts", {}),
            }
            if context_prompt := self._conversation_context_prompt(message):
                extra["conversation_context_count"] = self._conversation_context(message).get("loaded_count", 0)
            entry = self.archive_service.save_archive(message, title, sections, extra)
            doc_name = tag_rule.get("feishu_doc", "灵感池")
            fs = self._sync_inspiration_entry_to_feishu(entry, message, doc_name, result)
            reply = ReplyService.archived(message.entry_tag, entry.local_path, fs.get("doc", ""))
            if warning := fs.get("warning"):
                reply = ReplyService.append_warning(reply, warning)
            return TaskResult(
                ok=True,
                status="archived",
                reply=reply,
                task_id=entry.frontmatter["id"],
                local_path=entry.local_path,
                feishu_doc=fs.get("doc", ""),
                extra={"inspiration": result},
            )

        fallback = self._fallback_inspiration_result(message.body, str(result.get("reason") or "灵感整理失败"))
        title = self._inspiration_title(fallback, message.body)
        sections = self._inspiration_sections(message.body, fallback)
        tags = self._inspiration_tags(fallback, tag_rule)
        entry = self.archive_service.save_archive(
            message,
            title,
            sections,
            {
                "tags": tags,
                "postprocess_status": "fallback",
                "postprocess_reason": fallback.get("confidence_note", ""),
                "postprocess_artifacts": result.get("postprocess_artifacts", {}),
            },
        )
        doc_name = tag_rule.get("feishu_doc", "灵感池")
        fs = self._sync_inspiration_entry_to_feishu(entry, message, doc_name, fallback)
        reply = ReplyService.archived(message.entry_tag, entry.local_path, fs.get("doc", ""))
        if warning := fs.get("warning"):
            reply = ReplyService.append_warning(reply, warning)
        return TaskResult(
            ok=True,
            status="archived",
            reply=reply,
            task_id=entry.frontmatter["id"],
            local_path=entry.local_path,
            feishu_doc=fs.get("doc", ""),
            extra={"inspiration": fallback, "postprocess": result},
        )

    def _feishu_block(self, message: Message, local_path: str, body: str) -> str:
        return "\n".join([
            f"## {format_display_time(message.created_at)}",
            "",
            f"- 来源：{message.source.upper()}",
            f"- 标签：{message.entry_tag}",
            f"- 原始内容：{body}",
            f"- 本地归档：{local_path}",
        ])

    def _sync_inspiration_entry_to_feishu(self, entry, message: Message, doc_name: str, result: dict[str, Any]) -> dict[str, str]:
        try:
            content = "\n".join(
                [
                    f"## {format_display_time(message.created_at)}",
                    "",
                    f"- 来源：{message.source.upper()}",
                    "- 标签：灵感",
                    f"- 标题：{self._inspiration_title(result, message.body)}",
                    f"- 本地归档：{entry.local_path}",
                    "",
                    "### 清理后的完整灵感脉络",
                    str(result.get("cleaned_brief") or message.body).strip(),
                    "",
                    "### 内容结构",
                    self._format_inspiration_list(result.get("content_outline")),
                    "",
                    "### 素材与场景",
                    self._format_inspiration_list(result.get("scenes_materials")),
                    "",
                    "### 观点与理念",
                    self._format_inspiration_list(result.get("concepts_or_views")),
                    "",
                    "### AI / 科技知识点",
                    self._format_inspiration_list(result.get("knowledge_points")),
                    "",
                    "### 执行清单",
                    self._format_inspiration_checklist(result.get("execution_plan")),
                    "",
                    "### 待补充",
                    self._format_inspiration_checklist(result.get("pending_questions")),
                ]
            ).strip()
            fs = self.feishu_service.append_entry(doc_name, content)
            self.archive_service.update_frontmatter(entry.local_path, {"feishu_synced": True, "feishu_doc": fs.get("doc", "")})
            return fs
        except Exception as exc:
            self.archive_service.update_frontmatter(entry.local_path, {"feishu_synced": False, "feishu_doc": doc_name, "feishu_error": str(exc)})
            return {"status": "pending_manual", "doc": doc_name, "warning": f"飞书同步失败：{exc}"}

    def _inspiration_sections(self, raw_body: str, result: dict[str, Any]) -> list[tuple[str, str]]:
        return [
            ("原始内容", raw_body.strip()),
            ("清理后的完整灵感脉络", str(result.get("cleaned_brief") or raw_body).strip()),
            ("核心主旨", str(result.get("core_theme") or "").strip() or "未明确"),
            ("内容结构", self._format_inspiration_list(result.get("content_outline"))),
            ("素材与场景", self._format_inspiration_list(result.get("scenes_materials"))),
            ("观点与理念", self._format_inspiration_list(result.get("concepts_or_views"))),
            ("AI / 科技知识点", self._format_inspiration_list(result.get("knowledge_points"))),
            ("执行清单", self._format_inspiration_checklist(result.get("execution_plan"))),
            ("待补充", self._format_inspiration_checklist(result.get("pending_questions"))),
            ("整理说明", str(result.get("confidence_note") or "已按灵感卡结构整理。").strip()),
        ]

    def _inspiration_title(self, result: dict[str, Any], raw_body: str) -> str:
        title = self._clean_meeting_topic_candidate(result.get("title", ""))
        if title:
            return f"灵感：{title}"
        fallback = self._knowledge_compact_title(str(raw_body or ""), limit=28)
        return f"灵感：{fallback or '未命名灵感'}"

    def _inspiration_tags(self, result: dict[str, Any], tag_rule: dict[str, Any]) -> list[str]:
        tags: list[str] = []
        default_tags = tag_rule.get("default_tags") if isinstance(tag_rule, dict) else []
        if isinstance(default_tags, list):
            tags.extend(str(item).strip() for item in default_tags if str(item).strip())
        suggested = result.get("suggested_tags")
        if isinstance(suggested, list):
            tags.extend(str(item).strip() for item in suggested if str(item).strip())
        tags.insert(0, "灵感")
        deduped: list[str] = []
        for tag in tags:
            if tag and tag not in deduped:
                deduped.append(tag)
        return deduped

    def _format_inspiration_list(self, value: Any) -> str:
        items: list[str] = []
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    text = "；".join(f"{key}：{val}" for key, val in item.items() if str(val).strip())
                else:
                    text = str(item).strip()
                if text:
                    items.append(text)
        else:
            text = str(value or "").strip()
            if text:
                items.extend(line.strip("-*+ 　") for line in text.splitlines() if line.strip())
        return "\n".join(f"- {item}" for item in items) if items else "- 未明确"

    def _format_inspiration_checklist(self, value: Any) -> str:
        text = self._format_inspiration_list(value)
        if text == "- 未明确":
            return "- [ ] 未明确"
        lines = []
        for line in text.splitlines():
            item = re.sub(r"^[-*+]\s*", "", line).strip()
            if item:
                lines.append(f"- [ ] {item}")
        return "\n".join(lines) if lines else "- [ ] 未明确"

    def _fallback_inspiration_result(self, raw_body: str, reason: str) -> dict[str, Any]:
        cleaned = self._clean_labeled_transcript_text(raw_body)
        title = self._knowledge_compact_title(cleaned, limit=24)
        return {
            "status": "fallback",
            "title": title or "未命名灵感",
            "cleaned_brief": cleaned or raw_body.strip(),
            "core_theme": title or "待进一步整理的灵感",
            "content_outline": [cleaned or raw_body.strip()],
            "scenes_materials": [],
            "concepts_or_views": [],
            "knowledge_points": [],
            "execution_plan": ["补充目标平台、受众、形式、素材和发布时间"],
            "pending_questions": ["这条灵感最终要沉淀为选题、脚本、项目计划还是知识卡？"],
            "suggested_tags": ["灵感"],
            "confidence_note": f"LLM 灵感整理未完成，已保存确定性兜底结构。原因：{reason}",
        }
