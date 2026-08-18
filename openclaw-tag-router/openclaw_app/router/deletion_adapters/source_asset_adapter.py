from __future__ import annotations

import json
import re
from typing import Any

from selfmedia.growth import source_asset_public_id

from ..deletion_discovery import DiscoveryResult
from ..deletion_plan import DeletionEntity, DeletionPlan
from .base import DeletionContext, resolve_media_registry_table


PUBLIC_ASSET_ID = re.compile(r"^asset_[A-Za-z0-9_-]{2,154}$")


class SourceAssetDeletionAdapter:
    adapter_id = "source_asset"
    capability_id = "source_asset_intake"
    labels = ("素材",)

    def can_handle(self, discovery: DiscoveryResult) -> bool:
        return bool(PUBLIC_ASSET_ID.fullmatch(discovery.target_id))

    def build_plan(self, discovery: DiscoveryResult, context: DeletionContext) -> DeletionPlan:
        plan = DeletionPlan(
            target_id=discovery.target_id,
            capability_id=self.capability_id,
            capability_label="素材源",
            matched_by=[*discovery.matched_by, "source_asset_public_projection"],
        )
        try:
            _, _, _, owner, matches, projection_exists = self._resolve_state(
                discovery.target_id,
                context,
            )
        except (OSError, ValueError, RuntimeError) as exc:
            plan.blocked = True
            plan.add_entity(
                DeletionEntity(
                    "bitable_record",
                    discovery.target_id,
                    "feishu_bitable_delete_record",
                    "high",
                    "manual_required",
                    f"素材表读取失败：{str(exc)[:160]}",
                )
            )
            return plan
        if owner is None or (not matches and not projection_exists):
            plan.add_entity(
                DeletionEntity(
                    "bitable_record",
                    discovery.target_id,
                    "feishu_bitable_delete_record",
                    "high",
                    "already_absent",
                    "飞书素材源和素材页投影中均已无此记录",
                )
            )
            return plan
        if len(matches) > 1:
            plan.blocked = True
            plan.add_entity(
                DeletionEntity(
                    "bitable_record",
                    discovery.target_id,
                    "feishu_bitable_delete_record",
                    "high",
                    "manual_required",
                    "公开素材引用匹配到多条记录，禁止猜测删除",
                )
            )
            return plan
        title = self._field_text(matches[0].get("fields"), "标题") if matches else ""
        stores = []
        if matches:
            stores.append("飞书素材源")
        if projection_exists:
            stores.append("素材页投影")
        plan.add_entity(
            DeletionEntity(
                "bitable_record",
                discovery.target_id,
                "feishu_bitable_delete_record",
                "high",
                detail=f"{'、'.join(stores)}{f'：{title[:80]}' if title else ''}",
            )
        )
        return plan

    def execute(self, plan: DeletionPlan, context: DeletionContext) -> DeletionPlan:
        plan.mode = "apply"
        results: list[DeletionEntity] = []
        for entity in plan.entities:
            if entity.status in {"manual_required", "already_absent"}:
                results.append(entity)
                continue
            try:
                service, app_token, table_id, owner, matches, projection_exists = self._resolve_state(
                    entity.target,
                    context,
                )
            except (OSError, ValueError, RuntimeError) as exc:
                results.append(self._failed(entity, f"删除前读取失败：{str(exc)[:160]}"))
                continue
            if owner is None or (not matches and not projection_exists):
                results.append(DeletionEntity(entity.kind, entity.target, entity.operation, entity.risk, "already_absent", entity.detail))
                continue
            if len(matches) > 1:
                results.append(self._failed(entity, "删除前匹配数量不再唯一，已阻断"))
                continue
            record_id = str(matches[0].get("record_id") or "").strip() if matches else ""
            if matches and (
                not record_id
                or not hasattr(service, "delete_bitable_record")
                or not hasattr(service, "read_bitable_record")
            ):
                results.append(self._failed(entity, "缺少唯一飞书记录或删除服务"))
                continue
            try:
                def delete_projection() -> None:
                    if matches:
                        try:
                            service.delete_bitable_record(app_token, table_id, record_id)
                        except Exception as exc:
                            if not self._is_absent_error(exc):
                                raise
                        try:
                            readback = service.read_bitable_record(app_token, table_id, record_id)
                        except Exception as exc:
                            if not self._is_absent_error(exc):
                                raise
                        else:
                            if readback:
                                raise RuntimeError("飞书素材删除 API 返回成功，但读回仍找到记录")
                    if projection_exists:
                        context.source_asset_projection.delete(
                            context.tenant_id,
                            owner.canonical_resource_id,
                        )
                    if context.source_asset_projection.exists(
                        context.tenant_id,
                        owner.canonical_resource_id,
                    ):
                        raise RuntimeError("PostgreSQL 素材投影删除后读回仍存在")

                if owner.status == "active":
                    context.tenant_owned_resources.archive_after_delete(
                        "media.source_asset",
                        owner.canonical_resource_id,
                        session_tenant_id=context.tenant_id,
                        deleter=delete_projection,
                    )
                elif owner.status == "archived":
                    delete_projection()
                else:
                    raise RuntimeError("canonical 素材 owner 状态无效")
                results.append(DeletionEntity(entity.kind, entity.target, entity.operation, entity.risk, "deleted", f"{entity.detail}；飞书与素材页投影读回均已不存在"))
            except Exception as exc:
                results.append(self._failed(entity, str(exc)[:300]))
        plan.entities = results
        plan.blocked = any(entity.status in {"failed", "manual_required"} for entity in results)
        return plan

    @staticmethod
    def _failed(entity: DeletionEntity, detail: str) -> DeletionEntity:
        return DeletionEntity(entity.kind, entity.target, entity.operation, entity.risk, "failed", detail)

    @staticmethod
    def _is_absent_error(exc: Exception) -> bool:
        text = str(exc).lower()
        return "not found" in text or "status=404" in text or "code=1254043" in text

    def _resolve_state(
        self,
        public_id: str,
        context: DeletionContext,
    ) -> tuple[Any, str, str, Any | None, list[dict[str, Any]], bool]:
        service = context.media_feishu_service or context.feishu_service
        if service is None or not hasattr(service, "list_bitable_records"):
            raise RuntimeError("未配置飞书多维表格记录读取服务")
        owner_service = context.tenant_owned_resources
        if owner_service is None or not context.tenant_id:
            raise RuntimeError("未配置 canonical resource owner 服务")
        projection = context.source_asset_projection
        if (
            projection is None
            or not hasattr(projection, "exists")
            or not hasattr(projection, "delete")
        ):
            raise RuntimeError("未配置 PostgreSQL 素材投影删除服务")
        registry = json.loads(context.media_registry_path.read_text(encoding="utf-8"))
        entry = resolve_media_registry_table(
            registry,
            legacy_key="source_assets",
            table_key="source_asset",
        )
        app_token = entry["app_token"]
        table_id = entry["table_id"]
        owners = [
            owner
            for owner in self._tenant_owners(
                owner_service,
                context.tenant_id,
                "media.source_asset",
                include_archived=True,
            )
            if public_id in {owner.canonical_resource_id, source_asset_public_id(owner.canonical_resource_id)}
        ]
        if not owners:
            return service, app_token, table_id, None, [], False
        if len(owners) != 1:
            raise RuntimeError("canonical 素材公开引用不唯一")
        owner = owners[0]
        source_asset_id = owner.canonical_resource_id
        records = service.list_bitable_records(
            app_token,
            table_id,
            page_size=2,
            filter_formula=f'CurrentValue.[素材ID] = {json.dumps(source_asset_id, ensure_ascii=False)}',
        )
        matches = [
            record
            for record in records
            if self._field_text(record.get("fields") if isinstance(record, dict) else {}, "素材ID") == source_asset_id
        ]
        for record in matches:
            owner_service.registry.assert_feishu_projection(
                "media.source_asset",
                source_asset_id,
                observed_tenant_id=(record.get("fields") or {}).get("租户ID"),
                projection_source=f"feishu:{table_id}/{record.get('record_id') or 'missing'}",
            )
        projection_exists = bool(projection.exists(context.tenant_id, source_asset_id))
        return service, app_token, table_id, owner, matches, projection_exists

    @staticmethod
    def _tenant_owners(
        owner_service: Any,
        tenant_id: str,
        resource_type: str,
        *,
        include_archived: bool = False,
    ) -> list[Any]:
        return owner_service.registry.list_all_by_tenant(
            tenant_id,
            resource_type=resource_type,
            include_archived=include_archived,
        )

    @staticmethod
    def _field_text(fields: Any, name: str) -> str:
        if not isinstance(fields, dict):
            return ""
        value = fields.get(name)
        if isinstance(value, list):
            return "".join(SourceAssetDeletionAdapter._field_text({name: item}, name) for item in value).strip()
        if isinstance(value, dict):
            return str(value.get("text") or value.get("name") or value.get("value") or "").strip()
        return str(value or "").strip()
