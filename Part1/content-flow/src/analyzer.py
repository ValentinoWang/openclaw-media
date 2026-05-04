from __future__ import annotations

import base64
import os
import threading
import time
from typing import Callable, Optional

import requests

from .config import Settings
from .utils import extract_gemini_text, guess_mime_type, parse_json_payload


ANALYST_SYSTEM_PROMPT = """
你是一位拥有千万粉丝的抖音/小红书短视频内容操盘手。你擅长拆解爆款逻辑，并将其转化为可执行的拍摄脚本。

请根据用户提供的【视频文案/逐字稿】，输出一份结构化的分析报告。

请严格遵守以下输出要求：
1. 必须以 JSON 格式输出。
2. JSON 的 Key 必须包含：summary, hooks, emotion, score, tags, action_plan。
3. 所有文本内容的分析必须犀利、直击痛点，拒绝正确的废话。

以下是各字段的具体定义：

summary (黄金总结):
1. 用 3 点概括这条视频的核心价值（用户看了能得到什么）。
2. 语言要极度精炼。

hooks (黄金三秒):
1. 分析前 5 秒文案或画面是如何留住用户的。
2. 提取出它的“抓手”类型（例如：痛点反问、巨大的反差、利益承诺等）。

emotion (情绪价值):
1. 这是一个单选或双选：焦虑 / 爽感 / 好奇 / 共鸣 / 愤怒 / 治愈。
2. 简述它是如何调动这种情绪的。

score (翻拍推荐指数):
1. 给出 0-100 的打分。
2. 逻辑：低成本+高流量=高分；高成本+低流量=低分。

tags (标签):
1. 给出 3-5 个搜索标签。

action_plan (二创实操SOP):
这是一个极其重要的字段，请必须按照 "1. 2. 3." 的格式分点作答，内容必须包含以下三个维度：
1. 【万能结构公式】：将原视频拆解为“开头+中间+结尾”的填空题模板。（例如：开头用xx提问 + 中间展示3个xx + 结尾升华到xx）。
2. 【差异化切入点】：如果我来拍，如何换个角度蹭这个热点？（例如：原视频讲职场，建议你改到考研赛道；原视频是口播，建议你改为Vlog形式）。
3. 【低成本拍摄方案】：给出具体的画面建议（例如：不需要外景，只需要在这个位置，打一盏灯，对镜头展示xx物品）。
"""


def upload_media_file(file_path: str, mime_type: str, file_size: int, settings: Settings) -> Optional[str]:
    try:
        init_response = requests.post(
            f"{settings.gemini_base_url}upload/v1beta/files",
            headers={
                "X-Goog-Upload-Protocol": "resumable",
                "X-Goog-Upload-Command": "start",
                "X-Goog-Upload-Header-Content-Length": str(file_size),
                "X-Goog-Upload-Header-Content-Type": mime_type,
                "Content-Type": "application/json",
                "X-goog-api-key": settings.gemini_api_key,
            },
            json={"file": {"display_name": os.path.basename(file_path)}},
            timeout=settings.gemini_timeout,
        )
        init_response.raise_for_status()
    except requests.RequestException:
        return None

    upload_url = init_response.headers.get("X-Goog-Upload-URL") or init_response.headers.get(
        "x-goog-upload-url"
    )
    if not upload_url:
        return None

    try:
        with open(file_path, "rb") as handle:
            upload_response = requests.post(
                upload_url,
                headers={
                    "Content-Length": str(file_size),
                    "X-Goog-Upload-Offset": "0",
                    "X-Goog-Upload-Command": "upload, finalize",
                },
                data=handle,
                timeout=max(settings.gemini_timeout, 120),
            )
            upload_response.raise_for_status()
    except requests.RequestException:
        return None

    file_info = upload_response.json()
    if isinstance(file_info, dict) and "file" in file_info:
        file_info = file_info["file"]

    if not isinstance(file_info, dict):
        return None

    file_uri = file_info.get("uri")
    if file_uri:
        return file_uri
    if file_info.get("name"):
        return f"{settings.gemini_base_url}v1beta/{file_info['name']}"
    return None


def build_media_part(file_path: str, settings: Settings) -> Optional[dict]:
    if not file_path or not os.path.exists(file_path):
        return None

    file_size = os.path.getsize(file_path)
    mime_type = guess_mime_type(file_path)

    if file_size <= settings.max_inline_size:
        with open(file_path, "rb") as handle:
            data = base64.b64encode(handle.read()).decode("ascii")
        return {"inline_data": {"mime_type": mime_type, "data": data}}

    file_uri = upload_media_file(file_path, mime_type, file_size, settings)
    if not file_uri:
        return None

    return {"file_data": {"mime_type": mime_type, "file_uri": file_uri}}


ProgressFn = Callable[[str, int, str], None]


