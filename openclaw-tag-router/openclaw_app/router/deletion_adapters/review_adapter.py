from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from selfmedia.growth import review_public_id

from ..deletion_discovery import DiscoveryResult
from ..deletion_plan import DeletionEntity, DeletionPlan
from .base import DeletionContext, resolve_media_registry_table


PUBLIC_REVIEW_ID = re.compile(r"^review_[a-f0-9]{16}$")
MODEL_CONTRACT_PATH = Path("/home/ubuntu/docs/ai-harness/media-model-v2-contract.json")


class ReviewDeletionAdapter:
    adapter_id = "published_post_review"
    capability_id = "selfmedia_data_review"
    labels = ("数据复盘",)

    def can_handle(self, discovery: DiscoveryResult) -> bool:
        return bool(PUBLIC_REVIEW_ID.fullmatch(discovery.target_id))

    def build_plan(self, discovery: DiscoveryResult, context: DeletionContext) -> DeletionPlan:
        plan = DeletionPlan(
            target_id=discovery.target_id,
            capability_id=self.capability_id,
            capability_label="数据复盘",
            matched_by=[*discovery.matched_by, "review_public_projection"],
        )
        try:
            resolution = self._resolve(discovery.target_id, context)
        except (OSError, ValueError, RuntimeError) as exc:
            plan.blocked = True
            plan.add_entity(self._entity(discovery.target_id, "manual_required", f"复盘来源读取失败：{str(exc)[:160]}"))
            return plan
        reviews = resolution["reviews"]
        if not reviews:
            plan.add_entity(self._entity(discovery.target_id, "already_absent", "发布复盘及关联指标已不存在"))
            return plan
        if len(reviews) != 1:
            plan.blocked = True
            plan.add_entity(self._entity(discovery.target_id, "manual_required", "公开复盘引用匹配到多条主记录，禁止猜测删除"))
            return plan
        fields = reviews[0].get("fields") or {}
        platform = self._field_text(fields, resolution["post_fields"]["platform"])
        review_node = self._field_text(fields, resolution["post_fields"]["review_node"])
        metric_count = len(resolution["metrics"])
        label = " / ".join(item for item in (platform, review_node) if item)
        detail = f"04_PostReviews_发布复盘{f'：{label}' if label else ''}；级联 {metric_count} 条 H01 指标快照"
        plan.add_entity(self._entity(discovery.target_id, "planned", detail))
        return plan

    def execute(self, plan: DeletionPlan, context: DeletionContext) -> DeletionPlan:
        plan.mode = "apply"
        entity = plan.entities[0] if plan.entities else self._entity(plan.target_id, "failed", "删除计划为空")
        if entity.status in {"manual_required", "already_absent"}:
            plan.blocked = entity.status == "manual_required"
            return plan
        try:
            resolution = self._resolve(plan.target_id, context)
        except (OSError, ValueError, RuntimeError) as exc:
            plan.entities = [self._entity(plan.target_id, "failed", f"删除前读取失败：{str(exc)[:160]}")]
            plan.blocked = True
            return plan
        reviews = resolution["reviews"]
        if not reviews:
            plan.entities = [self._entity(plan.target_id, "already_absent", "发布复盘及关联指标已不存在")]
            return plan
        if len(reviews) != 1:
            plan.entities = [self._entity(plan.target_id, "failed", "删除前主记录匹配数量不再唯一，已阻断")]
            plan.blocked = True
            return plan
        service = context.feishu_service
        if service is None or not hasattr(service, "delete_bitable_record") or not hasattr(service, "read_bitable_record"):
            plan.entities = [self._entity(plan.target_id, "failed", "缺少飞书删除或回读服务")]
            plan.blocked = True
            return plan

        deleted_metrics = 0
        for metric in resolution["metrics"]:
            record_id = str(metric.get("record_id") or "").strip()
            metric_id = self._field_text(metric.get("fields") or {}, resolution["metric_fields"]["snapshot_id"])
            if not record_id:
                plan.entities = [self._entity(plan.target_id, "failed", "关联指标缺少唯一飞书记录 ID，主记录已保留")]
                plan.blocked = True
                return plan
            error = self._archive_delete(
                context,
                resource_type="media.metric_snapshot",
                resource_id=metric_id,
                app_token=resolution["app_token"],
                table_id=resolution["metric_table_id"],
                record_id=record_id,
            )
            if error:
                plan.entities = [self._entity(plan.target_id, "failed", f"已删除 {deleted_metrics} 条指标；关联指标删除失败，主记录已保留：{error}")]
                plan.blocked = True
                return plan
            deleted_metrics += 1

        remaining = self._matching_metrics(resolution["post_id"], context, resolution)
        if remaining:
            plan.entities = [self._entity(plan.target_id, "failed", "指标删除回读仍有记录，主记录已保留")]
            plan.blocked = True
            return plan

        review_record_id = str(reviews[0].get("record_id") or "").strip()
        if not review_record_id:
            plan.entities = [self._entity(plan.target_id, "failed", "复盘主记录缺少唯一飞书记录 ID")]
            plan.blocked = True
            return plan
        error = self._archive_delete(
            context,
            resource_type="media.post_review",
            resource_id=resolution["post_id"],
            app_token=resolution["app_token"],
            table_id=resolution["post_table_id"],
            record_id=review_record_id,
        )
        if error:
            plan.entities = [self._entity(plan.target_id, "failed", f"已删除 {deleted_metrics} 条指标；复盘主记录删除失败：{error}")]
            plan.blocked = True
            return plan
        plan.entities = [self._entity(plan.target_id, "deleted", f"已删除复盘主记录和 {deleted_metrics} 条关联指标；飞书回读均不存在")]
        plan.blocked = False
        return plan

    @staticmethod
    def _entity(target: str, status: str, detail: str) -> DeletionEntity:
        return DeletionEntity("bitable_record", target, "feishu_bitable_cascade_delete", "high", status, detail)

    def _resolve(self, public_id: str, context: DeletionContext) -> dict[str, Any]:
        service = context.feishu_service
        if service is None or not hasattr(service, "list_bitable_records"):
            raise RuntimeError("未配置飞书多维表格记录读取服务")
        owner_service = context.tenant_owned_resources
        if owner_service is None or not context.tenant_id:
            raise RuntimeError("未配置 canonical resource owner 服务")
        registry = json.loads(context.media_registry_path.read_text(encoding="utf-8"))
        post_entry = resolve_media_registry_table(
            registry,
            legacy_key="post_reviews",
            table_key="post_review",
        )
        metric_entry = resolve_media_registry_table(
            registry,
            legacy_key="metric_snapshot",
            table_key="post_metric_snapshot",
        )
        if post_entry["app_token"] != metric_entry["app_token"]:
            raise ValueError("复盘主表与指标表不属于同一 canonical Media OS app")
        contract = json.loads(MODEL_CONTRACT_PATH.read_text(encoding="utf-8"))
        post_fields = self._field_map(contract, "PublishedPost")
        metric_fields = self._field_map(contract, "MetricSnapshot")
        post_ids = [
            owner.canonical_resource_id
            for owner in self._tenant_owners(owner_service, context.tenant_id, "media.post_review")
            if review_public_id(owner.canonical_resource_id) == public_id
        ]
        if len(post_ids) > 1:
            raise RuntimeError("canonical 复盘公开引用不唯一")
        post_id = post_ids[0] if post_ids else ""
        records = [] if not post_id else service.list_bitable_records(
            post_entry["app_token"],
            post_entry["table_id"],
            page_size=2,
            filter_formula=(
                f'CurrentValue.[{post_fields["post_id"]}] = '
                f'{json.dumps(post_id, ensure_ascii=False)}'
            ),
        )
        reviews = [
            record
            for record in records
            if self._field_text(record.get("fields") if isinstance(record, dict) else {}, post_fields["post_id"]) == post_id
        ]
        for record in reviews:
            owner_service.assert_projection_read(
                "media.post_review",
                post_id,
                session_tenant_id=context.tenant_id,
                fields=record.get("fields") or {},
                projection_source=f"feishu:{post_entry['table_id']}/{record.get('record_id') or 'missing'}",
            )
        resolution = {
            "app_token": post_entry["app_token"],
            "post_table_id": post_entry["table_id"],
            "metric_table_id": metric_entry["table_id"],
            "post_fields": post_fields,
            "metric_fields": metric_fields,
            "reviews": reviews,
            "post_id": post_id,
            "metrics": [],
        }
        if post_id:
            resolution["metrics"] = self._matching_metrics(post_id, context, resolution)
        return resolution

    def _matching_metrics(self, post_id: str, context: DeletionContext, resolution: dict[str, Any]) -> list[dict[str, Any]]:
        service = context.feishu_service
        owner_service = context.tenant_owned_resources
        post_field = resolution["metric_fields"]["post_id"]
        records = service.list_bitable_records(
            resolution["app_token"],
            resolution["metric_table_id"],
            page_size=100,
            filter_formula=(
                f'CurrentValue.[{post_field}] = {json.dumps(post_id, ensure_ascii=False)}'
            ),
        )
        matches = [
            record
            for record in records
            if self._field_text(record.get("fields") if isinstance(record, dict) else {}, post_field) == post_id
        ]
        relations = [("media.post_review", post_id)]
        snapshot_field = resolution["metric_fields"]["snapshot_id"]
        for record in matches:
            snapshot_id = self._field_text(record.get("fields") or {}, snapshot_field)
            if not snapshot_id:
                raise RuntimeError("MetricSnapshot projection is missing canonical snapshot_id")
            owner_service.assert_projection_read(
                "media.metric_snapshot",
                snapshot_id,
                session_tenant_id=context.tenant_id,
                fields=record.get("fields") or {},
                projection_source=f"feishu:{resolution['metric_table_id']}/{record.get('record_id') or 'missing'}",
            )
            relations.append(("media.metric_snapshot", snapshot_id))
        owner_service.assert_same_tenant_relations(
            relations,
            session_tenant_id=context.tenant_id,
        )
        return matches

    @staticmethod
    def _tenant_owners(owner_service: Any, tenant_id: str, resource_type: str) -> list[Any]:
        return owner_service.registry.list_all_by_tenant(
            tenant_id,
            resource_type=resource_type,
        )

    @staticmethod
    def _field_map(contract: dict[str, Any], entity: str) -> dict[str, str]:
        matches = [
            item.get("field_name_map")
            for item in (contract.get("projection_contracts") or {}).values()
            if isinstance(item, dict) and item.get("entity") == entity
        ]
        if len(matches) != 1 or not isinstance(matches[0], dict):
            raise ValueError(f"{entity} canonical field map is missing or ambiguous")
        return {str(key): str(value) for key, value in matches[0].items()}

    @classmethod
    def _field_text(cls, fields: Any, name: str) -> str:
        if not isinstance(fields, dict):
            return ""
        value = fields.get(name)
        if isinstance(value, list):
            return "".join(cls._field_text({name: item}, name) for item in value).strip()
        if isinstance(value, dict):
            return str(value.get("text") or value.get("name") or value.get("value") or "").strip()
        return str(value or "").strip()

    @classmethod
    def _delete_and_readback(cls, service: Any, app_token: str, table_id: str, record_id: str) -> str:
        try:
            service.delete_bitable_record(app_token, table_id, record_id)
            record = service.read_bitable_record(app_token, table_id, record_id)
            return "删除 API 返回成功，但读回仍找到记录" if record else ""
        except Exception as exc:
            if cls._is_absent_error(exc):
                return ""
            return str(exc)[:240]

    @classmethod
    def _archive_delete(
        cls,
        context: DeletionContext,
        *,
        resource_type: str,
        resource_id: str,
        app_token: str,
        table_id: str,
        record_id: str,
    ) -> str:
        if not resource_id:
            return "canonical resource id is missing"
        try:
            def delete_projection() -> None:
                error = cls._delete_and_readback(
                    context.feishu_service,
                    app_token,
                    table_id,
                    record_id,
                )
                if error:
                    raise RuntimeError(error)

            context.tenant_owned_resources.archive_after_delete(
                resource_type,
                resource_id,
                session_tenant_id=context.tenant_id,
                deleter=delete_projection,
            )
            return ""
        except Exception as exc:
            return str(exc)[:240]

    @staticmethod
    def _is_absent_error(exc: Exception) -> bool:
        text = str(exc).lower()
        return "not found" in text or "status=404" in text or "code=1254043" in text
