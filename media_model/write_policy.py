from __future__ import annotations

from .validators import LLMIOContractError


def assert_generation_write_policy(*, generation_source: str, llm_ok: bool, validation_ok: bool) -> None:
    # validation_ok is a plain bool this module does not compute itself.
    # Platform-draft field validation (title/tags/platform rules) is owned
    # by selfmedia.creation.platform_validator.validate_platform_draft --
    # callers should pass its ValidationResult.ok here (dedup audit cluster
    # SV-09 removed media_model's own weaker copy, platform_validation_report).
    if generation_source == "llm" and not llm_ok:
        raise LLMIOContractError("LLM generation failed; writer may only persist pending/manual status")
    if not validation_ok:
        raise LLMIOContractError("platform validation failed; writer may only persist pending/manual status")
