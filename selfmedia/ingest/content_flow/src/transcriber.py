from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import time
from typing import Any, Callable, Optional

import requests

from .config import Settings


ProgressFn = Callable[[str, int, str], None]

_DASHSCOPE_TRANSCRIPTION_ENDPOINT = "https://dashscope.aliyuncs.com/api/v1/services/audio/asr/transcription"
_DASHSCOPE_TASK_ENDPOINT = "https://dashscope.aliyuncs.com/api/v1/tasks/{task_id}"
_DASHSCOPE_BATCH_MODE_ALIASES = {"batch", "file", "offline", "async", "non-realtime", "non_realtime"}
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


def _load_oss_utils() -> Any:
    try:
        from dashscope.utils.oss_utils import OssUtils
    except ModuleNotFoundError as exc:
        raise RuntimeError("dashscope Python package 未安装，无法使用阿里 DashScope ASR。请在 content-flow 环境运行 uv sync。") from exc
    return OssUtils


def _dashscope_request(method: str, url: str, **kwargs: Any) -> requests.Response:
    with requests.Session() as session:
        session.trust_env = False
        return session.request(method, url, **kwargs)


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


def _require_dashscope_batch_settings(file_path: str, settings: Settings) -> None:
    path = Path(file_path)
    if not path.is_file() or path.stat().st_size <= 0:
        raise RuntimeError(f"音频文件不存在或为空：{file_path}")
    provider = (settings.asr_provider or "dashscope").strip().lower()
    if provider != "dashscope":
        raise RuntimeError(f"ASR_PROVIDER 只能是 dashscope；当前为 {settings.asr_provider!r}。")
    if not settings.dashscope_api_key:
        raise RuntimeError("DASHSCOPE_API_KEY 未配置，无法使用阿里 DashScope ASR。")
    mode = (settings.dashscope_asr_mode or "batch").strip().lower()
    if mode not in _DASHSCOPE_BATCH_MODE_ALIASES:
        raise RuntimeError(f"DASHSCOPE_ASR_MODE 只能是 batch/async/offline；当前为 {settings.dashscope_asr_mode!r}。")
    if not (settings.dashscope_asr_model or "").strip():
        raise RuntimeError("DASHSCOPE_ASR_MODEL 未配置。")


