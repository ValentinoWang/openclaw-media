from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
import re
from typing import Any
from urllib.parse import urlparse

from common.feishu_urls import DEFAULT_FEISHU_DOC_HOSTS

from .canonical_resource_contracts import (
    CANONICAL_RESOURCE_CONTRACTS,
    TENANT_PROJECTION_FIELD,
)
from .resource_owner_registry import (
    ResourceOwner,
    ResourceOwnerConflict,
    ResourceOwnerInvalid,
    ResourceOwnerNotFound,
    ResourceOwnerRegistry,
)
from .resource_access import ResourceAccessService, ResourceLink


ProjectionWriter = Callable[[dict[str, Any]], dict[str, Any]]
ProjectionLoader = Callable[[Sequence[str]], Sequence[Mapping[str, Any]]]
ProjectionDeleter = Callable[[], None]


_DOCX_TOKEN = re.compile(r"[A-Za-z0-9_-]{8,160}\Z")
_FEISHU_DOC_HOST_SUFFIXES = tuple(f".{host}" for host in DEFAULT_FEISHU_DOC_HOSTS)
_FEISHU_DOC_ROOT_HOSTS = frozenset(DEFAULT_FEISHU_DOC_HOSTS)


class TenantOwnedResourceContractError(RuntimeError):
    pass


