"""Server-owned AI context and tenant-scoped source routing for Stage 2.

This module is deliberately an adapter-level contract. It does not query a
database or call an external provider; callers supply authenticated server
facts and an injected, tenant-aware source reader.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Callable, Protocol
from uuid import UUID


SCHEMA_VERSION = "stage2.ai_execution_context.v2"
RECEIPT_SCHEMA_VERSION = "stage2.context_readback_receipt.v1"
PERSONAL_TENANT_TYPE = "personal"
ORGANIZATION_TENANT_TYPE = "organization"
PERSONAL_WORKSPACE_MODE = "personal_web"
ORGANIZATION_WORKSPACE_MODE = "organization_lark"
PERSONAL_BODY_AUTHORITY = "internal"
ORGANIZATION_BODY_AUTHORITY = "lark"
PERSONAL_AUTHORITY_MODE = "personal_web/internal"
ORGANIZATION_AUTHORITY_MODE = "organization_lark/lark"
SUPPORTED_AUTHORITY_MODES = frozenset({PERSONAL_AUTHORITY_MODE, ORGANIZATION_AUTHORITY_MODE})

DOCUMENT_WRITER_FIXTURE_ID = "stage2_document_writer_fixture"
READ_ONLY_CONSULTATION_FIXTURE_ID = "stage2_read_only_consultation_fixture"

_ALLOWED_TENANT_TYPES = frozenset({PERSONAL_TENANT_TYPE, ORGANIZATION_TENANT_TYPE})
_ALLOWED_PAIRS = {
    PERSONAL_WORKSPACE_MODE: PERSONAL_BODY_AUTHORITY,
    ORGANIZATION_WORKSPACE_MODE: ORGANIZATION_BODY_AUTHORITY,
}
_FORBIDDEN_BROWSER_FIELDS = frozenset(
    {
        "tenant",
        "tenant_id",
        "tenantId",
        "tenant_type",
        "tenantType",
        "organization_id",
        "organizationId",
        "workspace",
        "workspace_mode",
        "workspaceMode",
        "body_authority",
        "bodyAuthority",
        "binding",
        "binding_id",
        "bindingId",
        "binding_generation",
        "bindingGeneration",
        "member_role",
        "memberRole",
        "role",
    }
)


class Stage2ContextError(RuntimeError):
    """Fail-closed error with the project's code/detail/status shape."""

    def __init__(self, code: str, detail: str, *, status: int = 400) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.status = status


class ContextAuthorityError(Stage2ContextError):
    def __init__(self, fields: Iterable[str]) -> None:
        normalized = tuple(sorted({str(field) for field in fields}))
        super().__init__(
            "authority_override",
            "browser authority claims are not authorization facts",
            status=400,
        )
        self.fields = normalized


