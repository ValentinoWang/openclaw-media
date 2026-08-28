"""DeepMath Daily resource ownership and exact-name resolution.

This module is deliberately independent from the legacy Daily reminder
configuration.  It resolves only resources explicitly tagged as belonging to
the DeepMath tenant; an absent or ambiguous resource is a result requiring
approval/manual selection, never a fallback to an older tenant.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import urlparse
import re


DEEP_MATH_TENANT_KEY = "deepmath"
DEEP_MATH_FEISHU_ACCOUNT_ID = "deepmath"
BASE_NAME = "DeepMath CEO Thinking"
TASKLIST_NAME = "DeepMath CEO Actions"
CALENDAR_NAME = "DeepMath CEO Calendar"
DEFAULT_TIMEZONE = "Asia/Shanghai"
RESOURCE_CONFIG_VERSION = 1
RESOURCE_CONFIG_FILENAME = "deepmath_ceo_thinking_resources.json"
_BITABLE_TOKEN = re.compile(r"[A-Za-z0-9_-]{8,160}\Z")
_FEISHU_HOSTS = ("feishu.cn", "larksuite.com", "larkoffice.com")


class DeepMathResourceContractError(ValueError):
    """Configuration or candidate data would violate tenant isolation."""


def default_resource_config_path() -> Path:
    """Locate the bundled resource contract without depending on a deploy root."""

    return Path(__file__).resolve().parents[2] / "config" / RESOURCE_CONFIG_FILENAME


def resolve_resource_config_path(configured_path: Any, *, settings_path: str | Path) -> Path:
    """Resolve an explicit path relative to its settings file, without fallback."""

    raw_path = str(configured_path or "").strip()
    if not raw_path:
        raise DeepMathResourceContractError("explicit DeepMath resource config path is required")
    path = Path(raw_path).expanduser()
    return path if path.is_absolute() else Path(settings_path).parent / path


@dataclass(frozen=True)
class DeepMathResourceSpec:
    kind: str
    name: str
    resource_id: str | None
    writable: bool
    status: str
    reason: str = ""


@dataclass(frozen=True)
class DeepMathResourceApprovalCandidate:
    """Deterministic approval-record input for one discovery result."""

    object_type: str
    resource_kind: str
    resource_name: str
    candidate_action: str
    resource_id: str | None
    approval_status: str
    requires_manual_selection: bool
    reason: str = ""


@dataclass(frozen=True)
class DeepMathResourceConfig:
    tenant_key: str
    base_name: str
    tasklist_name: str
    calendar_name: str
    timezone: str
    base_id: str | None = None
    tasklist_id: str | None = None
    calendar_id: str | None = None
    base_url: str | None = None
    tenant_proof: str | None = None

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "DeepMathResourceConfig":
        if str(value.get("tenant_key") or "") != DEEP_MATH_TENANT_KEY:
            raise DeepMathResourceContractError("tenant_key must be deepmath")
        expected = {
            "base_name": BASE_NAME,
            "tasklist_name": TASKLIST_NAME,
            "calendar_name": CALENDAR_NAME,
            "timezone": DEFAULT_TIMEZONE,
        }
        for key, expected_value in expected.items():
            if str(value.get(key) or "") != expected_value:
                raise DeepMathResourceContractError(f"{key} must equal {expected_value}")
        forbidden = {"fallback", "legacy", "compat", "old_resource", "old_organization"}
        if forbidden.intersection(value):
            raise DeepMathResourceContractError("legacy/fallback resource keys are forbidden")
        tenant_proof = _optional_id(value.get("tenant_proof"))
        if tenant_proof == DEEP_MATH_TENANT_KEY:
            raise DeepMathResourceContractError(
                "tenant_proof must be the Feishu tenant_key returned by API readback, not the symbolic deepmath label"
            )
        binding_values = {
            "base_id": _optional_id(value.get("base_id")),
            "tasklist_id": _optional_id(value.get("tasklist_id")),
            "calendar_id": _optional_id(value.get("calendar_id")),
            "base_url": _optional_id(value.get("base_url")),
            "tenant_proof": tenant_proof,
        }
        if any(binding_values.values()) and not all(binding_values.values()):
            raise DeepMathResourceContractError("DeepMath resource binding must be complete and atomic")
        validated_base_url = binding_values["base_url"]
        if validated_base_url:
            base_token = parse_explicit_bitable_url(validated_base_url)
            if binding_values["base_id"] != base_token:
                raise DeepMathResourceContractError("base_id must match the token in base_url")
        return cls(
            tenant_key=DEEP_MATH_TENANT_KEY,
            base_name=BASE_NAME,
            tasklist_name=TASKLIST_NAME,
            calendar_name=CALENDAR_NAME,
            timezone=DEFAULT_TIMEZONE,
            base_id=binding_values["base_id"],
            tasklist_id=binding_values["tasklist_id"],
            calendar_id=binding_values["calendar_id"],
            base_url=validated_base_url,
            tenant_proof=tenant_proof,
        )

    def as_mapping(self) -> dict[str, Any]:
        return {
            "version": RESOURCE_CONFIG_VERSION,
            "tenant_key": self.tenant_key,
            "base_name": self.base_name,
            "tasklist_name": self.tasklist_name,
            "calendar_name": self.calendar_name,
            "timezone": self.timezone,
            "base_id": self.base_id,
            "tasklist_id": self.tasklist_id,
            "calendar_id": self.calendar_id,
            "base_url": self.base_url,
            "tenant_proof": self.tenant_proof,
        }


def _optional_id(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def parse_explicit_bitable_url(value: Any) -> str:
    """Return the app token from a user-provided Feishu Base URL."""

    url = str(value or "").strip()
    parsed = urlparse(url)
    host = str(parsed.hostname or "").lower()
    if parsed.scheme != "https" or not (host in _FEISHU_HOSTS or any(host.endswith("." + suffix) for suffix in _FEISHU_HOSTS)):
        raise DeepMathResourceContractError("base_url must be an explicit Feishu/Lark Base URL")
    match = re.search(r"/base/([^/?#]+)", parsed.path)
    token = match.group(1).strip() if match else ""
    if not _BITABLE_TOKEN.fullmatch(token):
        raise DeepMathResourceContractError("base_url does not contain a valid Base token")
    return token


def load_resource_config(path: str | Path) -> DeepMathResourceConfig:
    config_path = Path(path)
    try:
        value = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DeepMathResourceContractError("DeepMath resource config is unreadable") from exc
    if not isinstance(value, dict):
        raise DeepMathResourceContractError("DeepMath resource config must be an object")
    if int(value.get("version") or 0) != RESOURCE_CONFIG_VERSION:
        raise DeepMathResourceContractError("unsupported DeepMath resource config version")
    return DeepMathResourceConfig.from_mapping(value)


def resolve_exact_resource(
    kind: str,
    expected_name: str,
    candidates: Sequence[Mapping[str, Any]],
    *,
    tenant_key: str = DEEP_MATH_TENANT_KEY,
) -> DeepMathResourceSpec:
    """Resolve one exact DeepMath candidate to a deterministic outcome."""

    if tenant_key != DEEP_MATH_TENANT_KEY:
        raise DeepMathResourceContractError("resource resolution must use the deepmath tenant")
    matches: list[Mapping[str, Any]] = []
    for candidate in candidates:
        if str(candidate.get("tenant_key") or "") != DEEP_MATH_TENANT_KEY:
            continue
        if str(candidate.get("name") or candidate.get("summary") or "").strip() != expected_name:
            continue
        if str(candidate.get("id") or candidate.get("resource_id") or "").strip():
            matches.append(candidate)
    if len(matches) == 1:
        item = matches[0]
        resource_id = str(item.get("id") or item.get("resource_id")).strip()
        writable = bool(item.get("writable", item.get("permissions") in {"owner", "writer", "rw"}))
        if not writable:
            return DeepMathResourceSpec(kind, expected_name, resource_id, False, "unavailable", "resource is not writable")
        return DeepMathResourceSpec(kind, expected_name, resource_id, True, "bind_pending", "exact writable match requires approval")
    if not matches:
        return DeepMathResourceSpec(kind, expected_name, None, False, "create_pending", "no exact DeepMath match")
    return DeepMathResourceSpec(kind, expected_name, None, False, "selection_required", "multiple exact DeepMath matches")


def approval_candidate_for_resolution(spec: DeepMathResourceSpec) -> DeepMathResourceApprovalCandidate:
    """Map exact-name discovery to the single U1 approval contract.

    This function only prepares an approval-record candidate.  It never
    approves, creates, or binds an external resource; U4 owns approval state
    transitions and the explicit binder owns the post-approval local write.
    """

    if spec.status == "create_pending":
        return DeepMathResourceApprovalCandidate(
            "资源", spec.kind, spec.name, "创建", None, "待审批", False, spec.reason
        )
    if spec.status == "bind_pending" and spec.writable and spec.resource_id:
        return DeepMathResourceApprovalCandidate(
            "资源", spec.kind, spec.name, "绑定", spec.resource_id, "待审批", False, spec.reason
        )
    if spec.status == "selection_required":
        return DeepMathResourceApprovalCandidate(
            "资源", spec.kind, spec.name, "绑定", None, "人工处理", True, spec.reason
        )
    if spec.status == "unavailable":
        return DeepMathResourceApprovalCandidate(
            "资源", spec.kind, spec.name, "绑定", spec.resource_id, "人工处理", False, spec.reason
        )
    raise DeepMathResourceContractError(f"unsupported resource approval status: {spec.status}")


def tenant_identity_status(configured_proof: str | None, observed_tenant_key: str | None) -> str:
    """Compare an approved tenant key with the tenant API readback.

    A symbolic label or CLI assertion is never sufficient proof.  First-time
    discovery therefore remains approval_required until the observed key is
    explicitly approved and persisted in the DeepMath resource registry.
    """

    observed = _optional_id(observed_tenant_key)
    approved = _optional_id(configured_proof)
    if not observed:
        return "unverified"
    if not approved:
        return "approval_required"
    if approved != observed:
        return "tenant_mismatch"
    return "verified"


def configured_specs(config: DeepMathResourceConfig) -> tuple[DeepMathResourceSpec, ...]:
    return (
        _configured("base", config.base_name, config.base_id),
        _configured("tasklist", config.tasklist_name, config.tasklist_id),
        _configured("calendar", config.calendar_name, config.calendar_id),
    )


def _configured(kind: str, name: str, resource_id: str | None) -> DeepMathResourceSpec:
    if resource_id:
        return DeepMathResourceSpec(kind, name, resource_id, True, "bound")
    return DeepMathResourceSpec(kind, name, None, False, "discovery_required", "resource ID has not been bound")
