from __future__ import annotations

import hashlib
import html
import os
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from html.parser import HTMLParser
from typing import Any, Callable, Protocol
from urllib.parse import parse_qs, unquote, urlencode, urlparse
from zoneinfo import ZoneInfo

import requests

from selfmedia.business.id_business import load_playwright_cookies
from selfmedia.ingest.content_flow.src.downloader import (
    _extract_xhs_interaction_stats,
    _parse_xhs_initial_state,
    extract_router_data,
)


SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
DEFAULT_LIMIT = 20
MAX_LIMIT = 50
DEFAULT_TIME_RANGE = "近7天"
DEFAULT_SORT = "点赞降序"
MOBILE_USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)
DESKTOP_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
INPUT_LABELS = ("平台", "关键词", "时间", "标签", "排序", "数量")
DOUYIN_PATH_RE = re.compile(r"/(?:video|note|share/video|share/note)/(\d+)")
XHS_PATH_RE = re.compile(r"/(?:explore|discovery/item)/([0-9a-fA-F]{24,32})")


class HotlistValidationError(ValueError):
    pass


class SearchSourceError(RuntimeError):
    def __init__(self, code: str, reason: str, *, http_status: int | None = None):
        super().__init__(reason)
        self.code = code
        self.reason = reason
        self.http_status = http_status


class DetailSourceError(RuntimeError):
    def __init__(self, code: str, reason: str):
        super().__init__(reason)
        self.code = code
        self.reason = reason


@dataclass(frozen=True)
class TimeWindow:
    label: str
    start: datetime | None = None
    end: datetime | None = None

    def contains(self, value: datetime) -> bool:
        localized = value.astimezone(SHANGHAI_TZ)
        if self.start is not None and localized < self.start:
            return False
        if self.end is not None and localized > self.end:
            return False
        return True


@dataclass(frozen=True)
class HotlistRequest:
    platform: str
    keyword: str
    time_window: TimeWindow
    tags: tuple[str, ...] = ()
    sort: str = "likes_desc"
    sort_label: str = DEFAULT_SORT
    limit: int = DEFAULT_LIMIT


@dataclass(frozen=True)
class SearchCandidate:
    platform: str
    content_id: str
    url: str
    discovery_source: str


@dataclass(frozen=True)
class HotlistItem:
    platform: str
    content_id: str
    title: str
    author: str
    like_count: int
    published_at: datetime
    tags: tuple[str, ...]
    url: str
    source_url: str
    source_status: str

    def as_dict(self, *, rank: int | None = None) -> dict[str, Any]:
        result: dict[str, Any] = {
            "platform": self.platform,
            "content_id": self.content_id,
            "title": self.title,
            "author": self.author,
            "like_count": self.like_count,
            "published_at": self.published_at.astimezone(SHANGHAI_TZ).isoformat(),
            "tags": list(self.tags),
            "url": self.url,
            "source_url": self.source_url,
            "source_status": self.source_status,
        }
        if rank is not None:
            result["rank"] = rank
        return result


@dataclass(frozen=True)
class HotlistResult:
    status: str
    request: HotlistRequest
    checked_at: datetime
    trace_id: str
    items: tuple[HotlistItem, ...] = ()
    discovered_count: int = 0
    verified_count: int = 0
    source_status: dict[str, Any] = field(default_factory=dict)
    rejected_counts: dict[str, int] = field(default_factory=dict)
    reason: str = ""
    blocked_source: str = ""

    @property
    def ok(self) -> bool:
        return self.status in {"ok", "no_verified_results"}

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "trace_id": self.trace_id,
            "checked_at": self.checked_at.astimezone(SHANGHAI_TZ).isoformat(),
            "request": {
                "platform": self.request.platform,
                "keyword": self.request.keyword,
                "time": self.request.time_window.label,
                "tags": list(self.request.tags),
                "sort": self.request.sort_label,
                "limit": self.request.limit,
            },
            "items": [item.as_dict(rank=index) for index, item in enumerate(self.items, start=1)],
            "discovered_count": self.discovered_count,
            "verified_count": self.verified_count,
            "source_status": self.source_status,
            "rejected_counts": self.rejected_counts,
            "reason": self.reason,
            "blocked_source": self.blocked_source,
        }


