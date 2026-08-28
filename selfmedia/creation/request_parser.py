from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from urllib.parse import unquote, urlparse
from zoneinfo import ZoneInfo

from .field_contract import normalize_content_type, normalize_platform, split_tags


CREATION_PATTERN = re.compile(r"^\s*【创作(?:>(?P<platform>小红书|抖音|B站|哔哩哔哩|bilibili))?】")
REQUEST_KEYS = (
    "平台|赛道|类型|内容类型|主体|主题|发布时间|用户想法|想法|"
    "素材/参考|素材参考|参考素材|参考|素材|希望产出|输出要求|目标人群|"
    "关键词|标签|tags|品牌|产品|项目|账号|作者ID|博主|Brief|brief|商务|"
    "source_asset_id|source|来源|素材源ID|SourceAsset来源ID|路径续接ID"
)
KEY_VALUE_RE = re.compile(rf"(?P<key>{REQUEST_KEYS})\s*[=:：]\s*(?P<value>.*?)(?=\s+(?:{REQUEST_KEYS})\s*[=:：]|$)")
KNOWN_PLATFORMS = {"小红书", "抖音", "B站"}
SOURCE_ASSET_ID_RE = re.compile(r"\bsource_asset[_-][A-Za-z0-9_.:-]+\b")


@dataclass(frozen=True)
class CreationRequest:
    platform: str
    content_type: str
    track: str
    topic: str
    publish_time: str
    user_idea: str = ""
    keywords: list[str] | None = None
    brand: str = ""
    product: str = ""
    project: str = ""
    account: str = ""
    brief: str = ""
    business_note: str = ""
    source_asset_id: str = ""
    raw_text: str = ""

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["keywords"] = list(self.keywords or [])
        return payload



def parse_creation_request(
    raw_text: str,
    *,
    now: datetime | None = None,
    timezone_name: str = "Asia/Shanghai",
    inferred_values: dict[str, object] | None = None,
) -> CreationRequest:
    text = raw_text.strip()
    match = CREATION_PATTERN.match(text)
    if not match:
        raise ValueError("不是【创作】入口")
    platform_hint = normalize_platform(match.group("platform") or "")
    body = text[match.end():].strip()
    values = _parse_key_values(body)
    inferred = _normalize_inferred_values(inferred_values or {})
    platform_source = values.get("平台") or platform_hint
    platform = normalize_platform(platform_source) or inferred.get("平台", "")
    raw_content_type = values.get("内容类型") or values.get("类型") or ""
    content_type = normalize_content_type(raw_content_type) or inferred.get("内容类型", "")
    if not platform:
        raise ValueError("【创作】必须能解析出平台，请使用【创作>小红书】、【创作>抖音】、【创作>B站】或填写 平台=小红书/抖音/B站")
    if platform not in KNOWN_PLATFORMS:
        raise ValueError("【创作】平台只支持 小红书、抖音 或 B站")
    if not content_type:
        raise ValueError("【创作】缺少内容类型")
    if content_type not in {"图文", "视频"}:
        raise ValueError("【创作】v1 的内容类型只支持 图文 或 视频")
    topic = (values.get("主体") or values.get("主题") or "").strip() or inferred.get("主题", "")
    track = (values.get("赛道") or "").strip() or inferred.get("赛道", "")
    if not track:
        raise ValueError("【创作】缺少赛道")
    if not topic:
        raise ValueError("【创作】缺少主体/主题")
    tz = ZoneInfo(timezone_name)
    base_now = now or datetime.now(tz)
    publish_time = normalize_publish_time(values.get("发布时间") or inferred.get("发布时间", "") or "", base_now, tz)
    user_idea = _join_labeled_notes(
        (
            ("用户想法", values.get("用户想法") or values.get("想法") or inferred.get("用户想法", "")),
            ("目标人群", values.get("目标人群", "")),
            ("希望产出", values.get("希望产出") or values.get("输出要求") or ""),
            ("素材/参考", values.get("素材/参考") or values.get("素材参考") or values.get("参考素材") or values.get("参考") or values.get("素材") or ""),
        )
    )
    brand = (values.get("品牌") or inferred.get("品牌", "")).strip()
    product = (values.get("产品") or inferred.get("产品", "")).strip()
    project = (values.get("项目") or inferred.get("项目", "")).strip()
    account = (values.get("账号") or values.get("作者ID") or values.get("博主") or inferred.get("账号", "")).strip()
    brief = (
        values.get("Brief")
        or values.get("brief")
        or values.get("素材/参考")
        or values.get("素材参考")
        or values.get("参考素材")
        or values.get("参考")
        or values.get("素材")
        or inferred.get("Brief", "")
    ).strip()
    business_note = (values.get("商务") or inferred.get("商务", "")).strip()
    keywords = split_tags(values.get("关键词") or values.get("标签") or values.get("tags") or inferred.get("关键词", "") or " ".join([track, topic, brand, product, project, account]))
    source_asset_id = extract_source_asset_id(
        raw_text,
        values.get("source_asset_id")
        or values.get("SourceAsset来源ID")
        or values.get("素材源ID")
        or values.get("source")
        or values.get("来源")
        or inferred.get("source_asset_id", "")
    )
    return CreationRequest(
        platform=platform,
        content_type=content_type,
        track=track,
        topic=topic,
        publish_time=publish_time,
        user_idea=user_idea,
        keywords=keywords,
        brand=brand,
        product=product,
        project=project,
        account=account,
        brief=brief,
        business_note=business_note,
        source_asset_id=source_asset_id,
        raw_text=raw_text,
    )