class TenantOwnedResourceService:
    """One owner-first path for private stores and their Feishu projections."""

    def __init__(self, registry: ResourceOwnerRegistry) -> None:
        self.registry = registry
        self.resource_access = ResourceAccessService(registry)

    def register_docx_link(
        self,
        resource_type: str,
        canonical_resource_id: str,
        *,
        session_tenant_id: str | int,
        document_url: str,
        policy: str,
    ) -> ResourceLink:
        """Register a real Docx result only after its canonical owner exists."""
        parsed = urlparse(str(document_url or "").strip())
        host = str(parsed.hostname or "").lower()
        path_parts = [part for part in parsed.path.split("/") if part]
        if (
            parsed.scheme != "https"
            or not (
                host in _FEISHU_DOC_ROOT_HOSTS
                or any(host.endswith(suffix) for suffix in _FEISHU_DOC_HOST_SUFFIXES)
            )
            or len(path_parts) != 2
            or path_parts[0].lower() not in {"docx", "doc", "docs"}
            or _DOCX_TOKEN.fullmatch(path_parts[1]) is None
        ):
            raise ResourceOwnerInvalid("document_url must be a Feishu Docx URL")
        return self.resource_access.put_docx_link(
            resource_type,
            canonical_resource_id,
            session_tenant_id=session_tenant_id,
            docx_token=path_parts[1],
            policy=policy,
        )

    def create_projection(
        self,
        resource_type: str,
        canonical_resource_id: str,
        *,
        session_tenant_id: str | int,
        fields: Mapping[str, Any],
        writer: ProjectionWriter,
    ) -> dict[str, Any]:
        self._reject_owner_input(fields)
        try:
            owner = self.registry.create(
                resource_type,
                canonical_resource_id,
                session_tenant_id=session_tenant_id,
            )
        except ResourceOwnerConflict:
            owner = self.registry.assert_owner(
                resource_type,
                canonical_resource_id,
                session_tenant_id=session_tenant_id,
            )
        if resource_type == "media.creation_run":
            self.registry.upsert_creation_run_summary(
                canonical_resource_id,
                session_tenant_id=owner.tenant_id,
                fields=self._creation_run_summary_fields(fields),
            )
        return writer(self._project(owner, fields))

    def update_projection(
        self,
        resource_type: str,
        canonical_resource_id: str,
        *,
        session_tenant_id: str | int,
        fields: Mapping[str, Any],
        writer: ProjectionWriter,
    ) -> dict[str, Any]:
        self._reject_owner_input(fields)
        owner = self.registry.assert_owner(
            resource_type,
            canonical_resource_id,
            session_tenant_id=session_tenant_id,
        )
        if resource_type == "media.creation_run":
            self.registry.upsert_creation_run_summary(
                canonical_resource_id,
                session_tenant_id=owner.tenant_id,
                fields=self._creation_run_summary_fields(fields),
            )
        return writer(self._project(owner, fields))

    def assert_projection_read(
        self,
        resource_type: str,
        canonical_resource_id: str,
        *,
        session_tenant_id: str | int,
        fields: Mapping[str, Any],
        projection_source: str,
    ) -> Mapping[str, Any]:
        self.registry.assert_owner(
            resource_type,
            canonical_resource_id,
            session_tenant_id=session_tenant_id,
        )
        self.registry.assert_feishu_projection(
            resource_type,
            canonical_resource_id,
            observed_tenant_id=fields.get(TENANT_PROJECTION_FIELD),
            projection_source=projection_source,
        )
        return fields

    def list_projections(
        self,
        resource_type: str,
        *,
        session_tenant_id: str | int,
        loader: ProjectionLoader,
        canonical_id_field: str,
        projection_source: Callable[[Mapping[str, Any]], str],
        include_archived: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Mapping[str, Any]]:
        owners = self.registry.list_by_tenant(
            session_tenant_id,
            resource_type=resource_type,
            include_archived=include_archived,
            limit=limit,
            offset=offset,
        )
        ids = [owner.canonical_resource_id for owner in owners]
        if not ids:
            return []
        allowed_ids = set(ids)
        rows = list(loader(ids))
        result: list[Mapping[str, Any]] = []
        seen: set[str] = set()
        for row in rows:
            resource_id = str(row.get(canonical_id_field) or "").strip()
            if resource_id not in allowed_ids or resource_id in seen:
                raise TenantOwnedResourceContractError(
                    "projection loader returned an unrequested or duplicate resource"
                )
            self.assert_projection_read(
                resource_type,
                resource_id,
                session_tenant_id=session_tenant_id,
                fields=row,
                projection_source=projection_source(row),
            )
            seen.add(resource_id)
            result.append(row)
        if seen != allowed_ids:
            raise TenantOwnedResourceContractError("canonical projection is missing")
        return result

    def archive_after_delete(
        self,
        resource_type: str,
        canonical_resource_id: str,
        *,
        session_tenant_id: str | int,
        deleter: ProjectionDeleter,
    ) -> ResourceOwner:
        self.registry.assert_owner(
            resource_type,
            canonical_resource_id,
            session_tenant_id=session_tenant_id,
        )
        deleter()
        return self.registry.archive(
            resource_type,
            canonical_resource_id,
            session_tenant_id=session_tenant_id,
        )

    def assert_same_tenant_relations(
        self,
        relations: Sequence[tuple[str, str]],
        *,
        session_tenant_id: str | int,
    ) -> tuple[ResourceOwner, ...]:
        if not relations:
            raise ResourceOwnerInvalid("at least one relation endpoint is required")
        return tuple(
            self.registry.assert_owner(
                resource_type,
                resource_id,
                session_tenant_id=session_tenant_id,
            )
            for resource_type, resource_id in relations
        )

    @staticmethod
    def _reject_owner_input(fields: Mapping[str, Any]) -> None:
        if TENANT_PROJECTION_FIELD in fields:
            raise ResourceOwnerInvalid("tenant projection is server-owned")
        forbidden = {"tenant_id", "tenantId", "owner_id", "principal"}
        if forbidden.intersection(fields):
            raise ResourceOwnerInvalid("owner fields are server-owned")

    @staticmethod
    def _project(owner: ResourceOwner, fields: Mapping[str, Any]) -> dict[str, Any]:
        contract = CANONICAL_RESOURCE_CONTRACTS[owner.resource_type]
        if contract.tenant_projection_field != TENANT_PROJECTION_FIELD:
            raise TenantOwnedResourceContractError("resource has no Feishu tenant projection")
        return {**dict(fields), TENANT_PROJECTION_FIELD: owner.tenant_id}

    @staticmethod
    def _creation_run_summary_fields(fields: Mapping[str, Any]) -> dict[str, Any]:
        aliases = {
            "input_summary": ("input_summary", "输入需求摘要", "title", "标题"),
            "status": ("status", "状态", "主状态"),
            "entrypoint": ("entrypoint", "入口标签"),
            "created_at": ("created_at", "创建时间", "入库时间"),
            "updated_at": ("updated_at", "更新时间"),
        }
        return {
            target: next(
                (fields[name] for name in names if fields.get(name) not in (None, "")),
                "",
            )
            for target, names in aliases.items()
        }


def uniform_resource_not_found(exc: Exception) -> ResourceOwnerNotFound:
    if isinstance(exc, ResourceOwnerNotFound):
        return exc
    return ResourceOwnerNotFound("resource not found")