class CandidateDiscovery(Protocol):
    source_name: str

    def discover(self, request: HotlistRequest) -> list[SearchCandidate]: ...


class DetailReader(Protocol):
    def read(self, candidate: SearchCandidate) -> HotlistItem: ...


def _normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).lower()
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", normalized)


def _parse_labeled_fields(text: str) -> dict[str, str]:
    body = re.sub(r"^\s*【热榜】\s*", "", str(text or "").strip())
    label_pattern = "|".join(re.escape(label) for label in INPUT_LABELS)
    pattern = re.compile(rf"(?:(?<=^)|(?<=\s))(?P<label>{label_pattern})\s*[：:=]\s*", re.M)
    matches = list(pattern.finditer(body))
    fields: dict[str, str] = {}
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        fields[match.group("label")] = body[start:end].strip()
    return fields


def _normalize_platform(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"抖音", "douyin"}:
        return "抖音"
    if normalized in {"小红书", "xiaohongshu", "xhs", "rednote"}:
        return "小红书"
    if "/" in normalized or "、" in normalized or "," in normalized or "，" in normalized:
        raise HotlistValidationError("一次只能查询一个平台，请在“抖音”和“小红书”中选择一个。")
    raise HotlistValidationError("平台仅支持“抖音”或“小红书”。")


def _parse_tags(value: str) -> tuple[str, ...]:
    raw = str(value or "").strip()
    if not raw or raw in {"无", "不限", "不筛选"}:
        return ()
    hash_tags = re.findall(r"#([^#\s,，、]+)", raw)
    parts = hash_tags or re.split(r"[\s,，、;；]+", raw)
    deduped: list[str] = []
    seen: set[str] = set()
    for part in parts:
        cleaned = part.strip().lstrip("#＃").strip()
        key = _normalize_text(cleaned)
        if cleaned and key and key not in seen:
            seen.add(key)
            deduped.append(cleaned)
    return tuple(deduped)


def _at_start(value: date) -> datetime:
    return datetime.combine(value, time.min, tzinfo=SHANGHAI_TZ)


def _at_end(value: date) -> datetime:
    return datetime.combine(value, time.max, tzinfo=SHANGHAI_TZ)


def _parse_date(value: str) -> date:
    text = str(value or "").strip().replace("年", "-").replace("月", "-").replace("日", "")
    text = text.replace("/", "-").replace(".", "-")
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise HotlistValidationError(f"无法识别时间日期：{value}") from exc


def parse_time_window(value: str, *, now: datetime) -> TimeWindow:
    raw = str(value or "").strip() or DEFAULT_TIME_RANGE
    localized_now = now.astimezone(SHANGHAI_TZ)
    if raw in {"不限", "全部", "不筛选"}:
        return TimeWindow(label="不限")
    if raw in {"今天", "今日"}:
        return TimeWindow(label=raw, start=_at_start(localized_now.date()), end=localized_now)
    relative = re.fullmatch(r"(?:近|最近|过去)?\s*(\d{1,4})\s*(小时|天|周|个月|月)", raw)
    if relative:
        amount = int(relative.group(1))
        if amount <= 0:
            raise HotlistValidationError("时间范围必须大于 0。")
        unit = relative.group(2)
        delta = {
            "小时": timedelta(hours=amount),
            "天": timedelta(days=amount),
            "周": timedelta(weeks=amount),
            "个月": timedelta(days=amount * 30),
            "月": timedelta(days=amount * 30),
        }[unit]
        return TimeWindow(label=raw, start=localized_now - delta, end=localized_now)
    range_match = re.fullmatch(
        r"\s*(20\d{2}[-/.年]\d{1,2}[-/.月]\d{1,2}日?)\s*(?:至|到|~|～|—|--| - )\s*(20\d{2}[-/.年]\d{1,2}[-/.月]\d{1,2}日?)\s*",
        raw,
    )
    if range_match:
        start_date = _parse_date(range_match.group(1))
        end_date = _parse_date(range_match.group(2))
        if start_date > end_date:
            raise HotlistValidationError("时间范围的开始日期不能晚于结束日期。")
        return TimeWindow(label=raw, start=_at_start(start_date), end=_at_end(end_date))
    if re.fullmatch(r"20\d{2}[-/.年]\d{1,2}[-/.月]\d{1,2}日?", raw):
        day = _parse_date(raw)
        return TimeWindow(label=raw, start=_at_start(day), end=_at_end(day))
    raise HotlistValidationError("时间支持：近24小时、近7天、近30天、今天、2026-07-01至2026-07-18 或 不限。")


