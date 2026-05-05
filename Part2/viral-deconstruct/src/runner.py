from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .config import load_config
from .llm_client import ensure_llm_provider_available, generate_json, generate_native_video_observation
from .media_parts import NoRealMediaError, cleanup_temp_files, detect_media_type, prepare_media_evidence
from .prompt import DECONSTRUCT_PROMPT, RECREATE_PROMPT
from .schemas import DeconstructResult, RecreateResult, validate_evidence_asset_ids
from .trigger import WorkflowMode, extract_url, require_executable_mode, route_mode

ROOT = Path(__file__).resolve().parents[1]
TITLE_TIMEZONE = "Asia/Shanghai"
TITLE_THEME_MAX_CHARS = 24
RECREATE_IMAGE_POST_KEYWORDS = ("图文", "图集", "图片笔记", "小红书笔记", "小红书图文", "长图")
RECREATE_VIDEO_KEYWORDS = ("视频", "短视频", "分镜", "镜头", "口播", "转场", "剪辑", "运镜", "拍摄")
STORYBOARD_IMAGE_REQUEST_KEYWORDS = ("生成示意图", "生成分镜图", "生成画面图", "带示意图", "带分镜图", "带画面图", "image2", "gpt-image-2", "gpt_image2")


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
        from src.downloader import clean_douyin_url, resolve_media  # type: ignore

        return load_settings, clean_douyin_url, resolve_media
    finally:
        try:
            sys.path.remove(str(_part1_path()))
        except ValueError:
            pass
        # Restore Part2's `src` modules explicitly. Part1 imports populate
        # sys.modules['src']; using setdefault would leave that binding in place
        # and later relative imports like .feishu_doc_writer may resolve against
        # Part1, causing `No module named src.feishu_doc_writer`.
        for name in [name for name in list(sys.modules) if name == "src" or name.startswith("src.")]:
            sys.modules.pop(name, None)
        for name, module in current_src.items():
            sys.modules[name] = module


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


def _source_media_type(source: dict[str, Any]) -> str:
    raw = str(source.get("media_type") or source.get("part1_media_type") or "").strip().lower()
    if raw in {"video", "image_post"}:
        return raw
    if source.get("source_video_path"):
        return "video"
    image_paths = source.get("source_image_paths")
    if isinstance(image_paths, list) and image_paths:
        return "image_post"
    return "video"


def _select_recreate_media_type(text: str, source: dict[str, Any]) -> str:
    source_media_type = _source_media_type(source)
    user_text = text or ""
    wants_image_post = any(keyword in user_text for keyword in RECREATE_IMAGE_POST_KEYWORDS)
    wants_video = any(keyword in user_text for keyword in RECREATE_VIDEO_KEYWORDS)
    if wants_image_post and not wants_video:
        return "image_post"
    if wants_video and not wants_image_post:
        return "video"
    return source_media_type


def _normalize_recreate_result(result: dict[str, Any], media_type: str) -> dict[str, Any]:
    result["media_type"] = media_type
    if media_type == "video":
        if not result.get("video_storyboard"):
            raise RuntimeError("再创作结果缺少 video_storyboard，无法生成视频脚本")
        result["image_post_script"] = []
    elif media_type == "image_post":
        if not result.get("image_post_script"):
            raise RuntimeError("再创作结果缺少 image_post_script，无法生成图文脚本")
        result["video_storyboard"] = []
    else:
        raise RuntimeError(f"不支持的再创作交付类型：{media_type}")
    return result


def _should_generate_storyboard_images(text: str) -> bool:
    lowered = (text or "").lower()
    return any(keyword.lower() in lowered for keyword in STORYBOARD_IMAGE_REQUEST_KEYWORDS)


def _title_timestamp() -> str:
    return datetime.now(ZoneInfo(TITLE_TIMEZONE)).strftime("%Y%m%d%H%M")


def _expected_creation_time(text: str, fallback: str) -> str:
    text = text or ""
    match = re.search(r"(?P<year>20\d{2})[-/.年](?P<month>\d{1,2})[-/.月](?P<day>\d{1,2})日?(?:\s*(?P<hour>\d{1,2})[:点时](?P<minute>\d{1,2})?)?", text)
    if match:
        year = int(match.group("year"))
        month = int(match.group("month"))
        day = int(match.group("day"))
        hour = int(match.group("hour") or 0)
        minute = int(match.group("minute") or 0)
        try:
            return datetime(year, month, day, hour, minute).strftime("%Y%m%d%H%M")
        except ValueError:
            return fallback
    match = re.search(r"(?P<month>\d{1,2})月(?P<day>\d{1,2})日(?:\s*(?P<hour>\d{1,2})[:点时](?P<minute>\d{1,2})?)?", text)
    if match:
        now = datetime.now(ZoneInfo(TITLE_TIMEZONE))
        month = int(match.group("month"))
        day = int(match.group("day"))
        hour = int(match.group("hour") or 0)
        minute = int(match.group("minute") or 0)
        try:
            return datetime(now.year, month, day, hour, minute).strftime("%Y%m%d%H%M")
        except ValueError:
            return fallback
    return fallback


