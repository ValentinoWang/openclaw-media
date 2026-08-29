from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .extractor import current_metrics_summary, normalize_public_http_url
from .schemas import CREATOR_PROFILE_FIELDS, LIST_FIELDS, SEMANTIC_FIELDS, creator_profile_id, normalize_platform


PACKAGE_ROOT = Path(__file__).resolve().parent

from common.llm_client import generate_json_from_parts
from common.llm_settings import load_profile_llm_settings
from common.llm_validation import LLMValidationContract, register_llm_validation_contract


PROMPT_PATH = PACKAGE_ROOT / "prompts" / "creator_profile_candidate_v2.md"


def _chinese_ratio(value: Any) -> float:
    text = str(value or "")
    cjk = len(re.findall(r"[\u3400-\u9fff]", text))
    letters = len(re.findall(r"[A-Za-z\u3400-\u9fff]", text))
    return cjk / letters if letters else 1.0


def _validate_chinese_text(value: Any, *, location: str) -> None:
    if isinstance(value, str) and value.strip() and _chinese_ratio(value) < 0.2:
        raise ValueError(f"{location} 必须使用中文，不能直接回灌英文或翻译腔")


def _validate_creator_profile_candidate(payload: dict[str, Any], _context: dict[str, Any]) -> dict[str, Any]:
    candidates = payload.get("field_candidates")
    if not isinstance(candidates, dict) or not candidates:
        raise ValueError("field_candidates 必须是非空对象")
    unknown_fields = set(candidates) - set(SEMANTIC_FIELDS)
    if unknown_fields:
        raise ValueError(f"field_candidates 含不允许的字段：{sorted(unknown_fields)}")
    for field_name, item in candidates.items():
        if not isinstance(item, dict):
            raise ValueError(f"field_candidates.{field_name} 必须是对象")
        if not isinstance(item.get("evidence"), list) or not str(item.get("reason") or "").strip():
            raise ValueError(f"field_candidates.{field_name} 必须包含 evidence 和 reason")
        required = {"value", "evidence", "confidence", "reason"}
        missing = required - set(item)
        if missing:
            raise ValueError(f"field_candidates.{field_name} 缺少字段：{sorted(missing)}")
        confidence = item.get("confidence")
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
            raise ValueError(f"field_candidates.{field_name}.confidence 必须是 0 到 1 之间的数字")
        value = item.get("value")
        if field_name in LIST_FIELDS and not isinstance(value, list):
            raise ValueError(f"field_candidates.{field_name}.value 必须是数组")
        if field_name not in LIST_FIELDS and not isinstance(value, str):
            raise ValueError(f"field_candidates.{field_name}.value 必须是文本")
        _validate_chinese_text(value, location=f"field_candidates.{field_name}.value")
        if isinstance(value, list):
            for index, part in enumerate(value):
                _validate_chinese_text(part, location=f"field_candidates.{field_name}.value[{index}]")
        _validate_chinese_text(item.get("reason"), location=f"field_candidates.{field_name}.reason")
        for index, evidence in enumerate(item["evidence"]):
            if not isinstance(evidence, str) or not evidence.strip():
                raise ValueError(f"field_candidates.{field_name}.evidence[{index}] 必须是非空文本")
            _validate_chinese_text(evidence, location=f"field_candidates.{field_name}.evidence[{index}]")
    missing_fields = set(SEMANTIC_FIELDS) - set(candidates)
    if missing_fields:
        raise ValueError(f"field_candidates 缺少字段：{sorted(missing_fields)}")
    return payload


CREATOR_PROFILE_CANDIDATE_VALIDATION_CONTRACT = register_llm_validation_contract(
    LLMValidationContract(
        contract_id="selfmedia.creator_profile.candidate.v1",
        profile="bounded_open",
        required_fields=("field_candidates",),
        non_empty_fields=("field_candidates",),
        field_types={"field_candidates": dict},
        evidence_fields=("field_candidates",),
        validator=_validate_creator_profile_candidate,
    )
)


def field_candidate(value: Any, *, confidence: float, evidence: list[str], reason: str) -> dict[str, Any]:
    return {"value": value, "confidence": confidence, "evidence": evidence, "reason": reason}


