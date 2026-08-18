from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .daily_journal_contract import (
    DAILY_JOURNAL_ARRANGEMENT_PROMPT,
    DAILY_JOURNAL_FIELD_BY_ID,
    DAILY_JOURNAL_FIELD_BY_TITLE,
    DAILY_JOURNAL_FIELDS,
    DAILY_JOURNAL_LLM_PROFILE,
    DAILY_JOURNAL_RECORD_KIND,
    DAILY_JOURNAL_TEMPLATE,
    WEEKLY_DYNAMIC_TOPIC_CLUSTERS,
    WEEKLY_FIXED_SECTIONS,
    WEEKLY_SELF_MODEL_LLM_PROFILE,
    WEEKLY_SELF_MODEL_RECORD_KIND,
    WEEKLY_SELF_MODEL_SUMMARY_PROMPT,
    daily_journal_config,
    field_ids,
    journal_path,
    parse_compact_date,
    sample_status,
    week_bounds_for,
    week_key,
    weekly_summary_path,
)
from .tag_router_common import *


DAILY_JOURNAL_URL_RE = re.compile(r"https?://[^\s<>()\[\]{}\"'，。；、]+")


class WeeklySelfModelMixin:
    def handle_日记(self, message: Message) -> TaskResult:
        if not self._daily_journal_has_content(message.body):
            reply = "\n".join(
                [
                    "日记正文为空，未写入。",
                    "",
                    "可以按下面模板填写：",
                    DAILY_JOURNAL_TEMPLATE,
                ]
            )
            return TaskResult(ok=False, status="missing_content", reply=reply, task_id="", extra={"template": DAILY_JOURNAL_TEMPLATE})

        arranged = self._arrange_daily_journal(message)
        if arranged.get("status") != "done":
            reason = str(arranged.get("reason") or "日记整理失败，需要人工补充。").strip()
            return TaskResult(ok=False, status="pending_manual", reply=f"日记未写入：{reason}", task_id="", extra={"arrangement": arranged})

        sections = self._normalize_daily_journal_sections(arranged)
        if not any(value.strip() for value in sections.values()):
            return TaskResult(
                ok=False,
                status="missing_content",
                reply="日记正文没有可保存内容，未写入。",
                task_id="",
                extra={"arrangement": arranged},
            )
        arranged_text = self._coerce_section_text(arranged.get("arranged_text") or arranged.get("summary"))
        if not arranged_text:
            return TaskResult(
                ok=False,
                status="pending_manual",
                reply="日记未写入：LLM 未返回整理后总结。",
                task_id="",
                extra={"arrangement": arranged},
            )
        arranged_text = self._ensure_daily_journal_links(message.body, arranged_text)
        weekly_projection = self._normalize_daily_journal_weekly_projection(arranged)
        if not weekly_projection.get("title") or not weekly_projection.get("summary"):
            return TaskResult(
                ok=False,
                status="pending_manual",
                reply="日记未写入：LLM 未返回可写入周归档的 weekly_projection.title / weekly_projection.summary。",
                task_id="",
                extra={"arrangement": arranged},
            )

        entry_id = self._daily_journal_entry_id(message)
        day = message.created_at.astimezone(ZoneInfo(self.timezone)).date()
        path = journal_path(self._daily_journal_root(), day)
        block = self._render_daily_journal_entry_block(message, entry_id, sections, arranged_text, weekly_projection, arranged)
        self._write_managed_block(
            path,
            "openclaw-daily-journal",
            entry_id,
            block,
            file_header=f"# {day.isoformat()} 日记\n\n",
        )
        weekly_path = self._write_daily_journal_weekly_projection(day)

        filled_titles = [DAILY_JOURNAL_FIELD_BY_ID[field_id].title for field_id, value in sections.items() if value.strip()]
        reply_lines = [
            "日记已保存",
            f"状态：written",
            f"任务ID：{entry_id}",
            f"文件：{path}",
            f"周归档：{weekly_path}",
        ]
        if filled_titles:
            reply_lines.append("已记录：" + "、".join(filled_titles[:8]))
            if len(filled_titles) > 8:
                reply_lines.append(f"另有 {len(filled_titles) - 8} 个字段。")
        return TaskResult(
            ok=True,
            status="written",
            reply="\n".join(reply_lines),
            task_id=entry_id,
            local_path=str(path),
            extra={
                "record_kind": DAILY_JOURNAL_RECORD_KIND,
                "journal_path": str(path),
                "weekly_archive_path": str(weekly_path),
                "sections": sections,
                "arranged_text": arranged_text,
                "weekly_projection": weekly_projection,
                "arrangement_mode": arranged.get("arrangement_mode", ""),
            },
        )

    def handle_周记(self, message: Message) -> TaskResult:
        ranges, error = self._weekly_self_model_ranges(message)
        if error:
            return TaskResult(ok=False, status="invalid_range", reply=error, task_id="")

        results = [self._build_weekly_self_model_summary(start, end) for start, end in ranges]
        pending = next((item for item in results if item["status"] == "pending_manual"), None)
        if pending:
            return TaskResult(
                ok=False,
                status="pending_manual",
                reply=f"周记未写入：{pending['reason']}",
                task_id=pending["week"],
                local_path=pending.get("path", ""),
                extra={"summaries": results},
            )

        if len(results) == 1:
            status = results[0]["status"]
            task_id = results[0]["week"]
            local_path = results[0]["path"]
        else:
            status = "written" if any(item["status"] == "written" for item in results) else results[-1]["status"]
            task_id = ",".join(item["week"] for item in results)
            local_path = results[-1]["path"]

        reply_lines = []
        for item in results:
            if item["status"] == "written":
                title = "周记已生成"
            elif item["status"] == "insufficient":
                title = "周记样本不足，已写入索引"
            else:
                title = "周记样本为空，已写入空状态"
            reply_lines.extend(
                [
                    title,
                    f"周：{item['week']}",
                    f"状态：{item['status']}",
                    f"日记样本：{item['sample_count']} 篇",
                    f"文件：{item['path']}",
                    "",
                ]
            )
        return TaskResult(
            ok=True,
            status=status,
            reply="\n".join(reply_lines).strip(),
            task_id=task_id,
            local_path=local_path,
            extra={"record_kind": WEEKLY_SELF_MODEL_RECORD_KIND, "summaries": results},
        )

    def daily_journal_scheduled_prompt(self) -> str:
        return DAILY_JOURNAL_TEMPLATE

    def _daily_journal_config(self) -> dict[str, Any]:
        return daily_journal_config(getattr(self, "daily_journal_settings", {}) or {})

    def _daily_journal_root(self) -> Path:
        return Path(str(self._daily_journal_config()["journal_root"]))

    def _weekly_self_model_archive_root(self) -> Path:
        return Path(str(self._daily_journal_config()["weekly_archive_root"]))

    @staticmethod
    def _daily_journal_has_content(body: str) -> bool:
        text = str(body or "").strip()
        if not text:
            return False
        values = WeeklySelfModelMixin._parse_daily_journal_template_fields(text)
        if any(value.strip() for value in values.values()):
            return True
        cleaned = text
        for field in DAILY_JOURNAL_FIELDS:
            cleaned = cleaned.replace(field.prompt, "").replace(f"{field.title}：", "").replace(f"{field.title}:", "")
        return bool(cleaned.strip())

    def _arrange_daily_journal(self, message: Message) -> dict[str, Any]:
        explicit_sections = self._parse_daily_journal_template_fields(message.body)
        if not getattr(self, "content_flow_client", None) or not hasattr(self.content_flow_client, "_call_profile_provider_json"):
            return {"status": "pending_manual", "reason": "缺少可用 LLM 日记整理器"}
        user_content = json.dumps(
            {
                "created_at": message.created_at.isoformat(timespec="seconds"),
                "timezone": self.timezone,
                "raw_text": message.body,
                "template_fields": {field_id: value for field_id, value in explicit_sections.items() if value.strip()},
                "field_ids": list(field_ids()),
            },
            ensure_ascii=False,
        )
        payload = self.content_flow_client._call_profile_provider_json(
            DAILY_JOURNAL_LLM_PROFILE,
            DAILY_JOURNAL_ARRANGEMENT_PROMPT,
            user_content,
            "Daily 日记整理",
        )
        if payload.get("status") == "done":
            payload["arrangement_mode"] = "llm"
        return payload

    @staticmethod
    def _parse_daily_journal_template_fields(text: str) -> dict[str, str]:
        sections: dict[str, list[str]] = {field.field_id: [] for field in DAILY_JOURNAL_FIELDS}
        title_to_id = {field.title: field.field_id for field in DAILY_JOURNAL_FIELDS}
        current_id = ""
        field_pattern = re.compile(r"^(?P<title>.+?)\s*[:：]\s*(?P<value>.*)$")
        for raw_line in str(text or "").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            match = field_pattern.match(line)
            if match and match.group("title").strip() in title_to_id:
                current_id = title_to_id[match.group("title").strip()]
                value = match.group("value").strip()
                if value:
                    sections[current_id].append(value)
                continue
            if current_id:
                sections[current_id].append(line)
        return {field_id: "\n".join(parts).strip() for field_id, parts in sections.items()}

    @staticmethod
    def _normalize_daily_journal_sections(payload: dict[str, Any]) -> dict[str, str]:
        raw_sections = payload.get("sections") if isinstance(payload.get("sections"), dict) else payload
        normalized: dict[str, str] = {}
        for field in DAILY_JOURNAL_FIELDS:
            value = ""
            if isinstance(raw_sections, dict):
                value = WeeklySelfModelMixin._coerce_section_text(
                    raw_sections.get(field.field_id)
                    or raw_sections.get(field.title)
                    or payload.get(field.field_id)
                    or payload.get(field.title)
                )
            normalized[field.field_id] = value
        return normalized

    @staticmethod
    def _coerce_section_text(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, list):
            return "\n".join(str(item).strip() for item in value if str(item or "").strip()).strip()
        if isinstance(value, dict):
            return json.dumps(value, ensure_ascii=False, sort_keys=True)
        return str(value).strip()

    @staticmethod
    def _daily_journal_entry_id(message: Message) -> str:
        seed = "|".join([message.created_at.isoformat(timespec="seconds"), message.source, message.entry_tag, message.raw_text])
        digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:10]
        return f"{message.created_at.strftime('%Y%m%d-%H%M%S')}-{message.source}-日记-{digest}"

    def _render_daily_journal_entry_block(
        self,
        message: Message,
        entry_id: str,
        sections: dict[str, str],
        arranged_text: str,
        weekly_projection: dict[str, str],
        payload: dict[str, Any],
    ) -> str:
        created = message.created_at.astimezone(ZoneInfo(self.timezone))
        data = {
            "record_kind": DAILY_JOURNAL_RECORD_KIND,
            "entry_id": entry_id,
            "created_at": created.isoformat(timespec="seconds"),
            "source": message.source,
            "arranged_text": arranged_text.strip(),
            "weekly_projection": weekly_projection,
            "sections": {field_id: value for field_id, value in sections.items() if value.strip()},
            "raw_text": message.body.strip(),
            "arrangement_mode": payload.get("arrangement_mode", ""),
        }
        comment_json = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("--", "\\u002d\\u002d")
        lines = [
            f"<!-- openclaw-daily-journal:{entry_id}:start -->",
            f"## {created.strftime('%H:%M')} 日记",
            "",
            f"<!-- openclaw-daily-journal-data:{comment_json} -->",
            "",
            "### 整理后内容",
            arranged_text.strip(),
            "",
            "### 原文",
            self._fenced_text(message.body),
        ]
        lines.extend(["", f"<!-- openclaw-daily-journal:{entry_id}:end -->", ""])
        return "\n".join(lines)

    @staticmethod
    def _daily_journal_explicit_urls(text: str) -> list[str]:
        urls: list[str] = []
        for match in DAILY_JOURNAL_URL_RE.finditer(str(text or "")):
            url = match.group(0).rstrip(".,;:!?，。；、）)]】》")
            if url and url not in urls:
                urls.append(url)
        return urls

    @classmethod
    def _ensure_daily_journal_links(cls, raw_text: str, arranged_text: str) -> str:
        arranged = str(arranged_text or "").strip()
        missing = [url for url in cls._daily_journal_explicit_urls(raw_text) if url not in arranged]
        if not missing:
            return arranged
        return arranged.rstrip() + "\n\n相关链接：" + "；".join(missing)

    @staticmethod
    def _normalize_daily_journal_weekly_projection(payload: dict[str, Any]) -> dict[str, str]:
        raw_projection = payload.get("weekly_projection") if isinstance(payload.get("weekly_projection"), dict) else {}
        title = WeeklySelfModelMixin._sanitize_daily_journal_projection_title(raw_projection.get("title"))
        summary = WeeklySelfModelMixin._coerce_section_text(raw_projection.get("summary"))
        summary = re.sub(r"\n{3,}", "\n\n", summary).strip()
        return {"title": title, "summary": summary}

    @staticmethod
    def _sanitize_daily_journal_projection_title(value: Any) -> str:
        title = WeeklySelfModelMixin._coerce_section_text(value)
        title = re.sub(r"[\r\n]+", " ", title).strip()
        title = re.sub(r"^#+\s*", "", title).strip()
        title = re.sub(r"\s+", " ", title)
        return title[:80].strip()

    @staticmethod
    def _daily_journal_projection_sentence_count(text: str) -> int:
        compact = str(text or "").strip()
        if not compact:
            return 0
        parts = [part for part in re.split(r"[。！？!?]+", compact) if part.strip()]
        return len(parts) or 1

    def _write_daily_journal_weekly_projection(self, day: date) -> Path:
        start, end = week_bounds_for(datetime.combine(day, datetime.min.time(), tzinfo=ZoneInfo(self.timezone)), self.timezone)
        path = weekly_summary_path(self._weekly_self_model_archive_root(), start, end)
        daily_path = journal_path(self._daily_journal_root(), day)
        entries = []
        if daily_path.exists():
            entries = [
                entry
                for entry in self._read_daily_journal_entries(daily_path, day)
                if (entry.get("weekly_projection") or {}).get("title") and (entry.get("weekly_projection") or {}).get("summary")
            ]
        block = self._render_daily_journal_weekly_projection_section(day, entries)
        self._upsert_daily_journal_weekly_projection_block(path, day, block, file_header=f"# {week_key(start, end)} 周记\n\n")
        return path

    def _render_daily_journal_weekly_projection_section(self, day: date, entries: list[dict[str, Any]]) -> str:
        lines = ["## 日记", ""]
        for entry in entries:
            projection = self._normalize_daily_journal_weekly_projection({"weekly_projection": entry.get("weekly_projection")})
            title = projection.get("title", "")
            summary = projection.get("summary", "")
            if not title or not summary:
                continue
            lines.extend([f"### {title}", "", summary, ""])
            urls = self._daily_journal_explicit_urls(str(entry.get("raw_text") or entry.get("arranged_text") or ""))
            if urls:
                lines.extend(["相关链接：" + "；".join(urls), ""])
            link_target = f"../{self._daily_journal_root().name}/{day.isoformat()}.md"
            lines.extend([f"日记链接：[{day.isoformat()} 日记]({link_target})", ""])
        return "\n".join(lines).rstrip()

    @staticmethod
    def _upsert_daily_journal_weekly_projection_block(path: Path, day: date, block: str, file_header: str = "") -> None:
        ensure_dir(path.parent)
        existing = path.read_text(encoding="utf-8") if path.exists() else file_header
        date_heading = day.strftime("%Y%m%d")
        block_text = block.rstrip() + "\n"
        date_pattern = re.compile(rf"^#\s+{re.escape(date_heading)}\s*$", flags=re.MULTILINE)
        date_match = date_pattern.search(existing)
        if not date_match:
            base = existing.rstrip()
            date_section = f"# {date_heading}\n\n{block_text}"
            updated = base + "\n\n" + date_section if base.strip() else date_section
            path.write_text(updated.rstrip() + "\n", encoding="utf-8")
            return

        next_date_match = re.search(r"^#\s+.+$", existing[date_match.end() :], flags=re.MULTILINE)
        date_end = date_match.end() + next_date_match.start() if next_date_match else len(existing)
        date_section = existing[date_match.start() : date_end]
        journal_pattern = re.compile(r"^##\s+日记\s*$", flags=re.MULTILINE)
        journal_match = journal_pattern.search(date_section)
        if journal_match:
            next_section_match = re.search(r"^##\s+.+$", date_section[journal_match.end() :], flags=re.MULTILINE)
            journal_end = journal_match.end() + next_section_match.start() if next_section_match else len(date_section)
            new_date_section = date_section[: journal_match.start()].rstrip() + "\n\n" + block_text + "\n" + date_section[journal_end:].lstrip("\n")
        else:
            heading_line_end = date_section.find("\n")
            if heading_line_end < 0:
                heading_line_end = len(date_section)
            new_date_section = date_section[:heading_line_end].rstrip() + "\n\n" + block_text + "\n" + date_section[heading_line_end:].lstrip("\n")

        updated = existing[: date_match.start()] + new_date_section.rstrip() + "\n" + existing[date_end:].lstrip("\n")
        path.write_text(updated.rstrip() + "\n", encoding="utf-8")

    @staticmethod
    def _fenced_text(text: str) -> str:
        fence = "````" if "```" in str(text or "") else "```"
        return f"{fence}text\n{text.strip()}\n{fence}"

    @staticmethod
    def _write_managed_block(path: Path, marker_prefix: str, marker_id: str, block: str, file_header: str = "") -> None:
        ensure_dir(path.parent)
        if path.exists():
            existing = path.read_text(encoding="utf-8")
        else:
            existing = file_header
        pattern = re.compile(
            rf"<!--\s*{re.escape(marker_prefix)}:{re.escape(marker_id)}:start\s*-->[\s\S]*?<!--\s*{re.escape(marker_prefix)}:{re.escape(marker_id)}:end\s*-->\n*",
            flags=re.MULTILINE,
        )
        block_text = block.rstrip() + "\n"
        if pattern.search(existing):
            updated = pattern.sub(lambda _match: block_text, existing)
        else:
            updated = existing.rstrip() + "\n\n" + block_text if existing.strip() else file_header.rstrip() + "\n\n" + block_text
        path.write_text(updated.rstrip() + "\n", encoding="utf-8")

    @staticmethod
    def _write_weekly_self_model_block(path: Path, week: str, block: str, file_header: str = "") -> None:
        ensure_dir(path.parent)
        if path.exists():
            existing = path.read_text(encoding="utf-8")
        else:
            existing = file_header
        marker_pattern = re.compile(
            rf"<!--\s*openclaw-weekly-self-model:{re.escape(week)}:start\s*-->[\s\S]*?<!--\s*openclaw-weekly-self-model:{re.escape(week)}:end\s*-->\n*",
            flags=re.MULTILINE,
        )
        without_old_block = marker_pattern.sub("", existing).rstrip()
        block_text = block.rstrip() + "\n"
        dev_match = re.search(r"^# 开发\s*$", without_old_block, flags=re.MULTILINE)
        if dev_match:
            updated = without_old_block[: dev_match.start()].rstrip() + "\n\n" + block_text + "\n" + without_old_block[dev_match.start() :].lstrip("\n")
        else:
            updated = without_old_block + "\n\n" + block_text if without_old_block.strip() else file_header.rstrip() + "\n\n" + block_text
        path.write_text(updated.rstrip() + "\n", encoding="utf-8")

    def _weekly_self_model_ranges(self, message: Message) -> tuple[list[tuple[date, date]], str]:
        text = str(message.body or "").strip()
        current_start, current_end = week_bounds_for(message.created_at, self.timezone)
        explicit = re.search(r"(20\d{6})\s*(?:-|—|~|至|到)\s*(20\d{6})", text)
        if explicit:
            start = parse_compact_date(explicit.group(1))
            end = parse_compact_date(explicit.group(2))
            if not start or not end or end < start:
                return [], "周记范围格式不正确。请使用 `【周记】20260525-20260531`。"
            return [(start, end)], ""

        recent = re.search(r"最近\s*(\d{1,2})\s*周", text)
        if recent:
            count = max(1, min(8, int(recent.group(1))))
            ranges = []
            end = current_end
            for _ in range(count):
                start = end - timedelta(days=6)
                ranges.append((start, end))
                end = start - timedelta(days=1)
            return list(reversed(ranges)), ""

        return [(current_start, current_end)], ""

    def _build_weekly_self_model_summary(self, start: date, end: date) -> dict[str, Any]:
        week = week_key(start, end)
        entries = self._weekly_self_model_journal_entries(start, end)
        config = self._daily_journal_config()
        sample_state = sample_status(len(entries), int(config["minimum_weekly_samples"]))
        path = weekly_summary_path(self._weekly_self_model_archive_root(), start, end)

        if sample_state in {"empty", "insufficient"}:
            block = self._render_weekly_self_model_summary_block(
                week=week,
                status=sample_state,
                sample_count=len(entries),
                entries=entries,
                fixed_sections={},
                dynamic_clusters=[],
                reason="样本不足 3 篇，未生成重复模式、人格判断或稳定结论。" if sample_state == "insufficient" else "本周没有日记样本。",
            )
            self._write_weekly_self_model_block(path, week, block, file_header=f"# {week} 周记\n\n")
            return {"week": week, "status": sample_state, "sample_count": len(entries), "path": str(path), "topics": []}

        payload = self._call_weekly_self_model_llm(start, end, entries)
        if payload.get("status") != "done":
            return {
                "week": week,
                "status": "pending_manual",
                "sample_count": len(entries),
                "path": str(path),
                "reason": str(payload.get("reason") or "周记 LLM 总结失败，需要人工复核。"),
            }

        fixed_sections, dynamic_clusters = self._normalize_weekly_self_model_payload(payload)
        block = self._render_weekly_self_model_summary_block(
            week=week,
            status="written",
            sample_count=len(entries),
            entries=entries,
            fixed_sections=fixed_sections,
            dynamic_clusters=dynamic_clusters,
            reason="",
        )
        self._write_weekly_self_model_block(path, week, block, file_header=f"# {week} 周记\n\n")
        return {
            "week": week,
            "status": "written",
            "sample_count": len(entries),
            "path": str(path),
            "topics": [cluster.get("topic", "") for cluster in dynamic_clusters if cluster.get("topic")],
        }

    def _weekly_self_model_journal_entries(self, start: date, end: date) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        current = start
        root = self._daily_journal_root()
        while current <= end:
            path = journal_path(root, current)
            if path.exists():
                entries.extend(self._read_daily_journal_entries(path, current))
            current += timedelta(days=1)
        return sorted(entries, key=lambda item: str(item.get("created_at") or item.get("date") or ""))

    def _read_daily_journal_entries(self, path: Path, day: date) -> list[dict[str, Any]]:
        text = path.read_text(encoding="utf-8")
        pattern = re.compile(
            r"<!--\s*openclaw-daily-journal:(?P<entry_id>[^:]+):start\s*-->(?P<body>[\s\S]*?)<!--\s*openclaw-daily-journal:(?P=entry_id):end\s*-->",
            flags=re.MULTILINE,
        )
        entries: list[dict[str, Any]] = []
        for match in pattern.finditer(text):
            body = match.group("body")
            data = self._daily_journal_data_from_block(body)
            sections = self._normalize_daily_journal_sections(data) if data else self._daily_journal_sections_from_markdown(body)
            entries.append(
                {
                    "entry_id": data.get("entry_id") or match.group("entry_id") if data else match.group("entry_id"),
                    "date": day.isoformat(),
                    "created_at": data.get("created_at") if data else day.isoformat(),
                    "path": str(path),
                    "arranged_text": data.get("arranged_text") if data else "",
                    "weekly_projection": data.get("weekly_projection") if isinstance(data.get("weekly_projection"), dict) else {},
                    "raw_text": data.get("raw_text") if data else "",
                    "sections": {field_id: value for field_id, value in sections.items() if value.strip()},
                }
            )
        if not entries:
            sections = self._daily_journal_sections_from_markdown(text)
            if any(value.strip() for value in sections.values()):
                entries.append({"entry_id": f"{day.isoformat()}-manual", "date": day.isoformat(), "created_at": day.isoformat(), "path": str(path), "sections": sections})
        return entries

    @staticmethod
    def _daily_journal_data_from_block(block: str) -> dict[str, Any]:
        match = re.search(r"<!--\s*openclaw-daily-journal-data:(?P<data>[\s\S]*?)\s*-->", block)
        if not match:
            return {}
        try:
            data = json.loads(match.group("data"))
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _daily_journal_sections_from_markdown(text: str) -> dict[str, str]:
        sections: dict[str, str] = {field.field_id: "" for field in DAILY_JOURNAL_FIELDS}
        for line in str(text or "").splitlines():
            stripped = line.strip().lstrip("-*").strip()
            for title, field in DAILY_JOURNAL_FIELD_BY_TITLE.items():
                prefix = f"{title}："
                if stripped.startswith(prefix):
                    sections[field.field_id] = stripped[len(prefix) :].strip()
        return sections

    def _call_weekly_self_model_llm(self, start: date, end: date, entries: list[dict[str, Any]]) -> dict[str, Any]:
        if not getattr(self, "content_flow_client", None) or not hasattr(self.content_flow_client, "_call_profile_provider_json"):
            return {"status": "pending_manual", "reason": "缺少可用 LLM 周记总结器"}
        user_content = json.dumps(
            {
                "week": week_key(start, end),
                "fixed_sections": list(WEEKLY_FIXED_SECTIONS),
                "dynamic_topic_clusters": list(WEEKLY_DYNAMIC_TOPIC_CLUSTERS),
                "journal_entries": self._weekly_entries_for_llm(entries),
            },
            ensure_ascii=False,
        )
        return self.content_flow_client._call_profile_provider_json(
            WEEKLY_SELF_MODEL_LLM_PROFILE,
            WEEKLY_SELF_MODEL_SUMMARY_PROMPT,
            user_content,
            "Daily 周记总结",
        )

    @staticmethod
    def _weekly_entries_for_llm(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        normalized = []
        for entry in entries:
            sections = {}
            for field_id, value in (entry.get("sections") or {}).items():
                text = str(value or "").strip()
                if text:
                    sections[field_id] = text[:1200]
            normalized.append({"date": entry.get("date"), "path": entry.get("path"), "sections": sections})
        return normalized

    @staticmethod
    def _normalize_weekly_self_model_payload(payload: dict[str, Any]) -> tuple[dict[str, str], list[dict[str, Any]]]:
        raw_fixed = payload.get("fixed_sections") if isinstance(payload.get("fixed_sections"), dict) else {}
        fixed_sections = {section: str(raw_fixed.get(section) or "").strip() for section in WEEKLY_FIXED_SECTIONS}
        raw_clusters = payload.get("dynamic_topic_clusters") if isinstance(payload.get("dynamic_topic_clusters"), list) else []
        allowed = set(WEEKLY_DYNAMIC_TOPIC_CLUSTERS)
        clusters: list[dict[str, Any]] = []
        for raw in raw_clusters:
            if not isinstance(raw, dict):
                continue
            topic = str(raw.get("topic") or "").strip()
            if topic not in allowed:
                continue
            summary = str(raw.get("summary") or "").strip()
            evidence_dates = raw.get("evidence_dates") if isinstance(raw.get("evidence_dates"), list) else []
            clusters.append(
                {
                    "topic": topic,
                    "summary": summary,
                    "evidence_dates": [str(item).strip() for item in evidence_dates if str(item or "").strip()],
                }
            )
        return fixed_sections, clusters

    def _render_weekly_self_model_summary_block(
        self,
        *,
        week: str,
        status: str,
        sample_count: int,
        entries: list[dict[str, Any]],
        fixed_sections: dict[str, str],
        dynamic_clusters: list[dict[str, Any]],
        reason: str,
    ) -> str:
        lines = [
            f"<!-- openclaw-weekly-self-model:{week}:start -->",
            "# 日记 / 周记自我模型",
            "",
            f"- 周期：{week}",
            f"- 状态：{status}",
            f"- 日记样本：{sample_count} 篇",
        ]
        if reason:
            lines.append(f"- 说明：{reason}")
        lines.append("")

        lines.append("## 固定总结")
        if status == "written":
            for section in WEEKLY_FIXED_SECTIONS:
                value = fixed_sections.get(section, "").strip() or "未从本周日记中提取到足够证据。"
                lines.extend([f"### {section}", value, ""])
        else:
            lines.extend(["样本不足，本区不生成稳定总结。", ""])

        lines.append("## 动态主题簇")
        if status == "written" and dynamic_clusters:
            for cluster in dynamic_clusters:
                lines.append(f"### {cluster['topic']}")
                lines.append(cluster.get("summary") or "未提取到摘要。")
                dates = "、".join(cluster.get("evidence_dates") or [])
                if dates:
                    lines.append(f"证据日期：{dates}")
                lines.append("")
        else:
            lines.extend(["未生成动态主题簇。", ""])

        lines.append("## 日记索引")
        if entries:
            for entry in entries:
                lines.append(self._weekly_self_model_entry_index_line(entry))
        else:
            lines.append("- 本周没有日记文件。")
        lines.extend(["", f"<!-- openclaw-weekly-self-model:{week}:end -->", ""])
        return "\n".join(lines)

    @staticmethod
    def _weekly_self_model_entry_index_line(entry: dict[str, Any]) -> str:
        sections = entry.get("sections") or {}
        candidate_ids = (
            "today_one_sentence",
            "today_most_recordable",
            "development_work",
            "engineering_experience",
            "commitment_unfinished",
        )
        summary = next((str(sections.get(field_id) or "").strip() for field_id in candidate_ids if str(sections.get(field_id) or "").strip()), "")
        if len(summary) > 80:
            summary = summary[:77] + "..."
        return f"- {entry.get('date')}：{summary or '已记录'}（{entry.get('path')}）"
