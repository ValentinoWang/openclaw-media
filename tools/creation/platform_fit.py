from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .llm_generator import _call_openclaw_json
from .request_parser import CreationRequest


FIT_SCHEMA_KEYS = (
    "platform_mechanism_version",
    "mechanism_claim_boundary",
    "mechanism_evidence_level",
    "source_weights",
    "platform_strategy",
    "activity_strategy",
    "traffic_hypothesis",
    "creation_reverse_plan",
    "validation_targets",
    "post_publish_correction",
    "risks_or_missing_info",
)

FORBIDDEN_CLAIM_PATTERNS = (
    "破解算法",
    "平台真实权重",
    "黑箱权重",
    "精确权重",
    "保证爆款",
    "保证出爆款",
    "必爆",
    "一定爆",
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PLATFORM_MECHANISM_CONFIG_DIR = REPO_ROOT / "config" / "platform_mechanisms"


def generate_platform_mechanism_fit(
    request: CreationRequest,
    *,
    activity_candidates: list[dict[str, Any]],
    viral_candidates: list[dict[str, Any]],
    inspiration_candidates: list[dict[str, Any]],
    business_candidates: list[dict[str, Any]],
    reference_docs: list[dict[str, str]],
    media_context: dict[str, Any],
) -> dict[str, Any]:
    """Build a creation-stage platform mechanism hypothesis.

    This layer is deliberately framed as a fit/hypothesis, not a claim about
    private platform ranking weights.
    """
    fallback = fallback_platform_mechanism_fit(
        request,
        activity_candidates=activity_candidates,
        viral_candidates=viral_candidates,
        inspiration_candidates=inspiration_candidates,
        business_candidates=business_candidates,
        reference_docs=reference_docs,
        media_context=media_context,
    )
    if _env_bool("SELFMEDIA_CREATION_PLATFORM_FIT_DISABLE_LLM", False):
        result = dict(fallback)
        result["platform_fit_meta"] = _build_platform_fit_meta(
            request,
            mechanism_version=str(result.get("platform_mechanism_version") or ""),
            fallback_used=True,
            fallback_reason="llm_disabled",
            fallback_baseline=str(result.get("platform_mechanism_version") or ""),
            mechanism_source=str(result.get("mechanism_source") or "fallback"),
            baseline_source=str(result.get("mechanism_source") or "fallback"),
            activity_candidates=activity_candidates,
            viral_candidates=viral_candidates,
            inspiration_candidates=inspiration_candidates,
            business_candidates=business_candidates,
            reference_docs=reference_docs,
            media_context=media_context,
            include_llm=False,
        )
        return result

    prompt = build_platform_mechanism_prompt(
        request,
        fallback=fallback,
        activity_candidates=activity_candidates,
        viral_candidates=viral_candidates,
        inspiration_candidates=inspiration_candidates,
        business_candidates=business_candidates,
        reference_docs=reference_docs,
        media_context=media_context,
    )
    last_error = ""
    retries = _env_int("SELFMEDIA_CREATION_PLATFORM_FIT_RETRIES", 1)
    for attempt in range(retries + 1):
        message = prompt
        if last_error:
            message = (
                f"{prompt}\n\n"
                "上一次平台推荐拟合输出没有通过代码校验。\n"
                f"错误：{last_error}\n"
                "请重新输出完整 JSON object，只修正格式和约束，不要解释。"
            )
        try:
            payload = _call_openclaw_json(message)
            result = validate_platform_mechanism_fit_payload(payload, request, fallback=fallback)
            result["generation"] = {
                "provider": "openclaw_llm",
                "mode": "platform_mechanism_fit",
                "fallback_used": False,
            }
            result["platform_fit_meta"] = _build_platform_fit_meta(
                request,
                mechanism_version=str(result.get("platform_mechanism_version") or ""),
                fallback_used=False,
                fallback_reason="",
                fallback_baseline=str(fallback.get("platform_mechanism_version") or ""),
                mechanism_source="llm",
                baseline_source=str(fallback.get("mechanism_source") or "fallback"),
                activity_candidates=activity_candidates,
                viral_candidates=viral_candidates,
                inspiration_candidates=inspiration_candidates,
                business_candidates=business_candidates,
                reference_docs=reference_docs,
                media_context=media_context,
                include_llm=True,
            )
            return result
        except Exception as exc:  # keep creation available if this advisory layer fails
            last_error = str(exc)
            if attempt >= retries:
                break

    result = dict(fallback)
    result["generation"] = {
        "provider": "deterministic_baseline",
        "mode": "platform_mechanism_fit",
        "fallback_used": True,
        "llm_error": last_error[-1000:],
    }
    result["platform_fit_meta"] = _build_platform_fit_meta(
        request,
        mechanism_version=str(result.get("platform_mechanism_version") or ""),
        fallback_used=True,
        fallback_reason=_fallback_reason(last_error),
        fallback_baseline=str(result.get("platform_mechanism_version") or ""),
        mechanism_source=str(result.get("mechanism_source") or "fallback"),
        baseline_source=str(result.get("mechanism_source") or "fallback"),
        activity_candidates=activity_candidates,
        viral_candidates=viral_candidates,
        inspiration_candidates=inspiration_candidates,
        business_candidates=business_candidates,
        reference_docs=reference_docs,
        media_context=media_context,
        include_llm=False,
    )
    result["risks_or_missing_info"] = _as_string_list(result.get("risks_or_missing_info")) + [
        f"平台推荐拟合 LLM 未成功，已使用内置机制假设基线：{last_error[-200:]}"
    ]
    return result


def build_platform_mechanism_prompt(
    request: CreationRequest,
    *,
    fallback: dict[str, Any],
    activity_candidates: list[dict[str, Any]],
    viral_candidates: list[dict[str, Any]],
    inspiration_candidates: list[dict[str, Any]],
    business_candidates: list[dict[str, Any]],
    reference_docs: list[dict[str, str]],
    media_context: dict[str, Any],
) -> str:
    payload = {
        "request": request.to_dict(),
        "baseline_mechanism_fit": fallback,
        "account_profile": _truncate_nested((media_context or {}).get("account_profile") or {}, 1800),
        "recent_creations": _truncate_nested((media_context or {}).get("recent_creations") or [], 1000),
        "recent_reviews": _truncate_nested((media_context or {}).get("recent_reviews") or [], 1200),
        "activity_candidates": _truncate_nested(activity_candidates, 1200),
        "viral_candidates": _truncate_nested(viral_candidates, 1200),
        "inspiration_candidates": _truncate_nested(inspiration_candidates, 1200),
        "business_candidates": _truncate_nested(business_candidates, 1000),
        "reference_docs": _compact_reference_docs(reference_docs),
    }
    return (
        "你是 OpenClaw 的【平台推荐机制拟合层】。你的任务不是破解平台真实算法，也不能声称知道黑箱权重；"
        "你要把平台公开机制常识、输入里的活动/爆款/灵感/账号复盘/商务信息，拟合成一次创作可执行的判断模型。\n\n"
        "证据优先级：官方公开信息和平台功能说明 > 我们自己的历史复盘 > 同平台同赛道爆款拆解 > 活动 Brief > 全网经验/人工假设。"
        "如果输入没有证据，要明确标为待验证假设。\n\n"
        "必须区分 platform_strategy 与 activity_strategy："
        "platform_strategy 只回答推荐、搜索、互动、账号垂直度等平台机制适配；"
        "activity_strategy 只回答活动是否自然适配、如何投稿、是否硬蹭、是否调整标题/封面/结构。\n\n"
        "输出要求：\n"
        "1. 只输出合法 JSON object，不要 Markdown 代码块，不要解释。\n"
        f"2. platform_mechanism_version 优先沿用 baseline_mechanism_fit 里的版本：{fallback.get('platform_mechanism_version')}。\n"
        "3. mechanism_claim_boundary 必须说明：这是机制拟合假设，不是平台真实算法或权重结论。\n"
        "4. creation_reverse_plan 必须能反推到标题、封面/首屏、开头、内容结构、收藏/评论/关注触发。\n"
        "5. validation_targets 必须给出 2 小时、24 小时、7 天的可观察验证指标。\n"
        "6. post_publish_correction 必须说明点击低、停留低、收藏/互动低、活动不适配时分别修什么。\n"
        "7. activity_strategy 必须包含 matched_activities, natural_fit, hard_fit_risk, risk_reason, required_adjustments, do_not_force；hard_fit_risk 只能是 low/medium/high。\n"
        "8. 不得编造活动 ID、爆款数据、账号数据或官方公告；不得出现“破解算法/平台真实权重/保证爆款/必爆”等表述。\n\n"
        "输出 JSON 字段固定为：\n"
        f"{', '.join(FIT_SCHEMA_KEYS)}。\n\n"
        "输入 JSON：\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )


def validate_platform_mechanism_fit_payload(
    payload: dict[str, Any],
    request: CreationRequest,
    *,
    fallback: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("平台推荐拟合 JSON 顶层必须是 object")
    result = dict(fallback)
    result["platform_mechanism_version"] = _text(payload.get("platform_mechanism_version")) or fallback.get("platform_mechanism_version", "")
    result["mechanism_claim_boundary"] = _text(payload.get("mechanism_claim_boundary")) or fallback.get("mechanism_claim_boundary", "")
    result["mechanism_evidence_level"] = _text(payload.get("mechanism_evidence_level")) or fallback.get("mechanism_evidence_level", "")
    for key in (
        "source_weights",
        "platform_strategy",
        "activity_strategy",
        "traffic_hypothesis",
        "creation_reverse_plan",
        "validation_targets",
        "post_publish_correction",
    ):
        value = _as_dict(payload.get(key))
        if value:
            if key == "activity_strategy":
                result[key] = {**_as_dict(fallback.get(key)), **value}
            else:
                result[key] = value
    result["risks_or_missing_info"] = _as_string_list(payload.get("risks_or_missing_info")) or _as_string_list(fallback.get("risks_or_missing_info"))
    result["activity_strategy"] = _normalize_activity_strategy(result.get("activity_strategy"), fallback.get("activity_strategy"))
    result["platform"] = request.platform
    result["content_type"] = request.content_type
    result["track"] = request.track
    result["topic"] = request.topic
    missing = [key for key in FIT_SCHEMA_KEYS if not result.get(key)]
    if missing:
        raise ValueError(f"平台推荐拟合缺少字段：{', '.join(missing)}")
    if "真实算法" in str(result.get("mechanism_claim_boundary")) and "不是" not in str(result.get("mechanism_claim_boundary")):
        raise ValueError("mechanism_claim_boundary 不能声称掌握平台真实算法")
    _assert_no_forbidden_claims(result)
    return result


def parse_platform_mechanism_note(
    platform: str,
    raw_text: str,
    *,
    source_type: str = "creator_test",
    persist: bool = False,
    use_llm: bool = True,
) -> dict[str, Any]:
    baseline = default_platform_mechanism(platform)
    fallback = _fallback_platform_mechanism_note(platform, raw_text, source_type=source_type, baseline=baseline)
    if use_llm and not _env_bool("SELFMEDIA_PLATFORM_MECHANISM_NOTE_DISABLE_LLM", False):
        prompt = _build_platform_mechanism_note_prompt(platform, raw_text, source_type=source_type, fallback=fallback, baseline=baseline)
        try:
            payload = _call_openclaw_json(prompt)
            result = validate_platform_mechanism_note_payload(payload, platform=platform, source_type=source_type, fallback=fallback)
            result["parser"] = {"provider": "openclaw_llm", "fallback_used": False}
        except Exception as exc:
            result = dict(fallback)
            result["parser"] = {"provider": "deterministic_baseline", "fallback_used": True, "error": str(exc)[-1000:]}
    else:
        result = dict(fallback)
        result["parser"] = {"provider": "deterministic_baseline", "fallback_used": True, "reason": "llm_disabled"}
    if persist:
        persist_platform_mechanism_observation(result)
    return result


def validate_platform_mechanism_note_payload(
    payload: dict[str, Any],
    *,
    platform: str,
    source_type: str,
    fallback: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("平台机制材料解析 JSON 顶层必须是 object")
    result = dict(fallback)
    result["platform"] = _text(payload.get("platform")) or platform
    result["source_type"] = _text(payload.get("source_type")) or source_type
    result["evidence_level"] = _normalize_evidence_level(payload.get("evidence_level"), source_type)
    hypotheses = []
    for item in _as_list(payload.get("hypotheses")):
        hypothesis = _normalize_hypothesis(item, evidence_level=result["evidence_level"])
        if hypothesis:
            hypotheses.append(hypothesis)
    if hypotheses:
        result["hypotheses"] = hypotheses[:8]
    if not result.get("hypotheses"):
        raise ValueError("平台机制材料解析必须至少输出一条 hypothesis")
    result["generated_at"] = _text(payload.get("generated_at")) or result.get("generated_at") or _now_iso()
    _assert_no_forbidden_claims(result)
    return result


def persist_platform_mechanism_observation(observation: dict[str, Any]) -> Path:
    platform = _text(observation.get("platform"))
    raw_dir = os.getenv("SELFMEDIA_PLATFORM_MECHANISM_CONFIG_DIR", "").strip()
    config_dir = Path(raw_dir).expanduser() if raw_dir else DEFAULT_PLATFORM_MECHANISM_CONFIG_DIR
    config_dir.mkdir(parents=True, exist_ok=True)
    path = config_dir / f"{platform_slug(platform)}.json"
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}
    else:
        payload = {
            "platform": platform,
            "mechanism_version": _text(observation.get("mechanism_version")) or f"{platform_slug(platform)}_{_now_version_month()}_v1",
            "status": "active",
            "observations": [],
        }
    observations = payload.get("observations")
    if not isinstance(observations, list):
        observations = []
    observations.append(observation)
    payload["observations"] = observations[-200:]
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _build_platform_mechanism_note_prompt(
    platform: str,
    raw_text: str,
    *,
    source_type: str,
    fallback: dict[str, Any],
    baseline: dict[str, Any],
) -> str:
    payload = {
        "platform": platform,
        "source_type": source_type,
        "default_evidence_level": _source_type_evidence_level(source_type),
        "baseline": baseline,
        "fallback_schema_example": fallback,
        "raw_text": _truncate(raw_text, 6000),
    }
    return (
        "你是 OpenClaw 的平台机制材料解析器。你要把官方说明、创作者实测、流量解读或内部复盘，"
        "整理成可被平台推荐拟合层后续使用的机制命题。\n\n"
        "边界：这不是破解平台真实算法，不能声称知道黑箱权重，也不能承诺保证爆款。\n"
        "证据等级：S=官方公示/官方文档/明确活动规则；A=自己账号多次复盘验证；B=爆款拆解+自己少量数据支持；"
        "C=全网创作者实测或经验帖；D=LLM 推测或人工假设。\n\n"
        "只输出合法 JSON object，不要 Markdown 代码块。字段固定为：platform, source_type, evidence_level, hypotheses。\n"
        "每条 hypothesis 必须包含：claim, evidence_level, applies_to, creation_action, validation_metrics, risk, status。\n"
        "status 只能是 candidate/active/deprecated，外部实测默认 candidate。\n"
        "不得出现“破解算法”“平台真实权重”“黑箱权重”“精确权重”“保证爆款”“必爆”等表述。\n\n"
        "输入 JSON：\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )


def _fallback_platform_mechanism_note(
    platform: str,
    raw_text: str,
    *,
    source_type: str,
    baseline: dict[str, Any],
) -> dict[str, Any]:
    evidence_level = _source_type_evidence_level(source_type)
    claim = _infer_note_claim(raw_text)
    metrics = _infer_note_metrics(raw_text, baseline)
    actions = _infer_note_actions(raw_text, baseline)
    applies_to = _infer_note_applies_to(platform, raw_text)
    return {
        "platform": platform,
        "source_type": source_type,
        "evidence_level": evidence_level,
        "mechanism_version": baseline.get("version") or f"{platform_slug(platform)}_{_now_version_month()}_v1",
        "generated_at": _now_iso(),
        "hypotheses": [
            {
                "claim": claim,
                "evidence_level": evidence_level,
                "applies_to": applies_to,
                "creation_action": actions,
                "validation_metrics": metrics,
                "risk": _source_type_risk(source_type),
                "status": "candidate",
            }
        ],
        "parser": {"provider": "deterministic_baseline", "fallback_used": True},
    }


def _normalize_hypothesis(value: Any, *, evidence_level: str) -> dict[str, Any]:
    data = _as_dict(value)
    if not data:
        return {}
    claim = _sanitize_forbidden_claims(_text(data.get("claim") or data.get("summary")))
    if not claim:
        return {}
    status = _text(data.get("status")) or "candidate"
    if status not in {"candidate", "active", "deprecated"}:
        status = "candidate"
    return {
        "claim": claim,
        "evidence_level": _normalize_evidence_level(data.get("evidence_level"), "") or evidence_level,
        "applies_to": _as_string_list(data.get("applies_to")) or ["内容创作"],
        "creation_action": _as_string_list(data.get("creation_action")) or ["发布前将该命题转成标题、首屏和结构调整。"],
        "validation_metrics": _as_string_list(data.get("validation_metrics")) or ["点击", "停留", "互动"],
        "risk": _sanitize_forbidden_claims(_text(data.get("risk"))) or "该命题尚未经过本账号发布数据验证。",
        "status": status,
    }


def _source_type_evidence_level(source_type: str) -> str:
    normalized = str(source_type or "").strip().lower()
    if normalized in {"official", "official_notice", "official_doc", "official_creator_docs", "activity_rule", "activity_brief"}:
        return "S"
    if normalized in {"internal_review", "internal_replay", "account_review"}:
        return "A"
    if normalized in {"hot_content_with_internal_support", "viral_with_review"}:
        return "B"
    if normalized in {"creator_test", "creator_experience", "external_test", "hot_content", "experience_post"}:
        return "C"
    return "D"


def _normalize_evidence_level(value: Any, source_type: str) -> str:
    level = _text(value).upper()
    if level in {"S", "A", "B", "C", "D"}:
        return level
    return _source_type_evidence_level(source_type)


def _source_type_risk(source_type: str) -> str:
    level = _source_type_evidence_level(source_type)
    if level == "S":
        return "来自官方或明确规则，仍需确认适用范围和发布时间。"
    if level == "A":
        return "来自本账号复盘，仍需继续观察是否受平台版本变化影响。"
    if level == "B":
        return "已有爆款或少量内部数据支持，仍需扩大样本验证。"
    if level == "C":
        return "该结论来自外部实测或经验帖，未经过本账号数据验证。"
    return "该结论主要来自人工或 LLM 推测，只能作为低置信候选命题。"


def _infer_note_claim(raw_text: str) -> str:
    text = _sanitize_forbidden_claims(_truncate(" ".join(str(raw_text or "").split()), 120))
    if "收藏" in text and "搜索" in text:
        return "内容可能需要同时强化收藏理由和搜索长尾。"
    if "前3秒" in text or "前三秒" in text or "完播" in text:
        return "视频内容可能需要优先强化前段停留和观看深度。"
    if "评论" in text or "互动" in text:
        return "内容可能需要设计更具体的评论触发问题。"
    if text:
        return f"该材料提出一个待验证平台机制命题：{text}"
    return "该材料需要整理为待验证平台机制命题。"


def _infer_note_actions(raw_text: str, baseline: dict[str, Any]) -> list[str]:
    text = str(raw_text or "")
    actions: list[str] = []
    if "搜索" in text:
        actions.append("标题、正文和标签保留明确搜索词。")
    if "收藏" in text:
        actions.append("前半段提供步骤、清单、模板或自查标准。")
    if "封面" in text or "点击" in text:
        actions.append("封面或首屏突出具体痛点、结果或收益。")
    if "评论" in text or "互动" in text:
        actions.append("结尾提出用户能直接回答的具体问题。")
    if "前3秒" in text or "前三秒" in text or "完播" in text:
        actions.append("前 3 秒给出冲突、结果或看完理由。")
    if actions:
        return actions
    image_actions = baseline.get("image_actions") or {}
    return _as_string_list(image_actions.get("structure")) or ["把机制命题转成标题、首屏、结构和验证指标。"]


def _infer_note_metrics(raw_text: str, baseline: dict[str, Any]) -> list[str]:
    text = str(raw_text or "")
    metrics: list[str] = []
    if "搜索" in text:
        metrics.extend(["搜索来源占比", "7天长尾阅读"])
    if "收藏" in text:
        metrics.extend(["收藏率", "收藏/点赞比"])
    if "评论" in text or "互动" in text:
        metrics.extend(["评论率", "评论关键词"])
    if "前3秒" in text or "前三秒" in text:
        metrics.extend(["前 3 秒留存", "平均观看时长"])
    if "完播" in text:
        metrics.append("完播率")
    if metrics:
        return _dedupe(metrics)
    targets = baseline.get("validation_targets") or {}
    return _dedupe([*(_as_string_list(targets.get("two_hour"))), *(_as_string_list(targets.get("twenty_four_hour")))])[:5]


def _infer_note_applies_to(platform: str, raw_text: str) -> list[str]:
    text = str(raw_text or "")
    result = [platform] if platform else []
    if "图文" in text or "笔记" in text:
        result.append("图文")
    if "视频" in text or "前3秒" in text or "前三秒" in text or "完播" in text:
        result.append("视频")
    for keyword in ("知识型内容", "个人IP", "自媒体运营", "内容创作", "选题", "素材库"):
        if keyword in text:
            result.append(keyword)
    return _dedupe(result) or ["内容创作"]


def _sanitize_forbidden_claims(text: str) -> str:
    cleaned = _text(text)
    replacements = {
        "破解算法": "拟合机制假设",
        "平台真实权重": "平台机制假设",
        "黑箱权重": "机制信号",
        "精确权重": "相对重要性",
        "保证爆款": "提升验证概率",
        "保证出爆款": "提升验证概率",
        "必爆": "需要验证",
        "一定爆": "需要验证",
    }
    for pattern, replacement in replacements.items():
        cleaned = cleaned.replace(pattern, replacement)
    return cleaned


def fallback_platform_mechanism_fit(
    request: CreationRequest,
    *,
    activity_candidates: list[dict[str, Any]] | None = None,
    viral_candidates: list[dict[str, Any]] | None = None,
    inspiration_candidates: list[dict[str, Any]] | None = None,
    business_candidates: list[dict[str, Any]] | None = None,
    reference_docs: list[dict[str, str]] | None = None,
    media_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    activity_candidates = activity_candidates or []
    viral_candidates = viral_candidates or []
    inspiration_candidates = inspiration_candidates or []
    business_candidates = business_candidates or []
    reference_docs = reference_docs or []
    media_context = media_context or {}
    baseline = default_platform_mechanism(request.platform)
    activity_ids = _candidate_ids(activity_candidates)
    viral_ids = _candidate_ids(viral_candidates)
    inspiration_ids = _candidate_ids(inspiration_candidates)
    has_reviews = bool((media_context or {}).get("recent_reviews"))
    content_labels = _dedupe([request.track, request.topic, *(request.keywords or []), *baseline["default_labels"]])
    content_actions = baseline["image_actions"] if request.content_type == "图文" else baseline["video_actions"]
    activity_strategy = _build_activity_strategy(request, activity_candidates, activity_ids)

    review_signal = "已有内部复盘可校准" if has_reviews else "缺少同账号近期复盘，先按待验证假设处理"
    result = {
        "platform": request.platform,
        "content_type": request.content_type,
        "track": request.track,
        "topic": request.topic,
        "platform_mechanism_version": baseline["version"],
        "mechanism_source": baseline.get("mechanism_source", "fallback"),
        "mechanism_claim_boundary": "这是基于公开机制、候选样本和内部复盘形成的推荐机制拟合假设，不是平台真实算法或权重结论。",
        "mechanism_evidence_level": _evidence_level(has_reviews, bool(viral_candidates), bool(activity_candidates)),
        "source_weights": {
            "platform_public_baseline": "A-",
            "internal_review_data": "B" if has_reviews else "待补",
            "hot_content_candidates": "B" if viral_candidates else "待补",
            "activity_brief_candidates": "B" if activity_candidates else "待补",
            "creator_experience_or_manual_hypothesis": "C",
            "reference_docs_loaded": len(reference_docs),
            "business_candidates_loaded": len(business_candidates),
        },
        "platform_strategy": {
            "platform_lens": baseline["platform_lens"],
            "primary_entries": baseline["primary_entries"],
            "content_labels_to_make_clear": content_labels[:12],
            "user_actions_to_design": baseline["user_actions_to_design"],
            "mechanism_observation_hypotheses": baseline.get("observed_hypotheses", [])[:8],
            "account_memory_use": review_signal,
            "hot_content_reference_ids": viral_ids[:8],
            "inspiration_reference_ids": inspiration_ids[:8],
            "fit_summary": f"本次应把「{request.topic}」包装成用户一眼能理解、愿意停留并能产生{baseline['key_feedback']}的作品。",
        },
        "activity_strategy": activity_strategy,
        "traffic_hypothesis": {
            "system_may_understand_as": content_labels[:10],
            "initial_audience": _dedupe([request.track, request.topic, "对该问题已有真实困扰的人群"]),
            "click_reason": baseline["click_reason"],
            "stay_reason": baseline["stay_reason"],
            "save_or_interaction_reason": baseline["save_or_interaction_reason"],
            "main_risk": "如果标题/封面只像观点口号，系统和用户都难以判断具体场景，点击和收藏会偏弱。",
        },
        "creation_reverse_plan": {
            "title": [
                f"标题必须同时出现具体人群/场景和「{request.topic}」相关问题。",
                "避免只写宏大观点，优先写用户会搜索或会转述的问题。",
            ],
            "cover_or_first_screen": content_actions["cover_or_first_screen"],
            "opening": content_actions["opening"],
            "structure": content_actions["structure"],
            "save_comment_follow_trigger": content_actions["save_comment_follow_trigger"],
        },
        "validation_targets": {
            "two_hour": baseline["validation_targets"]["two_hour"],
            "twenty_four_hour": baseline["validation_targets"]["twenty_four_hour"],
            "seven_day": baseline["validation_targets"]["seven_day"],
            "failure_diagnosis": {
                "low_click": "优先修标题、封面/首屏和搜索词，检查是否一眼可懂。",
                "low_stay": "优先修开头承诺、前半段节奏和案例密度。",
                "low_save_or_interaction": "优先补清单、步骤、判断标准、评论问题或关注理由。",
                "activity_not_working": "检查活动话题是否硬蹭，必要时保留作品主线、降低活动表达权重。",
            },
        },
        "post_publish_correction": {
            "if_low_click": "重写标题和封面/首屏，让具体人群、问题和收益更明确。",
            "if_low_stay": "压缩铺垫，把真实场景或冲突提前，减少抽象解释。",
            "if_low_save_or_interaction": "增加可收藏步骤、检查清单、评论触发问题或关注后的连续价值。",
            "if_activity_mismatch": "撤掉硬蹭活动表达，改为普通推荐/搜索包装，或换更贴合活动再发。",
            "next_iteration": "把发布后 2 小时、24 小时、7 天数据回填复盘表，用于升级下一版机制假设。",
        },
        "risks_or_missing_info": _missing_info(media_context, viral_candidates, activity_candidates, inspiration_candidates),
        "generation": {
            "provider": "deterministic_baseline",
            "mode": "platform_mechanism_fit",
            "fallback_used": True,
        },
    }
    result["platform_fit_meta"] = _build_platform_fit_meta(
        request,
        mechanism_version=str(result.get("platform_mechanism_version") or ""),
        fallback_used=True,
        fallback_reason="deterministic_baseline",
        fallback_baseline=str(result.get("platform_mechanism_version") or ""),
        mechanism_source=str(result.get("mechanism_source") or "fallback"),
        baseline_source=str(result.get("mechanism_source") or "fallback"),
        activity_candidates=activity_candidates,
        viral_candidates=viral_candidates,
        inspiration_candidates=inspiration_candidates,
        business_candidates=business_candidates,
        reference_docs=reference_docs,
        media_context=media_context,
        include_llm=False,
    )
    observation_actions = _observation_creation_actions(baseline.get("observed_hypotheses", []))
    if observation_actions:
        result["creation_reverse_plan"]["mechanism_observation_actions"] = observation_actions
    return result


def _build_activity_strategy(
    request: CreationRequest,
    activity_candidates: list[dict[str, Any]],
    activity_ids: list[str],
) -> dict[str, Any]:
    matched = [_activity_summary(item) for item in activity_candidates[:8]]
    if not activity_candidates:
        return {
            "fit": "暂无匹配活动，先按平台推荐/搜索/互动机制完成作品。",
            "matched_activities": [],
            "candidate_activity_ids": [],
            "natural_fit": False,
            "hard_fit_risk": "low",
            "risk_reason": "没有活动候选时不做活动包装，因此不存在硬蹭风险。",
            "required_adjustments": [],
            "do_not_force": ["不要为了活动流量临时改写主题。", "不要把作品改成和账号定位无关的泛话题。"],
            "adaptation_actions": ["不强行包装活动入口；发布后再按平台活动表补投适配话题。"],
            "decision_boundary": "活动是短期入口信号，不等同于平台推荐算法；只在自然适配时合流。",
        }

    risk = _activity_hard_fit_risk(request, activity_candidates)
    risk_reason = {
        "low": "候选活动和平台、赛道或主体有明确重叠，适合自然合流。",
        "medium": "候选活动有可借势空间，但需要保持作品主线，避免为了活动改题。",
        "high": "候选活动和当前平台、内容类型或主题存在明显错位，建议不投或换活动。",
    }[risk]
    return {
        "fit": "有候选活动，可作为短期流量入口，但必须围绕主体自然承接，避免硬蹭。",
        "matched_activities": matched,
        "candidate_activity_ids": activity_ids[:8],
        "natural_fit": risk in {"low", "medium"},
        "hard_fit_risk": risk,
        "risk_reason": risk_reason,
        "required_adjustments": ["标题或正文保留活动主话题的自然承接。", "标签区补充活动关键词。"] if risk != "high" else [],
        "do_not_force": ["不要为了活动改成泛话题。", "不要牺牲账号定位和用户真实问题。", "不要编造活动奖励或投稿规则。"],
        "adaptation_actions": [
            "优先选择和主体、赛道、内容类型都匹配的活动。",
            "标题和封面保留用户问题本身，活动话题放在标签或正文承接处。",
            "如果活动要求和账号定位冲突，宁可不投，不为活动牺牲作品主线。",
        ],
        "decision_boundary": "活动是短期入口信号，不等同于平台推荐算法；只在自然适配时合流。",
    }


def _normalize_activity_strategy(value: Any, fallback: Any) -> dict[str, Any]:
    base = _as_dict(fallback)
    strategy = {**base, **_as_dict(value)}
    risk = str(strategy.get("hard_fit_risk") or "").strip().lower()
    if risk not in {"low", "medium", "high"}:
        risk = "medium" if strategy.get("matched_activities") or strategy.get("candidate_activity_ids") else "low"
    strategy["hard_fit_risk"] = risk
    strategy["matched_activities"] = _as_list_of_dicts(strategy.get("matched_activities"))
    strategy["candidate_activity_ids"] = _as_string_list(strategy.get("candidate_activity_ids"))
    strategy["natural_fit"] = bool(strategy.get("natural_fit")) if "natural_fit" in strategy else risk != "high"
    strategy["risk_reason"] = _text(strategy.get("risk_reason")) or _text(base.get("risk_reason")) or "活动适配风险需要发布前人工复核。"
    strategy["required_adjustments"] = _as_string_list(strategy.get("required_adjustments"))
    strategy["do_not_force"] = _as_string_list(strategy.get("do_not_force")) or ["不要为了活动改写内容主线。"]
    return strategy


def _activity_hard_fit_risk(request: CreationRequest, candidates: list[dict[str, Any]]) -> str:
    strong_match = False
    weak_match = False
    for item in candidates:
        platform = _text(item.get("platform"))
        if platform and request.platform and platform != request.platform:
            return "high"
        requirement = _text(item.get("content_type_requirement") or item.get("content_type"))
        if requirement and requirement not in {"不限", request.content_type}:
            return "high"
        haystack = _candidate_text(item)
        if request.topic and request.topic in haystack:
            strong_match = True
        if request.track and request.track in haystack:
            weak_match = True
        for keyword in request.keywords or []:
            if keyword and str(keyword).strip() in haystack:
                weak_match = True
    if strong_match:
        return "low"
    if weak_match:
        return "medium"
    return "medium"


def _activity_summary(item: dict[str, Any]) -> dict[str, str]:
    return {
        "id": _text(item.get("id") or item.get("source_record_id") or item.get("relation_id")),
        "title": _text(item.get("title")),
        "topic": _text(item.get("topic")),
        "deadline": _text(item.get("deadline")),
    }


def _build_platform_fit_meta(
    request: CreationRequest,
    *,
    mechanism_version: str,
    fallback_used: bool,
    fallback_reason: str,
    fallback_baseline: str,
    mechanism_source: str,
    baseline_source: str,
    activity_candidates: list[dict[str, Any]],
    viral_candidates: list[dict[str, Any]],
    inspiration_candidates: list[dict[str, Any]],
    business_candidates: list[dict[str, Any]],
    reference_docs: list[dict[str, str]],
    media_context: dict[str, Any],
    include_llm: bool,
) -> dict[str, Any]:
    has_reviews = bool((media_context or {}).get("recent_reviews"))
    has_profile = bool(((media_context or {}).get("loaded") or {}).get("account_profile") or (media_context or {}).get("account_profile"))
    evidence_level = _evidence_grade(has_reviews, bool(viral_candidates), bool(activity_candidates), include_llm)
    return {
        "platform": request.platform,
        "content_type": request.content_type,
        "mechanism_version": mechanism_version,
        "mechanism_source": mechanism_source,
        "fit_source": _fit_sources(
            mechanism_source=mechanism_source,
            baseline_source=baseline_source,
            include_llm=include_llm,
            has_activity=bool(activity_candidates),
            has_viral=bool(viral_candidates),
            has_inspiration=bool(inspiration_candidates),
            has_business=bool(business_candidates),
            has_reviews=has_reviews,
            has_profile=has_profile,
            has_reference_docs=bool(reference_docs),
        ),
        "fallback_used": fallback_used,
        "fallback_reason": fallback_reason,
        "fallback_baseline": fallback_baseline if fallback_used else "",
        "confidence": _confidence_label(evidence_level),
        "evidence_level": evidence_level,
        "generated_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds"),
    }


def _fit_sources(
    *,
    mechanism_source: str,
    baseline_source: str,
    include_llm: bool,
    has_activity: bool,
    has_viral: bool,
    has_inspiration: bool,
    has_business: bool,
    has_reviews: bool,
    has_profile: bool,
    has_reference_docs: bool,
) -> list[str]:
    sources = ["mechanism_config" if baseline_source == "config" else "builtin_baseline"]
    if include_llm:
        sources.append("llm")
    if has_activity:
        sources.append("activity_table")
    if has_viral:
        sources.append("hot_content_table")
    if has_inspiration:
        sources.append("inspiration_table")
    if has_profile:
        sources.append("account_memory")
    if has_reviews:
        sources.append("review_data")
    if has_business:
        sources.append("business_table")
    if has_reference_docs:
        sources.append("reference_docs")
    return sources


def _evidence_grade(has_reviews: bool, has_viral: bool, has_activity: bool, include_llm: bool) -> str:
    if has_reviews and has_viral and has_activity:
        return "A"
    if has_reviews and (has_viral or has_activity):
        return "B"
    if has_viral or has_activity:
        return "C"
    return "D" if include_llm else "D"


def _confidence_label(evidence_level: str) -> str:
    if evidence_level in {"S", "A"}:
        return "high"
    if evidence_level == "B":
        return "medium"
    return "low"


def _fallback_reason(error: str) -> str:
    text = _text(error)
    if "JSON" in text or "json" in text or "parse" in text or "解析" in text:
        return "llm_json_parse_failed"
    if "timeout" in text.lower() or "timed out" in text.lower():
        return "llm_timeout"
    return "llm_failed"


def _assert_no_forbidden_claims(payload: dict[str, Any]) -> None:
    text = json.dumps(payload, ensure_ascii=False)
    for pattern in FORBIDDEN_CLAIM_PATTERNS:
        if pattern in text:
            raise ValueError(f"平台推荐拟合不能出现算法神化表述：{pattern}")


def default_platform_mechanism(platform: str) -> dict[str, Any]:
    slug = platform_slug(platform)
    config = load_platform_mechanism_config(platform)
    if config:
        return _baseline_from_config(config, platform=platform, slug=slug)
    version = f"{slug}_{_now_version_month()}_v1"
    return {
        "version": version,
        "mechanism_source": "fallback",
        "platform_lens": "未读取到平台机制配置，使用通用推荐机制保底：让平台和用户快速理解内容标签，并围绕点击、停留、互动和复盘验证做创作。",
        "primary_entries": ["推荐流", "搜索", "关注关系"],
        "default_labels": ["内容标签", "用户问题", "互动触发", "验证指标"],
        "user_actions_to_design": ["点击", "停留", "收藏/分享", "评论", "关注"],
        "key_feedback": "点击、停留、互动和关注",
        "click_reason": "标题和首屏让用户快速判断这条内容和自己有关。",
        "stay_reason": "内容持续兑现开头承诺，减少抽象铺垫。",
        "save_or_interaction_reason": "提供可保存、可讨论或可继续追踪的具体价值。",
        "image_actions": {
            "cover_or_first_screen": ["封面明确具体问题和用户收益。"],
            "opening": ["首屏先给人群、痛点和判断标准。"],
            "structure": ["场景 -> 问题 -> 方法 -> 自查 -> 互动。"],
            "save_comment_follow_trigger": ["用清单、模板或评论问题承接收藏和互动。"],
        },
        "video_actions": {
            "cover_or_first_screen": ["首帧明确场景、冲突或结果。"],
            "opening": ["前 3 秒说清看完理由。"],
            "structure": ["钩子 -> 场景 -> 方法 -> 对照 -> 行动。"],
            "save_comment_follow_trigger": ["结尾给评论问题或系列关注理由。"],
        },
        "validation_targets": {
            "two_hour": ["点击", "停留", "互动启动"],
            "twenty_four_hour": ["互动率", "收藏/分享", "转粉"],
            "seven_day": ["搜索长尾", "回访", "账号标签"],
        },
    }


def load_platform_mechanism_config(platform: str) -> dict[str, Any]:
    raw_dir = os.getenv("SELFMEDIA_PLATFORM_MECHANISM_CONFIG_DIR", "").strip()
    config_dir = Path(raw_dir).expanduser() if raw_dir else DEFAULT_PLATFORM_MECHANISM_CONFIG_DIR
    path = config_dir / f"{platform_slug(platform)}.json"
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict) or payload.get("status") not in ("", None, "active"):
        return {}
    return payload


def _baseline_from_config(config: dict[str, Any], *, platform: str, slug: str) -> dict[str, Any]:
    version = _text(config.get("mechanism_version")) or f"{slug}_{_now_version_month()}_v1"
    reasoning = _as_dict(config.get("content_reasoning"))
    actions = _as_dict(config.get("content_type_actions"))
    image_actions = _content_actions_from_config(actions.get("图文"), default_content_type="图文")
    video_actions = _content_actions_from_config(actions.get("视频"), default_content_type="视频")
    core_signals = [item for item in config.get("core_signals") or [] if isinstance(item, dict)]
    observed_hypotheses = _observation_hypotheses_from_config(config)
    validation_targets = _validation_targets_from_config(config, core_signals, observed_hypotheses)
    default_labels = _dedupe([
        *(_as_string_list(config.get("default_labels")) or [str(item.get("name")) for item in core_signals if item.get("name")]),
        *[label for item in observed_hypotheses for label in _as_string_list(item.get("applies_to"))],
    ])
    return {
        "version": version,
        "mechanism_source": "config",
        "platform_lens": _text(config.get("baseline_summary")) or f"{platform} 推荐机制配置。",
        "primary_entries": _as_string_list(config.get("default_traffic_entries")) or ["推荐流", "搜索", "关注关系"],
        "default_labels": default_labels or ["内容标签", "用户行为", "验证指标"],
        "user_actions_to_design": _as_string_list(config.get("user_actions_to_design")) or ["点击", "停留", "互动", "关注"],
        "key_feedback": _text(config.get("key_feedback")) or "点击、停留和互动",
        "click_reason": _text(reasoning.get("click_reason")) or _signal_action(core_signals, "点击") or "标题和首屏能让用户快速判断和自己有关。",
        "stay_reason": _text(reasoning.get("stay_reason")) or _signal_action(core_signals, "停留") or "内容持续兑现开头承诺。",
        "save_or_interaction_reason": _text(reasoning.get("save_or_interaction_reason")) or _signal_action(core_signals, "收藏") or "提供可保存、可讨论或可继续追踪的价值。",
        "image_actions": image_actions,
        "video_actions": video_actions,
        "validation_targets": validation_targets,
        "observed_hypotheses": observed_hypotheses,
    }


def _content_actions_from_config(value: Any, *, default_content_type: str) -> dict[str, list[str]]:
    data = _as_dict(value)
    defaults = {
        "图文": {
            "cover_or_first_screen": ["封面明确具体问题和用户收益。"],
            "opening": ["首屏先给人群、痛点和判断标准。"],
            "structure": ["场景 -> 问题 -> 方法 -> 自查 -> 互动。"],
            "save_comment_follow_trigger": ["用清单、模板或评论问题承接收藏和互动。"],
        },
        "视频": {
            "cover_or_first_screen": ["首帧明确场景、冲突或结果。"],
            "opening": ["前 3 秒说清看完理由。"],
            "structure": ["钩子 -> 场景 -> 方法 -> 对照 -> 行动。"],
            "save_comment_follow_trigger": ["结尾给评论问题或系列关注理由。"],
        },
    }[default_content_type]
    return {
        key: _as_string_list(data.get(key)) or defaults[key]
        for key in ("cover_or_first_screen", "opening", "structure", "save_comment_follow_trigger")
    }


def _validation_targets_from_config(
    config: dict[str, Any],
    core_signals: list[dict[str, Any]],
    observed_hypotheses: list[dict[str, Any]],
) -> dict[str, list[str]]:
    value = _as_dict(config.get("validation_targets"))
    metrics = []
    for signal in core_signals:
        metrics.extend(_as_string_list(signal.get("validation_metrics")))
    for hypothesis in observed_hypotheses:
        metrics.extend(_as_string_list(hypothesis.get("validation_metrics")))
    metrics = _dedupe(metrics)
    return {
        "two_hour": _as_string_list(value.get("two_hour")) or metrics[:4] or ["点击", "停留", "互动启动"],
        "twenty_four_hour": _as_string_list(value.get("twenty_four_hour")) or metrics[1:5] or ["互动率", "收藏/分享", "转粉"],
        "seven_day": _as_string_list(value.get("seven_day")) or metrics[-3:] or ["搜索长尾", "回访", "账号标签"],
    }


def _signal_action(core_signals: list[dict[str, Any]], keyword: str) -> str:
    for signal in core_signals:
        text = " ".join(str(signal.get(key) or "") for key in ("name", "description", "creation_action"))
        if keyword in text:
            return _text(signal.get("creation_action"))
    return ""


def _observation_hypotheses_from_config(config: dict[str, Any]) -> list[dict[str, Any]]:
    hypotheses: list[dict[str, Any]] = []
    observations = config.get("observations")
    if not isinstance(observations, list):
        return []
    for observation in observations[-50:]:
        if not isinstance(observation, dict):
            continue
        evidence_level = _normalize_evidence_level(observation.get("evidence_level"), observation.get("source_type") or "")
        for item in _as_list(observation.get("hypotheses")):
            hypothesis = _normalize_hypothesis(item, evidence_level=evidence_level)
            if not hypothesis or hypothesis.get("status") == "deprecated":
                continue
            hypotheses.append(hypothesis)
    return hypotheses[-20:]


def _observation_creation_actions(hypotheses: list[dict[str, Any]]) -> list[str]:
    actions: list[str] = []
    for item in hypotheses[-8:]:
        actions.extend(_as_string_list(item.get("creation_action")))
    return _dedupe(actions)[:8]


def platform_slug(platform: str) -> str:
    mapping = {
        "小红书": "xiaohongshu",
        "抖音": "douyin",
        "B站": "bilibili",
        "哔哩哔哩": "bilibili",
        "bilibili": "bilibili",
    }
    if platform in mapping:
        return mapping[platform]
    text = re.sub(r"[^a-zA-Z0-9]+", "_", str(platform or "platform").strip().lower()).strip("_")
    return text or "platform"


def _evidence_level(has_reviews: bool, has_viral: bool, has_activity: bool) -> str:
    parts = ["platform_public_baseline"]
    if has_reviews:
        parts.append("internal_replay")
    if has_viral:
        parts.append("hot_content")
    if has_activity:
        parts.append("activity_brief")
    parts.append("llm_or_manual_hypothesis")
    return " + ".join(parts)


def _missing_info(
    media_context: dict[str, Any],
    viral_candidates: list[dict[str, Any]],
    activity_candidates: list[dict[str, Any]],
    inspiration_candidates: list[dict[str, Any]],
) -> list[str]:
    risks: list[str] = []
    loaded = (media_context or {}).get("loaded") or {}
    if not loaded.get("account_profile"):
        risks.append("缺少账号档案，账号垂直度和受众画像只能按请求推断。")
    if not (media_context or {}).get("recent_reviews"):
        risks.append("缺少近期发布复盘，机制判断无法用同账号数据校准。")
    if not viral_candidates:
        risks.append("缺少同平台同赛道爆款拆解，结构迁移依据偏弱。")
    if not inspiration_candidates:
        risks.append("缺少可复用创作灵感，真实场景和个人 IP 记忆偏弱。")
    if not activity_candidates:
        risks.append("未匹配到近期活动，活动入口暂不参与创作反推。")
    return risks or ["当前输入具备基础拟合条件，仍需发布后用数据复盘校准。"]


def _candidate_ids(candidates: list[dict[str, Any]]) -> list[str]:
    ids = []
    for item in candidates:
        value = item.get("id") or item.get("source_record_id") or item.get("relation_id")
        text = str(value or "").strip()
        if text and text not in ids:
            ids.append(text)
    return ids


def _candidate_text(item: dict[str, Any]) -> str:
    parts = [
        item.get("title"),
        item.get("content"),
        item.get("platform"),
        item.get("content_type"),
        item.get("content_type_requirement"),
        item.get("track"),
        item.get("topic"),
        " ".join(str(tag) for tag in item.get("tags") or []),
        item.get("direction"),
        item.get("participation_requirement"),
    ]
    return " ".join(str(part or "") for part in parts)


def _dedupe(items: list[Any]) -> list[str]:
    result: list[str] = []
    for item in items:
        text = str(item or "").strip(" #\t")
        if text and text not in result:
            result.append(text)
    return result


def _compact_reference_docs(reference_docs: list[dict[str, str]]) -> list[dict[str, str]]:
    docs = []
    for item in (reference_docs or [])[:8]:
        docs.append(
            {
                "url": _text(item.get("url") or item.get("source") or ""),
                "title": _text(item.get("title") or ""),
                "content": _truncate(_text(item.get("content") or item.get("text") or ""), 1600),
            }
        )
    return docs


def _truncate_nested(value: Any, max_chars: int) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= 30:
                break
            result[str(key)] = _truncate_nested(item, max_chars)
        return result
    if isinstance(value, list):
        return [_truncate_nested(item, max_chars) for item in value[:20]]
    if isinstance(value, str):
        return _truncate(value, max_chars)
    return value


def _truncate(value: str, max_chars: int) -> str:
    text = str(value or "").strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 12].rstrip() + "..."


def _as_string_list(value: Any) -> list[str]:
    if value in (None, "", []):
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip() for item in re.split(r"[\n,，、;；]+", value) if item.strip()]
    return [str(value).strip()] if str(value).strip() else []


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, list):
        return {"items": value} if value else {}
    text = _text(value)
    return {"summary": text} if text else {}


def _as_list_of_dicts(value: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in _as_list(value):
        if isinstance(item, dict):
            clean = {str(key): item_value for key, item_value in item.items() if item_value not in (None, "", [])}
            if clean:
                result.append(clean)
        else:
            text = _text(item)
            if text:
                result.append({"summary": text})
    return result


def _as_list(value: Any) -> list[Any]:
    if value in (None, "", []):
        return []
    if isinstance(value, list):
        return [item for item in value if item not in (None, "", [])]
    if isinstance(value, str):
        return [item.strip() for item in re.split(r"[\n,，、;；]+", value) if item.strip()]
    return [value]


def _text(value: Any) -> str:
    return str(value or "").strip()


def _now_version_month() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y_%m")


def _now_iso() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}
