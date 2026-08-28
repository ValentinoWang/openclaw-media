from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from common.llm_client import generate_json_from_parts
from common.llm_settings import load_profile_llm_settings
from common.llm_validation import LLMValidationContract, register_llm_validation_contract, validate_llm_payload

from media_vault.vault import MediaVault, make_timestamp_id

from .context_loader import StyleContext, load_style_context
from .contract import (
    STYLE_POLISH_CAPABILITY,
    StylePolishRequest,
    StylePolishResult,
    StyleSourceTrace,
    StyleVersion,
)
from .feedback import empty_feedback_record
from .validators import _remove_must_keep, validate_version_text


StylePayloadProvider = Callable[[str], dict[str, Any]]
STYLE_SCORE_FIELDS = ("naturalness", "voice", "clarity", "fact_fidelity")


def _validate_style_payload(payload: dict[str, Any], validation_context: dict[str, Any]) -> dict[str, Any]:
    request = validation_context.get("request")
    context = validation_context.get("style_context")
    if not isinstance(request, StylePolishRequest) or not isinstance(context, StyleContext):
        raise ValueError("style polish validation requires request and style_context")

    diagnosis = _string_list(payload.get("diagnosis"))
    strategy = str(payload.get("style_strategy") or "").strip()
    raw_versions = payload.get("versions")
    recommended_name = str(payload.get("recommended_version") or "").strip()
    if not diagnosis:
        raise ValueError("diagnosis must contain at least one item")
    if not strategy:
        raise ValueError("style_strategy must not be empty")
    if not isinstance(raw_versions, list) or not 1 <= len(raw_versions) <= request.variants:
        raise ValueError(f"versions must contain between 1 and {request.variants} items")

    versions: list[dict[str, Any]] = []
    names: set[str] = set()
    for index, raw_version in enumerate(raw_versions, start=1):
        if not isinstance(raw_version, dict):
            raise ValueError(f"versions[{index}] must be an object")
        unknown = set(raw_version) - {"name", "text", "target_use", "score_breakdown", "risk_notes"}
        if unknown:
            raise ValueError(f"versions[{index}] contains unknown fields: {sorted(unknown)}")
        name = str(raw_version.get("name") or "").strip()
        text = str(raw_version.get("text") or "").strip()
        target_use = str(raw_version.get("target_use") or "").strip()
        if not name or not text or not target_use:
            raise ValueError(f"versions[{index}] requires name, text, and target_use")
        if name in names:
            raise ValueError(f"duplicate version name: {name}")
        names.add(name)
        failures = validate_version_text(request, text, platform_mechanism=context.platform_mechanism)
        residual = _remove_must_keep(text, request.must_keep)
        failures.extend(
            f"出现通用模板表达：{phrase}"
            for phrase in context.anti_patterns
            if phrase and phrase in residual
        )
        if failures:
            raise ValueError("; ".join(failures))
        scores = _validate_style_scores(raw_version.get("score_breakdown"), index=index)
        versions.append(
            {
                "name": name,
                "text": text,
                "target_use": target_use,
                "score_breakdown": scores,
                "risk_notes": _string_list(raw_version.get("risk_notes")),
            }
        )

    if recommended_name not in names:
        raise ValueError("recommended_version must name one generated version")
    return {
        "diagnosis": diagnosis,
        "style_strategy": strategy,
        "versions": versions,
        "recommended_version": recommended_name,
    }


STYLE_POLISH_VALIDATION_CONTRACT = register_llm_validation_contract(
    LLMValidationContract(
        contract_id="selfmedia.style.polish.v1",
        profile="strict_structured",
        required_fields=("diagnosis", "style_strategy", "versions", "recommended_version"),
        allowed_fields=frozenset({"diagnosis", "style_strategy", "versions", "recommended_version"}),
        validator=_validate_style_payload,
    )
)


