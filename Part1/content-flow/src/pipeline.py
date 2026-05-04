from __future__ import annotations

import time
from typing import Callable, Optional

from langgraph.graph import END, START, StateGraph

from .analyzer import analyze_transcript
from .config import Settings
from .downloader import clean_douyin_url, resolve_media
from .state import FlowState
from .storage import ensure_media_paths, load_json, load_text, save_json, save_text
from .transcriber import transcribe_audio
from .notion_writer import write_to_notion
from .utils import (
    detect_platform,
    extract_tags_from_comments,
    extract_tags_from_text,
    merge_tag_lists,
    normalize_tags,
    stringify_value,
)


ProgressFn = Callable[[str, int, str], None]


def _noop_progress(_: str, __: int, ___: str) -> None:
    return None


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
        transcript = transcribe_audio(
            audio_path,
            settings,
            progress=progress,
            progress_range=(45, 70),
        )
        if not transcript:
            print("转写失败。", flush=True)
            progress("transcriber", 60, "转写失败")
            return {}

        print("转写完成。", flush=True)
        print(f"转写耗时: {time.time() - start_time:.1f}s", flush=True)
        save_text(paths.transcript_path, transcript)
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
            ai_tags = normalize_tags(payload.get("tags"))
            ai_text = " ".join(
                [
                    stringify_value(payload.get("summary")),
                    stringify_value(payload.get("hooks")),
                    stringify_value(payload.get("emotion")),
                    stringify_value(payload.get("action_plan")),
                ]
            ).strip()
            ai_text_tags = extract_tags_from_text(ai_text, limit=6) if ai_text else []
            comment_tags = extract_tags_from_comments(state.get("top_comments") or [], limit=6)
            merged = merge_tag_lists(ai_tags, ai_text_tags, comment_tags, limit=8)
            if merged:
                payload["tags"] = merged

        paths = ensure_media_paths(state["url"])
        cached_analysis = load_json(paths.analysis_path)
        if cached_analysis:
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
            save_json(paths.analysis_path, analysis_payload)
            return {"analysis_result": analysis_payload, "is_success": True}

        start_time = time.time()
        progress("analyst", 70, "开始分析")
        print("开始分析视频与文案...", flush=True)
        analysis_result = analyze_transcript(
            state.get("transcript", ""),
            state["url"],
            state.get("video_path"),
            state.get("image_paths") or [],
            state.get("caption") or "",
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
        save_json(paths.analysis_path, analysis_result)
        progress("analyst", 90, "分析完成")
        return {"analysis_result": analysis_result, "is_success": True}

    return analyst_node


def make_notion_writer_node(settings: Settings, progress: ProgressFn):
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
