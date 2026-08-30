from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from common.llm_client import ensure_llm_provider_available as common_ensure_llm_provider_available
from common.llm_client import generate_json_from_parts as common_generate_json_from_parts
from common.llm_settings import LLMProviderSettings
from common.llm_validation import LLMValidationContract, register_llm_validation_contract
from common.model_transport_context import ModelTransportError

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
    # dedup(llm-wrapper-05): delegate the actual precheck to the common
    # implementation (common/llm_client.py:ensure_llm_provider_available),
    # which is the only version that recognizes tenant model transport and
    # the openclaw_agent api_type. This wrapper exists solely to preserve the
    # historical ConfigError contract that runner.py's four fail-fast call
    # sites and tests/test_hard_guards.py::test_missing_llm_key_fails_fast_before_part1
    # depend on -- common raises a bare RuntimeError.
    try:
        common_ensure_llm_provider_available(_provider_settings(config))
    except RuntimeError as exc:
        raise ConfigError(str(exc)) from exc


def generate_json(
    parts: list[dict[str, Any]],
    config: ViralDeconstructConfig,
    schema: type[BaseModel] | None = None,
    post_validate: Any | None = None,
    max_retries: int = 2,
) -> dict[str, Any]:
    ensure_llm_provider_available(config)

    # Delegate JSON generation, retrying, and schema/post-validation entirely to
    # the shared common.llm_client.generate_json_from_parts implementation:
    # - It carries the authoritative `except ModelTransportError: raise` guard
    #   so a terminal transport failure is never silently retried.
    # - It applies the same DECONSTRUCTION_VALIDATION_CONTRACT + {"schema":
    #   schema, "post_validate": post_validate} context this module used to
    #   apply itself in its own retry loop, so schema/post-validation coverage
    #   is unchanged.
    try:
        return common_generate_json_from_parts(
            parts,
            _provider_settings(config),
            max_retries=max_retries,
            validation_contract=DECONSTRUCTION_VALIDATION_CONTRACT,
            validation_context={"schema": schema, "post_validate": post_validate},
            error_prefix="LLM 输出 JSON 校验失败",
        )
    except ModelTransportError:
        # Terminal transport outcome: callers must see it as-is, never masked
        # as a retryable ConfigError.
        raise
    except RuntimeError as exc:
        # Preserve the historical ConfigError contract for callers
        # (multi_signal_contract.py, runner.py, evidence/modality_dag.py) that
        # only expect ConfigError out of this module, without re-entering any
        # retry loop for the exception being wrapped here.
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
