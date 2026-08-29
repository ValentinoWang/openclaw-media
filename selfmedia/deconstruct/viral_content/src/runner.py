from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

from .artifact_v2 import (
    merge_llm_result_with_evidence,
    validate_llm_deconstruction_v2_payload,
)
from .config import load_config
from .evidence.modality_dag import evidence_store_prompt, run_evidence_dag
from .llm_client import ensure_llm_provider_available, generate_json
from .media_parts import MediaEvidence, NoRealMediaError, _image_part, cleanup_temp_files, detect_media_type
from .multi_signal_contract import (
    MULTI_SIGNAL_CONTRACT_DEFERRED_STATUS,
    build_multi_signal_contract,
    multi_signal_contract_is_ready,
    multi_signal_contract_status,
)
from .multi_signal_schema import validate_multi_signal_contract_payload
from .prompt import DECONSTRUCT_PROMPT, PARTIAL_DECONSTRUCT_PROMPT, RECREATE_PROMPT
from selfmedia.request_constraints import parse_request_constraints, validate_request_constraints_payload
from .schemas import (
    DeconstructResult,
    PartialDeconstructResult,
    PRODUCTION_ROUTE_VALUES,
    RecreateResult,
    validate_evidence_asset_ids,
    validate_schema,
    validate_video_storyboard_granularity,
)
from .trigger import WorkflowMode, extract_url, require_executable_mode, route_mode
from common.resource_ownership import require_tenant_id
from common.platform_links import platform_for_url
from selfmedia.context import build_media_context

ROOT = Path(__file__).resolve().parents[1]
TITLE_TIMEZONE = "Asia/Shanghai"
TITLE_THEME_MAX_CHARS = 24
RECREATE_IMAGE_POST_KEYWORDS = ("图文", "图集", "图片笔记", "小红书笔记", "小红书图文", "长图")
RECREATE_VIDEO_KEYWORDS = ("视频", "短视频", "分镜", "镜头", "口播", "转场", "剪辑", "运镜", "拍摄")
STORYBOARD_IMAGE_REQUEST_KEYWORDS = ("生成示意图", "生成分镜图", "生成画面图", "带示意图", "带分镜图", "带画面图", "image2", "gpt-image-2", "gpt_image2")
STAGE_LOG_ENV = "OPENCLAW_DECONSTRUCT_STAGE_LOG"
STAGE_DIR_ENV = "OPENCLAW_DECONSTRUCT_STAGE_DIR"
MEDIA_RESOLVE_ATTEMPTS_ENV = "OPENCLAW_DECONSTRUCT_MEDIA_RESOLVE_ATTEMPTS"
MEDIA_RESOLVE_RETRY_SECONDS_ENV = "OPENCLAW_DECONSTRUCT_MEDIA_RESOLVE_RETRY_SECONDS"
ACCOUNT_CONTEXT_UNAVAILABLE_REASON = "账号画像未提供，不能评估"
ACCOUNT_PROFILE_PROMPT_FIELDS = (
    "identity_summary",
    "identity_tags",
    "education_background",
    "expertise_domains",
    "creator_role",
    "public_persona_boundaries",
    "story_usable_identity_points",
    "positioning_summary",
    "target_audience",
    "content_pillars",
    "proven_patterns",
    "avoid_patterns",
    "recent_lessons",
)
_ACCOUNT_FIELD_RE = re.compile(
    r"(?:^|\s)(?:账号|账号名称|博主)\s*[=:：]\s*(.+?)(?=\s+(?:账号|账号名称|博主|平台)\s*[=:：]|$)"
)
_PLATFORM_FIELD_RE = re.compile(r"(?:^|\s)平台\s*[=:：]\s*(.+?)(?=\s+(?:账号|账号名称|博主|平台)\s*[=:：]|$)")


def _stage_log(message: str) -> None:
    if os.getenv(STAGE_LOG_ENV, "").strip() not in {"1", "true", "TRUE", "yes", "on"}:
        return
    print(f"[deconstruct-stage] {datetime.now(ZoneInfo(TITLE_TIMEZONE)).isoformat()} {message}", file=sys.stderr, flush=True)


def _resolve_stage_dir(stage_dir: str | Path | None) -> Path | None:
    value = str(stage_dir or os.getenv(STAGE_DIR_ENV, "") or "").strip()
    if not value:
        return None
    return Path(value).expanduser()


