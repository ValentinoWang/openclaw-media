from __future__ import annotations

import json
import base64
import mimetypes
import os
import queue
import re
import subprocess
import tempfile
import time
import threading
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Any

import requests

from .bot_llm_config import openclaw_subprocess_env
from .llm_settings import (
    API_TYPE_CHAT_COMPLETIONS,
    API_TYPE_CODEX_RESPONSES,
    API_TYPE_OPENCLAW_AGENT,
    LLMProviderSettings,
)
from .llm_validation import validate_llm_payload
from .model_transport_context import ModelCall, ModelTransport, ModelTransportError, current_model_transport


CODEX_AUTH_FILE_SENTINEL = "codex_auth_file"
DEFAULT_CODEX_AUTH_PATH = Path("/home/ubuntu/.codex/auth.json")
DEFAULT_CODEX_RESPONSES_CONNECT_TIMEOUT_SECONDS = 30.0
DEFAULT_CODEX_RESPONSES_READ_TIMEOUT_SECONDS = 120.0
CODEX_RESPONSES_CONNECT_TIMEOUT_ENV = "OPENCLAW_CODEX_RESPONSES_CONNECT_TIMEOUT_SECONDS"
CODEX_RESPONSES_READ_TIMEOUT_ENV = "OPENCLAW_CODEX_RESPONSES_READ_TIMEOUT_SECONDS"
CODEX_RESPONSES_TOTAL_TIMEOUT_ENV = "OPENCLAW_CODEX_RESPONSES_TOTAL_TIMEOUT_SECONDS"
MODEL_CAPACITY_RETRY_DELAYS_SECONDS = (15.0, 45.0)
MODEL_CAPACITY_ERROR_MARKER = "selected model is at capacity"
MODEL_CAPACITY_DEFAULT_DETAIL = "Selected model is at capacity. Please try a different model."


def is_model_capacity_failure(error: object) -> bool:
    return MODEL_CAPACITY_ERROR_MARKER in str(error or "").lower()


def model_capacity_failure_detail(error: object) -> str:
    detail = str(error or "").strip()
    marker_index = detail.lower().find(MODEL_CAPACITY_ERROR_MARKER)
    if marker_index < 0:
        return MODEL_CAPACITY_DEFAULT_DETAIL
    capacity_detail = detail[marker_index:].splitlines()[0].strip()
    return capacity_detail or MODEL_CAPACITY_DEFAULT_DETAIL


def _json_retry_delay_seconds(error: object, attempt: int) -> float:
    if not is_model_capacity_failure(error):
        return 0.5
    return MODEL_CAPACITY_RETRY_DELAYS_SECONDS[min(max(0, attempt), len(MODEL_CAPACITY_RETRY_DELAYS_SECONDS) - 1)]


def ensure_llm_provider_available(config: LLMProviderSettings) -> None:
    tenant_transport = current_model_transport()
    if tenant_transport is not None:
        if not config.model:
            raise RuntimeError("tenant model transport requires an explicit model")
        return
    if config.api_type == API_TYPE_OPENCLAW_AGENT:
        missing = [
            name
            for name, value in (("bin", config.bin), ("agent", config.agent), ("cwd", config.cwd), ("codex_home", config.codex_home))
            if not str(value or "").strip()
        ]
        if missing:
            raise RuntimeError(f"OpenClaw agent provider 配置不完整：{', '.join(missing)}")
        return
    if config.api_type not in {API_TYPE_CODEX_RESPONSES, API_TYPE_CHAT_COMPLETIONS}:
        raise RuntimeError(f"LLM client 不支持 api_type={config.api_type}")
    if not config.api_key:
        raise RuntimeError("缺少可用 LLM Provider：config/openclaw_bots.json 当前 profile provider api_key 未配置")
    if not config.base_url or not config.model or not config.api_type:
        raise RuntimeError("缺少可用 LLM Provider：config/openclaw_bots.json 当前 profile provider 未完整配置")


