from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from typing import Literal, Mapping, NoReturn, Protocol, Sequence, TypeAlias
from uuid import UUID


BindingId: TypeAlias = UUID | int | str
BindingStatus: TypeAlias = Literal["pending", "active", "disabled", "revoked"]
MembershipStatus: TypeAlias = Literal["active", "disabled"]
ExternalIdentityStatus: TypeAlias = Literal["active", "inactive", "unknown"]


class _ServerMarker:
    __slots__ = ()


_SERVER_CONTEXT_MARKER = _ServerMarker()
_SERVER_AUTHORIZATION_MARKER = _ServerMarker()


def _invalid(code: str, detail: str, *, status: int = 400) -> NoReturn:
    raise MemberOnboardingError(code, detail, status=status)


def _validate_server_string(value: object, *, field_name: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    if value != value.strip() or not value or len(value) > maximum:
        raise ValueError(f"{field_name} is invalid")
    if any(character.isspace() or ord(character) < 32 for character in value):
        raise ValueError(f"{field_name} is invalid")
    return value


def _normalize_open_id(value: object) -> str:
    if not isinstance(value, str):
        _invalid("member_onboarding_open_id_invalid", "trusted authorization did not contain a valid open_id")
    if value != value.strip() or not value or len(value) > 512:
        _invalid("member_onboarding_open_id_invalid", "trusted authorization did not contain a valid open_id")
    if any(character.isspace() or ord(character) < 32 for character in value):
        _invalid("member_onboarding_open_id_invalid", "trusted authorization did not contain a valid open_id")
    return value


def _normalize_server_profile(value: object, *, field_name: str, maximum: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        _invalid("member_onboarding_authorization_invalid", f"trusted authorization {field_name} is invalid")
    if value != value.strip() or not value or len(value) > maximum:
        _invalid("member_onboarding_authorization_invalid", f"trusted authorization {field_name} is invalid")
    if any(ord(character) < 32 for character in value):
        _invalid("member_onboarding_authorization_invalid", f"trusted authorization {field_name} is invalid")
    return value


@dataclass(frozen=True, init=False)
class ServerFeishuInstallContext:
    """The server-owned Feishu tenant/install context used for Binding lookup."""

    tenant_key: str
    installation_id: str | None
    _server_marker: object = field(repr=False, compare=False)

    def __init__(
        self,
        tenant_key: str,
        installation_id: str | None = None,
        *,
        _server_marker: object | None = None,
    ) -> None:
        if _server_marker is not _SERVER_CONTEXT_MARKER:
            raise TypeError("ServerFeishuInstallContext must come from the server authorization boundary")
        normalized_tenant_key = _validate_server_string(tenant_key, field_name="tenant_key", maximum=128)
        normalized_installation_id = (
            None
            if installation_id is None
            else _validate_server_string(installation_id, field_name="installation_id", maximum=128)
        )
        object.__setattr__(self, "tenant_key", normalized_tenant_key)
        object.__setattr__(self, "installation_id", normalized_installation_id)
        object.__setattr__(self, "_server_marker", _server_marker)

    @classmethod
    def from_server_adapter(
        cls,
        tenant_key: str,
        installation_id: str | None = None,
    ) -> "ServerFeishuInstallContext":
        return cls(tenant_key, installation_id, _server_marker=_SERVER_CONTEXT_MARKER)

    @classmethod
    def from_server(
        cls,
        tenant_key: str,
        installation_id: str | None = None,
    ) -> "ServerFeishuInstallContext":
        return cls.from_server_adapter(tenant_key, installation_id)


@dataclass(frozen=True, init=False)
class TrustedFeishuAuthorization:
    """A stable Feishu identity emitted only by the trusted server adapter."""

    open_id: str
    email: str | None
    display_name: str | None
    _server_marker: object = field(repr=False, compare=False)

    def __init__(
        self,
        open_id: str,
        email: str | None = None,
        display_name: str | None = None,
        *,
        _server_marker: object | None = None,
    ) -> None:
        if _server_marker is not _SERVER_AUTHORIZATION_MARKER:
            raise TypeError("TrustedFeishuAuthorization must come from the server authorization boundary")
        object.__setattr__(self, "open_id", open_id)
        object.__setattr__(self, "email", email)
        object.__setattr__(self, "display_name", display_name)
        object.__setattr__(self, "_server_marker", _server_marker)

    @classmethod
    def from_server_adapter(
        cls,
        open_id: str,
        *,
        email: str | None = None,
        display_name: str | None = None,
    ) -> "TrustedFeishuAuthorization":
        return cls(
            open_id,
            email,
            display_name,
            _server_marker=_SERVER_AUTHORIZATION_MARKER,
        )

    @classmethod
    def from_server(
        cls,
        open_id: str,
        *,
        email: str | None = None,
        display_name: str | None = None,
    ) -> "TrustedFeishuAuthorization":
        return cls.from_server_adapter(open_id, email=email, display_name=display_name)


@dataclass(frozen=True)
class MemberOnboardingRequest:
    install_context: ServerFeishuInstallContext
    authorization: TrustedFeishuAuthorization
    browser_payload: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class MemberBinding:
    binding_id: BindingId
    tenant_id: UUID
    tenant_key: str
    status: str
    installation_id: str | None = None
    owner_user_id: UUID | None = None


@dataclass(frozen=True)
class PlatformUserRecord:
    user_id: UUID
    username: str
    email: str | None
    display_name: str
    role: str = "user"
    status: str = "active"


@dataclass(frozen=True)
class TenantMembershipRecord:
    membership_id: UUID
    tenant_id: UUID
    user_id: UUID
    role: str
    status: str = "active"


@dataclass(frozen=True)
class TenantMemberIdentityRecord:
    identity_id: UUID
    binding_id: BindingId
    tenant_id: UUID
    user_id: UUID
    open_id: str
    external_status: str = "active"


@dataclass(frozen=True)
class MemberOnboardingReceipt:
    action: Literal["created", "reused"]
    binding_id: BindingId
    tenant_id: UUID
    user_id: UUID
    membership_id: UUID
    identity_id: UUID
    tenant_key: str
    open_id: str
    role: Literal["member"] = "member"

    @property
    def created(self) -> bool:
        return self.action == "created"


class MemberOnboardingError(RuntimeError):
    """Stable service errors that an HTTP adapter can expose without SQL details."""

    def __init__(self, code: str, detail: str, *, status: int) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.status = status

    def to_http_error(self) -> dict[str, object]:
        return {"code": self.code, "detail": self.detail}


class MemberOnboardingStoreConflict(RuntimeError):
    """A repository uniqueness or row-state guard rejected a transaction."""

    def __init__(self, entity: str = "identity") -> None:
        super().__init__(entity)
        self.entity = entity


class MemberOnboardingStore(Protocol):
    """The MB1-facing transaction surface; implementations own SQL and constraints."""

    def bindings_for_context(
        self,
        *,
        tenant_key: str,
        installation_id: str | None,
    ) -> Sequence[MemberBinding]:
        ...

    def identities_for_binding_open_id(
        self,
        *,
        binding_id: BindingId,
        open_id: str,
    ) -> Sequence[TenantMemberIdentityRecord]:
        ...

    def identities_for_open_id(self, *, open_id: str) -> Sequence[TenantMemberIdentityRecord]:
        ...

    def user_for_id(self, user_id: UUID) -> PlatformUserRecord | None:
        ...

    def memberships_for_user_tenant(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
    ) -> Sequence[TenantMembershipRecord]:
        ...

    def create_user(
        self,
        *,
        email: str | None,
        display_name: str,
    ) -> PlatformUserRecord:
        ...

    def create_membership(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        role: Literal["member"],
    ) -> TenantMembershipRecord:
        ...

    def create_identity(
        self,
        *,
        binding_id: BindingId,
        tenant_id: UUID,
        user_id: UUID,
        open_id: str,
        external_status: Literal["active"],
    ) -> TenantMemberIdentityRecord:
        ...


class MemberOnboardingRepository(Protocol):
    def transaction(self) -> AbstractContextManager[MemberOnboardingStore]:
        ...


class MemberOnboardingService:
    """Candidate Release 1B JIT member onboarding, without directory or Writer calls."""

    def __init__(self, repository: MemberOnboardingRepository) -> None:
        self._repository = repository

    def onboard(
        self,
        *,
        install_context: ServerFeishuInstallContext,
        authorization: TrustedFeishuAuthorization,
        browser_payload: Mapping[str, object] | None = None,
    ) -> MemberOnboardingReceipt:
        request = MemberOnboardingRequest(
            install_context=install_context,
            authorization=authorization,
            browser_payload={} if browser_payload is None else browser_payload,
        )
        return self.onboard_request(request)

    def onboard_request(self, request: MemberOnboardingRequest) -> MemberOnboardingReceipt:
        self._validate_request(request)
        open_id = _normalize_open_id(request.authorization.open_id)
        email = _normalize_server_profile(request.authorization.email, field_name="email", maximum=254)
        display_name = _normalize_server_profile(
            request.authorization.display_name,
            field_name="display_name",
            maximum=80,
        ) or f"Feishu member {open_id[:32]}"

        try:
            with self._repository.transaction() as store:
                binding = self._binding_for_context(store, request.install_context)
                identities = tuple(
                    store.identities_for_open_id(open_id=open_id)
                )
                self._reject_cross_tenant_or_ambiguous_identities(identities, binding, open_id)

                pair_identities = tuple(
                    store.identities_for_binding_open_id(
                        binding_id=binding.binding_id,
                        open_id=open_id,
                    )
                )
                if len(pair_identities) > 1:
                    _invalid(
                        "member_onboarding_identity_ambiguous",
                        "the existing Feishu identity is ambiguous",
                        status=409,
                    )
                if pair_identities:
                    return self._reuse_existing_member(
                        store,
                        binding=binding,
                        identity=pair_identities[0],
                        open_id=open_id,
                    )

                user = self._create_user(store, email=email, display_name=display_name)
                membership = self._create_membership(
                    store,
                    tenant_id=binding.tenant_id,
                    user_id=user.user_id,
                )
                identity = self._create_identity(
                    store,
                    binding=binding,
                    user_id=user.user_id,
                    open_id=open_id,
                )
                self._validate_created_rows(binding, user, membership, identity, open_id)
                return MemberOnboardingReceipt(
                    action="created",
                    binding_id=binding.binding_id,
                    tenant_id=binding.tenant_id,
                    user_id=user.user_id,
                    membership_id=membership.membership_id,
                    identity_id=identity.identity_id,
                    tenant_key=binding.tenant_key,
                    open_id=open_id,
                )
        except MemberOnboardingError:
            raise
        except MemberOnboardingStoreConflict as exc:
            raise self._store_conflict_error(exc) from exc
        except Exception as exc:
            raise MemberOnboardingError(
                "member_onboarding_storage_unavailable",
                "member onboarding storage is unavailable",
                status=503,
            ) from exc

    onboard_member = onboard

    @staticmethod
    def _validate_request(request: MemberOnboardingRequest) -> None:
        if not isinstance(request, MemberOnboardingRequest):
            _invalid("member_onboarding_request_invalid", "member onboarding request is invalid")
        if not isinstance(request.install_context, ServerFeishuInstallContext):
            _invalid(
                "member_onboarding_server_context_required",
                "member onboarding requires a server-owned Feishu install context",
                status=403,
            )
        if not isinstance(request.authorization, TrustedFeishuAuthorization):
            _invalid(
                "member_onboarding_untrusted_authorization",
                "member onboarding requires a trusted server authorization result",
                status=403,
            )
        if not isinstance(request.browser_payload, Mapping):
            _invalid("member_onboarding_request_invalid", "browser payload must be an object")
        if "open_id" in request.browser_payload or "openId" in request.browser_payload:
            _invalid(
                "member_onboarding_caller_open_id_forbidden",
                "open_id must come from the trusted server authorization adapter",
                status=403,
            )

    @staticmethod
    def _binding_for_context(
        store: MemberOnboardingStore,
        context: ServerFeishuInstallContext,
    ) -> MemberBinding:
        bindings = tuple(
            store.bindings_for_context(
                tenant_key=context.tenant_key,
                installation_id=context.installation_id,
            )
        )
        if not bindings:
            _invalid(
                "member_onboarding_binding_missing",
                "no Feishu Binding matches the server install context",
                status=409,
            )
        if len(bindings) > 1:
            _invalid(
                "member_onboarding_binding_ambiguous",
                "the server install context matches multiple Bindings",
                status=409,
            )
        binding = bindings[0]
        if binding.tenant_key != context.tenant_key:
            _invalid(
                "member_onboarding_conflicting_rows",
                "Binding tenant_key does not match the server install context",
                status=409,
            )
        if context.installation_id is not None and binding.installation_id != context.installation_id:
            _invalid(
                "member_onboarding_conflicting_rows",
                "Binding installation does not match the server install context",
                status=409,
            )
        if not isinstance(binding.tenant_id, UUID):
            _invalid("member_onboarding_conflicting_rows", "Binding tenant_id is invalid", status=409)
        if str(binding.status).strip().lower() != "active":
            _invalid(
                "member_onboarding_binding_inactive",
                "the Feishu Binding is not active",
                status=409,
            )
        return binding

    @staticmethod
    def _reject_cross_tenant_or_ambiguous_identities(
        identities: Sequence[TenantMemberIdentityRecord],
        binding: MemberBinding,
        open_id: str,
    ) -> None:
        for identity in identities:
            if identity.open_id != open_id:
                _invalid(
                    "member_onboarding_conflicting_rows",
                    "the existing identity lookup returned a different open_id",
                    status=409,
                )
            if identity.tenant_id != binding.tenant_id:
                _invalid(
                    "member_onboarding_cross_tenant_identity",
                    "the Feishu open_id is already used by another tenant",
                    status=403,
                )
            if identity.binding_id != binding.binding_id:
                _invalid(
                    "member_onboarding_conflicting_rows",
                    "the Feishu open_id is already attached to another Binding",
                    status=409,
                )

    @classmethod
    def _reuse_existing_member(
        cls,
        store: MemberOnboardingStore,
        *,
        binding: MemberBinding,
        identity: TenantMemberIdentityRecord,
        open_id: str,
    ) -> MemberOnboardingReceipt:
        if identity.binding_id != binding.binding_id or identity.tenant_id != binding.tenant_id:
            _invalid(
                "member_onboarding_conflicting_rows",
                "the existing identity does not belong to the active Binding",
                status=409,
            )
        if identity.open_id != open_id:
            _invalid(
                "member_onboarding_conflicting_rows",
                "the existing identity open_id does not match the authorization result",
                status=409,
            )
        if str(identity.external_status).strip().lower() != "active":
            _invalid(
                "member_onboarding_identity_inactive",
                "the existing Feishu identity is not active",
                status=409,
            )

        user = store.user_for_id(identity.user_id)
        if user is None:
            _invalid(
                "member_onboarding_conflicting_rows",
                "the existing identity points to a missing platform user",
                status=409,
            )
        memberships = tuple(
            store.memberships_for_user_tenant(
                tenant_id=binding.tenant_id,
                user_id=identity.user_id,
            )
        )
        if len(memberships) != 1:
            _invalid(
                "member_onboarding_identity_ambiguous"
                if len(memberships) > 1
                else "member_onboarding_conflicting_rows",
                "the existing platform membership is not unique",
                status=409,
            )
        membership = memberships[0]
        if membership.tenant_id != binding.tenant_id or membership.user_id != identity.user_id:
            _invalid(
                "member_onboarding_conflicting_rows",
                "the existing membership does not match the identity",
                status=409,
            )
        if str(membership.role).strip().lower() == "owner" or binding.owner_user_id == identity.user_id:
            _invalid(
                "member_onboarding_owner_reonboarding",
                "the ordinary-member path cannot re-onboard an owner",
                status=409,
            )
        if str(membership.role).strip().lower() != "member":
            _invalid(
                "member_onboarding_conflicting_rows",
                "the existing membership role is not an ordinary member role",
                status=409,
            )
        if str(membership.status).strip().lower() != "active":
            _invalid(
                "member_onboarding_membership_inactive",
                "the existing membership is not active",
                status=409,
            )
        if str(user.status).strip().lower() != "active":
            _invalid(
                "member_onboarding_user_inactive",
                "the existing platform user is not active",
                status=409,
            )
        return MemberOnboardingReceipt(
            action="reused",
            binding_id=binding.binding_id,
            tenant_id=binding.tenant_id,
            user_id=user.user_id,
            membership_id=membership.membership_id,
            identity_id=identity.identity_id,
            tenant_key=binding.tenant_key,
            open_id=open_id,
        )

    @staticmethod
    def _create_user(
        store: MemberOnboardingStore,
        *,
        email: str | None,
        display_name: str,
    ) -> PlatformUserRecord:
        try:
            return store.create_user(email=email, display_name=display_name)
        except MemberOnboardingStoreConflict as exc:
            raise MemberOnboardingError(
                "member_onboarding_user_conflict",
                "a platform user with the server-provided account data already conflicts",
                status=409,
            ) from exc

    @staticmethod
    def _create_membership(
        store: MemberOnboardingStore,
        *,
        tenant_id: UUID,
        user_id: UUID,
    ) -> TenantMembershipRecord:
        try:
            return store.create_membership(tenant_id=tenant_id, user_id=user_id, role="member")
        except MemberOnboardingStoreConflict as exc:
            raise MemberOnboardingError(
                "member_onboarding_membership_conflict",
                "the tenant membership could not be created without a conflict",
                status=409,
            ) from exc

    @staticmethod
    def _create_identity(
        store: MemberOnboardingStore,
        *,
        binding: MemberBinding,
        user_id: UUID,
        open_id: str,
    ) -> TenantMemberIdentityRecord:
        try:
            return store.create_identity(
                binding_id=binding.binding_id,
                tenant_id=binding.tenant_id,
                user_id=user_id,
                open_id=open_id,
                external_status="active",
            )
        except MemberOnboardingStoreConflict as exc:
            raise MemberOnboardingStoreConflict("identity") from exc

    @staticmethod
    def _validate_created_rows(
        binding: MemberBinding,
        user: PlatformUserRecord,
        membership: TenantMembershipRecord,
        identity: TenantMemberIdentityRecord,
        open_id: str,
    ) -> None:
        if not isinstance(user.user_id, UUID) or str(user.status).strip().lower() != "active":
            _invalid(
                "member_onboarding_conflicting_rows",
                "repository returned an invalid platform user",
                status=409,
            )
        if str(user.role).strip().lower() != "user":
            _invalid(
                "member_onboarding_owner_reonboarding",
                "ordinary onboarding cannot create an elevated user",
                status=409,
            )
        if (
            membership.tenant_id != binding.tenant_id
            or membership.user_id != user.user_id
            or str(membership.role).strip().lower() != "member"
            or str(membership.status).strip().lower() != "active"
        ):
            _invalid("member_onboarding_conflicting_rows", "repository returned an invalid membership", status=409)
        if (
            identity.binding_id != binding.binding_id
            or identity.tenant_id != binding.tenant_id
            or identity.user_id != user.user_id
            or identity.open_id != open_id
            or str(identity.external_status).strip().lower() != "active"
        ):
            _invalid("member_onboarding_conflicting_rows", "repository returned an invalid identity", status=409)

    @staticmethod
    def _store_conflict_error(exc: MemberOnboardingStoreConflict) -> MemberOnboardingError:
        if exc.entity == "identity":
            return MemberOnboardingError(
                "member_onboarding_concurrent_duplicate",
                "another request claimed this Feishu member concurrently",
                status=409,
            )
        if exc.entity == "user":
            return MemberOnboardingError(
                "member_onboarding_user_conflict",
                "platform user creation conflicted with an existing row",
                status=409,
            )
        return MemberOnboardingError(
            "member_onboarding_storage_conflict",
            "member onboarding encountered a storage conflict",
            status=409,
        )


ServerFeishuTenantContext = ServerFeishuInstallContext
TrustedServerFeishuAuthorization = TrustedFeishuAuthorization
Stage1MemberOnboardingService = MemberOnboardingService


__all__ = [
    "BindingId",
    "BindingStatus",
    "ExternalIdentityStatus",
    "MembershipStatus",
    "MemberBinding",
    "MemberOnboardingError",
    "MemberOnboardingReceipt",
    "MemberOnboardingRepository",
    "MemberOnboardingRequest",
    "MemberOnboardingService",
    "MemberOnboardingStore",
    "MemberOnboardingStoreConflict",
    "PlatformUserRecord",
    "ServerFeishuInstallContext",
    "ServerFeishuTenantContext",
    "Stage1MemberOnboardingService",
    "TenantMemberIdentityRecord",
    "TenantMembershipRecord",
    "TrustedFeishuAuthorization",
    "TrustedServerFeishuAuthorization",
]
