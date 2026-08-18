from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

from .config import load_config
from .llm_client import generate_json
from .multi_signal_schema import (
    MultiSignalContract,
    validate_dimension_analysis_payload,
    validate_multi_signal_contract_payload,
)


MULTI_SIGNAL_CONTRACT_VERSION = "multi_signal_contract.v1"

MULTI_SIGNAL_CONTRACT_PROMPT = """
你是创作交接合同草稿生成器。基于 deconstruction 摘要、evidence_store 摘要和用户创作交接意图，只输出后续创作/拍摄链路要消费的证据信号草稿。

只输出严格 JSON object，不要 Markdown，不要解释。顶层只需要这些字段：
- source_signal_dimensions: 3-6 个维度即可，按证据自然形成 visual、speech、ocr、pacing、copy、comments、engagement、risk 等；每项包含 dimension_id、status、source_refs、observations、summary、reusable_signal、transform_rule、risk_boundary、confidence、insufficient_evidence、conflict_notes。
- shot_adaptation_notes: 1-5 条镜头/图页/场景级适配建议；每项包含 note_id、source_refs、source_dimension_ids、learnable_pattern、adaptation_rule、do_not_copy、confidence。
- conflict_notes: 多信号冲突。
- open_questions: 证据不足或需要人工确认的问题。

要求：
1. 这是单次合同草稿生成，不要输出并行 worker、中间产物、独立镜头产物字段或最终再创脚本。
2. 禁止输出 editorial_plan、production_route_plan、final_script、video_storyboard、image_post_script、titles、hashtags 等 recreate() 最终字段。
3. shot_adaptation_notes 是合同内部字段，不是独立产物。
4. 证据不足只能写 insufficient_evidence/open_questions，不能补造事实。
5. source_refs 只能引用 evidence_manifest_sample 中可见的 id；不确定时少引用或留空并标记 insufficient_evidence。
6. 不需要输出 contract_version、evidence_manifest_refs、evidence_store_summary、aggregation_report、validation，这些由代码补齐。
7. 每个 source_signal_dimensions[*].status 只能从这四个字符串中选择：available、insufficient_evidence、schema_failed、llm_failed。禁止输出 available_with_caution、partial、unknown、missing、not_applicable 或其他枚举。
""".strip()


def build_multi_signal_contract(deconstruction: dict[str, Any], *, user_intent: str = "") -> dict[str, Any]:
    parts = _contract_prompt_parts(deconstruction, user_intent=user_intent)
    config = _contract_llm_config()
    return generate_json(
        parts,
        config,
        schema=None,
        post_validate=lambda payload: _normalize_multi_signal_contract_payload(deconstruction, payload),
    )


def _contract_llm_config() -> Any:
    config = load_config()
    try:
        return replace(config, thinking="")
    except TypeError:
        return config


def _normalize_multi_signal_contract_payload(deconstruction: dict[str, Any], contract_payload: dict[str, Any]) -> dict[str, Any]:
    evidence_ids = _evidence_ids(deconstruction)
    payload = dict(contract_payload or {})
    payload["contract_version"] = MULTI_SIGNAL_CONTRACT_VERSION
    payload["evidence_manifest_refs"] = sorted(evidence_ids)

    dimensions = [
        validate_dimension_analysis_payload(_normalize_dimension_status_for_schema(dimension), evidence_ids)
        for dimension in payload.get("source_signal_dimensions") or []
        if isinstance(dimension, dict)
    ]
    if not dimensions:
        raise ValueError("MultiSignalContract 至少需要一个 source_signal_dimension")
    payload["source_signal_dimensions"] = dimensions
    payload["shot_adaptation_notes"] = [
        item for item in payload.get("shot_adaptation_notes") or [] if isinstance(item, dict)
    ]
    payload["evidence_store_summary"] = payload.get("evidence_store_summary") or _evidence_store_summary(deconstruction)
    payload["aggregation_report"] = _aggregation_report(dimensions)
    payload["conflict_notes"] = _collect_contract_list(payload, "conflict_notes") or _collect_list(dimensions, "conflict_notes")
    payload["open_questions"] = _collect_contract_list(payload, "open_questions") or _open_questions(dimensions)

    warnings = _collect_contract_list(payload.get("validation") or {}, "warnings")
    if payload["aggregation_report"]["failed_dimensions"]:
        warnings.append("存在合同维度生成失败，最终再创必须显式识别证据缺口")
    if payload["aggregation_report"]["insufficient_dimensions"]:
        warnings.append("存在证据不足维度，禁止最终再创编造缺失事实")
    payload["validation"] = {
        "source_refs_status": "validated",
        "multi_signal_contract_status": "validated_with_warnings" if warnings else "validated",
        "warnings": _dedupe(warnings),
    }
    return validate_multi_signal_contract_payload(payload, evidence_ids)


