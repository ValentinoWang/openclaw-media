"""Server-only authorization for Stage 1 organization provisioning."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from uuid import UUID

from ..account.auth import AccountSession
from .stage1_organization_provisioning import (
    REQUIRED_ADMIN_SCOPE,
    ProvisioningError,
    ResourceTarget,
    InstallationTarget,
    TrustedFeishuAdministrator,
)
from .stage1_provision_models import Stage1LifecycleState


UTC = timezone.utc


def _fail(code: str, detail: str, *, status: int) -> None:
    raise ProvisioningError(code, detail, status=status)


def _text(value: object, field_name: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized or len(normalized) > maximum:
        raise ValueError(f"{field_name} is invalid")
    return normalized


def _uuid(value: object, field_name: str) -> UUID:
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError(f"{field_name} is invalid") from exc


def _aware_datetime(value: object, field_name: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be an ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field_name} is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone")
    return parsed.astimezone(UTC)


@dataclass(frozen=True, repr=False)
class AuthorizedProvisioningContext:
    """A complete server-derived grant consumed by the provisioning runtime."""

    grant_id: str
    user_id: UUID
    tenant_id: UUID
    installation_id: UUID
    installation_public_id: str
    tenant_key: str
    organization_name: str
    authorization: TrustedFeishuAdministrator = field(repr=False)
    credential_ref: str = field(repr=False, default="")
    resource_target: ResourceTarget | None = field(default=None, repr=False)
    session_id: UUID | None = None
    session_tenant_id: UUID | None = None

    def __repr__(self) -> str:
        return "AuthorizedProvisioningContext(<redacted>)"


@dataclass(frozen=True, repr=False)
class _ConfiguredGrant:
    grant_id: str
    user_id: UUID
    tenant_id: UUID
    installation_id: UUID
    installation_public_id: str | None
    tenant_key: str
    open_id: str
    scopes: tuple[str, ...]
    expires_at: datetime
    is_tenant_administrator: bool
    organization_name: str
    credential_ref: str = field(repr=False)
    resource_target: ResourceTarget | None = field(default=None, repr=False)

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "_ConfiguredGrant":
        scopes_value = value.get("scopes")
        if not isinstance(scopes_value, list) or not scopes_value:
            raise ValueError("scopes must be a non-empty list")
        scopes = tuple(_text(item, "scope", 160) for item in scopes_value)
        if len(scopes) != len(set(scopes)):
            raise ValueError("scopes must be unique")
        administrator = value.get("isTenantAdministrator")
        if not isinstance(administrator, bool):
            raise ValueError("isTenantAdministrator must be a boolean")
        organization_name = _text(value.get("organizationName"), "organizationName", 120)
        installation_public_id_value = value.get("installationPublicId")
        installation_public_id = (
            None
            if installation_public_id_value is None
            else _text(installation_public_id_value, "installationPublicId", 128)
        )
        target_value = value.get("resourceTarget")
        target: ResourceTarget | None = None
        if target_value is not None:
            if not isinstance(target_value, Mapping):
                raise ValueError("resourceTarget must be an object")
            target_installation_id = _uuid(
                target_value.get("installationId", value.get("installationId")),
                "resourceTarget.installationId",
            )
            target_tenant_id = _uuid(
                target_value.get("tenantId", value.get("tenantId")),
                "resourceTarget.tenantId",
            )
            target_tenant_key = _text(
                target_value.get("tenantKey", value.get("tenantKey")),
                "resourceTarget.tenantKey",
                128,
            )
            space_id = _text(target_value.get("spaceId"), "resourceTarget.spaceId", 256)
            parent_node_token = _text(
                target_value.get("parentNodeToken"),
                "resourceTarget.parentNodeToken",
                256,
            )
            binding_id_value = target_value.get("bindingId")
            binding_generation_value = target_value.get("generation")
            if binding_id_value is None or binding_generation_value is None:
                raise ValueError("resourceTarget binding generation is required")
            binding_id = int(binding_id_value)
            binding_generation = int(binding_generation_value)
            if binding_id <= 0:
                raise ValueError("resourceTarget.bindingId is invalid")
            if binding_generation <= 0:
                raise ValueError("resourceTarget.generation is invalid")
            target = ResourceTarget(
                target_installation_id,
                target_tenant_id,
                target_tenant_key,
                space_id,
                parent_node_token,
                binding_id,
                binding_generation,
            )
        return cls(
            grant_id=_text(value.get("grantId"), "grantId", 160),
            user_id=_uuid(value.get("userId"), "userId"),
            tenant_id=_uuid(value.get("tenantId"), "tenantId"),
            installation_id=_uuid(value.get("installationId"), "installationId"),
            installation_public_id=installation_public_id,
            tenant_key=_text(value.get("tenantKey"), "tenantKey", 128),
            open_id=_text(value.get("openId"), "openId", 512),
            scopes=scopes,
            expires_at=_aware_datetime(value.get("expiresAt"), "expiresAt"),
            is_tenant_administrator=administrator,
            organization_name=organization_name,
            credential_ref=_text(value.get("credentialRef"), "credentialRef", 256),
            resource_target=target,
        )

    def __repr__(self) -> str:
        return "_ConfiguredGrant(<redacted>)"


class Stage1AdministratorAuthorizer:
    """Resolve a current owner identity and an exact server-held admin grant."""

    def __init__(
        self,
        connection_factory: Callable[[], Any],
        grants_file: str | Path | None,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if not callable(connection_factory):
            raise TypeError("connection factory is required")
        self._connection_factory = connection_factory
        normalized_path = str(grants_file or "").strip()
        self._grants_file = Path(normalized_path).expanduser() if normalized_path else None
        self._now = now or (lambda: datetime.now(UTC))

    @staticmethod
    def _rows(result: Any) -> list[Sequence[object]]:
        fetchall = getattr(result, "fetchall", None)
        return list(fetchall()) if callable(fetchall) else []

    def _current_authority(
        self, session: AccountSession, grant: _ConfiguredGrant, now: datetime
    ) -> InstallationTarget:
        connection = self._connection_factory()
        try:
            result = connection.execute(
                """SELECT s.id, s.user_id, s.tenant_id, s.status, s.expires_at,
                          u.status, t.status, m.status,
                          installation.id, installation.installation_public_id,
                          installation.app_id, installation.tenant_key, installation.tenant_id,
                          installation.status, installation.credential_ref
                     FROM openclaw_account.sessions AS s
                     JOIN openclaw_account.users AS u ON u.id=s.user_id
                     JOIN openclaw_account.tenants AS t ON t.id=s.tenant_id
                     JOIN openclaw_account.tenant_members AS m
                       ON m.tenant_id=s.tenant_id AND m.user_id=s.user_id
                    JOIN media_product.stage1_installations AS installation
                      ON installation.id=%s
                     AND installation.tenant_key=%s
                    WHERE s.id=%s AND s.user_id=%s AND s.tenant_id=%s
                    FOR SHARE OF s, u, t, m, installation""",
                (
                    grant.installation_id,
                    grant.tenant_key,
                    session.session_id,
                    session.user_id,
                    session.tenant_id,
                ),
            )
            rows = self._rows(result)
            commit = getattr(connection, "commit", None)
            if callable(commit):
                commit()
        except Exception as exc:
            rollback = getattr(connection, "rollback", None)
            if callable(rollback):
                rollback()
            _fail(
                "feishu_administrator_authorization_unavailable",
                "Feishu 管理员授权暂不可用",
                status=503,
            )
            raise AssertionError("unreachable") from exc
        finally:
            close = getattr(connection, "close", None)
            if callable(close):
                close()
        if len(rows) != 1:
            _fail(
                "feishu_administrator_authorization_forbidden",
                "当前会话或安装授权无效",
                status=403,
            )
        row = rows[0]
        session_expires_at = row[4]
        if not isinstance(session_expires_at, datetime) or session_expires_at.tzinfo is None:
            _fail("feishu_administrator_authorization_forbidden", "当前会话无效", status=403)
        if (
            _uuid(row[0], "session id") != session.session_id
            or _uuid(row[1], "session user id") != session.user_id
            or _uuid(row[2], "session tenant id") != session.tenant_id
            or str(row[3]) != "active"
            or str(row[5]) != "active"
            or str(row[6]) != "active"
            or str(row[7]) != "active"
            or session_expires_at.astimezone(UTC) <= now
            or session.expires_at.astimezone(UTC) <= now
        ):
            _fail("feishu_administrator_authorization_forbidden", "当前会话无效", status=403)
        installation = InstallationTarget(
            installation_id=_uuid(row[8], "installation id"),
            installation_public_id=str(row[9]),
            app_id=str(row[10]),
            tenant_key=str(row[11]),
            tenant_id=None if row[12] is None else _uuid(row[12], "installation tenant id"),
            state=Stage1LifecycleState(str(row[13])),
            credential_ref=None if row[14] is None else str(row[14]),
        )
        if (
            installation.installation_id != grant.installation_id
            or (
                grant.installation_public_id is not None
                and installation.installation_public_id != grant.installation_public_id
            )
            or installation.tenant_key != grant.tenant_key
            or installation.tenant_id not in {None, grant.tenant_id}
            or installation.state not in {
                Stage1LifecycleState.ACTIVE,
                Stage1LifecycleState.NEEDS_ATTENTION,
            }
            or installation.credential_ref not in {None, grant.credential_ref}
        ):
            _fail("feishu_administrator_authorization_forbidden", "当前安装授权无效", status=403)
        if grant.resource_target is not None and (
            grant.resource_target.installation_id != installation.installation_id
            or grant.resource_target.tenant_id != grant.tenant_id
            or grant.resource_target.tenant_key != grant.tenant_key
        ):
            _fail("feishu_administrator_authorization_forbidden", "当前资源目标无效", status=403)
        return installation

    def resource_target_for_context(
        self, context: Any
    ) -> ResourceTarget | None:
        """Resolve the server-owned target for one live binding context.

        Canonical 042 deliberately has no resource target columns.  The grant
        document is therefore the only configuration source, and the caller
        still has to compare the returned target with the live binding before
        every external operation.
        """
        installation_id = getattr(context, "installation_id", None)
        tenant_id = getattr(context, "tenant_id", None)
        tenant_key = getattr(context, "tenant_key", None)
        if not isinstance(installation_id, UUID) or not isinstance(tenant_id, UUID):
            return None
        try:
            normalized_tenant_key = _text(tenant_key, "tenant_key", 128)
        except ValueError:
            return None
        matches = tuple(
            grant
            for grant in self._load_grants()
            if grant.installation_id == installation_id
            and grant.tenant_id == tenant_id
            and grant.tenant_key == normalized_tenant_key
            and grant.resource_target is not None
        )
        if len(matches) != 1:
            return None
        target = matches[0].resource_target
        if target is None:
            return None
        binding_id = getattr(context, "binding_id", None)
        binding_generation = getattr(context, "binding_generation", None)
        if target.binding_id != binding_id:
            return None
        if target.binding_generation != binding_generation:
            return None
        return target

    def _load_grants(self) -> tuple[_ConfiguredGrant, ...]:
        if self._grants_file is None:
            _fail(
                "feishu_administrator_authorization_unavailable",
                "Feishu 管理员授权暂不可用",
                status=503,
            )
        try:
            raw = json.loads(self._grants_file.read_text(encoding="utf-8"))
            if not isinstance(raw, Mapping):
                raise ValueError("grant document must be an object")
            if raw.get("schemaVersion") != "media.stage1.administrator-grants.v1":
                raise ValueError("unsupported grant schema")
            values = raw.get("grants")
            if not isinstance(values, list):
                raise ValueError("grants must be a list")
            grants = tuple(
                _ConfiguredGrant.from_mapping(item)
                for item in values
                if isinstance(item, Mapping)
            )
            if len(grants) != len(values):
                raise ValueError("every grant must be an object")
            if len({grant.grant_id for grant in grants}) != len(grants):
                raise ValueError("grant identifiers must be unique")
            return grants
        except ProvisioningError:
            raise
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            raise ProvisioningError(
                "feishu_administrator_authorization_unavailable",
                "Feishu 管理员授权暂不可用",
                status=503,
            ) from exc

    def authorize(self, session: AccountSession) -> AuthorizedProvisioningContext:
        if not isinstance(session, AccountSession):
            _fail("feishu_administrator_authorization_forbidden", "当前会话无权确认组织安装", status=403)
        now = self._now().astimezone(UTC)
        if session.expires_at.astimezone(UTC) <= now:
            _fail("feishu_administrator_authorization_forbidden", "当前会话无权确认组织安装", status=403)
        matches = tuple(
            grant
            for grant in self._load_grants()
            if grant.user_id == session.user_id
            and grant.expires_at > now
            and grant.is_tenant_administrator
            and REQUIRED_ADMIN_SCOPE in grant.scopes
        )
        if len(matches) != 1:
            _fail("feishu_administrator_authorization_forbidden", "当前会话无权确认组织安装", status=403)
        grant = matches[0]
        installation = self._current_authority(session, grant, now)
        authorization = TrustedFeishuAdministrator.from_server_adapter(
            grant.tenant_key,
            grant.open_id,
            scopes=grant.scopes,
            expires_at=grant.expires_at,
            is_tenant_administrator=True,
        )
        return AuthorizedProvisioningContext(
            grant_id=grant.grant_id,
            user_id=session.user_id,
            tenant_id=grant.tenant_id,
            installation_id=installation.installation_id,
            installation_public_id=installation.installation_public_id,
            tenant_key=grant.tenant_key,
            organization_name=grant.organization_name,
            credential_ref=grant.credential_ref,
            resource_target=grant.resource_target,
            authorization=authorization,
            session_id=session.session_id,
            session_tenant_id=session.tenant_id,
        )

    def revalidate_grant(self, context: AuthorizedProvisioningContext) -> AuthorizedProvisioningContext:
        """Reload only the server-owned grant facts for confirmation recheck.

        Database authority is rechecked by the confirmation transaction.  This
        method deliberately does not infer anything from browser input and
        does not replace the database row locks.
        """
        if not isinstance(context, AuthorizedProvisioningContext):
            _fail("feishu_administrator_authorization_forbidden", "当前授权无效", status=403)
        now = self._now().astimezone(UTC)
        matches = tuple(
            grant
            for grant in self._load_grants()
            if grant.grant_id == context.grant_id
            and grant.user_id == context.user_id
            and grant.tenant_id == context.tenant_id
            and grant.installation_id == context.installation_id
            and grant.tenant_key == context.tenant_key
            and grant.credential_ref == context.credential_ref
            and grant.organization_name == context.organization_name
            and grant.open_id == context.authorization.open_id
            and frozenset(grant.scopes) == context.authorization.scopes
            and grant.is_tenant_administrator is context.authorization.is_tenant_administrator
            and grant.expires_at == context.authorization.expires_at
            and grant.expires_at > now
            and grant.resource_target == context.resource_target
        )
        if len(matches) != 1:
            _fail("feishu_administrator_authorization_forbidden", "管理员授权已变化", status=403)
        return context

    __call__ = authorize


__all__ = ["AuthorizedProvisioningContext", "Stage1AdministratorAuthorizer"]
