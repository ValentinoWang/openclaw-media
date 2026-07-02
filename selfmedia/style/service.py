from __future__ import annotations

import re
from pathlib import Path
from typing import Any

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
from .validators import score_version, validate_version_text


def run_style_polish(
    request: StylePolishRequest,
    *,
    vault_root: str | Path | None = None,
    memory_root: str | Path | None = None,
    run_id: str | None = None,
) -> StylePolishResult:
    if not request.raw_text:
        raise ValueError("StylePolishRequest.raw_text is required")

    context = load_style_context(request, memory_root=memory_root)
    vault = MediaVault(root=vault_root)
    actual_run_id = run_id or make_timestamp_id("style_polish")
    run_dir = vault.root / "style_polish_runs" / actual_run_id
    artifact_uri = vault.to_uri(run_dir / "result.json")
    source_trace = context.source_trace
    versions = _build_versions(request, context, source_trace=source_trace)
    diagnosis = _build_diagnosis(request, context)
    risk_notes = tuple(_collect_risk_notes(versions))
    result = StylePolishResult(
        run_id=actual_run_id,
        diagnosis=tuple(diagnosis),
        style_strategy=_style_strategy(request, context),
        versions=tuple(versions[: request.variants]),
        recommended_version=versions[0].name,
        score_breakdown=_aggregate_scores(versions),
        risk_notes=risk_notes,
        source_trace=source_trace,
        feedback_record=empty_feedback_record(),
        artifact_uri=artifact_uri,
        creation_run_binding=_creation_binding(request, artifact_uri),
    )
    _persist_run(vault, run_dir, request, context, result)
    return result


def _build_versions(request: StylePolishRequest, context: StyleContext, *, source_trace: tuple[StyleSourceTrace, ...]) -> list[StyleVersion]:
    cleaned = _normalize_spacing(request.raw_text)
    candidates = [
        ("稳妥版", cleaned, "正式发布或继续人工编辑"),
        ("网感版", _short_line_breaks(_remove_anti_patterns(cleaned, context.anti_patterns, request.must_keep)), "短视频标题、封面或正文开头"),
        ("强冲突版", _frontload_first_clause(_remove_anti_patterns(cleaned, context.anti_patterns, request.must_keep)), "需要更强开头但仍需人工确认的版本"),
    ]
    versions: list[StyleVersion] = []
    for name, text, target_use in candidates:
        failures = validate_version_text(request, text, platform_mechanism=context.platform_mechanism)
        versions.append(
            StyleVersion(
                name=name,
                text=text,
                target_use=target_use,
                score_breakdown=score_version(request, text, failures=failures),
                risk_notes=tuple(failures),
                source_trace=source_trace,
            )
        )
    return versions


def _build_diagnosis(request: StylePolishRequest, context: StyleContext) -> list[str]:
    loaded = context.media_context.get("loaded") or {}
    notes = [
        "已按 style_polish 处理；润色类 alias 不拆成第二能力。",
        f"账号画像：{'已读取' if loaded.get('account_profile') else '未读取到'}；平台机制：{'已读取' if context.platform_mechanism else '未指定或未读取到'}。",
        "本次只做表达层处理，不新增事实、不写 CreativePattern。",
    ]
    if request.must_keep:
        notes.append(f"必须保留事实：{', '.join(request.must_keep)}")
    if request.avoid:
        notes.append(f"禁止表达：{', '.join(request.avoid)}")
    return notes


def _style_strategy(request: StylePolishRequest, context: StyleContext) -> str:
    platform = context.platform_mechanism.get("platform") or request.platform or "未指定平台"
    baseline = context.platform_mechanism.get("baseline_summary") or "未加载平台机制时只做事实保真的基础表达整理"
    return f"面向{platform}，读取既有账号上下文和平台机制；在不新增事实的前提下压缩表达、降低 AI 腔，并保留人工确认入口。平台依据：{baseline}"


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
    return {key: min(int(version.score_breakdown.get(key, 0)) for version in versions) for key in keys}


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


def _normalize_spacing(text: str) -> str:
    clean = re.sub(r"[ \t]+", " ", str(text or "")).strip()
    clean = re.sub(r"\n{3,}", "\n\n", clean)
    return clean


def _remove_anti_patterns(text: str, anti_patterns: tuple[str, ...], must_keep: tuple[str, ...]) -> str:
    result = text
    for phrase in anti_patterns:
        if phrase and phrase not in must_keep:
            result = result.replace(phrase, "")
    return _normalize_spacing(result)


def _short_line_breaks(text: str) -> str:
    parts = [part.strip() for part in re.split(r"([。！？!?；;])", text) if part.strip()]
    lines: list[str] = []
    buffer = ""
    for part in parts:
        if part in "。！？!?；;":
            lines.append((buffer + part).strip())
            buffer = ""
        else:
            buffer = (buffer + part).strip()
    if buffer:
        lines.append(buffer)
    return "\n".join(lines) if len(lines) > 1 else text


def _frontload_first_clause(text: str) -> str:
    clean = _normalize_spacing(text)
    match = re.search(r"[，,。！？!?；;]", clean)
    if not match:
        return clean
    head = clean[: match.start()].strip()
    tail = clean[match.end() :].strip()
    if not head or not tail:
        return clean
    return f"{head}\n{tail}"