def _parse_sort(value: str) -> tuple[str, str]:
    raw = re.sub(r"\s+", "", str(value or "").strip()) or DEFAULT_SORT
    if raw in {"点赞降序", "点赞从高到低", "赞从高到低", "按点赞", "点赞"}:
        return "likes_desc", "点赞降序"
    if raw in {"最新优先", "时间从近到前", "发布时间降序", "按最新", "最新"}:
        return "published_desc", "最新优先"
    raise HotlistValidationError("排序仅支持“点赞降序”或“最新优先”。")


def parse_hotlist_request(text: str, *, now: datetime | None = None) -> HotlistRequest:
    fields = _parse_labeled_fields(text)
    if not fields:
        raise HotlistValidationError("请按模板填写平台、关键词、时间、标签、排序和数量。")
    platform = _normalize_platform(fields.get("平台", ""))
    keyword = str(fields.get("关键词") or "").strip()
    if not keyword:
        raise HotlistValidationError("缺少关键词。")
    if len(keyword) > 80:
        raise HotlistValidationError("关键词不能超过 80 个字符。")
    checked_at = now or datetime.now(SHANGHAI_TZ)
    time_window = parse_time_window(fields.get("时间", ""), now=checked_at)
    sort, sort_label = _parse_sort(fields.get("排序", ""))
    limit_raw = str(fields.get("数量") or DEFAULT_LIMIT).strip()
    if not re.fullmatch(r"\d+", limit_raw):
        raise HotlistValidationError("数量必须是 1-50 的整数。")
    limit = int(limit_raw)
    if not 1 <= limit <= MAX_LIMIT:
        raise HotlistValidationError("数量必须在 1-50 之间。")
    return HotlistRequest(
        platform=platform,
        keyword=keyword,
        time_window=time_window,
        tags=_parse_tags(fields.get("标签", "")),
        sort=sort,
        sort_label=sort_label,
        limit=limit,
    )


class _HrefCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        for name, value in attrs:
            if name.lower() == "href" and value:
                self.hrefs.append(html.unescape(value.strip()))
                break


def _unwrap_search_href(value: str) -> str:
    href = html.unescape(unquote(str(value or "").strip()))
    parsed = urlparse(href)
    if parsed.netloc.endswith("search.brave.com"):
        query = parse_qs(parsed.query)
        for key in ("url", "target", "u"):
            candidate = str((query.get(key) or [""])[0]).strip()
            if candidate.startswith("http"):
                return unquote(candidate)
    return href


def _candidate_from_url(platform: str, value: str) -> SearchCandidate | None:
    url = _unwrap_search_href(value)
    parsed = urlparse(url)
    host = parsed.netloc.lower().split(":", 1)[0]
    if platform == "抖音":
        if not (host == "douyin.com" or host.endswith(".douyin.com") or host.endswith(".iesdouyin.com")):
            return None
        match = DOUYIN_PATH_RE.search(parsed.path)
        if not match:
            return None
        content_id = match.group(1)
        kind = "note" if "/note/" in parsed.path else "video"
        canonical = f"https://www.douyin.com/{kind}/{content_id}"
        return SearchCandidate(platform=platform, content_id=content_id, url=canonical, discovery_source="brave_web_search")
    if platform == "小红书":
        if not (host == "xiaohongshu.com" or host.endswith(".xiaohongshu.com")):
            return None
        match = XHS_PATH_RE.search(parsed.path)
        if not match:
            return None
        content_id = match.group(1).lower()
        query = parse_qs(parsed.query, keep_blank_values=False)
        kept_query = {
            key: values
            for key, values in query.items()
            if key in {"xsec_token", "xsec_source"} and any(str(item).strip() for item in values)
        }
        canonical = f"https://www.xiaohongshu.com/explore/{content_id}"
        if kept_query:
            canonical += "?" + urlencode(kept_query, doseq=True)
        return SearchCandidate(platform=platform, content_id=content_id, url=canonical, discovery_source="brave_web_search")
    return None


