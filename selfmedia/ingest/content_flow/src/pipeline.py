from __future__ import annotations

import hashlib
import os
import subprocess
import time
from typing import Callable, Optional

from .analyzer import analyze_transcript
from .config import Settings
from .downloader import clean_douyin_url, resolve_media
from .state import FlowState
from .storage import ensure_media_paths, load_json, load_text, save_json, save_text
from .semantic_persistence import analysis_user_field_contract_issue
from .transcriber import transcribe_audio_evidence
from .utils import (
    detect_platform,
    normalize_tags,
)


ProgressFn = Callable[[str, int, str], None]
PATTERN_TENANT_ID_ENV = "CONTENT_FLOW_PATTERN_TENANT_ID"


def _noop_progress(_: str, __: int, ___: str) -> None:
    return None


def _cached_analysis_needs_rerun(payload: dict) -> bool:
    return bool(analysis_user_field_contract_issue(payload))


def _sync_creative_pattern_from_analysis(state: FlowState, analysis: dict) -> dict:
    """Persist only a candidate pattern under an explicitly configured service tenant."""
    tenant_id = os.getenv(PATTERN_TENANT_ID_ENV, "").strip()
    if not tenant_id:
        return {
            "status": "skipped",
            "reason": "not_configured",
            "tenant_env": PATTERN_TENANT_ID_ENV,
        }
    try:
        from common.resource_ownership import require_tenant_id
        from integrations.feishu.media_writer import upsert_entity_record
        from media_model.payloads import build_pattern_payload, normalize_source_url
        from selfmedia.creation.retrieval import resolve_inspiration_bitable_url

        tenant_id = require_tenant_id(tenant_id)
    except Exception as exc:
        return {"status": "failed", "reason": "invalid_tenant_configuration", "detail": str(exc)}

    action_plan = str(analysis.get("action_plan") or "").strip()
    transferable_expression = str(analysis.get("transferable_expression") or "").strip()
    hooks = str(analysis.get("hooks") or "").strip()
    if not any((action_plan, transferable_expression, hooks)):
        return {"status": "skipped", "reason": "no_candidate_evidence"}

    table_url = resolve_inspiration_bitable_url()
    if not table_url:
        return {"status": "skipped", "reason": "inspiration_table_not_configured"}

    source_url = normalize_source_url(state.get("url") or "")
    if not source_url:
        return {"status": "failed", "reason": "missing_normalized_source_url"}
    fingerprint = hashlib.sha256(source_url.encode("utf-8")).hexdigest()[:24]
    platform = str(state.get("platform") or analysis.get("platform") or "").strip()
    category = "/".join(str(item).strip() for item in (analysis.get("secondary_category") or []) if str(item).strip())
    pattern_name = str(analysis.get("title") or "").strip() or f"{platform or '内容'}可迁移创作模式"
    payload = build_pattern_payload(
        pattern_id=f"pattern_ingest_{fingerprint}",
        pattern_name=pattern_name[:120],
        pattern_status="candidate_pattern",
        platform=platform,
        content_type=str(state.get("media_type") or "").strip(),
        applicable_persona=str(analysis.get("target_audience") or "").strip(),
        applicable_scenarios=" / ".join(item for item in (str(analysis.get("primary_category") or "").strip(), category) if item),
        opening_template=hooks,
        structure_template=action_plan,
        visual_template=str(analysis.get("visual_cues") or "").strip(),
        emotional_levers=str(analysis.get("emotion") or "").strip(),
        forbidden_scenarios=str(analysis.get("hidden_info") or "").strip(),
        historical_performance_summary=f"可迁移表达：{transferable_expression}" if transferable_expression else "",
    )
    try:
        write = upsert_entity_record(
            "CreativePattern",
            table_url,
            payload,
            session_tenant_id=tenant_id,
            key_field="pattern_id",
        )
    except Exception as exc:
        return {"status": "failed", "reason": "creative_pattern_upsert_failed", "detail": str(exc)}
    return {
        "status": "persisted",
        "pattern_id": payload["pattern_id"],
        "write_mode": str(write.get("mode") or ""),
        "record_id": str(write.get("record_id") or ""),
    }