def resolve_provider_api_key(api_key: str) -> str:
    value = str(api_key or "").strip()
    if value.startswith("env:"):
        env_name = value.removeprefix("env:").strip()
        token = str(os.getenv(env_name) or "").strip()
        if not env_name or not token:
            raise RuntimeError(f"LLM provider API key environment variable is unavailable: {env_name}")
        return token
    if value != CODEX_AUTH_FILE_SENTINEL:
        return value
    auth_path = Path(os.getenv("CODEX_AUTH_FILE", "") or os.getenv("CODEX_AUTH_PATH", "") or DEFAULT_CODEX_AUTH_PATH)
    try:
        payload = json.loads(auth_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError(f"Codex auth token unavailable: {auth_path} does not exist") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Codex auth token unavailable: {auth_path} is not valid JSON") from exc
    candidates = [
        payload.get("OPENAI_API_KEY"),
        (payload.get("tokens") or {}).get("access_token") if isinstance(payload.get("tokens"), dict) else None,
        payload.get("access_token"),
    ]
    for candidate in candidates:
        token = str(candidate or "").strip()
        if token:
            return token
    raise RuntimeError(f"Codex auth token unavailable: {auth_path} has no usable token")


def generate_json_from_parts(
    parts: list[dict[str, Any]],
    config: LLMProviderSettings,
    *,
    max_retries: int = 2,
    capacity_max_retries: int | None = None,
    error_prefix: str = "LLM 输出 JSON 校验失败",
    retry_text: str = "上一次输出没有通过 JSON 校验：{error}\n请只返回合法 JSON object，不要 Markdown。",
    instructions: str = "你是 JSON 输出引擎。必须只输出合法 JSON object，不要 Markdown，不要解释。",
    validation_contract: str,
    validation_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ensure_llm_provider_available(config)
    last_error = ""
    request_parts = list(parts)
    normal_retry_limit = max(0, int(max_retries))
    capacity_retry_limit = max(
        normal_retry_limit,
        int(capacity_max_retries) if capacity_max_retries is not None else normal_retry_limit,
    )
    for attempt in range(capacity_retry_limit + 1):
        try:
            parsed = generate_json_once(request_parts, config, instructions=instructions)
            return validate_llm_payload(parsed, validation_contract, context=validation_context).payload
        except ModelTransportError:
            raise
        except Exception as exc:
            last_error = str(exc)
            retry_limit = capacity_retry_limit if is_model_capacity_failure(exc) else normal_retry_limit
            if attempt >= retry_limit:
                break
            request_parts = list(parts) + [{"text": retry_text.format(error=last_error)}]
            time.sleep(_json_retry_delay_seconds(exc, attempt))
    raise RuntimeError(f"{error_prefix}：{last_error}")


def generate_json_once(
    parts: list[dict[str, Any]],
    config: LLMProviderSettings,
    *,
    instructions: str = "你是 JSON 输出引擎。必须只输出合法 JSON object，不要 Markdown，不要解释。",
) -> dict[str, Any]:
    ensure_llm_provider_available(config)
    if current_model_transport() is not None:
        # Authenticated Media execution owns the transport decision. Provider
        # base URLs, auth files, direct HTTP credentials and agent subprocesses
        # from a shared profile are intentionally unreachable in this scope.
        tenant_model = str(config.model).strip()
        if "/" in tenant_model:
            tenant_model = tenant_model.split("/", 1)[1]
        return _generate_json_codex_responses(
            parts,
            replace(config, model=tenant_model, api_type=API_TYPE_CODEX_RESPONSES),
            instructions=instructions,
        )
    if config.api_type == API_TYPE_OPENCLAW_AGENT:
        return _generate_json_openclaw_agent(parts, config, instructions=instructions)
    if config.api_type == API_TYPE_CODEX_RESPONSES:
        return _generate_json_codex_responses(parts, config, instructions=instructions)
    if config.api_type != API_TYPE_CHAT_COMPLETIONS:
        raise RuntimeError(f"direct LLM client 不支持 api_type={config.api_type}")
    return _generate_json_chat_completions(parts, config)


def _generate_json_openclaw_agent(
    parts: list[dict[str, Any]],
    config: LLMProviderSettings,
    *,
    instructions: str,
) -> dict[str, Any]:
    message_parts = [instructions.strip()]
    attachments: list[tuple[str, str, str]] = []
    for index, part in enumerate(parts, start=1):
        if "text" in part:
            message_parts.append(str(part["text"]))
            continue
        data = part.get("image_data") or part.get("inline_data") or part.get("audio_data")
        if not isinstance(data, dict) or not str(data.get("data") or "").strip():
            raise RuntimeError(f"OpenClaw agent 不支持的 LLM part：{sorted(part)}")
        mime_type = str(data.get("mime_type") or ("audio/mpeg" if "audio_data" in part else "image/jpeg"))
        attachments.append(
            (
                str(data.get("file_name") or f"input-{index}{mimetypes.guess_extension(mime_type) or ''}"),
                mime_type,
                str(data["data"]),
            )
        )

    message = "\n\n".join(item for item in message_parts if item).strip()
    if not message:
        raise RuntimeError("OpenClaw agent JSON 调用缺少文本指令")
    timeout_seconds = max(1, int(float(config.timeout or 600)))
    run_token = uuid.uuid4().hex
    try:
        with tempfile.TemporaryDirectory(prefix="openclaw-structured-json-") as temp_dir:
            temp_root = Path(temp_dir)
            attachment_lines: list[str] = []
            for index, (file_name, mime_type, content) in enumerate(attachments, start=1):
                safe_name = Path(file_name).name or f"input-{index}"
                attachment_path = temp_root / safe_name
                try:
                    attachment_path.write_bytes(base64.b64decode(content, validate=True))
                except (ValueError, base64.binascii.Error) as exc:
                    raise RuntimeError(f"OpenClaw agent attachment {safe_name} 不是合法 base64") from exc
                attachment_lines.append(f"- {mime_type}: {attachment_path}")
            if attachment_lines:
                message = f"{message}\n\n本次输入附件（必须读取后再输出 JSON）：\n" + "\n".join(attachment_lines)
            message_path = temp_root / "prompt.txt"
            message_path.write_text(message, encoding="utf-8")
            command = [
                config.bin,
                "agent",
                "--agent",
                config.agent,
                "--session-key",
                f"agent:{config.agent}:structured-json:{run_token}",
                "--message-file",
                str(message_path),
                "--timeout",
                str(timeout_seconds),
                "--json",
            ]
            proc = subprocess.run(
                command,
                cwd=config.cwd or None,
                env=openclaw_subprocess_env(config.codex_home),
                text=True,
                capture_output=True,
                timeout=timeout_seconds + 45,
                check=False,
            )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"OpenClaw Codex harness JSON 调用失败：{exc}") from exc
    if proc.returncode != 0:
        detail = "\n".join(
            item for item in (proc.stderr.strip(), proc.stdout.strip(), f"exit={proc.returncode}") if item
        )[-4000:]
        raise RuntimeError(f"OpenClaw Codex harness JSON 调用失败：{detail}")
    try:
        payload = json.loads(proc.stdout)
        result = payload.get("result") if isinstance(payload.get("result"), dict) else payload
        payloads = result.get("payloads") if isinstance(result, dict) else None
        text = next(
            str(item.get("text") or "")
            for item in (payloads or [])
            if isinstance(item, dict) and str(item.get("text") or "").strip()
        )
    except (json.JSONDecodeError, AttributeError, StopIteration, TypeError) as exc:
        raise RuntimeError("OpenClaw Codex harness 没有返回可解析的 JSON 文本") from exc
    return parse_json_object_text(text)


def _generate_json_chat_completions(parts: list[dict[str, Any]], config: LLMProviderSettings) -> dict[str, Any]:
    content = []
    for part in parts:
        if "text" in part:
            content.append({"type": "text", "text": str(part["text"])})
        elif "image_data" in part:
            data = part["image_data"]
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:{data.get('mime_type','image/jpeg')};base64,{data.get('data','')}"},
            })
        elif "inline_data" in part:
            data = part["inline_data"]
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:{data.get('mime_type','image/png')};base64,{data.get('data','')}"},
            })
        elif "audio_data" in part:
            data = part["audio_data"]
            content.append({
                "type": "input_audio",
                "input_audio": {
                    "data": str(data.get("data") or ""),
                    "format": _audio_format(data),
                },
            })
    body = {
            "model": config.model,
            "messages": [{"role": "user", "content": content}],
            "response_format": {"type": "json_object"},
        }
    response, model_call = _post_model_request(
        config,
        "/chat/completions",
        body,
        timeout=config.timeout,
    )
    try:
        payload = response.json()
        if model_call is not None:
            model_call.complete(response, payload)
        parsed = parse_json_object_text(payload["choices"][0]["message"]["content"])
        return parsed
    except Exception:
        if model_call is not None:
            model_call.uncertain(response)
        raise


