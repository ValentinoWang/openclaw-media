from __future__ import annotations

from contextlib import contextmanager
from http import HTTPStatus
import os
from pathlib import Path
import shutil
import subprocess
import threading
import tempfile
import time
from typing import Any, Callable, Optional

import dashscope
import requests
from dashscope.audio.asr import Recognition
from dashscope.audio.asr.recognition import RecognitionCallback, RecognitionResult
from dashscope.utils.oss_utils import OssUtils

from .config import Settings


ProgressFn = Callable[[str, int, str], None]
_DEFAULT_SAMPLE_RATE = 16000
_DASHSCOPE_TRANSCRIPTION_ENDPOINT = "https://dashscope.aliyuncs.com/api/v1/services/audio/asr/transcription"
_DASHSCOPE_TASK_ENDPOINT = "https://dashscope.aliyuncs.com/api/v1/tasks/{task_id}"
_PROXY_ENV_KEYS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
)


@contextmanager
def _without_proxy_env():
    saved = {key: os.environ.get(key) for key in _PROXY_ENV_KEYS}
    try:
        for key in _PROXY_ENV_KEYS:
            os.environ.pop(key, None)
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _dashscope_request(method: str, url: str, **kwargs: Any) -> requests.Response:
    with requests.Session() as session:
        session.trust_env = False
        return session.request(method, url, **kwargs)


def _dashscope_sample_rate(model: str) -> int:
    return 8000 if "8k" in (model or "").lower() else _DEFAULT_SAMPLE_RATE


def _convert_audio_for_asr(file_path: str, sample_rate: int) -> str:
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg 未安装，无法将音频转换为 DashScope ASR 所需格式。")

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
        str(sample_rate),
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


def _use_dashscope_batch_asr(settings: Settings) -> bool:
    mode = (settings.dashscope_asr_mode or "auto").strip().lower()
    if mode in {"batch", "file", "offline", "async", "non-realtime", "non_realtime"}:
        return True
    if mode in {"realtime", "streaming", "stream"}:
        return False
    model = (settings.dashscope_asr_model or "").strip().lower()
    return "realtime" not in model


def _dashscope_headers(settings: Settings, *, async_request: bool = False, resolve_oss: bool = False) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {settings.dashscope_api_key}",
        "Content-Type": "application/json",
    }
    if async_request:
        headers["X-DashScope-Async"] = "enable"
    if resolve_oss:
        headers["X-DashScope-OssResourceResolve"] = "enable"
    return headers


