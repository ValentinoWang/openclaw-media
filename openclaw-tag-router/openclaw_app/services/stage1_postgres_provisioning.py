"""PostgreSQL adapters for the Stage 1 organization provision contract.

The service layer deliberately stays storage agnostic.  This module is the
production boundary: it owns transactions, row locks, durable step receipts,
and the small idempotency projection available in the canonical schema.
"""

from __future__ import annotations

import json
import secrets
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterator, Mapping, Sequence
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from .stage1_organization_provisioning import (
    AdminConfirmationReceipt,
    AdminConfirmationRepository,
    AdminConfirmationStore,
    BindingGeneration,
    DeprovisionReceipt,
    DeprovisionRepository,
    DeprovisionStore,
    ExternalResource,
    FeishuResourceGateway,
    InstallationTarget,
    OwnerIdentity,
    OwnerRecord,
    ProvisionRun,
    ProvisionRunRepository,
    ProvisionRunState,
    ResourceInitializationRepository,
    ResourceStepReceipt,
    TrustedFeishuAdministrator,
    TrustedProvisionActor,
    ProvisioningError,
    ResourceBindingContext,
    _digest,
    _projection_key,
    _resource_run_key,
    _text,
    retry_delay_seconds,
)
from .stage1_member_onboarding import (
    MemberBinding,
    MemberOnboardingRepository,
    MemberOnboardingStoreConflict,
    PlatformUserRecord,
    ServerFeishuInstallContext,
    TenantMemberIdentityRecord,
    TenantMembershipRecord,
)
from .stage1_provision_models import Stage1LifecycleState


UTC = timezone.utc
_IDEMPOTENCY_OPERATION = {
    "confirmation": "stage1.organization.confirm",
    "deprovision": "stage1.organization.deprovision",
}


def _state(value: object) -> Stage1LifecycleState:
    try:
        return Stage1LifecycleState(str(value))
    except ValueError as exc:
        raise RuntimeError(f"invalid Stage 1 lifecycle state: {value!r}") from exc


def _run_state(value: object) -> ProvisionRunState:
    try:
        return ProvisionRunState(str(value))
    except ValueError as exc:
        raise RuntimeError(f"invalid Stage 1 provision state: {value!r}") from exc