def _generate_json_codex_responses(
    parts: list[dict[str, Any]],
    config: LLMProviderSettings,
    *,
    instructions: str,
) -> dict[str, Any]:
    body = build_codex_responses_body(parts, config, instructions=instructions)
    return _generate_json_codex_responses_stream(body, config)


def build_codex_responses_body(parts: list[dict[str, Any]], config: LLMProviderSettings, *, instructions: str) -> dict[str, Any]:
    content = []
    for part in parts:
        if "text" in part:
            content.append({"type": "input_text", "text": str(part["text"])})
        elif "image_data" in part:
            data = part["image_data"]
            content.append({
                "type": "input_image",
                "detail": "auto",
                "image_url": f"data:{data.get('mime_type','image/jpeg')};base64,{data.get('data','')}",
            })
        elif "inline_data" in part:
            data = part["inline_data"]
            content.append({
                "type": "input_image",
                "detail": "auto",
                "image_url": f"data:{data.get('mime_type','image/png')};base64,{data.get('data','')}",
            })
        elif "audio_data" in part:
            data = part["audio_data"]
            content.append({
                "type": "input_audio",
                "input_audio": {
                    "data": str(data.get("data") or ""),
                    "format": _audio_format(data),
                },
            })
    body: dict[str, Any] = {
        "model": config.model,
        "instructions": instructions,
        "input": [{"role": "user", "content": content}],
        "stream": False,
        "store": False,
    }
    if config.thinking:
        body["reasoning"] = {"effort": config.thinking}
    return body


