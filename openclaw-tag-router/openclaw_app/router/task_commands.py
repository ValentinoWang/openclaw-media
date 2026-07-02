from __future__ import annotations

from .tag_router_common import *


class TaskCommandMixin:
    ACTIVE_ARCHIVE_TAGS = {"待办", "日程", "待办-开发"}
    DONE_STATUSES = {"已完成", "已取消"}

    def handle_今日(self, message: Message) -> TaskResult:
        today = message.created_at.date()
        entries = self._active_task_entries(today=today)
        lines = ["今日执行清单"]
        reminder_lines = self._format_task_bucket(entries, {"待办", "日程"}, limit=7)
        development_lines = self._format_task_bucket(entries, {"待办-开发"}, limit=7)
        lines.append("")
        lines.append("提醒/日程/待办：")
        lines.extend(reminder_lines or ["- 暂无本地待处理项"])
        lines.append("")
        lines.append("开发：")
        lines.extend(development_lines or ["- 暂无本地待处理开发需求"])
        lines.append("")
        lines.append("说明：这里读取本地归档生成清单；飞书多维表格仍是后台库。")
        content = "\n".join(lines)
        entry = self.archive_service.save_archive(message, "今日执行清单", [("清单", content)])
        return TaskResult(ok=True, status="archived", reply=content, task_id=entry.frontmatter["id"], local_path=entry.local_path)

    def handle_开发_完成(self, message: Message) -> TaskResult:
        return self._handle_task_status_update(message, status="已完成", archive_tags={"待办-开发"}, updates={"dev_status": "已完成"})

    def handle_开发_验证(self, message: Message) -> TaskResult:
        return self._handle_task_status_update(message, status="待验证", archive_tags={"待办-开发"}, updates={"dev_status": "待验证"})

    def _active_task_entries(self, *, today) -> list[Any]:
        entries = []
        for tag in self.ACTIVE_ARCHIVE_TAGS:
            entries.extend(self.archive_service.list_archives(limit=80, tag=tag))
        active = []
        for entry in entries:
            frontmatter = entry.frontmatter or {}
            status = str(frontmatter.get("status") or "").strip()
            dev_status = str(frontmatter.get("dev_status") or "").strip()
            if status in self.DONE_STATUSES or dev_status in self.DONE_STATUSES:
                continue
            due_at = str(frontmatter.get("due_at") or "").strip()
            if entry.frontmatter.get("entry_tag") == "待办-开发":
                active.append(entry)
                continue
            if not due_at or self._task_date_is_today_or_overdue(due_at, today):
                active.append(entry)
        return sorted(active, key=lambda entry: self._task_sort_key(entry, today))

    def _format_task_bucket(self, entries: list[Any], tags: set[str], *, limit: int) -> list[str]:
        lines = []
        for entry in entries:
            tag = str(entry.frontmatter.get("entry_tag") or "")
            if tag not in tags:
                continue
            title = self._entry_display_title(entry)
            due_at = str(entry.frontmatter.get("due_at") or "").strip()
            status = str(entry.frontmatter.get("dev_status") or entry.frontmatter.get("status") or "待处理").strip()
            task_id = str(entry.frontmatter.get("id") or entry.local_path).strip()
            suffix = f"｜{due_at}" if due_at else ""
            lines.append(f"- [{tag}] {title}{suffix}｜{status}｜{task_id}")
            if len(lines) >= limit:
                break
        return lines

    def _handle_task_status_update(
        self,
        message: Message,
        *,
        status: str,
        archive_tags: set[str],
        updates: dict[str, Any] | None = None,
        note: str = "",
    ) -> TaskResult:
        query = self._status_query(message.body)
        target = self._find_task_entry(query, archive_tags)
        if target is None:
            reply = f"未找到匹配任务：{query or '空查询'}\n请使用任务ID，或发送 `【今日】` 查看可操作任务。"
            entry = self.archive_service.save_archive(message, f"任务状态更新失败：{status}", [("结果", reply)])
            return TaskResult(ok=False, status="not_found", reply=reply, task_id=entry.frontmatter["id"], local_path=entry.local_path)
        target_updates = {"status": status, "updated_at": format_display_time(message.created_at)}
        if updates:
            target_updates.update(updates)
        if target.frontmatter.get("entry_tag") == "待办-开发" and "dev_status" not in target_updates:
            target_updates["dev_status"] = status
        updated = self.archive_service.update_frontmatter(target.local_path, target_updates)
        title = self._entry_display_title(updated)
        content = "\n".join(
            item
            for item in [
                f"任务：{title}",
                f"任务ID：{updated.frontmatter.get('id', '')}",
                f"状态：{status}",
                note,
                f"本地路径：{updated.local_path}",
                "说明：已更新本地归档；当前未直接修改飞书多维表格。",
            ]
            if item
        )
        command_entry = self.archive_service.save_archive(message, f"任务状态更新：{title}", [("结果", content)])
        return TaskResult(ok=True, status="updated", reply=content, task_id=updated.frontmatter.get("id", ""), local_path=updated.local_path, extra={"command_path": command_entry.local_path})

    def _status_query(self, body: str) -> str:
        text = re.sub(r"\s+", " ", str(body or "")).strip()
        text = re.sub(r"^(开发-完成|开发-验证)\s*", "", text).strip()
        return text

    def _find_task_entry(self, query: str, archive_tags: set[str]) -> Any | None:
        query = str(query or "").strip()
        if not query:
            return None
        candidates = []
        for tag in archive_tags:
            candidates.extend(self.archive_service.list_archives(limit=120, tag=tag))
        for entry in candidates:
            if query == str(entry.frontmatter.get("id") or "") or query == str(entry.local_path):
                return entry
        q = query.lower()
        matches = []
        for entry in candidates:
            haystack = "\n".join([self._entry_display_title(entry), entry.local_path, *(body for _, body in entry.sections)]).lower()
            score = 0
            if q in haystack:
                score += 10
            score += sum(1 for token in re.split(r"\s+", q) if token and token in haystack)
            if score > 0:
                matches.append((score, entry))
        if not matches:
            return None
        matches.sort(key=lambda item: (item[0], str(item[1].frontmatter.get("created_at") or "")), reverse=True)
        return matches[0][1]

    def _entry_display_title(self, entry: Any) -> str:
        title = str(entry.title or "").strip()
        title = re.sub(r"^(待办|日程|待办-开发)：", "", title).strip()
        return title or str(entry.frontmatter.get("id") or "未命名任务")

    def _task_date_is_today_or_overdue(self, due_at: str, today) -> bool:
        match = re.search(r"(\d{2})(\d{2})(\d{2})", due_at)
        if not match:
            return True
        year = 2000 + int(match.group(1))
        month = int(match.group(2))
        day = int(match.group(3))
        try:
            return datetime(year, month, day).date() <= today
        except ValueError:
            return True

    def _task_sort_key(self, entry: Any, today) -> tuple[int, str, str]:
        due_at = str(entry.frontmatter.get("due_at") or "").strip()
        match = re.search(r"(\d{2})(\d{2})(\d{2})", due_at)
        if not match:
            return (9999, "999999", str(entry.frontmatter.get("created_at") or ""))
        try:
            item_date = datetime(2000 + int(match.group(1)), int(match.group(2)), int(match.group(3))).date()
        except ValueError:
            return (9999, "999999", str(entry.frontmatter.get("created_at") or ""))
        distance = abs((item_date - today).days)
        return (distance, due_at, str(entry.frontmatter.get("created_at") or ""))
