from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MEMORY_ROOT = ROOT / "data" / "media_memory"
MEDIA_AGENT_ROOT = Path("/home/ubuntu/openclaw-agents/media")
TAG_RE = re.compile(r"^\s*【[^】\n]{1,32}】")
REQUEST_KEYS = (
    "平台|账号|作者ID|博主|赛道|类型|内容类型|主体|主题|标题|发布时间|发布链接|作品链接|"
    "创作记录ID|作品档案|数据|表现|问题|结论|经验|改进|下一步|用户想法|想法|关键词|标签|品牌|产品|项目"
    "|播放量|播放|阅读量|阅读|曝光|点赞|赞|收藏|评论|分享|转发|完播率|互动率|新增关注|涨粉"
)
KEY_VALUE_RE = re.compile(rf"(?P<key>{REQUEST_KEYS})\s*[=:：]\s*(?P<value>.*?)(?=\s+(?:{REQUEST_KEYS})\s*[=:：]|$)")
METRIC_RE = re.compile(
    r"(?P<key>播放量|播放|阅读量|阅读|曝光|点赞|赞|收藏|评论|分享|转发|完播率|互动率|新增关注|涨粉)"
    r"\s*[=:：]?\s*(?P<value>[0-9]+(?:\.[0-9]+)?\s*(?:万|w|W|%|％)?)"
)
MEDIA_REVIEW_KEYWORDS = (
    "小红书",
    "抖音",
    "视频",
    "图文",
    "发布链接",
    "作品链接",
    "创作记录",
    "作品档案",
    "播放",
    "阅读",
    "点赞",
    "收藏",
    "评论",
    "分享",
    "完播",
    "互动率",
    "账号",
)


def build_media_context_for_request(request: Any, *, root: str | Path | None = None, limit: int = 5) -> dict[str, Any]:
    return build_media_context(
        platform=str(getattr(request, "platform", "") or ""),
        account=str(getattr(request, "account", "") or ""),
        track=str(getattr(request, "track", "") or ""),
        topic=str(getattr(request, "topic", "") or ""),
        keywords=list(getattr(request, "keywords", None) or []),
        root=root,
        limit=limit,
    )


def build_media_context(
    *,
    platform: str = "",
    account: str = "",
    track: str = "",
    topic: str = "",
    keywords: list[str] | None = None,
    root: str | Path | None = None,
    limit: int = 5,
) -> dict[str, Any]:
    memory_root = _memory_root(root)
    platform = _clean_text(platform)
    account = _clean_text(account)
    profile = load_account_profile(platform, account, root=memory_root, ensure_markdown=True) if account else {}
    query_terms = _dedupe([track, topic, *(keywords or [])])
    creations = _recent_matching(
        _iter_jsonl(memory_root / "creations.jsonl"),
        platform=platform,
        account=account,
        query_terms=query_terms,
        limit=limit,
    )
    reviews = _recent_matching(
        _iter_jsonl(memory_root / "reviews.jsonl"),
        platform=platform,
        account=account,
        query_terms=query_terms,
        limit=limit,
    )
    context = {
        "platform": platform,
        "account": account,
        "track": _clean_text(track),
        "topic": _clean_text(topic),
        "keywords": query_terms,
        "memory_root": str(memory_root),
        "account_profile": profile,
        "recent_creations": creations,
        "recent_reviews": reviews,
        "global_rules": _load_media_rule_snippets(),
        "loaded": {
            "account_profile": bool(profile),
            "recent_creations": len(creations),
            "recent_reviews": len(reviews),
        },
    }
    context["prompt"] = render_context_for_prompt(context)
    return context