class ContextAuthorizationError(Stage2ContextError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(code, detail, status=403)


class ContextSourceError(Stage2ContextError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(code, detail, status=403)


class CapabilityEffectError(Stage2ContextError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(code, detail, status=403)


def _canonical_json(value: Any) -> str:
    """Serialize only stable JSON-shaped facts used in checksums."""

    def normalize(item: Any) -> Any:
        if isinstance(item, UUID):
            return str(item)
        if isinstance(item, datetime):
            return item.astimezone(timezone.utc).isoformat()
        if isinstance(item, Mapping):
            normalized: dict[str, Any] = {}
            for key, child in item.items():
                if not isinstance(key, str):
                    raise TypeError("checksum mappings require string keys")
                normalized[key] = normalize(child)
            return normalized
        if isinstance(item, (list, tuple)):
            return [normalize(child) for child in item]
        if item is None or isinstance(item, (bool, int, float, str)):
            return item
        raise TypeError(f"unsupported checksum value: {type(item).__name__}")

    return json.dumps(
        normalize(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _checksum(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _identifier(value: Any, label: str, *, maximum: int = 512) -> str:
    if isinstance(value, UUID):
        value = str(value)
    if not isinstance(value, str):
        raise Stage2ContextError("invalid_request", f"{label} must be a string")
    normalized = value.strip()
    if not normalized or len(normalized) > maximum or any(ord(char) < 32 for char in normalized):
        raise Stage2ContextError("invalid_request", f"{label} is invalid")
    return normalized


def _tenant_id(value: Any, label: str = "tenant_id") -> str:
    normalized = _identifier(value, label)
    try:
        parsed = UUID(normalized)
    except (ValueError, AttributeError) as exc:
        raise Stage2ContextError("invalid_request", f"{label} must be a canonical tenant UUID") from exc
    canonical = str(parsed)
    if normalized != canonical:
        raise Stage2ContextError("invalid_request", f"{label} must be a canonical tenant UUID")
    return canonical


def _positive_generation(value: Any, label: str = "binding_generation") -> int:
    if isinstance(value, bool):
        raise Stage2ContextError("invalid_request", f"{label} must be a positive integer")
    try:
        generation = int(value)
    except (TypeError, ValueError) as exc:
        raise Stage2ContextError("invalid_request", f"{label} must be a positive integer") from exc
    if generation < 1 or str(value).strip() != str(generation):
        raise Stage2ContextError("invalid_request", f"{label} must be a positive integer")
    return generation


def _authority_mode(workspace_mode: str, body_authority: str) -> str:
    if _ALLOWED_PAIRS.get(workspace_mode) != body_authority:
        raise Stage2ContextError("invalid_authority_pair", "workspace mode and body authority are incompatible")
    return f"{workspace_mode}/{body_authority}"


def _first(mapping: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping:
            return mapping[key]
    return None


def _reject_browser_claims(claims: Mapping[str, Any] | None) -> None:
    if claims is None:
        return
    if not isinstance(claims, Mapping):
        raise Stage2ContextError("invalid_request", "browser claims must be an object")
    found = sorted(set(claims).intersection(_FORBIDDEN_BROWSER_FIELDS))
    if found:
        raise ContextAuthorityError(found)


@dataclass(frozen=True, slots=True)
class ServerSessionFacts:
    """Authenticated facts supplied by the server-side session layer."""

    session_id: str
    user_id: str
    tenant_id: str
    tenant_type: str
    session_status: str = "active"
    member_status: str = "active"
    member_tenant_id: str | None = None
    member_role: str = "member"
    binding_generation: int | None = None
    tenant_status: str = "active"
    expires_at: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "session_id", _identifier(self.session_id, "session_id"))
        object.__setattr__(self, "user_id", _identifier(self.user_id, "user_id"))
        object.__setattr__(self, "tenant_id", _tenant_id(self.tenant_id))
        if self.tenant_type not in _ALLOWED_TENANT_TYPES:
            raise Stage2ContextError("invalid_request", "tenant_type is not supported")
        for name in ("session_status", "member_status", "tenant_status"):
            value = _identifier(getattr(self, name), name).lower()
            object.__setattr__(self, name, value)
        object.__setattr__(self, "member_role", _identifier(self.member_role, "member_role"))
        if self.member_tenant_id is not None:
            object.__setattr__(self, "member_tenant_id", _tenant_id(self.member_tenant_id, "member_tenant_id"))
        if self.binding_generation is not None:
            object.__setattr__(self, "binding_generation", _positive_generation(self.binding_generation))
        if self.expires_at is not None and not isinstance(self.expires_at, datetime):
            raise Stage2ContextError("invalid_request", "expires_at must be a datetime")

    def assert_active(self, *, now: datetime | None = None) -> None:
        if self.session_status != "active" or self.tenant_status != "active":
            raise ContextAuthorizationError("session_inactive", "authenticated session or tenant is inactive")
        if self.member_status != "active" or self.member_tenant_id != self.tenant_id:
            raise ContextAuthorizationError("member_inactive", "active tenant membership is required")
        if self.expires_at is not None:
            current = now or datetime.now(timezone.utc)
            expires_at = self.expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if expires_at <= current:
                raise ContextAuthorizationError("session_expired", "authenticated session has expired")


@dataclass(frozen=True, slots=True)
class OrganizationBinding:
    """Non-secret active Binding identity used by the organization path."""

    binding_id: str
    tenant_id: str
    generation: int
    status: str = "active"

    def __post_init__(self) -> None:
        object.__setattr__(self, "binding_id", _identifier(self.binding_id, "binding_id"))
        object.__setattr__(self, "tenant_id", _tenant_id(self.tenant_id))
        object.__setattr__(self, "generation", _positive_generation(self.generation, "generation"))
        object.__setattr__(self, "status", _identifier(self.status, "binding_status").lower())

    def assert_matches(self, session: ServerSessionFacts) -> None:
        if self.status != "active":
            raise ContextAuthorizationError("binding_inactive", "organization Binding is not active")
        if self.tenant_id != session.tenant_id:
            raise ContextAuthorizationError("binding_tenant_mismatch", "organization Binding tenant does not match session")
        if session.binding_generation is None or self.generation != session.binding_generation:
            raise ContextAuthorizationError("binding_generation_mismatch", "organization Binding generation does not match session")


@dataclass(frozen=True, slots=True)
class CapabilityEffect:
    capability_id: str
    document_side_effect: bool
    allowed_authority_modes: frozenset[str]
    readback_required: bool
    source_kinds: frozenset[str]

    def __post_init__(self) -> None:
        object.__setattr__(self, "capability_id", _identifier(self.capability_id, "capability_id"))
        modes = frozenset(_identifier(mode, "authority_mode") for mode in self.allowed_authority_modes)
        sources = frozenset(_identifier(source, "source_kind") for source in self.source_kinds)
        if not modes or not modes.issubset(SUPPORTED_AUTHORITY_MODES):
            raise CapabilityEffectError("invalid_capability_effect", "allowed authority modes are invalid")
        if not sources:
            raise CapabilityEffectError("invalid_capability_effect", "source kinds are required")
        if not self.document_side_effect and self.readback_required:
            raise CapabilityEffectError("invalid_capability_effect", "read-only capability cannot require document readback")
        object.__setattr__(self, "allowed_authority_modes", modes)
        object.__setattr__(self, "source_kinds", sources)

    @property
    def authority_modes(self) -> frozenset[str]:
        return self.allowed_authority_modes

    @property
    def produces_document(self) -> bool:
        return self.document_side_effect

    @property
    def requires_readback(self) -> bool:
        return self.readback_required


DEFAULT_CAPABILITY_EFFECTS = (
    CapabilityEffect(
        capability_id=DOCUMENT_WRITER_FIXTURE_ID,
        document_side_effect=True,
        allowed_authority_modes=frozenset(SUPPORTED_AUTHORITY_MODES),
        readback_required=True,
        source_kinds=frozenset(
            {"personal_material", "organization_material", "research_brief", "decision_brief"}
        ),
    ),
    CapabilityEffect(
        capability_id=READ_ONLY_CONSULTATION_FIXTURE_ID,
        document_side_effect=False,
        allowed_authority_modes=frozenset(SUPPORTED_AUTHORITY_MODES),
        readback_required=False,
        source_kinds=frozenset({"personal_material", "organization_material", "research_brief", "consultation_note"}),
    ),
)


class CapabilityEffectRegistry:
    """Immutable capability effect allow-list; absent IDs always fail closed."""

    def __init__(self, effects: Iterable[CapabilityEffect] = DEFAULT_CAPABILITY_EFFECTS) -> None:
        if isinstance(effects, Mapping):
            values = tuple(effects.values())
        else:
            values = tuple(effects)
        index: dict[str, CapabilityEffect] = {}
        for effect in values:
            if not isinstance(effect, CapabilityEffect):
                raise CapabilityEffectError("invalid_capability_effect", "registry entries must be CapabilityEffect values")
            if effect.capability_id in index:
                raise CapabilityEffectError("duplicate_capability_effect", "capability effect is registered more than once")
            index[effect.capability_id] = effect
        self._effects = MappingProxyType(index)

    @property
    def effects(self) -> tuple[CapabilityEffect, ...]:
        return tuple(self._effects[key] for key in sorted(self._effects))

    @property
    def definitions(self) -> tuple[CapabilityEffect, ...]:
        return self.effects

    def get(self, capability_id: str) -> CapabilityEffect | None:
        return self._effects.get(str(capability_id or "").strip())

    def require(self, capability_id: str) -> CapabilityEffect:
        effect = self.get(capability_id)
        if effect is None:
            raise CapabilityEffectError("unregistered_capability", "capability effect is not registered")
        return effect

    def authorize(
        self,
        capability_id: str,
        *,
        authority_mode: str,
        source_kind: str | None = None,
        document_side_effect: bool | None = None,
        readback_required: bool | None = None,
    ) -> CapabilityEffect:
        effect = self.require(capability_id)
        if authority_mode not in effect.allowed_authority_modes:
            raise CapabilityEffectError("capability_authority_forbidden", "capability is not allowed for this authority mode")
        if source_kind is not None and source_kind not in effect.source_kinds:
            raise CapabilityEffectError("capability_source_forbidden", "capability is not allowed to read this source kind")
        if document_side_effect is not None and document_side_effect != effect.document_side_effect:
            raise CapabilityEffectError("capability_effect_mismatch", "requested document side effect differs from registration")
        if readback_required is not None and readback_required != effect.readback_required:
            raise CapabilityEffectError("capability_readback_mismatch", "requested readback requirement differs from registration")
        return effect

    def authorize_context(self, context: "AIExecutionContext") -> CapabilityEffect:
        return self.authorize(
            context.capability_id,
            authority_mode=context.authority_mode,
        )


DEFAULT_CAPABILITY_EFFECT_REGISTRY = CapabilityEffectRegistry()


@dataclass(frozen=True, slots=True)
class AIExecutionContext:
    """Trusted context derived from server facts, never browser authority."""

    session_id: str
    user_id: str
    tenant_id: str
    tenant_type: str
    workspace_mode: str
    body_authority: str
    member_role: str
    capability_id: str
    binding_id: str | None = None
    binding_generation: int | None = None
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "session_id", _identifier(self.session_id, "session_id"))
        object.__setattr__(self, "user_id", _identifier(self.user_id, "user_id"))
        object.__setattr__(self, "tenant_id", _tenant_id(self.tenant_id))
        if self.tenant_type not in _ALLOWED_TENANT_TYPES:
            raise Stage2ContextError("invalid_request", "tenant_type is not supported")
        _authority_mode(self.workspace_mode, self.body_authority)
        object.__setattr__(self, "member_role", _identifier(self.member_role, "member_role"))
        object.__setattr__(self, "capability_id", _identifier(self.capability_id, "capability_id"))
        if self.tenant_type == PERSONAL_TENANT_TYPE:
            if self.binding_id is not None or self.binding_generation is not None:
                raise ContextAuthorizationError("personal_binding_forbidden", "personal context cannot carry an organization Binding")
        else:
            if self.binding_id is None or self.binding_generation is None:
                raise ContextAuthorizationError("binding_required", "organization context requires an active Binding")
            object.__setattr__(self, "binding_id", _identifier(self.binding_id, "binding_id"))
            object.__setattr__(self, "binding_generation", _positive_generation(self.binding_generation))

    @classmethod
    def from_server_facts(
        cls,
        session: ServerSessionFacts,
        capability_id: str,
        *,
        binding: OrganizationBinding | None = None,
        browser_claims: Mapping[str, Any] | None = None,
        effect_registry: CapabilityEffectRegistry | None = None,
        now: datetime | None = None,
    ) -> "AIExecutionContext":
        if not isinstance(session, ServerSessionFacts):
            raise Stage2ContextError("invalid_request", "server session facts are required")
        _reject_browser_claims(browser_claims)
        registry = effect_registry or DEFAULT_CAPABILITY_EFFECT_REGISTRY
        registry.require(capability_id)
        session.assert_active(now=now)
        if session.tenant_type == PERSONAL_TENANT_TYPE:
            if binding is not None:
                raise ContextAuthorizationError("personal_binding_forbidden", "personal context cannot use an organization Binding")
            if session.binding_generation is not None:
                raise ContextAuthorizationError("personal_binding_forbidden", "personal session carries Binding generation")
            workspace_mode = PERSONAL_WORKSPACE_MODE
            body_authority = PERSONAL_BODY_AUTHORITY
            binding_id = None
            binding_generation = None
        else:
            if binding is None:
                raise ContextAuthorizationError("binding_required", "organization context requires an active Binding")
            binding.assert_matches(session)
            workspace_mode = ORGANIZATION_WORKSPACE_MODE
            body_authority = ORGANIZATION_BODY_AUTHORITY
            binding_id = binding.binding_id
            binding_generation = binding.generation
        context = cls(
            session_id=session.session_id,
            user_id=session.user_id,
            tenant_id=session.tenant_id,
            tenant_type=session.tenant_type,
            workspace_mode=workspace_mode,
            body_authority=body_authority,
            member_role=session.member_role,
            capability_id=capability_id,
            binding_id=binding_id,
            binding_generation=binding_generation,
        )
        registry.authorize_context(context)
        return context

    @property
    def authority_mode(self) -> str:
        return _authority_mode(self.workspace_mode, self.body_authority)

    @property
    def context_checksum(self) -> str:
        return _checksum(self._checksum_payload())

    def _checksum_payload(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schema_version,
            "sessionId": self.session_id,
            "userId": self.user_id,
            "tenantId": self.tenant_id,
            "tenantType": self.tenant_type,
            "workspaceMode": self.workspace_mode,
            "bodyAuthority": self.body_authority,
            "memberRole": self.member_role,
            "capabilityId": self.capability_id,
            "bindingId": self.binding_id,
            "bindingGeneration": self.binding_generation,
        }

    def as_dict(self) -> dict[str, Any]:
        return {**self._checksum_payload(), "authorityMode": self.authority_mode, "contextChecksum": self.context_checksum}

    to_dict = as_dict


@dataclass(frozen=True, slots=True)
class ContextSourceRow:
    source_id: str
    source_kind: str
    tenant_id: str
    workspace_mode: str
    body_authority: str
    payload: Mapping[str, Any]
    binding_id: str | None = None
    binding_generation: int | None = None
    revision: str = "1"
    binding_present: bool = False
    binding_tenant_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_id", _identifier(self.source_id, "source_id"))
        object.__setattr__(self, "source_kind", _identifier(self.source_kind, "source_kind"))
        object.__setattr__(self, "tenant_id", _tenant_id(self.tenant_id))
        _authority_mode(self.workspace_mode, self.body_authority)
        if not isinstance(self.payload, Mapping):
            raise ContextSourceError("invalid_source_row", "source payload must be an object")
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))
        if self.binding_id is not None:
            object.__setattr__(self, "binding_id", _identifier(self.binding_id, "binding_id"))
        if self.binding_generation is not None:
            object.__setattr__(self, "binding_generation", _positive_generation(self.binding_generation))
        object.__setattr__(self, "revision", _identifier(self.revision, "source_revision"))
        if self.binding_tenant_id is not None:
            object.__setattr__(self, "binding_tenant_id", _tenant_id(self.binding_tenant_id, "binding_tenant_id"))
        if self.binding_present and self.binding_id is None and self.binding_generation is None:
            raise ContextSourceError("invalid_source_row", "source Binding identity is incomplete")

    @classmethod
    def from_record(cls, raw: Mapping[str, Any] | "ContextSourceRow") -> "ContextSourceRow":
        if isinstance(raw, ContextSourceRow):
            return raw
        if not isinstance(raw, Mapping):
            raise ContextSourceError("invalid_source_row", "source row must be an object")
        binding_present = "binding" in raw or "bindingFacts" in raw
        nested = _first(raw, "binding", "bindingFacts")
        nested_mapping = nested if isinstance(nested, Mapping) else None
        if nested is not None and nested_mapping is None:
            raise ContextSourceError("invalid_source_row", "source Binding must be an object")
        binding_id = _first(raw, "binding_id", "bindingId")
        binding_generation = _first(raw, "binding_generation", "bindingGeneration")
        binding_tenant_id = _first(raw, "binding_tenant_id", "bindingTenantId")
        if nested_mapping is not None:
            binding_id = binding_id if binding_id is not None else _first(nested_mapping, "binding_id", "bindingId", "id")
            binding_generation = (
                binding_generation
                if binding_generation is not None
                else _first(nested_mapping, "binding_generation", "bindingGeneration", "generation")
            )
            binding_tenant_id = (
                binding_tenant_id
                if binding_tenant_id is not None
                else _first(nested_mapping, "tenant_id", "tenantId")
            )
        return cls(
            source_id=_first(raw, "source_id", "sourceId", "id"),
            source_kind=_first(raw, "source_kind", "sourceKind", "kind"),
            tenant_id=_first(raw, "tenant_id", "tenantId", "owner_tenant_id", "ownerTenantId"),
            workspace_mode=_first(raw, "workspace_mode", "workspaceMode"),
            body_authority=_first(raw, "body_authority", "bodyAuthority"),
            payload=_first(raw, "payload", "data", "fields") or {},
            binding_id=binding_id,
            binding_generation=binding_generation,
            revision=str(_first(raw, "revision", "source_revision", "sourceRevision") or "1"),
            binding_present=binding_present or binding_id is not None or binding_generation is not None,
            binding_tenant_id=binding_tenant_id,
        )

    @property
    def checksum(self) -> str:
        return _checksum(self._checksum_payload())

    @property
    def source_checksum(self) -> str:
        return self.checksum

    def _checksum_payload(self) -> dict[str, Any]:
        return {
            "sourceId": self.source_id,
            "sourceKind": self.source_kind,
            "tenantId": self.tenant_id,
            "workspaceMode": self.workspace_mode,
            "bodyAuthority": self.body_authority,
            "payload": self.payload,
            "bindingId": self.binding_id,
            "bindingGeneration": self.binding_generation,
            "bindingTenantId": self.binding_tenant_id,
            "revision": self.revision,
        }

    def as_dict(self) -> dict[str, Any]:
        value = dict(self._checksum_payload())
        value["sourceChecksum"] = self.checksum
        return value


@dataclass(frozen=True, slots=True)
class ContextReadbackReceipt:
    context_checksum: str
    tenant_id: str
    workspace_mode: str
    body_authority: str
    capability_id: str
    source_refs: tuple[tuple[str, str, str], ...]
    binding_id: str | None
    binding_generation: int | None
    schema_version: str = RECEIPT_SCHEMA_VERSION
    checksum: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "tenant_id", _tenant_id(self.tenant_id))
        _authority_mode(self.workspace_mode, self.body_authority)
        object.__setattr__(self, "capability_id", _identifier(self.capability_id, "capability_id"))
        normalized_refs = tuple(
            (_identifier(source_id, "source_id"), _identifier(source_kind, "source_kind"), _identifier(source_checksum, "source_checksum"))
            for source_id, source_kind, source_checksum in self.source_refs
        )
        object.__setattr__(self, "source_refs", normalized_refs)
        if self.binding_id is not None:
            object.__setattr__(self, "binding_id", _identifier(self.binding_id, "binding_id"))
        if self.binding_generation is not None:
            object.__setattr__(self, "binding_generation", _positive_generation(self.binding_generation))
        object.__setattr__(self, "checksum", _checksum(self._checksum_payload()))

    def _checksum_payload(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schema_version,
            "contextChecksum": self.context_checksum,
            "tenantId": self.tenant_id,
            "workspaceMode": self.workspace_mode,
            "bodyAuthority": self.body_authority,
            "capabilityId": self.capability_id,
            "sourceRefs": self.source_refs,
            "bindingId": self.binding_id,
            "bindingGeneration": self.binding_generation,
        }

    @property
    def receipt_id(self) -> str:
        return f"stage2_receipt_{self.checksum[:24]}"

    @property
    def readback_checksum(self) -> str:
        return self.checksum

    def as_dict(self) -> dict[str, Any]:
        return {
            **self._checksum_payload(),
            "receiptId": self.receipt_id,
            "readbackChecksum": self.checksum,
        }


@dataclass(frozen=True, slots=True)
class ContextBuildResult:
    context: AIExecutionContext
    items: tuple[ContextSourceRow, ...]
    receipt: ContextReadbackReceipt

    @property
    def context_checksum(self) -> str:
        return self.context.context_checksum

    @property
    def checksum(self) -> str:
        return self.context_checksum

    @property
    def readback_receipt(self) -> ContextReadbackReceipt:
        return self.receipt

    def as_dict(self) -> dict[str, Any]:
        return {
            "context": self.context.as_dict(),
            "items": [item.as_dict() for item in self.items],
            "readbackReceipt": self.receipt.as_dict(),
        }


class ContextSourceReader(Protocol):
    def list_sources(
        self,
        *,
        tenant_id: str,
        workspace_mode: str,
        source_kinds: tuple[str, ...],
    ) -> Iterable[Mapping[str, Any] | ContextSourceRow]: ...


class ContextBuilder:
    """Build context sources through an exact tenant/workspace reader call."""

    def __init__(
        self,
        source_reader: ContextSourceReader | Any | None = None,
        *,
        effect_registry: CapabilityEffectRegistry | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._source_reader = source_reader
        self._effects = effect_registry or DEFAULT_CAPABILITY_EFFECT_REGISTRY
        self._clock = clock

    def build_context(
        self,
        session: ServerSessionFacts,
        capability_id: str,
        *,
        binding: OrganizationBinding | None = None,
        browser_claims: Mapping[str, Any] | None = None,
    ) -> AIExecutionContext:
        return AIExecutionContext.from_server_facts(
            session,
            capability_id,
            binding=binding,
            browser_claims=browser_claims,
            effect_registry=self._effects,
            now=self._clock() if self._clock is not None else None,
        )

    def build_for_session(
        self,
        session: ServerSessionFacts,
        capability_id: str,
        *,
        binding: OrganizationBinding | None = None,
        browser_claims: Mapping[str, Any] | None = None,
        source_rows: Iterable[Mapping[str, Any] | ContextSourceRow] | None = None,
        requested_source_kinds: Iterable[str] | None = None,
    ) -> ContextBuildResult:
        context = self.build_context(
            session,
            capability_id,
            binding=binding,
            browser_claims=browser_claims,
        )
        return self.build(
            context,
            source_rows=source_rows,
            requested_source_kinds=requested_source_kinds,
        )

    def build(
        self,
        context: AIExecutionContext,
        *,
        source_rows: Iterable[Mapping[str, Any] | ContextSourceRow] | None = None,
        requested_source_kinds: Iterable[str] | None = None,
    ) -> ContextBuildResult:
        if not isinstance(context, AIExecutionContext):
            raise Stage2ContextError("invalid_request", "trusted AIExecutionContext is required")
        effect = self._effects.authorize_context(context)
        requested = self._requested_source_kinds(effect, requested_source_kinds)
        raw_rows = source_rows
        if raw_rows is None:
            raw_rows = self._read_sources(context, requested)
        if not isinstance(raw_rows, Iterable):
            raise ContextSourceError("source_reader_invalid", "source reader must return an iterable")
        parsed: list[ContextSourceRow] = []
        seen: set[tuple[str, str]] = set()
        for raw in raw_rows:
            row = ContextSourceRow.from_record(raw)
            self._validate_row(row, context, effect, requested)
            identity = (row.source_kind, row.source_id)
            if identity in seen:
                raise ContextSourceError("duplicate_source", "context contains a duplicate source")
            seen.add(identity)
            parsed.append(row)
        parsed.sort(key=lambda row: (row.source_kind, row.source_id, row.revision, row.checksum))
        refs = tuple((row.source_id, row.source_kind, row.checksum) for row in parsed)
        receipt = ContextReadbackReceipt(
            context_checksum=context.context_checksum,
            tenant_id=context.tenant_id,
            workspace_mode=context.workspace_mode,
            body_authority=context.body_authority,
            capability_id=context.capability_id,
            source_refs=refs,
            binding_id=context.binding_id,
            binding_generation=context.binding_generation,
        )
        return ContextBuildResult(context=context, items=tuple(parsed), receipt=receipt)

    @staticmethod
    def _requested_source_kinds(
        effect: CapabilityEffect,
        requested_source_kinds: Iterable[str] | None,
    ) -> tuple[str, ...]:
        if requested_source_kinds is None:
            return tuple(sorted(effect.source_kinds))
        requested = frozenset(_identifier(kind, "source_kind") for kind in requested_source_kinds)
        if not requested or not requested.issubset(effect.source_kinds):
            raise CapabilityEffectError("capability_source_forbidden", "requested source kinds exceed the registration")
        return tuple(sorted(requested))

    def _read_sources(self, context: AIExecutionContext, source_kinds: tuple[str, ...]) -> Iterable[Any]:
        if self._source_reader is None:
            raise ContextSourceError("source_reader_required", "a tenant-scoped source reader is required")
        reader = getattr(self._source_reader, "list_sources", None)
        if not callable(reader):
            reader = getattr(self._source_reader, "read_for_context", None)
        if not callable(reader):
            raise ContextSourceError("source_reader_invalid", "source reader has no supported read method")
        return reader(
            tenant_id=context.tenant_id,
            workspace_mode=context.workspace_mode,
            source_kinds=source_kinds,
        )

    @staticmethod
    def _validate_row(
        row: ContextSourceRow,
        context: AIExecutionContext,
        effect: CapabilityEffect,
        requested_source_kinds: tuple[str, ...],
    ) -> None:
        if row.tenant_id != context.tenant_id:
            raise ContextSourceError("source_tenant_mismatch", "source row belongs to another tenant")
        if row.workspace_mode != context.workspace_mode or row.body_authority != context.body_authority:
            raise ContextSourceError("source_authority_mismatch", "source row authority does not match context")
        if row.source_kind not in requested_source_kinds or row.source_kind not in effect.source_kinds:
            raise ContextSourceError("source_kind_forbidden", "source row kind is not registered for this capability")
        if context.tenant_type == PERSONAL_TENANT_TYPE:
            if row.binding_present or row.binding_id is not None or row.binding_generation is not None or row.binding_tenant_id is not None:
                raise ContextSourceError("personal_binding_forbidden", "personal context cannot read Binding data")
            return
        if not row.binding_present or row.binding_id is None or row.binding_generation is None:
            raise ContextSourceError("source_binding_required", "organization source row requires Binding identity")
        if row.binding_id != context.binding_id or row.binding_generation != context.binding_generation:
            raise ContextSourceError("source_binding_mismatch", "source row Binding does not match context")
        if row.binding_tenant_id is not None and row.binding_tenant_id != context.tenant_id:
            raise ContextSourceError("source_binding_tenant_mismatch", "source row Binding tenant does not match context")


def build_ai_execution_context(
    session: ServerSessionFacts,
    capability_id: str,
    *,
    binding: OrganizationBinding | None = None,
    browser_claims: Mapping[str, Any] | None = None,
    effect_registry: CapabilityEffectRegistry | None = None,
    now: datetime | None = None,
) -> AIExecutionContext:
    return AIExecutionContext.from_server_facts(
        session,
        capability_id,
        binding=binding,
        browser_claims=browser_claims,
        effect_registry=effect_registry,
        now=now,
    )


TrustedAIExecutionContext = AIExecutionContext
SessionFacts = ServerSessionFacts
Binding = OrganizationBinding
ContextSource = ContextSourceRow
ContextReceipt = ContextReadbackReceipt
CapabilityEffectRegistryError = CapabilityEffectError


__all__ = [
    "AIExecutionContext",
    "Binding",
    "CapabilityEffect",
    "CapabilityEffectError",
    "CapabilityEffectRegistry",
    "CapabilityEffectRegistryError",
    "ContextAuthorityError",
    "ContextBuildResult",
    "ContextBuilder",
    "ContextReceipt",
    "ContextReadbackReceipt",
    "ContextSource",
    "ContextSourceError",
    "ContextSourceReader",
    "ContextSourceRow",
    "DOCUMENT_WRITER_FIXTURE_ID",
    "DEFAULT_CAPABILITY_EFFECTS",
    "DEFAULT_CAPABILITY_EFFECT_REGISTRY",
    "ORGANIZATION_AUTHORITY_MODE",
    "ORGANIZATION_BODY_AUTHORITY",
    "ORGANIZATION_TENANT_TYPE",
    "ORGANIZATION_WORKSPACE_MODE",
    "OrganizationBinding",
    "PERSONAL_AUTHORITY_MODE",
    "PERSONAL_BODY_AUTHORITY",
    "PERSONAL_TENANT_TYPE",
    "PERSONAL_WORKSPACE_MODE",
    "READ_ONLY_CONSULTATION_FIXTURE_ID",
    "SCHEMA_VERSION",
    "ServerSessionFacts",
    "SessionFacts",
    "Stage2ContextError",
    "TrustedAIExecutionContext",
    "build_ai_execution_context",
]