def _source_id(result: dict[str, Any]) -> str:
    stats = result.get("stats") if isinstance(result.get("stats"), dict) else {}
    for value in (
        stats.get("video_id"),
        stats.get("aweme_id"),
        result.get("source_id"),
        result.get("aweme_id"),
    ):
        if value:
            return _clean_title_part(str(value), max_chars=32)
    url = str(result.get("source_url") or "")
    match = re.search(r"/([A-Za-z0-9_-]{6,})(?:/)?$", url.rstrip("/"))
    if match:
        return _clean_title_part(match.group(1), max_chars=32)
    return "unknown"


def _clean_title_part(value: Any, max_chars: int = TITLE_THEME_MAX_CHARS) -> str:
    text = str(value or "").strip()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[\\/:*?\"<>|\r\n]+", " ", text).strip(" ｜")
    return (text[:max_chars].strip() or "未命名")


def _deconstruct_theme(result: dict[str, Any]) -> str:
    caption = str(result.get("source_caption") or "")
    caption = re.sub(r"https?://\S+", "", caption)
    caption = re.sub(r"#\S+", "", caption).strip()
    return _clean_title_part(result.get("content_summary") or result.get("source_summary") or result.get("source_title") or caption or "爆款拆解")


def _recreate_theme(recreate_result: dict[str, Any], source: dict[str, Any]) -> str:
    return _clean_title_part(
        source.get("content_summary")
        or recreate_result.get("doc_title")
        or recreate_result.get("creative_positioning")
        or source.get("source_summary")
        or "再创作"
    )


def deconstruct_doc_title(result: dict[str, Any], landing_time: str | None = None) -> str:
    return f"{landing_time or _title_timestamp()}｜{_deconstruct_theme(result)}｜{_source_id(result)}"


def recreate_doc_title(text: str, recreate_result: dict[str, Any], source: dict[str, Any], landing_time: str | None = None) -> str:
    base_time = landing_time or _title_timestamp()
    expected_time = _expected_creation_time(text, base_time)
    return f"{expected_time}｜{_recreate_theme(recreate_result, source)}｜由{_source_id(source)}二创"


def deconstruct(text: str) -> dict[str, Any]:
    mode = require_executable_mode(text)
    if mode == WorkflowMode.ORGANIZE_ONLY:
        return {"skipped": True, "reason": "missing_trigger", "mode": mode.value}

    url = extract_url(text)
    if not url:
        raise ValueError("未找到链接")
    ensure_llm_provider_available(load_config())

    part1_modules = _load_part1_modules()
    if len(part1_modules) == 2:
        load_settings, resolve_media = part1_modules
        clean_douyin_url = lambda value: value
    else:
        load_settings, clean_douyin_url, resolve_media = part1_modules
    settings = load_settings()
    cleaned_url = clean_douyin_url(url)
    media = resolve_media(cleaned_url, settings)

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
                f"原链接：{cleaned_url}\n"
                f"平台：{_platform_from_url(cleaned_url)}\n"
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

    result.setdefault("source_url", cleaned_url)
    result.setdefault("media_type", detected_media_type)
    result.setdefault("part1_media_type", getattr(media, "media_type", "") or "未抓取")
    result.setdefault("platform", _platform_from_url(cleaned_url))
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
    media_type = _select_recreate_media_type(text, source)
    parts = [
        {"text": RECREATE_PROMPT},
        {"text": "本次再创作交付类型：" + media_type + "。只输出这一种脚本，另一种脚本必须为空数组。"},
        {"text": "用户输入/想法：\n" + text},
        {"text": "已有拆解信息：\n" + json.dumps(source, ensure_ascii=False, indent=2)},
    ]
    result = _call_llm(parts, RecreateResult)
    result = _normalize_recreate_result(result, media_type)
    result["generate_storyboard_images"] = _should_generate_storyboard_images(text)
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

    landing_time = _title_timestamp()
    deconstruct_title = deconstruct_doc_title(deconstruct_result, landing_time)
    deconstruct_result["deconstruct_doc_title"] = deconstruct_title
    deconstruct_doc = create_checked_doc(deconstruct_title, deconstruct_result, doc_kind="deconstruct")
    deconstruct_result["deconstruct_doc_id"] = deconstruct_doc.document_id
    deconstruct_result["deconstruct_doc_url"] = deconstruct_doc.url

    combined = dict(deconstruct_result)
    if recreate_result is not None:
        recreate_title = recreate_doc_title(text, recreate_result, deconstruct_result, landing_time)
        recreate_result["recreate_doc_title"] = recreate_title
        recreate_doc = create_checked_doc(
            recreate_title,
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