def _generate_json_codex_responses_stream(body: dict[str, Any], config: LLMProviderSettings) -> dict[str, Any]:
    body = dict(body)
    body["stream"] = True
    total_timeout = codex_responses_total_timeout(config.timeout)
    tenant_transport = current_model_transport()
    completed_response: requests.Response | None = None
    completed_call: ModelCall | None = None
    try:
        def _request_and_collect() -> str:
            nonlocal completed_response, completed_call
            response, model_call = _post_model_request(
                config,
                "/responses",
                body,
                timeout=codex_responses_stream_timeout(config.timeout),
                stream=True,
                transport=tenant_transport,
            )
            completed_response = response
            completed_call = model_call
            try:
                output = collect_responses_sse_text(
                    response,
                    progress_timeout_seconds=codex_responses_read_timeout(config.timeout),
                    total_timeout_seconds=total_timeout,
                )
                if model_call is not None:
                    model_call.complete(response)
                return output
            except Exception:
                if model_call is not None:
                    model_call.uncertain(response)
                raise
            finally:
                close = getattr(response, "close", None)
                if callable(close):
                    close()

        output_text = _run_with_thread_deadline(
            _request_and_collect,
            total_timeout,
            "Codex Responses SSE exceeded hard total timeout before completion",
        )
    except TimeoutError as exc:
        if completed_call is not None:
            completed_call.uncertain(completed_response)
        raise RuntimeError(
            f"Codex Responses SSE watchdog timeout: {exc}. "
            f"progress_timeout={codex_responses_read_timeout(config.timeout):g}s, "
            f"total_timeout={total_timeout:g}s. "
            "Increase OPENCLAW_CODEX_RESPONSES_READ_TIMEOUT_SECONDS only when Responses progress events are still arriving, "
            "or OPENCLAW_CODEX_RESPONSES_TOTAL_TIMEOUT_SECONDS for known long runs."
        ) from exc
    except requests.exceptions.RequestException as exc:
        if completed_call is not None:
            completed_call.uncertain(completed_response)
        if not _is_timeout_like_request_error(exc):
            raise
        raise RuntimeError(
            f"Codex Responses SSE watchdog timeout: {exc}. "
            f"progress_timeout={codex_responses_read_timeout(config.timeout):g}s, "
            f"total_timeout={total_timeout:g}s. "
            "Increase OPENCLAW_CODEX_RESPONSES_READ_TIMEOUT_SECONDS only when Responses progress events are still arriving, "
            "or OPENCLAW_CODEX_RESPONSES_TOTAL_TIMEOUT_SECONDS for known long runs."
        ) from exc
    return parse_json_object_text(output_text)


