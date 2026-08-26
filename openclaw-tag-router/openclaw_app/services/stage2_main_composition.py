"""Canonical current-main composition boundary for the isolated Stage-2 service.

This module deliberately keeps Stage-2 separate from the large Media HTTP
server while reusing the current account, workspace, tenant, Binding, and
production-writer authorities.  It never treats the historical release copy as
source code.
"""

from __future__ import annotations

import importlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from ..stage2_server_app import Stage2ServerApp
from .stage2_contract_validator import contract_digest, validate_contract_file
from .stage2_gateway import Stage2GatewayError
from .stage2_production import Stage2ProductionAssemblyError


DEFAULT_STAGE2_CONTRACT = (
    Path(__file__).resolve().parents[1] / "contracts" / "stage2_writer_contract.json"
)
REQUIRED_STAGE2_ENDPOINTS = frozenset(
    {"/stage2/personal", "/stage2/organization"}
)


@dataclass(frozen=True, slots=True)
class Stage2ContractIdentity:
    path: str
    digest: str
    status: str
    runtime_integration: bool
    endpoints: tuple[str, ...]
    acceptance_mode: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "digest": self.digest,
            "status": self.status,
            "runtimeIntegration": self.runtime_integration,
            "endpoints": list(self.endpoints),
            "acceptanceMode": self.acceptance_mode,
        }


_ALIAS_GROUPS: tuple[tuple[str, ...], ...] = (
    ("operation_id", "operationId"),
    ("idempotency_key", "idempotencyKey"),
    ("confirmed_by", "confirmedBy"),
    ("confirmation_ref", "confirmationRef"),
    ("source_rows", "sourceRows"),
    ("platform_constraints", "platformConstraints"),
)


def reject_ambiguous_stage2_aliases(payload: Mapping[str, Any]) -> None:
    """Reject ambiguous snake/camel input before any writer side effect."""

    for aliases in _ALIAS_GROUPS:
        supplied = [name for name in aliases if name in payload]
        if len(supplied) > 1:
            raise Stage2GatewayError(
                "invalid_request",
                "request contains conflicting field aliases",
                status=400,
            )


class StrictStage2Gateway:
    """Production wrapper that closes transport alias ambiguity globally."""

    def __init__(self, delegate: Any) -> None:
        if delegate is None or not callable(getattr(delegate, "run", None)):
            raise TypeError("delegate must expose run(mode, payload)")
        self._delegate = delegate

    @property
    def delegate(self) -> Any:
        return self._delegate

    def run(self, mode: str, payload: Mapping[str, Any] | None) -> dict[str, Any]:
        if not isinstance(payload, Mapping):
            raise Stage2GatewayError(
                "invalid_request", "JSON request body must be an object", status=400
            )
        reject_ambiguous_stage2_aliases(payload)
        return self._delegate.run(mode, payload)


def _load_contract_mapping(path: Path) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Stage2ProductionAssemblyError(
            "production_contract_unavailable",
            "the Stage-2 contract cannot be loaded",
        ) from exc
    if not isinstance(value, Mapping):
        raise Stage2ProductionAssemblyError(
            "production_contract_invalid", "the Stage-2 contract must be an object"
        )
    return value


def _contract_endpoints(contract: Mapping[str, Any]) -> tuple[str, ...]:
    result: list[str] = []
    raw = contract.get("endpoints")
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, str):
                result.append(item)
            elif isinstance(item, Mapping) and isinstance(item.get("path"), str):
                result.append(str(item["path"]))
    return tuple(sorted(set(result)))


def load_stage2_contract_identity(
    path: str | Path = DEFAULT_STAGE2_CONTRACT,
    *,
    acceptance_mode: bool = False,
) -> Stage2ContractIdentity:
    """Validate a persisted contract and enforce production/acceptance state."""

    contract_path = Path(path).expanduser().resolve()
    validate_contract_file(contract_path)
    contract = _load_contract_mapping(contract_path)
    status = str(contract.get("status") or "").strip().lower()
    runtime_integration = contract.get("runtimeIntegration") is True
    endpoints = _contract_endpoints(contract)

    if acceptance_mode:
        if status not in {"provisional", "accepted"}:
            raise Stage2ProductionAssemblyError(
                "production_contract_not_accepted",
                "Stage-2 acceptance mode requires a provisional or accepted contract",
            )
    elif (
        status != "accepted"
        or not runtime_integration
        or not REQUIRED_STAGE2_ENDPOINTS.issubset(endpoints)
    ):
        raise Stage2ProductionAssemblyError(
            "production_contract_not_accepted",
            "Stage-2 production requires an accepted integrated contract",
        )

    return Stage2ContractIdentity(
        path=str(contract_path),
        digest=contract_digest(contract),
        status=status,
        runtime_integration=runtime_integration,
        endpoints=endpoints,
        acceptance_mode=acceptance_mode,
    )


def _load_factory(reference: str) -> Callable[..., Any]:
    module_name, separator, attribute = reference.partition(":")
    if separator != ":" or not module_name or not attribute:
        raise Stage2ProductionAssemblyError(
            "production_factory_invalid",
            "Stage-2 factory reference must use module:function",
        )
    try:
        module = importlib.import_module(module_name)
        factory = getattr(module, attribute)
    except (ImportError, AttributeError) as exc:
        raise Stage2ProductionAssemblyError(
            "production_factory_unavailable", "Stage-2 factory cannot be loaded"
        ) from exc
    if not callable(factory):
        raise Stage2ProductionAssemblyError(
            "production_factory_invalid", "Stage-2 factory is not callable"
        )
    return factory


def build_main_stage2_app(
    *,
    settings_path: str,
    contract_path: str | Path = DEFAULT_STAGE2_CONTRACT,
    factory_reference: str = (
        "openclaw_app.services.stage2_production_factory:"
        "build_production_stage2_gateway"
    ),
    acceptance_mode: bool = False,
) -> tuple[Stage2ServerApp, Stage2ContractIdentity]:
    """Build a Git-main-owned Stage-2 app and fail on contract replacement."""

    before = load_stage2_contract_identity(
        contract_path, acceptance_mode=acceptance_mode
    )
    factory = _load_factory(factory_reference)
    gateway = factory(
        settings_path=str(settings_path),
        contract_path=before.path,
        contract_digest=before.digest,
    )
    after = load_stage2_contract_identity(
        before.path, acceptance_mode=acceptance_mode
    )
    if after.digest != before.digest:
        raise Stage2ProductionAssemblyError(
            "production_contract_changed",
            "Stage-2 contract changed during production assembly",
        )
    strict_gateway = StrictStage2Gateway(gateway)
    return Stage2ServerApp(settings_path, stage2_gateway=strict_gateway), before


__all__ = [
    "DEFAULT_STAGE2_CONTRACT",
    "REQUIRED_STAGE2_ENDPOINTS",
    "Stage2ContractIdentity",
    "StrictStage2Gateway",
    "build_main_stage2_app",
    "load_stage2_contract_identity",
    "reject_ambiguous_stage2_aliases",
]