def _dashscope_json(response: requests.Response, action: str) -> dict[str, Any]:
    if response.status_code >= 400:
        detail = response.text.strip()
        raise RuntimeError(f"DashScope {action}失败 HTTP {response.status_code}: {detail[:800]}")
    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError(f"DashScope {action}返回的不是 JSON：{response.text[:800]}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"DashScope {action}返回格式异常：{payload!r}")
    return payload


def _dashscope_request_timeout(settings: Settings, cap: float = 120.0) -> float:
    return min(max(settings.dashscope_timeout, 1.0), cap)


def _submit_dashscope_batch(file_path: str, settings: Settings) -> str:
    with _without_proxy_env():
        uploaded_url, _ = OssUtils.upload(
            model=settings.dashscope_asr_model,
            file_path=file_path,
            api_key=settings.dashscope_api_key,
        )

    parameters: dict[str, Any] = {}
    if settings.dashscope_diarization_enabled:
        parameters["diarization_enabled"] = True
    if settings.dashscope_speaker_count > 0:
        parameters["speaker_count"] = settings.dashscope_speaker_count

    payload: dict[str, Any] = {
        "model": settings.dashscope_asr_model,
        "input": {"file_urls": [uploaded_url]},
    }
    if parameters:
        payload["parameters"] = parameters

    response = _dashscope_request(
        "POST",
        _DASHSCOPE_TRANSCRIPTION_ENDPOINT,
        headers=_dashscope_headers(settings, async_request=True, resolve_oss=True),
        json=payload,
        timeout=_dashscope_request_timeout(settings),
    )
    data = _dashscope_json(response, "提交非实时转写任务")
    output = data.get("output") if isinstance(data.get("output"), dict) else {}
    task_id = str(output.get("task_id") or data.get("task_id") or "").strip()
    if not task_id:
        raise RuntimeError(f"DashScope 未返回非实时转写 task_id：{data!r}")
    return task_id


def _poll_dashscope_batch(task_id: str, settings: Settings) -> dict[str, Any]:
    deadline = time.time() + max(settings.dashscope_timeout, 1.0)
    poll_interval = max(settings.dashscope_poll_interval, 1.0)
    last_status = ""
    last_payload: dict[str, Any] = {}

    while True:
        response = _dashscope_request(
            "GET",
            _DASHSCOPE_TASK_ENDPOINT.format(task_id=task_id),
            headers=_dashscope_headers(settings),
            timeout=_dashscope_request_timeout(settings, cap=60.0),
        )
        data = _dashscope_json(response, "查询非实时转写任务")
        last_payload = data
        output = data.get("output") if isinstance(data.get("output"), dict) else {}
        status = str(output.get("task_status") or data.get("task_status") or "").upper()
        last_status = status or last_status

        if status in {"SUCCEEDED", "SUCCESS"}:
            return data
        if status in {"FAILED", "CANCELED", "CANCELLED"}:
            message = output.get("message") or data.get("message") or data.get("code") or data
            raise RuntimeError(f"DashScope 非实时转写任务失败：{message}")
        if time.time() >= deadline:
            raise RuntimeError(
                f"DashScope 非实时转写超时：任务 {task_id} 在 {settings.dashscope_timeout:.0f}s 内未完成，"
                f"最后状态 {last_status or 'unknown'}，最后响应 {last_payload!r}"
            )
        time.sleep(poll_interval)


def _transcription_result_url(task_payload: dict[str, Any]) -> str:
    output = task_payload.get("output") if isinstance(task_payload.get("output"), dict) else {}
    results = output.get("results")
    if not isinstance(results, list) or not results:
        raise RuntimeError(f"DashScope 非实时转写完成但没有 results：{task_payload!r}")

    failed: list[str] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        status = str(item.get("subtask_status") or item.get("status") or "").upper()
        if status in {"FAILED", "CANCELED", "CANCELLED"}:
            failed.append(str(item.get("message") or item.get("code") or item))
            continue
        url = str(item.get("transcription_url") or item.get("url") or "").strip()
        if url:
            return url

    detail = "; ".join(failed) if failed else repr(results)
    raise RuntimeError(f"DashScope 非实时转写没有可下载的转写结果：{detail}")


def _first_text(payload: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = payload.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _first_time(payload: dict[str, Any]) -> float:
    for key in ("begin_time", "start_time", "start", "begin"):
        value = payload.get(key)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return -1.0


def _format_speaker_text(speaker: str, text: str) -> str:
    if not speaker:
        return text
    lowered = speaker.lower()
    if lowered.startswith("speaker") or speaker.startswith("说话人"):
        return f"{speaker}：{text}"
    return f"说话人{speaker}：{text}"


def _collect_batch_transcript_lines(payload: Any, inherited_speaker: str = "") -> list[tuple[float, str]]:
    if isinstance(payload, list):
        lines: list[tuple[float, str]] = []
        for item in payload:
            lines.extend(_collect_batch_transcript_lines(item, inherited_speaker))
        return lines

    if isinstance(payload, dict):
        speaker = _first_text(payload, ("speaker_id", "speaker", "spk", "speaker_no")) or inherited_speaker
        lines: list[tuple[float, str]] = []
        for key in ("sentences", "sentence", "segments", "segment", "transcripts", "results"):
            value = payload.get(key)
            if isinstance(value, (list, dict)):
                lines.extend(_collect_batch_transcript_lines(value, speaker))
        if lines:
            return lines

        text = _first_text(payload, ("text", "transcript", "content", "sentence_text"))
        if text:
            return [(_first_time(payload), _format_speaker_text(speaker, text))]
        return []

    if isinstance(payload, str) and payload.strip():
        return [(-1.0, payload.strip())]
    return []


def _extract_dashscope_batch_transcript(payload: Any) -> Optional[str]:
    lines = _collect_batch_transcript_lines(payload)
    if not lines:
        return None

    if any(begin >= 0 for begin, _line in lines):
        indexed = list(enumerate(lines))
        indexed.sort(key=lambda item: (item[1][0] if item[1][0] >= 0 else item[0], item[0]))
        ordered_lines = [line for _index, (_begin, line) in indexed]
    else:
        ordered_lines = [line for _begin, line in lines]

    text = "\n".join(line.strip() for line in ordered_lines if line.strip())
    return text.strip() or None


def _download_dashscope_batch_result(result_url: str, settings: Settings) -> Optional[str]:
    response = _dashscope_request("GET", result_url, timeout=_dashscope_request_timeout(settings))
    if response.status_code >= 400:
        detail = response.text.strip()
        raise RuntimeError(f"DashScope 下载非实时转写结果失败 HTTP {response.status_code}: {detail[:800]}")
    try:
        payload: Any = response.json()
    except ValueError:
        payload = response.text
    return _extract_dashscope_batch_transcript(payload)


def _transcribe_via_dashscope_batch(file_path: str, settings: Settings) -> Optional[str]:
    task_id = _submit_dashscope_batch(file_path, settings)
    task_payload = _poll_dashscope_batch(task_id, settings)
    return _download_dashscope_batch_result(_transcription_result_url(task_payload), settings)


def _transcribe_via_dashscope_realtime(file_path: str, settings: Settings) -> Optional[str]:
    if not settings.dashscope_api_key:
        raise RuntimeError("DASHSCOPE_API_KEY 未配置，无法进行转写。")

    sample_rate = _dashscope_sample_rate(settings.dashscope_asr_model)
    converted_path = _convert_audio_for_asr(file_path, sample_rate)
    dashscope.api_key = settings.dashscope_api_key
    recognizer = Recognition(
        model=settings.dashscope_asr_model,
        callback=RecognitionCallback(),
        format="wav",
        sample_rate=sample_rate,
    )
    try:
        with _without_proxy_env():
            result = recognizer.call(converted_path)
        return _extract_transcript(result)
    finally:
        try:
            os.remove(converted_path)
        except OSError:
            pass


def _transcribe_via_dashscope(file_path: str, settings: Settings) -> Optional[str]:
    if not settings.dashscope_api_key:
        raise RuntimeError("DASHSCOPE_API_KEY 未配置，无法进行转写。")
    if _use_dashscope_batch_asr(settings):
        return _transcribe_via_dashscope_batch(file_path, settings)
    return _transcribe_via_dashscope_realtime(file_path, settings)


def _openai_transcription_endpoint(base_url: str) -> str:
    base = (base_url or "https://api.openai.com/v1").rstrip("/")
    if base.endswith("/audio/transcriptions"):
        return base
    return f"{base}/audio/transcriptions"


def _transcribe_via_openai_whisper(file_path: str, settings: Settings) -> Optional[str]:
    if not settings.openai_api_key:
        raise RuntimeError("SELFMEDIA_TRANSCRIPTION_OPENAI_API_KEY 未配置，无法使用 Whisper 转写。")

    endpoint = _openai_transcription_endpoint(settings.openai_base_url)
    data = {
        "model": settings.openai_transcription_model or "whisper-1",
        "response_format": "text",
    }
    if settings.openai_transcription_language:
        data["language"] = settings.openai_transcription_language

    with open(file_path, "rb") as audio_file:
        response = requests.post(
            endpoint,
            headers={"Authorization": f"Bearer {settings.openai_api_key}"},
            data=data,
            files={"file": (Path(file_path).name, audio_file, "application/octet-stream")},
            timeout=max(settings.openai_transcription_timeout, 1.0),
        )
    if response.status_code >= 400:
        detail = response.text.strip()
        raise RuntimeError(f"Whisper 转写失败 HTTP {response.status_code}: {detail[:500]}")

    text = response.text.strip()
    if text.startswith("{"):
        try:
            payload = response.json()
            text = str(payload.get("text") or "").strip()
        except ValueError:
            pass
    return text or None


def _resolve_asr_provider(settings: Settings) -> str:
    provider = (settings.asr_provider or "dashscope").strip().lower()
    if provider in {"whisper", "openai-whisper"}:
        return "openai"
    if provider == "auto":
        return "openai" if settings.openai_api_key else "dashscope"
    if provider:
        return provider
    return "dashscope"


def _provider_timeout(settings: Settings, provider: str) -> float:
    if provider == "openai":
        return settings.openai_transcription_timeout
    return settings.dashscope_timeout


def _transcribe_with_provider(file_path: str, settings: Settings, provider: str) -> Optional[str]:
    if provider == "openai":
        return _transcribe_via_openai_whisper(file_path, settings)
    if provider == "dashscope":
        return _transcribe_via_dashscope(file_path, settings)
    raise RuntimeError(f"不支持的 ASR_PROVIDER：{settings.asr_provider}")


def transcribe_audio(
    file_path: str,
    settings: Settings,
    progress: Optional[ProgressFn] = None,
    progress_range: tuple[int, int] = (45, 70),
    raise_errors: bool = False,
) -> Optional[str]:
    result_text: dict[str, Optional[str]] = {"text": None}
    error_box: dict[str, Exception] = {}
    provider = _resolve_asr_provider(settings)

    def worker() -> None:
        try:
            result_text["text"] = _transcribe_with_provider(file_path, settings, provider)
        except Exception as exc:
            error_box["error"] = exc

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()

    start_time = time.time()
    start_percent, end_percent = progress_range
    while thread.is_alive():
        if progress:
            elapsed = time.time() - start_time
            timeout = max(_provider_timeout(settings, provider), 1.0)
            ratio = min(elapsed / timeout, 0.95)
            percent = start_percent + int((end_percent - start_percent) * ratio)
            try:
                progress("transcriber", percent, f"转写中 {elapsed:.0f}s")
            except Exception:
                pass
        thread.join(timeout=1.0)

    thread.join()
    if error_box:
        if raise_errors:
            raise error_box["error"]
        print(f"{provider} 转写失败: {error_box['error']}", flush=True)
        return None

    return result_text["text"]