def _parse_key_values(body: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for match in KEY_VALUE_RE.finditer(body):
        key = match.group("key").strip()
        value = match.group("value").strip()
        if value:
            values[key] = value
    return values




def _join_labeled_notes(items: tuple[tuple[str, object], ...]) -> str:
    lines: list[str] = []
    for label, raw_value in items:
        value = str(raw_value or "").strip()
        if not value:
            continue
        if label == "用户想法":
            lines.append(value)
        else:
            lines.append(f"{label}：{value}")
    return "\n".join(lines)


def _normalize_inferred_values(values: dict[str, object]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    alias_map = {
        "platform": "平台",
        "content_type": "内容类型",
        "track": "赛道",
        "topic": "主题",
        "publish_time": "发布时间",
        "user_idea": "用户想法",
        "keywords": "关键词",
        "brand": "品牌",
        "product": "产品",
        "project": "项目",
        "account": "账号",
        "brief": "Brief",
        "business_note": "商务",
        "source_asset_id": "source_asset_id",
    }
    for raw_key, raw_value in values.items():
        key = alias_map.get(str(raw_key), str(raw_key))
        if isinstance(raw_value, list):
            value = " ".join(str(item).strip() for item in raw_value if str(item).strip())
        else:
            value = str(raw_value or "").strip()
        if not value:
            continue
        if key == "平台":
            value = normalize_platform(value)
            if value not in KNOWN_PLATFORMS:
                value = ""
        elif key == "内容类型":
            value = normalize_content_type(value)
            if value not in {"图文", "视频"}:
                value = ""
        if value:
            normalized[key] = value
    return normalized


def extract_source_asset_id(raw_text: str, explicit_value: object = "") -> str:
    for candidate in (explicit_value, raw_text):
        normalized = _normalize_source_asset_ref(str(candidate or ""))
        if normalized:
            return normalized
    return ""


def _normalize_source_asset_ref(value: str) -> str:
    text = str(value or "").strip().strip("`")
    if not text:
        return ""
    parsed = urlparse(text)
    if parsed.scheme == "media":
        parts = [unquote(part) for part in (parsed.netloc, *parsed.path.split("/")) if part]
        if parts and parts[0] == "source_assets" and len(parts) >= 2:
            return parts[1]
        return ""
    match = SOURCE_ASSET_ID_RE.search(text)
    return match.group(0) if match else ""


def normalize_publish_time(raw: str, now: datetime, tz: ZoneInfo) -> str:
    text = raw.strip()
    if not text:
        return ""
    period_hint = ""
    if any(item in text for item in ("下午", "晚上", "今晚")):
        period_hint = "下午"
    normalized = text.replace("今晚", "今天").replace("中午", "12点").replace("上午", "").replace("下午", "").replace("晚上", "")
    relative_day = 0
    if normalized.startswith("今天"):
        relative_day = 0
        normalized = normalized[len("今天"):].strip()
    elif normalized.startswith("明天"):
        relative_day = 1
        normalized = normalized[len("明天"):].strip()
    elif normalized.startswith("后天"):
        relative_day = 2
        normalized = normalized[len("后天"):].strip()
    if relative_day or raw.startswith(("今天", "今晚", "明天", "后天")):
        hour, minute = _parse_chinese_time(normalized + period_hint)
        dt = (now + timedelta(days=relative_day)).replace(hour=hour, minute=minute, second=0, microsecond=0)
        return dt.isoformat(timespec="minutes")
    for fmt in ("%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(text, fmt)
        except ValueError:
            continue
        return dt.replace(tzinfo=tz).isoformat(timespec="minutes")
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    return dt.astimezone(tz).isoformat(timespec="minutes")


def _parse_chinese_time(text: str) -> tuple[int, int]:
    match = re.search(r"(?P<hour>\d{1,2})(?:[:：点](?P<minute>\d{1,2})?)?", text)
    if not match:
        return 20, 0
    hour = int(match.group("hour"))
    minute = int(match.group("minute") or 0)
    if "下午" in text and hour < 12:
        hour += 12
    if "晚上" in text and hour < 12:
        hour += 12
    return min(max(hour, 0), 23), min(max(minute, 0), 59)
