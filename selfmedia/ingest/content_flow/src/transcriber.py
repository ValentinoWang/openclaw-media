from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Optional

from common.llm_client import audio_part_from_path, generate_json_from_parts
from common.llm_settings import load_profile_llm_settings

from .config import Settings


ProgressFn = Callable[[str, int, str], None]


TRANSCRIBE_INSTRUCTIONS = (
    "你是音频转写 JSON 引擎。请只基于用户提供的音频输出合法 JSON object，不要 Markdown，不要解释。"
    "字段固定为 transcript、segments、language、confidence_note。"
    "transcript 是完整清洗逐字稿；segments 是按自然语义切分的数组，每项包含 text、speaker、start、end。"
    "如果无法可靠判断 speaker、start、end，可输出空字符串或 null；不要编造真实姓名。"
)


def _build_audio_parts(file_path: str) -> list[dict[str, Any]]:
    path = Path(file_path)
    if not path.is_file() or path.stat().st_size <= 0:
        raise RuntimeError(f"音频文件不存在或为空：{file_path}")
    return [
        {
            "text": (
                "请转写这段音频，并输出 JSON。"
                "保留有效口语信息，清理明显口吃、重复语气词和识别噪声。"
            )
        },
        audio_part_from_path(path),
    ]


def _normalize_segments(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    segments: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, str):
            text = item.strip()
            if text:
                segments.append({"text": text, "speaker": "", "start": None, "end": None})
            continue
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        segments.append(
            {
                "text": text,
                "speaker": str(item.get("speaker") or "").strip(),
                "start": item.get("start"),
                "end": item.get("end"),
            }
        )
    return segments


def _transcribe_with_codex(file_path: str, progress: Optional[ProgressFn] = None) -> dict[str, Any]:
    if progress:
        progress("transcriber", 50, "Codex Responses 转写中")
    settings = load_profile_llm_settings("media_analysis")
    result = generate_json_from_parts(
        _build_audio_parts(file_path),
        settings,
        max_retries=1,
        error_prefix="Codex Responses 音频转写 JSON 校验失败",
        instructions=TRANSCRIBE_INSTRUCTIONS,
    )
    transcript = str(result.get("transcript") or "").strip()
    segments = _normalize_segments(result.get("segments"))
    if not transcript and segments:
        transcript = "\n".join(segment["text"] for segment in segments if segment.get("text"))
    if not transcript:
        raise RuntimeError("Codex Responses 未返回可用 transcript")
    return {
        "provider": "codex_responses",
        "transcript": transcript,
        "segments": segments,
        "language": str(result.get("language") or "").strip(),
        "confidence_note": str(result.get("confidence_note") or "").strip(),
    }


def transcribe_audio(
    file_path: str,
    settings: Settings,
    progress: Optional[ProgressFn] = None,
    progress_range: tuple[int, int] = (45, 70),
    raise_errors: bool = False,
) -> Optional[str]:
    try:
        result = _transcribe_with_codex(file_path, progress)
    except Exception as exc:
        if raise_errors:
            raise
        print(f"codex_responses 转写失败: {exc}", flush=True)
        return None
    if progress:
        progress("transcriber", progress_range[1], "转写完成")
    return str(result.get("transcript") or "").strip() or None


def transcribe_audio_evidence(
    file_path: str,
    settings: Settings,
    progress: Optional[ProgressFn] = None,
    progress_range: tuple[int, int] = (45, 70),
    raise_errors: bool = False,
) -> Optional[dict[str, Any]]:
    try:
        result = _transcribe_with_codex(file_path, progress)
    except Exception as exc:
        if raise_errors:
            raise
        print(f"codex_responses 转写失败: {exc}", flush=True)
        return None
    if progress:
        progress("transcriber", progress_range[1], "转写完成")
    return result
