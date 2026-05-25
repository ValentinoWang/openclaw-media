from __future__ import annotations

import json
import base64
import re
from pathlib import Path
from typing import Any

import requests
from pydantic import BaseModel

from common.llm_client import generate_json_once as common_generate_json_once
from common.llm_client import parse_json_object_text as common_parse_json_object_text
from common.llm_settings import LLMProviderSettings

from .config import ConfigError, ViralDeconstructConfig
from .schemas import NativeVideoObservation, validate_schema


def ensure_llm_provider_available(config: ViralDeconstructConfig) -> None:
    if not config.api_key:
        raise ConfigError("缺少可用 LLM Provider：config/openclaw_bots.json providers.main_llm.api_key 未配置")
    if not config.base_url or not config.model or not config.llm_api_type:
        raise ConfigError("缺少可用 LLM Provider：config/openclaw_bots.json providers.main_llm 未完整配置")


def ensure_qwen_provider_available(config: ViralDeconstructConfig) -> None:
    if not config.qwen_api_key:
        raise ConfigError("缺少 Qwen-Omni Provider：config/openclaw_bots.json providers.qwen.api_key 未配置")
    if not config.qwen_base_url or not config.qwen_model:
        raise ConfigError("缺少 Qwen-Omni Provider：config/openclaw_bots.json providers.qwen 未完整配置")


def generate_json(
    parts: list[dict[str, Any]],
    config: ViralDeconstructConfig,
    schema: type[BaseModel] | None = None,
    post_validate: Any | None = None,
    max_retries: int = 2,
) -> dict[str, Any]:
    ensure_llm_provider_available(config)

    last_error = ""
    request_parts = list(parts)
    for attempt in range(max_retries + 1):
        try:
            payload = _generate_json_once(request_parts, config)
            payload = validate_schema(payload, schema) if schema else payload
            if post_validate:
                payload = post_validate(payload)
            return payload
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            last_error = str(exc)
            if attempt >= max_retries:
                break
            request_parts = list(parts) + [
                {
                    "text": (
                        "上一次输出没有通过代码 JSON/schema 校验。"
                        f"错误：{last_error}\n"
                        "请只返回合法 JSON，不要 Markdown，不要解释，并补齐所有必填字段。"
                    )
                }
            ]
    raise RuntimeError(f"LLM 输出 JSON 校验失败：{last_error}")


def _generate_json_once(parts: list[dict[str, Any]], config: ViralDeconstructConfig) -> dict[str, Any]:
    try:
        return common_generate_json_once(parts, _provider_settings(config))
    except RuntimeError as exc:
        raise ConfigError(str(exc)) from exc


def _provider_settings(config: ViralDeconstructConfig) -> LLMProviderSettings:
    return LLMProviderSettings(
        model=config.model,
        base_url=config.base_url,
        api_key=config.api_key,
        api_type=config.llm_api_type,
        timeout=config.timeout,
        thinking=config.thinking,
    )


def _generate_json_once_chat_completions(parts: list[dict[str, Any]], config: ViralDeconstructConfig) -> dict[str, Any]:
    text_parts = []
    for part in parts:
        if "text" in part:
            text_parts.append({"type": "text", "text": part["text"]})
        elif "image_data" in part:
            data = part["image_data"]
            text_parts.append({
                "type": "image_url",
                "image_url": {"url": f"data:{data.get('mime_type','image/jpeg')};base64,{data.get('data','')}"},
            })
        elif "inline_data" in part:
            data = part["inline_data"]
            text_parts.append({
                "type": "image_url",
                "image_url": {"url": f"data:{data.get('mime_type','image/png')};base64,{data.get('data','')}"},
            })
        # viral deconstruct does not pass raw video to OpenAI directly; runner extracts video frames first.

    resp = requests.post(
        f"{config.base_url}/chat/completions",
        headers={"Authorization": f"Bearer {config.api_key}", "Content-Type": "application/json"},
        json={
            "model": config.model,
            "messages": [{"role": "user", "content": text_parts}],
            "response_format": {"type": "json_object"},
        },
        timeout=config.timeout,
    )
    resp.raise_for_status()
    payload = resp.json()
    content = payload["choices"][0]["message"]["content"]
    parsed = common_parse_json_object_text(content)
    if not isinstance(parsed, dict):
        raise ValueError("LLM JSON 顶层必须是 object")
    return parsed


