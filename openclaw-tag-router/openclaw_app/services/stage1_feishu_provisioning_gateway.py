"""Idempotent Feishu resource gateway for Stage 1 provisioning.

The gateway deliberately exposes only discovery, creation and read-back.  It
does not write document bodies; that authority remains a later-stage writer.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from .stage1_organization_provisioning import ExternalResource, ResourceBindingContext, ResourceTarget


UTC = timezone.utc


class FeishuProvisioningError(RuntimeError):
    """An external error that can be retried by the provision orchestrator."""


class Stage1FeishuProvisioningGateway:
    def __init__(
        self,
        feishu_service: Any | None = None,
        *,
        target_resolver: Callable[[ResourceBindingContext], ResourceTarget | None] | None = None,
        credential_client_resolver: Callable[[ResourceBindingContext], Any | None] | None = None,
        app_directory_title: str = "MediaClaw",
    ) -> None:
        # ``feishu_service`` is retained only for constructor compatibility. A
        # global client is never used for a Stage 1 external operation.
        self._legacy_service = feishu_service
        self._target_resolver = target_resolver
        self._credential_client_resolver = credential_client_resolver
        self._app_directory_title = app_directory_title.strip() or "MediaClaw"

    def _target(self, context: ResourceBindingContext) -> ResourceTarget:
        if self._target_resolver is None:
            raise FeishuProvisioningError("Feishu resource target is not configured")
        target = self._target_resolver(context)
        if not isinstance(target, ResourceTarget):
            raise FeishuProvisioningError("Feishu resource target is not binding-scoped")
        if target != context.resource_target:
            raise FeishuProvisioningError("Feishu resource target changed")
        if (
            target.installation_id != context.installation_id
            or target.tenant_id != context.tenant_id
            or target.tenant_key != context.tenant_key
            or target.binding_id != context.binding_id
            or target.binding_generation != context.binding_generation
            or target.space_id != context.space_id
            or target.parent_node_token != context.parent_node_token
        ):
            raise FeishuProvisioningError("Feishu resource target is not binding-scoped")
        if not target.space_id or not target.parent_node_token:
            raise FeishuProvisioningError("Feishu wiki space and parent node are required")
        return target

    def _client(self, context: ResourceBindingContext) -> Any:
        if self._credential_client_resolver is None:
            raise FeishuProvisioningError("Feishu credential client is not configured")
        try:
            client = self._credential_client_resolver(context)
        except Exception as exc:
            raise FeishuProvisioningError("Feishu credential client is unavailable") from exc
        if client is None:
            raise FeishuProvisioningError("Feishu credential client is unavailable")
        return client

    @staticmethod
    def _resource(context: ResourceBindingContext, kind: str, external_id: str, url: str) -> ExternalResource:
        if not external_id or not url.startswith("https://"):
            raise FeishuProvisioningError(f"Feishu {kind} readback is incomplete")
        return ExternalResource(kind, external_id, url, context.installation_id, context.binding_id, context.binding_generation)

    def discover(self, context: ResourceBindingContext, kind: str):
        target = self._target(context)
        client = self._client(context)
        parent = target.parent_node_token
        try:
            if kind == "wiki":
                metadata = client.resolve_wiki_node_metadata(parent)
                node = str(metadata.get("node_token") or parent)
                return (self._resource(context, kind, node, f"{client.web_base_url}/wiki/{node}"),)
            children = client.list_knowledge_resource_nodes(parent)
            matches = []
            for item in children:
                if not isinstance(item, Mapping):
                    continue
                title = str(item.get("title") or item.get("name") or "").strip()
                if kind == "parent_node" and title == self._app_directory_title:
                    token = str(item.get("node_token") or "").strip()
                    if token:
                        matches.append(self._resource(context, kind, token, f"{client.web_base_url}/wiki/{token}"))
                elif kind == "app_directory" and title == self._app_directory_title:
                    token = str(item.get("obj_token") or item.get("document_id") or item.get("node_token") or "").strip()
                    node = str(item.get("node_token") or token)
                    if token:
                        matches.append(self._resource(context, kind, token, f"{client.web_base_url}/wiki/{node}"))
            return tuple(matches)
        except Exception as exc:
            if isinstance(exc, FeishuProvisioningError):
                raise
            raise FeishuProvisioningError(f"Feishu {kind} discovery failed") from exc

    def create(self, context: ResourceBindingContext, kind: str, idempotency_key: str) -> ExternalResource:
        target = self._target(context)
        client = self._client(context)
        _space_id, parent = target.space_id, target.parent_node_token
        if kind == "wiki":
            raise FeishuProvisioningError("the configured wiki root must be discovered, not created")
        try:
            # Feishu has no universal idempotency header for Wiki node create;
            # the service layer supplies the key to the durable step receipt and
            # discovery-before-create prevents duplicate nodes after retries.
            get_or_create = getattr(client, "_get_or_create_document", None)
            if callable(get_or_create):
                document_id, _document_url = get_or_create(f"{self._app_directory_title}-{idempotency_key}")
            else:
                document_id = f"stage1-{idempotency_key}"
            _node_token, _obj_token, node_url = client._create_knowledge_node(
                self._app_directory_title,
                document_id,
                _space_id,
                parent,
            )
            node_token = node_url.rsplit("/", 1)[-1] if node_url else _node_token
            if kind == "parent_node":
                return self._resource(context, kind, node_token, f"{client.web_base_url}/wiki/{node_token}")
            return self._resource(context, kind, document_id, f"{client.web_base_url}/wiki/{node_token}")
        except Exception as exc:
            if isinstance(exc, FeishuProvisioningError):
                raise
            raise FeishuProvisioningError(f"Feishu {kind} creation failed") from exc

    def readback(self, context: ResourceBindingContext, external_id: str) -> ExternalResource | None:
        target = self._target(context)
        client = self._client(context)
        parent = target.parent_node_token
        try:
            if external_id == parent:
                return self._resource(context, "wiki", external_id, f"{client.web_base_url}/wiki/{external_id}")
            children = client.list_knowledge_resource_nodes(parent)
            for item in children:
                if not isinstance(item, Mapping):
                    continue
                node = str(item.get("node_token") or "").strip()
                obj = str(item.get("obj_token") or item.get("document_id") or "").strip()
                if external_id not in {node, obj}:
                    continue
                kind = "parent_node" if node == external_id else "app_directory"
                return self._resource(context, kind, external_id, f"{client.web_base_url}/wiki/{node or external_id}")
            return None
        except Exception as exc:
            if isinstance(exc, FeishuProvisioningError):
                raise
            raise FeishuProvisioningError("Feishu resource readback failed") from exc


class FeishuCredentialRevocationGateway:
    """Best-effort external credential revocation hook.

    Credential material is held outside the product database.  Deployments can
    supply a callable; the default is deliberately false and therefore leaves
    the durable local revocation in place for a later retry.
    """

    def __init__(self, revoke_callback: Callable[[Any, str], bool] | None = None) -> None:
        self._revoke_callback = revoke_callback

    def revoke(self, installation_id: Any, idempotency_key: str) -> bool:
        if self._revoke_callback is None:
            return False
        return bool(self._revoke_callback(installation_id, idempotency_key))


__all__ = ["FeishuCredentialRevocationGateway", "FeishuProvisioningError", "Stage1FeishuProvisioningGateway"]
