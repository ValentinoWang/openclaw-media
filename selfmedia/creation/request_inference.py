from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from .field_contract import normalize_content_type, normalize_platform, split_tags
from .llm_generator import call_creation_json
from .request_parser import CREATION_PATTERN, KEY_VALUE_RE, CreationRequest, parse_creation_request


def parse_creation_request_with_llm(
    raw_text: str,
    *,
    now: datetime | None = None,
    timezone_name: str = "Asia/Shanghai",
) -> CreationRequest:
    inferred: dict[str, Any] = {}
    if _needs_llm_inference(raw_text):
        inferred = infer_creation_request_fields(raw_text)
    return parse_creation_request(raw_text, now=now, timezone_name=timezone_name, inferred_values=inferred)


def infer_creation_request_fields(raw_text: str) -> dict[str, Any]:
    prompt = build_request_inference_prompt(raw_text)
    payload = call_creation_json(prompt)
    return normalize_inferred_creation_fields(payload)


def build_request_inference_prompt(raw_text: str) -> str:
    explicit = _explicit_payload(raw_text)
    return (
        "你是自媒体创作入口的请求解析器。任务是把用户的【创作】消息补全成结构化字段，"
        "只做字段理解，不写稿，不扩写创意。\n\n"
        "规则：\n"
        "1. 只能根据用户原文推断；不确定就留空字符串，不要编造账号、品牌、发布时间、链接内容或外部事实。\n"
        "2. platform 只能是 小红书、抖音 或空字符串。用户明确写了平台时必须尊重。\n"
        "3. content_type 只能是 图文、视频 或空字符串。视频脚本、镜头、字幕、开头几秒、素材剪辑通常是 视频；笔记、首图、页卡通常是 图文。\n"
        "4. track 是粗粒度赛道，例如 体育、职场成长、亲子教育、美妆护肤、旅行、美食、教育；不确定可留空。\n"
        "5. topic 是本次要创作的具体主体/主题，要短而具体，优先抽取用户说的「主题/主体/聚焦/围绕」内容。\n"
        "6. user_idea 保留用户对创作方向、素材选择、禁忌、字幕、开头、风格的补充要求。\n"
        "7. keywords 输出 3-10 个从原文抽取或高度贴近原文的关键词。\n"
        "8. 只输出合法 JSON object，不要 Markdown，不要解释。\n\n"
        "输出字段固定为：platform, content_type, track, topic, publish_time, user_idea, "
        "keywords, brand, product, project, account, brief, business_note。\n\n"
        f"已解析到的显式字段：\n{json.dumps(explicit, ensure_ascii=False, indent=2)}\n\n"
        f"用户原文：\n{raw_text}"
    )


def normalize_inferred_creation_fields(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    platform = normalize_platform(payload.get("platform") or payload.get("平台") or "")
    if platform not in {"小红书", "抖音"}:
        platform = ""
    content_type = normalize_content_type(payload.get("content_type") or payload.get("内容类型") or "")
    if content_type not in {"图文", "视频"}:
        content_type = ""
    normalized = {
        "platform": platform,
        "content_type": content_type,
        "track": _clean_text(payload.get("track") or payload.get("赛道") or "", 40),
        "topic": _clean_text(payload.get("topic") or payload.get("主题") or payload.get("主体") or "", 80),
        "publish_time": _clean_text(payload.get("publish_time") or payload.get("发布时间") or "", 60),
        "user_idea": _clean_text(payload.get("user_idea") or payload.get("用户想法") or payload.get("想法") or "", 1200),
        "keywords": split_tags(payload.get("keywords") or payload.get("关键词") or payload.get("标签") or "")[:10],
        "brand": _clean_text(payload.get("brand") or payload.get("品牌") or "", 80),
        "product": _clean_text(payload.get("product") or payload.get("产品") or "", 80),
        "project": _clean_text(payload.get("project") or payload.get("项目") or "", 80),
        "account": _clean_text(payload.get("account") or payload.get("账号") or payload.get("作者ID") or payload.get("博主") or "", 80),
        "brief": _clean_text(payload.get("brief") or payload.get("Brief") or "", 1000),
        "business_note": _clean_text(payload.get("business_note") or payload.get("商务") or "", 1000),
    }
    return {key: value for key, value in normalized.items() if value}


def _needs_llm_inference(raw_text: str) -> bool:
    text = (raw_text or "").strip()
    match = CREATION_PATTERN.match(text)
    if not match:
        return False
    body = text[match.end() :].strip()
    values = {field_match.group("key").strip(): field_match.group("value").strip() for field_match in KEY_VALUE_RE.finditer(body)}
    platform = normalize_platform(values.get("平台") or match.group("platform") or "")
    has_content_type = bool(normalize_content_type(values.get("内容类型") or values.get("类型") or ""))
    has_topic = bool((values.get("主体") or values.get("主题") or "").strip())
    has_track = bool((values.get("赛道") or "").strip())
    return not (platform and has_content_type and has_track and has_topic)


def _explicit_payload(raw_text: str) -> dict[str, Any]:
    text = (raw_text or "").strip()
    match = CREATION_PATTERN.match(text)
    if not match:
        return {}
    body = text[match.end() :].strip()
    values = {field_match.group("key").strip(): field_match.group("value").strip() for field_match in KEY_VALUE_RE.finditer(body)}
    if match.group("platform"):
        values["入口平台"] = match.group("platform")
    return values


def _clean_text(value: Any, limit: int) -> str:
    if isinstance(value, list):
        text = " ".join(str(item).strip() for item in value if str(item).strip())
    else:
        text = str(value or "").strip()
    return text[:limit]