def _normalize_dimension_status_for_schema(dimension: dict[str, Any]) -> dict[str, Any]:
    allowed = {"available", "insufficient_evidence", "schema_failed", "llm_failed"}
    result = dict(dimension or {})
    raw_status = str(result.get("status") or "").strip()
    if raw_status in allowed:
        return result
    notes = result.get("conflict_notes")
    if not isinstance(notes, list):
        notes = [str(notes).strip()] if str(notes or "").strip() else []
    notes.append(f"LLM 输出非法维度 status={raw_status or '<empty>'}，已按 insufficient_evidence 保守处理")
    insufficient = result.get("insufficient_evidence")
    if not isinstance(insufficient, list):
        insufficient = [str(insufficient).strip()] if str(insufficient or "").strip() else []
    if not insufficient:
        insufficient = ["维度 status 不符合合同枚举，需要人工复核后再决定是否采用"]
    result["status"] = "insufficient_evidence"
    result["conflict_notes"] = notes
    result["insufficient_evidence"] = insufficient
    return result


def _contract_prompt_parts(deconstruction: dict[str, Any], *, user_intent: str) -> list[dict[str, Any]]:
    evidence_store = deconstruction.get("evidence_store") if isinstance(deconstruction.get("evidence_store"), dict) else {}
    modality_facts = evidence_store.get("modality_facts") if isinstance(evidence_store.get("modality_facts"), dict) else deconstruction.get("modality_facts") or {}
    compact_payload = {
        "schema_version": deconstruction.get("schema_version") or "",
        "source_url": deconstruction.get("source_url") or "",
        "media_type": deconstruction.get("media_type") or "",
        "content_summary": _compact_for_prompt(deconstruction.get("content_summary") or "", max_string=500),
        "source_summary": _compact_for_prompt(deconstruction.get("source_summary") or "", max_string=500),
        "viral_reuse_assessment": _compact_for_prompt(deconstruction.get("viral_reuse_assessment") or {}, max_items=5, max_string=240, max_depth=2),
        "pacing_profile": _compact_for_prompt(deconstruction.get("pacing_profile") or {}, max_items=5, max_string=240, max_depth=2),
        "reuse_guardrails": _compact_for_prompt(deconstruction.get("reuse_guardrails") or {}, max_items=5, max_string=240, max_depth=2),
        "evidence_manifest_sample": _compact_evidence_manifest(deconstruction.get("evidence_manifest") or {}),
        "evidence_store_summary": _evidence_store_summary(deconstruction),
        "missing_evidence_report": _compact_for_prompt(evidence_store.get("missing_evidence_report") or []),
        "modality_fact_statuses": _modality_fact_statuses(modality_facts),
    }
    return [
        {"text": MULTI_SIGNAL_CONTRACT_PROMPT},
        {"text": "用户创作交接意图：\n" + str(user_intent or "").strip()},
        {"text": "deconstruction + evidence_store compact payload：\n" + json.dumps(compact_payload, ensure_ascii=False, separators=(",", ":"))},
    ]


def _evidence_ids(deconstruction: dict[str, Any]) -> set[str]:
    manifest = deconstruction.get("evidence_manifest")
    if not isinstance(manifest, dict) or not manifest:
        raise ValueError("MultiSignalContract 生成需要 deconstruction.v2.evidence_manifest")
    return {str(item) for item in manifest.keys() if str(item).strip()}


def _aggregation_report(dimensions: list[dict[str, Any]]) -> dict[str, Any]:
    available: list[str] = []
    insufficient: list[str] = []
    failed: list[str] = []
    for dimension in dimensions:
        dimension_id = str(dimension.get("dimension_id") or "")
        status = str(dimension.get("status") or "")
        if status == "available":
            available.append(dimension_id)
        elif status == "insufficient_evidence":
            insufficient.append(dimension_id)
        elif status in {"schema_failed", "llm_failed"}:
            failed.append(dimension_id)
    return {
        "dimension_count": len(dimensions),
        "available_dimensions": available,
        "insufficient_dimensions": insufficient,
        "failed_dimensions": failed,
        "source_ref_failures": [],
    }


def _collect_list(dimensions: list[dict[str, Any]], key: str) -> list[str]:
    result: list[str] = []
    for dimension in dimensions:
        values = dimension.get(key)
        if not isinstance(values, list):
            continue
        for value in values:
            text = str(value or "").strip()
            if text:
                result.append(text)
    return _dedupe(result)


def _collect_contract_list(payload: dict[str, Any], key: str) -> list[str]:
    values = payload.get(key) if isinstance(payload, dict) else []
    if not isinstance(values, list):
        return []
    return _dedupe([str(item or "").strip() for item in values if str(item or "").strip()])