def _submit_dashscope_batch(file_path: str, settings: Settings) -> str:
    oss_utils = _load_oss_utils()
    with _without_proxy_env():
        uploaded_url, _ = oss_utils.upload(
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


def _poll_dashscope_batch(
    task_id: str,
    settings: Settings,
    progress: Optional[ProgressFn] = None,
    progress_range: tuple[int, int] = (45, 70),
) -> dict[str, Any]:
    start_time = time.time()
    deadline = start_time + max(settings.dashscope_timeout, 1.0)
    poll_interval = max(settings.dashscope_poll_interval, 1.0)
    last_status = ""
    last_payload: dict[str, Any] = {}
    start_percent, end_percent = progress_range

    while True:
        elapsed = time.time() - start_time
        if progress:
            timeout = max(settings.dashscope_timeout, 1.0)
            ratio = min(elapsed / timeout, 0.95)
            percent = start_percent + int((end_percent - start_percent) * ratio)
            progress("transcriber", percent, f"DashScope 转写中 {elapsed:.0f}s")

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


def _coerce_time_seconds(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number > 1000:
        return round(number / 1000.0, 3)
    return number


def _first_time(payload: dict[str, Any], keys: tuple[str, ...]) -> Optional[float]:
    for key in keys:
        value = _coerce_time_seconds(payload.get(key))
        if value is not None:
            return value
    return None


def _format_speaker_text(speaker: str, text: str) -> str:
    if not speaker:
        return text
    lowered = speaker.lower()
    if lowered.startswith("speaker") or speaker.startswith("说话人"):
        return f"{speaker}：{text}"
    return f"说话人{speaker}：{text}"


def _collect_dashscope_segments(payload: Any, inherited_speaker: str = "") -> list[tuple[float, dict[str, Any]]]:
    if isinstance(payload, list):
        segments: list[tuple[float, dict[str, Any]]] = []
        for item in payload:
            segments.extend(_collect_dashscope_segments(item, inherited_speaker))
        return segments

    if not isinstance(payload, dict):
        if isinstance(payload, str) and payload.strip():
            return [(-1.0, {"text": payload.strip(), "speaker": "", "start": None, "end": None})]
        return []

    speaker = _first_text(payload, ("speaker_id", "speaker", "spk", "speaker_no")) or inherited_speaker
    nested: list[tuple[float, dict[str, Any]]] = []
    for key in ("sentences", "sentence", "segments", "segment", "transcripts", "results"):
        value = payload.get(key)
        if isinstance(value, (list, dict)):
            nested.extend(_collect_dashscope_segments(value, speaker))
    if nested:
        return nested

    text = _first_text(payload, ("text", "transcript", "content", "sentence_text"))
    if not text:
        return []
    start = _first_time(payload, ("begin_time", "start_time", "start", "begin"))
    end = _first_time(payload, ("end_time", "end"))
    segment = {
        "text": _format_speaker_text(speaker, text),
        "speaker": str(speaker or "").strip(),
        "start": start,
        "end": end,
    }
    return [(start if start is not None else -1.0, segment)]


def _extract_dashscope_batch_segments(payload: Any) -> list[dict[str, Any]]:
    indexed = list(enumerate(_collect_dashscope_segments(payload)))
    if any(sort_key >= 0 for _index, (sort_key, _segment) in indexed):
        indexed.sort(key=lambda item: (item[1][0] if item[1][0] >= 0 else item[0], item[0]))
    return [segment for _index, (_sort_key, segment) in indexed if segment.get("text")]


def _download_dashscope_batch_result(result_url: str, settings: Settings) -> list[dict[str, Any]]:
    response = _dashscope_request("GET", result_url, timeout=_dashscope_request_timeout(settings))
    if response.status_code >= 400:
        detail = response.text.strip()
        raise RuntimeError(f"DashScope 下载非实时转写结果失败 HTTP {response.status_code}: {detail[:800]}")
    try:
        payload: Any = response.json()
    except ValueError:
        payload = response.text
    segments = _extract_dashscope_batch_segments(payload)
    if not segments:
        raise RuntimeError(f"DashScope 非实时转写结果未包含可用文本：{str(payload)[:800]}")
    return segments


def _transcribe_with_dashscope(
    file_path: str,
    settings: Settings,
    progress: Optional[ProgressFn] = None,
    progress_range: tuple[int, int] = (45, 70),
) -> dict[str, Any]:
    _require_dashscope_batch_settings(file_path, settings)
    if progress:
        progress("transcriber", progress_range[0], "DashScope 非实时转写提交中")
    task_id = _submit_dashscope_batch(file_path, settings)
    task_payload = _poll_dashscope_batch(task_id, settings, progress=progress, progress_range=progress_range)
    result_url = _transcription_result_url(task_payload)
    segments = _download_dashscope_batch_result(result_url, settings)
    transcript = "\n".join(str(segment.get("text") or "").strip() for segment in segments if segment.get("text")).strip()
    if not transcript:
        raise RuntimeError("DashScope 未返回可用 transcript")
    return {
        "provider": "dashscope",
        "asr_mode": "batch",
        "task_id": task_id,
        "transcript": transcript,
        "segments": segments,
        "language": "",
        "confidence_note": "DashScope 非实时 ASR 输出；未通过本地语义补写。",
    }


def transcribe_audio(
    file_path: str,
    settings: Settings,
    progress: Optional[ProgressFn] = None,
    progress_range: tuple[int, int] = (45, 70),
    raise_errors: bool = False,
) -> Optional[str]:
    try:
        result = _transcribe_with_dashscope(file_path, settings, progress=progress, progress_range=progress_range)
    except Exception as exc:
        if raise_errors:
            raise
        print(f"dashscope 转写失败: {exc}", flush=True)
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
        result = _transcribe_with_dashscope(file_path, settings, progress=progress, progress_range=progress_range)
    except Exception as exc:
        if raise_errors:
            raise
        print(f"dashscope 转写失败: {exc}", flush=True)
        return None
    if progress:
        progress("transcriber", progress_range[1], "转写完成")
    return result