def merge_conversation_context(media_context: dict[str, Any], conversation_context: dict[str, Any] | None) -> dict[str, Any]:
    if not conversation_context:
        return media_context
    context = dict(media_context)
    loaded_count = int(conversation_context.get("loaded_count") or len(conversation_context.get("items") or []))
    context["conversation_context"] = conversation_context
    loaded = dict(context.get("loaded") or {})
    loaded["conversation_context"] = loaded_count
    context["loaded"] = loaded
    prompt = str(context.get("prompt") or "").strip()
    conversation_prompt = str(conversation_context.get("prompt") or "").strip()
    if conversation_prompt:
        context["prompt"] = (prompt + "\n\n" + conversation_prompt).strip() if prompt else conversation_prompt
    return context


def render_context_for_prompt(context: dict[str, Any], *, max_chars: int = 2600) -> str:
    profile = context.get("account_profile") or {}
    creations = context.get("recent_creations") or []
    reviews = context.get("recent_reviews") or []
    rules = context.get("global_rules") or []
    lines = ["媒体长期上下文："]
    if profile:
        lines.extend(
            [
                f"- 账号ID：{profile.get('profile_id') or profile.get('account') or context.get('account')}",
                f"- 账号：{profile.get('platform') or context.get('platform')}/{profile.get('account') or context.get('account')}",
                f"- Markdown档案：{profile.get('markdown_path') or '未建立'}",
                f"- 账号定位：{profile.get('positioning_summary') or '未沉淀'}",
                f"- 核心受众：{_join(profile.get('target_audience')) or '未沉淀'}",
                f"- 内容支柱：{_join(profile.get('content_pillars')) or '未沉淀'}",
                f"- 已验证有效模式：{_join(profile.get('proven_patterns')) or '未沉淀'}",
                f"- 需要规避：{_join(profile.get('avoid_patterns')) or '未沉淀'}",
                f"- 最近复盘结论：{_join(profile.get('recent_lessons'), limit=4) or '未沉淀'}",
            ]
        )
        markdown_profile = _clean_text(profile.get("markdown"))
        if markdown_profile:
            lines.append("- 账号 Markdown 档案原文：")
            lines.append(markdown_profile[:1200])
    else:
        lines.append("- 账号画像：未找到；若要连续复盘，请在消息中填写 账号=xxx。")
    if reviews:
        lines.append("- 相关历史复盘：")
        for item in reviews[:4]:
            lines.append(f"  {item.get('created_at', '')[:10]} {item.get('topic') or item.get('title') or '未命名作品'}：{item.get('lesson') or item.get('summary') or ''}")
    if creations:
        lines.append("- 相关历史创作：")
        for item in creations[:3]:
            lines.append(f"  {item.get('created_at', '')[:10]} {item.get('topic') or '未命名'}：{item.get('title') or item.get('doc_link') or item.get('creation_id') or ''}")
    if rules:
        lines.append("- 媒体 Bot 长期规则摘要：")
        lines.extend(f"  {item}" for item in rules[:4])
    lines.append("生成要求：必须显式继承账号定位和复盘结论；如果没有账号画像，先指出需要补齐的人设/栏目/目标受众。")
    text = "\n".join(line for line in lines if line is not None)
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 20].rstrip() + "\n...（上下文已截断）"


