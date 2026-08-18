from __future__ import annotations

import hashlib
import inspect
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Literal, Mapping, Protocol, Sequence, cast
from uuid import UUID

from openclaw_app.adapters.media_business_context import SessionPrincipal

from .auth import AccountSession


SCHEMA_VERSION = "media-stage1-shared-v1"
WorkspaceMode = Literal["personal_web", "organization_lark"]
BodyAuthority = Literal["internal", "lark"]
MemberRole = Literal["owner", "member"]
ResolutionState = Literal[
    "RESOLVED",
    "REQUIRES_SELECTION",
    "NO_ELIGIBLE_WORKSPACE",
    "INVALID_SESSION",
]


class WorkspaceResolutionError(RuntimeError):
    """Raised when a caller tries to use a non-resolved workspace result."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


def _value(source: Any, names: Sequence[str], default: Any = None) -> Any:
    if isinstance(source, Mapping):
        for name in names:
            if name in source:
                return source[name]
        return default
    for name in names:
        if hasattr(source, name):
            return getattr(source, name)
    return default


def _uuid(value: Any, field: str) -> UUID:
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (AttributeError, TypeError, ValueError) as exc:
        raise WorkspaceResolutionError("validation_error", f"{field} is not a UUID") from exc


def _upper(value: Any, default: str | None = None) -> str | None:
    if value is None:
        return default
    return str(value).strip().upper()


def _binding_state(value: Any) -> str:
    normalized = _upper(value)
    if normalized in {"ACTIVE", "PENDING", "REVOKED", "SUSPENDED", "REVOKING", "NEEDS_ATTENTION"}:
        return cast(str, normalized)
    if normalized in {"DISABLED", "INACTIVE"}:
        return "SUSPENDED"
    return "NEEDS_ATTENTION"


def _workspace_status(value: Any) -> str:
    normalized = _upper(value, "ACTIVE")
    if normalized in {"ACTIVE", "SUSPENDED", "REVOKED", "NEEDS_ATTENTION"}:
        return cast(str, normalized)
    return "NEEDS_ATTENTION"


def _membership_state(value: Any) -> str:
    normalized = _upper(value, "ACTIVE")
    if normalized == "DISABLED":
        return "SUSPENDED"
    if normalized in {"ACTIVE", "SUSPENDED", "REVOKED", "NEEDS_ATTENTION"}:
        return cast(str, normalized)
    return "NEEDS_ATTENTION"


@dataclass(frozen=True)
class WorkspaceResolutionRow:
    """A current workspace/membership/binding observation from the server."""

    workspace_id: UUID
    tenant_id: UUID
    workspace_mode: str
    body_authority: str
    membership_role: str
    membership_state: str = "ACTIVE"
    binding_id: str | int | UUID | None = None
    binding_status: str | None = None
    workspace_status: str = "ACTIVE"
    ownership_state: str = "PROVEN"
    visibility_state: str = "VISIBLE"
    owner_user_id: UUID | None = None
    user_id: UUID | None = None
    identity_link_receipt_ids: tuple[str, ...] = ()

    @property
    def member_role(self) -> str:
        return self.membership_role

    @property
    def binding_state(self) -> str | None:
        return self.binding_status

    @property
    def tenant(self) -> UUID:
        return self.tenant_id


WorkspaceResolutionCandidateRow = WorkspaceResolutionRow


@dataclass(frozen=True)
class WorkspaceMembership:
    membership_id: str
    tenant_id: UUID
    user_id: UUID
    role: MemberRole
    status: str

    def to_dict(self) -> dict[str, object]:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "membershipId": self.membership_id,
            "tenantId": str(self.tenant_id),
            "userId": str(self.user_id),
            "identityLinkReceiptId": None,
            "bindingId": None,
            "role": self.role,
            "status": self.status,
        }


@dataclass(frozen=True)
class BindingState:
    binding_id: str
    tenant_id: UUID
    status: str

    @property
    def state(self) -> str:
        return self.status

    @property
    def binding_status(self) -> str:
        return self.status

    def to_dict(self) -> dict[str, object]:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "bindingId": self.binding_id,
            "tenantId": str(self.tenant_id),
            "provider": "lark",
            "state": self.status,
        }


@dataclass(frozen=True)
class WorkspaceCandidate:
    """Immutable public candidate data; no candidate is client-authoritative."""

    workspace_id: UUID
    tenant_id: UUID
    workspace_mode: WorkspaceMode
    body_authority: BodyAuthority
    membership_role: MemberRole
    membership_state: str
    binding_state: str
    ownership_state: str
    workspace_status: str
    binding_id: str | int | UUID | None = None
    resolution_eligibility: str = "ELIGIBLE"
    identity_link_receipt_id: str | None = None
    user_id: UUID | None = None

    def __post_init__(self) -> None:
        if self.workspace_mode not in {"personal_web", "organization_lark"}:
            raise WorkspaceResolutionError("validation_error", "workspace mode is invalid")
        expected_authority = "internal" if self.workspace_mode == "personal_web" else "lark"
        if self.body_authority != expected_authority:
            raise WorkspaceResolutionError("validation_error", "workspace authority is invalid")
        if self.membership_role not in {"owner", "member"}:
            raise WorkspaceResolutionError("validation_error", "workspace member role is invalid")
        if self.membership_state not in {"ACTIVE", "DISABLED", "SUSPENDED", "REVOKED", "NEEDS_ATTENTION"}:
            raise WorkspaceResolutionError("validation_error", "workspace membership state is invalid")
        if self.binding_state not in {
            "NOT_APPLICABLE",
            "PENDING",
            "ACTIVE",
            "SUSPENDED",
            "REVOKING",
            "REVOKED",
            "NEEDS_ATTENTION",
        }:
            raise WorkspaceResolutionError("validation_error", "workspace binding state is invalid")
        if self.ownership_state not in {"PROVEN", "CONFLICT", "NO_EVIDENCE"}:
            raise WorkspaceResolutionError("validation_error", "workspace ownership state is invalid")
        if self.workspace_status not in {"ACTIVE", "SUSPENDED", "REVOKED", "NEEDS_ATTENTION"}:
            raise WorkspaceResolutionError("validation_error", "workspace status is invalid")
        if self.resolution_eligibility not in {"ELIGIBLE", "SUSPENDED", "REVOKED"}:
            raise WorkspaceResolutionError("validation_error", "workspace eligibility is invalid")
        if self.workspace_mode == "personal_web" and (
            self.binding_id is not None or self.binding_state != "NOT_APPLICABLE"
        ):
            raise WorkspaceResolutionError("validation_error", "personal workspace cannot have a Lark binding")
        if self.workspace_mode == "organization_lark" and self.binding_state == "NOT_APPLICABLE":
            raise WorkspaceResolutionError("validation_error", "organization workspace requires binding state")

    @property
    def schema_version(self) -> str:
        return SCHEMA_VERSION

    @property
    def workspaceId(self) -> UUID:
        return self.workspace_id

    @property
    def workspaceMode(self) -> WorkspaceMode:
        return self.workspace_mode

    @property
    def bodyAuthority(self) -> BodyAuthority:
        return self.body_authority

    @property
    def tenant(self) -> UUID:
        return self.tenant_id

    @property
    def member_role(self) -> MemberRole:
        return self.membership_role

    @property
    def membershipRole(self) -> MemberRole:
        return self.membership_role

    @property
    def membershipState(self) -> str:
        return self.membership_state

    @property
    def binding_status(self) -> str:
        return self.binding_state

    @property
    def bindingStatus(self) -> str:
        return self.binding_state

    @property
    def bindingState(self) -> str:
        return self.binding_state

    @property
    def ownershipState(self) -> str:
        return self.ownership_state

    @property
    def resolutionEligibility(self) -> str:
        return self.resolution_eligibility

    @property
    def membership(self) -> WorkspaceMembership:
        return WorkspaceMembership(
            membership_id=str(self.workspace_id),
            tenant_id=self.tenant_id,
            user_id=self.user_id or UUID(int=0),
            role=self.membership_role,
            status=self.membership_state,
        )

    @property
    def binding(self) -> BindingState | None:
        if self.binding_id is None:
            return None
        return BindingState(str(self.binding_id), self.tenant_id, self.binding_state)

    def to_dict(self) -> dict[str, object]:
        base: dict[str, object] = {
            "schemaVersion": SCHEMA_VERSION,
            "workspaceId": str(self.workspace_id),
            "tenantId": str(self.tenant_id),
            "workspaceMode": self.workspace_mode,
            "bodyAuthority": self.body_authority,
            "membershipRole": self.membership_role,
            "membershipState": self.membership_state,
            "bindingState": self.binding_state,
            "ownershipState": self.ownership_state,
            "workspaceStatus": self.workspace_status,
            "resolutionEligibility": self.resolution_eligibility,
            "bindingId": None if self.binding_id is None else str(self.binding_id),
        }
        return base


@dataclass(frozen=True)
class WorkspaceCandidatePersonal(WorkspaceCandidate):
    def __post_init__(self) -> None:
        super().__post_init__()
        if self.workspace_mode != "personal_web" or self.body_authority != "internal":
            raise WorkspaceResolutionError("validation_error", "personal candidate authority is invalid")
        if self.membership_role != "owner":
            raise WorkspaceResolutionError("validation_error", "personal workspace owner is invalid")
        if self.membership_state != "ACTIVE" or self.workspace_status != "ACTIVE":
            raise WorkspaceResolutionError("membership_inactive", "personal workspace is not active")

    def to_dict(self) -> dict[str, object]:
        result = super().to_dict()
        result.update(
            {
                "workspaceMode": "personal_web",
                "bodyAuthority": "internal",
                "membershipRole": "owner",
                "bindingState": "NOT_APPLICABLE",
            }
        )
        return result


@dataclass(frozen=True)
class WorkspaceCandidateOrganization(WorkspaceCandidate):
    def __post_init__(self) -> None:
        super().__post_init__()
        if self.workspace_mode != "organization_lark" or self.body_authority != "lark":
            raise WorkspaceResolutionError("validation_error", "organization candidate authority is invalid")

    def to_dict(self) -> dict[str, object]:
        result = super().to_dict()
        membership = {
            "schemaVersion": SCHEMA_VERSION,
            "membershipId": str(self.workspace_id),
            "tenantId": str(self.tenant_id),
            "userId": None if self.user_id is None else str(self.user_id),
            "identityLinkReceiptId": self.identity_link_receipt_id,
            "bindingId": None if self.binding_id is None else str(self.binding_id),
            "role": self.membership_role,
            "status": self.membership_state,
        }
        binding = None
        if self.binding_id is not None:
            binding = {
                "schemaVersion": SCHEMA_VERSION,
                "bindingId": str(self.binding_id),
                "tenantId": str(self.tenant_id),
                "provider": "lark",
                "state": self.binding_state,
            }
        result.update(
            {
                "workspaceMode": "organization_lark",
                "bodyAuthority": "lark",
                "membership": membership,
                "binding": binding,
            }
        )
        return result


@dataclass(frozen=True)
class WorkspaceResolutionResult:
    principal: SessionPrincipal | None
    workspace_intent: WorkspaceMode | None
    candidates: tuple[WorkspaceCandidate, ...]
    resolution_state: ResolutionState
    selected_workspace_id: UUID | None = None
    selected_workspace_mode: WorkspaceMode | None = None
    failure_code: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "candidates", tuple(self.candidates))
        candidate_keys = [(candidate.workspace_id, candidate.tenant_id) for candidate in self.candidates]
        if len(set(candidate_keys)) != len(candidate_keys):
            raise WorkspaceResolutionError("conflict", "workspace candidates are duplicated")
        if self.resolution_state == "RESOLVED" and self.selected_workspace_id is None:
            raise WorkspaceResolutionError("validation_error", "resolved workspace is missing")
        if self.resolution_state != "RESOLVED" and self.selected_workspace_id is not None:
            raise WorkspaceResolutionError("validation_error", "unresolved result cannot select workspace")
        if self.selected_workspace_id is not None:
            selected = self.selected_workspace
            if selected is None or selected.resolution_eligibility != "ELIGIBLE":
                raise WorkspaceResolutionError("validation_error", "selected workspace is not eligible")
            if self.selected_workspace_mode != selected.workspace_mode:
                raise WorkspaceResolutionError("validation_error", "selected workspace mode is inconsistent")
        elif self.selected_workspace_mode is not None:
            raise WorkspaceResolutionError("validation_error", "unselected result has a workspace mode")

    @property
    def state(self) -> ResolutionState:
        return self.resolution_state

    @property
    def workspace_candidates(self) -> tuple[WorkspaceCandidate, ...]:
        return self.candidates

    @property
    def candidate_set(self) -> tuple[WorkspaceCandidate, ...]:
        return self.candidates

    @property
    def selected_workspace(self) -> WorkspaceCandidate | None:
        if self.selected_workspace_id is None:
            return None
        return next(
            (candidate for candidate in self.candidates if candidate.workspace_id == self.selected_workspace_id),
            None,
        )

    @property
    def selected_tenant_id(self) -> UUID | None:
        selected = self.selected_workspace
        return None if selected is None else selected.tenant_id

    @property
    def selectedTenantId(self) -> UUID | None:
        return self.selected_tenant_id

    @property
    def selectedWorkspaceId(self) -> UUID | None:
        return self.selected_workspace_id

    @property
    def selectedWorkspaceMode(self) -> WorkspaceMode | None:
        return self.selected_workspace_mode

    @property
    def resolutionState(self) -> ResolutionState:
        return self.resolution_state

    @property
    def failureCode(self) -> str | None:
        return self.failure_code

    @property
    def is_resolved(self) -> bool:
        return self.resolution_state == "RESOLVED"

    def require_selected(self) -> WorkspaceCandidate:
        selected = self.selected_workspace
        if selected is None:
            raise WorkspaceResolutionError(
                self.failure_code or "workspace_access_denied",
                "a selectable workspace is not available",
            )
        return selected

    def to_dict(self) -> dict[str, object]:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "principal": None if self.principal is None else self.principal.to_dict(),
            "workspaceIntent": self.workspace_intent,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "resolutionState": self.resolution_state,
            "selectedWorkspaceId": None
            if self.selected_workspace_id is None
            else str(self.selected_workspace_id),
            "selectedWorkspaceMode": self.selected_workspace_mode,
            "failureCode": self.failure_code,
        }


class WorkspaceResolutionRepository(Protocol):
    def list_workspace_candidates(
        self,
        connection: Any,
        *,
        user_id: UUID,
    ) -> Sequence[WorkspaceResolutionRow]:
        ...


class PostgresWorkspaceResolutionRepository:
    """Reads current state directly; the migration candidate table is not cached."""

    _SQL = """
        SELECT workspace.id,
               workspace.tenant_id,
               workspace.workspace_mode,
               workspace.body_authority,
               workspace.status,
               workspace.ownership_state,
               workspace.visibility_state,
               workspace.owner_user_id,
               membership.user_id,
               membership.role,
               membership.state,
               binding.id,
               binding.status
        FROM openclaw_account.workspaces AS workspace
        JOIN openclaw_account.workspace_memberships AS membership
          ON membership.workspace_id = workspace.id
         AND membership.tenant_id = workspace.tenant_id
         AND membership.user_id = %s
        LEFT JOIN media_product.lark_tenant_bindings AS binding
          ON binding.tenant_id = workspace.tenant_id
         AND workspace.workspace_mode = 'organization_lark'
        ORDER BY CASE workspace.workspace_mode
                   WHEN 'personal_web' THEN 0
                   ELSE 1
                 END,
                 workspace.id,
                 binding.id
    """

    def list_workspace_candidates(
        self,
        connection: Any,
        *,
        user_id: UUID,
    ) -> tuple[WorkspaceResolutionRow, ...]:
        rows = connection.execute(self._SQL, (user_id,)).fetchall()
        return tuple(
            WorkspaceResolutionRow(
                workspace_id=_uuid(row[0], "workspace_id"),
                tenant_id=_uuid(row[1], "tenant_id"),
                workspace_mode=str(row[2]),
                body_authority=str(row[3]),
                workspace_status=str(row[4]),
                ownership_state=str(row[5]),
                visibility_state=str(row[6]),
                owner_user_id=None if row[7] is None else _uuid(row[7], "owner_user_id"),
                user_id=_uuid(row[8], "user_id"),
                membership_role=str(row[9]),
                membership_state=str(row[10]),
                binding_id=row[11],
                binding_status=None if row[12] is None else str(row[12]),
            )
            for row in rows
        )


class InMemoryWorkspaceResolutionRepository:
    """Small deterministic adapter for unit tests and local contract fixtures."""

    def __init__(self, rows: Sequence[WorkspaceResolutionRow] = ()) -> None:
        self._rows = tuple(rows)
        self.lookups: list[UUID] = []

    def replace(self, rows: Sequence[WorkspaceResolutionRow]) -> None:
        self._rows = tuple(rows)

    def list_workspace_candidates(
        self,
        _connection: Any = None,
        *,
        user_id: UUID,
    ) -> tuple[WorkspaceResolutionRow, ...]:
        self.lookups.append(user_id)
        return tuple(row for row in self._rows if row.user_id in {None, user_id})

    def candidates_for_user(self, user_id: UUID) -> tuple[WorkspaceResolutionRow, ...]:
        return self.list_workspace_candidates(user_id=user_id)


def _row_from_value(value: Any, user_id: UUID) -> WorkspaceResolutionRow:
    if isinstance(value, WorkspaceResolutionRow):
        return value
    workspace = _value(value, ("workspace",), value)
    membership = _value(value, ("membership",), value)
    binding = _value(value, ("binding",), None)
    identity_ids = _value(value, ("identity_link_receipt_ids", "identityLinkReceiptIds"), ())
    if isinstance(identity_ids, str):
        identity_ids = (identity_ids,)
    return WorkspaceResolutionRow(
        workspace_id=_uuid(_value(workspace, ("workspace_id", "workspaceId", "id")), "workspace_id"),
        tenant_id=_uuid(
            _value(value, ("tenant_id", "tenantId"), _value(workspace, ("tenant_id", "tenantId"))),
            "tenant_id",
        ),
        workspace_mode=str(_value(workspace, ("workspace_mode", "workspaceMode"), "")),
        body_authority=str(_value(workspace, ("body_authority", "bodyAuthority"), "")),
        membership_role=str(_value(membership, ("membership_role", "membershipRole", "role"), "")),
        membership_state=str(
            _value(membership, ("membership_state", "membershipState", "status", "state"), "ACTIVE")
        ),
        binding_id=_value(binding, ("binding_id", "bindingId", "id"), _value(value, ("binding_id", "bindingId"))),
        binding_status=_value(
            binding,
            ("binding_status", "bindingStatus", "status", "state"),
            _value(value, ("binding_status", "bindingStatus")),
        ),
        workspace_status=str(_value(workspace, ("workspace_status", "workspaceStatus", "status"), "ACTIVE")),
        ownership_state=str(_value(workspace, ("ownership_state", "ownershipState"), "PROVEN")),
        visibility_state=str(_value(workspace, ("visibility_state", "visibilityState"), "VISIBLE")),
        owner_user_id=(
            None
            if _value(workspace, ("owner_user_id", "ownerUserId")) is None
            else _uuid(_value(workspace, ("owner_user_id", "ownerUserId")), "owner_user_id")
        ),
        user_id=(
            user_id
            if _value(value, ("user_id", "userId")) is None
            else _uuid(_value(value, ("user_id", "userId")), "user_id")
        ),
        identity_link_receipt_ids=tuple(str(item) for item in identity_ids),
    )


class WorkspaceResolver:
    """Resolves authenticated sessions against current server-owned workspace state."""

    def __init__(
        self,
        account_auth: Any,
        repository: WorkspaceResolutionRepository | Any | None = None,
        *,
        database: Any | None = None,
        now: Any | None = None,
    ) -> None:
        self._account_auth = account_auth
        self._repository = repository or PostgresWorkspaceResolutionRepository()
        self._database = database or getattr(account_auth, "_database", None)
        self._now = now or (lambda: datetime.now(timezone.utc))

    def resolve(
        self,
        token_or_session: str | AccountSession | None,
        *,
        tenant_id: UUID | str | None = None,
        selected_tenant_id: UUID | str | None = None,
        requested_tenant_id: UUID | str | None = None,
        frontend_tenant_id: UUID | str | None = None,
    ) -> WorkspaceResolutionResult:
        session, token, invalid = self._authenticated_session(token_or_session)
        if invalid is not None or session is None:
            return self._invalid_result(invalid or "invalid_session")

        requested, selection_error = self._requested_tenant(
            tenant_id,
            selected_tenant_id,
            requested_tenant_id,
            frontend_tenant_id,
        )
        if selection_error is not None:
            principal = self._principal(session, token, (), None)
            return self._result(
                principal,
                (),
                session,
                "NO_ELIGIBLE_WORKSPACE",
                failure_code=selection_error,
            )

        try:
            rows = self._load_rows(_uuid(getattr(session, "user_id"), "user_id"))
            candidates, reasons, receipt_ids = self._candidates(rows, session)
        except WorkspaceResolutionError as exc:
            return self._invalid_result(exc.code)
        except Exception:
            return self._invalid_result("internal_error")

        session_tenant = _uuid(getattr(session, "tenant_id"), "tenant_id")
        eligible = tuple(candidate for candidate in candidates if candidate.resolution_eligibility == "ELIGIBLE")
        selected: WorkspaceCandidate | None = None
        failure_code: str | None = None
        state: ResolutionState

        if requested is not None:
            matches = tuple(candidate for candidate in candidates if candidate.tenant_id == requested)
            if not matches:
                state = "NO_ELIGIBLE_WORKSPACE"
                failure_code = "workspace_access_denied"
            elif len(matches) != 1:
                state = "NO_ELIGIBLE_WORKSPACE"
                failure_code = "conflict"
            elif matches[0].resolution_eligibility != "ELIGIBLE":
                state = "NO_ELIGIBLE_WORKSPACE"
                failure_code = self._failure_for_candidate(matches[0])
            else:
                selected = matches[0]
                state = "RESOLVED"
        elif not eligible:
            state = "NO_ELIGIBLE_WORKSPACE"
            failure_code = self._failure_for_reasons(reasons)
        else:
            current = tuple(candidate for candidate in eligible if candidate.tenant_id == session_tenant)
            if len(current) == 1:
                selected = current[0]
                state = "RESOLVED"
            elif len(eligible) == 1:
                selected = eligible[0]
                state = "RESOLVED"
            else:
                state = "REQUIRES_SELECTION"
                failure_code = "workspace_selection_required"

        principal = self._principal(session, token, candidates, selected)
        if principal is None:
            return self._invalid_result("invalid_session")
        return self._result(
            principal,
            candidates,
            session,
            state,
            selected=selected,
            failure_code=failure_code,
            receipt_ids=receipt_ids,
        )

    def resolve_session(
        self,
        token_or_session: str | AccountSession | None,
        tenant_id: UUID | str | None = None,
        **kwargs: Any,
    ) -> WorkspaceResolutionResult:
        return self.resolve(token_or_session, tenant_id=tenant_id, **kwargs)

    def _authenticated_session(
        self,
        token_or_session: str | AccountSession | None,
    ) -> tuple[Any | None, str | None, str | None]:
        if isinstance(token_or_session, str) or token_or_session is None:
            token = token_or_session
            try:
                session = self._account_auth.resolve_session(token)
            except Exception:
                return None, token, "invalid_session"
        else:
            session = token_or_session
            token = cast(str | None, getattr(token_or_session, "token", None))
        if session is None:
            return None, token, "invalid_session"
        try:
            expires_at = getattr(session, "expires_at")
            if expires_at <= self._now():
                return None, token, "invalid_session"
            session_status = getattr(session, "session_status", None)
            if session_status is None:
                session_status = getattr(session, "status", "ACTIVE")
            if _upper(session_status, "ACTIVE") != "ACTIVE":
                return None, token, "invalid_session"
            if getattr(session, "revoked_at", None) is not None:
                return None, token, "invalid_session"
            if bool(getattr(session, "revoked", False)) or bool(getattr(session, "is_revoked", False)):
                return None, token, "invalid_session"
            for field in ("user_status", "tenant_status"):
                if _upper(getattr(session, field, "ACTIVE"), "ACTIVE") != "ACTIVE":
                    return None, token, "invalid_session"
            account_status = _upper(getattr(session, "account_status", "ACTIVE"), "ACTIVE")
            if account_status != "ACTIVE":
                return None, token, "invalid_session"
            if getattr(session, "user_type", None) is not None:
                return None, token, "validation_error"
            if _uuid(getattr(session, "user_id"), "user_id") is None:
                return None, token, "invalid_session"
            if _uuid(getattr(session, "tenant_id"), "tenant_id") is None:
                return None, token, "invalid_session"
            role = str(getattr(session, "role"))
            if role not in {"user", "admin"}:
                return None, token, "invalid_session"
            if bool(getattr(session, "is_maintainer", False)) and role != "admin":
                return None, token, "invalid_session"
            mode = str(getattr(session, "workspace_mode"))
            authority = str(getattr(session, "body_authority"))
            if (mode, authority) not in {
                ("personal_web", "internal"),
                ("organization_lark", "lark"),
            }:
                return None, token, "validation_error"
            if str(getattr(session, "member_role")) not in {"owner", "member"}:
                return None, token, "validation_error"
        except (AttributeError, TypeError, ValueError, WorkspaceResolutionError):
            return None, token, "invalid_session"
        return session, token, None

    def _requested_tenant(
        self,
        *values: UUID | str | None,
    ) -> tuple[UUID | None, str | None]:
        supplied = [value for value in values if value is not None]
        if not supplied:
            return None, None
        try:
            parsed = tuple(_uuid(value, "tenant_id") for value in supplied)
        except WorkspaceResolutionError as exc:
            return None, exc.code
        if len(set(parsed)) != 1:
            return None, "validation_error"
        return parsed[0], None

    def _load_rows(self, user_id: UUID) -> tuple[WorkspaceResolutionRow, ...]:
        method = None
        for name in (
            "list_workspace_candidates",
            "workspace_candidates_for_user",
            "candidates_for_user",
            "list_candidates",
        ):
            possible = getattr(self._repository, name, None)
            if possible is not None:
                method = possible
                break
        if method is None:
            raise WorkspaceResolutionError("internal_error", "workspace repository has no candidate reader")

        connection_context = None
        connection = None
        try:
            parameters = tuple(inspect.signature(method).parameters.values())
        except (TypeError, ValueError):
            parameters = ()
        needs_connection = any(parameter.name in {"connection", "conn"} for parameter in parameters)
        if self._database is not None and needs_connection:
            connection_context = self._database.connect()
            connection = connection_context.__enter__()
        try:
            rows = self._invoke_reader(method, connection, user_id)
            return tuple(_row_from_value(row, user_id) for row in (rows or ()))
        finally:
            if connection_context is not None:
                connection_context.__exit__(None, None, None)

    @staticmethod
    def _invoke_reader(method: Any, connection: Any, user_id: UUID) -> Any:
        try:
            parameters = tuple(inspect.signature(method).parameters.values())
        except (TypeError, ValueError):
            parameters = ()
        names = {parameter.name for parameter in parameters}
        if "connection" in names or "conn" in names:
            try:
                return method(connection, user_id=user_id)
            except TypeError:
                return method(connection, user_id)
        if connection is not None and parameters and len(parameters) >= 2:
            return method(connection, user_id)
        try:
            return method(user_id=user_id)
        except TypeError:
            return method(user_id)

    @staticmethod
    def _candidates(
        rows: Sequence[WorkspaceResolutionRow],
        session: Any,
    ) -> tuple[tuple[WorkspaceCandidate, ...], tuple[str, ...], tuple[str, ...]]:
        user_id = _uuid(getattr(session, "user_id"), "user_id")
        groups: dict[tuple[UUID, UUID], list[WorkspaceResolutionRow]] = {}
        for row in rows:
            if row.user_id is not None and row.user_id != user_id:
                continue
            key = (_uuid(row.workspace_id, "workspace_id"), _uuid(row.tenant_id, "tenant_id"))
            groups.setdefault(key, []).append(row)

        active_binding_groups: dict[str, set[tuple[UUID, UUID]]] = {}
        for key, group in groups.items():
            for row in group:
                if row.binding_id is not None and _upper(row.binding_status) == "ACTIVE":
                    active_binding_groups.setdefault(str(row.binding_id), set()).add(key)
        duplicate_binding_groups = {
            key
            for keys in active_binding_groups.values()
            if len(keys) > 1
            for key in keys
        }

        candidates: list[WorkspaceCandidate] = []
        reasons: list[str] = []
        receipt_ids: set[str] = set()
        for (workspace_id, tenant_id), group in groups.items():
            if (workspace_id, tenant_id) in duplicate_binding_groups:
                reasons.append("conflict")
                continue
            active_bindings = {
                str(row.binding_id)
                for row in group
                if row.binding_id is not None and _upper(row.binding_status) == "ACTIVE"
            }
            binding_ids = {str(row.binding_id) for row in group if row.binding_id is not None}
            if len(active_bindings) > 1 or len(binding_ids) > 1:
                reasons.append("conflict")
                continue
            row = group[0]
            for item in group:
                receipt_ids.update(str(value) for value in item.identity_link_receipt_ids)
            mode = str(row.workspace_mode)
            authority = str(row.body_authority)
            if (mode, authority) not in {
                ("personal_web", "internal"),
                ("organization_lark", "lark"),
            }:
                reasons.append("validation_error")
                continue
            if _upper(row.ownership_state) != "PROVEN" or _upper(row.visibility_state) != "VISIBLE":
                reasons.append("workspace_access_denied")
                continue
            role = str(row.membership_role)
            if role not in {"owner", "member"}:
                reasons.append("validation_error")
                continue
            membership_state = _membership_state(row.membership_state)
            workspace_status = _workspace_status(row.workspace_status)
            if mode == "personal_web":
                if row.binding_id is not None or (
                    row.binding_status is not None
                    and _upper(row.binding_status) not in {"NOT_APPLICABLE", "NONE"}
                ):
                    reasons.append("validation_error")
                    continue
                if role != "owner":
                    reasons.append("validation_error")
                    continue
                if row.owner_user_id is not None and row.owner_user_id != user_id:
                    reasons.append("workspace_access_denied")
                    continue
                binding_id = None
                binding_state = "NOT_APPLICABLE"
            else:
                binding_id = row.binding_id
                binding_state = _binding_state(row.binding_status)
                if binding_id is None:
                    binding_state = "NEEDS_ATTENTION"
            if membership_state == "REVOKED" or workspace_status == "REVOKED" or binding_state == "REVOKED":
                eligibility = "REVOKED"
            elif (
                membership_state != "ACTIVE"
                or workspace_status != "ACTIVE"
                or (mode == "organization_lark" and binding_state != "ACTIVE")
            ):
                eligibility = "SUSPENDED"
            else:
                eligibility = "ELIGIBLE"
            if membership_state != "ACTIVE":
                reasons.append("membership_inactive")
            if workspace_status != "ACTIVE":
                reasons.append("workspace_access_denied")
            if mode == "organization_lark" and binding_state != "ACTIVE":
                reasons.append("binding_unavailable")
            if mode == "personal_web" and (membership_state != "ACTIVE" or workspace_status != "ACTIVE"):
                reasons.append("membership_inactive")
                continue
            if membership_state == "NEEDS_ATTENTION" or workspace_status == "NEEDS_ATTENTION":
                reasons.append("workspace_access_denied")
                continue
            try:
                candidate_type = (
                    WorkspaceCandidatePersonal if mode == "personal_web" else WorkspaceCandidateOrganization
                )
                candidate = candidate_type(
                    workspace_id=workspace_id,
                    tenant_id=tenant_id,
                    workspace_mode=cast(WorkspaceMode, mode),
                    body_authority=cast(BodyAuthority, authority),
                    membership_role=cast(MemberRole, role),
                    membership_state=membership_state,
                    binding_state=binding_state,
                    ownership_state=cast(str, _upper(row.ownership_state, "PROVEN")),
                    workspace_status=workspace_status,
                    binding_id=binding_id,
                    resolution_eligibility=eligibility,
                    identity_link_receipt_id=(
                        row.identity_link_receipt_ids[0] if row.identity_link_receipt_ids else None
                    ),
                    user_id=user_id,
                )
            except WorkspaceResolutionError as exc:
                reasons.append(exc.code)
                continue
            candidates.append(candidate)

        candidates.sort(key=lambda item: (0 if item.workspace_mode == "personal_web" else 1, str(item.tenant_id), str(item.workspace_id)))
        return tuple(candidates), tuple(reasons), tuple(sorted(receipt_ids))

    def _principal(
        self,
        session: Any,
        token: str | None,
        candidates: Sequence[WorkspaceCandidate],
        selected: WorkspaceCandidate | None,
    ) -> SessionPrincipal | None:
        try:
            user_id = _uuid(getattr(session, "user_id"), "user_id")
            tenant_id = _uuid(getattr(session, "tenant_id"), "tenant_id")
            session_id = _uuid(getattr(session, "session_id"), "session_id")
            current = selected or next(
                (candidate for candidate in candidates if candidate.tenant_id == tenant_id),
                None,
            )
            mode = current.workspace_mode if current is not None else str(getattr(session, "workspace_mode"))
            authority = current.body_authority if current is not None else str(getattr(session, "body_authority"))
            role = current.member_role if current is not None else str(getattr(session, "member_role"))
            issued_at = getattr(session, "session_issued_at", None) or getattr(session, "issued_at", None) or self._now()
            authenticated_at = self._now()
            if token is not None:
                token_hash = hashlib.sha256(token.encode("ascii")).digest()
            else:
                supplied_hash = getattr(session, "session_token_hash", None)
                token_hash = supplied_hash if isinstance(supplied_hash, bytes) and len(supplied_hash) == 32 else hashlib.sha256(
                    str(getattr(session, "session_id")).encode("ascii")
                ).digest()
            personal = next((candidate for candidate in candidates if candidate.workspace_mode == "personal_web"), None)
            memberships = tuple(dict.fromkeys(str(candidate.tenant_id) for candidate in candidates))
            bindings = tuple(
                str(candidate.binding_id)
                for candidate in candidates
                if candidate.binding_state == "ACTIVE" and candidate.binding_id is not None
            )
            bindings = tuple(dict.fromkeys(bindings))
            identity_links = tuple(
                sorted(
                    {
                        candidate.identity_link_receipt_id
                        for candidate in candidates
                        if candidate.identity_link_receipt_id is not None
                    }
                )
            )
            return SessionPrincipal(
                session_id=session_id,
                user_id=user_id,
                tenant_id=current.tenant_id if current is not None else tenant_id,
                user_public_id=str(getattr(session, "user_public_id", user_id)),
                role=cast(Literal["user", "admin"], str(getattr(session, "role"))),
                is_maintainer=bool(getattr(session, "is_maintainer", False)),
                expires_at=getattr(session, "expires_at"),
                workspace_mode=cast(WorkspaceMode, mode),
                body_authority=cast(BodyAuthority, authority),
                member_role=cast(MemberRole, role),
                session_token_hash=token_hash,
                schema_version=SCHEMA_VERSION,
                principal_id=str(getattr(session, "user_public_id", user_id)),
                account_status=cast(
                    Literal["PENDING_EMAIL_VERIFICATION", "ACTIVE", "SUSPENDED"],
                    _upper(getattr(session, "account_status", "ACTIVE"), "ACTIVE"),
                ),
                workspace_intent=cast(WorkspaceMode, mode),
                personal_workspace_id=None if personal is None else personal.workspace_id,
                tenant_membership_ids=memberships,
                active_binding_ids=bindings,
                identity_link_receipt_ids=identity_links,
                authenticated_at=authenticated_at,
                session_issued_at=issued_at,
            )
        except (AttributeError, TypeError, ValueError, UnicodeError):
            return None

    @staticmethod
    def _failure_for_candidate(candidate: WorkspaceCandidate) -> str:
        if candidate.membership_state != "ACTIVE":
            return "membership_inactive"
        if candidate.binding_state != "ACTIVE" and candidate.workspace_mode == "organization_lark":
            return "binding_unavailable"
        if candidate.ownership_state != "PROVEN":
            return "workspace_access_denied"
        return "workspace_access_denied"

    @staticmethod
    def _failure_for_reasons(reasons: Sequence[str]) -> str:
        for code in (
            "conflict",
            "validation_error",
            "membership_inactive",
            "binding_unavailable",
            "workspace_access_denied",
        ):
            if code in reasons:
                return code
        return "workspace_not_found"

    def _result(
        self,
        principal: SessionPrincipal,
        candidates: Sequence[WorkspaceCandidate],
        session: Any,
        state: ResolutionState,
        *,
        selected: WorkspaceCandidate | None = None,
        failure_code: str | None = None,
        receipt_ids: Sequence[str] = (),
    ) -> WorkspaceResolutionResult:
        if receipt_ids and principal.identity_link_receipt_ids != tuple(sorted(set(receipt_ids))):
            principal = replace(
                principal,
                identity_link_receipt_ids=tuple(sorted(set(receipt_ids))),
            )
        return WorkspaceResolutionResult(
            principal=principal,
            workspace_intent=cast(WorkspaceMode, selected.workspace_mode if selected else principal.workspace_intent),
            candidates=tuple(candidates),
            resolution_state=state,
            selected_workspace_id=None if selected is None else selected.workspace_id,
            selected_workspace_mode=None if selected is None else selected.workspace_mode,
            failure_code=failure_code,
        )

    @staticmethod
    def _invalid_result(code: str) -> WorkspaceResolutionResult:
        return WorkspaceResolutionResult(
            principal=None,
            workspace_intent=None,
            candidates=(),
            resolution_state="INVALID_SESSION",
            failure_code=code,
        )


WorkspaceResolutionService = WorkspaceResolver
AccountWorkspaceResolutionRepository = PostgresWorkspaceResolutionRepository
WorkspaceRepositoryAdapter = PostgresWorkspaceResolutionRepository
SessionPrincipalV2 = SessionPrincipal


def resolve_workspace(
    account_auth: Any,
    token: str | None,
    repository: WorkspaceResolutionRepository | Any | None = None,
    *,
    tenant_id: UUID | str | None = None,
    database: Any | None = None,
) -> WorkspaceResolutionResult:
    return WorkspaceResolver(account_auth, repository, database=database).resolve(token, tenant_id=tenant_id)


__all__ = [
    "SCHEMA_VERSION",
    "AccountWorkspaceResolutionRepository",
    "BindingState",
    "BodyAuthority",
    "InMemoryWorkspaceResolutionRepository",
    "MemberRole",
    "PostgresWorkspaceResolutionRepository",
    "ResolutionState",
    "SessionPrincipalV2",
    "WorkspaceCandidate",
    "WorkspaceCandidateOrganization",
    "WorkspaceCandidatePersonal",
    "WorkspaceMembership",
    "WorkspaceMode",
    "WorkspaceResolutionCandidateRow",
    "WorkspaceResolutionError",
    "WorkspaceResolutionRepository",
    "WorkspaceResolutionResult",
    "WorkspaceResolutionRow",
    "WorkspaceResolutionService",
    "WorkspaceResolver",
    "WorkspaceRepositoryAdapter",
    "resolve_workspace",
]
