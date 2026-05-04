from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from .config import load_config
from .llm_client import ensure_llm_provider_available, generate_json, generate_native_video_observation
from .media_parts import NoRealMediaError, cleanup_temp_files, detect_media_type, prepare_media_evidence
from .prompt import DECONSTRUCT_PROMPT, RECREATE_PROMPT
from .schemas import DeconstructResult, RecreateResult, validate_evidence_asset_ids
from .trigger import WorkflowMode, extract_url, require_executable_mode, route_mode

ROOT = Path(__file__).resolve().parents[1]


def _part1_path() -> Path:
    return load_config().part1_path


def _load_part1_modules():
    # This Part2 package is also named `src`, so import Part1 lazily only after
    # trigger validation and temporarily clear the current `src` package binding.
    current_src = {name: module for name, module in sys.modules.items() if name == "src" or name.startswith("src.")}
    for name in list(current_src):
        sys.modules.pop(name, None)
    sys.path.insert(0, str(_part1_path()))
    try:
        from src.config import load_settings  # type: ignore
        from src.downloader import resolve_media  # type: ignore

        return load_settings, resolve_media
    finally:
        try:
            sys.path.remove(str(_part1_path()))
        except ValueError:
            pass
        for name, module in current_src.items():
            sys.modules.setdefault(name, module)


def _call_llm(parts: list[dict[str, Any]], schema: type[Any], post_validate: Any | None = None) -> dict[str, Any]:
    return generate_json(parts, load_config(), schema=schema, post_validate=post_validate)


def _native_video_observation(video_path: str, caption: str, stats: dict[str, Any]) -> dict[str, Any]:
    return generate_native_video_observation(video_path, caption, stats, load_config())


def _maybe_observe_native_video(media: Any, media_type: str) -> dict[str, Any] | None:
    config = load_config()
    provider = config.video_understanding_provider
    if provider not in {"qwen_omni", "hybrid"}:
        return None
    if media_type != "video" or not getattr(media, "video_path", None):
        return None
    try:
        return _native_video_observation(
            str(media.video_path),
            getattr(media, "caption", "") or "",
            getattr(media, "stats", {}) or {},
        )
    except Exception as exc:
        if provider == "hybrid":
            return {"fallback_reason": str(exc), "uncertainty_notes": ["Qwen-Omni 原生视频观察失败，已回退到本地抽帧证据包。"]}
        raise


def _platform_from_url(url: str) -> str:
    lowered = url.lower()
    if "douyin" in lowered:
        return "抖音"
    if "xiaohongshu" in lowered or "xhs" in lowered:
        return "小红书"
    return "未抓取"


def deconstruct(text: str) -> dict[str, Any]:
    mode = require_executable_mode(text)
    if mode == WorkflowMode.ORGANIZE_ONLY:
        return {"skipped": True, "reason": "missing_trigger", "mode": mode.value}

    url = extract_url(text)
    if not url:
        raise ValueError("未找到链接")
    ensure_llm_provider_available(load_config())

    load_settings, resolve_media = _load_part1_modules()
    settings = load_settings()
    media = resolve_media(url, settings)

    detected_media_type = detect_media_type(media.video_path, media.image_paths)
    source_path = media.video_path or (media.image_paths[0] if media.image_paths else "")
    work_dir = str(Path(source_path).resolve().parent)
    evidence = prepare_media_evidence(
        media.video_path,
        media.image_paths,
        work_dir,
        max_frames=8,
        existing_audio_path=getattr(media, "audio_path", None),
    )
    native_observation = _maybe_observe_native_video(media, detected_media_type)
    parts: list[dict[str, Any]] = [
        {"text": DECONSTRUCT_PROMPT},
        {
            "text": (
                f"原链接：{url}\n"
                f"平台：{_platform_from_url(url)}\n"
                f"内容类型：{getattr(media, 'media_type', '') or detected_media_type}\n"
                f"原文案摘要：{(getattr(media, 'caption', '') or '未抓取')[:300]}\n"
                f"互动数据：{json.dumps(getattr(media, 'stats', {}) or {}, ensure_ascii=False)}"
            )
        },
        {
            "text": (
                "以下图片是代码从已下载原视频抽取的关键帧，或已下载原图文素材。"
                "每张图前都有唯一 asset_id。video_storyboard 和 image_post_script 每一行必须输出 evidence_asset_id，"
                "且只能引用给出的 asset_id，禁止自造 ID。"
            )
        },
    ]
    if native_observation:
        parts.append({"text": "Qwen-Omni 原生视频观察结果（只作为辅助观察，最终拆解仍必须引用 evidence_asset_id）：\n" + json.dumps(native_observation, ensure_ascii=False, indent=2)})
    parts.extend(evidence.parts)
    valid_asset_ids = {item["asset_id"] for item in evidence.evidence_assets}

    try:
        result = _call_llm(
            parts,
            DeconstructResult,
            post_validate=lambda payload: validate_evidence_asset_ids(payload, valid_asset_ids),
        )
        result.setdefault("analysis_evidence_count", len(evidence.evidence_paths))
    finally:
        cleanup_temp_files(evidence.cleanup_paths)

    result.setdefault("source_url", url)
    result.setdefault("media_type", detected_media_type)
    result.setdefault("part1_media_type", getattr(media, "media_type", "") or "未抓取")
    result.setdefault("platform", _platform_from_url(url))
    result.setdefault("source_caption", getattr(media, "caption", "") or "")
    result.setdefault("source_title", getattr(media, "title", "") or "")
    result.setdefault("published_at", getattr(media, "published_at", "") or getattr(media, "publish_time", "") or "")
    media_stats = getattr(media, "stats", {}) or {}
    result.setdefault("stats", media_stats)
    result.setdefault("interaction_screenshot_path", media_stats.get("interaction_screenshot_path"))
    result.setdefault("interaction_screenshot_status", media_stats.get("interaction_screenshot_status"))
    result.setdefault("interaction_status", media_stats.get("interaction_status"))
    result.setdefault("source_video_path", media.video_path)
    result.setdefault("source_audio_path", evidence.audio_path)
    result.setdefault("source_image_paths", media.image_paths)
    result.setdefault("source_preview_path", evidence.preview_path)
    result.setdefault("cover_path", evidence.preview_path)
    result.setdefault("evidence_assets", evidence.evidence_assets)
    if native_observation:
        result.setdefault("native_video_observation", native_observation)
    return result


