from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from zoneinfo import ZoneInfo

from ..adapters.mac_agent_client import MacAgentClient, SchedulePayload
from .utils import format_display_time


@dataclass
class ParsedSchedule:
    title: str
    due_at: datetime
    used_default_time: bool
    raw_body: str


class ScheduleService:
    def __init__(self, timezone: str, mac_agent_client: MacAgentClient, obsidian_root: str):
        self.tz = ZoneInfo(timezone)
        self.mac_agent_client = mac_agent_client
        self.obsidian_root = obsidian_root

    def parse(self, body: str, now: datetime) -> ParsedSchedule:
        text = body.strip()
        base_date = now.astimezone(self.tz).date()
        target_date = base_date
        used_default_time = False

        explicit_date = re.search(r"(?:(\d{4})[-/年])?(\d{1,2})[月/-](\d{1,2})日?", text)
        if explicit_date:
            year = explicit_date.group(1)
            month = int(explicit_date.group(2))
            day = int(explicit_date.group(3))
            target_date = date(int(year) if year else base_date.year, month, day)
            text = text.replace(explicit_date.group(0), "", 1).strip()
        elif "后天" in text:
            target_date = base_date + timedelta(days=2)
            text = text.replace("后天", "", 1).strip()
        elif "明天" in text:
            target_date = base_date + timedelta(days=1)
            text = text.replace("明天", "", 1).strip()
        elif "今天" in text:
            target_date = base_date
            text = text.replace("今天", "", 1).strip()

        hour = minute = None
        m = re.search(r"(上午|中午|下午|晚上)?\s*(\d{1,2})\s*(?:[:点时]\s*(\d{1,2}))?\s*(分)?", text)
        if m and any(token in m.group(0) for token in [":", "点", "时"]):
            ap = m.group(1) or ""
            hour = int(m.group(2))
            minute = int(m.group(3) or 0)
            if ap in {"下午", "晚上"} and hour < 12:
                hour += 12
            if ap == "中午" and hour < 11:
                hour += 12
            text = text.replace(m.group(0), "", 1).strip()
        elif "下午" in text:
            m2 = re.search(r"下午\s*(\d{1,2})", text)
            if m2:
                hour = int(m2.group(1))
                if hour < 12:
                    hour += 12
                minute = 0
                text = text.replace(m2.group(0), "", 1).strip()

        if hour is None:
            hour, minute = 14, 0
            used_default_time = True

        title = self._concise_title(text, body)
        due_at = datetime.combine(target_date, time(hour, minute), tzinfo=self.tz)
        return ParsedSchedule(title=title, due_at=due_at, used_default_time=used_default_time, raw_body=body)

    def reminder_at(self, parsed: ParsedSchedule) -> datetime:
        """Return the time the user should be notified/act for a schedule.

        If the explicit schedule time is clearly a departure/action time, remind at
        that time. Otherwise use one hour before the event/start/arrival time.
        """
        if self._explicit_time_is_departure(parsed.raw_body):
            return parsed.due_at
        return parsed.due_at - timedelta(hours=1)

    @staticmethod
    def _explicit_time_is_departure(text: str) -> bool:
        compact = re.sub(r"\s+", "", text)
        time_pattern = r"(?:上午|中午|下午|晚上)?\d{1,2}(?::|点|时)\d{0,2}分?"
        for m in re.finditer(time_pattern, compact):
            window = compact[max(0, m.start() - 6): m.end() + 8]
            if any(word in window for word in ("出发", "动身", "启程")):
                return True
        return False

    @staticmethod
    def _concise_title(text: str, fallback: str) -> str:
        """Build a short calendar/reminder title from the body after date/time removal."""
        title = re.sub(r"\s+", " ", text).strip(" ，,。；;：:")
        title = re.sub(r"^(请|帮我|请帮我|记得|提醒我|要|需要)\s*", "", title)
        title = title.replace("那个自己的", "").replace("自己的", "")
        title = re.sub(r"快递有个?衣服发到那边", "取衣服快递", title)
        title = re.sub(r"有个?衣服发到那边", "取衣服快递", title)
        title = title.replace("快递取衣服快递", "取衣服快递")
        title = re.sub(r"^点\s*", "", title)

        # Drop context/planning clauses that make Feishu calendar titles noisy.
        parts = [p.strip(" ，,。；;：:") for p in re.split(r"[，,。；;\n]", title) if p.strip(" ，,。；;：:")]
        noise_prefixes = ("我在", "当前", "现在", "需要", "请帮", "帮我", "留出", "给我", "还没有", "还没")
        useful = [p for p in parts if not p.startswith(noise_prefixes)]
        if useful:
            title = useful[0]
            # If the next useful clause is a short object/purpose, keep it.
            if len(useful) > 1 and len(title) + len(useful[1]) <= 22:
                title = f"{title}{useful[1]}"

        title = re.sub(r"\s+", " ", title).strip(" ，,。；;：:")
        if not title:
            title = re.sub(r"\s+", " ", fallback).strip(" ，,。；;：:")
        return title[:30]

    def execute(self, parsed: ParsedSchedule) -> dict[str, str]:
        note_path = f"{self.obsidian_root}/{parsed.due_at.strftime('%Y%m%d')}.md"
        payload = SchedulePayload(
            title=parsed.title,
            due_at=parsed.due_at,
            note_path=note_path,
            reminder_text=f"- [ ] {format_display_time(parsed.due_at)} {parsed.title}",
        )
        result = self.mac_agent_client.create_schedule(payload)
        result["display_time"] = format_display_time(parsed.due_at)
        result["used_default_time"] = "true" if parsed.used_default_time else "false"
        return result