def _uuid(value: object) -> UUID:
    return value if isinstance(value, UUID) else UUID(str(value))


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _organization_name(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("organization_name must be a string")
    normalized = value.strip()
    if value != normalized or not normalized or len(normalized) > 120:
        raise ValueError("organization_name is invalid")
    if any(ord(character) < 32 for character in normalized):
        raise ValueError("organization_name is invalid")
    return normalized


class _ConnectionStore:
    """One transaction-scoped implementation of all Stage 1 repository ports."""

    def __init__(self, connection: Any, *, actor_session_id: UUID | None = None) -> None:
        self.connection = connection
        self.actor_session_id = actor_session_id

    def _execute(self, sql: str, params: Sequence[object] = ()) -> Any:
        execute = getattr(self.connection, "execute", None)
        if callable(execute):
            return execute(sql, tuple(params))
        cursor = self.connection.cursor()
        cursor.execute(sql, tuple(params))
        return cursor

    @staticmethod
    def _one(result: Any) -> Any:
        fetchone = getattr(result, "fetchone", None)
        return fetchone() if callable(fetchone) else None

    @staticmethod
    def _all(result: Any) -> list[Any]:
        fetchall = getattr(result, "fetchall", None)
        return list(fetchall()) if callable(fetchall) else []

    @staticmethod
    def _identity_id(tenant_id: UUID, external_user_id: str) -> UUID:
        """Expose a stable receipt id for the canonical composite identity key."""
        return uuid5(
            NAMESPACE_URL,
            f"media-stage1:tenant-member-identity:{tenant_id}:{external_user_id}",
        )

    @staticmethod
    def _membership_id(tenant_id: UUID, user_id: UUID) -> UUID:
        return uuid5(NAMESPACE_URL, f"media-stage1:tenant-membership:{tenant_id}:{user_id}")

    @staticmethod
    def _is_unique_violation(exc: Exception) -> bool:
        return str(getattr(exc, "sqlstate", "")) == "23505" or exc.__class__.__name__ == "UniqueViolation"

    def bindings_for_context(
        self,
        *,
        tenant_key: str,
        installation_id: str | None,
    ) -> Sequence[MemberBinding]:
        predicates = ""
        params: list[object] = [tenant_key]
        if installation_id is not None:
            predicates = " AND installation.installation_public_id=%s"
            params.append(installation_id)
        rows = self._all(self._execute(
            f"""SELECT binding.binding_id, binding.tenant_id, binding.tenant_key,
                          binding.status, installation.installation_public_id,
                          tenant.primary_user_id
                     FROM media_product.stage1_binding_generations AS binding
                     JOIN media_product.stage1_installations AS installation
                       ON installation.id=binding.installation_id
                      AND installation.tenant_id=binding.tenant_id
                      AND installation.tenant_key=binding.tenant_key
                     JOIN openclaw_account.tenants AS tenant
                       ON tenant.id=binding.tenant_id
                    WHERE binding.tenant_key=%s
                      {predicates}
                      AND installation.status='ACTIVE'
                      AND installation.credential_ref IS NOT NULL
                      AND binding.status='ACTIVE'
                    ORDER BY binding.generation DESC
                    FOR SHARE OF binding, installation, tenant""",
            tuple(params),
        ))
        return tuple(
            MemberBinding(
                binding_id=int(row[0]),
                tenant_id=_uuid(row[1]),
                tenant_key=str(row[2]),
                status="active" if str(row[3]).upper() == "ACTIVE" else str(row[3]).lower(),
                installation_id=str(row[4]),
                owner_user_id=_uuid(row[5]) if row[5] is not None else None,
            )
            for row in rows
        )

    def _identity_records(self, rows: Sequence[Any]) -> tuple[TenantMemberIdentityRecord, ...]:
        return tuple(
            TenantMemberIdentityRecord(
                identity_id=self._identity_id(_uuid(row[0]), str(row[5] or row[3])),
                binding_id=row[6] if row[6] is not None else None,
                tenant_id=_uuid(row[0]),
                user_id=_uuid(row[1]),
                open_id=str(row[3]),
                external_status=str(row[4]),
            )
            for row in rows
        )

    def identities_for_binding_open_id(
        self,
        *,
        binding_id: int | str | UUID,
        open_id: str,
    ) -> Sequence[TenantMemberIdentityRecord]:
        rows = self._all(self._execute(
            """SELECT tenant_id, user_id, tenant_key, open_id, external_status,
                          external_user_id, binding_id
                     FROM openclaw_account.tenant_member_identities
                    WHERE binding_id=%s AND open_id=%s
                    FOR UPDATE""",
            (binding_id, open_id),
        ))
        return self._identity_records(rows)

    def identities_for_open_id(self, *, open_id: str) -> Sequence[TenantMemberIdentityRecord]:
        rows = self._all(self._execute(
            """SELECT tenant_id, user_id, tenant_key, open_id, external_status,
                          external_user_id, binding_id
                     FROM openclaw_account.tenant_member_identities
                    WHERE open_id=%s
                    FOR UPDATE""",
            (open_id,),
        ))
        return self._identity_records(rows)

    def user_for_id(self, user_id: UUID) -> PlatformUserRecord | None:
        row = self._one(self._execute(
            """SELECT id, username, email, display_name, role, status
                 FROM openclaw_account.users
                WHERE id=%s
                FOR SHARE""",
            (user_id,),
        ))
        if row is None:
            return None
        return PlatformUserRecord(
            user_id=_uuid(row[0]),
            username=str(row[1]),
            email=None if row[2] is None else str(row[2]),
            display_name=str(row[3]),
            role=str(row[4]),
            status=str(row[5]),
        )

    def memberships_for_user_tenant(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
    ) -> Sequence[TenantMembershipRecord]:
        rows = self._all(self._execute(
            """SELECT tenant_id, user_id, role, status
                 FROM openclaw_account.tenant_members
                WHERE tenant_id=%s AND user_id=%s
                FOR SHARE""",
            (tenant_id, user_id),
        ))
        return tuple(
            TenantMembershipRecord(
                membership_id=self._membership_id(_uuid(row[0]), _uuid(row[1])),
                tenant_id=_uuid(row[0]),
                user_id=_uuid(row[1]),
                role=str(row[2]),
                status=str(row[3]),
            )
            for row in rows
        )

    def create_user(self, *, email: str | None, display_name: str) -> PlatformUserRecord:
        user_id = uuid4()
        username = f"feishu-member-{user_id.hex[:16]}"
        # This account is intentionally Feishu-bound and has no password login.
        password_hash = "!feishu-member-" + secrets.token_urlsafe(48)
        try:
            self._execute(
                """INSERT INTO openclaw_account.users
                   (id, username, email, password_hash, role, status, display_name)
                   VALUES (%s,%s,%s,%s,'user','active',%s)""",
                (user_id, username, email, password_hash, display_name),
            )
        except Exception as exc:
            if self._is_unique_violation(exc):
                raise MemberOnboardingStoreConflict("user") from exc
            raise
        return PlatformUserRecord(user_id, username, email, display_name, "user", "active")

    def create_membership(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        role: str,
    ) -> TenantMembershipRecord:
        try:
            self._execute(
                """INSERT INTO openclaw_account.tenant_members(tenant_id, user_id, role, status)
                   VALUES (%s,%s,%s,'active')""",
                (tenant_id, user_id, role),
            )
        except Exception as exc:
            if self._is_unique_violation(exc):
                raise MemberOnboardingStoreConflict("membership") from exc
            raise
        return TenantMembershipRecord(
            self._membership_id(tenant_id, user_id), tenant_id, user_id, role, "active"
        )

    def create_identity(
        self,
        *,
        binding_id: int | str | UUID,
        tenant_id: UUID,
        user_id: UUID,
        open_id: str,
        external_status: str,
    ) -> TenantMemberIdentityRecord:
        try:
            self._execute(
                """INSERT INTO openclaw_account.tenant_member_identities
                   (tenant_id, user_id, tenant_key, open_id, external_user_id,
                    display_name, external_status, binding_id, status)
                   SELECT %s, %s, binding.tenant_key, %s, %s, %s, %s, %s, 'ACTIVE'
                     FROM media_product.stage1_binding_generations AS binding
                    WHERE binding.binding_id=%s AND binding.tenant_id=%s
                      AND binding.status='ACTIVE'""",
                (
                    tenant_id,
                    user_id,
                    open_id,
                    open_id,
                    open_id,
                    external_status,
                    binding_id,
                    binding_id,
                    tenant_id,
                ),
            )
        except Exception as exc:
            if self._is_unique_violation(exc):
                raise MemberOnboardingStoreConflict("identity") from exc
            raise
        return TenantMemberIdentityRecord(
            self._identity_id(tenant_id, open_id),
            binding_id,
            tenant_id,
            user_id,
            open_id,
            external_status,
        )

    def _confirmation_projection(self, installation_id: UUID, key: str) -> dict[str, Any] | None:
        key = _projection_key(key)
        result = self._execute(
            """SELECT response_json, request_fingerprint
               FROM openclaw_account.if2_idempotency_receipts
              WHERE scope_kind='tenant' AND scope_id=%s
                AND operation_id=%s AND idempotency_key=%s
                AND state='completed'
              FOR UPDATE""",
            (installation_id, _IDEMPOTENCY_OPERATION["confirmation"], key),
        )
        row = self._one(result)
        if not row:
            return None
        payload = row[0]
        if isinstance(payload, str):
            payload = json.loads(payload)
        return dict(payload) if isinstance(payload, Mapping) else None

    def _save_projection(
        self,
        *,
        scope_id: UUID,
        operation: str,
        key: str,
        request_digest: bytes,
        payload: Mapping[str, Any],
    ) -> None:
        if operation in _IDEMPOTENCY_OPERATION.values():
            key = _projection_key(key)
        # The canonical IF2 receipt enforces the same replay/conflict contract
        # and is intentionally used instead of adding another migration table.
        self._execute(
            """INSERT INTO openclaw_account.if2_idempotency_receipts
               (scope_kind, scope_id, operation_id, idempotency_key,
                path_fingerprint, request_fingerprint, state, response_status,
                response_json, completed_at)
               VALUES ('tenant', %s, %s, %s, %s, %s, 'completed', 200, %s::jsonb, now())
               ON CONFLICT (scope_kind, scope_id, operation_id, idempotency_key)
               DO UPDATE SET response_json=EXCLUDED.response_json,
                             request_fingerprint=EXCLUDED.request_fingerprint,
                             response_status=EXCLUDED.response_status,
                             state='completed', completed_at=now()""",
            (scope_id, operation, key, request_digest, request_digest, _json(payload)),
        )

    def _installation_row(self, row: Sequence[Any]) -> InstallationTarget:
        return InstallationTarget(
            installation_id=_uuid(row[0]),
            installation_public_id=str(row[1]),
            app_id=str(row[2]),
            tenant_key=str(row[3]),
            tenant_id=_uuid(row[4]) if row[4] is not None else None,
            state=_state(row[5]),
            credential_ref=str(row[6]) if row[6] is not None else None,
        )

    def _live_binding_row(
        self,
        installation_id: UUID,
        tenant_id: UUID,
        binding_id: int,
        binding_generation: int | None = None,
    ) -> Sequence[Any] | None:
        predicates = ""
        params: list[object] = [installation_id, tenant_id, binding_id]
        if binding_generation is not None:
            predicates = " AND b.generation=%s"
            params.append(binding_generation)
        return self._one(self._execute(
            f"""SELECT i.id, i.tenant_id, i.tenant_key, i.status, i.credential_ref,
                          b.binding_id, b.generation, b.tenant_id, b.tenant_key, b.status
                     FROM media_product.stage1_installations AS i
                     JOIN media_product.stage1_binding_generations AS b
                       ON b.installation_id=i.id
                      AND b.tenant_id=i.tenant_id
                    WHERE i.id=%s AND i.tenant_id=%s AND b.binding_id=%s
                      {predicates}
                    FOR UPDATE OF i, b""",
            tuple(params),
        ))

    @staticmethod
    def _assert_live_binding(row: Sequence[Any] | None) -> None:
        generation = None if not row or row[6] is None else int(row[6])
        if (
            not row
            or row[1] is None
            or row[7] is None
            or not str(row[2]).strip()
            or not str(row[8]).strip()
            or str(row[2]) != str(row[8])
            or str(row[3]) not in {"ACTIVE", "NEEDS_ATTENTION"}
            or not isinstance(row[4], str)
            or not row[4].strip()
            or generation is None
            or generation <= 0
            or str(row[9]) not in {"ACTIVE", "NEEDS_ATTENTION"}
        ):
            raise RuntimeError("Stage 1 binding is inactive or credential-fenced")

    def confirmation_for_key(self, installation_id: UUID, idempotency_key: str) -> AdminConfirmationReceipt | None:
        payload = self._confirmation_projection(installation_id, idempotency_key)
        if payload is None:
            return None
        return AdminConfirmationReceipt(
            confirmation_id=_uuid(payload["confirmationId"]),
            idempotency_key=str(payload["idempotencyKey"]),
            request_digest=bytes.fromhex(str(payload["requestDigest"])),
            installation_id=_uuid(payload["installationId"]),
            tenant_id=_uuid(payload["tenantId"]),
            owner_user_id=_uuid(payload["ownerUserId"]),
            binding_id=int(payload["bindingId"]),
            binding_generation=int(payload["bindingGeneration"]),
            tenant_key=str(payload["tenantKey"]),
            open_id=str(payload["openId"]),
            action=str(payload["action"]),
            confirmed_at=datetime.fromisoformat(str(payload["confirmedAt"])),
        )

    def installation_for_update(self, installation_public_id: str, tenant_key: str) -> InstallationTarget | None:
        row = self._one(self._execute(
            """SELECT id, installation_public_id, app_id, tenant_key, tenant_id,
                      status, credential_ref
                 FROM media_product.stage1_installations
                WHERE installation_public_id=%s AND tenant_key=%s
                FOR UPDATE""",
            (installation_public_id, tenant_key),
        ))
        return self._installation_row(row) if row else None

    def ensure_organization_owner(
        self, tenant_id: UUID, owner_user_id: UUID, organization_name: str
    ) -> OwnerRecord | None:
        try:
            normalized_name = _organization_name(organization_name)
        except ValueError:
            return None
        user = self._one(self._execute(
            "SELECT id, role, status FROM openclaw_account.users WHERE id=%s FOR UPDATE",
            (owner_user_id,),
        ))
        if not user or str(user[2]) != "active":
            return None

        tenant = self._one(self._execute(
            """SELECT primary_user_id, status, tenant_type, workspace_mode,
                      body_authority, organization_name
                 FROM openclaw_account.tenants
                WHERE id=%s FOR UPDATE""",
            (tenant_id,),
        ))
        if tenant is None:
            self._execute(
                """INSERT INTO openclaw_account.tenants(
                           id, primary_user_id, status, tenant_type,
                           workspace_mode, body_authority, organization_name
                       ) VALUES (%s,%s,'active','organization',
                                 'organization_lark','lark',%s)""",
                (tenant_id, owner_user_id, normalized_name),
            )
        elif (
            _uuid(tenant[0]) != owner_user_id
            or str(tenant[1]) != "active"
            or str(tenant[2]) != "organization"
            or str(tenant[3]) != "organization_lark"
            or str(tenant[4]) != "lark"
            or str(tenant[5] or "").strip() != normalized_name
        ):
            # A personal or otherwise conflicting tenant is never converted.
            return None

        memberships = self._all(self._execute(
            """SELECT user_id, role, status
                 FROM openclaw_account.tenant_members
                WHERE tenant_id=%s
                FOR UPDATE""",
            (tenant_id,),
        ))
        active_owners = [row for row in memberships if str(row[1]) == "owner" and str(row[2]) == "active"]
        if len(active_owners) > 1:
            return None
        if active_owners and _uuid(active_owners[0][0]) != owner_user_id:
            return None
        owner_membership = next(
            (row for row in memberships if _uuid(row[0]) == owner_user_id),
            None,
        )
        if owner_membership is None:
            self._execute(
                """INSERT INTO openclaw_account.tenant_members(tenant_id, user_id, role, status)
                   VALUES (%s,%s,'owner','active')""",
                (tenant_id, owner_user_id),
            )
        elif str(owner_membership[1]) != "owner" or str(owner_membership[2]) != "active":
            return None
        return OwnerRecord(
            owner_user_id,
            tenant_id,
            organization_name=normalized_name,
        )

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
    ) -> None:
        if (
            not isinstance(session_id, UUID)
            or not isinstance(session_user_id, UUID)
            or not isinstance(session_tenant_id, UUID)
            or not isinstance(target_tenant_id, UUID)
            or not isinstance(installation_id, UUID)
        ):
            raise RuntimeError("confirmation authority identifiers are invalid")
        if (
            not is_tenant_administrator
            or "tenant:provision" not in scopes
            or not isinstance(authorization_expires_at, datetime)
            or authorization_expires_at.tzinfo is None
            or authorization_expires_at.astimezone(UTC) <= now
            or not str(tenant_key).strip()
            or not str(open_id).strip()
            or not str(credential_ref).strip()
        ):
            raise RuntimeError("confirmation authority is expired or incomplete")
        session = self._one(self._execute(
            """SELECT s.id, s.user_id, s.tenant_id, s.status, s.expires_at,
                      u.status, t.status, m.status
                 FROM openclaw_account.sessions AS s
                 JOIN openclaw_account.users AS u ON u.id=s.user_id
                 JOIN openclaw_account.tenants AS t ON t.id=s.tenant_id
                 JOIN openclaw_account.tenant_members AS m
                   ON m.tenant_id=s.tenant_id AND m.user_id=s.user_id
                WHERE s.id=%s AND s.user_id=%s AND s.tenant_id=%s
                FOR UPDATE OF s, u, t, m""",
            (session_id, session_user_id, session_tenant_id),
        ))
        if (
            not session
            or _uuid(session[0]) != session_id
            or _uuid(session[1]) != session_user_id
            or _uuid(session[2]) != session_tenant_id
            or str(session[3]) != "active"
            or str(session[5]) != "active"
            or str(session[6]) != "active"
            or str(session[7]) != "active"
            or not isinstance(session[4], datetime)
            or session[4].astimezone(UTC) <= now
        ):
            raise RuntimeError("current session authority changed")

        installation = self._one(self._execute(
            """SELECT id, installation_public_id, tenant_key, tenant_id,
                      status, credential_ref
                 FROM media_product.stage1_installations
                WHERE id=%s
                FOR UPDATE""",
            (installation_id,),
        ))
        if (
            not installation
            or _uuid(installation[0]) != installation_id
            or str(installation[1]) != installation_public_id
            or str(installation[2]) != tenant_key
            or installation[3] is not None and _uuid(installation[3]) != target_tenant_id
            or str(installation[4]) not in {"ACTIVE", "NEEDS_ATTENTION"}
            or installation[5] not in {None, credential_ref}
        ):
            raise RuntimeError("installation authority changed")

        target = self._one(self._execute(
            """SELECT primary_user_id, status, tenant_type, workspace_mode,
                      body_authority, organization_name
                 FROM openclaw_account.tenants
                WHERE id=%s
                FOR UPDATE""",
            (target_tenant_id,),
        ))
        if target is not None and (
            _uuid(target[0]) != session_user_id
            or str(target[1]) != "active"
            or str(target[2]) != "organization"
            or str(target[3]) != "organization_lark"
            or str(target[4]) != "lark"
            or not str(target[5] or "").strip()
        ):
            raise RuntimeError("target organization authority changed")

        # Existing Stage 1 generations are locked so a revoke or generation
        # change cannot be hidden between the authority read and P3 mutation.
        bindings = self._all(self._execute(
            """SELECT binding_id, installation_id, tenant_id, tenant_key,
                      generation, status
                 FROM media_product.stage1_binding_generations
                WHERE installation_id=%s AND tenant_id=%s
                FOR UPDATE""",
            (installation_id, target_tenant_id),
        ))
        for binding in bindings:
            if (
                _uuid(binding[1]) != installation_id
                or _uuid(binding[2]) != target_tenant_id
                or str(binding[3]) != tenant_key
                or str(binding[5]) in {"DISABLED", "REVOKED"}
            ):
                raise RuntimeError("Stage 1 binding authority changed")

    def current_bindings(self, installation_id: UUID, tenant_id: UUID) -> Sequence[BindingGeneration]:
        rows = self._all(self._execute(
            """SELECT binding_id, installation_id, tenant_id, tenant_key,
                      generation, status
                 FROM media_product.stage1_binding_generations
                WHERE installation_id=%s AND tenant_id=%s
                  AND status IN ('NEEDS_ATTENTION','ACTIVE')
                ORDER BY generation DESC FOR UPDATE""",
            (installation_id, tenant_id),
        ))
        return tuple(BindingGeneration(int(r[0]), _uuid(r[1]), _uuid(r[2]), str(r[3]), int(r[4]), _state(r[5])) for r in rows)

    def create_binding(self, installation: InstallationTarget, tenant_id: UUID) -> BindingGeneration:
        generation_row = self._one(self._execute(
            """SELECT generation
                 FROM media_product.stage1_binding_generations
                WHERE installation_id=%s
                ORDER BY generation DESC
                LIMIT 1
                FOR UPDATE""",
            (installation.installation_id,),
        ))
        generation = int(generation_row[0]) + 1 if generation_row else 1
        binding_id = self._one(self._execute(
            """INSERT INTO media_product.stage1_binding_generations
               (installation_id, tenant_id, tenant_key, generation, status)
               VALUES (%s,%s,%s,%s,'NEEDS_ATTENTION') RETURNING binding_id""",
            (installation.installation_id, tenant_id, installation.tenant_key, generation),
        ))
        return BindingGeneration(int(binding_id[0]), installation.installation_id, tenant_id, installation.tenant_key, generation, Stage1LifecycleState.NEEDS_ATTENTION)

    def owner_identities(self, binding_id: int, open_id: str) -> Sequence[OwnerIdentity]:
        rows = self._all(self._execute(
            """SELECT tenant_id, user_id, binding_id, open_id, status, external_status
                 FROM openclaw_account.tenant_member_identities
                WHERE binding_id=%s AND open_id=%s FOR UPDATE""",
            (binding_id, open_id),
        ))
        return tuple(
            OwnerIdentity(
                _uuid(r[0]),
                _uuid(r[1]),
                int(r[2]),
                str(r[3]),
                _state(r[4]) if str(r[5]) == "active" else Stage1LifecycleState.NEEDS_ATTENTION,
            )
            for r in rows
        )

    def conflicting_owner_identities(
        self, tenant_id: UUID, binding_id: int, owner_user_id: UUID, open_id: str
    ) -> Sequence[OwnerIdentity]:
        rows = self._all(self._execute(
            """SELECT tenant_id, user_id, binding_id, open_id, status, external_status
                 FROM openclaw_account.tenant_member_identities
                WHERE tenant_id=%s
                  AND status='ACTIVE'
                  AND (
                        (binding_id=%s AND open_id=%s AND user_id<>%s)
                     OR (user_id=%s AND (binding_id<>%s OR open_id<>%s))
                  )
                FOR UPDATE""",
            (tenant_id, binding_id, open_id, owner_user_id, owner_user_id, binding_id, open_id),
        ))
        return tuple(
            OwnerIdentity(
                _uuid(r[0]),
                _uuid(r[1]),
                int(r[2]),
                str(r[3]),
                _state(r[4]) if str(r[5]) == "active" else Stage1LifecycleState.NEEDS_ATTENTION,
            )
            for r in rows
        )

    def create_owner_identity(self, binding: BindingGeneration, owner_user_id: UUID, open_id: str) -> OwnerIdentity:
        self._execute(
            """INSERT INTO openclaw_account.tenant_member_identities
               (tenant_id, user_id, tenant_key, open_id, external_user_id,
                display_name, external_status, binding_id, status)
               VALUES (%s,%s,%s,%s,%s,%s,'active',%s,'ACTIVE')""",
            (binding.tenant_id, owner_user_id, binding.tenant_key, open_id, open_id, open_id, binding.binding_id),
        )
        return OwnerIdentity(binding.tenant_id, owner_user_id, binding.binding_id, open_id, Stage1LifecycleState.ACTIVE)

    def assign_installation(self, installation_id: UUID, tenant_id: UUID, credential_ref: str | None) -> InstallationTarget:
        if not isinstance(credential_ref, str) or not credential_ref.strip() or len(credential_ref.strip()) > 256:
            raise RuntimeError("installation credential reference is required")
        row = self._one(self._execute(
            """UPDATE media_product.stage1_installations
                  SET tenant_id=%s, credential_ref=%s, updated_at=now(), last_seen_at=now()
                WHERE id=%s AND (tenant_id IS NULL OR tenant_id=%s)
                  AND status IN ('ACTIVE','NEEDS_ATTENTION')
            RETURNING id, installation_public_id, app_id, tenant_key, tenant_id, status, credential_ref""",
            (tenant_id, credential_ref.strip(), installation_id, tenant_id),
        ))
        if not row:
            raise RuntimeError("installation assignment did not return a row")
        return self._installation_row(row)

    def write_confirmation_audit(self, receipt: AdminConfirmationReceipt, authorization: TrustedFeishuAdministrator) -> None:
        projection_key = _projection_key(receipt.idempotency_key)
        session_id = self.actor_session_id
        if session_id is None:
            # An HTTP caller always supplies the session.  Direct workers may
            # omit it; retain an immutable machine receipt rather than inventing
            # a foreign-key session identity.
            return
        self._execute(
            """INSERT INTO openclaw_account.admin_audit
               (id, actor_user_id, actor_session_id, action, target_user_id,
                reason, metadata, target_tenant_id, target_public_tenant_id,
                operation_id, idempotency_key, request_fingerprint)
               VALUES (%s,%s,%s,'stage1.organization.confirm',%s,%s,%s::jsonb,%s,%s,%s,%s,%s)""",
            (
                receipt.confirmation_id,
                receipt.owner_user_id,
                session_id,
                receipt.owner_user_id,
                "Feishu 管理员确认组织安装",
                _json({"openId": authorization.open_id, "tenantKey": receipt.tenant_key}),
                receipt.tenant_id,
                receipt.tenant_key,
                _IDEMPOTENCY_OPERATION["confirmation"],
                projection_key,
                receipt.request_digest,
            ),
        )

    def save_confirmation(self, receipt: AdminConfirmationReceipt) -> None:
        self._save_projection(
            scope_id=receipt.installation_id,
            operation=_IDEMPOTENCY_OPERATION["confirmation"],
            key=receipt.idempotency_key,
            request_digest=receipt.request_digest,
            payload={
                "confirmationId": str(receipt.confirmation_id),
                "idempotencyKey": receipt.idempotency_key,
                "requestDigest": receipt.request_digest.hex(),
                "installationId": str(receipt.installation_id),
                "tenantId": str(receipt.tenant_id),
                "ownerUserId": str(receipt.owner_user_id),
                "bindingId": receipt.binding_id,
                "bindingGeneration": receipt.binding_generation,
                "tenantKey": receipt.tenant_key,
                "openId": receipt.open_id,
                "action": receipt.action,
                "confirmedAt": receipt.confirmed_at.isoformat(),
            },
        )

    def readback_confirmation(self, confirmation_id: UUID) -> AdminConfirmationReceipt | None:
        result = self._one(self._execute(
            """SELECT response_json FROM openclaw_account.if2_idempotency_receipts
                WHERE operation_id=%s AND response_json->>'confirmationId'=%s
                  AND state='completed' FOR SHARE""",
            (_IDEMPOTENCY_OPERATION["confirmation"], str(confirmation_id)),
        ))
        if not result:
            return None
        payload = result[0]
        if isinstance(payload, str):
            payload = json.loads(payload)
        if not isinstance(payload, Mapping):
            return None
        return self.confirmation_for_key(_uuid(payload["installationId"]), str(payload["idempotencyKey"]))

    def completed_resource_step(self, installation_id: UUID, idempotency_key: str) -> ResourceStepReceipt | None:
        idempotency_key = _resource_run_key(idempotency_key)
        row = self._one(self._execute(
            """SELECT step_receipt_id, provision_run_id, installation_id,
                      tenant_id, binding_id, step_key, idempotency_key,
                      request_digest, external_reference, finished_at
                 FROM media_product.stage1_provision_step_receipts
                WHERE installation_id=%s AND idempotency_key=%s
                  AND status='SUCCEEDED' FOR SHARE""",
            (installation_id, idempotency_key),
        ))
        if not row:
            return None
        resource_payload = json.loads(str(row[8]))
        resource = ExternalResource(
            kind=str(resource_payload["kind"]), external_id=str(resource_payload["externalId"]),
            open_url=str(resource_payload["openUrl"]), installation_id=_uuid(resource_payload["installationId"]),
            binding_id=int(resource_payload["bindingId"]), binding_generation=int(resource_payload["bindingGeneration"]),
        )
        return ResourceStepReceipt(_uuid(row[0]), _uuid(row[1]), _uuid(row[2]), _uuid(row[3]), int(row[4]), str(row[5]), str(row[6]), bytes(row[7]), resource, str(resource_payload.get("action") or "discovered"), Stage1LifecycleState.ACTIVE, row[9])

    def save_resource_step(self, receipt: ResourceStepReceipt) -> None:
        _resource_run_key(receipt.idempotency_key)
        step_key = _text(receipt.step_key, "step_key", 160)
        completed_at = (
            receipt.completed_at.astimezone(UTC)
            if isinstance(receipt.completed_at, datetime)
            and receipt.completed_at.tzinfo is not None
            and receipt.completed_at.utcoffset() is not None
            else None
        )
        if completed_at is None:
            raise ValueError("completed_at must be timezone aware")
        live = self._live_binding_row(
            receipt.installation_id,
            receipt.tenant_id,
            receipt.binding_id,
            receipt.resource.binding_generation,
        )
        self._assert_live_binding(live)
        self._execute(
            """INSERT INTO media_product.stage1_provision_step_receipts
               (step_receipt_id, provision_run_id, installation_id, tenant_id,
                binding_id, step_key, idempotency_key, attempt, status, state,
                request_digest, result_digest, external_reference, created_at, started_at, finished_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,1,'SUCCEEDED','ACTIVE',%s,%s,%s,%s,%s,%s)
               ON CONFLICT (provision_run_id, step_key) DO UPDATE
                 SET attempt=stage1_provision_step_receipts.attempt + 1,
                     status='SUCCEEDED', state='ACTIVE', request_digest=EXCLUDED.request_digest,
                     result_digest=EXCLUDED.result_digest, external_reference=EXCLUDED.external_reference,
                     failure_code=NULL, started_at=COALESCE(stage1_provision_step_receipts.started_at, EXCLUDED.started_at),
                     finished_at=EXCLUDED.finished_at, updated_at=EXCLUDED.finished_at""",
            (
                receipt.step_receipt_id, receipt.provision_run_id, receipt.installation_id,
                receipt.tenant_id, receipt.binding_id, step_key, receipt.idempotency_key,
                receipt.request_digest, _digest({"resource": receipt.resource.external_id}),
                _json({"kind": receipt.resource.kind, "externalId": receipt.resource.external_id,
                       "openUrl": receipt.resource.open_url, "installationId": str(receipt.resource.installation_id),
                       "bindingId": receipt.resource.binding_id, "bindingGeneration": receipt.resource.binding_generation,
                       "action": receipt.action}),
                completed_at,
                completed_at,
                completed_at,
            ),
        )

    def current_resource_context(self, context: ResourceBindingContext) -> ResourceBindingContext | None:
        target = context.resource_target
        if target is None:
            return None
        if (
            target.installation_id != context.installation_id
            or target.tenant_id != context.tenant_id
            or target.tenant_key != context.tenant_key
            or target.binding_id != context.binding_id
            or target.binding_generation != context.binding_generation
            or target.space_id != context.space_id
            or target.parent_node_token != context.parent_node_token
        ):
            return None
        row = self._live_binding_row(
            context.installation_id,
            context.tenant_id,
            context.binding_id,
            context.binding_generation,
        )
        try:
            self._assert_live_binding(row)
        except RuntimeError:
            return None
        if (
            str(row[2]) != context.tenant_key
            or str(row[8]) != context.tenant_key
            or str(row[4]) != context.credential_ref
        ):
            return None
        return ResourceBindingContext(
            installation_id=context.installation_id,
            tenant_id=context.tenant_id,
            binding_id=context.binding_id,
            binding_generation=context.binding_generation,
            tenant_key=str(row[2]),
            credential_ref=str(row[4]),
            state=_state(row[9]),
            space_id=context.space_id,
            parent_node_token=context.parent_node_token,
            resource_target=target,
        )

    def run_for_key(self, installation_id: UUID, idempotency_key: str) -> ProvisionRun | None:
        idempotency_key = _resource_run_key(idempotency_key)
        return self._run_row(self._one(self._execute(
            """SELECT provision_run_id, installation_id, tenant_id, idempotency_key,
                      request_digest, status, state, updated_at, finished_at
                 FROM media_product.stage1_provision_runs
                WHERE installation_id=%s AND idempotency_key=%s FOR SHARE""",
            (installation_id, idempotency_key),
        )))

    def _run_row(self, row: Sequence[Any] | None) -> ProvisionRun | None:
        if not row:
            return None
        failed = self._one(self._execute(
            "SELECT step_key, attempt, updated_at FROM media_product.stage1_provision_step_receipts WHERE provision_run_id=%s AND status='FAILED' ORDER BY updated_at DESC LIMIT 1",
            (_uuid(row[0]),),
        ))
        failed_step = str(failed[0]) if failed else None
        retry_count = int(failed[1]) if failed and failed[1] is not None else 0
        retry_after = (
            failed[2] + timedelta(seconds=retry_delay_seconds(retry_count))
            if failed and failed[2] is not None and retry_count > 0
            else None
        )
        return ProvisionRun(
            _uuid(row[0]),
            _uuid(row[1]),
            _uuid(row[2]),
            str(row[3]),
            bytes(row[4]),
            _run_state(row[5]),
            _state(row[6]),
            None,
            None,
            failed_step,
            retry_count,
            retry_after,
        )

    def create_run(self, run: ProvisionRun) -> ProvisionRun:
        _resource_run_key(run.idempotency_key)
        row = self._one(self._execute(
            """WITH selected_binding AS (
                   SELECT b.binding_id
                     FROM media_product.stage1_binding_generations AS b
                     JOIN media_product.stage1_installations AS i
                       ON i.id=b.installation_id
                      AND i.tenant_id=b.tenant_id
                      AND i.tenant_key=b.tenant_key
                    WHERE b.installation_id=%s AND b.tenant_id=%s
                      AND i.status IN ('ACTIVE','NEEDS_ATTENTION')
                      AND i.credential_ref IS NOT NULL
                      AND b.status IN ('ACTIVE','NEEDS_ATTENTION')
                    ORDER BY b.generation DESC
                    LIMIT 1
                    FOR UPDATE
               )
               INSERT INTO media_product.stage1_provision_runs
               (provision_run_id, installation_id, tenant_id, binding_id,
                idempotency_key, request_digest, status, state)
               SELECT %s,%s,%s,binding_id,%s,%s,%s,%s
                 FROM selected_binding
               RETURNING binding_id""",
            (
                run.installation_id,
                run.tenant_id,
                run.provision_run_id,
                run.installation_id,
                run.tenant_id,
                run.idempotency_key,
                run.request_digest,
                run.status.value,
                run.state.value,
            ),
        ))
        if not row:
            raise RuntimeError("provision run requires one current binding generation")
        return run

    def claim_run(self, provision_run_id: UUID, lease_owner: str, lease_expires_at: datetime, now: datetime) -> ProvisionRun | None:
        # 042 intentionally has no lease columns.  RUNNING + updated_at is the
        # durable lease, and an expired runner can be reclaimed transactionally.
        context = self._one(self._execute(
            """SELECT installation_id, tenant_id, binding_id
                 FROM media_product.stage1_provision_runs
                WHERE provision_run_id=%s
                FOR UPDATE""",
            (provision_run_id,),
        ))
        if not context or context[1] is None or context[2] is None:
            return None
        live = self._live_binding_row(
            _uuid(context[0]),
            _uuid(context[1]),
            int(context[2]),
        )
        self._assert_live_binding(live)
        row = self._one(self._execute(
            """UPDATE media_product.stage1_provision_runs
                  SET status='RUNNING', started_at=COALESCE(started_at, now()), updated_at=now()
                WHERE provision_run_id=%s AND status <> 'SUCCEEDED'
                  AND (status <> 'RUNNING' OR updated_at < %s)
            RETURNING provision_run_id, installation_id, tenant_id, idempotency_key,
                      request_digest, status, state, updated_at, finished_at""",
            (provision_run_id, now - timedelta(seconds=300)),
        ))
        return self._run_row(row)

    def completed_step_keys(self, provision_run_id: UUID) -> Sequence[str]:
        rows = self._all(self._execute(
            "SELECT step_key FROM media_product.stage1_provision_step_receipts WHERE provision_run_id=%s AND status='SUCCEEDED' ORDER BY step_key",
            (provision_run_id,),
        ))
        return tuple(str(row[0]) for row in rows)

    def mark_step_succeeded(self, provision_run_id: UUID, step_key: str) -> None:
        receipt = self._one(self._execute(
            """SELECT r.installation_id, r.tenant_id, r.binding_id, s.binding_id,
                          s.external_reference
                 FROM media_product.stage1_provision_step_receipts AS s
                 JOIN media_product.stage1_provision_runs AS r
                   ON r.provision_run_id=s.provision_run_id
                WHERE s.provision_run_id=%s AND s.step_key=%s
                FOR UPDATE OF s, r""",
            (provision_run_id, step_key),
        ))
        if not receipt or receipt[1] is None or receipt[2] is None or receipt[3] is None:
            raise RuntimeError("provision step success requires a durable binding context")
        live = self._live_binding_row(
            _uuid(receipt[0]),
            _uuid(receipt[1]),
            int(receipt[2]),
        )
        self._assert_live_binding(live)
        if int(receipt[3]) != int(receipt[2]):
            raise RuntimeError("provision step binding context changed")
        try:
            resource_payload = json.loads(str(receipt[4]))
            if (
                int(resource_payload["bindingId"]) != int(receipt[2])
                or int(resource_payload["bindingGeneration"]) != int(live[6])
            ):
                raise RuntimeError("provision step binding generation changed")
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError("provision step resource receipt is invalid") from exc
        self._execute(
            """UPDATE media_product.stage1_provision_step_receipts
                  SET status='SUCCEEDED', state='ACTIVE', started_at=COALESCE(started_at, now()), finished_at=now(), updated_at=now()
                WHERE provision_run_id=%s AND step_key=%s
                  AND status <> 'SUCCEEDED'""",
            (provision_run_id, step_key),
        )

    def mark_run_succeeded(self, provision_run_id: UUID) -> ProvisionRun:
        run_context = self._one(self._execute(
            """SELECT installation_id, tenant_id, binding_id
                 FROM media_product.stage1_provision_runs
                WHERE provision_run_id=%s
                FOR UPDATE""",
            (provision_run_id,),
        ))
        if not run_context or run_context[1] is None or run_context[2] is None:
            raise RuntimeError("provision success requires a durable binding context")
        installation_id = _uuid(run_context[0])
        tenant_id = _uuid(run_context[1])
        binding_id = int(run_context[2])
        live = self._live_binding_row(installation_id, tenant_id, binding_id)
        self._assert_live_binding(live)
        if _uuid(live[0]) != installation_id or _uuid(live[7]) != tenant_id or int(live[5]) != binding_id:
            raise RuntimeError("provision success binding context changed")
        binding = self._one(self._execute(
            """UPDATE media_product.stage1_binding_generations
                  SET status='ACTIVE', activated_at=COALESCE(activated_at, now()),
                      disabled_at=NULL, updated_at=now()
                WHERE installation_id=%s AND tenant_id=%s AND binding_id=%s
                  AND generation=%s AND status IN ('ACTIVE','NEEDS_ATTENTION')
            RETURNING binding_id""",
            (installation_id, tenant_id, binding_id, int(live[6])),
        ))
        if not binding or int(binding[0]) != binding_id:
            raise RuntimeError("provision success binding activation failed")
        installation = self._one(self._execute(
            """UPDATE media_product.stage1_installations
                  SET status='ACTIVE', updated_at=now(), last_seen_at=now()
                WHERE id=%s AND tenant_id=%s AND credential_ref IS NOT NULL
                  AND status IN ('ACTIVE','NEEDS_ATTENTION')
            RETURNING id""",
            (installation_id, tenant_id),
        ))
        if not installation or _uuid(installation[0]) != installation_id:
            raise RuntimeError("provision success installation activation failed")
        row = self._one(self._execute(
            """UPDATE media_product.stage1_provision_runs
                  SET status='SUCCEEDED', state='ACTIVE', finished_at=now(), updated_at=now()
                WHERE provision_run_id=%s
            RETURNING provision_run_id, installation_id, tenant_id, idempotency_key, request_digest, status, state, updated_at, finished_at""",
            (provision_run_id,),
        ))
        if not row:
            raise RuntimeError("provision success readback failed")
        return self._run_row(row)  # type: ignore[return-value]

    def mark_run_failed(self, provision_run_id: UUID, step_key: str, failure_code: str, retry_after: datetime) -> ProvisionRun:
        step_key = _text(step_key, "step_key", 160)
        failure_code = _text(failure_code, "failure_code", 160)
        run_identity = self._one(self._execute(
            "SELECT installation_id, tenant_id, idempotency_key, request_digest FROM media_product.stage1_provision_runs WHERE provision_run_id=%s FOR UPDATE",
            (provision_run_id,),
        ))
        if not run_identity:
            raise RuntimeError("provision run was not found")
        existing_step = self._one(self._execute(
            """SELECT attempt
                 FROM media_product.stage1_provision_step_receipts
                WHERE provision_run_id=%s AND step_key=%s
                FOR UPDATE""",
            (provision_run_id, step_key),
        ))
        attempt = int(existing_step[0]) + 1 if existing_step else 1
        if attempt <= 0 or not isinstance(retry_after, datetime) or retry_after.tzinfo is None or retry_after.utcoffset() is None:
            raise RuntimeError("provision retry authority is invalid")
        retry_deadline = retry_after.astimezone(UTC)
        failed_at = retry_deadline - timedelta(seconds=retry_delay_seconds(attempt))
        self._execute(
            """INSERT INTO media_product.stage1_provision_step_receipts
               (step_receipt_id, provision_run_id, installation_id, tenant_id,
                step_key, idempotency_key, attempt, status, state,
                request_digest, failure_code, created_at, started_at, finished_at, updated_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,'FAILED','NEEDS_ATTENTION',%s,%s,%s,%s,%s,%s)
               ON CONFLICT (provision_run_id, step_key) DO UPDATE
                 SET idempotency_key=EXCLUDED.idempotency_key,
                     attempt=EXCLUDED.attempt, status='FAILED', state='NEEDS_ATTENTION',
                     request_digest=EXCLUDED.request_digest, failure_code=EXCLUDED.failure_code,
                     finished_at=EXCLUDED.finished_at, updated_at=EXCLUDED.updated_at""",
            (
                uuid4(),
                provision_run_id,
                run_identity[0],
                run_identity[1],
                step_key,
                f"failed-{uuid4().hex}",
                attempt,
                bytes(run_identity[3]),
                failure_code,
                failed_at,
                failed_at,
                failed_at,
                failed_at,
            ),
        )
        row = self._one(self._execute(
            """UPDATE media_product.stage1_provision_runs
                  SET status='FAILED', state='NEEDS_ATTENTION', updated_at=%s
                WHERE provision_run_id=%s
            RETURNING provision_run_id, installation_id, tenant_id, idempotency_key, request_digest, status, state, updated_at, finished_at""",
            (failed_at, provision_run_id),
        ))
        if not row:
            raise RuntimeError("provision failure readback failed")
        return self._run_row(row)  # type: ignore[return-value]

    def run_for_id(self, provision_run_id: UUID) -> ProvisionRun | None:
        return self._run_row(self._one(self._execute(
            """SELECT provision_run_id, installation_id, tenant_id, idempotency_key,
                      request_digest, status, state, updated_at, finished_at
                 FROM media_product.stage1_provision_runs WHERE provision_run_id=%s FOR SHARE""",
            (provision_run_id,),
        )))

    def deprovision_receipt(self, installation_id: UUID, idempotency_key: str) -> DeprovisionReceipt | None:
        result = self._one(self._execute(
            """SELECT response_json FROM openclaw_account.if2_idempotency_receipts
                WHERE scope_kind='tenant' AND scope_id=%s AND operation_id=%s
                  AND idempotency_key=%s AND state='completed' FOR UPDATE""",
            (installation_id, _IDEMPOTENCY_OPERATION["deprovision"], _projection_key(idempotency_key)),
        ))
        if not result:
            return None
        payload = result[0]
        if isinstance(payload, str):
            payload = json.loads(payload)
        return self._deprovision_from_payload(payload) if isinstance(payload, Mapping) else None

    @staticmethod
    def _deprovision_from_payload(payload: Mapping[str, Any]) -> DeprovisionReceipt:
        return DeprovisionReceipt(_uuid(payload["receiptId"]), _uuid(payload["installationId"]), _uuid(payload["tenantId"]), _state(payload["state"]), str(payload["idempotencyKey"]), bytes.fromhex(str(payload["requestDigest"])), int(payload["revokedSessionCount"]), datetime.fromisoformat(str(payload["revokedAt"])), bool(payload["externalCredentialRevoked"]))

    def installation_for_deprovision(self, installation_id: UUID) -> InstallationTarget | None:
        row = self._one(self._execute(
            "SELECT id, installation_public_id, app_id, tenant_key, tenant_id, status, credential_ref FROM media_product.stage1_installations WHERE id=%s FOR UPDATE",
            (installation_id,),
        ))
        return self._installation_row(row) if row else None

    def deactivate_binding_and_members(self, installation_id: UUID, tenant_id: UUID, state: Stage1LifecycleState, occurred_at: datetime) -> int:
        self._execute(
            "UPDATE media_product.stage1_binding_generations SET status=%s, updated_at=%s, disabled_at=CASE WHEN %s='DISABLED' THEN %s ELSE disabled_at END, revoked_at=CASE WHEN %s='REVOKED' THEN %s ELSE revoked_at END WHERE installation_id=%s AND tenant_id=%s AND status <> 'REVOKED'",
            (state.value, occurred_at, state.value, occurred_at, state.value, occurred_at, installation_id, tenant_id),
        )
        self._execute(
            "UPDATE media_product.stage1_installations SET status=%s, updated_at=%s WHERE id=%s",
            (state.value, occurred_at, installation_id),
        )
        session_result = self._execute(
            "UPDATE openclaw_account.sessions SET status='revoked', revoked_at=%s, last_seen_at=%s WHERE tenant_id=%s AND status='active' RETURNING id",
            (occurred_at, occurred_at, tenant_id),
        )
        revoked_sessions = len(self._all(session_result))
        self._execute(
            "UPDATE openclaw_account.tenant_member_identities SET status=%s, external_status='inactive', updated_at=%s WHERE tenant_id=%s AND binding_id IN (SELECT binding_id FROM media_product.stage1_binding_generations WHERE installation_id=%s AND tenant_id=%s) RETURNING tenant_id",
            (state.value, occurred_at, tenant_id, installation_id, tenant_id),
        )
        return revoked_sessions

    def revoke_cached_credentials(self, installation_id: UUID, occurred_at: datetime) -> None:
        self._execute("UPDATE media_product.stage1_installations SET credential_ref=NULL, updated_at=%s WHERE id=%s", (occurred_at, installation_id))

    def save_deprovision_receipt(self, receipt: DeprovisionReceipt) -> None:
        self._save_projection(
            scope_id=receipt.installation_id,
            operation=_IDEMPOTENCY_OPERATION["deprovision"],
            key=receipt.idempotency_key,
            request_digest=receipt.request_digest,
            payload={"receiptId": str(receipt.receipt_id), "installationId": str(receipt.installation_id), "tenantId": str(receipt.tenant_id), "state": receipt.state.value, "idempotencyKey": receipt.idempotency_key, "requestDigest": receipt.request_digest.hex(), "revokedSessionCount": receipt.revoked_session_count, "revokedAt": receipt.revoked_at.isoformat(), "externalCredentialRevoked": receipt.external_credential_revoked},
        )

    def write_deprovision_audit(self, receipt: DeprovisionReceipt, actor_user_id: UUID) -> None:
        if self.actor_session_id is None:
            return
        self._execute(
            """INSERT INTO openclaw_account.admin_audit
               (id, actor_user_id, actor_session_id, action, target_user_id, reason, metadata, target_tenant_id, target_public_tenant_id, operation_id, idempotency_key, request_fingerprint)
               VALUES (%s,%s,%s,'stage1.organization.deprovision',%s,%s,%s::jsonb,%s,%s,%s,%s,%s)""",
            (receipt.receipt_id, actor_user_id, self.actor_session_id, actor_user_id, "停用组织接入并撤销本地访问", _json({"state": receipt.state.value}), receipt.tenant_id, str(receipt.tenant_id), _IDEMPOTENCY_OPERATION["deprovision"], _projection_key(receipt.idempotency_key), receipt.request_digest),
        )

    def mark_external_credential_revoked(self, receipt_id: UUID) -> DeprovisionReceipt:
        result = self._one(self._execute(
            """SELECT response_json FROM openclaw_account.if2_idempotency_receipts
                WHERE operation_id=%s AND response_json->>'receiptId'=%s FOR UPDATE""",
            (_IDEMPOTENCY_OPERATION["deprovision"], str(receipt_id)),
        ))
        if not result:
            raise RuntimeError("deprovision receipt not found")
        payload = result[0]
        if isinstance(payload, str):
            payload = json.loads(payload)
        if not isinstance(payload, Mapping):
            raise RuntimeError("deprovision receipt is invalid")
        updated = dict(payload)
        updated["externalCredentialRevoked"] = True
        receipt = self._deprovision_from_payload(updated)
        self._save_projection(scope_id=receipt.installation_id, operation=_IDEMPOTENCY_OPERATION["deprovision"], key=receipt.idempotency_key, request_digest=receipt.request_digest, payload=updated)
        return receipt

    def binding_context_for_actor(self, actor: TrustedProvisionActor) -> tuple[UUID, int, int, str, str] | None:
        row = self._one(self._execute(
            """SELECT b.tenant_id, b.binding_id, b.generation, b.tenant_key, i.credential_ref
                 FROM media_product.stage1_binding_generations b
                 JOIN media_product.stage1_installations i ON i.id=b.installation_id
                WHERE b.installation_id=%s AND b.tenant_id=%s
                  AND i.tenant_id=b.tenant_id
                  AND i.tenant_key=b.tenant_key
                  AND i.status IN ('ACTIVE','NEEDS_ATTENTION')
                  AND i.credential_ref IS NOT NULL
                  AND b.status IN ('ACTIVE','NEEDS_ATTENTION')
                ORDER BY b.generation DESC LIMIT 1 FOR UPDATE""",
            (actor.installation_id, actor.tenant_id),
        ))
        if not row or not str(row[4] or "").strip():
            return None
        return _uuid(row[0]), int(row[1]), int(row[2]), str(row[3]), str(row[4] or "")

    def installation_for_tenant(self, tenant_id: UUID) -> InstallationTarget | None:
        row = self._one(self._execute(
            """SELECT id, installation_public_id, app_id, tenant_key, tenant_id, status, credential_ref
                 FROM media_product.stage1_installations WHERE tenant_id=%s
                ORDER BY updated_at DESC LIMIT 1 FOR SHARE""",
            (tenant_id,),
        ))
        return self._installation_row(row) if row else None

    def owner_installations(self, user_id: UUID, tenant_id: UUID) -> Sequence[InstallationTarget]:
        rows = self._all(self._execute(
            """SELECT installation.id, installation.installation_public_id,
                      installation.app_id, installation.tenant_key,
                      installation.tenant_id, installation.status,
                      installation.credential_ref
                 FROM media_product.stage1_installations AS installation
                 JOIN openclaw_account.tenant_members AS member
                   ON member.tenant_id=installation.tenant_id
                WHERE installation.tenant_id=%s AND member.user_id=%s
                  AND installation.status IN ('ACTIVE','NEEDS_ATTENTION')
                  AND member.role='owner' AND member.status='active'
                ORDER BY installation.updated_at DESC
                FOR SHARE OF installation, member""",
            (tenant_id, user_id),
        ))
        return tuple(self._installation_row(row) for row in rows)

    def resource_target_for_context(self, context: Any) -> tuple[str, str] | None:
        # 042 intentionally has no resource target columns. Targets come from
        # the server-owned grant/config resolver and are checked against the
        # live binding by current_resource_context before every external call.
        return None

    def open_id_for_user(self, tenant_id: UUID, user_id: UUID) -> str | None:
        row = self._one(self._execute(
            """SELECT open_id FROM openclaw_account.tenant_member_identities
                WHERE tenant_id=%s AND user_id=%s AND status='ACTIVE'
                ORDER BY updated_at DESC LIMIT 1 FOR SHARE""",
            (tenant_id, user_id),
        ))
        return str(row[0]) if row and row[0] else None


