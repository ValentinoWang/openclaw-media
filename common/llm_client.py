from __future__ import annotations

import json
import re
import time
from typing import Any

import requests

from .llm_settings import API_TYPE_CHAT_COMPLETIONS, API_TYPE_CODEX_RESPONSES, LLMProviderSettings


def ensure_llm_provider_available(config: LLMProviderSettings) -> None:
    if not config.api_key:
        raise RuntimeError("缺少可用 LLM Provider：SELFMEDIA_CLEAN_LLM_API_KEY 未配置")
    if not config.base_url or not config.model or not config.api_type:
        raise RuntimeError("缺少可用 LLM Provider：SELFMEDIA_CLEAN_LLM_MODEL / SELFMEDIA_CLEAN_LLM_BASE_URL / SELFMEDIA_CLEAN_LLM_API_TYPE 未完整配置")


def generate_json_from_parts(
    parts: list[dict[str, Any]],
    config: LLMProviderSettings,
    *,
    max_retries: int = 2,
    error_prefix: str = "LLM 输出 JSON 校验失败",
    retry_text: str = "上一次输出没有通过 JSON 校验：{error}\n请只返回合法 JSON object，不要 Markdown。",
    instructions: str = "你是 JSON 输出引擎。必须只输出合法 JSON object，不要 Markdown，不要解释。",
) -> dict[str, Any]:
    ensure_llm_provider_available(config)
    last_error = ""
    request_parts = list(parts)
    for attempt in range(max_retries + 1):
        try:
            return generate_json_once(request_parts, config, instructions=instructions)
        except Exception as exc:
            last_error = str(exc)
            if attempt >= max_retries:
                break
            request_parts = list(parts) + [{"text": retry_text.format(error=last_error)}]
            time.sleep(0.5)
    raise RuntimeError(f"{error_prefix}：{last_error}")


def generate_json_once(
    parts: list[dict[str, Any]],
    config: LLMProviderSettings,
    *,
    instructions: str = "你是 JSON 输出引擎。必须只输出合法 JSON object，不要 Markdown，不要解释。",
) -> dict[str, Any]:
    if config.api_type == API_TYPE_CODEX_RESPONSES:
        return _generate_json_codex_responses(parts, config, instructions=instructions)
    if config.api_type != API_TYPE_CHAT_COMPLETIONS:
        raise RuntimeError(f"不支持的 LLM API 类型：{config.api_type}")
    return _generate_json_chat_completions(parts, config)


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
    response = requests.post(
        f"{config.base_url}/chat/completions",
        headers={"Authorization": f"Bearer {config.api_key}", "Content-Type": "application/json"},
        json={
            "model": config.model,
            "messages": [{"role": "user", "content": content}],
            "response_format": {"type": "json_object"},
        },
        timeout=config.timeout,
    )
    response.raise_for_status()
    payload = response.json()
    return parse_json_object_text(payload["choices"][0]["message"]["content"])


def _generate_json_codex_responses(
    parts: list[dict[str, Any]],
    config: LLMProviderSettings,
    *,
    instructions: str,
) -> dict[str, Any]:
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
    body: dict[str, Any] = {
        "model": config.model,
        "instructions": instructions,
        "input": [{"role": "user", "content": content}],
        "stream": True,
        "store": False,
    }
    if config.thinking:
        body["reasoning"] = {"effort": config.thinking}
    response = requests.post(
        codex_responses_url(config.base_url),
        headers={"Authorization": f"Bearer {config.api_key}", "Content-Type": "application/json"},
        json=body,
        timeout=config.timeout,
        stream=True,
    )
    response.raise_for_status()
    return parse_json_object_text(collect_responses_sse_text(response))


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


def collect_responses_sse_text(resp: requests.Response) -> str:
    chunks: list[str] = []
    for raw_line in resp.iter_lines(decode_unicode=True):
        if not raw_line:
            continue
        if isinstance(raw_line, bytes):
            line = raw_line.decode("utf-8", errors="ignore").strip()
        else:
            line = str(raw_line).strip()
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            break
        try:
            event = json.loads(data)
        except json.JSONDecodeError:
            continue
        event_type = event.get("type")
        if event_type == "response.output_text.delta" and event.get("delta"):
            chunks.append(str(event["delta"]))
        elif event_type == "response.completed":
            text = extract_responses_output_text(event.get("response") or {})
            if text:
                chunks.append(text)
    return "".join(chunks)


def extract_responses_output_text(response: dict[str, Any]) -> str:
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
    if base.endswith("/codex"):
        return f"{base}/responses"
    return f"{base}/codex/responses"
