from __future__ import annotations

import json
import os
import subprocess
from typing import Any

from pydantic import BaseModel

from common.bot_llm_config import bot_runtime, openclaw_subprocess_env
from common.llm_client import generate_json_once as common_generate_json_once
from common.llm_client import parse_json_object_text
from common.llm_settings import LLMProviderSettings

from .config import ConfigError, ViralDeconstructConfig
from .schemas import validate_schema


def ensure_llm_provider_available(config: ViralDeconstructConfig) -> None:
    if not config.api_key:
        raise ConfigError("缺少可用 LLM Provider：config/openclaw_bots.json 当前 profile provider api_key 未配置")
    if not config.base_url or not config.model or not config.llm_api_type:
        raise ConfigError("缺少可用 LLM Provider：config/openclaw_bots.json 当前 profile provider 未完整配置")


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
        except (json.JSONDecodeError, KeyError, ValueError, ConfigError) as exc:
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
    if _use_openclaw_agent(parts, config):
        return _generate_json_openclaw_agent(parts, config)
    try:
        return common_generate_json_once(parts, _provider_settings(config))
    except RuntimeError as exc:
        raise ConfigError(str(exc)) from exc


def _use_openclaw_agent(parts: list[dict[str, Any]], config: ViralDeconstructConfig) -> bool:
    has_non_text = any("image_data" in part or "inline_data" in part or "audio_data" in part for part in parts)
    if config.llm_api_type == "openclaw_agent":
        if has_non_text:
            raise ConfigError("OpenClaw agent JSON adapter 只支持文本 parts；含图片/音频的拆解主 LLM 必须使用 direct Responses")
        return True
    return (
        not has_non_text
        and os.getenv("OPENCLAW_DECONSTRUCT_TEXT_LLM_VIA_AGENT", "").strip().lower() in {"1", "true", "yes", "on"}
    )


def _generate_json_openclaw_agent(parts: list[dict[str, Any]], config: ViralDeconstructConfig) -> dict[str, Any]:
    runtime = bot_runtime("media")
    bin_path = config.bin or runtime.bin
    agent = config.agent or runtime.agent
    cwd = config.cwd or runtime.cwd
    codex_home = config.codex_home or runtime.codex_home
    thinking = config.thinking or os.getenv("OPENCLAW_DECONSTRUCT_AGENT_THINKING", "").strip() or "low"
    timeout = int(max(1, float(config.timeout or runtime.timeout or 600)))
    message = "\n\n".join(str(part.get("text") or "") for part in parts if "text" in part)
    command = [
        bin_path,
        "agent",
        "--agent",
        agent,
        "--message",
        message,
        "--thinking",
        thinking,
        "--json",
        "--timeout",
        str(timeout),
    ]
    proc = subprocess.run(
        command,
        cwd=cwd or None,
        env=openclaw_subprocess_env(codex_home),
        text=True,
        capture_output=True,
        timeout=timeout + 30,
        check=False,
    )
    if proc.returncode != 0:
        raise ConfigError((proc.stderr or proc.stdout or f"openclaw agent failed: exit={proc.returncode}")[-2000:])
    try:
        payload = json.loads(proc.stdout)
        text = str((((payload.get("result") or {}).get("payloads") or [{}])[0] or {}).get("text") or "")
    except (json.JSONDecodeError, AttributeError, IndexError) as exc:
        raise ConfigError(f"OpenClaw agent JSON 输出格式异常：{str(exc)}") from exc
    if not text.strip():
        raise ConfigError("OpenClaw agent 没有返回 JSON 文本")
    return parse_json_object_text(text)


def _provider_settings(config: ViralDeconstructConfig) -> LLMProviderSettings:
    return LLMProviderSettings(
        model=config.model,
        base_url=config.base_url,
        api_key=config.api_key,
        api_type=config.llm_api_type,
        timeout=config.timeout,
        thinking=config.thinking,
        bin=config.bin,
        agent=config.agent,
        cwd=config.cwd,
        codex_home=config.codex_home,
    )
