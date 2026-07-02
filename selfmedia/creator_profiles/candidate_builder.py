from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .extractor import current_metrics_summary
from .schemas import CREATOR_PROFILE_FIELDS, LIST_FIELDS, SEMANTIC_FIELDS, creator_profile_id, normalize_platform


PACKAGE_ROOT = Path(__file__).resolve().parent

from common.llm_client import generate_json_from_parts
from common.llm_settings import load_profile_llm_settings


PROMPT_PATH = PACKAGE_ROOT / "prompts" / "creator_profile_candidate_v2.md"


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
    metrics = current_metrics_summary(profile)

    candidates: dict[str, dict[str, Any]] = {
        "creator_profile_id": field_candidate(creator_profile_id(platform, author_id), confidence=1.0, evidence=["system key from platform+author_id"], reason="Stable v2 CreatorProfile primary key."),
        "platform": field_candidate(platform, confidence=1.0, evidence=["user input and resolver platform"], reason="Platform is supplied by user and normalized by resolver."),
        "author_id": field_candidate(author_id, confidence=0.97 if author_id else 0.0, evidence=[f"public profile matched input id {author_id}"] if author_id else [], reason="Resolved author id equals the input display id."),
        "account_name": field_candidate(account_name, confidence=0.95 if account_name else 0.0, evidence=["public profile title/text"], reason="Account name came from public profile text."),
        "profile_url": field_candidate(profile_url, confidence=0.95 if profile_url else 0.0, evidence=["resolved public profile url"], reason="Profile URL came from resolver."),
        "current_metrics_summary": field_candidate(metrics, confidence=0.9 if metrics else 0.0, evidence=["public rendered text or embedded public profile data"], reason="Metrics are deterministic public extractions."),
    }

    semantic = llm_payload if llm_payload is not None else (call_llm_candidate(resolver_result, profile) if use_llm else {})
    llm_status = "ok" if semantic else ("skipped" if not use_llm else "failed")
    semantic_candidates = normalize_semantic_candidates(semantic.get("field_candidates") if isinstance(semantic, dict) else {})
    for field in SEMANTIC_FIELDS:
        candidates[field] = semantic_candidates.get(field) or empty_semantic_candidate(field)

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
    parts = [{"text": prompt + "\n\nPublic evidence JSON:\n" + json.dumps(evidence, ensure_ascii=False, indent=2)}]
    try:
        return generate_json_from_parts(parts, load_profile_llm_settings("media_analysis"), max_retries=1, error_prefix="CreatorProfile candidate LLM failed")
    except Exception:
        return {}


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


def empty_semantic_candidate(field: str) -> dict[str, Any]:
    value: Any = [] if field in LIST_FIELDS else ""
    return field_candidate(value, confidence=0.0, evidence=[], reason="LLM candidate unavailable or public evidence insufficient; keep pending/manual.")


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
