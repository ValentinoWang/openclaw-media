from __future__ import annotations

from .validators import LLMIOContractError


def assert_generation_write_policy(*, generation_source: str, llm_ok: bool, validation_ok: bool) -> None:
    if generation_source == "llm" and not llm_ok:
        raise LLMIOContractError("LLM generation failed; writer may only persist pending/manual status")
    if not validation_ok:
        raise LLMIOContractError("platform validation failed; writer may only persist pending/manual status")