class Stage1PostgresRepository(
    AdminConfirmationRepository,
    ProvisionRunRepository,
    ResourceInitializationRepository,
    DeprovisionRepository,
    MemberOnboardingRepository,
):
    """Connection-factory backed repository used by the HTTP runtime."""

    def __init__(self, connection_factory: Callable[[], Any], *, actor_session_id: UUID | None = None) -> None:
        self._connection_factory = connection_factory
        self._actor_session_id = actor_session_id

    @contextmanager
    def transaction(self) -> Iterator[_ConnectionStore]:
        connection = self._connection_factory()
        store = _ConnectionStore(connection, actor_session_id=self._actor_session_id)
        try:
            yield store
            commit = getattr(connection, "commit", None)
            if callable(commit):
                commit()
        except Exception:
            rollback = getattr(connection, "rollback", None)
            if callable(rollback):
                rollback()
            raise
        finally:
            close = getattr(connection, "close", None)
            if callable(close):
                close()

    def _read(self, callback: Callable[[_ConnectionStore], Any]) -> Any:
        with self.transaction() as store:
            return callback(store)

    def run_for_key(self, installation_id: UUID, idempotency_key: str) -> ProvisionRun | None:
        return self._read(lambda store: store.run_for_key(installation_id, idempotency_key))

    def create_run(self, run: ProvisionRun) -> ProvisionRun:
        with self.transaction() as store:
            return store.create_run(run)

    def claim_run(self, provision_run_id: UUID, lease_owner: str, lease_expires_at: datetime, now: datetime) -> ProvisionRun | None:
        with self.transaction() as store:
            return store.claim_run(provision_run_id, lease_owner, lease_expires_at, now)

    def completed_step_keys(self, provision_run_id: UUID) -> Sequence[str]:
        return self._read(lambda store: store.completed_step_keys(provision_run_id))

    def mark_step_succeeded(self, provision_run_id: UUID, step_key: str) -> None:
        with self.transaction() as store:
            store.mark_step_succeeded(provision_run_id, step_key)

    def mark_run_succeeded(self, provision_run_id: UUID) -> ProvisionRun:
        with self.transaction() as store:
            return store.mark_run_succeeded(provision_run_id)

    def mark_run_failed(self, provision_run_id: UUID, step_key: str, failure_code: str, retry_after: datetime) -> ProvisionRun:
        with self.transaction() as store:
            return store.mark_run_failed(provision_run_id, step_key, failure_code, retry_after)

    def run_for_id(self, provision_run_id: UUID) -> ProvisionRun | None:
        return self._read(lambda store: store.run_for_id(provision_run_id))

    def completed_resource_step(self, installation_id: UUID, idempotency_key: str) -> ResourceStepReceipt | None:
        return self._read(lambda store: store.completed_resource_step(installation_id, idempotency_key))

    def save_resource_step(self, receipt: ResourceStepReceipt) -> None:
        with self.transaction() as store:
            store.save_resource_step(receipt)

    def current_resource_context(self, context: ResourceBindingContext) -> ResourceBindingContext | None:
        return self._read(lambda store: store.current_resource_context(context))

    def resource_target_for_context(self, context: Any) -> tuple[str, str] | None:
        return self._read(lambda store: store.resource_target_for_context(context))

    def open_id_for_user(self, tenant_id: UUID, user_id: UUID) -> str | None:
        return self._read(lambda store: store.open_id_for_user(tenant_id, user_id))


__all__ = ["Stage1PostgresRepository"]
