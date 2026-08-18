"""HTTP-facing composition for Stage 1 organization provisioning."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable, Mapping
from uuid import UUID

from ..account.auth import AccountSession
from .stage1_feishu_provisioning_gateway import FeishuCredentialRevocationGateway
from .stage1_administrator_authorization import (
    AuthorizedProvisioningContext,
    Stage1AdministratorAuthorizer,
)
from .stage1_member_onboarding import ServerFeishuInstallContext
from .stage1_organization_provisioning import (
    AdministratorConfirmationService,
    OrganizationDeprovisionService,
    OrganizationResourceInitializer,
    ProvisionOrchestrator,
    ProvisionStatusService,
    ProvisioningError,
    ResourceTarget,
    ResourceBindingContext,
    TrustedProvisionActor,
)
from .stage1_postgres_provisioning import Stage1PostgresRepository
from .stage1_provision_models import Stage1LifecycleState


class Stage1ProvisioningRuntime:
    """Composes the durable repository and the external Feishu gateway.

    ``administrator_authorizer`` is intentionally injected. The HTTP layer
    never accepts browser-supplied identity, installation, role, or credential
    selectors.
    """

    def __init__(
        self,
        connection_factory: Callable[[], Any],
        gateway: Any,
        *,
        credential_gateway: Any | None = None,
        administrator_authorizer: Callable[[AccountSession], AuthorizedProvisioningContext] | None = None,
        resource_target_resolver: Callable[[ResourceBindingContext], ResourceTarget | None] | None = None,
    ) -> None:
        self._connection_factory = connection_factory
        self._gateway = gateway
        self._credential_gateway = credential_gateway or FeishuCredentialRevocationGateway()
        self._administrator_authorizer = administrator_authorizer
        self._resource_target_resolver = resource_target_resolver

    def _repository(self, session_id: UUID | None = None) -> Stage1PostgresRepository:
        return Stage1PostgresRepository(self._connection_factory, actor_session_id=session_id)

    def actor_for_session(self, session: AccountSession) -> TrustedProvisionActor:
        if (
            session.workspace_mode != "organization_lark"
            or session.body_authority != "lark"
            or session.member_role != "owner"
        ):
            raise ProvisioningError("provision_owner_required", "当前组织负责人身份无效", status=403)
        repository = self._repository(session.session_id)
        with repository.transaction() as store:
            installations = store.owner_installations(session.user_id, session.tenant_id)
        if not installations:
            raise ProvisioningError("provision_installation_missing", "当前租户没有可用的组织安装", status=404)
        if len(installations) != 1:
            raise ProvisioningError("provision_installation_ambiguous", "当前租户的组织安装不唯一", status=409)
        installation = installations[0]
        return TrustedProvisionActor.from_server_authorization(
            session.user_id,
            session.tenant_id,
            "owner",
            installation.installation_id,
        )

    def confirm_for_session(self, session: AccountSession, *, idempotency_key: str) -> Any:
        if self._administrator_authorizer is None:
            raise ProvisioningError("feishu_administrator_authorization_unavailable", "Feishu 管理员授权暂不可用", status=503)
        authorized = self._administrator_authorizer(session)
        if (
            authorized.user_id != session.user_id
            or authorized.session_id != session.session_id
            or authorized.session_tenant_id != session.tenant_id
        ):
            raise ProvisioningError("feishu_administrator_authorization_forbidden", "当前会话无权确认组织安装", status=403)
        repository = self._repository(session.session_id)
        context = ServerFeishuInstallContext.from_server_adapter(
            authorized.tenant_key,
            authorized.installation_public_id,
        )
        return AdministratorConfirmationService(repository).confirm(
            tenant_id=authorized.tenant_id,
            owner_user_id=session.user_id,
            installation_id=authorized.installation_id,
            install_context=context,
            authorization=authorized.authorization,
            idempotency_key=idempotency_key,
            credential_ref=authorized.credential_ref,
            organization_name=authorized.organization_name,
            session_id=session.session_id,
            session_tenant_id=session.tenant_id,
            authorization_revalidator=(
                lambda: self._administrator_authorizer.revalidate_grant(authorized)
                if callable(getattr(self._administrator_authorizer, "revalidate_grant", None))
                else authorized
            ),
        )

    def start_for_session(self, session: AccountSession, *, idempotency_key: str) -> Any:
        actor = self.actor_for_session(session)
        repository = self._repository(session.session_id)
        with repository.transaction() as store:
            binding = store.binding_context_for_actor(actor)
        if binding is None:
            raise ProvisioningError("provision_binding_missing", "组织绑定尚未确认", status=409)
        tenant_id, binding_id, generation, tenant_key, credential_ref = binding
        base_context = ResourceBindingContext(
            actor.installation_id,
            tenant_id,
            binding_id,
            generation,
            tenant_key,
            credential_ref,
            Stage1LifecycleState.NEEDS_ATTENTION,
        )
        target_resolver = self._resource_target_resolver
        if target_resolver is None:
            target_resolver = getattr(self._administrator_authorizer, "resource_target_for_context", None)
        if not callable(target_resolver):
            raise ProvisioningError(
                "provision_target_unavailable",
                "组织资源目标尚未配置",
                status=503,
            )
        try:
            target = target_resolver(base_context)
        except ProvisioningError:
            raise
        except Exception as exc:
            raise ProvisioningError(
                "provision_target_unavailable",
                "组织资源目标尚未配置",
                status=503,
            ) from exc
        if not isinstance(target, ResourceTarget):
            raise ProvisioningError(
                "provision_target_unavailable",
                "组织资源目标尚未配置",
                status=503,
            )
        context = ResourceBindingContext(
            base_context.installation_id,
            base_context.tenant_id,
            base_context.binding_id,
            base_context.binding_generation,
            base_context.tenant_key,
            base_context.credential_ref,
            base_context.state,
            target.space_id,
            target.parent_node_token,
            target,
        )
        initializer = OrganizationResourceInitializer(repository, self._gateway)
        # The initializer is idempotent across all three resources, while the
        # orchestrator keeps one checkpoint per externally visible step.  This
        # lets a retry skip durable successes even when a later resource failed.
        steps = {
            resource_kind: lambda run_id, step_key, kind=resource_kind: initializer.initialize(
                context, provision_run_id=run_id, idempotency_key=step_key, kinds=(kind,)
            )
            for resource_kind in ("wiki", "parent_node", "app_directory")
        }
        return ProvisionOrchestrator(repository, steps=steps).run(
            actor,
            idempotency_key=idempotency_key,
            lease_owner=f"http:{session.session_id}",
        )

    def status_for_session(self, session: AccountSession, provision_run_id: UUID) -> Any:
        actor = self.actor_for_session(session)
        return ProvisionStatusService(self._repository(session.session_id)).status(actor, provision_run_id)

    def deprovision_for_session(self, session: AccountSession, *, idempotency_key: str, revoke: bool) -> Any:
        actor = self.actor_for_session(session)
        return OrganizationDeprovisionService(
            self._repository(session.session_id), self._credential_gateway
        ).deprovision(actor, idempotency_key=idempotency_key, revoke=revoke)


def build_stage1_provisioning_runtime(
    connection_factory: Callable[[], Any],
    gateway: Any,
    *,
    administrator_grants_file: str | Path | None,
    administrator_authorizer: Any | None = None,
    resource_target_resolver: Callable[[ResourceBindingContext], ResourceTarget | None] | None = None,
) -> Stage1ProvisioningRuntime:
    """Compose the fail-closed control plane from server-owned inputs."""

    authorizer = administrator_authorizer or Stage1AdministratorAuthorizer(
        connection_factory,
        administrator_grants_file,
    )
    return Stage1ProvisioningRuntime(
        connection_factory,
        gateway,
        administrator_authorizer=authorizer,
        resource_target_resolver=resource_target_resolver,
    )


def provision_run_json(value: Any) -> dict[str, Any]:
    return {
        "provisionRunId": str(value.provision_run_id),
        "installationId": str(value.installation_id),
        "tenantId": str(value.tenant_id),
        "idempotencyKey": value.idempotency_key,
        "status": value.status.value,
        "state": value.state.value,
        "failedStep": value.failed_step,
        "retryAfter": value.retry_after.isoformat() if value.retry_after else None,
    }


def provision_status_json(value: Any) -> dict[str, Any]:
    return {
        "provisionRunId": str(value.provision_run_id),
        "installationId": str(value.installation_id),
        "tenantId": str(value.tenant_id),
        "status": value.status.value,
        "state": value.state.value,
        "completedSteps": list(value.completed_steps),
        "failedStep": value.failed_step,
        "retryAvailable": value.retry_available,
        "retryAfter": value.retry_after.isoformat() if value.retry_after else None,
    }


def deprovision_json(value: Any) -> dict[str, Any]:
    return {
        "receiptId": str(value.receipt_id),
        "installationId": str(value.installation_id),
        "tenantId": str(value.tenant_id),
        "state": value.state.value,
        "idempotencyKey": value.idempotency_key,
        "revokedSessionCount": value.revoked_session_count,
        "revokedAt": value.revoked_at.isoformat(),
        "externalCredentialRevoked": value.external_credential_revoked,
    }


__all__ = [
    "Stage1ProvisioningRuntime",
    "build_stage1_provisioning_runtime",
    "deprovision_json",
    "provision_run_json",
    "provision_status_json",
]