def build_candidate(
    *,
    run_id: str,
    resolver_result: dict[str, Any],
    evidence_uri: str,
    use_llm: bool = True,
    llm_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    profile = resolver_result.get("extracted_profile") if isinstance(resolver_result.get("extracted_profile"), dict) else {}
    platform = normalize_platform(resolver_result.get("platform") or profile.get("platform"))
    author_id = str(resolver_result.get("resolved_author_id") or profile.get("author_id") or resolver_result.get("input_platform_id") or "").strip()
    account_name = str(resolver_result.get("account_name") or profile.get("account_name") or "").strip()
    profile_url = str(resolver_result.get("resolved_profile_url") or profile.get("profile_url") or profile.get("homepage_link") or "").strip()
    avatar_url = normalize_public_http_url(profile.get("avatar_url"))
    metrics = current_metrics_summary(profile)
    explicit_identity = resolver_result.get("source") == "explicit_user_fields"
    identity_source = "用户明确提供" if explicit_identity else ("用户输入匹配公开主页" if resolver_result.get("input_platform_id") else "公开主页链接")
    author_evidence = list(resolver_result.get("success_evidence") or []) if author_id else []
    account_evidence = ["用户明确提供"] if explicit_identity else ["公开主页标题或文本"]

    candidates: dict[str, dict[str, Any]] = {
        "creator_profile_id": field_candidate(creator_profile_id(platform, author_id), confidence=1.0, evidence=["系统根据 platform 和 author_id 生成的主键"], reason="CreatorProfile v2 稳定主键。"),
        "platform": field_candidate(platform, confidence=1.0, evidence=[identity_source], reason="平台由明确输入或白名单公开主页链接归一化得到。"),
        "author_id": field_candidate(author_id, confidence=1.0 if explicit_identity else (0.97 if author_id else 0.0), evidence=author_evidence, reason="作者 ID 来自用户明确输入。" if explicit_identity else "已解析的作者 ID 在公开主页中明确可见。"),
        "account_name": field_candidate(account_name, confidence=1.0 if explicit_identity else (0.95 if account_name else 0.0), evidence=account_evidence, reason="账号名称来自用户明确输入。" if explicit_identity else "账号名称来自公开主页文本。"),
        "profile_url": field_candidate(profile_url, confidence=0.95 if profile_url else 0.0, evidence=["已解析的公开主页链接"], reason="主页链接来自解析器。"),
        "avatar_url": field_candidate(avatar_url, confidence=0.95 if avatar_url else 0.0, evidence=["公开结构化主页数据"] if avatar_url else [], reason="头像链接来自明确的公开主页数据。" if avatar_url else "没有可用的公开头像链接。"),
        "current_metrics_summary": field_candidate(metrics, confidence=0.9 if metrics else 0.0, evidence=["公开渲染文本或嵌入的公开主页数据"], reason="指标由公开数据确定性提取。"),
    }

    semantic = llm_payload if llm_payload is not None else (call_llm_candidate(resolver_result, profile) if use_llm else {})
    llm_failed = use_llm and (not semantic or bool(semantic.get("_error")))
    llm_status = "failed" if llm_failed else ("ok" if semantic else "skipped")
    semantic_failure_reason = "人设候选生成失败，未注入人设字段；请重新运行或人工补充。" if llm_failed else "LLM 候选不可用或公开证据不足，保持待人工补充。"
    semantic_candidates = normalize_semantic_candidates(semantic.get("field_candidates") if isinstance(semantic, dict) else {})
    for field in SEMANTIC_FIELDS:
        candidates[field] = semantic_candidates.get(field) or empty_semantic_candidate(field, reason=semantic_failure_reason)

    payload = {field: candidates[field]["value"] for field in CREATOR_PROFILE_FIELDS}
    payload["identity_tags"] = normalize_list(payload.get("identity_tags"))
    payload["expertise_domains"] = normalize_list(payload.get("expertise_domains"))
    result = {
        "write_status": "candidate_only_not_written",
        "target_table": "06_CreatorProfiles_达人账号档案",
        "runtime_key": "MEDIA_OS_CREATOR_PROFILES_V2_URL",
        "run_id": run_id,
        "evidence_uri": evidence_uri,
        "llm_status": llm_status,
        "resolver": {
            "platform": platform,
            "input_platform_id": resolver_result.get("input_platform_id", ""),
            "input_platform_id_type": resolver_result.get("input_platform_id_type", ""),
            "resolve_status": resolver_result.get("resolve_status", ""),
            "resolved_author_id": author_id,
            "resolved_author_id_type": resolver_result.get("resolved_author_id_type", ""),
            "resolved_profile_url": profile_url,
            "account_name": account_name,
            "needs_review": True,
            "writable": False,
            "success_evidence": resolver_result.get("success_evidence", []),
        },
        "field_candidates": candidates,
        "candidate_payload": payload,
        "metric_source": {
            "fans_count": profile.get("fans_count"),
            "following_count": profile.get("following_count"),
            "total_favorited": profile.get("total_favorited"),
            "post_count": profile.get("post_count"),
            "note_count": profile.get("note_count"),
        },
    }
    return result


def call_llm_candidate(resolver_result: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    prompt = PROMPT_PATH.read_text(encoding="utf-8")
    evidence = {
        "platform": resolver_result.get("platform"),
        "account_name": resolver_result.get("account_name") or profile.get("account_name"),
        "author_id": resolver_result.get("resolved_author_id") or profile.get("author_id"),
        "bio": profile.get("bio", ""),
        "visible_post_titles": profile.get("visible_post_titles", []),
        "rendered_text_excerpt": str(resolver_result.get("rendered_text") or "")[:6000],
    }
    parts = [{"text": prompt + "\n\n公开证据 JSON：\n" + json.dumps(evidence, ensure_ascii=False, indent=2)}]
    try:
        return generate_json_from_parts(
            parts,
            load_profile_llm_settings("media_analysis"),
            max_retries=1,
            error_prefix="CreatorProfile 候选 LLM 生成失败",
            validation_contract=CREATOR_PROFILE_CANDIDATE_VALIDATION_CONTRACT,
        )
    except Exception:
        return {"_error": "llm_generation_failed"}


def normalize_semantic_candidates(payload: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(payload, dict):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for field in SEMANTIC_FIELDS:
        item = payload.get(field)
        if not isinstance(item, dict):
            continue
        value = item.get("value")
        if field in LIST_FIELDS:
            value = normalize_list(value)
        result[field] = field_candidate(
            value,
            confidence=float(item.get("confidence") or 0),
            evidence=[str(part) for part in item.get("evidence") or []],
            reason=str(item.get("reason") or ""),
        )
    return result


def empty_semantic_candidate(field: str, *, reason: str | None = None) -> dict[str, Any]:
    value: Any = [] if field in LIST_FIELDS else ""
    return field_candidate(
        value,
        confidence=0.0,
        evidence=[],
        reason=reason or "LLM 候选不可用或公开证据不足，保持待人工补充。",
    )


def normalize_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value or "").strip()
    if not text:
        return []
    parts = []
    for item in text.replace("，", ",").replace("、", ",").split(","):
        stripped = item.strip()
        if stripped:
            parts.append(stripped)
    return parts
