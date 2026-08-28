from __future__ import annotations

from argparse import Namespace

from .tag_router_common import *
from datetime import date
from zoneinfo import ZoneInfo
from media_vault import MediaVaultError, require_tenant_id


BUSINESS_PRESENTATION_STATUS_LABELS = {
    "captured": "已获取",
    "collected": "已收集",
    "done": "已完成",
    "pending": "待确认",
    "pending_manual": "待人工确认",
    "capture_auth_required": "登录状态失效，待重新获取",
    "capture_failed": "获取失败，待复核",
}


def _business_presentation_status(value: object) -> str:
    raw = str(value or "").strip()
    return BUSINESS_PRESENTATION_STATUS_LABELS.get(raw, "待复核")


class BusinessVlogMixin:
    def handle_id_business(self, message: Message) -> TaskResult:
        try:
            tenant_id = require_tenant_id((message.metadata or {}).get("tenant_id"))
        except MediaVaultError as exc:
            return TaskResult(ok=False, status="tenant_context_required", reply=str(exc), task_id="")
        from selfmedia.business.id_business import ingest

        parsed = ingest(
            Namespace(
                text=message.raw_text,
                stdin=False,
                feishu_url="",
                profile_url="",
                screenshot="",
                brief_file=[],
                account_name="",
                notify_confirmation=True,
                require_feishu=True,
                dry_run=False,
                no_screenshot=False,
                smoke=False,
                tenant_id=tenant_id,
            )
        )
        if str(parsed.get("status") or "") == "id_business_llm_pending_manual":
            reason = str(parsed.get("reason") or parsed.get("error") or "商务>ID LLM 字段抽取待人工确认").strip()
            fields = parsed.get("fields") if isinstance(parsed.get("fields"), dict) else {}
            pending = str(fields.get("待补充字段") or "").strip()
            details = parsed.get("details") if isinstance(parsed.get("details"), dict) else {}
            ai_reply = str(fields.get("AI回复话术") or "").strip()
            if not ai_reply and isinstance(details.get("ai_reply"), dict):
                ai_reply = str(details["ai_reply"].get("reply") or "").strip()
            fallback_reply = reason
            if pending:
                fallback_reply += f"\n待补充字段：{pending}"
            return TaskResult(
                ok=False,
                status="id_business_llm_pending_manual",
                reply=ai_reply or fallback_reply,
                task_id="",
                local_path=str(parsed.get("local_path") or ""),
                extra={"id_business": parsed},
            )
        if str(parsed.get("status") or "") == "id_business_external_retry_pending":
            return TaskResult(
                ok=False,
                status="id_business_external_retry_pending",
                reply="商务账号与商机尚未完成外部读回，已保留可重试记录。请在外部配置恢复后重试原始【商务>ID】消息。",
                task_id="",
                local_path=str(parsed.get("local_path") or parsed.get("commercial_loop_path") or ""),
                extra={"id_business": parsed},
            )
        fields = parsed.get("fields") if isinstance(parsed.get("fields"), dict) else {}
        feishu = parsed.get("feishu") if isinstance(parsed.get("feishu"), dict) else {}
        capture = parsed.get("capture") if isinstance(parsed.get("capture"), dict) else {}
        details = parsed.get("details") if isinstance(parsed.get("details"), dict) else {}
        ai_reply_details = details.get("ai_reply") if isinstance(details.get("ai_reply"), dict) else {}
        ai_reply_status = str(ai_reply_details.get("status") or "").strip()
        record_id = str(feishu.get("account_record_id") or "")
        reply_lines = [
            "商务>ID已写入商务账号与商务机会多维表格",
            f"平台：{fields.get('平台') or '未识别'}",
            f"作者ID：{fields.get('作者ID') or '未提取到'}",
            f"平台账号：{fields.get('账号名称') or '未提取到'}",
            f"项目：{fields.get('项目') or '未提取到'}",
            f"品牌：{fields.get('品牌') or '未提取到'}",
            f"产品：{fields.get('产品') or '未提取到'}",
        ]
        if fields.get("主页链接"):
            reply_lines.append(f"主页链接：{fields['主页链接']}")
        if fields.get("Brief链接"):
            reply_lines.append(f"Brief链接：{fields['Brief链接']}")
        if fields.get("账号数据摘要"):
            reply_lines.append(f"账号数据：{fields['账号数据摘要']}")
        if capture.get("status") or fields.get("截图状态"):
            reply_lines.append(f"截图状态：{_business_presentation_status(capture.get('status') or fields.get('截图状态'))}")
        if fields.get("需反问博主字段"):
            reply_lines.append(f"需反问博主：{fields['需反问博主字段']}")
        if fields.get("反问博主状态"):
            reply_lines.append(f"反问状态：{_business_presentation_status(fields['反问博主状态'])}")
        if fields.get("待补充字段") and ai_reply_status != "done":
            reply_lines.append(f"待补充字段：{fields['待补充字段']}")
        ai_reply = str(fields.get("AI回复话术") or "").strip()
        if not ai_reply and isinstance(details.get("ai_reply"), dict):
            ai_reply = str(details["ai_reply"].get("reply") or "").strip()
        visible_reply = ai_reply or "\n".join(reply_lines)
        return TaskResult(
            ok=True,
            status="id_business_archived",
            reply=visible_reply,
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
            validation_issue = self._inspiration_archive_validation_issue(result)
            if validation_issue:
                result = {**result, "status": "pending_manual", "reason": validation_issue}
            else:
                return self._archive_inspiration_done(message, tag_rule, result)

        reason = str(result.get("reason") or "LLM 未返回可用灵感结构").strip()
        entry = self.archive_service.save_archive(
            message,
            "灵感待 LLM 整理",
            [
                ("原始内容", message.body.strip()),
                ("整理失败原因", reason),
                ("已识别内容", self._inspiration_failure_summary(result)),
                ("建议补充", "补充清晰的主题、目标产物或可验证动作后重新整理。"),
            ],
            {
                "tags": ["灵感", "LLM整理失败"],
                "postprocess_status": "pending_manual",
                "postprocess_reason": reason,
                "postprocess_artifacts": result.get("postprocess_artifacts", {}),
            },
        )
        reply = "\n".join(
            [
                "灵感卡没有生成：LLM 未返回可用主体字段。",
                f"原因：{reason}",
                "已保留本地记录；不会用确定性规则生成灵感卡主体。",
                f"本地路径：{entry.local_path}",
            ]
        )
        return TaskResult(
            ok=False,
            status="inspiration_llm_pending_manual",
            reply=reply,
            task_id=entry.frontmatter["id"],
            local_path=entry.local_path,
            extra={"postprocess": result},
        )

    def _archive_inspiration_done(self, message: Message, tag_rule: dict[str, Any], result: dict[str, Any]) -> TaskResult:
        title = self._inspiration_title(result, message.body)
        sections = self._inspiration_sections(message.body, result)
        tags = self._inspiration_tags(result, tag_rule)
        weekly_title = self._inspiration_weekly_title(result, message.body)
        extra = {
            "tags": tags,
            "feishu_skip": True,
            "postprocess_status": "done",
            "postprocess_provider": result.get("postprocess_provider", ""),
            "postprocess_model": result.get("postprocess_model", ""),
            "postprocess_artifacts": result.get("postprocess_artifacts", {}),
        }
        if context_prompt := self._conversation_context_prompt(message):
            extra["conversation_context_count"] = self._conversation_context(message).get("loaded_count", 0)
        entry = self.archive_service.save_archive(message, title, sections, extra)
        obsidian_note_path = self._mirror_inspiration_to_obsidian(entry.local_path)
        weekly_path, weekly_line = self._append_inspiration_to_weekly_content(message, weekly_title, obsidian_note_path, result)
        entry = self.archive_service.update_frontmatter(
            entry.local_path,
            {
                "obsidian_synced": True,
                "obsidian_note_path": str(obsidian_note_path),
                "weekly_path": str(weekly_path),
                "weekly_title": weekly_title,
                "weekly_line": weekly_line,
            },
        )
        obsidian_note_path = self._mirror_inspiration_to_obsidian(entry.local_path)
        reply = "\n".join(
            [
                "已归档到周记。",
                "标签：灵感",
                f"周记标题：{weekly_title}",
                f"周记路径：{weekly_path}",
                f"Obsidian详情：{obsidian_note_path}",
                f"本地归档：{entry.local_path}",
            ]
        )
        return TaskResult(
            ok=True,
            status="obsidian_archived",
            reply=reply,
            task_id=entry.frontmatter["id"],
            local_path=entry.local_path,
            extra={
                "inspiration": result,
                "obsidian_note_path": str(obsidian_note_path),
                "weekly_path": str(weekly_path),
                "weekly_title": weekly_title,
                "weekly_line": weekly_line,
            },
        )

    def _mirror_inspiration_to_obsidian(self, local_path: str) -> Path:
        obsidian_root = Path(os.environ.get("OPENCLAW_OBSIDIAN_ROOT", str(self.workspace_root / "obsidian")))
        target_dir = ensure_dir(obsidian_root / "灵感" / "归档")
        target_path = target_dir / Path(local_path).name
        target_path.write_text(Path(local_path).read_text(encoding="utf-8"), encoding="utf-8")
        return target_path

    def _append_inspiration_to_weekly_content(
        self,
        message: Message,
        weekly_title: str,
        obsidian_note_path: str | Path,
        result: dict[str, Any],
    ) -> tuple[Path, str]:
        zoned = message.created_at.astimezone(ZoneInfo(self.timezone))
        start = zoned.date() - timedelta(days=zoned.weekday())
        end = start + timedelta(days=6)
        archive_root = Path(os.environ.get("OPENCLAW_WEEKLY_ARCHIVE_ROOT", str(self.workspace_root / "obsidian" / "Archieve")))
        weekly_path = archive_root / f"{start.strftime('%Y%m%d')}-{end.strftime('%Y%m%d')}.md"
        ensure_dir(weekly_path.parent)
        relative_path = os.path.relpath(Path(obsidian_note_path), weekly_path.parent).replace(os.sep, "/")
        entry = self._build_inspiration_weekly_entry(message, weekly_title, relative_path, result)
        if weekly_path.exists():
            text = weekly_path.read_text(encoding="utf-8")
        else:
            text = ""
        if relative_path not in text:
            text = self._append_entry_to_weekly_date_section(text, zoned.date(), "灵感", "灵感", entry)
            text = self._sort_weekly_date_sections(text)
            weekly_path.write_text(text, encoding="utf-8")
        return weekly_path, entry

    @staticmethod
    def _find_weekly_heading_bounds(text: str, level: int, heading: str, start: int = 0, end: int | None = None) -> tuple[re.Match[str] | None, int, int]:
        end = len(text) if end is None else end
        prefix = "#" * level
        match = re.search(rf"^{re.escape(prefix)}\s+{re.escape(heading)}\s*$", text[start:end], flags=re.MULTILINE)
        if not match:
            return None, end, end
        absolute_start = start + match.start()
        absolute_end = start + match.end()
        next_heading = re.search(rf"^#{{1,{level}}}\s+\S.*$", text[absolute_end:end], flags=re.MULTILINE)
        body_end = absolute_end + next_heading.start() if next_heading else end
        return re.match(r".*", text[absolute_start:absolute_end]), absolute_end, body_end

    @staticmethod
    def _append_entry_to_weekly_date_section(text: str, entry_date: date, section: str, subsection: str, entry: str) -> str:
        if text and not text.endswith("\n"):
            text += "\n"
        date_heading = entry_date.strftime("%Y%m%d")
        _, date_body_start, date_body_end = BusinessVlogMixin._find_weekly_heading_bounds(text, 1, date_heading)
        if date_body_start == len(text) and f"# {date_heading}" not in text:
            dev_match = re.search(r"^#\s*开发\s*$", text, flags=re.MULTILINE)
            block = f"# {date_heading}\n"
            if dev_match:
                before = text[:dev_match.start()].rstrip()
                after = text[dev_match.start():].lstrip("\n")
                text = f"{before}\n\n{block}\n{after}" if before else f"{block}\n{after}"
            else:
                text = f"{text.rstrip()}\n\n{block}" if text.strip() else block

        _, date_body_start, date_body_end = BusinessVlogMixin._find_weekly_heading_bounds(text, 1, date_heading)
        _, section_body_start, section_body_end = BusinessVlogMixin._find_weekly_heading_bounds(
            text, 2, section, date_body_start, date_body_end
        )
        if section_body_start == date_body_end and f"## {section}" not in text[date_body_start:date_body_end]:
            before = text[:date_body_end].rstrip()
            after = text[date_body_end:].lstrip("\n")
            text = f"{before}\n\n## {section}\n"
            if after:
                text += "\n" + after

        _, date_body_start, date_body_end = BusinessVlogMixin._find_weekly_heading_bounds(text, 1, date_heading)
        _, section_body_start, section_body_end = BusinessVlogMixin._find_weekly_heading_bounds(
            text, 2, section, date_body_start, date_body_end
        )
        _, subsection_body_start, subsection_body_end = BusinessVlogMixin._find_weekly_heading_bounds(
            text, 3, subsection, section_body_start, section_body_end
        )
        if subsection_body_start == section_body_end and f"### {subsection}" not in text[section_body_start:section_body_end]:
            before = text[:section_body_end].rstrip()
            after = text[section_body_end:].lstrip("\n")
            text = f"{before}\n\n### {subsection}\n"
            if after:
                text += "\n" + after

        _, date_body_start, date_body_end = BusinessVlogMixin._find_weekly_heading_bounds(text, 1, date_heading)
        _, section_body_start, section_body_end = BusinessVlogMixin._find_weekly_heading_bounds(
            text, 2, section, date_body_start, date_body_end
        )
        _, _, subsection_body_end = BusinessVlogMixin._find_weekly_heading_bounds(
            text, 3, subsection, section_body_start, section_body_end
        )
        before = text[:subsection_body_end].rstrip()
        after = text[subsection_body_end:].lstrip("\n")
        updated = f"{before}\n\n{entry.rstrip()}\n"
        if after:
            updated += "\n" + after
        return updated

    @staticmethod
    def _append_entry_to_weekly_section(text: str, section: str, entry: str) -> str:
        if not text.endswith("\n"):
            text += "\n"
        heading = f"# {section}"
        match = re.search(rf"^#\s+{re.escape(section)}\s*$", text, flags=re.MULTILINE)
        if not match:
            dev_match = re.search(r"^#\s*开发\s*$", text, flags=re.MULTILINE)
            section_block = f"{heading}\n\n{entry.rstrip()}\n\n"
            if dev_match:
                before = text[: dev_match.start()].rstrip()
                after = text[dev_match.start():].lstrip("\n")
                prefix = f"{before}\n\n" if before else ""
                return f"{prefix}{section_block}{after}"
            suffix = "" if text.endswith("\n\n") else "\n"
            return f"{text}{suffix}{heading}\n\n{entry.rstrip()}\n"
        next_heading = re.search(r"^#(?!#)\s+\S.*$", text[match.end():], flags=re.MULTILINE)
        insert_at = match.end() + next_heading.start() if next_heading else len(text)
        before = text[:insert_at].rstrip()
        after = text[insert_at:].lstrip("\n")
        updated = f"{before}\n\n{entry.rstrip()}\n"
        if after:
            updated += "\n" + after
        return updated

    def _build_inspiration_weekly_entry(self, message: Message, weekly_title: str, relative_path: str, result: dict[str, Any]) -> str:
        zoned = message.created_at.astimezone(ZoneInfo(self.timezone))
        link_title = re.sub(r"[\[\]\n\r]", "", weekly_title).strip() or "记录一个待展开的灵感火花"
        lines = [
            f"#### {link_title}",
            "",
            f"宏观总结：{self._inspiration_archive_macro_summary(result)}",
            "",
        ]
        lines.extend(f"- {item}" for item in self._inspiration_archive_summary_bullets(result))
        lines.extend(["", f"详细链接：[{Path(relative_path).stem}]({relative_path})"])
        return "\n".join(lines).rstrip() + "\n"

    @staticmethod
    def _sort_weekly_date_sections(text: str) -> str:
        stripped = text.strip()
        if not stripped:
            return ""
        starts = [item.start() for item in re.finditer(r"(?m)^#\s+\S.*$", stripped)]
        if not starts:
            return stripped + "\n"
        if starts[0] != 0:
            starts.insert(0, 0)
        starts.append(len(stripped))
        date_blocks: list[tuple[date, int, str]] = []
        other_blocks: list[tuple[int, str]] = []
        bottom_blocks: list[tuple[int, str]] = []
        for index, start in enumerate(starts[:-1]):
            block = stripped[start: starts[index + 1]].strip()
            if not block:
                continue
            heading_match = re.match(r"^#\s+(.+?)\s*$", block.splitlines()[0])
            heading = heading_match.group(1).strip() if heading_match else ""
            date_match = re.match(r"^(20\d{2})(\d{2})(\d{2})$", heading)
            if date_match:
                try:
                    parsed = date(*(int(part) for part in date_match.groups()))
                except ValueError:
                    other_blocks.append((index, block))
                else:
                    date_blocks.append((parsed, index, block))
            elif heading == "开发":
                bottom_blocks.append((index, block))
            else:
                other_blocks.append((index, block))
        ordered_dates = [block for _, _, block in sorted(date_blocks, key=lambda item: (item[0], -item[1]), reverse=True)]
        ordered_other = [block for _, block in sorted(other_blocks, key=lambda item: item[0])]
        ordered_bottom = [block for _, block in sorted(bottom_blocks, key=lambda item: item[0])]
        return "\n\n".join(ordered_dates + ordered_other + ordered_bottom).rstrip() + "\n"

    @staticmethod
    def _sort_weekly_section_entries_by_date(text: str, section: str) -> str:
        match = re.search(rf"^#\s+{re.escape(section)}\s*$", text, flags=re.MULTILINE)
        if not match:
            return text
        body_start = match.end()
        next_heading = re.search(r"^#(?!#)\s+\S.*$", text[body_start:], flags=re.MULTILINE)
        body_end = body_start + next_heading.start() if next_heading else len(text)
        body = text[body_start:body_end].strip()
        if not body:
            return text
        starts = [item.start() for item in re.finditer(r"(?m)^###\s+\d{2}-\d{2}-\d{2}\b", body)]
        if not starts:
            return text
        if starts[0] != 0:
            starts.insert(0, 0)
        starts.append(len(body))
        entries = [body[starts[index] : starts[index + 1]].strip() for index in range(len(starts) - 1)]
        entries = [entry for entry in entries if entry]

        def sort_key(item: tuple[int, str]) -> tuple[int, int, int, int]:
            index, entry = item
            date_match = re.search(r"(?m)^###\s+(\d{2})-(\d{2})-(\d{2})\b", entry)
            if not date_match:
                return (0, 0, 0, -index)
            year, month, day = (int(part) for part in date_match.groups())
            return (2000 + year, month, day, -index)

        sorted_entries = [entry for _, entry in sorted(enumerate(entries), key=sort_key, reverse=True)]
        before = text[:body_start].rstrip()
        after = text[body_end:].lstrip("\n")
        updated = f"{before}\n\n" + "\n\n".join(sorted_entries).rstrip() + "\n"
        if after:
            updated += "\n" + after
        return updated.rstrip() + "\n"

    @staticmethod
    def _inspiration_archive_validation_issue(result: dict[str, Any]) -> str:
        macro = str(result.get("archive_macro_summary") or "").strip()
        bullets = result.get("archive_summary_bullets")
        if not macro:
            return "LLM 灵感整理缺少周记宏观总结"
        if not isinstance(bullets, list) or not [str(item).strip() for item in bullets if str(item).strip()]:
            return "LLM 灵感整理缺少周记分点摘要"
        if len([str(item).strip() for item in bullets if str(item).strip()]) > 5:
            return "LLM 灵感整理周记分点摘要超过 5 条"
        return ""

    @staticmethod
    def _inspiration_failure_summary(result: dict[str, Any]) -> str:
        labels = (("主题", "core_theme"), ("一句话火花", "spark"), ("标题", "title"), ("可展开方向", "expansion_directions"))
        lines: list[str] = []
        for label, key in labels:
            value = result.get(key)
            if isinstance(value, list):
                value = "、".join(str(item).strip() for item in value if str(item).strip())
            text = re.sub(r"\s+", " ", str(value or "")).strip()
            if text:
                lines.append(f"{label}：{text[:500]}")
        return "\n".join(lines) if lines else "暂未识别出可直接归档的主题或行动信息。"

    @staticmethod
    def _inspiration_archive_macro_summary(result: dict[str, Any]) -> str:
        macro = str(result.get("archive_macro_summary") or "").strip()
        return re.sub(r"\s+", " ", macro)[:500]

    @staticmethod
    def _inspiration_archive_summary_bullets(result: dict[str, Any]) -> list[str]:
        bullets = result.get("archive_summary_bullets")
        cleaned: list[str] = []
        if isinstance(bullets, list):
            for item in bullets:
                text = re.sub(r"^\s*[-*•\d.、]+\s*", "", str(item or "")).strip()
                text = re.sub(r"\s+", " ", text)
                if text:
                    cleaned.append(text[:500])
                if len(cleaned) >= 5:
                    break
        return cleaned

    def _feishu_block(self, message: Message, local_path: str, body: str) -> str:
        return "\n".join([
            f"## {format_display_time(message.created_at)}",
            "",
            f"- 来源：{message.source.upper()}",
            f"- 标签：{message.entry_tag}",
            f"- 原始内容：{body}",
            f"- 本地归档：{local_path}",
        ])

    def _inspiration_sections(self, raw_body: str, result: dict[str, Any]) -> list[tuple[str, str]]:
        return [
            ("原始内容", raw_body.strip()),
            ("一句话火花", str(result.get("spark") or result.get("core_theme") or result.get("cleaned_brief") or raw_body).strip()),
            ("这条灵感在做什么", str(result.get("what_it_does") or result.get("core_theme") or "").strip() or "未明确"),
            ("为什么现在出现", str(result.get("why_now") or "").strip() or "未明确"),
            ("可展开方向", self._format_inspiration_list(result.get("expansion_directions") or result.get("content_outline"))),
            ("可能产物", self._format_inspiration_list(result.get("possible_outputs") or result.get("scenes_materials"))),
            ("可验证动作", self._format_inspiration_checklist(result.get("verification_actions") or result.get("execution_plan"))),
            ("保留的原始句子", self._format_inspiration_list(result.get("original_lines_to_keep"))),
            ("待补充", self._format_inspiration_checklist(result.get("pending_questions"))),
            ("整理说明", str(result.get("confidence_note") or "已按灵感归档结构整理。").strip()),
        ]

    def _inspiration_title(self, result: dict[str, Any], raw_body: str) -> str:
        title = self._clean_meeting_topic_candidate(result.get("title", ""))
        if title:
            return f"灵感：{title}"
        derived_title = self._knowledge_compact_title(str(raw_body or ""), limit=28)
        return f"灵感：{derived_title or '未命名灵感'}"

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

    def _inspiration_weekly_title(self, result: dict[str, Any], raw_body: str) -> str:
        title = self._clean_meeting_topic_candidate(result.get("weekly_title", ""))
        if not title:
            title = self._clean_meeting_topic_candidate(result.get("what_it_does", ""))
        if not title:
            title = self._clean_meeting_topic_candidate(result.get("title", ""))
        if not title:
            title = self._knowledge_compact_title(str(raw_body or ""), limit=32)
        title = re.sub(r"^(关于|有关|对于)", "", str(title or "")).strip(" ：:，,。")
        return title[:42] or "记录一个待展开的灵感火花"

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