def record_creation_memory(
    request: Any,
    *,
    draft: dict[str, Any] | None = None,
    analysis: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
    doc_link: str = "",
    creation_record_id: str = "",
    source_paths: list[str] | None = None,
    validation: dict[str, Any] | None = None,
    root: str | Path | None = None,
) -> dict[str, Any]:
    memory_root = _memory_root(root)
    memory_root.mkdir(parents=True, exist_ok=True)
    draft = draft or {}
    analysis = analysis or {}
    platform = _clean_text(getattr(request, "platform", "") or "")
    account = _clean_text(getattr(request, "account", "") or "")
    record = {
        "creation_id": creation_record_id or _stable_id("creation", [platform, account, getattr(request, "topic", ""), doc_link, _now_iso()]),
        "created_at": _now_iso(),
        "platform": platform,
        "account": account,
        "content_type": _clean_text(getattr(request, "content_type", "") or ""),
        "track": _clean_text(getattr(request, "track", "") or ""),
        "topic": _clean_text(getattr(request, "topic", "") or ""),
        "title": _clean_text(draft.get("title") or analysis.get("title") or ""),
        "tags": _dedupe(list(getattr(request, "keywords", None) or []) + list(draft.get("tags") or [])),
        "doc_link": doc_link,
        "creation_record_id": creation_record_id,
        "source_paths": list(source_paths or []),
        "positioning": _clean_text(_nested_get(draft, ["positioning_analysis", "positioning"]) or analysis.get("positioning") or ""),
        "account_fit": _clean_text(_nested_get(draft, ["positioning_analysis", "account_fit"]) or analysis.get("account_fit") or ""),
        "review_plan": _as_list(draft.get("review_plan") or analysis.get("review_plan")),
        "validation_ok": bool((validation or {}).get("ok", True)),
        "context_loaded": (context or {}).get("loaded") or {},
    }
    _append_jsonl(memory_root / "creations.jsonl", record)
    profile_result = {}
    if account:
        profile_result = upsert_account_profile(
            platform=platform,
            account=account,
            creation=record,
            analysis=analysis,
            draft=draft,
            root=memory_root,
        )
    return {
        "status": "recorded",
        "creation_id": record["creation_id"],
        "path": str(memory_root / "creations.jsonl"),
        "profile": profile_result,
    }


def record_review_memory(
    raw_text: str,
    *,
    source: str = "",
    root: str | Path | None = None,
) -> dict[str, Any]:
    memory_root = _memory_root(root)
    memory_root.mkdir(parents=True, exist_ok=True)
    parsed = parse_media_review(raw_text)
    review = {
        "review_id": _stable_id("review", [parsed.get("platform", ""), parsed.get("account", ""), parsed.get("publish_url", ""), raw_text, _now_iso()]),
        "created_at": _now_iso(),
        "source": source,
        **parsed,
    }
    _append_jsonl(memory_root / "reviews.jsonl", review)
    profile_result = {}
    if review.get("account"):
        profile_result = upsert_account_profile(
            platform=review.get("platform", ""),
            account=review.get("account", ""),
            review=review,
            root=memory_root,
        )
    return {
        "status": "recorded",
        "review_id": review["review_id"],
        "path": str(memory_root / "reviews.jsonl"),
        "review": review,
        "profile": profile_result,
        "reply": format_review_reply(review, profile_result),
    }


def looks_like_media_review(text: str) -> bool:
    body = _strip_tag(text)
    values = _parse_key_values(body)
    if any(key in values for key in ("账号", "作者ID", "博主", "平台", "发布链接", "作品链接", "创作记录ID", "作品档案")):
        return True
    keyword_hits = sum(1 for keyword in MEDIA_REVIEW_KEYWORDS if keyword in body)
    metric_hits = len(METRIC_RE.findall(body))
    return keyword_hits >= 2 or metric_hits >= 2


def parse_media_review(raw_text: str) -> dict[str, Any]:
    body = _strip_tag(raw_text)
    values = _parse_key_values(body)
    platform = _clean_text(values.get("平台") or _infer_platform(body))
    account = _clean_text(values.get("账号") or values.get("作者ID") or values.get("博主") or "")
    track = _clean_text(values.get("赛道") or "")
    topic = _clean_text(values.get("主体") or values.get("主题") or values.get("标题") or "")
    publish_url = _clean_text(values.get("发布链接") or values.get("作品链接") or _first_url(body))
    metrics = _parse_metrics(body)
    lesson = _first_non_empty(values, ("结论", "经验", "改进", "下一步", "问题"))
    summary = lesson or _clean_text(values.get("表现") or values.get("数据") or body)
    return {
        "platform": platform,
        "account": account,
        "track": track,
        "topic": topic,
        "content_type": _clean_text(values.get("内容类型") or values.get("类型") or _infer_content_type(body)),
        "title": _clean_text(values.get("标题") or topic),
        "publish_time": _clean_text(values.get("发布时间") or ""),
        "publish_url": publish_url,
        "creation_record_id": _clean_text(values.get("创作记录ID") or values.get("作品档案") or ""),
        "metrics": metrics,
        "performance": _clean_text(values.get("表现") or values.get("数据") or ""),
        "problem": _clean_text(values.get("问题") or ""),
        "lesson": _clean_text(lesson),
        "next_step": _clean_text(values.get("下一步") or ""),
        "summary": _clean_text(summary)[:1000],
        "raw_text": raw_text,
    }