def _post_model_request(
    config: LLMProviderSettings,
    endpoint: str,
    body: dict[str, Any],
    *,
    timeout: Any,
    stream: bool = False,
    transport: ModelTransport | None = None,
) -> tuple[requests.Response, ModelCall | None]:
    tenant_transport = transport if transport is not None else current_model_transport()
    if tenant_transport is not None:
        model_call = tenant_transport.begin_call(endpoint)
        return (
            model_call.post(endpoint, json_body=body, timeout=timeout, stream=stream),
            model_call,
        )
    response = requests.post(
        (codex_responses_url(config.base_url) if endpoint == "/responses" else f"{config.base_url}{endpoint}"),
        headers={
            "Authorization": f"Bearer {resolve_provider_api_key(config.api_key)}",
            "Content-Type": "application/json",
        },
        json=body,
        timeout=timeout,
        stream=stream,
    )
    response.raise_for_status()
    return response, None


def parse_json_object_text(text: str) -> dict[str, Any]:
    cleaned = str(text or "").strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", cleaned, flags=re.DOTALL | re.IGNORECASE)
    if fence:
        cleaned = fence.group(1).strip()
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        parsed = json.loads(cleaned[start:end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("JSON 顶层必须是 object")
    return parsed


def audio_part_from_path(path: str | Path) -> dict[str, Any]:
    audio_path = Path(path)
    mime_type = mimetypes.guess_type(str(audio_path))[0] or "application/octet-stream"
    data = audio_path.read_bytes()
    return {
        "audio_data": {
            "mime_type": mime_type,
            "format": _audio_format({"mime_type": mime_type, "path": str(audio_path)}),
            "data": base64.b64encode(data).decode("ascii"),
            "path": str(audio_path),
        }
    }


def _audio_format(data: dict[str, Any]) -> str:
    explicit = str(data.get("format") or "").strip().lower()
    if explicit:
        return explicit
    mime_type = str(data.get("mime_type") or "").lower()
    path = str(data.get("path") or "").lower()
    if "wav" in mime_type or path.endswith(".wav"):
        return "wav"
    if "mpeg" in mime_type or "mp3" in mime_type or path.endswith(".mp3"):
        return "mp3"
    if "mp4" in mime_type or "m4a" in mime_type or path.endswith((".m4a", ".mp4")):
        return "mp4"
    if "webm" in mime_type or path.endswith(".webm"):
        return "webm"
    if "ogg" in mime_type or path.endswith(".ogg"):
        return "ogg"
    return "mp3"


def collect_responses_sse_text(
    resp: requests.Response,
    *,
    progress_timeout_seconds: float | None = None,
    total_timeout_seconds: float | None = None,
) -> str:
    chunks: list[str] = []
    progress_timeout = _positive_float(str(progress_timeout_seconds), 0.0) if progress_timeout_seconds else 0.0
    total_timeout = _positive_float(str(total_timeout_seconds), 0.0) if total_timeout_seconds else 0.0
    started_at = time.monotonic()
    last_event_at = started_at
    buffer = ""
    done = False

    # Responses proxies may advertise a legacy response charset; SSE payloads are UTF-8 JSON bytes.
    for raw_chunk in resp.iter_content(chunk_size=4096, decode_unicode=False):
        _check_responses_watchdog(started_at, last_event_at, progress_timeout, total_timeout)
        if not raw_chunk:
            continue
        if isinstance(raw_chunk, bytes):
            buffer += raw_chunk.decode("utf-8", errors="ignore")
        else:
            buffer += str(raw_chunk)
        while "\n" in buffer:
            raw_line, buffer = buffer.split("\n", 1)
            line = raw_line.strip()
            if not line or not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                done = True
                break
            try:
                event = json.loads(data)
            except json.JSONDecodeError:
                continue
            last_event_at = time.monotonic()
            event_type = event.get("type")
            if event_type == "response.output_text.delta" and event.get("delta"):
                chunks.append(str(event["delta"]))
            elif event_type == "response.completed":
                text = extract_responses_output_text(event.get("response") or {})
                if text:
                    if not chunks:
                        chunks.append(text)
                if not chunks:
                    raise RuntimeError("Codex Responses completed without output text")
                done = True
                break
            elif event_type in {"response.failed", "response.incomplete"}:
                raise RuntimeError(f"Codex Responses ended with {event_type}: {_responses_event_error_text(event)}")
        if done:
            break
    if not chunks:
        raise RuntimeError("Codex Responses stream ended before producing output text")
    return "".join(chunks)


def _check_responses_watchdog(started_at: float, last_event_at: float, progress_timeout: float, total_timeout: float) -> None:
    now = time.monotonic()
    if total_timeout and now - started_at > total_timeout:
        raise requests.exceptions.ReadTimeout("Codex Responses SSE exceeded total timeout before completion")
    if progress_timeout and now - last_event_at > progress_timeout:
        raise requests.exceptions.ReadTimeout("Codex Responses SSE produced no progress event before idle timeout")


def _responses_event_error_text(event: dict[str, Any]) -> str:
    for key in ("error", "incomplete_details"):
        value = event.get(key)
        if value:
            return json.dumps(value, ensure_ascii=False)
    response = event.get("response")
    if isinstance(response, dict):
        for key in ("error", "incomplete_details", "status_details"):
            value = response.get(key)
            if value:
                return json.dumps(value, ensure_ascii=False)
    return "no details"


def codex_responses_stream_timeout(config_timeout: float) -> tuple[float, float]:
    return (
        codex_responses_connect_timeout(config_timeout),
        codex_responses_read_timeout(config_timeout),
    )


def codex_responses_connect_timeout(config_timeout: float) -> float:
    return _bounded_positive_timeout(
        CODEX_RESPONSES_CONNECT_TIMEOUT_ENV,
        DEFAULT_CODEX_RESPONSES_CONNECT_TIMEOUT_SECONDS,
        config_timeout,
    )


def codex_responses_read_timeout(config_timeout: float) -> float:
    return _bounded_positive_timeout(
        CODEX_RESPONSES_READ_TIMEOUT_ENV,
        DEFAULT_CODEX_RESPONSES_READ_TIMEOUT_SECONDS,
        config_timeout,
    )


def codex_responses_total_timeout(config_timeout: float) -> float:
    return _bounded_positive_timeout(
        CODEX_RESPONSES_TOTAL_TIMEOUT_ENV,
        config_timeout,
        config_timeout,
    )


def _bounded_positive_timeout(env_name: str, default: float, config_timeout: float) -> float:
    configured = _positive_float(os.getenv(env_name), default)
    upper_bound = _positive_float(str(config_timeout), configured)
    return min(configured, upper_bound)


def _positive_float(value: str | None, default: float) -> float:
    try:
        parsed = float(str(value).strip()) if value is not None else float(default)
    except (TypeError, ValueError):
        return float(default)
    if parsed <= 0:
        return float(default)
    return parsed


def _is_timeout_like_request_error(exc: requests.exceptions.RequestException) -> bool:
    if isinstance(exc, requests.exceptions.Timeout):
        return True
    return "timed out" in str(exc).lower()


def _run_with_thread_deadline(func, seconds: float, message: str):
    timeout = _positive_float(str(seconds), 0.0) if seconds else 0.0
    if timeout <= 0:
        return func()

    results: queue.Queue[tuple[bool, Any]] = queue.Queue(maxsize=1)

    def _runner() -> None:
        try:
            results.put((True, func()))
        except BaseException as exc:
            results.put((False, exc))

    worker = threading.Thread(target=_runner, daemon=True)
    worker.start()
    worker.join(timeout)
    if worker.is_alive():
        raise TimeoutError(message)
    ok, value = results.get_nowait()
    if ok:
        return value
    raise value


def extract_responses_output_text(response: dict[str, Any]) -> str:
    if response.get("output_text"):
        return str(response["output_text"])
    texts: list[str] = []
    for item in response.get("output") or []:
        if not isinstance(item, dict):
            continue
        for content in item.get("content") or []:
            if isinstance(content, dict) and content.get("text"):
                texts.append(str(content["text"]))
    return "".join(texts)


def codex_responses_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    if not base.endswith("/v1"):
        raise RuntimeError("OpenAI-compatible Responses endpoint must end with /v1")
    return f"{base}/responses"
