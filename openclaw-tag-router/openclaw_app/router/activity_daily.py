from __future__ import annotations

from .tag_router_common import *


class ActivityDailyMixin:
    def handle_活动(self, message: Message) -> TaskResult:
        ai_clean = self.content_flow_client.clean_activity_brief(
            message.body,
            created_at=message.created_at.isoformat(timespec="seconds"),
            source_hint=message.source,
        )
        if ai_clean.get("status") == "done":
            activity = self._activity_from_ai_clean(message.body, ai_clean)
        else:
            brief = self.brief_extraction_service.extract(message.body, domain="activity", created_at=message.created_at)
            activity = self._extract_activity(message.body, brief)
            activity["source_status"] = f"AI清洗失败，已使用兜底抽取：{ai_clean.get('reason') or '未返回结构化结果'}"
        self._mark_unread_external_activity_docs(activity)
        task_id = make_record_id(message.created_at, message.source, message.entry_tag)
        parse_status = activity.get("parse_status") or ("待人工补充" if activity.get("manual_needed") else "已解析")
        if parse_status == "已解析" and "待读取" in activity.get("source_status", ""):
            parse_status = "飞书文档待读取"
        source_links = "\n".join(f"{item['label']}：{item['url']}" for item in activity.get("links", []))
        subtopic_directions = "\n".join(f"- {item}" for item in activity.get("directions", []))
        missing_info = "、".join(activity.get("missing_info") or [])
        extra = {
            "platform": activity["platform"],
            "main_topic": activity["main_topic"],
            "activity_time": activity["activity_time"],
            "brief_summary": activity.get("brief_summary", ""),
            "participation_method": activity.get("participation_method", ""),
            "participation_form": activity.get("participation_form", ""),
            "filling_points": activity.get("filling_points", ""),
            "submission_requirements": activity.get("submission_requirements", ""),
            "source_status": activity.get("source_status", ""),
            "manual_needed": bool(activity.get("manual_needed")),
            "tags": ["内容素材", "活动", activity["platform"]],
        }
        reminder = self.reminder_service.add(
            kind="活动",
            title=activity["title"],
            text=self._format_activity_record(activity, message.body),
            due_at=None,
            remind_at=None,
            source=message.source,
            ref_id=task_id,
            local_path="",
            extra_fields={
                "记录类型": "活动",
                "状态": activity.get("status", "待判断"),
                "平台名称": self._activity_platform_value(activity.get("platform", "")),
                "活动Brief": activity.get("brief_summary", ""),
                "填写要点": activity.get("filling_points", ""),
                "参与方式": activity.get("participation_method", ""),
                "参与形式": activity.get("participation_form", ""),
                "提交要求": activity.get("submission_requirements", ""),
                "子话题方向": subtopic_directions,
                "活动时间": activity.get("activity_time", ""),
                "活动奖励": activity.get("reward", ""),
                "主话题": activity.get("main_topic", ""),
                "活动级别": activity.get("level", ""),
                "Brief链接": source_links,
                "解析状态": parse_status,
                "需人工补充": missing_info,
            },
        )
        bitable_url = ((reminder.get("data") or {}).get("table_url") or self.reminder_service.bitable_url) if reminder.get("ok") else self.reminder_service.bitable_url
        record_id = (reminder.get("data") or {}).get("record_id") or task_id
        reply_lines = [
            "活动已写入多维表格",
            f"标题：{activity['title']}",
            f"记录ID：{record_id}",
            f"平台：{activity['platform']}",
            f"时间：{activity['activity_time'] or '未提取到'}",
            f"主话题：{activity['main_topic'] or '未提取到'}",
            f"参与方式：{activity.get('participation_method') or '未提取到'}",
            f"参与形式：{activity.get('participation_form') or '未提取到'}",
            f"填写要点：{activity.get('filling_points') or '未提取到'}",
            f"解析：{activity.get('source_status') or parse_status}",
            f"待补：{missing_info}" if missing_info else "",
            f"方向：{len(activity['directions'])} 个",
            f"多维表格：{bitable_url}" if bitable_url else "",
        ]
        if activity.get("manual_needed"):
            reply_lines.append("文档正文暂未自动读取到；可以复制活动 Brief 正文后重新发 `【活动】`，我会合并提取并覆盖写入关键字段。")
        reply = "\n".join(line for line in reply_lines if line).strip()
        ok = bool(reminder.get("ok"))
        if not ok and reminder.get("error"):
            reply += f"\n错误：{reminder.get('error')}"
        return TaskResult(ok=ok, status="archived" if ok else "pending_manual", reply=reply, task_id=record_id, local_path="", feishu_doc="", extra=extra)

    def _extract_activity_parent_id(self, text: str) -> str:
        match = re.search(r"(?:父记录ID|父记录|原记录ID|记录ID|record[_ ]?id)\s*[=:：]\s*([A-Za-z0-9_-]{6,64})", text or "", flags=re.IGNORECASE)
        return match.group(1).strip() if match else ""

    def _infer_activity_parent_id(self, message: Message) -> str:
        metadata = message.metadata or {}
        parent_message_ids = {
            str(metadata.get("parent_id") or "").strip(),
            str(metadata.get("root_id") or "").strip(),
        }
        parent_message_ids.discard("")
        context = self._conversation_context(message)
        items = context.get("items") if isinstance(context.get("items"), list) else []
        if parent_message_ids:
            for item in reversed(items):
                if not isinstance(item, dict):
                    continue
                ids = {
                    str(item.get("message_id") or "").strip(),
                    str(item.get("bot_reply_message_id") or "").strip(),
                }
                if parent_message_ids & ids:
                    found = self._extract_activity_record_id_from_text(
                        "\n".join(
                            str(item.get(key) or "")
                            for key in ("bot_reply", "text")
                        )
                    )
                    if found:
                        return found
        for item in reversed(items):
            if not isinstance(item, dict):
                continue
            found = self._extract_activity_record_id_from_text(
                "\n".join(
                    str(item.get(key) or "")
                    for key in ("bot_reply", "text")
                )
            )
            if found:
                return found
        return self._extract_activity_record_id_from_text(self._conversation_context_prompt(message))

    def _extract_activity_record_id_from_text(self, text: str) -> str:
        patterns = (
            r"(?:活动记录ID|父记录ID|记录ID|record[_ ]?id)\s*[=:：]\s*(recv[A-Za-z0-9_-]{6,64})",
            r"\b(recv[A-Za-z0-9_-]{6,64})\b",
        )
        for pattern in patterns:
            match = re.search(pattern, text or "", flags=re.IGNORECASE)
            if match:
                return match.group(1).strip()
        return ""

    def _strip_activity_parent_marker(self, text: str) -> str:
        return re.sub(r"^\s*(?:父记录ID|父记录|原记录ID|记录ID|record[_ ]?id)\s*[=:：]\s*[A-Za-z0-9_-]{6,64}\s*", "", text or "", flags=re.IGNORECASE)

    def _activity_platform_value(self, platform: str) -> list[str]:
        value = str(platform or "").strip()
        return [value] if value else []

    def _mark_unread_external_activity_docs(self, activity: dict[str, Any]) -> None:
        links = activity.get("links") if isinstance(activity.get("links"), list) else []
        unread = []
        for item in links:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip().lower()
            if "doc.weixin.qq.com/" in url or "docs.qq.com/" in url:
                unread.append(str(item.get("label") or "腾讯文档").strip() or "腾讯文档")
        if not unread:
            return
        note = "微信/腾讯文档链接未自动读取，已按消息文本解析"
        status = str(activity.get("source_status") or "").strip()
        activity["source_status"] = f"{status}；{note}" if status else note
        missing = activity.get("missing_info")
        if not isinstance(missing, list):
            missing = []
        missing_note = "微信/腾讯文档链接未读取"
        if missing_note not in missing:
            missing.append(missing_note)
        activity["missing_info"] = missing
        activity["manual_needed"] = True
        if str(activity.get("parse_status") or "已解析").strip() == "已解析":
            activity["parse_status"] = "待人工补充"

    def handle_日程(self, message: Message) -> TaskResult:
        parsed = self.schedule_service.parse(message.body, message.created_at)
        remind_at = self.schedule_service.reminder_at(parsed)
        display_time = format_display_time(parsed.due_at)
        reminder_time = format_display_time(remind_at)
        extra = {
            "due_at": display_time,
            "remind_at": reminder_time,
            "calendar_provider": "feishu",
        }
        sections = [
            ("原始内容", message.raw_text),
            ("解析结果", f"- 目标日期：{parsed.due_at.strftime('%y%m%d')}\n- 日程时间：{display_time}\n- 提醒/出发时间：{reminder_time}\n- 默认时间：{'是' if parsed.used_default_time else '否'}"),
            ("执行状态", "- 飞书日历：待创建\n- 多维表格：待写入")
        ]
        entry = self.archive_service.save_archive(message, f"日程：{parsed.title}", sections, extra)
        reminder = self.reminder_service.add(
            kind="日程",
            title=parsed.title,
            text=message.body,
            due_at=parsed.due_at,
            remind_at=remind_at,
            source=message.source,
            ref_id=entry.frontmatter["id"],
            local_path=entry.local_path,
        )
        fs = {"doc": ""}
        if reminder.get("ok"):
            calendar = (reminder.get("data") or {}).get("calendar") or {}
            extra["feishu_reminder"] = "created"
            suffix = "（默认时间）" if parsed.used_default_time else ""
            if calendar.get("ok"):
                extra["feishu_calendar_event"] = calendar.get("event_id", "")
                table_url = (reminder.get("data") or {}).get("table_url") or self.reminder_service.bitable_url
                reply = f"已创建飞书日历事件\n时间：{display_time}{suffix}\n提醒时间：{reminder_time}\n多维表格：{table_url or '已写入'}\niPhone：飞书日历/提醒会通知"
                if calendar.get("app_link"):
                    reply += f"\n日历链接：{calendar.get('app_link')}"
            else:
                reason = calendar.get("error") or calendar.get("reason") or "unknown"
                table_url = (reminder.get("data") or {}).get("table_url") or self.reminder_service.bitable_url
                reply = f"已写入多维表格\n多维表格：{table_url or '已写入'}\n但飞书日历事件创建失败\n时间：{display_time}{suffix}\n提醒时间：{reminder_time}\n原因：{reason}"
            ok = True
            status = "archived"
        else:
            reply = "日程已本地归档，但飞书日历/提醒写入失败"
            if reminder.get("error"):
                reply += f"\n错误：{reminder.get('error')}"
            ok = False
            status = "pending_manual"
        return TaskResult(ok=ok, status=status, reply=reply, task_id=entry.frontmatter["id"], local_path=entry.local_path, feishu_doc=fs.get("doc", ""), extra=extra)

    def handle_待办(self, message: Message) -> TaskResult:
        parsed = self.schedule_service.parse(message.body, message.created_at)
        remind_at = parsed.due_at - timedelta(minutes=30)
        sections = [
            ("原始内容", message.raw_text),
            (
                "解析结果",
                f"- 截止/事项时间：{format_display_time(parsed.due_at)}\n"
                f"- 提醒时间：{format_display_time(remind_at)}\n"
                f"- 默认时间：{'是' if parsed.used_default_time else '否'}",
            ),
        ]
        entry = self.archive_service.save_archive(
            message,
            f"待办：{parsed.title}",
            sections,
            {
                "due_at": format_display_time(parsed.due_at),
                "remind_at": format_display_time(remind_at),
            },
        )
        reminder = self.reminder_service.add(
            kind="待办",
            title=parsed.title,
            text=message.body,
            due_at=parsed.due_at,
            remind_at=remind_at,
            source=message.source,
            ref_id=entry.frontmatter["id"],
            local_path=entry.local_path,
        )
        fs = {"doc": ""}
        if reminder.get("ok"):
            suffix = "（默认时间）" if parsed.used_default_time else ""
            table_url = (reminder.get("data") or {}).get("table_url") or self.reminder_service.bitable_url
            reply = (
                "已创建飞书待办提醒\n"
                f"事项时间：{format_display_time(parsed.due_at)}{suffix}\n"
                f"提醒时间：{format_display_time(remind_at)}\n"
                f"多维表格：{table_url or '已写入'}\n"
                "iPhone：提前 30 分钟由飞书 Bot 私聊提醒"
            )
            ok = True
            status = "archived"
        else:
            reply = f"待办已本地归档，但飞书提醒写入失败\n本地路径：{entry.local_path}"
            if reminder.get("error"):
                reply += f"\n错误：{reminder.get('error')}"
            ok = False
            status = "pending_manual"
        return TaskResult(ok=ok, status=status, reply=reply, task_id=entry.frontmatter["id"], local_path=entry.local_path, feishu_doc=fs.get("doc", ""))

    def _activity_from_ai_clean(self, body: str, clean: dict[str, Any]) -> dict[str, Any]:
        links = []
        for item in clean.get("source_links") or []:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            if not url:
                continue
            links.append({"label": str(item.get("label") or "来源链接").strip() or "来源链接", "url": url})
        directions = [str(item).strip() for item in clean.get("subtopic_directions") or [] if str(item).strip()]
        missing_info = [str(item).strip() for item in clean.get("missing_info") or [] if str(item).strip()]
        first_line = next((line.strip().lstrip("#📢 ").strip() for line in body.splitlines() if line.strip()), "")
        return {
            "title": str(clean.get("title") or first_line or "未命名活动").strip(),
            "platform": str(clean.get("platform") or "未识别").strip(),
            "level": str(clean.get("activity_level") or "").strip(),
            "main_topic": str(clean.get("main_topic") or "").strip(),
            "activity_time": str(clean.get("activity_time") or "").strip(),
            "reward": str(clean.get("reward") or "").strip(),
            "directions": directions,
            "links": links,
            "brief_summary": str(clean.get("brief_summary") or "").strip(),
            "participation_method": str(clean.get("participation_method") or "").strip(),
            "participation_form": str(clean.get("participation_form") or "").strip(),
            "filling_points": str(clean.get("filling_points") or "").strip(),
            "submission_requirements": str(clean.get("submission_requirements") or "").strip(),
            "status": str(clean.get("activity_status") or "待判断").strip() or "待判断",
            "parse_status": str(clean.get("parse_status") or "已解析").strip() or "已解析",
            "source_status": f"AI清洗完成：{clean.get('postprocess_provider') or 'provider'}",
            "manual_needed": str(clean.get("parse_status") or "") == "待人工补充",
            "missing_info": missing_info,
        }

    def _extract_activity(self, body: str, brief: dict[str, Any] | None = None) -> dict[str, Any]:
        brief = brief or {}
        fields = brief.get("fields") if isinstance(brief.get("fields"), dict) else {}
        lines = [line.strip() for line in body.splitlines() if line.strip()]
        title = str(fields.get("title") or (lines[0].lstrip("#📢 ").strip() if lines else "未命名活动")).strip()
        platform = str(fields.get("platform") or "").strip()
        if not platform or platform == "未识别":
            platform = "小红书" if "小红书" in body else "未识别"
        level_match = re.search(r"([A-Z]{1,3})级", body)
        main_topic_match = re.search(r"(#[\w\u4e00-\u9fff]+)", body)
        activity_time = str(fields.get("activity_time") or self._extract_labeled_text(body, "活动时间")).strip()
        reward = str(fields.get("reward") or self._extract_labeled_text(body, "活动奖励")).strip()
        links = []
        seen_urls: set[str] = set()
        for label, url in re.findall(r"([^：:\n]*?)[:：]\s*(https?://\S+)", body):
            clean_url = url.strip().rstrip("，。；、.）)]】")
            if clean_url in seen_urls:
                continue
            seen_urls.add(clean_url)
            links.append({"label": label.strip("🔗🧩 ") or "链接", "url": clean_url})
        for item in fields.get("source_links") or []:
            if not isinstance(item, dict):
                continue
            clean_url = str(item.get("url") or "").strip()
            if not clean_url or clean_url in seen_urls:
                continue
            seen_urls.add(clean_url)
            links.append({"label": str(item.get("label") or "来源链接"), "url": clean_url})
        directions = []
        for line in lines:
            if not line.startswith("#"):
                continue
            topic, _, desc = line.partition("：")
            directions.append(f"{topic.strip()}：{desc.strip()}" if desc else topic.strip())
        for item in fields.get("directions") or []:
            if isinstance(item, str) and item.strip() and item.strip() not in directions:
                directions.append(item.strip())
        return {
            "title": title,
            "platform": platform,
            "level": str(fields.get("level") or (level_match.group(1) if level_match else "")),
            "main_topic": str(fields.get("main_topic") or (main_topic_match.group(1) if main_topic_match else "")),
            "activity_time": activity_time,
            "reward": reward,
            "directions": directions,
            "links": links,
            "brief_summary": str(fields.get("brief_summary") or "").strip(),
            "participation_method": str(fields.get("participation_method") or "").strip(),
            "participation_form": str(fields.get("participation_form") or "").strip(),
            "filling_points": str(fields.get("filling_points") or "").strip(),
            "submission_requirements": str(fields.get("submission_requirements") or "").strip(),
            "source_status": str(fields.get("source_status") or brief.get("source_status") or "").strip(),
            "manual_needed": bool(fields.get("manual_needed") or brief.get("manual_needed")),
            "missing_info": fields.get("missing_info") if isinstance(fields.get("missing_info"), list) else [],
        }

    def _format_activity_record(self, activity: dict[str, Any], raw_body: str) -> str:
        lines = [
            self._format_activity_summary(activity),
            "",
            "活动 Brief：",
            activity.get("brief_summary") or "未提取到",
            "",
            "参与方式：",
            activity.get("participation_method") or "未提取到",
            "",
            "参与形式：",
            activity.get("participation_form") or "未提取到",
            "",
            "填写要点：",
            activity.get("filling_points") or "未提取到",
            "",
            "提交要求：",
            activity.get("submission_requirements") or "未提取到",
            "",
            "创作方向：",
            "\n".join(f"- {item}" for item in activity["directions"]) or "未提取到",
            "",
            "链接：",
            "\n".join(f"- {item['label']}：{item['url']}" for item in activity["links"]) or "未提取到",
            "",
            "解析状态：",
            activity.get("source_status") or "未记录",
            "",
            "待人工补充：",
            "、".join(activity.get("missing_info") or []) or "无",
            "",
            "原始内容：",
            raw_body.strip(),
        ]
        return "\n".join(lines).strip()

    def _format_activity_summary(self, activity: dict[str, Any]) -> str:
        return "\n".join(
            line
            for line in [
                f"- 标题：{activity['title']}",
                f"- 平台：{activity['platform']}",
                f"- 活动级别：{activity['level']}" if activity.get("level") else "",
                f"- 主话题：{activity['main_topic']}" if activity.get("main_topic") else "",
                f"- 活动时间：{activity['activity_time']}" if activity.get("activity_time") else "",
                f"- 活动奖励：{activity['reward']}" if activity.get("reward") else "",
            ]
            if line
        )