def upsert_account_profile(
    *,
    platform: str,
    account: str,
    creation: dict[str, Any] | None = None,
    review: dict[str, Any] | None = None,
    analysis: dict[str, Any] | None = None,
    draft: dict[str, Any] | None = None,
    root: str | Path | None = None,
) -> dict[str, Any]:
    memory_root = _memory_root(root)
    platform = _clean_text(platform)
    account = _clean_text(account)
    if not account:
        return {"status": "skipped", "reason": "missing_account"}
    path = _account_profile_path(memory_root, platform, account)
    profile = _read_json(path, default={}) or {}
    now = _now_iso()
    if not profile:
        profile = {
            "account": account,
            "platform": platform,
            "created_at": now,
            "updated_at": now,
            "positioning_summary": "",
            "target_audience": [],
            "content_pillars": [],
            "tracks": [],
            "topics": [],
            "keywords": [],
            "brands": [],
            "products": [],
            "projects": [],
            "proven_patterns": [],
            "avoid_patterns": [],
            "recent_lessons": [],
            "recent_creation_ids": [],
            "recent_review_ids": [],
        }
    profile["platform"] = platform or profile.get("platform", "")
    profile["account"] = account
    profile["updated_at"] = now
    analysis = analysis or {}
    draft = draft or {}
    if creation:
        _merge_list(profile, "tracks", [creation.get("track")])
        _merge_list(profile, "topics", [creation.get("topic")])
        _merge_list(profile, "keywords", creation.get("tags") or [])
        _merge_list(profile, "recent_creation_ids", [creation.get("creation_id")], max_len=20)
        positioning = _clean_text(creation.get("positioning") or analysis.get("positioning") or _nested_get(draft, ["positioning_analysis", "positioning"]) or "")
        if positioning and not profile.get("positioning_summary"):
            profile["positioning_summary"] = positioning[:300]
        _merge_list(profile, "target_audience", _as_list(analysis.get("target_audience") or _nested_get(draft, ["positioning_analysis", "target_audience"])), max_len=20)
        _merge_list(profile, "content_pillars", _as_list(analysis.get("content_angles") or _nested_get(draft, ["positioning_analysis", "content_angles"])), max_len=20)
    if review:
        _merge_list(profile, "tracks", [review.get("track")])
        _merge_list(profile, "topics", [review.get("topic")])
        _merge_list(profile, "recent_review_ids", [review.get("review_id")], max_len=30)
        lesson = _clean_text(review.get("lesson") or review.get("summary") or "")
        if lesson:
            _merge_list(profile, "recent_lessons", [lesson], max_len=12)
        raw = str(review.get("raw_text") or "")
        if any(word in raw for word in ("有效", "表现好", "高", "爆", "转化好", "收藏高", "评论好", "完播高")):
            _merge_list(profile, "proven_patterns", [lesson or review.get("summary")], max_len=12)
        if any(word in raw for word in ("无效", "表现差", "低", "失败", "流失", "不适合", "别再", "不要")):
            _merge_list(profile, "avoid_patterns", [lesson or review.get("summary")], max_len=12)
        profile["last_reviewed_at"] = now
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_json_atomic(path, profile)
    markdown_path = _write_account_profile_markdown(memory_root, platform, account, profile)
    return {
        "status": "updated",
        "path": str(path),
        "markdown_path": str(markdown_path),
        "profile_id": _account_profile_id(platform, account),
        "account": account,
        "platform": platform,
    }


