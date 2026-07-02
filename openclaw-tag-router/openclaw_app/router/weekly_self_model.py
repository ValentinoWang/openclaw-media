from __future__ import annotations

import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .tag_router_common import *


WEEKLY_SELF_MODEL_SECTIONS = ("知识", "认知", "灵感", "内容")
WEEKLY_SELF_MODEL_DAILY_TAGS = (
    "待办",
    "日程",
    "待办-开发",
    "今日",
    "开发-完成",
    "开发-验证",
)


class WeeklySelfModelMixin:
    def handle_周记(self, message: Message) -> TaskResult:
        ranges, error = self._weekly_self_model_ranges(message)
        if error:
            entry = self.archive_service.save_archive(message, "周记整理失败", [("失败原因", error)], {"status": "pending_source"})
            return TaskResult(ok=False, status="pending_source", reply=error, task_id=entry.frontmatter["id"], local_path=entry.local_path)

        drafts = []
        for start, end in ranges:
            drafts.append(self._build_weekly_self_model_draft(start, end))

        title = "周记整理：" + "、".join(draft["week"] for draft in drafts)
        sections = [
            ("处理状态", "\n".join(f"- {draft['week']}：{draft['draft_path']}" for draft in drafts)),
            ("数据来源", self._weekly_self_model_source_summary(drafts)),
        ]
        entry = self.archive_service.save_archive(
            message,
            title,
            sections,
            {
                "status": "draft",
                "record_kind": "weekly_self_model_review",
                "week": ",".join(draft["week"] for draft in drafts),
                "sources": ["weekly_archive", "daily_archive"],
                "applied": False,
            },
        )
        reply_lines = [
            "周记整理草稿已生成",
            f"状态：draft",
            f"任务ID：{entry.frontmatter['id']}",
        ]
        for draft in drafts:
            reply_lines.extend(
                [
                    "",
                    f"周：{draft['week']}",
                    f"Obsidian：{draft['draft_path']}",
                    f"周记小节：{draft['weekly_section_count']} 个",
                    f"Daily 能力归档：{draft['daily_archive_count']} 条",
                ]
            )
        return TaskResult(ok=True, status="draft", reply="\n".join(reply_lines), task_id=entry.frontmatter["id"], local_path=entry.local_path, extra={"drafts": drafts})

    def _weekly_self_model_ranges(self, message: Message) -> tuple[list[tuple[date, date]], str]:
        text = str(message.body or "").strip()
        current_start, current_end = self._weekly_self_model_week_bounds(message.created_at)
        explicit = re.search(r"(20\d{6})\s*(?:-|—|~|至|到)\s*(20\d{6})", text)
        if explicit:
            start = self._weekly_self_model_parse_date(explicit.group(1))
            end = self._weekly_self_model_parse_date(explicit.group(2))
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

    def _weekly_self_model_week_bounds(self, dt: datetime) -> tuple[date, date]:
        zoned = dt.astimezone(ZoneInfo(self.timezone))
        start = zoned.date() - timedelta(days=zoned.weekday())
        return start, start + timedelta(days=6)

    @staticmethod
    def _weekly_self_model_parse_date(value: str) -> date | None:
        try:
            return datetime.strptime(value, "%Y%m%d").date()
        except ValueError:
            return None

    def _build_weekly_self_model_draft(self, start: date, end: date) -> dict[str, Any]:
        week = f"{start.strftime('%Y%m%d')}-{end.strftime('%Y%m%d')}"
        weekly_path = self._weekly_self_model_archive_root() / f"{week}.md"
        weekly_sections = self._weekly_self_model_read_sections(weekly_path)
        daily_entries = self._weekly_self_model_daily_entries(start, end)
        candidates = self._weekly_self_model_candidates(weekly_sections, daily_entries)
        draft_path = self._weekly_self_model_draft_dir() / f"{week}-自我模型候选.md"
        ensure_dir(draft_path.parent)
        draft_path.write_text(
            self._render_weekly_self_model_draft(week, weekly_path, weekly_sections, daily_entries, candidates),
            encoding="utf-8",
        )
        return {
            "week": week,
            "draft_path": str(draft_path),
            "weekly_path": str(weekly_path),
            "weekly_section_count": len(weekly_sections),
            "daily_archive_count": len(daily_entries),
            "candidate_count": sum(len(items) for items in candidates.values()),
        }

    def _weekly_self_model_archive_root(self) -> Path:
        return Path(os.environ.get("OPENCLAW_WEEKLY_ARCHIVE_ROOT", "/home/ubuntu/obsidian-日记/Archieve"))

    def _weekly_self_model_draft_dir(self) -> Path:
        return Path(os.environ.get("OPENCLAW_SELF_MODEL_WEEKLY_DIR", "/home/ubuntu/obsidian-日记/社交/自我模型/周记整理"))

    def _weekly_self_model_read_sections(self, path: Path) -> list[dict[str, str]]:
        if not path.exists():
            return []
        text = self._strip_weekly_generated_blocks(path.read_text(encoding="utf-8"))
        headings = list(re.finditer(r"^#\s+(.+?)\s*$", text, flags=re.MULTILINE))
        sections: list[dict[str, str]] = []
        for index, heading in enumerate(headings):
            name = heading.group(1).strip()
            if name not in WEEKLY_SELF_MODEL_SECTIONS:
                continue
            start = heading.end()
            end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
            body = text[start:end].strip()
            if body:
                sections.append({"section": name, "body": body})
        return sections

    @staticmethod
    def _strip_weekly_generated_blocks(text: str) -> str:
        return re.sub(
            r"<!--\s*codex-dev-review:[^>]*:start\s*-->[\s\S]*?<!--\s*codex-dev-review:[^>]*:end\s*-->",
            "",
            text,
        )

    def _weekly_self_model_daily_entries(self, start: date, end: date) -> list[Any]:
        entries = []
        for tag in WEEKLY_SELF_MODEL_DAILY_TAGS:
            for entry in self.archive_service.list_archives(limit=None, tag=tag):
                created = self._weekly_self_model_entry_date(entry)
                if created and start <= created <= end:
                    entries.append(entry)
        return sorted(entries, key=lambda entry: str(entry.frontmatter.get("id") or ""))

    @staticmethod
    def _weekly_self_model_entry_date(entry: Any) -> date | None:
        record_id = str(entry.frontmatter.get("id") or "")
        if len(record_id) >= 8 and record_id[:8].isdigit():
            try:
                return datetime.strptime(record_id[:8], "%Y%m%d").date()
            except ValueError:
                return None
        return None

    def _weekly_self_model_candidates(self, weekly_sections: list[dict[str, str]], daily_entries: list[Any]) -> dict[str, list[dict[str, str]]]:
        candidates: dict[str, list[dict[str, str]]] = {}
        for section in weekly_sections:
            for line in self._weekly_self_model_meaningful_lines(section["body"]):
                for theme in self._weekly_self_model_themes(line):
                    self._append_weekly_candidate(candidates, theme, line, f"周记 #{section['section']}", "medium")

        for entry in daily_entries:
            text = self._weekly_self_model_entry_text(entry)
            themes = self._weekly_self_model_themes(text)
            if not themes:
                themes = ["生活节奏、执行偏好、时间管理"]
            for theme in themes:
                self._append_weekly_candidate(
                    candidates,
                    theme,
                    f"{entry.frontmatter.get('created_at', '')}｜{entry.frontmatter.get('entry_tag', '')}｜{entry.title}",
                    entry.local_path,
                    self._weekly_self_model_sensitive_level(text),
                )
        return candidates

    @staticmethod
    def _weekly_self_model_meaningful_lines(text: str) -> list[str]:
        lines: list[str] = []
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line in {"---"}:
                continue
            if line.startswith("|") or set(line.replace("|", "").strip()) <= {"-", ":"}:
                continue
            line = re.sub(r"^[-*]\s*", "", line)
            lines.append(line[:500])
        return lines

    @staticmethod
    def _append_weekly_candidate(candidates: dict[str, list[dict[str, str]]], theme: str, summary: str, source: str, sensitive_level: str) -> None:
        bucket = candidates.setdefault(theme, [])
        if len(bucket) >= 20:
            return
        item = {"summary": summary.strip(), "source": source, "confidence": "medium", "sensitive_level": sensitive_level}
        if item not in bucket:
            bucket.append(item)

    def _weekly_self_model_themes(self, text: str) -> list[str]:
        normalized = str(text or "")
        themes: list[str] = []
        theme_keywords = (
            ("需转 Social bot 复核", ("亲密", "亲密关系", "异性", "女生", "约会", "性关系", "社交对象")),
            ("教育 AI 创业与产品方向", ("教育", "AI教育", "教育AI", "K12", "学生", "家长", "教学", "课程", "学校", "教培", "学习产品")),
            ("体育 AI 创业与产品方向", ("体育", "训练", "田径", "短跑", "体能", "教练", "CMJ", "运动表现", "俱乐部", "测评")),
            ("内容/IP 与账号定位", ("博主", "Vlog", "抖音", "小红书", "粉丝", "IP", "账号", "选题", "发布", "创作")),
            ("教育与技术背景", ("清华", "AI", "人工智能", "技术", "程序员", "硕士", "本科", "数学系")),
            ("运动训练与赛事经历", ("100米", "一级", "比赛", "大运", "锦标赛", "首都高校", "胡凯", "起跑", "步频")),
            ("高频可见标签", ("身份", "标签", "小王", "清华小王", "短跑一级", "全运会火炬手")),
            ("隐私数据足迹与清理项", ("隐私", "session", "trajectory", "运行轨迹", "备份", "清理", "敏感")),
            ("生活节奏、执行偏好、时间管理", ("待办", "日程", "提醒", "完成", "延期", "取消", "今天", "明天", "截止")),
        )
        for theme, keywords in theme_keywords:
            if any(keyword in normalized for keyword in keywords):
                themes.append(theme)
        return themes

    @staticmethod
    def _weekly_self_model_sensitive_level(text: str) -> str:
        if any(keyword in str(text or "") for keyword in ("亲密", "异性", "女生", "性", "隐私", "轨迹")):
            return "high"
        return "medium"

    @staticmethod
    def _weekly_self_model_entry_text(entry: Any) -> str:
        parts = [entry.title]
        for heading, body in entry.sections[:2]:
            parts.append(heading)
            parts.append(body[:800])
        return "\n".join(parts)

    def _render_weekly_self_model_draft(
        self,
        week: str,
        weekly_path: Path,
        weekly_sections: list[dict[str, str]],
        daily_entries: list[Any],
        candidates: dict[str, list[dict[str, str]]],
    ) -> str:
        lines = [
            "---",
            "status: draft",
            f"week: {week}",
            "sources:",
            "  - weekly_archive",
            "  - daily_archive",
            "applied: false",
            "---",
            "",
            f"# 【王思尧】{week} 自我模型候选",
            "",
            "## 状态",
            "",
            "- 状态：draft",
            "- 维护目标：Obsidian `/home/ubuntu/obsidian-日记/社交/自我模型/`",
            "- 写入策略：先出草稿，不直接覆盖核心模型",
            "- Daily 边界：不直接改社交/亲密核心模型；相关内容只进入 Social bot 复核候选",
            "",
            "## 来源",
            "",
            f"- 周记：`{weekly_path}`",
            f"- 处理小节：{', '.join('# ' + item['section'] for item in weekly_sections) or '无'}",
            f"- Daily 能力归档：{len(daily_entries)} 条",
            "",
            "## 候选分流",
            "",
        ]
        if not candidates:
            lines.append("暂无候选。")
        for theme, items in candidates.items():
            lines.extend([f"### {theme}", ""])
            for item in items:
                lines.append(f"- {item['summary']}")
                lines.append(f"  - 来源：`{item['source']}`")
                lines.append(f"  - 置信度：{item['confidence']}；敏感级别：{item['sensitive_level']}")
            lines.append("")

        lines.extend(["## Daily 能力归档索引", ""])
        if not daily_entries:
            lines.append("无。")
        for entry in daily_entries[:80]:
            lines.append(f"- `{entry.frontmatter.get('id', '')}`｜{entry.frontmatter.get('entry_tag', '')}｜{entry.title}")
            lines.append(f"  - 路径：`{entry.local_path}`")
        lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    @staticmethod
    def _weekly_self_model_source_summary(drafts: list[dict[str, Any]]) -> str:
        return "\n".join(
            [
                f"- {draft['week']}：周记小节 {draft['weekly_section_count']} 个；Daily 能力归档 {draft['daily_archive_count']} 条；候选 {draft['candidate_count']} 条"
                for draft in drafts
            ]
        )
