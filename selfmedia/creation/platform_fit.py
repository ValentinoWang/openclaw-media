from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from common.llm_validation import LLMValidationContract, register_llm_validation_contract

from .llm_generator import call_creation_json, creation_generation_metadata
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
LLM_SEMANTIC_PERSISTENCE_ERROR_CODE = "LLM_SEMANTIC_PERSISTENCE_REQUIRED"


class SemanticPersistenceRequiredError(RuntimeError):
    pass


class PlatformMechanismConfigError(RuntimeError):
    """Raised when an explicitly selected platform config cannot be trusted."""


def _semantic_persistence_error(area: str, reason: str, detail: str = "") -> SemanticPersistenceRequiredError:
    parts = [LLM_SEMANTIC_PERSISTENCE_ERROR_CODE, area, reason]
    if detail:
        parts.append(detail[-1000:])
    return SemanticPersistenceRequiredError(":".join(parts))


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
    if _env_bool("SELFMEDIA_CREATION_PLATFORM_FIT_DISABLE_LLM", False):
        raise _semantic_persistence_error("platform_mechanism_fit", "llm_disabled")

    prompt = build_platform_mechanism_prompt(
        request,
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
            result = call_creation_json(
                message,
                validation_contract=PLATFORM_FIT_VALIDATION_CONTRACT,
                validation_context={"request": request},
            )
            result["generation"] = creation_generation_metadata("platform_mechanism_fit")
            result["platform_fit_meta"] = _build_platform_fit_meta(
                request,
                mechanism_version=str(result.get("platform_mechanism_version") or ""),
                mechanism_source="llm",
                baseline_source=str((default_platform_mechanism(request.platform)).get("mechanism_source") or "config"),
                activity_candidates=activity_candidates,
                viral_candidates=viral_candidates,
                inspiration_candidates=inspiration_candidates,
                business_candidates=business_candidates,
                reference_docs=reference_docs,
                media_context=media_context,
                include_llm=True,
            )
            return result
        except Exception as exc:
            last_error = str(exc)
            if attempt >= retries:
                break

    raise _semantic_persistence_error("platform_mechanism_fit", _failure_reason(last_error), last_error)


def build_platform_mechanism_prompt(
    request: CreationRequest,
    *,
    activity_candidates: list[dict[str, Any]],
    viral_candidates: list[dict[str, Any]],
    inspiration_candidates: list[dict[str, Any]],
    business_candidates: list[dict[str, Any]],
    reference_docs: list[dict[str, str]],
    media_context: dict[str, Any],
) -> str:
    payload = {
        "request": request.to_dict(),
        "platform_mechanism_reference": default_platform_mechanism(request.platform),
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
        "2. platform_mechanism_version 必须由你基于输入和 platform_mechanism_reference 输出；不确定时返回风险说明，不要留空。\n"
        "3. mechanism_claim_boundary 必须说明：这是机制拟合假设，不是平台真实算法或权重结论。\n"
        "4. mechanism_evidence_level 只能是 S/A/B/C/D：S=官方公开规则，A=本账号多次复盘，B=爆款拆解加少量自有数据，C=公开创作者实测，D=待验证假设。\n"
        "5. source_weights 必须是 object，键为实际使用的证据来源（例如官方规则、账号复盘、爆款拆解、活动 Brief、人工假设），值为 0-1 的相对权重；只写输入中真实存在的来源。\n"
        "6. creation_reverse_plan 必须能反推到标题、封面/首屏、开头、内容结构、收藏/评论/关注触发。\n"
        "7. validation_targets 必须给出 2 小时、24 小时、7 天的可观察验证指标。\n"
        "8. post_publish_correction 必须说明点击低、停留低、收藏/互动低、活动不适配时分别修什么。\n"
        "9. activity_strategy 必须包含 matched_activities, natural_fit, hard_fit_risk, risk_reason, required_adjustments, do_not_force；hard_fit_risk 只能是 low/medium/high。\n"
        "10. 不得编造活动 ID、爆款数据、账号数据或官方公告；不得出现“破解算法/平台真实权重/保证爆款/必爆”等表述。\n\n"
        "输出 JSON 字段固定为：\n"
        f"{', '.join(FIT_SCHEMA_KEYS)}。\n\n"
        "输入 JSON：\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )


def validate_platform_mechanism_fit_payload(
    payload: dict[str, Any],
    request: CreationRequest,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("平台推荐拟合 JSON 顶层必须是 object")
    result: dict[str, Any] = {}
    result["platform_mechanism_version"] = _text(payload.get("platform_mechanism_version"))
    result["mechanism_claim_boundary"] = _text(payload.get("mechanism_claim_boundary"))
    result["mechanism_evidence_level"] = _normalize_fit_evidence_level(payload.get("mechanism_evidence_level"))
    result["source_weights"] = _normalize_source_weights(payload.get("source_weights"))
    for key in (
        "platform_strategy",
        "activity_strategy",
        "traffic_hypothesis",
        "creation_reverse_plan",
        "validation_targets",
        "post_publish_correction",
    ):
        value = _as_dict(payload.get(key))
        if value:
            result[key] = value
    result["risks_or_missing_info"] = _as_string_list(payload.get("risks_or_missing_info"))
    result["activity_strategy"] = _normalize_activity_strategy(result.get("activity_strategy"), {})
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


def _normalize_fit_evidence_level(value: Any) -> str:
    level = _text(value).upper()
    if level not in {"S", "A", "B", "C", "D"}:
        raise ValueError("mechanism_evidence_level 必须是 S/A/B/C/D")
    return level


def _normalize_source_weights(value: Any) -> dict[str, float]:
    weights = _as_dict(value)
    if not weights:
        raise ValueError("source_weights 必须是非空 object")
    normalized: dict[str, float] = {}
    for source, raw_weight in weights.items():
        name = _text(source)
        if not name or isinstance(raw_weight, bool) or not isinstance(raw_weight, (int, float)):
            raise ValueError("source_weights 的键必须非空且权重必须是 0-1 数字")
        weight = float(raw_weight)
        if not 0 <= weight <= 1:
            raise ValueError("source_weights 的权重必须在 0-1")
        normalized[name] = weight
    if not any(normalized.values()):
        raise ValueError("source_weights 至少需要一个大于 0 的权重")
    return normalized


def parse_platform_mechanism_note(
    platform: str,
    raw_text: str,
    *,
    source_type: str = "creator_test",
    persist: bool = False,
    use_llm: bool = True,
) -> dict[str, Any]:
    baseline = default_platform_mechanism(platform)
    if use_llm and not _env_bool("SELFMEDIA_PLATFORM_MECHANISM_NOTE_DISABLE_LLM", False):
        prompt = _build_platform_mechanism_note_prompt(platform, raw_text, source_type=source_type, baseline=baseline)
        try:
            result = call_creation_json(
                prompt,
                validation_contract=PLATFORM_NOTE_VALIDATION_CONTRACT,
                validation_context={"platform": platform, "source_type": source_type},
            )
            result["parser"] = {"provider": "codex_responses"}
        except Exception as exc:
            raise _semantic_persistence_error("platform_mechanism_note", "llm_failed", str(exc)) from exc
    else:
        raise _semantic_persistence_error("platform_mechanism_note", "llm_disabled")
    if persist:
        persist_platform_mechanism_observation(result)
    return result


def validate_platform_mechanism_note_payload(
    payload: dict[str, Any],
    *,
    platform: str,
    source_type: str,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("平台机制材料解析 JSON 顶层必须是 object")
    result: dict[str, Any] = {}
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
    result["generated_at"] = _text(payload.get("generated_at")) or _now_iso()
    _assert_no_forbidden_claims(result)
    return result


def _validate_platform_fit_contract(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    request = context.get("request")
    if not isinstance(request, CreationRequest):
        raise ValueError("platform fit validation requires CreationRequest context")
    return validate_platform_mechanism_fit_payload(payload, request)


def _validate_platform_note_contract(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    return validate_platform_mechanism_note_payload(
        payload,
        platform=str(context.get("platform") or ""),
        source_type=str(context.get("source_type") or ""),
    )


PLATFORM_FIT_VALIDATION_CONTRACT = register_llm_validation_contract(
    LLMValidationContract(
        contract_id="selfmedia.creation.platform_fit.v1",
        profile="strict_structured",
        validator=_validate_platform_fit_contract,
    )
)
PLATFORM_NOTE_VALIDATION_CONTRACT = register_llm_validation_contract(
    LLMValidationContract(
        contract_id="selfmedia.creation.platform_note.v1",
        profile="strict_structured",
        validator=_validate_platform_note_contract,
    )
)


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
    baseline: dict[str, Any],
) -> str:
    payload = {
        "platform": platform,
        "source_type": source_type,
        "default_evidence_level": _source_type_evidence_level(source_type),
        "baseline": baseline,
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
        "status 只能是 candidate/active/inactive，外部实测默认 candidate。\n"
        "不得出现“破解算法”“平台真实权重”“黑箱权重”“精确权重”“保证爆款”“必爆”等表述。\n\n"
        "输入 JSON：\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )


def _normalize_hypothesis(value: Any, *, evidence_level: str) -> dict[str, Any]:
    data = _as_dict(value)
    if not data:
        return {}
    claim = _sanitize_forbidden_claims(_text(data.get("claim") or data.get("summary")))
    if not claim:
        return {}
    status = _text(data.get("status")) or "candidate"
    if status not in {"candidate", "active", "inactive"}:
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


def _normalize_activity_strategy(value: Any, baseline: Any) -> dict[str, Any]:
    base = _as_dict(baseline)
    supplied = _as_dict(value)
    required = ("hard_fit_risk", "risk_reason")
    missing = [key for key in required if key not in supplied and key not in base]
    if missing:
        raise ValueError(f"activity_strategy 缺少必填字段：{missing}")
    strategy = {**base, **supplied}
    risk = str(strategy.get("hard_fit_risk") or "").strip().lower()
    if risk not in {"low", "medium", "high"}:
        raise ValueError("activity_strategy.hard_fit_risk 必须是 low、medium 或 high")
    strategy["hard_fit_risk"] = risk
    strategy["matched_activities"] = _as_list_of_dicts(strategy.get("matched_activities"))
    strategy["candidate_activity_ids"] = _as_string_list(strategy.get("candidate_activity_ids"))
    strategy["natural_fit"] = bool(strategy.get("natural_fit")) if "natural_fit" in strategy else risk != "high"
    strategy["risk_reason"] = _text(strategy.get("risk_reason"))
    if not strategy["risk_reason"]:
        raise ValueError("activity_strategy.risk_reason 不能为空")
    strategy["required_adjustments"] = _as_string_list(strategy.get("required_adjustments"))
    strategy["do_not_force"] = _as_string_list(strategy.get("do_not_force"))
    if not strategy["do_not_force"]:
        raise ValueError("activity_strategy.do_not_force 不能为空")
    return strategy


def _build_platform_fit_meta(
    request: CreationRequest,
    *,
    mechanism_version: str,
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


def _failure_reason(error: str) -> str:
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
        "mechanism_source": "config_reference",
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


def fallback_platform_mechanism_fit(
    request: CreationRequest,
    *,
    failure_reason: str,
    activity_candidates: list[dict[str, Any]],
    viral_candidates: list[dict[str, Any]],
    inspiration_candidates: list[dict[str, Any]],
    business_candidates: list[dict[str, Any]],
    reference_docs: list[dict[str, str]],
    media_context: dict[str, Any],
) -> dict[str, Any]:
    """Return an explicitly marked baseline when the auxiliary fit LLM is unavailable."""
    baseline = default_platform_mechanism(request.platform)
    actions_key = "image_actions" if request.content_type == "图文" else "video_actions"
    actions = _as_dict(baseline.get(actions_key))
    risk = f"平台推荐拟合暂不可用（{_text(failure_reason) or '未知原因'}）；本次仅按已加载的平台公开机制基线执行，发布后需要人工复核数据。"
    result = {
        "platform_mechanism_version": _text(baseline.get("version")) or f"{platform_slug(request.platform)}_baseline",
        "mechanism_claim_boundary": "这是未经过本轮 LLM 拟合的平台机制基线，不是平台真实算法或权重结论。",
        "mechanism_evidence_level": "D",
        "source_weights": {"platform_mechanism_baseline": 1.0},
        "platform_strategy": {
            "summary": _text(baseline.get("platform_lens")),
            "primary_entries": _as_string_list(baseline.get("primary_entries")),
            "key_feedback": _text(baseline.get("key_feedback")),
            "content_actions": actions,
        },
        "activity_strategy": {
            "matched_activities": [],
            "candidate_activity_ids": [],
            "natural_fit": False,
            "hard_fit_risk": "low",
            "risk_reason": "本轮未完成活动适配拟合，不能为了活动改写内容主线。",
            "required_adjustments": [],
            "do_not_force": ["不要为了活动改写内容主线。"],
        },
        "traffic_hypothesis": {
            "summary": "仅以平台机制基线设计标题、首屏和互动动作，具体效果需要发布后验证。",
            "click_reason": _text(baseline.get("click_reason")),
            "stay_reason": _text(baseline.get("stay_reason")),
            "interaction_reason": _text(baseline.get("save_or_interaction_reason")),
        },
        "creation_reverse_plan": {
            "cover_or_first_screen": _as_string_list(actions.get("cover_or_first_screen")),
            "opening": _as_string_list(actions.get("opening")),
            "structure": _as_string_list(actions.get("structure")),
            "interaction_trigger": _as_string_list(actions.get("save_comment_follow_trigger")),
        },
        "validation_targets": _as_dict(baseline.get("validation_targets")),
        "post_publish_correction": {
            "if_low_click": "复核标题和封面是否清楚点出具体人群与问题。",
            "if_low_stay": "复核开头是否兑现承诺，并减少抽象铺垫。",
            "if_low_interaction": "补充可保存的具体动作或明确的评论问题。",
            "if_activity_mismatch": "停止强行绑定活动，保留内容主线。",
        },
        "risks_or_missing_info": [risk],
        "platform": request.platform,
        "content_type": request.content_type,
        "track": request.track,
        "topic": request.topic,
        "fallback_used": True,
        "fallback_reason": _text(failure_reason),
    }
    result["platform_fit_meta"] = {
        **_build_platform_fit_meta(
            request,
            mechanism_version=result["platform_mechanism_version"],
            mechanism_source="baseline_fallback",
            baseline_source=str(baseline.get("mechanism_source") or "config"),
            activity_candidates=activity_candidates,
            viral_candidates=viral_candidates,
            inspiration_candidates=inspiration_candidates,
            business_candidates=business_candidates,
            reference_docs=reference_docs,
            media_context=media_context,
            include_llm=False,
        ),
        "fallback_used": True,
        "fallback_reason": _text(failure_reason),
    }
    return result


def load_platform_mechanism_config(platform: str) -> dict[str, Any]:
    raw_dir = os.getenv("SELFMEDIA_PLATFORM_MECHANISM_CONFIG_DIR", "").strip()
    config_dir = Path(raw_dir).expanduser() if raw_dir else DEFAULT_PLATFORM_MECHANISM_CONFIG_DIR
    path = config_dir / f"{platform_slug(platform)}.json"
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise PlatformMechanismConfigError(f"平台机制配置不可读：{path}") from exc
    except json.JSONDecodeError as exc:
        raise PlatformMechanismConfigError(f"平台机制配置 JSON 损坏：{path}") from exc
    if not isinstance(payload, dict) or payload.get("status") not in ("", None, "active"):
        raise PlatformMechanismConfigError(f"平台机制配置未激活或结构无效：{path}")
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
            if not hypothesis or hypothesis.get("status") == "inactive":
                continue
            hypotheses.append(hypothesis)
    return hypotheses[-20:]


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
                result["_truncated_keys"] = len(value) - 30
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