def _generate_json_once_codex_responses(parts: list[dict[str, Any]], config: ViralDeconstructConfig) -> dict[str, Any]:
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
    body = {
        "model": config.model,
        "instructions": "你是 JSON 输出引擎。必须只输出合法 JSON object，不要 Markdown，不要解释。",
        "input": [{"role": "user", "content": content}],
        "stream": True,
        "store": False,
    }
    if config.thinking:
        body["reasoning"] = {"effort": config.thinking}
    resp = requests.post(
        _codex_responses_url(config.base_url),
        headers={"Authorization": f"Bearer {config.api_key}", "Content-Type": "application/json"},
        json=body,
        timeout=config.timeout,
        stream=True,
    )
    resp.raise_for_status()
    return common_parse_json_object_text(_collect_responses_sse_text(resp))


def _codex_responses_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/codex"):
        return f"{base}/responses"
    return f"{base}/codex/responses"


def generate_native_video_observation(
    video_path: str,
    caption: str,
    stats: dict[str, Any],
    config: ViralDeconstructConfig,
) -> dict[str, Any]:
    ensure_qwen_provider_available(config)
    path = Path(video_path)
    if not path.exists() or not path.is_file() or path.stat().st_size <= 0:
        raise ValueError(f"原生视频观察失败：视频文件不存在或为空 {video_path}")
    # Qwen-Omni OpenAI-compatible examples use data:;base64,<video> for local videos.
    data_url = f"data:;base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"
    prompt = (
        "你是短视频音视频观察模型。请只输出严格 JSON，字段必须包含："
        "timeline_summary, visual_events, audio_events, speech_summary, "
        "music_or_sound_effects, hook_moments, uncertainty_notes。\n"
        "只做观察，不做最终爆款拆解，不写飞书字段。\n"
        f"原文案：{caption or '未抓取'}\n"
        f"互动数据：{json.dumps(stats or {}, ensure_ascii=False)}"
    )
    body = {
        "model": config.qwen_model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "video_url", "video_url": {"url": data_url, "fps": config.qwen_fps}},
                ],
            }
        ],
        "stream": True,
        "stream_options": {"include_usage": True},
        "modalities": ["text"],
    }
    resp = requests.post(
        f"{config.qwen_base_url}/chat/completions",
        headers={"Authorization": f"Bearer {config.qwen_api_key}", "Content-Type": "application/json"},
        json=body,
        timeout=config.timeout,
        stream=True,
    )
    resp.raise_for_status()
    content = _collect_sse_delta_content(resp)
    parsed = common_parse_json_object_text(content)
    if not isinstance(parsed, dict):
        raise ValueError("Qwen-Omni observation JSON 顶层必须是 object")
    return validate_schema(parsed, NativeVideoObservation)


def _parse_json_object_text(text: str) -> dict[str, Any]:
    cleaned = text.strip()
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


def _collect_sse_delta_content(resp: requests.Response) -> str:
    chunks: list[str] = []
    for raw_line in resp.iter_lines(decode_unicode=True):
        if not raw_line:
            continue
        line = raw_line.strip()
        if not line.startswith("data:"):
            continue
        data = line[len("data:"):].strip()
        if data == "[DONE]":
            break
        try:
            payload = json.loads(data)
        except json.JSONDecodeError:
            continue
        for choice in payload.get("choices") or []:
            delta = choice.get("delta") or {}
            content = delta.get("content")
            if content:
                chunks.append(str(content))
    result = "".join(chunks).strip()
    if not result:
        raise ValueError("Qwen-Omni observation 返回空文本")
    return result


def _collect_responses_sse_text(resp: requests.Response) -> str:
    chunks: list[str] = []
    completed_response: dict[str, Any] | None = None
    for raw_line in resp.iter_lines(decode_unicode=True):
        if not raw_line:
            continue
        line = raw_line.decode("utf-8", errors="ignore") if isinstance(raw_line, bytes) else str(raw_line)
        line = line.strip()
        if not line.startswith("data:"):
            continue
        data = line[len("data:"):].strip()
        if data == "[DONE]":
            break
        try:
            payload = json.loads(data)
        except json.JSONDecodeError:
            continue
        event_type = payload.get("type")
        if event_type == "response.output_text.delta" and payload.get("delta"):
            chunks.append(str(payload["delta"]))
        elif isinstance(payload.get("delta"), str):
            chunks.append(str(payload["delta"]))
        elif event_type == "response.completed":
            completed_response = payload.get("response") if isinstance(payload.get("response"), dict) else None
    result = "".join(chunks).strip()
    if result:
        return result
    if completed_response:
        text = _extract_responses_output_text(completed_response)
        if text:
            return text
    raise ValueError("Codex Responses 返回空文本")


def _extract_responses_output_text(response: dict[str, Any]) -> str:
    chunks: list[str] = []
    for item in response.get("output") or []:
        for content in item.get("content") or []:
            if content.get("type") in {"output_text", "text"} and content.get("text"):
                chunks.append(str(content["text"]))
    return "".join(chunks).strip()