def recreate(text: str, source: dict[str, Any] | None = None) -> dict[str, Any]:
    source = source or {}
    if not source or not source.get("video_storyboard"):
        raise RuntimeError("【再创作】必须基于【拆解】结果执行：缺少 video_storyboard 拆解脚本")
    ensure_llm_provider_available(load_config())
    parts = [
        {"text": RECREATE_PROMPT},
        {"text": "用户输入/想法：\n" + text},
        {"text": "已有拆解信息：\n" + json.dumps(source, ensure_ascii=False, indent=2)},
    ]
    result = _call_llm(parts, RecreateResult)
    result.setdefault("user_input", text)
    result.setdefault("source_url", source.get("source_url", ""))
    return result


def run_workflow(text: str, *, write_feishu: bool = False, bitable_url: str | None = None) -> dict[str, Any]:
    mode = route_mode(text)
    if mode == WorkflowMode.INVALID_RECREATE_ONLY:
        raise RuntimeError("只有【再创作】不允许执行：不下载、不分析、不建文档、不写多维表格。")
    if mode == WorkflowMode.ORGANIZE_ONLY:
        return {"skipped": True, "reason": "organize_only", "mode": mode.value}
    ensure_llm_provider_available(load_config())

    deconstruct_result = deconstruct(text)
    recreate_result: dict[str, Any] | None = None
    if mode == WorkflowMode.DECONSTRUCT_AND_RECREATE:
        recreate_result = recreate(text, deconstruct_result)

    if not write_feishu:
        output = {"mode": mode.value, "deconstruct": deconstruct_result}
        if recreate_result is not None:
            output["recreate"] = recreate_result
        return output

    from .feishu_doc_writer import create_checked_doc
    from .feishu_writer import build_attachment_plan, write_deconstruction

    deconstruct_doc = create_checked_doc("爆款拆解文档", deconstruct_result, doc_kind="deconstruct")
    deconstruct_result["deconstruct_doc_id"] = deconstruct_doc.document_id
    deconstruct_result["deconstruct_doc_url"] = deconstruct_doc.url

    combined = dict(deconstruct_result)
    if recreate_result is not None:
        recreate_doc = create_checked_doc(
            recreate_result.get("doc_title") or "再创作文档",
            recreate_result,
            doc_kind="recreate",
        )
        recreate_result["recreate_doc_id"] = recreate_doc.document_id
        recreate_result["recreate_doc_url"] = recreate_doc.url
        combined["recreate_doc_id"] = recreate_doc.document_id
        combined["recreate_doc_url"] = recreate_doc.url

    # Validate attachment existence and field mapping before the final write.
    build_attachment_plan(combined)
    record_id = write_deconstruction(combined, text, bitable_url)
    combined["feishu_record_id"] = record_id
    output = {"mode": mode.value, "deconstruct": deconstruct_result, "feishu_record_id": record_id}
    if recreate_result is not None:
        output["recreate"] = recreate_result
    return output
