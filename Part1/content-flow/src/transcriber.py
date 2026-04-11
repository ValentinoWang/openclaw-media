from __future__ import annotations

from http import HTTPStatus
import os
from pathlib import Path
import shutil
import subprocess
import threading
import tempfile
import time
from typing import Callable, Optional

import dashscope
from dashscope.audio.asr import Recognition
from dashscope.audio.asr.recognition import RecognitionCallback, RecognitionResult

from .config import Settings


ProgressFn = Callable[[str, int, str], None]
_TARGET_SAMPLE_RATE = 16000


def _convert_audio_for_asr(file_path: str) -> str:
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg 未安装，无法将音频转换为 fun-asr-realtime 所需格式。")

    source = Path(file_path)
    with tempfile.NamedTemporaryFile(
        prefix=f"{source.stem}-asr-",
        suffix=".wav",
        delete=False,
    ) as tmp_file:
        converted_path = tmp_file.name

    command = [
        "ffmpeg",
        "-y",
        "-i",
        file_path,
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(_TARGET_SAMPLE_RATE),
        "-f",
        "wav",
        converted_path,
    ]
    try:
        subprocess.run(
            command,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("ffmpeg 未安装，无法进行音频转码。") from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(exc.stderr.strip() or "ffmpeg 音频转码失败。") from exc

    return converted_path


def _extract_transcript(result: RecognitionResult) -> Optional[str]:
    if result.status_code != HTTPStatus.OK:
        raise RuntimeError(result.message or result.code or "DashScope 语音识别失败。")

    sentences = result.get_sentence()
    if not sentences:
        return None

    if isinstance(sentences, dict):
        text = str(sentences.get("text") or "").strip()
        return text or None

    ordered = sorted(
        (sentence for sentence in sentences if sentence.get("text")),
        key=lambda sentence: sentence.get("begin_time") or 0,
    )
    text = "\n".join(str(sentence["text"]).strip() for sentence in ordered if sentence["text"])
    return text.strip() or None


def _transcribe_via_dashscope(file_path: str, settings: Settings) -> Optional[str]:
    if not settings.dashscope_api_key:
        raise RuntimeError("DASHSCOPE_API_KEY 未配置，无法进行转写。")

    converted_path = _convert_audio_for_asr(file_path)
    dashscope.api_key = settings.dashscope_api_key
    recognizer = Recognition(
        model=settings.dashscope_asr_model,
        callback=RecognitionCallback(),
        format="wav",
        sample_rate=_TARGET_SAMPLE_RATE,
    )
    try:
        result = recognizer.call(converted_path)
        return _extract_transcript(result)
    finally:
        try:
            os.remove(converted_path)
        except OSError:
            pass


def transcribe_audio(
    file_path: str,
    settings: Settings,
    progress: Optional[ProgressFn] = None,
    progress_range: tuple[int, int] = (45, 70),
) -> Optional[str]:
    result_text: dict[str, Optional[str]] = {"text": None}
    error_box: dict[str, Exception] = {}

    def worker() -> None:
        try:
            result_text["text"] = _transcribe_via_dashscope(file_path, settings)
        except Exception as exc:
            error_box["error"] = exc

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()

    start_time = time.time()
    start_percent, end_percent = progress_range
    while thread.is_alive():
        if progress:
            elapsed = time.time() - start_time
            timeout = max(settings.dashscope_timeout, 1.0)
            ratio = min(elapsed / timeout, 0.95)
            percent = start_percent + int((end_percent - start_percent) * ratio)
            try:
                progress("transcriber", percent, f"转写中 {elapsed:.0f}s")
            except Exception:
                pass
        thread.join(timeout=1.0)

    thread.join()
    if error_box:
        print(f"DashScope 转写失败: {error_box['error']}", flush=True)
        return None

    return result_text["text"]
