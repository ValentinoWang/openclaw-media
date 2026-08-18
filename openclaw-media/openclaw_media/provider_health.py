"""Sanitized local provider health and capability conformance receipt."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict

from .credentials import CredentialStore
from .provider_adapter import (
    ProviderAdapter,
    ProviderAdapterError,
    StructuredResult,
    VisionImage,
)
from .provider_config import ProviderConfig, ProviderHealth


Capability = Literal["text", "vision", "structured"]
_CAPABILITIES: tuple[Capability, ...] = ("text", "vision", "structured")
_PUBLIC_FAILURES = {
    "adapter_unavailable",
    "credential_unavailable",
    "invalid_response",
    "invalid_structured_response",
    "provider_unavailable",
}


class ProviderCheckResult(BaseModel):
    """One content-free capability result."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    capability: Capability
    passed: bool
    code: str


class ProviderHealthReceipt(BaseModel):
    """Local, immutable receipt that never contains endpoint, token, or output."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider_type: Literal["openai_compatible"]
    model_label: str
    health: ProviderHealth
    checked_at: datetime
    checks: tuple[ProviderCheckResult, ...]
    receipt_id: str


class _HealthProbe(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    ok: Literal[True]


def _failure_code(exc: Exception) -> str:
    if isinstance(exc, ProviderAdapterError) and exc.code in _PUBLIC_FAILURES:
        return exc.code
    return "provider_unavailable"


def _receipt(
    config: ProviderConfig,
    checked_at: datetime,
    checks: tuple[ProviderCheckResult, ...],
) -> ProviderHealthReceipt:
    health = (
        ProviderHealth.HEALTHY
        if all(check.passed for check in checks)
        else ProviderHealth.UNAVAILABLE
    )
    identity_payload = {
        "provider_type": config.provider_type,
        "model_label": config.model_label,
        "health": health.value,
        "checked_at": checked_at.isoformat(),
        "checks": [check.model_dump(mode="json") for check in checks],
    }
    digest = sha256(
        json.dumps(
            identity_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return ProviderHealthReceipt(
        **identity_payload,
        receipt_id=f"sha256:{digest}",
    )


def check_provider_health(
    config: ProviderConfig,
    credentials: CredentialStore,
    *,
    checked_at: datetime | None = None,
    adapter_factory: Callable[..., ProviderAdapter] | None = None,
) -> ProviderHealthReceipt:
    """Run the canonical adapter capability matrix and return only safe metadata."""

    if checked_at is None:
        checked_at = datetime.now(timezone.utc)
    elif not isinstance(checked_at, datetime) or checked_at.tzinfo is None:
        raise ValueError("invalid_checked_at")
    checked_at = checked_at.astimezone(timezone.utc)
    factory = ProviderAdapter if adapter_factory is None else adapter_factory
    try:
        adapter = factory(config.model_copy(deep=True), credentials, max_attempts=1)
    except Exception:
        failed = tuple(
            ProviderCheckResult(
                capability=capability,
                passed=False,
                code="provider_unavailable",
            )
            for capability in _CAPABILITIES
        )
        return _receipt(config, checked_at, failed)

    checks: list[ProviderCheckResult] = []
    for capability in _CAPABILITIES:
        try:
            if capability == "text":
                adapter.complete_text("Reply with a short acknowledgement.")
            elif capability == "vision":
                adapter.complete_vision(
                    "Describe whether an image is present.",
                    (VisionImage(media_type="image/png", data=b"health-probe"),),
                )
            else:
                result = adapter.complete_structured(
                    "Return JSON with ok set to true.", _HealthProbe
                )
                if not isinstance(result, StructuredResult) or not isinstance(
                    result.value, _HealthProbe
                ):
                    raise ProviderAdapterError("invalid_response")
            checks.append(
                ProviderCheckResult(capability=capability, passed=True, code="ok")
            )
        except Exception as exc:
            checks.append(
                ProviderCheckResult(
                    capability=capability,
                    passed=False,
                    code=_failure_code(exc),
                )
            )
    return _receipt(config, checked_at, tuple(checks))


__all__ = ["ProviderCheckResult", "ProviderHealthReceipt", "check_provider_health"]