def load_account_profile(platform: str, account: str, *, root: str | Path | None = None, ensure_markdown: bool = False) -> dict[str, Any]:
    memory_root = _memory_root(root)
    path = _account_profile_path(memory_root, platform, account)
    profile = _read_json(path, default={}) or {}
    markdown_path = _account_profile_markdown_path(memory_root, platform, account)
    if ensure_markdown:
        _ensure_account_profile_markdown(markdown_path, platform, account)
    markdown = markdown_path.read_text(encoding="utf-8") if markdown_path.exists() else ""
    if markdown or ensure_markdown:
        profile = {
            "platform": platform or profile.get("platform", ""),
            "account": account or profile.get("account", ""),
            **profile,
            "profile_id": _account_profile_id(platform, account),
            "markdown_path": str(markdown_path),
            "markdown": markdown,
        }
    return profile


def format_review_reply(review: dict[str, Any], profile_result: dict[str, Any]) -> str:
    lines = [
        "【复盘】已写入媒体账号记忆",
        f"平台：{review.get('platform') or '未识别'}",
        f"账号：{review.get('account') or '未填写'}",
        f"作品：{review.get('topic') or review.get('title') or '未填写'}",
    ]
    if review.get("metrics"):
        lines.append("数据：" + "、".join(f"{key}={value}" for key, value in review["metrics"].items()))
    if review.get("lesson"):
        lines.append(f"复盘结论：{review['lesson']}")
    if profile_result.get("path"):
        lines.append(f"账号画像：{profile_result['path']}")
    else:
        lines.append("账号画像：未更新，建议补充 账号=xxx")
    return "\n".join(lines)


def format_media_context_reply(context: dict[str, Any]) -> str:
    loaded = context.get("loaded") or {}
    lines = [
        "【媒体上下文】已加载",
        f"平台：{context.get('platform') or '未指定'}",
        f"账号：{context.get('account') or '未指定'}",
        f"账号画像：{'有' if loaded.get('account_profile') else '无'}",
        f"历史创作：{loaded.get('recent_creations', 0)} 条",
        f"历史复盘：{loaded.get('recent_reviews', 0)} 条",
        f"存储目录：{context.get('memory_root')}",
        "",
        context.get("prompt") or "",
    ]
    return "\n".join(lines).strip()


def _memory_root(root: str | Path | None = None) -> Path:
    if root:
        return Path(root).expanduser()
    if os.getenv("SELFMEDIA_MEMORY_ROOT"):
        return Path(os.environ["SELFMEDIA_MEMORY_ROOT"]).expanduser()
    return DEFAULT_MEMORY_ROOT


def _load_media_rule_snippets() -> list[str]:
    snippets: list[str] = []
    for path in (MEDIA_AGENT_ROOT / "USER.md", MEDIA_AGENT_ROOT / "MEMORY.md"):
        if not path.exists():
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            clean = line.strip()
            if not clean.startswith("-"):
                continue
            if any(keyword in clean for keyword in ("通用标签", "任意 Bot", "只做唤醒", "tag-router", "main/OpenClaw", "ID+商务", "商务账号", "报价", "品牌方")):
                continue
            if any(keyword in clean for keyword in ("账号", "复盘", "创作", "素材", "小红书", "抖音")):
                snippets.append(clean[:240])
            if len(snippets) >= 8:
                return snippets
    return snippets