class BraveSearchDiscovery:
    source_name = "brave_web_search"

    def __init__(self, *, endpoint: str | None = None, timeout: float = 20.0, session: requests.Session | None = None):
        self.endpoint = endpoint or os.getenv("HOTLIST_SEARCH_ENDPOINT", "https://search.brave.com/search")
        self.timeout = timeout
        self.session = session or requests.Session()

    @staticmethod
    def _query(request: HotlistRequest) -> str:
        if request.platform == "抖音":
            site = "(site:douyin.com/video/ OR site:douyin.com/note/)"
        else:
            site = "site:xiaohongshu.com/explore/"
        parts = [site, request.keyword, *request.tags]
        if request.time_window.start is not None:
            parts.append("after:" + request.time_window.start.date().isoformat())
        if request.time_window.end is not None:
            parts.append("before:" + (request.time_window.end.date() + timedelta(days=1)).isoformat())
        return " ".join(part for part in parts if part)

    def discover(self, request: HotlistRequest) -> list[SearchCandidate]:
        try:
            response = self.session.get(
                self.endpoint,
                params={"q": self._query(request), "source": "web", "spellcheck": "0"},
                headers={"User-Agent": DESKTOP_USER_AGENT, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.6"},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise SearchSourceError("HOTLIST_SEARCH_UNREACHABLE", f"公开候选搜索源不可达：{type(exc).__name__}") from exc
        if response.status_code == 429:
            raise SearchSourceError("HOTLIST_SEARCH_RATE_LIMITED", "公开候选搜索源触发限流。", http_status=429)
        if response.status_code != 200:
            raise SearchSourceError(
                "HOTLIST_SEARCH_HTTP_ERROR",
                f"公开候选搜索源返回 HTTP {response.status_code}。",
                http_status=response.status_code,
            )
        collector = _HrefCollector()
        try:
            collector.feed(response.text)
        except Exception as exc:
            raise SearchSourceError("HOTLIST_SEARCH_PARSE_FAILED", "公开候选搜索结果无法解析。") from exc
        by_id: dict[str, SearchCandidate] = {}
        max_candidates = min(50, max(20, request.limit * 3))
        for href in collector.hrefs:
            candidate = _candidate_from_url(request.platform, href)
            if candidate is None:
                continue
            current = by_id.get(candidate.content_id)
            if current is None or ("xsec_token=" not in current.url and "xsec_token=" in candidate.url):
                by_id[candidate.content_id] = candidate
            if len(by_id) >= max_candidates:
                break
        return list(by_id.values())


def _iter_dicts(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _iter_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _iter_dicts(child)


def _coerce_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    text = str(value).strip().replace(",", "")
    return int(text) if re.fullmatch(r"-?\d+", text) else None


def _timestamp(value: Any) -> datetime | None:
    number = _coerce_int(value)
    if number is None or number <= 0:
        return None
    if number > 10_000_000_000:
        number //= 1000
    try:
        return datetime.fromtimestamp(number, tz=SHANGHAI_TZ)
    except (OverflowError, OSError, ValueError):
        return None


def _extract_hash_tags(text: str) -> tuple[str, ...]:
    tags: list[str] = []
    seen: set[str] = set()
    for value in re.findall(r"[#＃]([^#＃\s]+)", str(text or "")):
        cleaned = value.strip("，,。.!！?？;；:：()（）[]【】")
        key = _normalize_text(cleaned)
        if cleaned and key and key not in seen:
            seen.add(key)
            tags.append(cleaned)
    return tuple(tags)


class PlatformShareDetailReader:
    def __init__(self, *, timeout: float = 15.0, session: requests.Session | None = None):
        self.timeout = timeout
        self.session = session or requests.Session()

    def read(self, candidate: SearchCandidate) -> HotlistItem:
        if candidate.platform == "抖音":
            return self._read_douyin(candidate)
        if candidate.platform == "小红书":
            return self._read_xhs(candidate)
        raise DetailSourceError("HOTLIST_PLATFORM_UNSUPPORTED", f"不支持的平台：{candidate.platform}")

    def _get(self, url: str, *, headers: dict[str, str], cookies: dict[str, str] | None = None) -> requests.Response:
        try:
            return self.session.get(url, headers=headers, cookies=cookies or {}, timeout=self.timeout, allow_redirects=True)
        except requests.RequestException as exc:
            raise DetailSourceError("HOTLIST_DETAIL_UNREACHABLE", f"作品详情源不可达：{type(exc).__name__}") from exc

    def _read_douyin(self, candidate: SearchCandidate) -> HotlistItem:
        kind = "note" if "/note/" in candidate.url else "video"
        source_url = f"https://www.iesdouyin.com/share/{kind}/{candidate.content_id}/"
        response = self._get(
            source_url,
            headers={"User-Agent": MOBILE_USER_AGENT, "Referer": "https://www.iesdouyin.com/"},
        )
        if response.status_code != 200:
            raise DetailSourceError("DOUYIN_DETAIL_HTTP_ERROR", f"抖音分享页返回 HTTP {response.status_code}。")
        router_data = extract_router_data(response.text)
        if not isinstance(router_data, dict):
            raise DetailSourceError("DOUYIN_DETAIL_BLOCKED", "抖音分享页未返回可核验作品数据。")
        aweme: dict[str, Any] | None = None
        for node in _iter_dicts(router_data):
            if str(node.get("aweme_id") or "") == candidate.content_id and isinstance(node.get("statistics"), dict):
                aweme = node
                break
        if aweme is None:
            raise DetailSourceError("DOUYIN_DETAIL_MISSING", "抖音分享页中未找到对应作品。")
        statistics = aweme.get("statistics") or {}
        like_count = _coerce_int(statistics.get("digg_count"))
        published_at = _timestamp(aweme.get("create_time"))
        title = str(aweme.get("desc") or "").strip()
        author_payload = aweme.get("author") if isinstance(aweme.get("author"), dict) else {}
        author = str(author_payload.get("nickname") or "").strip()
        if like_count is None or like_count < 0:
            raise DetailSourceError("DOUYIN_LIKES_UNVERIFIED", "抖音作品点赞数不可核验。")
        if published_at is None:
            raise DetailSourceError("DOUYIN_PUBLISHED_AT_UNVERIFIED", "抖音作品发布时间不可核验。")
        if not title or not author:
            raise DetailSourceError("DOUYIN_IDENTITY_UNVERIFIED", "抖音作品标题或作者不可核验。")
        tags = list(_extract_hash_tags(title))
        for item in aweme.get("text_extra") or []:
            if not isinstance(item, dict):
                continue
            tag = str(item.get("hashtag_name") or "").strip()
            if tag and _normalize_text(tag) not in {_normalize_text(value) for value in tags}:
                tags.append(tag)
        return HotlistItem(
            platform="抖音",
            content_id=candidate.content_id,
            title=title,
            author=author,
            like_count=like_count,
            published_at=published_at,
            tags=tuple(tags),
            url=candidate.url,
            source_url=source_url,
            source_status="platform_share_verified",
        )

    @staticmethod
    def _xhs_note(state: dict[str, Any], content_id: str) -> dict[str, Any] | None:
        matches: list[dict[str, Any]] = []
        for node in _iter_dicts(state):
            note_id = str(node.get("noteId") or node.get("note_id") or "").lower()
            if note_id != content_id.lower():
                continue
            if any(key in node for key in ("interactInfo", "interact_info", "title", "desc")):
                matches.append(node)
        if not matches:
            return None
        return max(matches, key=lambda item: len(item))

    def _read_xhs(self, candidate: SearchCandidate) -> HotlistItem:
        cookies = {item["name"]: item["value"] for item in load_playwright_cookies("小红书")}
        response = self._get(
            candidate.url,
            headers={"User-Agent": DESKTOP_USER_AGENT, "Referer": "https://www.xiaohongshu.com/"},
            cookies=cookies,
        )
        if response.status_code != 200:
            raise DetailSourceError("XHS_DETAIL_HTTP_ERROR", f"小红书作品页返回 HTTP {response.status_code}。")
        final_path = urlparse(response.url).path
        if "/website-login/error" in final_path or final_path.startswith("/404/"):
            raise DetailSourceError("XHS_DETAIL_BLOCKED", "小红书作品页要求有效登录态或 xsec_token，当前来源被风控拦截。")
        state = _parse_xhs_initial_state(response.text)
        if not isinstance(state, dict):
            raise DetailSourceError("XHS_DETAIL_BLOCKED", "小红书作品页未返回可核验初始数据。")
        note = self._xhs_note(state, candidate.content_id)
        if note is None:
            raise DetailSourceError("XHS_DETAIL_MISSING", "小红书作品页中未找到对应笔记。")
        stats = _extract_xhs_interaction_stats(note)
        like_count = _coerce_int(stats.get("like_count"))
        published_at = None
        for key in ("time", "publishTime", "publish_time", "createTime", "create_time", "lastUpdateTime"):
            published_at = _timestamp(note.get(key))
            if published_at is not None:
                break
        title = str(note.get("title") or note.get("desc") or "").strip()
        user = note.get("user") if isinstance(note.get("user"), dict) else {}
        author = str(user.get("nickname") or user.get("nickName") or user.get("name") or "").strip()
        if like_count is None or like_count < 0:
            raise DetailSourceError("XHS_LIKES_UNVERIFIED", "小红书笔记点赞数不可核验。")
        if published_at is None:
            raise DetailSourceError("XHS_PUBLISHED_AT_UNVERIFIED", "小红书笔记发布时间不可核验。")
        if not title or not author:
            raise DetailSourceError("XHS_IDENTITY_UNVERIFIED", "小红书笔记标题或作者不可核验。")
        tags = list(_extract_hash_tags("\n".join((str(note.get("title") or ""), str(note.get("desc") or "")))))
        for item in note.get("tagList") or note.get("tag_list") or []:
            if not isinstance(item, dict):
                continue
            tag = str(item.get("name") or item.get("tagName") or "").strip()
            if tag and _normalize_text(tag) not in {_normalize_text(value) for value in tags}:
                tags.append(tag)
        return HotlistItem(
            platform="小红书",
            content_id=candidate.content_id,
            title=title,
            author=author,
            like_count=like_count,
            published_at=published_at,
            tags=tuple(tags),
            url=candidate.url,
            source_url=candidate.url,
            source_status="platform_detail_verified",
        )


def _trace_id(request: HotlistRequest, checked_at: datetime) -> str:
    digest = hashlib.sha256(
        "|".join(
            (
                request.platform,
                request.keyword,
                request.time_window.label,
                ",".join(request.tags),
                request.sort,
                checked_at.isoformat(),
            )
        ).encode("utf-8")
    ).hexdigest()[:12]
    return f"hotlist_{checked_at.strftime('%Y%m%dT%H%M%S')}_{digest}"


class HotlistService:
    def __init__(
        self,
        *,
        discovery: CandidateDiscovery | None = None,
        detail_reader: DetailReader | None = None,
        now_provider: Callable[[], datetime] | None = None,
        max_workers: int = 4,
    ):
        self.discovery = discovery or BraveSearchDiscovery()
        self.detail_reader = detail_reader or PlatformShareDetailReader()
        self.now_provider = now_provider or (lambda: datetime.now(SHANGHAI_TZ))
        self.max_workers = max(1, min(int(max_workers), 8))

    def run(self, request_or_text: HotlistRequest | str) -> HotlistResult:
        checked_at = self.now_provider().astimezone(SHANGHAI_TZ)
        request = (
            request_or_text
            if isinstance(request_or_text, HotlistRequest)
            else parse_hotlist_request(request_or_text, now=checked_at)
        )
        trace_id = _trace_id(request, checked_at)
        try:
            candidates = self.discovery.discover(request)
        except SearchSourceError as exc:
            return HotlistResult(
                status="pending_manual",
                request=request,
                checked_at=checked_at,
                trace_id=trace_id,
                source_status={
                    "candidate_discovery": {
                        "source": getattr(self.discovery, "source_name", "candidate_discovery"),
                        "status": "blocked",
                        "error_code": exc.code,
                        **({"http_status": exc.http_status} if exc.http_status is not None else {}),
                    }
                },
                reason=exc.reason,
                blocked_source=getattr(self.discovery, "source_name", "candidate_discovery"),
            )
        if not candidates:
            return HotlistResult(
                status="no_verified_results",
                request=request,
                checked_at=checked_at,
                trace_id=trace_id,
                source_status={
                    "candidate_discovery": {
                        "source": getattr(self.discovery, "source_name", "candidate_discovery"),
                        "status": "readable",
                        "candidate_count": 0,
                    }
                },
                reason="公开候选搜索源未发现可回读的平台作品链接。",
            )

        verified: list[HotlistItem] = []
        detail_errors: dict[str, int] = {}
        workers = min(self.max_workers, len(candidates))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(self.detail_reader.read, candidate): candidate for candidate in candidates}
            for future in as_completed(futures):
                try:
                    verified.append(future.result())
                except DetailSourceError as exc:
                    detail_errors[exc.code] = detail_errors.get(exc.code, 0) + 1
                except Exception:
                    detail_errors["HOTLIST_DETAIL_UNEXPECTED"] = detail_errors.get("HOTLIST_DETAIL_UNEXPECTED", 0) + 1

        source_status = {
            "candidate_discovery": {
                "source": getattr(self.discovery, "source_name", "candidate_discovery"),
                "status": "readable",
                "candidate_count": len(candidates),
            },
            "detail_verification": {
                "source": "platform_share_page" if request.platform == "抖音" else "platform_note_page",
                "status": "readable" if verified else "blocked",
                "verified_count": len(verified),
                "failed_count": len(candidates) - len(verified),
                "error_counts": detail_errors,
            },
        }
        if not verified:
            reason = "候选链接已发现，但平台作品页无法核验标题、作者、点赞数和发布时间。"
            if request.platform == "小红书" and detail_errors.get("XHS_DETAIL_BLOCKED"):
                reason = "小红书候选已发现，但作品页要求有效登录态或 xsec_token，当前无法核验榜单事实。"
            return HotlistResult(
                status="pending_manual",
                request=request,
                checked_at=checked_at,
                trace_id=trace_id,
                discovered_count=len(candidates),
                source_status=source_status,
                reason=reason,
                blocked_source="platform_note_page" if request.platform == "小红书" else "platform_share_page",
            )

        keyword_terms = [_normalize_text(term) for term in re.split(r"\s+", request.keyword) if _normalize_text(term)]
        requested_tags = {_normalize_text(tag) for tag in request.tags if _normalize_text(tag)}
        accepted: list[HotlistItem] = []
        rejected = {"keyword": 0, "time": 0, "tags": 0}
        for item in verified:
            searchable = _normalize_text(" ".join((item.title, *item.tags)))
            if keyword_terms and not all(term in searchable for term in keyword_terms):
                rejected["keyword"] += 1
                continue
            if not request.time_window.contains(item.published_at):
                rejected["time"] += 1
                continue
            item_tags = {_normalize_text(tag) for tag in item.tags if _normalize_text(tag)}
            if requested_tags and not requested_tags.intersection(item_tags):
                rejected["tags"] += 1
                continue
            accepted.append(item)

        if request.sort == "likes_desc":
            accepted.sort(key=lambda item: (item.like_count, item.published_at.timestamp(), item.content_id), reverse=True)
        else:
            accepted.sort(key=lambda item: (item.published_at.timestamp(), item.like_count, item.content_id), reverse=True)
        items = tuple(accepted[: request.limit])
        status = "ok" if items else "no_verified_results"
        reason = "" if items else "平台详情可读，但没有作品同时满足关键词、时间和标签筛选。"
        return HotlistResult(
            status=status,
            request=request,
            checked_at=checked_at,
            trace_id=trace_id,
            items=items,
            discovered_count=len(candidates),
            verified_count=len(verified),
            source_status=source_status,
            rejected_counts={key: value for key, value in rejected.items() if value},
            reason=reason,
        )