def _analyze_transcript_impl(
    transcript: str,
    url: str,
    video_path: Optional[str],
    image_paths: Optional[list[str]],
    caption: str,
    media_type: Optional[str],
    settings: Settings,
) -> Optional[dict]:
    if not settings.gemini_api_key:
        print("GEMINI_API_KEY 未配置，使用本地规则生成基础分析。", flush=True)
        source_text = (caption or transcript or url or "").strip()
        compact = " ".join(source_text.split())
        summary = compact[:220] or "未提取到可分析文本，已保留原链接与媒体文件。"
        tags = []
        for token in ["AIGC", "AI生图", "PS", "AE", "视差动画", "AI动画", "设计干货", "小红书"]:
            if token.lower() in compact.lower() or token in url:
                tags.append(token)
        if not tags:
            tags = ["待人工复核"]
        return {
            "summary": [summary],
            "hooks": "本地基础分析：标题/文案提供明确收益点，需要人工复核前 5 秒画面。",
            "emotion": "好奇 / 爽感",
            "score": 60,
            "tags": tags[:5],
            "action_plan": "1. 保留原链接和已下载媒体。\n2. 待配置 GEMINI_API_KEY/DASHSCOPE_API_KEY 后可重新生成完整拆解。\n3. 当前先作为知识素材入库，避免链路阻塞。",
            "fallback_reason": "missing_GEMINI_API_KEY",
        }

    kind = "视频"
    if media_type == "animated":
        kind = "动图"
    elif media_type == "image" or (image_paths and not video_path):
        kind = "图文"
    elif not video_path and not image_paths:
        kind = "文案"

    caption = caption or ""
    transcript = transcript or ""

    caption_block = f"文案:\n{caption}" if caption else "文案: (空)"
    transcript_block = f"逐字稿:\n{transcript}" if transcript else "逐字稿: (空)"
    user_content = (
        f"内容类型: {kind}\n"
        f"链接: {url}\n"
        "请优先基于媒体内容与文案完成分析。\n"
        "若是图文/动图，请以图片内容为主，文案为辅。\n\n"
        f"{caption_block}\n\n{transcript_block}"
    )
    parts = [
        {"text": ANALYST_SYSTEM_PROMPT},
        {"text": user_content},
    ]

    if video_path:
        video_part = build_media_part(video_path, settings)
        if video_part:
            parts.append(video_part)
    elif image_paths:
        for path in image_paths[:6]:
            image_part = build_media_part(path, settings)
            if image_part:
                parts.append(image_part)

    request_body = {"contents": [{"parts": parts}]}

    try:
        response = requests.post(
            f"{settings.gemini_base_url}v1beta/models/{settings.gemini_model}:generateContent",
            headers={
                "Content-Type": "application/json",
                "X-goog-api-key": settings.gemini_api_key,
            },
            json=request_body,
            timeout=settings.gemini_timeout,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        resp = getattr(exc, "response", None)
        if resp is not None:
            preview = resp.text[:400].replace("\n", " ")
            print(f"分析接口异常: {resp.status_code} {preview}", flush=True)
        else:
            print(f"分析接口异常: {exc}", flush=True)
        return None

    try:
        payload = response.json()
    except ValueError:
        print("分析接口返回非 JSON。", flush=True)
        return None

    content = extract_gemini_text(payload).strip()
    if not content:
        print("分析接口返回空内容。", flush=True)
        return None

    return parse_json_payload(content)


def analyze_transcript(
    transcript: str,
    url: str,
    video_path: Optional[str],
    image_paths: Optional[list[str]],
    caption: str,
    media_type: Optional[str],
    settings: Settings,
    progress: Optional[ProgressFn] = None,
    progress_range: tuple[int, int] = (70, 90),
) -> Optional[dict]:
    if not progress:
        return _analyze_transcript_impl(
            transcript,
            url,
            video_path,
            image_paths,
            caption,
            media_type,
            settings,
        )

    result_box: dict[str, Optional[dict]] = {"result": None}
    error_box: dict[str, Exception] = {}

    def worker() -> None:
        try:
            result_box["result"] = _analyze_transcript_impl(
                transcript,
                url,
                video_path,
                image_paths,
                caption,
                media_type,
                settings,
            )
        except Exception as exc:
            error_box["error"] = exc

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()

    start_time = time.time()
    start_percent, end_percent = progress_range
    while thread.is_alive():
        elapsed = time.time() - start_time
        timeout = max(settings.gemini_timeout, 1.0)
        ratio = min(elapsed / timeout, 0.95)
        percent = start_percent + int((end_percent - start_percent) * ratio)
        try:
            progress("analyst", percent, f"分析中 {elapsed:.0f}s")
        except Exception:
            pass
        thread.join(timeout=1.0)

    thread.join()
    if error_box:
        return None
    return result_box["result"]