def _recent_matching(rows: list[dict[str, Any]], *, platform: str, account: str, query_terms: list[str], limit: int) -> list[dict[str, Any]]:
    def score(row: dict[str, Any]) -> int:
        value = 0
        if account and _clean_text(row.get("account")) == account:
            value += 8
        if platform and _clean_text(row.get("platform")) == platform:
            value += 3
        haystack = " ".join(
            [
                str(row.get("track") or ""),
                str(row.get("topic") or ""),
                str(row.get("title") or ""),
                " ".join(str(item) for item in row.get("tags") or []),
                str(row.get("summary") or ""),
                str(row.get("lesson") or ""),
            ]
        )
        value += sum(1 for term in query_terms if term and term in haystack)
        return value

    ranked = [(score(row), row) for row in rows]
    filtered = [row for item_score, row in ranked if item_score > 0 or (not account and not platform and not query_terms)]
    filtered.sort(key=lambda row: str(row.get("created_at") or ""), reverse=True)
    filtered.sort(key=score, reverse=True)
    return [_public_context_row(row) for row in filtered[:limit]]


def _public_context_row(row: dict[str, Any]) -> dict[str, Any]:
    keep = (
        "creation_id",
        "review_id",
        "created_at",
        "platform",
        "account",
        "content_type",
        "track",
        "topic",
        "title",
        "tags",
        "doc_link",
        "publish_url",
        "metrics",
        "lesson",
        "summary",
        "positioning",
        "account_fit",
    )
    return {key: row.get(key) for key in keep if row.get(key) not in (None, "", [])}