def _write_stage_json(stage_dir: str | Path | None, name: str, payload: dict[str, Any]) -> Path | None:
    target_dir = _resolve_stage_dir(stage_dir)
    if target_dir is None:
        return None
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{name}.json"
    stage_payload = {
        "stage": name,
        "created_at": datetime.now(ZoneInfo(TITLE_TIMEZONE)).isoformat(),
        **payload,
    }
    target.write_text(json.dumps(stage_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _stage_log(f"stage_json:write path={target}")
    return target


def _content_ingest_path() -> Path:
    return load_config().part1_path


def _load_content_ingest_modules():
    from selfmedia.ingest.content_flow.src.config import load_settings  # type: ignore
    from selfmedia.ingest.content_flow.src.downloader import clean_douyin_url, resolve_media  # type: ignore

    return load_settings, clean_douyin_url, resolve_media


def _call_llm(
    parts: list[dict[str, Any]],
    schema: type[Any],
    post_validate: Any | None = None,
    *,
    profile_name: str = "media_analysis",
) -> dict[str, Any]:
    return generate_json(parts, load_config(profile_name), schema=schema, post_validate=post_validate)


def _evidence_parts_for_llm(evidence: Any) -> list[dict[str, Any]]:
    return evidence.parts


def _platform_from_url(url: str) -> str:
    return {"douyin": "抖音", "xiaohongshu": "小红书"}.get(platform_for_url(url), "未抓取")


def _existing_sibling_file(source_path: str, filename: str) -> str:
    if not source_path:
        return ""
    path = Path(source_path).resolve().parent / filename
    return str(path) if path.is_file() and path.stat().st_size > 0 else ""


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
            raise RuntimeError("创作交接结果缺少 video_storyboard，无法生成视频脚本")
        result["image_post_script"] = []
    elif media_type == "image_post":
        if not result.get("image_post_script"):
            raise RuntimeError("创作交接结果缺少 image_post_script，无法生成图文脚本")
        result["video_storyboard"] = []
    else:
        raise RuntimeError(f"不支持的创作交接类型：{media_type}")
    return result


def _should_generate_storyboard_images(text: str) -> bool:
    lowered = (text or "").lower()
    return any(keyword.lower() in lowered for keyword in STORYBOARD_IMAGE_REQUEST_KEYWORDS)


def _recreate_capability_audit() -> dict[str, Any]:
    return {
        "routes_allowed": list(PRODUCTION_ROUTE_VALUES),
        "storyboard_images_default": False,
        "storyboard_images_opt_in_keywords": list(STORYBOARD_IMAGE_REQUEST_KEYWORDS),
        "sample_gate_enabled": False,
        "production_capabilities": {
            "simple_routes": ["真实素材剪辑", "需要补拍", "图片生成", "动效字幕"],
            "programmatic_routes": ["Remotion", "FFmpeg"],
        },
    }


def _title_timestamp() -> str:
    return datetime.now(ZoneInfo(TITLE_TIMEZONE)).strftime("%Y%m%d%H%M%S")


def _expected_creation_time(text: str, default_value: str) -> str:
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
            return default_value
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
            return default_value
    return default_value


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
        or "创作交接"
    )


def deconstruct_doc_title(result: dict[str, Any], landing_time: str | None = None) -> str:
    suffix = f"｜{landing_time}" if landing_time else ""
    return f"爆款拆解文档｜{_deconstruct_theme(result)}{suffix}"


def recreate_doc_title(text: str, recreate_result: dict[str, Any], source: dict[str, Any], landing_time: str | None = None) -> str:
    source_id = _source_id(source)
    short_id = source_id[-4:] if source_id and source_id != "unknown" else "未名"
    suffix = f"｜{landing_time}" if landing_time else ""
    return f"创作交接｜{_recreate_theme(recreate_result, source)}｜{short_id}{suffix}"


def _prepare_deconstruct_inputs(text: str, *, max_frames: int = 8) -> dict[str, Any]:
    url = extract_url(text)
    if not url:
        raise ValueError("未找到链接")
    ensure_llm_provider_available(load_config())

    _stage_log("prepare:start load_content_ingest_modules")
    content_ingest_modules = _load_content_ingest_modules()
    if len(content_ingest_modules) == 2:
        load_settings, resolve_media = content_ingest_modules
        clean_douyin_url = lambda value: value
    else:
        load_settings, clean_douyin_url, resolve_media = content_ingest_modules
    settings = load_settings()
    attempts = max(1, min(5, int(os.getenv(MEDIA_RESOLVE_ATTEMPTS_ENV, "3") or "3")))
    retry_seconds = max(0.0, min(30.0, float(os.getenv(MEDIA_RESOLVE_RETRY_SECONDS_ENV, "1") or "1")))
    media = None
    cleaned_url = url
    last_error: NoRealMediaError | None = None
    for attempt in range(1, attempts + 1):
        cleaned_url = clean_douyin_url(url)
        _stage_log(f"prepare:resolve_media:start attempt={attempt}/{attempts} url={cleaned_url}")
        media = resolve_media(cleaned_url, settings)
        _stage_log(
            "prepare:resolve_media:done "
            f"attempt={attempt}/{attempts} "
            f"video={bool(getattr(media, 'video_path', None))} "
            f"images={len(getattr(media, 'image_paths', []) or [])} "
            f"media_type={getattr(media, 'media_type', '')}"
        )
        try:
            detected_media_type = detect_media_type(media.video_path, media.image_paths)
            break
        except NoRealMediaError as exc:
            last_error = exc
            if attempt >= attempts:
                raise
            delay = retry_seconds * attempt
            _stage_log(f"prepare:resolve_media:retry attempt={attempt}/{attempts} delay={delay:g}s reason={exc}")
            if delay:
                time.sleep(delay)
    else:  # pragma: no cover - the final failed attempt raises above
        raise last_error or NoRealMediaError("未下载到真实视频或图片，禁止仅根据链接拆解")

    assert media is not None
    source_path = media.video_path or (media.image_paths[0] if media.image_paths else "")
    work_dir = str(Path(source_path).resolve().parent)
    media_stats = getattr(media, "stats", {}) or {}
    request_constraints = parse_request_constraints(text, default_write_policy="partial_no_write").to_dict()
    transcript_path = _existing_sibling_file(source_path, "transcript.txt")
    ocr_path = _existing_sibling_file(source_path, "ocr.txt")
    caption_path = _existing_sibling_file(source_path, "caption.txt")
    _stage_log("prepare:evidence_dag:start")
    dag = run_evidence_dag(
        source_url=cleaned_url,
        platform_asset_id=str(media_stats.get("video_id") or media_stats.get("note_id") or ""),
        media=media,
        media_type=detected_media_type,
        source_path=source_path,
        work_dir=work_dir,
        media_stats=media_stats,
        caption_path=caption_path,
        transcript_path=transcript_path,
        ocr_path=ocr_path,
        artifact_root=Path(work_dir) / "evidence_dag",
        max_frames=max_frames,
        existing_audio_path=getattr(media, "audio_path", None),
        analysis_time_range=str(request_constraints.get("analysis_time_range") or ""),
    )
    evidence = dag["evidence"]
    asset_manifest = dag["asset_manifest"]
    modality_facts = dag["modality_facts"]
    evidence_store = dag["evidence_store"]
    _stage_log(
        "prepare:evidence_dag:done "
        f"facts={len(modality_facts)} "
        f"manifest={len(evidence_store.get('evidence_manifest') or {})} "
        f"root={(dag.get('evidence_dag_artifact_paths') or {}).get('root_dir', '')}"
    )
    _stage_log("prepare:done")
    return {
        "cleaned_url": cleaned_url,
        "media": media,
        "detected_media_type": detected_media_type,
        "source_path": source_path,
        "work_dir": work_dir,
        "evidence": evidence,
        "media_stats": media_stats,
        "asset_manifest": asset_manifest,
        "modality_facts": modality_facts,
        "evidence_store": evidence_store,
        "evidence_dag_artifact_paths": dag.get("evidence_dag_artifact_paths") or {},
        "valid_asset_ids": {item["asset_id"] for item in evidence.evidence_assets},
    }


def _prepared_stage_payload(text: str, prepared: dict[str, Any], *, max_frames: int) -> dict[str, Any]:
    media = prepared["media"]
    evidence = prepared["evidence"]
    return {
        "input_text": text,
        "max_frames": max_frames,
        "prepared": {
            "cleaned_url": prepared["cleaned_url"],
            "detected_media_type": prepared["detected_media_type"],
            "source_path": prepared["source_path"],
            "work_dir": prepared["work_dir"],
            "media": {
                "video_path": getattr(media, "video_path", "") or "",
                "image_paths": getattr(media, "image_paths", []) or [],
                "media_type": getattr(media, "media_type", "") or "",
                "caption": getattr(media, "caption", "") or "",
                "title": getattr(media, "title", "") or "",
                "published_at": getattr(media, "published_at", "") or "",
                "publish_time": getattr(media, "publish_time", "") or "",
                "stats": getattr(media, "stats", {}) or {},
            },
            "evidence": {
                "media_type": getattr(evidence, "media_type", prepared["detected_media_type"]),
                "evidence_paths": evidence.evidence_paths,
                "evidence_assets": evidence.evidence_assets,
                "audio_path": evidence.audio_path,
                "preview_path": evidence.preview_path,
            },
            "media_stats": prepared["media_stats"],
            "asset_manifest": prepared.get("asset_manifest") or {},
            "modality_facts": prepared.get("modality_facts") or {},
            "evidence_store": prepared.get("evidence_store") or {},
            "evidence_dag_artifact_paths": prepared.get("evidence_dag_artifact_paths") or {},
            "valid_asset_ids": sorted(prepared["valid_asset_ids"]),
        },
    }


def _prepared_from_stage_payload(payload: dict[str, Any]) -> dict[str, Any]:
    prepared_payload = payload.get("prepared")
    if not isinstance(prepared_payload, dict):
        raise ValueError("阶段 JSON 缺少 prepared，不能从准备阶段恢复")
    media_payload = prepared_payload.get("media") if isinstance(prepared_payload.get("media"), dict) else {}
    evidence_payload = prepared_payload.get("evidence") if isinstance(prepared_payload.get("evidence"), dict) else {}
    evidence_assets = [item for item in evidence_payload.get("evidence_assets") or [] if isinstance(item, dict)]
    parts: list[dict[str, Any]] = []
    for asset in evidence_assets:
        asset_id = str(asset.get("asset_id") or "").strip()
        phase = str(asset.get("phase") or "").strip()
        path = str(asset.get("path") or "").strip()
        parts.append({"text": f"视觉证据 asset_id={asset_id}；这是阶段缓存中的原媒体视觉证据，{phase}。输出时只能引用这个 asset_id。"})
        parts.append(_image_part(path))
    evidence = MediaEvidence(
        media_type=str(evidence_payload.get("media_type") or prepared_payload.get("detected_media_type") or ""),
        parts=parts,
        evidence_paths=[str(item) for item in evidence_payload.get("evidence_paths") or [] if str(item)],
        evidence_assets=evidence_assets,
        cleanup_paths=[],
        audio_path=str(evidence_payload.get("audio_path") or ""),
        preview_path=str(evidence_payload.get("preview_path") or ""),
    )
    return {
        "cleaned_url": str(prepared_payload.get("cleaned_url") or ""),
        "media": SimpleNamespace(**media_payload),
        "detected_media_type": str(prepared_payload.get("detected_media_type") or evidence.media_type),
        "source_path": str(prepared_payload.get("source_path") or ""),
        "work_dir": str(prepared_payload.get("work_dir") or ""),
        "evidence": evidence,
        "media_stats": prepared_payload.get("media_stats") if isinstance(prepared_payload.get("media_stats"), dict) else {},
        "asset_manifest": prepared_payload.get("asset_manifest") if isinstance(prepared_payload.get("asset_manifest"), dict) else {},
        "modality_facts": prepared_payload.get("modality_facts") if isinstance(prepared_payload.get("modality_facts"), dict) else {},
        "evidence_store": prepared_payload.get("evidence_store") if isinstance(prepared_payload.get("evidence_store"), dict) else {},
        "evidence_dag_artifact_paths": prepared_payload.get("evidence_dag_artifact_paths") if isinstance(prepared_payload.get("evidence_dag_artifact_paths"), dict) else {},
        "valid_asset_ids": set(str(item) for item in prepared_payload.get("valid_asset_ids") or [] if str(item)),
    }


def finalize_deconstruction(result: dict[str, Any], prepared: dict[str, Any], evidence: MediaEvidence, evidence_store: dict[str, Any]) -> dict[str, Any]:
    media = prepared["media"]
    media_stats = prepared["media_stats"]
    cleaned_url = prepared["cleaned_url"]
    detected_media_type = prepared["detected_media_type"]
    result.setdefault("source_url", cleaned_url)
    result.setdefault("media_type", detected_media_type)
    result.setdefault("part1_media_type", getattr(media, "media_type", "") or "未抓取")
    result.setdefault("platform", _platform_from_url(cleaned_url))
    result.setdefault("source_caption", getattr(media, "caption", "") or "")
    result.setdefault("source_title", getattr(media, "title", "") or "")
    result.setdefault("published_at", getattr(media, "published_at", "") or getattr(media, "publish_time", "") or "")
    result.setdefault("stats", media_stats)
    result.setdefault("interaction_screenshot_path", media_stats.get("interaction_screenshot_path"))
    result.setdefault("interaction_screenshot_status", media_stats.get("interaction_screenshot_status"))
    result.setdefault("interaction_status", media_stats.get("interaction_status"))
    result.setdefault("source_video_path", getattr(media, "video_path", ""))
    result.setdefault("source_audio_path", evidence.audio_path)
    result.setdefault("source_image_paths", getattr(media, "image_paths", []) or [])
    result.setdefault("source_preview_path", evidence.preview_path)
    result.setdefault("cover_path", evidence.preview_path)
    result.setdefault("evidence_assets", evidence.evidence_assets)
    result.setdefault("asset_manifest", prepared.get("asset_manifest") or {})
    result.setdefault("modality_facts", prepared.get("modality_facts") or {})
    result.setdefault("evidence_store", evidence_store)
    artifact_paths = prepared.get("evidence_dag_artifact_paths") if isinstance(prepared.get("evidence_dag_artifact_paths"), dict) else {}
    if artifact_paths:
        result.setdefault("evidence_dag_artifact_paths", artifact_paths)
        result.setdefault("evidence_store_uri", artifact_paths.get("evidence_store") or "")
    validation = dict(result.get("validation") or {})
    validation.setdefault("evidence_reference_status", "validated")
    if artifact_paths.get("evidence_store"):
        validation.setdefault("evidence_store_uri", artifact_paths.get("evidence_store"))
    result["validation"] = validation
    return result


def finalize_deconstruction_contract(
    result: dict[str, Any],
    *,
    stage_dir: str | Path | None = None,
    user_intent: str = "",
) -> dict[str, Any]:
    existing_contract = result.get("multi_signal_contract") if isinstance(result.get("multi_signal_contract"), dict) else {}
    if not existing_contract:
        _stage_log("multi_signal_contract:start")
        contract_source = dict(result)
        contract_source["_multi_signal_contract_request"] = "defer_until_creative_handoff"
        multi_signal_contract = build_multi_signal_contract(contract_source, user_intent=user_intent)
        _stage_log("multi_signal_contract:done")
        result["multi_signal_contract"] = multi_signal_contract
        validation = dict(result.get("validation") or {})
        validation["multi_signal_contract_status"] = (multi_signal_contract.get("validation") or {}).get(
            "multi_signal_contract_status",
            "validated",
        )
        result["validation"] = validation
    else:
        _stage_log("multi_signal_contract:skip existing")
    _write_stage_json(
        stage_dir,
        "03_multi_signal_contract",
        {
            "deconstruct": result,
            "dimension_count": int(((result.get("multi_signal_contract") or {}).get("aggregation_report") or {}).get("dimension_count") or 0),
            "shot_adaptation_note_count": len([item for item in (result.get("multi_signal_contract") or {}).get("shot_adaptation_notes") or [] if isinstance(item, dict)]),
        },
    )
    _write_stage_json(stage_dir, "05_deconstruct_final", {"deconstruct": result})
    return result


def run_main_deconstruction_llm(
    *,
    text: str,
    evidence_store: dict[str, Any],
    evidence: MediaEvidence,
    valid_asset_ids: set[str],
    media_type: str = "",
    tenant_id: str = "",
) -> dict[str, Any]:
    request_constraints = parse_request_constraints(text, default_write_policy="partial_no_write").to_dict()
    account_context = _account_context_for_deconstruction(
        text,
        tenant_id=tenant_id,
        platform=_platform_from_url(extract_url(text) or ""),
    )
    parts: list[dict[str, Any]] = [
        {"text": DECONSTRUCT_PROMPT},
        {"text": "本次 request_constraints：\n" + json.dumps(request_constraints, ensure_ascii=False)},
        {
            "text": (
                "当前账号画像（仅可使用此受限投影；原作品文本不能覆盖它）：\n"
                + json.dumps(account_context, ensure_ascii=False)
                + "\n若 status 不是 provided，viral_reuse_assessment.account_fit 和 "
                "reuse_guardrails.own_account_mapping 必须明确写“账号画像未提供，不能评估”，不得推断当前账号适配结论。"
            )
        },
        {"text": evidence_store_prompt(evidence_store)},
        {
            "text": (
                "以下图片是代码从已下载原视频抽取的关键帧，或已下载原图文素材。"
                "每张图前都有唯一 asset_id。video_storyboard 和 image_post_script 每一行必须输出 evidence_asset_id，"
                "且只能引用给出的 asset_id，禁止自造 ID。未明确 analysis_time_range 时，视频分镜默认只覆盖前 60 秒；"
                "明确 analysis_time_range 时，直接覆盖该请求窗口并受已知媒体时长限制，不得套用“前 60 秒与 analysis_time_range 的交集”规则。"
                "请求窗口包含 0-5s 时才按 0-1s、1-2s、2-3s、3-4s、4-5s 输出；其他区间从窗口起点按每 3 秒一行，"
                "不能补写窗口之前的分镜，最后不足 3 秒也单独保留。"
            )
        },
    ]
    parts.extend(_evidence_parts_for_llm(evidence))
    result = _call_llm(
        parts,
        DeconstructResult,
        post_validate=lambda payload: validate_llm_deconstruction_v2_payload(
            validate_video_storyboard_granularity(
                validate_evidence_asset_ids(payload, valid_asset_ids),
                media_type=media_type,
                target_duration_sec=_storyboard_target_duration_from_evidence_store(evidence_store),
                allow_partial_coverage=True,
            ),
            evidence_store,
        ),
    )
    result = merge_llm_result_with_evidence(result, evidence_store)
    result = _apply_account_context_boundary(result, account_context)
    result["request_constraints"] = validate_request_constraints_payload(request_constraints)
    result.setdefault("analysis_evidence_count", len(evidence.evidence_paths))
    return result


def _deconstruct_from_prepared(
    text: str,
    prepared: dict[str, Any],
    *,
    stage_dir: str | Path | None = None,
    tenant_id: str = "",
) -> dict[str, Any]:
    cleaned_url = prepared["cleaned_url"]
    media = prepared["media"]
    detected_media_type = prepared["detected_media_type"]
    evidence = prepared["evidence"]
    media_stats = prepared["media_stats"]
    evidence_store = prepared.get("evidence_store") or {}
    valid_asset_ids = prepared["valid_asset_ids"]
    if not evidence_store:
        request_constraints = parse_request_constraints(text, default_write_policy="partial_no_write").to_dict()
        dag = run_evidence_dag(
            source_url=cleaned_url,
            platform_asset_id=str(media_stats.get("video_id") or media_stats.get("note_id") or ""),
            media=media,
            media_type=detected_media_type,
            source_path=prepared.get("source_path") or "",
            work_dir=prepared.get("work_dir") or "",
            media_stats=media_stats,
            transcript_path=_existing_sibling_file(prepared.get("source_path") or "", "transcript.txt"),
            ocr_path=_existing_sibling_file(prepared.get("source_path") or "", "ocr.txt"),
            caption_path=_existing_sibling_file(prepared.get("source_path") or "", "caption.txt"),
            artifact_root=Path(prepared.get("work_dir") or "") / "evidence_dag",
            existing_audio_path=evidence.audio_path,
            analysis_time_range=str(request_constraints.get("analysis_time_range") or ""),
        )
        evidence = dag["evidence"]
        evidence_store = dag["evidence_store"]
        valid_asset_ids = {item["asset_id"] for item in evidence.evidence_assets}
        prepared["evidence"] = evidence
        prepared["asset_manifest"] = dag.get("asset_manifest") or {}
        prepared["modality_facts"] = dag.get("modality_facts") or {}
        prepared["evidence_store"] = evidence_store
        prepared["valid_asset_ids"] = valid_asset_ids
    try:
        _stage_log("deconstruct:llm:start")
        result = run_main_deconstruction_llm(
            text=text,
            evidence_store=evidence_store,
            evidence=evidence,
            valid_asset_ids=valid_asset_ids,
            media_type=detected_media_type,
            tenant_id=tenant_id,
        )
        _stage_log("deconstruct:llm:done")
    finally:
        cleanup_temp_files(evidence.cleanup_paths)
        _stage_log("deconstruct:cleanup:done")

    result = finalize_deconstruction(result, prepared, evidence, evidence_store)
    _write_stage_json(stage_dir, "02_deconstruct_core", {"deconstruct": result})
    return finalize_deconstruction_contract(result, stage_dir=stage_dir, user_intent=text)


def deconstruct(text: str, *, stage_dir: str | Path | None = None, tenant_id: str = "") -> dict[str, Any]:
    mode = require_executable_mode(text)
    if mode == WorkflowMode.ORGANIZE_ONLY:
        return {"skipped": True, "reason": "missing_trigger", "mode": mode.value}

    _stage_log("deconstruct:start")
    prepared = _prepare_deconstruct_inputs(text, max_frames=8)
    _write_stage_json(stage_dir, "01_prepared", _prepared_stage_payload(text, prepared, max_frames=8))
    return _deconstruct_from_prepared(text, prepared, stage_dir=stage_dir, tenant_id=tenant_id)


def resume_deconstruct_from_stage(
    stage_json_path: str | Path,
    *,
    stage_dir: str | Path | None = None,
    user_intent: str = "",
    tenant_id: str = "",
) -> dict[str, Any]:
    payload = json.loads(Path(stage_json_path).expanduser().read_text(encoding="utf-8"))
    stage = str(payload.get("stage") or "")
    if stage == "01_prepared":
        text = str(payload.get("input_text") or "")
        _stage_log(f"resume:from_stage stage={stage}")
        return _deconstruct_from_prepared(text, _prepared_from_stage_payload(payload), stage_dir=stage_dir, tenant_id=tenant_id)
    result = payload.get("deconstruct") if isinstance(payload.get("deconstruct"), dict) else payload.get("result")
    if not isinstance(result, dict):
        raise ValueError("阶段 JSON 缺少 deconstruct/result，不能恢复")
    _stage_log(f"resume:from_stage stage={stage or 'unknown'}")
    account_context = _account_context_for_deconstruction(
        user_intent,
        tenant_id=tenant_id,
        platform=str(result.get("platform") or ""),
    )
    return finalize_deconstruction_contract(
        _apply_account_context_boundary(result, account_context),
        stage_dir=stage_dir,
        user_intent=user_intent,
    )


def partial_deconstruct(text: str) -> dict[str, Any]:
    mode = require_executable_mode(text)
    if mode == WorkflowMode.ORGANIZE_ONLY:
        return {"skipped": True, "reason": "missing_trigger", "mode": mode.value}

    prepared = _prepare_deconstruct_inputs(text, max_frames=6)
    cleaned_url = prepared["cleaned_url"]
    media = prepared["media"]
    detected_media_type = prepared["detected_media_type"]
    evidence = prepared["evidence"]
    media_stats = prepared["media_stats"]
    evidence_store = prepared.get("evidence_store") or {}
    valid_asset_ids = prepared["valid_asset_ids"]
    request_constraints = parse_request_constraints(text, default_write_policy="partial_no_write").to_dict()

    parts: list[dict[str, Any]] = [
        {"text": PARTIAL_DECONSTRUCT_PROMPT},
        {"text": "本次 request_constraints：\n" + json.dumps(request_constraints, ensure_ascii=False)},
        {
            "text": (
                "轻量拆解仍必须基于 canonical evidence_store 事实层，不得读取非合同事实支路。\n"
                f"用户轻量反抄要求：{text[:1000]}\n"
                + evidence_store_prompt(evidence_store)
            )
        },
        {
            "text": (
                "以下图片是代码从已下载原视频抽取的关键帧，或已下载原图文素材。"
                "每张图前都有唯一 asset_id。visual_order 和 evidence_asset_ids 只能引用这些 ID。"
            )
        },
    ]

    def post_validate(payload: dict[str, Any]) -> dict[str, Any]:
        result = validate_schema(payload, PartialDeconstructResult)
        used_ids = {str(item.get("evidence_asset_id") or "").strip() for item in result.get("visual_order") or []}
        used_ids.update(str(item or "").strip() for item in result.get("evidence_asset_ids") or [])
        used_ids.discard("")
        invalid = sorted(used_ids - set(valid_asset_ids))
        if invalid:
            raise ValueError("partial_deconstruct evidence_asset_id 非法或缺失: " + ", ".join(invalid))
        if not used_ids:
            raise ValueError("partial_deconstruct 必须引用至少一个 evidence_asset_id")
        return result

    try:
        parts.extend(_evidence_parts_for_llm(evidence))
        result = _call_llm(parts, PartialDeconstructResult, post_validate=post_validate)
        result.setdefault("analysis_evidence_count", len(evidence.evidence_paths))
    finally:
        cleanup_temp_files(evidence.cleanup_paths)

    result.setdefault("mode", "partial_deconstruct")
    result["request_constraints"] = validate_request_constraints_payload(request_constraints)
    result.setdefault("source_url", cleaned_url)
    result.setdefault("media_type", detected_media_type)
    result.setdefault("part1_media_type", getattr(media, "media_type", "") or "未抓取")
    result.setdefault("platform", _platform_from_url(cleaned_url))
    result.setdefault("source_caption", getattr(media, "caption", "") or "")
    result.setdefault("source_title", getattr(media, "title", "") or "")
    result.setdefault("published_at", getattr(media, "published_at", "") or getattr(media, "publish_time", "") or "")
    result.setdefault("stats", media_stats)
    result.setdefault("source_audio_path", evidence.audio_path)
    result.setdefault("source_preview_path", evidence.preview_path)
    result.setdefault("cover_path", evidence.preview_path)
    result.setdefault("evidence_assets", evidence.evidence_assets)
    result.setdefault("asset_manifest", prepared.get("asset_manifest") or {})
    result.setdefault("modality_facts", prepared.get("modality_facts") or {})
    result.setdefault("evidence_store", evidence_store)
    result.setdefault("evidence_dag_artifact_paths", prepared.get("evidence_dag_artifact_paths") or {})
    return result


def extract_evidence_store(text: str) -> dict[str, Any]:
    prepared = _prepare_deconstruct_inputs(text, max_frames=8)
    try:
        return {
            "mode": "evidence_store",
            "source_url": prepared["cleaned_url"],
            "media_type": prepared["detected_media_type"],
            "asset_manifest": prepared.get("asset_manifest") or {},
            "modality_facts": prepared.get("modality_facts") or {},
            "evidence_store": prepared.get("evidence_store") or {},
        }
    finally:
        cleanup_temp_files(prepared["evidence"].cleanup_paths)


def recreate(
    text: str,
    source: dict[str, Any] | None = None,
    *,
    compatibility_handoff: bool = False,
) -> dict[str, Any]:
    source = source or {}
    multi_signal_contract = source.get("multi_signal_contract")
    if not source or not isinstance(multi_signal_contract, dict) or not multi_signal_contract:
        raise RuntimeError("创作交接必须基于拆解结果执行：缺少 multi_signal_contract 多维证据合同")
    if compatibility_handoff:
        return _creation_handoff_from_multi_signal_contract(text, source)
    ensure_llm_provider_available(load_config("media_creation"))
    media_type = _select_recreate_media_type(text, source)
    recreate_contract = {
        "multi_signal_contract": multi_signal_contract,
        "capability_audit": _recreate_capability_audit(),
    }
    parts = [
        {"text": RECREATE_PROMPT},
        {"text": "本次创作交接类型：" + media_type + "。只输出这一种脚本，另一种脚本必须为空数组。"},
        {"text": "用户输入/想法：\n" + text},
        {"text": "唯一 multi_signal_contract 多维证据合同（最终再创只消费这个合同）：\n" + json.dumps(recreate_contract, ensure_ascii=False, indent=2)},
    ]
    source_evidence_asset_ids = {
        str(item.get("asset_id") or "").strip()
        for item in (source.get("evidence_assets") or [])
        if isinstance(item, dict) and str(item.get("asset_id") or "").strip()
    }
    result = _call_llm(
        parts,
        RecreateResult,
        post_validate=lambda payload: validate_video_storyboard_granularity(
            validate_evidence_asset_ids(payload, source_evidence_asset_ids) if media_type == "video" and source_evidence_asset_ids else payload,
            media_type=media_type,
            target_duration_sec=_storyboard_target_duration_from_evidence_store(source.get("evidence_store") or {}),
        ),
        profile_name="media_creation",
    )
    result = _normalize_recreate_result(result, media_type)
    result["generate_storyboard_images"] = _should_generate_storyboard_images(text)
    if media_type == "video" and source.get("evidence_assets"):
        result.setdefault("evidence_assets", source.get("evidence_assets") or [])
    result.setdefault("user_input", text)
    result.setdefault("source_url", source.get("source_url", ""))
    return result


def _creation_handoff_from_multi_signal_contract(text: str, source: dict[str, Any]) -> dict[str, Any]:
    contract = source.get("multi_signal_contract") if isinstance(source.get("multi_signal_contract"), dict) else {}
    evidence_manifest = source.get("evidence_manifest") if isinstance(source.get("evidence_manifest"), dict) else {}
    evidence_ids = {str(key).strip() for key in evidence_manifest if str(key).strip()}
    if not evidence_ids:
        raise RuntimeError("创作交接缺少 evidence_manifest，拒绝使用非合同 compact 兜底")

    status = multi_signal_contract_status(contract)
    if status == MULTI_SIGNAL_CONTRACT_DEFERRED_STATUS:
        ensure_llm_provider_available(load_config())
        contract = build_multi_signal_contract(source, user_intent=text)
        status = multi_signal_contract_status(contract)
    try:
        validated = validate_multi_signal_contract_payload(contract, evidence_ids)
    except ValueError as exc:
        raise RuntimeError(f"创作交接 multi_signal_contract 校验失败：{exc}") from exc
    if not multi_signal_contract_is_ready(validated):
        raise RuntimeError(f"创作交接合同未就绪：{status or 'missing_status'}")
    return {
        "multi_signal_contract": {
            key: validated[key]
            for key in (
                "contract_version",
                "source_signal_dimensions",
                "shot_adaptation_notes",
                "conflict_notes",
                "open_questions",
                "validation",
            )
        }
    }


def _storyboard_target_duration_from_evidence_store(evidence_store: dict[str, Any]) -> float | None:
    try:
        pacing = ((evidence_store.get("modality_facts") or {}).get("pacing") or {}).get("facts") or {}
        python_facts = pacing.get("pacing_python_facts") or {}
        duration = float(python_facts.get("duration_sec") or 0.0)
    except (TypeError, ValueError, AttributeError):
        return None
    return duration or None


def _explicit_account_name(text: str) -> str:
    match = _ACCOUNT_FIELD_RE.search(text or "")
    return str(match.group(1) if match else "").strip()


def _explicit_platform_name(text: str) -> str:
    match = _PLATFORM_FIELD_RE.search(text or "")
    return str(match.group(1) if match else "").strip()


def _account_context_for_deconstruction(text: str, *, tenant_id: str, platform: str) -> dict[str, Any]:
    if not tenant_id:
        return {"status": "tenant_context_missing", "reason": ACCOUNT_CONTEXT_UNAVAILABLE_REASON}
    try:
        tenant_id = require_tenant_id(tenant_id)
    except Exception:
        return {"status": "invalid_tenant_context", "reason": ACCOUNT_CONTEXT_UNAVAILABLE_REASON}
    account = _explicit_account_name(text)
    platform = _explicit_platform_name(text) or platform
    if not account:
        return {"status": "account_not_provided", "reason": ACCOUNT_CONTEXT_UNAVAILABLE_REASON}
    try:
        context = build_media_context(platform=platform, account=account, tenant_id=tenant_id)
    except Exception:
        return {"status": "profile_unavailable", "reason": ACCOUNT_CONTEXT_UNAVAILABLE_REASON}
    profile = context.get("account_profile") if isinstance(context, dict) else {}
    if not isinstance(profile, dict):
        profile = {}
    projection = {
        key: profile[key]
        for key in ACCOUNT_PROFILE_PROMPT_FIELDS
        if profile.get(key) not in (None, "", [])
    }
    if not projection:
        return {
            "status": "profile_not_found",
            "reason": ACCOUNT_CONTEXT_UNAVAILABLE_REASON,
            "account": account,
            "platform": platform,
        }
    return {
        "status": "provided",
        "account": account,
        "platform": platform,
        "profile": projection,
    }


def _apply_account_context_boundary(result: dict[str, Any], account_context: dict[str, Any]) -> dict[str, Any]:
    result = dict(result)
    result["account_context"] = account_context
    validation = dict(result.get("validation") or {})
    validation["account_context_status"] = str(account_context.get("status") or "unknown")
    result["validation"] = validation
    if account_context.get("status") == "provided":
        return result
    assessment = dict(result.get("viral_reuse_assessment") or {})
    assessment["account_fit"] = {"level": "not_assessed", "reason": ACCOUNT_CONTEXT_UNAVAILABLE_REASON}
    result["viral_reuse_assessment"] = assessment
    guardrails = dict(result.get("reuse_guardrails") or {})
    guardrails["own_account_mapping"] = {
        "status": "not_provided",
        "reason": ACCOUNT_CONTEXT_UNAVAILABLE_REASON,
    }
    result["reuse_guardrails"] = guardrails
    return result


def run_workflow(
    text: str,
    *,
    tenant_id: str = "",
    write_feishu: bool = False,
    stage_dir: str | Path | None = None,
    resume_stage_json: str | Path | None = None,
) -> dict[str, Any]:
    mode = route_mode(text)
    if mode == WorkflowMode.ORGANIZE_ONLY:
        return {"skipped": True, "reason": "organize_only", "mode": mode.value}
    ensure_llm_provider_available(load_config())

    if resume_stage_json:
        resume_payload = json.loads(Path(resume_stage_json).expanduser().read_text(encoding="utf-8"))
        if str(resume_payload.get("stage") or "") == "06_recreate":
            raise ValueError("06_recreate 是已退役阶段；请重新执行【拆解】并显式交接【创作】或【创作-拍摄执行】")
        else:
            deconstruct_result = resume_deconstruct_from_stage(
                resume_stage_json,
                stage_dir=stage_dir,
                user_intent=text,
                tenant_id=tenant_id,
            )
    elif _resolve_stage_dir(stage_dir) is None:
        deconstruct_result = deconstruct(text, tenant_id=tenant_id)
    else:
        deconstruct_result = deconstruct(text, stage_dir=stage_dir, tenant_id=tenant_id)

    if not write_feishu:
        output = {"mode": mode.value, "deconstruct": deconstruct_result}
        _write_stage_json(stage_dir, "99_workflow_output", output)
        return output

    from .feishu_doc_writer import create_checked_doc, sync_deconstruct_parent_index
    from .feishu_writer import build_attachment_plan, write_deconstruction

    landing_time = _title_timestamp()
    deconstruct_title = deconstruct_doc_title(deconstruct_result, landing_time)
    deconstruct_result["deconstruct_doc_title"] = deconstruct_title
    deconstruct_doc = create_checked_doc(deconstruct_title, deconstruct_result, doc_kind="deconstruct")
    deconstruct_result["deconstruct_doc_id"] = deconstruct_doc.document_id
    deconstruct_result["deconstruct_doc_url"] = deconstruct_doc.url

    combined = dict(deconstruct_result)

    # Validate attachment existence and field mapping before the final write.
    build_attachment_plan(combined)
    record_id = write_deconstruction(combined, text, tenant_id=tenant_id)
    combined["feishu_record_id"] = record_id
    sync_deconstruct_parent_index({deconstruct_title: record_id})
    output = {"mode": mode.value, "deconstruct": deconstruct_result, "feishu_record_id": record_id}
    _write_stage_json(stage_dir, "99_workflow_output", output)
    return output