def _open_questions(dimensions: list[dict[str, Any]]) -> list[str]:
    questions: list[str] = []
    for dimension in dimensions:
        dimension_id = str(dimension.get("dimension_id") or "")
        for item in dimension.get("insufficient_evidence") or []:
            text = str(item or "").strip()
            if text:
                questions.append(f"{dimension_id}: {text}")
    return questions


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _evidence_store_summary(deconstruction: dict[str, Any]) -> dict[str, Any]:
    evidence_store = deconstruction.get("evidence_store") if isinstance(deconstruction.get("evidence_store"), dict) else {}
    modality_facts = evidence_store.get("modality_facts") if isinstance(evidence_store.get("modality_facts"), dict) else deconstruction.get("modality_facts") or {}
    visual = _fact_payload(modality_facts, "visual_assets")
    engagement = _fact_payload(modality_facts, "engagement")
    comments = _fact_payload(modality_facts, "comments")
    return {
        "schema_version": "evidence_store_summary_v1",
        "evidence_store_schema": evidence_store.get("schema_version") or "",
        "visual_hook": deconstruction.get("visual_hook") or visual.get("visual_hook") or {},
        "engagement": deconstruction.get("engagement") or engagement or {},
        "comments": deconstruction.get("comments") or comments or {},
        "speech_status": (deconstruction.get("speech_transcript") or {}).get("status")
        if isinstance(deconstruction.get("speech_transcript"), dict)
        else "",
        "source_url": deconstruction.get("source_url") or "",
        "platform": deconstruction.get("platform") or "",
    }


def _fact_payload(modality_facts: dict[str, Any], fact_type: str) -> dict[str, Any]:
    fact = modality_facts.get(fact_type) if isinstance(modality_facts, dict) else {}
    if not isinstance(fact, dict):
        return {}
    payload = fact.get("facts")
    return payload if isinstance(payload, dict) else {}


def _compact_evidence_manifest(manifest: dict[str, Any], *, max_items: int = 8) -> dict[str, Any]:
    if not isinstance(manifest, dict):
        return {}
    result: dict[str, Any] = {}
    for evidence_id, payload in list(manifest.items())[:max_items]:
        item = payload if isinstance(payload, dict) else {}
        result[str(evidence_id)] = _compact_for_prompt(
            {
                "type": item.get("type") or item.get("fact_type") or "",
                "asset_id": item.get("asset_id") or "",
                "source_ref": item.get("source_ref") or "",
            },
            max_items=4,
            max_string=80,
            max_depth=2,
        )
    if len(manifest) > max_items:
        result["_truncated"] = {
            "total_evidence_ids": len(manifest),
            "included_evidence_ids": max_items,
            "note": "合同 LLM 只能引用本 sample 中可见的 source_refs；完整 evidence_manifest 仍由代码校验。",
        }
    return result


def _modality_fact_statuses(modality_facts: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(modality_facts, dict):
        return {}
    statuses: dict[str, Any] = {}
    for fact_type, fact in modality_facts.items():
        if not isinstance(fact, dict):
            continue
        statuses[str(fact_type)] = {
            "status": fact.get("status") or "",
            "missing_reason": fact.get("missing_reason") or "",
            "source_refs_sample": _compact_for_prompt(fact.get("source_refs") or [], max_items=4, max_string=80),
        }
    return statuses


def _modality_fact_summaries(modality_facts: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(modality_facts, dict):
        return {}
    summaries: dict[str, Any] = {}
    for fact_type, fact in modality_facts.items():
        if not isinstance(fact, dict):
            continue
        summaries[str(fact_type)] = {
            "status": fact.get("status") or "",
            "missing_reason": fact.get("missing_reason") or "",
            "source_refs": _compact_for_prompt(fact.get("source_refs") or [], max_items=8, max_string=120),
            "facts": _compact_for_prompt(fact.get("facts") or {}, max_items=6, max_string=260, max_depth=3),
        }
    return summaries


def _compact_for_prompt(
    value: Any,
    *,
    max_items: int = 8,
    max_string: int = 360,
    max_depth: int = 4,
) -> Any:
    if max_depth <= 0:
        if isinstance(value, (dict, list, tuple)):
            return f"<omitted {type(value).__name__}>"
        return _compact_scalar(value, max_string=max_string)
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= max_items:
                result["_truncated_keys"] = len(value) - max_items
                break
            result[str(key)] = _compact_for_prompt(item, max_items=max_items, max_string=max_string, max_depth=max_depth - 1)
        return result
    if isinstance(value, (list, tuple)):
        result = [
            _compact_for_prompt(item, max_items=max_items, max_string=max_string, max_depth=max_depth - 1)
            for item in list(value)[:max_items]
        ]
        if len(value) > max_items:
            result.append({"_truncated_items": len(value) - max_items})
        return result
    return _compact_scalar(value, max_string=max_string)


def _compact_scalar(value: Any, *, max_string: int) -> Any:
    if isinstance(value, str):
        text = value.strip()
        if len(text) > max_string:
            return text[:max_string] + f"...<truncated {len(text) - max_string} chars>"
        return text
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)[:max_string]