def _parse_key_values(body: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for match in KEY_VALUE_RE.finditer(body):
        key = match.group("key").strip()
        value = match.group("value").strip()
        if value:
            values[key] = value
    return values


def _parse_metrics(text: str) -> dict[str, str]:
    metrics: dict[str, str] = {}
    for match in METRIC_RE.finditer(text):
        key = match.group("key").strip()
        value = match.group("value").replace(" ", "").strip()
        metrics[key] = value
    return metrics


def _infer_platform(text: str) -> str:
    if "小红书" in text or "xhslink" in text:
        return "小红书"
    if "抖音" in text or "douyin" in text:
        return "抖音"
    return ""


def _infer_content_type(text: str) -> str:
    if "图文" in text or "首图" in text:
        return "图文"
    if "视频" in text or "完播" in text or "前5秒" in text:
        return "视频"
    return ""


def _first_url(text: str) -> str:
    match = re.search(r"https?://\S+", text)
    return match.group(0).rstrip("，。；;") if match else ""


def _first_non_empty(values: dict[str, str], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = _clean_text(values.get(key))
        if value:
            return value
    return ""


def _strip_tag(text: str) -> str:
    return TAG_RE.sub("", text or "", count=1).strip()


def _account_profile_path(root: Path, platform: str, account: str) -> Path:
    key = _slugify("|".join([platform, account]))
    return root / "accounts" / f"{key}.json"


def _account_profile_markdown_path(root: Path, platform: str, account: str) -> Path:
    key = _slugify("|".join([platform, account]))
    return root / "account_profiles" / f"{key}.md"


def _account_profile_id(platform: str, account: str) -> str:
    return _stable_id("media-account", [platform, account])


def _ensure_account_profile_markdown(path: Path, platform: str, account: str) -> None:
    if path.exists():
        return
    now = _now_iso()
    profile_id = _account_profile_id(platform, account)
    content = (
        f"# 媒体账号档案：{platform or '未填写平台'} / {account or '未填写账号'}\n\n"
        f"- 账号ID：{profile_id}\n"
        f"- 平台：{platform or '未填写'}\n"
        f"- 账号：{account or '未填写'}\n"
        f"- 创建时间：{now}\n"
        f"- 更新时间：{now}\n\n"
        "## 定位\n\n"
        "待补充账号定位、人设边界、主栏目和表达风格。\n\n"
        "## 目标受众\n\n"
        "- 待补充\n\n"
        "## 内容支柱\n\n"
        "- 待补充\n\n"
        "## 已验证有效模式\n\n"
        "- 待复盘沉淀\n\n"
        "## 需要规避\n\n"
        "- 待复盘沉淀\n\n"
        "## 最近复盘结论\n\n"
        "- 待复盘沉淀\n"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_account_profile_markdown(root: Path, platform: str, account: str, profile: dict[str, Any]) -> Path:
    path = _account_profile_markdown_path(root, platform, account)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    marker = "<!-- OpenClaw 自动摘要 -->"
    summary = _markdown_profile_summary(platform, account, profile)
    if marker in existing:
        updated = re.sub(r"<!-- OpenClaw 自动摘要 -->.*?<!-- /OpenClaw 自动摘要 -->", summary, existing, flags=re.S)
    else:
        base = existing.rstrip() if existing else ""
        updated = f"{base}\n\n{summary}\n" if base else summary + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(updated.rstrip() + "\n", encoding="utf-8")
    return path


def _markdown_profile_summary(platform: str, account: str, profile: dict[str, Any]) -> str:
    now = _now_iso()
    lines = [
        "<!-- OpenClaw 自动摘要 -->",
        "## OpenClaw 自动摘要",
        "",
        f"- 账号ID：{_account_profile_id(platform, account)}",
        f"- 平台：{platform or profile.get('platform') or '未填写'}",
        f"- 账号：{account or profile.get('account') or '未填写'}",
        f"- 更新时间：{now}",
        f"- 账号定位：{profile.get('positioning_summary') or '未沉淀'}",
        f"- 目标受众：{_join(profile.get('target_audience')) or '未沉淀'}",
        f"- 内容支柱：{_join(profile.get('content_pillars')) or '未沉淀'}",
        f"- 已验证有效模式：{_join(profile.get('proven_patterns')) or '未沉淀'}",
        f"- 需要规避：{_join(profile.get('avoid_patterns')) or '未沉淀'}",
        f"- 最近复盘结论：{_join(profile.get('recent_lessons'), limit=8) or '未沉淀'}",
        "",
        "<!-- /OpenClaw 自动摘要 -->",
    ]
    return "\n".join(lines)


def _append_jsonl(path: Path, item: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")


def _iter_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                rows.append(item)
    return rows


def _read_json(path: Path, *, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=str(path.parent), delete=False) as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")
        tmp_name = fh.name
    Path(tmp_name).replace(path)


def _merge_list(profile: dict[str, Any], key: str, values: list[Any], *, max_len: int = 30) -> None:
    existing = _as_list(profile.get(key))
    for value in values:
        clean = _clean_text(value)
        if clean and clean not in existing:
            existing.insert(0, clean)
    profile[key] = existing[:max_len]


def _as_list(value: Any) -> list[str]:
    if value in (None, "", []):
        return []
    if isinstance(value, list):
        return [_clean_text(item) for item in value if _clean_text(item)]
    if isinstance(value, tuple):
        return [_clean_text(item) for item in value if _clean_text(item)]
    text = _clean_text(value)
    if not text:
        return []
    return [item.strip() for item in re.split(r"[\n,，、;；]+", text) if item.strip()]


def _dedupe(values: list[Any]) -> list[str]:
    result: list[str] = []
    for value in values:
        clean = _clean_text(value)
        if clean and clean not in result:
            result.append(clean)
    return result


def _nested_get(value: dict[str, Any], path: list[str]) -> Any:
    current: Any = value
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _join(value: Any, *, limit: int = 6) -> str:
    return "、".join(_as_list(value)[:limit])


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _slugify(text: str) -> str:
    clean = re.sub(r"[^\w\u4e00-\u9fff.-]+", "-", text.strip(), flags=re.UNICODE).strip("-")
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]
    return f"{clean[:60] or 'account'}-{digest}"


def _stable_id(prefix: str, parts: list[Any]) -> str:
    raw = "|".join(_clean_text(part) for part in parts)
    return f"{prefix}:{hashlib.sha1(raw.encode('utf-8')).hexdigest()[:16]}"


def _now_iso() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")