def _clean_ocr_text(text: str) -> str:
    lines: list[str] = []
    previous = ""
    for raw_line in (text or "").replace("\f", "\n").splitlines():
        line = " ".join(raw_line.split())
        if not line or line == previous:
            continue
        previous = line
        lines.append(line)
    return "\n".join(lines).strip()


def _extract_image_ocr(image_paths: list[str], ocr_path: str, progress: ProgressFn) -> str:
    cached = load_text(ocr_path)
    if cached:
        return cached
    if not image_paths:
        return ""
    sections: list[str] = []
    for idx, image_path in enumerate(sorted(image_paths), start=1):
        if not image_path or not os.path.isfile(image_path):
            continue
        progress("ocr", min(69, 55 + idx), f"图片 OCR {idx}/{len(image_paths)}")
        try:
            proc = subprocess.run(
                ["tesseract", image_path, "stdout", "-l", "chi_sim+eng", "--psm", "6"],
                text=True,
                capture_output=True,
                timeout=45,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            print(f"图片 OCR 失败 {image_path}: {exc}", flush=True)
            continue
        text = _clean_ocr_text(proc.stdout)
        if text:
            sections.append(f"## {idx:02d} {os.path.basename(image_path)}\n{text}")
    ocr_text = "\n\n".join(sections).strip()
    if ocr_text:
        save_text(ocr_path, ocr_text)
    return ocr_text


def make_downloader_node(settings: Settings, progress: ProgressFn):
    def downloader_node(state: FlowState) -> dict:
        if not state["is_success"]:
            return {}

        progress("downloader", 5, "准备下载")
        cleaned_url = clean_douyin_url(state["url"])
        start_time = time.time()
        print("开始下载视频...", flush=True)
        media = resolve_media(cleaned_url, settings, progress=progress)
        video_path = media.video_path
        audio_path = media.audio_path
        image_paths = media.image_paths
        media_type = media.media_type
        caption = media.caption
        stats = media.stats or {}
        cover_url = stats.get("cover_url")
        platform = detect_platform(cleaned_url)
        if video_path:
            print(f"视频已保存: {video_path}", flush=True)
        if audio_path:
            print(f"音频已保存: {audio_path}", flush=True)
        if image_paths:
            print(f"图片已保存: {image_paths[0]}", flush=True)
        if not (video_path or image_paths or caption):
            print("下载失败。", flush=True)
            progress("downloader", 20, "下载失败")
        print(f"下载耗时: {time.time() - start_time:.1f}s", flush=True)
        if video_path:
            progress("downloader", 45, "下载完成")
        elif image_paths:
            progress("downloader", 45, "图文下载完成")
        return {
            "url": cleaned_url,
            "video_path": video_path,
            "audio_path": audio_path,
            "image_paths": image_paths,
            "media_type": media_type,
            "caption": caption,
            "platform": platform,
            "like_count": stats.get("like_count"),
            "collect_count": stats.get("collect_count"),
            "comment_count": stats.get("comment_count"),
            "share_count": stats.get("share_count"),
            "top_comments": stats.get("top_comments") or [],
            "video_id": stats.get("video_id"),
            "cover_url": cover_url,
            "stats_sources": stats.get("stats_sources"),
            "interaction_status": stats.get("interaction_status"),
            "stats_notice": stats.get("stats_notice"),
            "missing_interaction_fields": stats.get("missing_interaction_fields"),
            "interaction_screenshot_path": stats.get("interaction_screenshot_path"),
            "interaction_screenshot_status": stats.get("interaction_screenshot_status"),
            "interaction_screenshot_error": stats.get("interaction_screenshot_error"),
            "is_success": bool(video_path or image_paths or caption),
        }

    return downloader_node


def make_transcriber_node(settings: Settings, progress: ProgressFn):
    def transcriber_node(state: FlowState) -> dict:
        if not state["is_success"]:
            return {}

        media_type = state.get("media_type")
        if media_type and media_type != "video":
            print("当前为图文/动图，跳过转写。", flush=True)
            progress("transcriber", 55, "非视频，跳过转写")
            return {}

        audio_path = state.get("audio_path")
        if not audio_path:
            print("未找到音频文件，跳过转写。", flush=True)
            progress("transcriber", 55, "未找到音频，跳过转写")
            return {}

        paths = ensure_media_paths(state["url"])
        cached_transcript = load_text(paths.transcript_path)
        if cached_transcript:
            print("检测到已存在逐字稿，跳过转写。", flush=True)
            progress("transcriber", 70, "已存在逐字稿")
            return {"transcript": cached_transcript}

        start_time = time.time()
        progress("transcriber", 45, "开始转写")
        print("开始转写音频...", flush=True)
        evidence = transcribe_audio_evidence(
            audio_path,
            settings,
            progress=progress,
            progress_range=(45, 70),
        )
        transcript = str((evidence or {}).get("transcript") or "").strip()
        segments = (evidence or {}).get("segments") or []
        if not transcript:
            print("转写失败。", flush=True)
            progress("transcriber", 60, "转写失败")
            return {}

        print("转写完成。", flush=True)
        print(f"转写耗时: {time.time() - start_time:.1f}s", flush=True)
        save_text(paths.transcript_path, transcript)
        if segments:
            save_json(
                paths.speech_segments_path,
                {
                    "schema_version": "speech_segments_v1",
                    "provider": (evidence or {}).get("provider", ""),
                    "segments": segments,
                },
            )
        progress("transcriber", 70, "转写完成")
        return {"transcript": transcript}

    return transcriber_node


def make_analyst_node(settings: Settings, progress: ProgressFn):
    def analyst_node(state: FlowState) -> dict:
        if not state["is_success"]:
            return {}
        if not (
            state.get("video_path")
            or state.get("image_paths")
            or state.get("caption")
            or state.get("transcript")
        ):
            progress("analyst", 80, "缺少可分析内容")
            return {"is_success": False}

        def enrich_tags(payload: dict) -> None:
            payload["tags"] = normalize_tags(payload.get("tags"))

        paths = ensure_media_paths(state["url"])
        image_ocr = _extract_image_ocr(state.get("image_paths") or [], paths.ocr_path, progress)
        cached_analysis = load_json(paths.analysis_path)
        if cached_analysis and not _cached_analysis_needs_rerun(cached_analysis):
            print("检测到已存在分析结果，跳过分析。", flush=True)
            progress("analyst", 90, "已存在分析结果")
            analysis_payload = cached_analysis
            stats_payload = {
                "platform": state.get("platform"),
                "like_count": state.get("like_count"),
                "collect_count": state.get("collect_count"),
                "comment_count": state.get("comment_count"),
                "share_count": state.get("share_count"),
                "top_comments": state.get("top_comments"),
                "video_id": state.get("video_id"),
                "caption": state.get("caption"),
                "image_ocr": image_ocr,
                "media_type": state.get("media_type"),
                "cover_url": state.get("cover_url"),
                "stats_sources": state.get("stats_sources"),
                "interaction_status": state.get("interaction_status"),
                "stats_notice": state.get("stats_notice"),
                "missing_interaction_fields": state.get("missing_interaction_fields"),
                "interaction_screenshot_path": state.get("interaction_screenshot_path"),
                "interaction_screenshot_status": state.get("interaction_screenshot_status"),
                "interaction_screenshot_error": state.get("interaction_screenshot_error"),
            }
            for key, value in stats_payload.items():
                if value is None:
                    continue
                current_value = analysis_payload.get(key)
                if current_value is None:
                    analysis_payload[key] = value
                    continue
                if isinstance(current_value, list) and not current_value:
                    analysis_payload[key] = value
            enrich_tags(analysis_payload)
            analysis_payload["creative_pattern_sync"] = _sync_creative_pattern_from_analysis(state, analysis_payload)
            save_json(paths.analysis_path, analysis_payload)
            return {"analysis_result": analysis_payload, "image_ocr": image_ocr, "is_success": True}
        if cached_analysis:
            print("检测到待重跑的基础分析结果，重新分析。", flush=True)

        start_time = time.time()
        progress("analyst", 70, "开始分析")
        print("开始分析视频与文案...", flush=True)
        analysis_result = analyze_transcript(
            state.get("transcript", ""),
            state["url"],
            state.get("video_path"),
            state.get("image_paths") or [],
            state.get("caption") or "",
            image_ocr,
            state.get("media_type"),
            settings,
            progress=progress,
            progress_range=(70, 90),
        )
        if not analysis_result:
            print("分析失败。", flush=True)
            progress("analyst", 80, "分析失败")
            return {"is_success": False}

        print("分析完成。", flush=True)
        print(f"分析耗时: {time.time() - start_time:.1f}s", flush=True)
        stats_payload = {
            "platform": state.get("platform"),
            "like_count": state.get("like_count"),
            "collect_count": state.get("collect_count"),
            "comment_count": state.get("comment_count"),
            "share_count": state.get("share_count"),
            "top_comments": state.get("top_comments"),
            "video_id": state.get("video_id"),
            "caption": state.get("caption"),
            "image_ocr": image_ocr,
            "media_type": state.get("media_type"),
            "cover_url": state.get("cover_url"),
            "stats_sources": state.get("stats_sources"),
            "interaction_status": state.get("interaction_status"),
            "stats_notice": state.get("stats_notice"),
            "missing_interaction_fields": state.get("missing_interaction_fields"),
            "interaction_screenshot_path": state.get("interaction_screenshot_path"),
            "interaction_screenshot_status": state.get("interaction_screenshot_status"),
            "interaction_screenshot_error": state.get("interaction_screenshot_error"),
        }
        for key, value in stats_payload.items():
            if value is not None:
                analysis_result[key] = value
        enrich_tags(analysis_result)
        analysis_result["creative_pattern_sync"] = _sync_creative_pattern_from_analysis(state, analysis_result)
        save_json(paths.analysis_path, analysis_result)
        progress("analyst", 90, "分析完成")
        return {"analysis_result": analysis_result, "image_ocr": image_ocr, "is_success": True}

    return analyst_node


def make_notion_writer_node(settings: Settings, progress: ProgressFn):
    from .notion_writer import write_to_notion

    def notion_writer_node(state: FlowState) -> dict:
        if not state["is_success"]:
            return {}

        progress("notion_writer", 90, "写入 Notion")
        page_id = write_to_notion(
            state.get("url", ""),
            state.get("transcript", ""),
            state.get("caption") or "",
            state.get("analysis_result", {}),
            settings,
        )
        if not page_id:
            progress("notion_writer", 95, "写入失败")
            return {"is_success": False}
        print(f"Notion 已写入: {page_id}", flush=True)
        progress("notion_writer", 100, "写入完成")
        return {"notion_page_id": page_id, "is_success": True}

    return notion_writer_node


def build_graph(
    settings: Settings,
    progress: Optional[ProgressFn] = None,
    include_notion: bool = True,
):
    from langgraph.graph import END, START, StateGraph

    progress = progress or _noop_progress
    graph = StateGraph(FlowState)
    graph.add_node("downloader", make_downloader_node(settings, progress))
    graph.add_node("transcriber", make_transcriber_node(settings, progress))
    graph.add_node("analyst", make_analyst_node(settings, progress))
    graph.add_edge(START, "downloader")
    graph.add_edge("downloader", "transcriber")
    graph.add_edge("transcriber", "analyst")
    if include_notion:
        graph.add_node("notion_writer", make_notion_writer_node(settings, progress))
        graph.add_edge("analyst", "notion_writer")
        graph.add_edge("notion_writer", END)
    else:
        graph.add_edge("analyst", END)
    return graph.compile()
