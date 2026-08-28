"""Pure schedule parsing and local snapshot adaptation for media workflows."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable


LOCAL_TZ = timezone(timedelta(hours=8))
_DATE_RE = re.compile(r"(?P<year>20\d{2})[-/.](?P<month>1[0-2]|0?[1-9])[-/.](?P<day>3[01]|[12]\d|0?[1-9])")
_CHINESE_DATE_RE = re.compile(
    r"(?:(?P<year>20\d{2})\s*年\s*)?(?P<month>1[0-2]|0?[1-9])\s*月\s*(?P<day>3[01]|[12]\d|0?[1-9])\s*(?:日|号)?"
)
_MONTH_WINDOW_RE = re.compile(
    r"(?:(?P<year>20\d{2})\s*年\s*)?(?P<month>1[0-2]|[1-9])\s*月\s*(?P<period>上旬|中旬|下旬)"
)
_RELATIVE_MONTH_WINDOW_RE = re.compile(r"(?P<relative>本|这|下)月\s*(?P<period>上旬|中旬|下旬)")
_DAYS_AFTER_RE = re.compile(r"(?P<days>[1-9]\d*)\s*天后")
_TERMINAL_SCHEDULE_STATES = frozenset({"cancelled", "canceled", "completed", "deleted", "已取消", "已完成", "已删除"})


def schedule_reference_time(now: datetime | date | None = None) -> datetime:
    if now is None:
        return datetime.now(LOCAL_TZ)
    if isinstance(now, datetime):
        return (now.replace(tzinfo=LOCAL_TZ) if now.tzinfo is None else now.astimezone(LOCAL_TZ)).replace(microsecond=0)
    return datetime.combine(now, datetime.min.time(), tzinfo=LOCAL_TZ)


def schedule_window_end(value: Any, *, now: datetime | date | None = None) -> date | None:
    """Resolve a supported availability phrase to its inclusive end date."""
    text = _text(value)
    if not text:
        return None
    reference = schedule_reference_time(now).date()

    explicit_dates = _explicit_dates(text, default_year=reference.year)
    if explicit_dates:
        # A stated interval stays valid through its final stated day.
        return max(explicit_dates)

    relative_month = _RELATIVE_MONTH_WINDOW_RE.search(text)
    if relative_month:
        month_offset = 1 if relative_month.group("relative") == "下" else 0
        year, month = _add_months(reference.year, reference.month, month_offset)
        return _month_window_end(year, month, relative_month.group("period"))

    month_window = _MONTH_WINDOW_RE.search(text)
    if month_window:
        year = int(month_window.group("year") or reference.year)
        return _month_window_end(year, int(month_window.group("month")), month_window.group("period"))

    if "昨天" in text:
        return reference - timedelta(days=1)
    if "今天" in text:
        return reference
    if "明天" in text:
        return reference + timedelta(days=1)
    if "后天" in text:
        return reference + timedelta(days=2)
    days_after = _DAYS_AFTER_RE.search(text)
    if days_after:
        return reference + timedelta(days=int(days_after.group("days")))
    if "本周" in text or "这周" in text:
        return reference + timedelta(days=6 - reference.weekday())
    if "下周" in text:
        return reference + timedelta(days=13 - reference.weekday())
    return None


def is_expired_schedule_value(value: Any, *, now: datetime | date | None = None) -> bool:
    window_end = schedule_window_end(value, now=now)
    return window_end is not None and window_end < schedule_reference_time(now).date()


def is_confirmable_schedule_value(value: Any, *, now: datetime | date | None = None) -> bool:
    """Accept only a date commitment, never a vague availability phrase."""
    text = _text(value)
    if not text or re.search(r"尽快|尽早|待定|待确认|看情况|本周|下周|上旬|中旬|下旬", text):
        return False
    if _explicit_dates(text, default_year=schedule_reference_time(now).year):
        return not is_expired_schedule_value(text, now=now)
    return False


def upcoming_schedule_entries(
    rows: Iterable[Any],
    *,
    tenant_id: str,
    platform: str = "",
    account: str = "",
    now: datetime | date | None = None,
    horizon_days: int = 7,
    limit: int = 5,
) -> list[dict[str, str]]:
    """Adapt local schedule snapshots without contacting a calendar provider."""
    reference = schedule_reference_time(now)
    horizon = reference + timedelta(days=max(0, horizon_days))
    expected_platform = _text(platform)
    expected_account = _text(account)
    entries: list[dict[str, str]] = []
    for row in rows:
        for item in _snapshot_entries(row):
            if _text(item.get("tenant_id")) and _text(item.get("tenant_id")) != tenant_id:
                continue
            if _text(item.get("status")).lower() in _TERMINAL_SCHEDULE_STATES:
                continue
            if expected_platform and _text(item.get("platform")) and _text(item.get("platform")) != expected_platform:
                continue
            if expected_account and _text(item.get("account") or item.get("account_name")) and _text(item.get("account") or item.get("account_name")) != expected_account:
                continue
            start = _parse_snapshot_datetime(item.get("starts_at") or item.get("start_at") or item.get("due_at") or item.get("scheduled_at"))
            if start is None:
                continue
            end = _parse_snapshot_datetime(item.get("ends_at") or item.get("end_at")) or start
            if end < reference or start > horizon:
                continue
            title = _text(item.get("title") or item.get("summary") or item.get("name") or "已安排事项")[:160]
            entries.append(
                {
                    "title": title,
                    "starts_at": start.isoformat(timespec="minutes"),
                    "ends_at": end.isoformat(timespec="minutes"),
                    "status": _text(item.get("status")) or "confirmed",
                }
            )
    entries.sort(key=lambda item: (item["starts_at"], item["ends_at"], item["title"]))
    return entries[: max(0, limit)]


def _explicit_dates(text: str, *, default_year: int) -> list[date]:
    matches = sorted(
        [*_DATE_RE.finditer(text), *_CHINESE_DATE_RE.finditer(text)],
        key=lambda match: match.start(),
    )
    dates: list[date] = []
    for match in matches:
        parsed = _date_from_match(match, default_year=default_year)
        if parsed is None:
            continue
        if dates and match.group("year") is None:
            while parsed < dates[-1]:
                parsed = date(parsed.year + 1, parsed.month, parsed.day)
        dates.append(parsed)
    return dates


def _date_from_match(match: re.Match[str], *, default_year: int) -> date | None:
    try:
        return date(int(match.group("year") or default_year), int(match.group("month")), int(match.group("day")))
    except ValueError:
        return None


def _month_window_end(year: int, month: int, period: str) -> date:
    if period == "上旬":
        return date(year, month, 10)
    if period == "中旬":
        return date(year, month, 20)
    next_year, next_month = _add_months(year, month, 1)
    return date(next_year, next_month, 1) - timedelta(days=1)


def _add_months(year: int, month: int, months: int) -> tuple[int, int]:
    offset = year * 12 + month - 1 + months
    return offset // 12, offset % 12 + 1


def _snapshot_entries(row: Any) -> list[dict[str, Any]]:
    if not isinstance(row, dict):
        return []
    nested = row.get("entries")
    if isinstance(nested, list):
        return [item for item in nested if isinstance(item, dict)]
    return [row]


def _parse_snapshot_datetime(value: Any) -> datetime | None:
    text = _text(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=LOCAL_TZ)
    return parsed.astimezone(LOCAL_TZ)


def _text(value: Any) -> str:
    return str(value or "").strip()
