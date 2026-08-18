from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel

from common.llm_client import generate_json_from_parts as common_generate_json_from_parts
from common.llm_settings import LLMProviderSettings
from common.llm_validation import LLMValidationContract, register_llm_validation_contract, validate_llm_payload

from .config import ConfigError, ViralDeconstructConfig
from .schemas import validate_schema


def _validate_deconstruction_payload(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    schema = context.get("schema")
    post_validate = context.get("post_validate")
    validated = validate_schema(payload, schema) if schema else payload
    return post_validate(validated) if post_validate else validated


DECONSTRUCTION_VALIDATION_CONTRACT = register_llm_validation_contract(
    LLMValidationContract(
        contract_id="selfmedia.deconstruction.output.v1",
        profile="strict_structured",
        validator=_validate_deconstruction_payload,
    )
)


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

    validation_context = {"schema": schema, "post_validate": post_validate}
    last_error = ""
    request_parts = list(parts)
    for attempt in range(max_retries + 1):
        try:
            payload = _generate_json_once(request_parts, config)
            return validate_llm_payload(
                payload,
                DECONSTRUCTION_VALIDATION_CONTRACT,
                context=validation_context,
            ).payload
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


def common_generate_json_once(parts: list[dict[str, Any]], settings: LLMProviderSettings) -> dict[str, Any]:
    return common_generate_json_from_parts(
        parts,
        settings,
        max_retries=0,
        validation_contract=DECONSTRUCTION_VALIDATION_CONTRACT,
    )


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
        bin=config.bin,
        agent=config.agent,
        cwd=config.cwd,
        codex_home=config.codex_home,
    )
