"""Release 1B organization provisioning services.

The module keeps database transactions and Feishu calls behind explicit ports.
Database state is authoritative; external steps are idempotent and read back,
but are never described as part of a cross-system transaction.
"""

from __future__ import annotations

import hashlib
import json
import re
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Callable, Literal, Mapping, Protocol, Sequence
from uuid import UUID, uuid4

from .stage1_member_onboarding import ServerFeishuInstallContext
from .stage1_provision_models import Stage1LifecycleState


UTC = timezone.utc
REQUIRED_ADMIN_SCOPE = "tenant:provision"
REQUIRED_RESOURCE_KINDS = ("wiki", "parent_node", "app_directory")
MAX_LEASE_SECONDS = 300
IF2_IDEMPOTENCY_KEY_RE = re.compile(r"^[A-Za-z0-9_-]{8,128}$")


class ProvisioningError(RuntimeError):
    def __init__(self, code: str, detail: str, *, status: int = 409) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.status = status

    def to_http_error(self) -> dict[str, object]:
        return {"code": self.code, "detail": self.detail}


def _fail(code: str, detail: str, *, status: int = 409) -> None:
    raise ProvisioningError(code, detail, status=status)


def _text(value: object, name: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    normalized = value.strip()
    if value != normalized or not normalized or len(normalized) > maximum:
        raise ValueError(f"{name} is invalid")
    if any(ord(character) < 32 for character in normalized):
        raise ValueError(f"{name} is invalid")
    return normalized


def _projection_key(value: object) -> str:
    normalized = _text(value, "idempotency_key", 128)
    if not IF2_IDEMPOTENCY_KEY_RE.fullmatch(normalized):
        raise ValueError("idempotency_key is invalid")
    return normalized


def _resource_run_key(value: object) -> str:
    """Validate the 042 resource-run key without applying IF2's alphabet.

    The provision tables deliberately allow a wider key contract than the IF2
    projection.  In particular, orchestrator child keys contain a separator.
    """
    normalized = _text(value, "idempotency_key", 160)
    if len(normalized) < 8:
        raise ValueError("idempotency_key is invalid")
    return normalized


def _idempotency_key(value: object) -> str:
    """Compatibility name for callers that create a resource run key."""
    return _resource_run_key(value)


def retry_delay_seconds(retry_count: int) -> int:
    if not isinstance(retry_count, int) or isinstance(retry_count, bool) or retry_count <= 0:
        raise ValueError("retry_count must be a positive integer")
    return min(300, 2 ** min(retry_count, 8))


def _child_idempotency_key(parent: str, step: str) -> str:
    candidate = f"{parent}:{step}"
    if len(candidate) <= 160:
        return candidate
    suffix = hashlib.sha256(parent.encode("utf-8")).hexdigest()[:24]
    return f"{parent[:110]}:{step[:20]}:{suffix}"


def _utc(value: datetime, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone aware")
    return value.astimezone(UTC)


def _digest(payload: Mapping[str, object]) -> bytes:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).digest()


class _TrustedMarker:
    __slots__ = ()


_TRUSTED_ADMIN_MARKER = _TrustedMarker()
_TRUSTED_ACTOR_MARKER = _TrustedMarker()


@dataclass(frozen=True, init=False, repr=False)
class TrustedFeishuAdministrator:
    """Verified provider result created only by the server adapter."""

    tenant_key: str
    open_id: str
    scopes: frozenset[str]
    expires_at: datetime
    is_tenant_administrator: bool
    _marker: object = field(repr=False, compare=False)

    def __init__(
        self,
        tenant_key: str,
        open_id: str,
        *,
        scopes: Sequence[str],
        expires_at: datetime,
        is_tenant_administrator: bool,
        _marker: object | None = None,
    ) -> None:
        if _marker is not _TRUSTED_ADMIN_MARKER:
            raise TypeError("administrator authorization must come from the trusted adapter")
        object.__setattr__(self, "tenant_key", _text(tenant_key, "tenant_key", 128))
        object.__setattr__(self, "open_id", _text(open_id, "open_id", 512))
        object.__setattr__(self, "scopes", frozenset(_text(item, "scope", 160) for item in scopes))
        object.__setattr__(self, "expires_at", _utc(expires_at, "expires_at"))
        object.__setattr__(self, "is_tenant_administrator", is_tenant_administrator is True)
        object.__setattr__(self, "_marker", _marker)

    @classmethod
    def from_server_adapter(
        cls,
        tenant_key: str,
        open_id: str,
        *,
        scopes: Sequence[str],
        expires_at: datetime,
        is_tenant_administrator: bool,
    ) -> "TrustedFeishuAdministrator":
        return cls(
            tenant_key,
            open_id,
            scopes=scopes,
            expires_at=expires_at,
            is_tenant_administrator=is_tenant_administrator,
            _marker=_TRUSTED_ADMIN_MARKER,
        )

    def __repr__(self) -> str:
        return "TrustedFeishuAdministrator(<redacted>)"


@dataclass(frozen=True, init=False)
class TrustedProvisionActor:
    user_id: UUID
    tenant_id: UUID
    role: Literal["owner", "support"]
    installation_id: UUID
    _marker: object = field(repr=False, compare=False)

    def __init__(
        self,
        user_id: UUID,
        tenant_id: UUID,
        role: Literal["owner", "support"],
        installation_id: UUID,
        *,
        _marker: object | None = None,
    ) -> None:
        if _marker is not _TRUSTED_ACTOR_MARKER:
            raise TypeError("provision actor must come from the server authorization boundary")
        if not all(isinstance(value, UUID) for value in (user_id, tenant_id, installation_id)):
            raise ValueError("provision actor identifiers must be UUID values")
        if role not in {"owner", "support"}:
            raise ValueError("provision actor role is invalid")
        object.__setattr__(self, "user_id", user_id)
        object.__setattr__(self, "tenant_id", tenant_id)
        object.__setattr__(self, "role", role)
        object.__setattr__(self, "installation_id", installation_id)
        object.__setattr__(self, "_marker", _marker)

    @classmethod
    def from_server_authorization(
        cls,
        user_id: UUID,
        tenant_id: UUID,
        role: Literal["owner", "support"],
        installation_id: UUID,
    ) -> "TrustedProvisionActor":
        return cls(user_id, tenant_id, role, installation_id, _marker=_TRUSTED_ACTOR_MARKER)


@dataclass(frozen=True)
class InstallationTarget:
    installation_id: UUID
    installation_public_id: str
    app_id: str
    tenant_key: str
    state: Stage1LifecycleState
    tenant_id: UUID | None = None
    credential_ref: str | None = None


@dataclass(frozen=True)
class ResourceTarget:
    """A server-owned Feishu target bound to one Stage 1 installation."""

    installation_id: UUID
    tenant_id: UUID
    tenant_key: str
    space_id: str
    parent_node_token: str
    binding_id: int | None = None
    binding_generation: int | None = None


@dataclass(frozen=True)
class OwnerRecord:
    user_id: UUID
    tenant_id: UUID
    role: str = "owner"
    status: str = "active"
    tenant_type: str = "organization"
    workspace_mode: str = "organization_lark"
    body_authority: str = "lark"
    organization_name: str = ""


@dataclass(frozen=True)
class BindingGeneration:
    binding_id: int
    installation_id: UUID
    tenant_id: UUID
    tenant_key: str
    generation: int
    state: Stage1LifecycleState


@dataclass(frozen=True)
class OwnerIdentity:
    tenant_id: UUID
    user_id: UUID
    binding_id: int
    open_id: str
    state: Stage1LifecycleState


@dataclass(frozen=True)
class AdminConfirmationReceipt:
    confirmation_id: UUID
    idempotency_key: str
    request_digest: bytes
    installation_id: UUID
    tenant_id: UUID
    owner_user_id: UUID
    binding_id: int
    binding_generation: int
    tenant_key: str
    open_id: str
    action: Literal["created", "reused"]
    confirmed_at: datetime


class AdminConfirmationStore(Protocol):
    def confirmation_for_key(
        self, installation_id: UUID, idempotency_key: str
    ) -> AdminConfirmationReceipt | None: ...

    def installation_for_update(
        self, installation_public_id: str, tenant_key: str
    ) -> InstallationTarget | None: ...

    def ensure_organization_owner(
        self, tenant_id: UUID, owner_user_id: UUID, organization_name: str
    ) -> OwnerRecord | None:
        """Create or lock the organization tenant and its owner in this transaction."""
        ...

    def current_bindings(self, installation_id: UUID, tenant_id: UUID) -> Sequence[BindingGeneration]: ...

    def create_binding(
        self, installation: InstallationTarget, tenant_id: UUID
    ) -> BindingGeneration: ...

    def owner_identities(self, binding_id: int, open_id: str) -> Sequence[OwnerIdentity]: ...

    def conflicting_owner_identities(
        self, tenant_id: UUID, binding_id: int, owner_user_id: UUID, open_id: str
    ) -> Sequence[OwnerIdentity]: ...

    def recheck_confirmation_authority(
        self,
        *,
        session_id: UUID,
        session_user_id: UUID,
        session_tenant_id: UUID,
        target_tenant_id: UUID,
        installation_id: UUID,
        installation_public_id: str,
        tenant_key: str,
        open_id: str,
        credential_ref: str,
        scopes: frozenset[str],
        is_tenant_administrator: bool,
        authorization_expires_at: datetime,
        now: datetime,
    ) -> None: ...

    def create_owner_identity(
        self, binding: BindingGeneration, owner_user_id: UUID, open_id: str
    ) -> OwnerIdentity: ...

    def assign_installation(
        self, installation_id: UUID, tenant_id: UUID, credential_ref: str | None
    ) -> InstallationTarget: ...

    def write_confirmation_audit(
        self, receipt: AdminConfirmationReceipt, authorization: TrustedFeishuAdministrator
    ) -> None: ...

    def save_confirmation(self, receipt: AdminConfirmationReceipt) -> None: ...

    def readback_confirmation(self, confirmation_id: UUID) -> AdminConfirmationReceipt | None: ...


class AdminConfirmationRepository(Protocol):
    def transaction(self) -> AbstractContextManager[AdminConfirmationStore]: ...


class AdministratorConfirmationService:
    """Atomically bind an existing organization owner to one installation."""

    def __init__(
        self,
        repository: AdminConfirmationRepository,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._now = now or (lambda: datetime.now(UTC))

    def confirm(
        self,
        *,
        tenant_id: UUID,
        owner_user_id: UUID,
        installation_id: UUID | None = None,
        install_context: ServerFeishuInstallContext,
        authorization: TrustedFeishuAdministrator,
        idempotency_key: str,
        credential_ref: str | None = None,
        organization_name: str | None = None,
        session_id: UUID | None = None,
        session_tenant_id: UUID | None = None,
        authorization_revalidator: Callable[[], object] | None = None,
        browser_payload: Mapping[str, object] | None = None,
    ) -> AdminConfirmationReceipt:
        try:
            key = _projection_key(idempotency_key)
        except ValueError as exc:
            _fail("admin_confirmation_invalid_idempotency_key", "idempotency key is invalid", status=400)
            raise AssertionError("unreachable") from exc
        if not isinstance(tenant_id, UUID) or not isinstance(owner_user_id, UUID):
            _fail("admin_confirmation_invalid", "tenant and owner identifiers are invalid", status=400)
        if not isinstance(installation_id, UUID):
            _fail("admin_confirmation_installation_required", "installation identity is required", status=409)
        if not isinstance(install_context, ServerFeishuInstallContext):
            _fail("admin_confirmation_server_context_required", "server install context is required", status=403)
        if not isinstance(authorization, TrustedFeishuAdministrator):
            _fail("admin_confirmation_untrusted", "trusted administrator authorization is required", status=403)
        payload = {} if browser_payload is None else browser_payload
        if not isinstance(payload, Mapping):
            _fail("admin_confirmation_invalid", "browser payload must be an object", status=400)
        forbidden = {"tenant_id", "tenantId", "tenant_key", "tenantKey", "open_id", "openId", "binding_id", "bindingId"}
        if forbidden.intersection(payload):
            _fail("admin_confirmation_browser_identity_forbidden", "identity fields must be server derived", status=403)
        now = _utc(self._now(), "now")
        if not authorization.is_tenant_administrator:
            _fail("admin_confirmation_administrator_required", "a tenant administrator must confirm", status=403)
        if REQUIRED_ADMIN_SCOPE not in authorization.scopes:
            _fail("admin_confirmation_scope_missing", "administrator authorization scope is insufficient", status=403)
        if authorization.expires_at <= now:
            _fail("admin_confirmation_expired", "administrator authorization has expired", status=403)
        if authorization.tenant_key != install_context.tenant_key:
            _fail("admin_confirmation_cross_tenant", "authorization does not match the installation", status=403)
        if install_context.installation_id is None:
            _fail("admin_confirmation_installation_required", "installation identity is required", status=409)
        if organization_name is None:
            _fail("admin_confirmation_organization_name_required", "organization name is required", status=400)
        try:
            normalized_organization_name = _text(organization_name, "organization_name", 120)
            normalized_credential_ref = _text(credential_ref, "credential_ref", 256)
        except ValueError as exc:
            _fail("admin_confirmation_invalid", "organization confirmation facts are invalid", status=400)
            raise AssertionError("unreachable") from exc
        if session_id is not None and not isinstance(session_id, UUID):
            _fail("admin_confirmation_invalid", "session identity is invalid", status=400)
        if session_tenant_id is not None and not isinstance(session_tenant_id, UUID):
            _fail("admin_confirmation_invalid", "session tenant identity is invalid", status=400)
        if session_id is None or session_tenant_id is None:
            _fail("admin_confirmation_session_required", "current session authority is required", status=403)
        request_digest = _digest(
            {
                "tenantId": str(tenant_id),
                "ownerUserId": str(owner_user_id),
                "tenantKey": install_context.tenant_key,
                "installationPublicId": install_context.installation_id,
                "openId": authorization.open_id,
                "credentialRef": normalized_credential_ref,
                "organizationName": normalized_organization_name,
            }
        )
        try:
            with self._repository.transaction() as store:
                if authorization_revalidator is not None:
                    try:
                        refreshed = authorization_revalidator()
                    except ProvisioningError:
                        raise
                    except Exception as exc:
                        _fail("admin_confirmation_authority_changed", "administrator authority changed", status=403)
                        raise AssertionError("unreachable") from exc
                    refreshed_authorization = getattr(refreshed, "authorization", refreshed)
                    if not isinstance(refreshed_authorization, TrustedFeishuAdministrator):
                        _fail("admin_confirmation_authority_changed", "administrator authority changed", status=403)
                    if (
                        refreshed_authorization != authorization
                        or getattr(refreshed, "tenant_id", tenant_id) != tenant_id
                        or getattr(refreshed, "installation_id", installation_id) != installation_id
                        or getattr(refreshed, "installation_public_id", install_context.installation_id)
                        != install_context.installation_id
                        or getattr(refreshed, "credential_ref", normalized_credential_ref)
                        != normalized_credential_ref
                    ):
                        _fail("admin_confirmation_authority_changed", "administrator authority changed", status=403)
                recheck = getattr(store, "recheck_confirmation_authority", None)
                if not callable(recheck):
                    _fail("admin_confirmation_storage_unavailable", "confirmation authority recheck is unavailable", status=503)
                recheck(
                    session_id=session_id,
                    session_user_id=owner_user_id,
                    session_tenant_id=session_tenant_id,
                    target_tenant_id=tenant_id,
                    installation_id=installation_id,
                    installation_public_id=install_context.installation_id,
                    tenant_key=install_context.tenant_key,
                    open_id=authorization.open_id,
                    credential_ref=normalized_credential_ref,
                    scopes=authorization.scopes,
                    is_tenant_administrator=authorization.is_tenant_administrator,
                    authorization_expires_at=authorization.expires_at,
                    now=now,
                )
                installation = store.installation_for_update(
                    install_context.installation_id, install_context.tenant_key
                )
                if installation is None:
                    _fail("admin_confirmation_installation_missing", "installation is unavailable")
                if installation.installation_id != installation_id:
                    _fail("admin_confirmation_installation_changed", "installation identity changed")
                existing = store.confirmation_for_key(installation.installation_id, key)
                if existing is not None:
                    if existing.request_digest != request_digest:
                        _fail("admin_confirmation_idempotency_conflict", "idempotency key was reused")
                    return existing
                if installation.state in {Stage1LifecycleState.DISABLED, Stage1LifecycleState.REVOKED}:
                    _fail("admin_confirmation_installation_inactive", "installation is not active")
                if installation.tenant_id not in {None, tenant_id}:
                    _fail("admin_confirmation_cross_tenant", "installation belongs to another tenant", status=403)
                owner = store.ensure_organization_owner(
                    tenant_id, owner_user_id, normalized_organization_name
                )
                if (
                    owner is None
                    or owner.role != "owner"
                    or owner.status != "active"
                    or owner.tenant_id != tenant_id
                    or owner.user_id != owner_user_id
                    or owner.tenant_type != "organization"
                    or owner.workspace_mode != "organization_lark"
                    or owner.body_authority != "lark"
                    or owner.organization_name != normalized_organization_name
                ):
                    _fail("admin_confirmation_owner_invalid", "active organization owner is required", status=403)
                bindings = tuple(store.current_bindings(installation.installation_id, tenant_id))
                if len(bindings) > 1:
                    _fail("admin_confirmation_binding_ambiguous", "multiple active bindings exist")
                binding = bindings[0] if bindings else store.create_binding(installation, tenant_id)
                if (
                    binding.installation_id != installation.installation_id
                    or binding.tenant_id != tenant_id
                    or binding.tenant_key != install_context.tenant_key
                    or binding.state not in {
                        Stage1LifecycleState.NEEDS_ATTENTION,
                        Stage1LifecycleState.ACTIVE,
                    }
                ):
                    _fail("admin_confirmation_binding_invalid", "binding readback is inconsistent")
                conflicting_identities = getattr(store, "conflicting_owner_identities", None)
                if callable(conflicting_identities):
                    if conflicting_identities(
                        tenant_id, binding.binding_id, owner_user_id, authorization.open_id
                    ):
                        _fail("admin_confirmation_identity_conflict", "owner identity conflicts with another binding")
                identities = tuple(store.owner_identities(binding.binding_id, authorization.open_id))
                if len(identities) > 1:
                    _fail("admin_confirmation_identity_ambiguous", "owner identity is ambiguous")
                identity = identities[0] if identities else store.create_owner_identity(
                    binding, owner_user_id, authorization.open_id
                )
                if (
                    identity.tenant_id != tenant_id
                    or identity.user_id != owner_user_id
                    or identity.binding_id != binding.binding_id
                    or identity.open_id != authorization.open_id
                    or identity.state is not Stage1LifecycleState.ACTIVE
                ):
                    _fail("admin_confirmation_identity_conflict", "owner identity readback is inconsistent")
                assigned = store.assign_installation(
                    installation.installation_id, tenant_id, normalized_credential_ref
                )
                if (
                    assigned.tenant_id != tenant_id
                    or assigned.tenant_key != install_context.tenant_key
                    or assigned.credential_ref != normalized_credential_ref
                    or assigned.state
                    not in {Stage1LifecycleState.NEEDS_ATTENTION, Stage1LifecycleState.ACTIVE}
                ):
                    _fail("admin_confirmation_installation_readback_failed", "installation assignment was not durable")
                receipt = AdminConfirmationReceipt(
                    confirmation_id=uuid4(),
                    idempotency_key=key,
                    request_digest=request_digest,
                    installation_id=installation.installation_id,
                    tenant_id=tenant_id,
                    owner_user_id=owner_user_id,
                    binding_id=binding.binding_id,
                    binding_generation=binding.generation,
                    tenant_key=binding.tenant_key,
                    open_id=identity.open_id,
                    action="reused" if bindings and identities else "created",
                    confirmed_at=now,
                )
                store.write_confirmation_audit(receipt, authorization)
                store.save_confirmation(receipt)
                readback = store.readback_confirmation(receipt.confirmation_id)
                if readback != receipt:
                    _fail("admin_confirmation_readback_failed", "confirmation receipt was not durable")
                return receipt
        except ProvisioningError:
            raise
        except Exception as exc:
            raise ProvisioningError(
                "admin_confirmation_storage_unavailable",
                "administrator confirmation storage is unavailable",
                status=503,
            ) from exc


@dataclass(frozen=True)
class ResourceBindingContext:
    installation_id: UUID
    tenant_id: UUID
    binding_id: int
    binding_generation: int
    tenant_key: str
    credential_ref: str
    state: Stage1LifecycleState = Stage1LifecycleState.ACTIVE
    space_id: str = ""
    parent_node_token: str = ""
    resource_target: ResourceTarget | None = None


@dataclass(frozen=True)
class ExternalResource:
    kind: str
    external_id: str
    open_url: str
    installation_id: UUID
    binding_id: int
    binding_generation: int


@dataclass(frozen=True)
class ResourceStepReceipt:
    step_receipt_id: UUID
    provision_run_id: UUID
    installation_id: UUID
    tenant_id: UUID
    binding_id: int
    step_key: str
    idempotency_key: str
    request_digest: bytes
    resource: ExternalResource
    action: Literal["created", "discovered"]
    state: Stage1LifecycleState
    completed_at: datetime


class ResourceInitializationRepository(Protocol):
    def completed_resource_step(
        self, installation_id: UUID, idempotency_key: str
    ) -> ResourceStepReceipt | None: ...

    def save_resource_step(self, receipt: ResourceStepReceipt) -> None: ...

    def current_resource_context(
        self, context: ResourceBindingContext
    ) -> ResourceBindingContext | None: ...


class FeishuResourceGateway(Protocol):
    def discover(
        self, context: ResourceBindingContext, kind: str
    ) -> Sequence[ExternalResource]: ...

    def create(
        self, context: ResourceBindingContext, kind: str, idempotency_key: str
    ) -> ExternalResource: ...

    def readback(
        self, context: ResourceBindingContext, external_id: str
    ) -> ExternalResource | None: ...


class OrganizationResourceInitializer:
    def __init__(
        self,
        repository: ResourceInitializationRepository,
        gateway: FeishuResourceGateway,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._gateway = gateway
        self._now = now or (lambda: datetime.now(UTC))

    def initialize(
        self,
        context: ResourceBindingContext,
        *,
        provision_run_id: UUID,
        idempotency_key: str,
        kinds: Sequence[str] | None = None,
    ) -> tuple[ResourceStepReceipt, ...]:
        key = _resource_run_key(idempotency_key)
        self._validate_context(context)
        receipts: list[ResourceStepReceipt] = []
        requested_kinds = REQUIRED_RESOURCE_KINDS if kinds is None else tuple(kinds)
        if not requested_kinds or any(kind not in REQUIRED_RESOURCE_KINDS for kind in requested_kinds):
            _fail("resource_initialization_kind_invalid", "resource initialization step is invalid", status=400)
        for kind in requested_kinds:
            active_context = self._fenced_context(context)
            step_key = _child_idempotency_key(key, kind)
            digest = _digest(
                {
                    "installationId": str(context.installation_id),
                    "tenantId": str(context.tenant_id),
                    "bindingId": context.binding_id,
                    "bindingGeneration": context.binding_generation,
                    "spaceId": context.space_id,
                    "parentNodeToken": context.parent_node_token,
                    "resourceTarget": (
                        None
                        if context.resource_target is None
                        else {
                            "installationId": str(context.resource_target.installation_id),
                            "tenantId": str(context.resource_target.tenant_id),
                            "tenantKey": context.resource_target.tenant_key,
                            "bindingId": context.resource_target.binding_id,
                            "generation": context.resource_target.binding_generation,
                        }
                    ),
                    "kind": kind,
                }
            )
            existing = self._repository.completed_resource_step(active_context.installation_id, step_key)
            if existing is not None:
                if existing.request_digest != digest or existing.binding_id != active_context.binding_id:
                    _fail("resource_initialization_idempotency_conflict", "resource step key was reused")
                receipts.append(existing)
                continue
            active_context = self._fenced_context(context)
            discovered = tuple(self._gateway.discover(active_context, kind))
            if len(discovered) > 1:
                _fail("resource_initialization_ambiguous", f"multiple {kind} resources were discovered")
            if discovered:
                resource = discovered[0]
            else:
                active_context = self._fenced_context(context)
                resource = self._gateway.create(active_context, kind, step_key)
            action: Literal["created", "discovered"] = "discovered" if discovered else "created"
            active_context = self._fenced_context(context)
            readback = self._gateway.readback(active_context, resource.external_id)
            if readback is None:
                _fail("resource_initialization_readback_failed", f"{kind} resource readback failed")
            self._validate_resource(active_context, kind, readback)
            if readback != resource:
                _fail("resource_initialization_readback_failed", f"{kind} resource readback changed")
            receipt = ResourceStepReceipt(
                step_receipt_id=uuid4(),
                provision_run_id=provision_run_id,
                installation_id=active_context.installation_id,
                tenant_id=active_context.tenant_id,
                binding_id=active_context.binding_id,
                step_key=kind,
                idempotency_key=step_key,
                request_digest=digest,
                resource=readback,
                action=action,
                state=Stage1LifecycleState.ACTIVE,
                completed_at=_utc(self._now(), "now"),
            )
            self._repository.save_resource_step(receipt)
            receipts.append(receipt)
        return tuple(receipts)

    @staticmethod
    def _validate_context(context: ResourceBindingContext) -> None:
        if not isinstance(context, ResourceBindingContext):
            _fail("resource_initialization_context_invalid", "binding context is invalid", status=400)
        if context.state not in {Stage1LifecycleState.NEEDS_ATTENTION, Stage1LifecycleState.ACTIVE}:
            _fail("resource_initialization_binding_inactive", "usable binding generation is required")
        if context.binding_id <= 0 or context.binding_generation <= 0:
            _fail("resource_initialization_binding_invalid", "binding generation is invalid")
        _text(context.tenant_key, "tenant_key", 128)
        _text(context.credential_ref, "credential_ref", 256)
        _text(context.space_id, "space_id", 256)
        _text(context.parent_node_token, "parent_node_token", 256)
        target = context.resource_target
        if not isinstance(target, ResourceTarget):
            _fail("resource_initialization_target_invalid", "server-owned resource target is required", status=409)
        if (
            target.installation_id != context.installation_id
            or target.tenant_id != context.tenant_id
            or target.tenant_key != context.tenant_key
            or target.binding_id != context.binding_id
            or target.binding_generation != context.binding_generation
            or target.space_id != context.space_id
            or target.parent_node_token != context.parent_node_token
        ):
            _fail("resource_initialization_target_invalid", "resource target is not bound to the current generation", status=409)

    def _fenced_context(self, context: ResourceBindingContext) -> ResourceBindingContext:
        validator = getattr(self._repository, "current_resource_context", None)
        if not callable(validator):
            _fail(
                "resource_initialization_binding_unavailable",
                "Stage 1 binding revalidation is unavailable",
                status=503,
            )
        current = validator(context)
        if current is None:
            _fail("resource_initialization_binding_unavailable", "Stage 1 binding changed or is inactive")
        if not isinstance(current, ResourceBindingContext):
            _fail("resource_initialization_binding_unavailable", "Stage 1 binding readback is invalid")
        if (
            current.installation_id != context.installation_id
            or current.tenant_id != context.tenant_id
            or current.binding_id != context.binding_id
            or current.binding_generation != context.binding_generation
            or current.tenant_key != context.tenant_key
            or current.credential_ref != context.credential_ref
            or current.space_id != context.space_id
            or current.parent_node_token != context.parent_node_token
            or current.resource_target != context.resource_target
            or current.state not in {Stage1LifecycleState.NEEDS_ATTENTION, Stage1LifecycleState.ACTIVE}
        ):
            _fail("resource_initialization_binding_changed", "Stage 1 binding changed or is inactive")
        return current

    @staticmethod
    def _validate_resource(context: ResourceBindingContext, kind: str, resource: ExternalResource) -> None:
        if (
            resource.kind != kind
            or resource.installation_id != context.installation_id
            or resource.binding_id != context.binding_id
            or resource.binding_generation != context.binding_generation
        ):
            _fail("resource_initialization_cross_binding", "resource belongs to another installation")
        if not resource.open_url.startswith("https://"):
            _fail("resource_initialization_untrusted_link", "resource open link is not trusted")


class ProvisionRunState(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class ProvisionRun:
    provision_run_id: UUID
    installation_id: UUID
    tenant_id: UUID
    idempotency_key: str
    request_digest: bytes
    status: ProvisionRunState
    state: Stage1LifecycleState
    lease_owner: str | None = None
    lease_expires_at: datetime | None = None
    failed_step: str | None = None
    retry_count: int = 0
    retry_after: datetime | None = None


@dataclass(frozen=True)
class ProvisionStatusView:
    provision_run_id: UUID
    installation_id: UUID
    tenant_id: UUID
    status: ProvisionRunState
    state: Stage1LifecycleState
    completed_steps: tuple[str, ...]
    failed_step: str | None
    retry_available: bool
    retry_after: datetime | None


class ProvisionRunRepository(Protocol):
    def run_for_key(self, installation_id: UUID, idempotency_key: str) -> ProvisionRun | None: ...

    def create_run(self, run: ProvisionRun) -> ProvisionRun: ...

    def claim_run(
        self, provision_run_id: UUID, lease_owner: str, lease_expires_at: datetime, now: datetime
    ) -> ProvisionRun | None: ...

    def completed_step_keys(self, provision_run_id: UUID) -> Sequence[str]: ...

    def mark_step_succeeded(self, provision_run_id: UUID, step_key: str) -> None: ...

    def mark_run_succeeded(self, provision_run_id: UUID) -> ProvisionRun: ...

    def mark_run_failed(
        self,
        provision_run_id: UUID,
        step_key: str,
        failure_code: str,
        retry_after: datetime,
    ) -> ProvisionRun: ...

    def run_for_id(self, provision_run_id: UUID) -> ProvisionRun | None: ...


ProvisionStep = Callable[[UUID, str], object]


class ProvisionOrchestrator:
    """Lease-bound runner that resumes only from durable step checkpoints."""

    def __init__(
        self,
        repository: ProvisionRunRepository,
        *,
        steps: Mapping[str, ProvisionStep],
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if not steps:
            raise ValueError("at least one provision step is required")
        self._repository = repository
        self._steps = tuple((key, steps[key]) for key in steps)
        self._now = now or (lambda: datetime.now(UTC))

    def run(
        self,
        actor: TrustedProvisionActor,
        *,
        idempotency_key: str,
        lease_owner: str,
    ) -> ProvisionRun:
        self._validate_actor(actor)
        key = _resource_run_key(idempotency_key)
        worker = _text(lease_owner, "lease_owner", 160)
        digest = _digest(
            {
                "installationId": str(actor.installation_id),
                "tenantId": str(actor.tenant_id),
                "steps": [name for name, _ in self._steps],
            }
        )
        existing = self._repository.run_for_key(actor.installation_id, key)
        if existing is not None and existing.request_digest != digest:
            _fail("provision_idempotency_conflict", "provision key was reused")
        run = existing or self._repository.create_run(
            ProvisionRun(
                provision_run_id=uuid4(),
                installation_id=actor.installation_id,
                tenant_id=actor.tenant_id,
                idempotency_key=key,
                request_digest=digest,
                status=ProvisionRunState.PENDING,
                state=Stage1LifecycleState.NEEDS_ATTENTION,
            )
        )
        if run.tenant_id != actor.tenant_id:
            _fail("provision_cross_tenant", "provision run belongs to another tenant", status=403)
        if run.status is ProvisionRunState.SUCCEEDED:
            return run
        now = _utc(self._now(), "now")
        if run.retry_after is not None and run.retry_after > now:
            _fail("provision_retry_backoff", "provision retry is not available yet", status=429)
        claimed = self._repository.claim_run(
            run.provision_run_id,
            worker,
            now + timedelta(seconds=MAX_LEASE_SECONDS),
            now,
        )
        if claimed is None:
            _fail("provision_lease_conflict", "another worker owns the provision lease")
        completed = set(self._repository.completed_step_keys(run.provision_run_id))
        for step_key, step in self._steps:
            if step_key in completed:
                continue
            step_idempotency_key = _child_idempotency_key(key, step_key)
            try:
                step(run.provision_run_id, step_idempotency_key)
                self._repository.mark_step_succeeded(run.provision_run_id, step_key)
            except ProvisioningError as exc:
                retry_count = claimed.retry_count + 1
                retry_after = now + timedelta(seconds=retry_delay_seconds(retry_count))
                return self._repository.mark_run_failed(
                    run.provision_run_id,
                    step_key,
                    exc.code,
                    retry_after,
                )
            except Exception:
                retry_count = claimed.retry_count + 1
                retry_after = now + timedelta(seconds=retry_delay_seconds(retry_count))
                return self._repository.mark_run_failed(
                    run.provision_run_id,
                    step_key,
                    "provision_step_unavailable",
                    retry_after,
                )
        return self._repository.mark_run_succeeded(run.provision_run_id)

    @staticmethod
    def _validate_actor(actor: TrustedProvisionActor) -> None:
        if not isinstance(actor, TrustedProvisionActor):
            _fail("provision_actor_untrusted", "trusted owner or support actor is required", status=403)


class ProvisionStatusService:
    def __init__(self, repository: ProvisionRunRepository) -> None:
        self._repository = repository

    def status(self, actor: TrustedProvisionActor, provision_run_id: UUID) -> ProvisionStatusView:
        ProvisionOrchestrator._validate_actor(actor)
        run = self._repository.run_for_id(provision_run_id)
        if run is None or run.installation_id != actor.installation_id:
            _fail("provision_not_found", "provision run was not found", status=404)
        if run.tenant_id != actor.tenant_id:
            _fail("provision_not_found", "provision run was not found", status=404)
        completed = tuple(self._repository.completed_step_keys(provision_run_id))
        return ProvisionStatusView(
            provision_run_id=run.provision_run_id,
            installation_id=run.installation_id,
            tenant_id=run.tenant_id,
            status=run.status,
            state=run.state,
            completed_steps=completed,
            failed_step=run.failed_step,
            retry_available=run.status is ProvisionRunState.FAILED,
            retry_after=run.retry_after,
        )


@dataclass(frozen=True)
class DeprovisionReceipt:
    receipt_id: UUID
    installation_id: UUID
    tenant_id: UUID
    state: Stage1LifecycleState
    idempotency_key: str
    request_digest: bytes
    revoked_session_count: int
    revoked_at: datetime
    external_credential_revoked: bool


class DeprovisionStore(Protocol):
    def deprovision_receipt(
        self, installation_id: UUID, idempotency_key: str
    ) -> DeprovisionReceipt | None: ...

    def installation_for_deprovision(self, installation_id: UUID) -> InstallationTarget | None: ...

    def deactivate_binding_and_members(
        self, installation_id: UUID, tenant_id: UUID, state: Stage1LifecycleState, occurred_at: datetime
    ) -> int: ...

    def revoke_cached_credentials(self, installation_id: UUID, occurred_at: datetime) -> None: ...

    def save_deprovision_receipt(self, receipt: DeprovisionReceipt) -> None: ...

    def write_deprovision_audit(self, receipt: DeprovisionReceipt, actor_user_id: UUID) -> None: ...

    def mark_external_credential_revoked(self, receipt_id: UUID) -> DeprovisionReceipt: ...


class DeprovisionRepository(Protocol):
    def transaction(self) -> AbstractContextManager[DeprovisionStore]: ...


class CredentialRevocationGateway(Protocol):
    def revoke(self, installation_id: UUID, idempotency_key: str) -> bool: ...


class OrganizationDeprovisionService:
    """Close local access first, then attempt external credential revocation."""

    def __init__(
        self,
        repository: DeprovisionRepository,
        credential_gateway: CredentialRevocationGateway,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._credential_gateway = credential_gateway
        self._now = now or (lambda: datetime.now(UTC))

    def deprovision(
        self,
        actor: TrustedProvisionActor,
        *,
        idempotency_key: str,
        revoke: bool,
    ) -> DeprovisionReceipt:
        ProvisionOrchestrator._validate_actor(actor)
        try:
            key = _projection_key(idempotency_key)
        except ValueError as exc:
            _fail("deprovision_invalid_idempotency_key", "idempotency key is invalid", status=400)
            raise AssertionError("unreachable") from exc
        target_state = Stage1LifecycleState.REVOKED if revoke else Stage1LifecycleState.DISABLED
        digest = _digest(
            {
                "installationId": str(actor.installation_id),
                "tenantId": str(actor.tenant_id),
                "state": target_state.value,
            }
        )
        now = _utc(self._now(), "now")
        try:
            with self._repository.transaction() as store:
                existing = store.deprovision_receipt(actor.installation_id, key)
                if existing is not None:
                    if existing.request_digest != digest:
                        _fail("deprovision_idempotency_conflict", "deprovision key was reused")
                    local_receipt = existing
                else:
                    installation = store.installation_for_deprovision(actor.installation_id)
                    if installation is None or installation.tenant_id != actor.tenant_id:
                        _fail("deprovision_not_found", "installation was not found", status=404)
                    revoked_sessions = store.deactivate_binding_and_members(
                        actor.installation_id, actor.tenant_id, target_state, now
                    )
                    store.revoke_cached_credentials(actor.installation_id, now)
                    local_receipt = DeprovisionReceipt(
                        receipt_id=uuid4(),
                        installation_id=actor.installation_id,
                        tenant_id=actor.tenant_id,
                        state=target_state,
                        idempotency_key=key,
                        request_digest=digest,
                        revoked_session_count=revoked_sessions,
                        revoked_at=now,
                        external_credential_revoked=False,
                    )
                    store.save_deprovision_receipt(local_receipt)
                    store.write_deprovision_audit(local_receipt, actor.user_id)
        except ProvisioningError:
            raise
        except Exception as exc:
            raise ProvisioningError(
                "deprovision_storage_unavailable",
                "deprovision storage is unavailable",
                status=503,
            ) from exc
        if local_receipt.external_credential_revoked:
            return local_receipt
        try:
            external_revoked = self._credential_gateway.revoke(actor.installation_id, key)
        except Exception:
            external_revoked = False
        if not external_revoked:
            return local_receipt
        try:
            with self._repository.transaction() as store:
                final_receipt = store.mark_external_credential_revoked(local_receipt.receipt_id)
                if not final_receipt.external_credential_revoked:
                    _fail("deprovision_readback_failed", "credential revocation was not durable")
                return final_receipt
        except ProvisioningError:
            raise
        except Exception as exc:
            raise ProvisioningError(
                "deprovision_storage_unavailable",
                "credential revocation readback is unavailable",
                status=503,
            ) from exc


Stage1AdministratorConfirmationService = AdministratorConfirmationService
Stage1OrganizationResourceInitializer = OrganizationResourceInitializer
Stage1ProvisionOrchestrator = ProvisionOrchestrator
Stage1ProvisionStatusService = ProvisionStatusService
Stage1OrganizationDeprovisionService = OrganizationDeprovisionService


__all__ = [
    "AdminConfirmationReceipt",
    "AdminConfirmationRepository",
    "AdminConfirmationStore",
    "AdministratorConfirmationService",
    "BindingGeneration",
    "CredentialRevocationGateway",
    "DeprovisionReceipt",
    "DeprovisionRepository",
    "ExternalResource",
    "FeishuResourceGateway",
    "InstallationTarget",
    "OrganizationDeprovisionService",
    "OrganizationResourceInitializer",
    "OwnerIdentity",
    "OwnerRecord",
    "ProvisionOrchestrator",
    "ProvisionRun",
    "ProvisionRunRepository",
    "ProvisionRunState",
    "ProvisionStatusService",
    "ProvisionStatusView",
    "ProvisioningError",
    "ResourceBindingContext",
    "ResourceInitializationRepository",
    "ResourceStepReceipt",
    "Stage1AdministratorConfirmationService",
    "Stage1OrganizationDeprovisionService",
    "Stage1OrganizationResourceInitializer",
    "Stage1ProvisionOrchestrator",
    "Stage1ProvisionStatusService",
    "TrustedFeishuAdministrator",
    "TrustedProvisionActor",
]