def run_style_polish(
    request: StylePolishRequest,
    *,
    tenant_id: str,
    vault_root: str | Path | None = None,
    run_id: str | None = None,
    provider: StylePayloadProvider | None = None,
) -> StylePolishResult:
    if not request.raw_text:
        raise ValueError("StylePolishRequest.raw_text is required")

    vault = MediaVault(tenant_id=tenant_id, root=vault_root)
    context = load_style_context(request, tenant_id=tenant_id, memory_root=vault.root / "account_memory")
    actual_run_id = run_id or make_timestamp_id("style_polish")
    run_dir = vault.root / "style_polish_runs" / actual_run_id
    artifact_uri = vault.to_uri(run_dir / "result.json")
    source_trace = context.source_trace
    llm_payload = _generate_style_payload(request, context, provider=provider)
    versions = _build_versions(llm_payload, source_trace=source_trace)
    diagnosis = tuple(llm_payload["diagnosis"])
    risk_notes = tuple(_collect_risk_notes(versions))
    result = StylePolishResult(
        run_id=actual_run_id,
        diagnosis=diagnosis,
        style_strategy=str(llm_payload["style_strategy"]),
        versions=tuple(versions),
        recommended_version=str(llm_payload["recommended_version"]),
        score_breakdown=_aggregate_scores(versions),
        risk_notes=risk_notes,
        source_trace=source_trace,
        feedback_record=empty_feedback_record(),
        artifact_uri=artifact_uri,
        creation_run_binding=_creation_binding(request, artifact_uri),
    )
    _persist_run(vault, run_dir, request, context, result)
    return result


def _generate_style_payload(
    request: StylePolishRequest,
    context: StyleContext,
    *,
    provider: StylePayloadProvider | None,
) -> dict[str, Any]:
    prompt = _build_style_prompt(request, context)
    validation_context = {"request": request, "style_context": context}
    if provider is not None:
        return validate_llm_payload(
            provider(prompt),
            STYLE_POLISH_VALIDATION_CONTRACT,
            context=validation_context,
        ).payload

    settings = load_profile_llm_settings("media_creation")
    return generate_json_from_parts(
        [{"text": prompt}],
        settings,
        max_retries=1,
        error_prefix="StylePolish LLM output validation failed",
        instructions="你是 Media 的自然中文编辑。只输出合法 JSON object，不要 Markdown，不要解释。",
        validation_contract=STYLE_POLISH_VALIDATION_CONTRACT,
        validation_context=validation_context,
    )


def _build_style_prompt(request: StylePolishRequest, context: StyleContext) -> str:
    payload = {
        "request": request.to_dict(),
        "account_context": {
            "loaded": context.media_context.get("loaded") or {},
            "prompt": context.media_context.get("prompt") or "",
            "profile": context.creator_profile,
            "recent_lessons": list(context.recent_lessons),
            "proven_patterns": list(context.proven_patterns),
            "avoid_patterns": list(context.avoid_patterns),
        },
        "platform_mechanism": context.platform_mechanism,
        "anti_patterns": list(context.anti_patterns),
    }
    return (
        "你是一个懂中文社交媒体语感的真人编辑。请改写用户已经提供的文字，不要写审稿报告。\n\n"
        "先在脑中把原文当成作者给朋友发的一段语音：像给朋友发一段 30 秒语音那样复述一遍，再把这种语气写下来。\n"
        "改写要求：\n"
        "1. 先交付可直接使用的成稿。不要在 text 里出现分析、修改说明、版本 A/B、推荐理由、run_id、artifact 或 source_trace。\n"
        "2. 一段只讲一件事。减少名词堆叠和流程图句式，多用人物动作、现场观察、停顿和具体判断。\n"
        "3. 保留一点自然节奏，不要把每段写得同样长，也不要为了口语化机械添加‘说实话’‘其实’‘那一刻’。\n"
        "4. 把作者为什么在意、看到哪一步产生判断写清楚；没有输入依据时不要补个人经历或情绪。\n"
        "5. 保留原文所有可验证事实、专名、因果边界和合规限定。不得把演示、相关或参考结果升级成已证实的控制、诊断或疗效。\n"
        "6. 必须保留 must_keep；不得在 must_keep 之外出现 avoid、anti_patterns 或平台禁用宣称。账号资料没读到时，不模拟账号人格。\n"
        "7. 小红书正文优先第一人称现场感、短段落和一个清楚判断；标题必须是人会点开的具体体验，不堆地点、编号和流程术语。\n"
        "8. 只生成 request.variants 指定数量，默认只给一个最自然、可直接发布的版本，不用凑三版。\n\n"
        "输出 JSON 固定为：diagnosis, style_strategy, versions, recommended_version。\n"
        "diagnosis 是内部审计用的短数组；style_strategy 是一句内部策略。\n"
        "versions 每项固定字段为 name, text, target_use, score_breakdown, risk_notes。\n"
        "score_breakdown 是可选诊断字段；如提供，使用 naturalness, voice, clarity, fact_fidelity 四项，每项为可转成 1-5 的数值。\n"
        "risk_notes 是内部风险短数组。recommended_version 必须等于某个 versions.name。\n\n"
        "输入 JSON：\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )


def _build_versions(payload: dict[str, Any], *, source_trace: tuple[StyleSourceTrace, ...]) -> list[StyleVersion]:
    return [
        StyleVersion(
            name=str(item["name"]),
            text=str(item["text"]),
            target_use=str(item["target_use"]),
            score_breakdown=dict(item["score_breakdown"]),
            risk_notes=tuple(item["risk_notes"]),
            source_trace=source_trace,
        )
        for item in payload["versions"]
    ]


def _collect_risk_notes(versions: list[StyleVersion]) -> list[str]:
    seen: set[str] = set()
    notes: list[str] = []
    for version in versions:
        for note in version.risk_notes:
            if note not in seen:
                seen.add(note)
                notes.append(note)
    return notes


def _aggregate_scores(versions: list[StyleVersion]) -> dict[str, Any]:
    if not versions:
        return {}
    keys = sorted({key for version in versions for key in version.score_breakdown})
    return {
        key: min(int(version.score_breakdown[key]) for version in versions if key in version.score_breakdown)
        for key in keys
    }


def _creation_binding(request: StylePolishRequest, artifact_uri: str) -> dict[str, Any]:
    if not request.should_bind_creation_run:
        return {"bound": False, "reason": "explicit style polish run without creation/material/draft id"}
    return {
        "bound": True,
        "creation_id": request.creation_id,
        "material_id": request.material_id,
        "draft_id": request.draft_id,
        "style_pass_artifact_uri": artifact_uri,
        "feishu_write_policy": "summary_and_link_only",
    }


def _persist_run(vault: MediaVault, run_dir: Path, request: StylePolishRequest, context: StyleContext, result: StylePolishResult) -> None:
    owner_id = result.run_id
    vault.write_json_artifact(
        run_dir,
        "request.json",
        {"capability": STYLE_POLISH_CAPABILITY, **request.to_dict()},
        owner_type="StylePolishRun",
        owner_id=owner_id,
        artifact_type="style_polish_request",
    )
    vault.write_json_artifact(
        run_dir,
        "context.json",
        context.to_dict(),
        owner_type="StylePolishRun",
        owner_id=owner_id,
        artifact_type="style_polish_context",
    )
    vault.write_json_artifact(
        run_dir,
        "result.json",
        result.to_dict(),
        owner_type="StylePolishRun",
        owner_id=owner_id,
        artifact_type="style_polish_result",
    )
    vault.write_json_artifact(
        run_dir,
        "feedback_record.json",
        result.feedback_record.to_dict(),
        owner_type="StylePolishRun",
        owner_id=owner_id,
        artifact_type="style_polish_feedback",
    )


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item or "").strip()]


def _validate_style_scores(value: Any, *, index: int) -> dict[str, int]:
    if value in (None, {}):
        return {}
    if not isinstance(value, dict) or not set(value).issubset(set(STYLE_SCORE_FIELDS)):
        raise ValueError(f"versions[{index}].score_breakdown must use only {STYLE_SCORE_FIELDS}")
    scores: dict[str, int] = {}
    for field in value:
        score = value[field]
        if isinstance(score, bool):
            raise ValueError(f"versions[{index}].score_breakdown.{field} must be numeric from 1 to 5")
        try:
            normalized = int(float(score))
        except (TypeError, ValueError):
            raise ValueError(f"versions[{index}].score_breakdown.{field} must be numeric from 1 to 5") from None
        if not 1 <= normalized <= 5:
            raise ValueError(f"versions[{index}].score_breakdown.{field} must be numeric from 1 to 5")
        scores[field] = normalized
    return scores
