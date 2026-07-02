from __future__ import annotations

import re
import urllib.parse
from typing import Any

from ..deletion_discovery import DiscoveryResult
from ..deletion_plan import DeletionEntity, DeletionPlan
from .base import DeletionContext


RECORD_KEYS = ("record_id", "feishu_record_id", "creation_record_id", "bitable_record_id")
TABLE_KEYS = ("table_url", "bitable_url", "feishu_table_url")


class BitableRecordDeletionAdapter:
    adapter_id = "bitable_record"
    capability_id = "bitable_record"
    labels: tuple[str, ...] = ()

    def can_handle(self, discovery: DiscoveryResult) -> bool:
        if re.fullmatch(r"rec[A-Za-z0-9_-]+", discovery.target_id):
            return True
        for candidate in discovery.archive_candidates:
            if self._record_ids(candidate.frontmatter) and self._table_ref(candidate.frontmatter):
                return True
        return False

    def build_plan(self, discovery: DiscoveryResult, context: DeletionContext) -> DeletionPlan:
        plan = DeletionPlan(
            target_id=discovery.target_id,
            capability_id=self.capability_id,
            capability_label="多维表格记录",
            matched_by=list(discovery.matched_by),
        )
        found = False
        for candidate in discovery.archive_candidates:
            table = self._table_ref(candidate.frontmatter)
            for record_id in self._record_ids(candidate.frontmatter):
                found = True
                if not table:
                    plan.add_entity(DeletionEntity("bitable_record", record_id, "feishu_bitable_delete_record", "high", "manual_required", "缺少唯一 app_token/table_id"))
                    continue
                detail = self._record_detail(context, table, record_id)
                plan.add_entity(DeletionEntity("bitable_record", f"{table['app_token']}/{table['table_id']}/{record_id}", "feishu_bitable_delete_record", "high", detail=detail))
        if not found and re.fullmatch(r"rec[A-Za-z0-9_-]+", discovery.target_id):
            plan.add_entity(DeletionEntity("bitable_record", discovery.target_id, "feishu_bitable_delete_record", "high", "manual_required", "直接输入 record_id 时缺少唯一表归属，不能跨表猜删"))
        return plan

    def execute(self, plan: DeletionPlan, context: DeletionContext) -> DeletionPlan:
        plan.mode = "apply"
        results: list[DeletionEntity] = []
        for entity in plan.entities:
            if entity.status == "manual_required":
                results.append(entity)
                continue
            parsed = self._parse_target(entity.target)
            if not parsed:
                results.append(DeletionEntity(entity.kind, entity.target, entity.operation, entity.risk, "failed", "invalid bitable target"))
                continue
            service = context.feishu_service
            if service is None or not hasattr(service, "delete_bitable_record"):
                results.append(DeletionEntity(entity.kind, entity.target, entity.operation, entity.risk, "failed", "missing feishu bitable delete service"))
                continue
            try:
                service.delete_bitable_record(parsed["app_token"], parsed["table_id"], parsed["record_id"])
                status = "deleted"
                detail = entity.detail
                try:
                    record = service.read_bitable_record(parsed["app_token"], parsed["table_id"], parsed["record_id"])
                    if record:
                        status = "failed"
                        detail = "delete API returned but readback still found record"
                except Exception as exc:
                    detail = f"readback absent: {str(exc)[:160]}"
                results.append(DeletionEntity(entity.kind, entity.target, entity.operation, entity.risk, status, detail))
            except Exception as exc:
                results.append(DeletionEntity(entity.kind, entity.target, entity.operation, entity.risk, "failed", str(exc)[:500]))
        plan.entities = results
        plan.blocked = any(entity.status == "failed" for entity in results)
        return plan

    def _record_detail(self, context: DeletionContext, table: dict[str, str], record_id: str) -> str:
        service = context.feishu_service
        if service is None or not hasattr(service, "read_bitable_record"):
            return "未配置 readback 服务；仅按归档证据预览"
        try:
            record = service.read_bitable_record(table["app_token"], table["table_id"], record_id)
        except Exception as exc:
            return f"record readback failed: {str(exc)[:160]}"
        fields = record.get("fields") if isinstance(record, dict) else {}
        if not isinstance(fields, dict):
            fields = {}
        title = self._field_text(fields, "名称") or self._field_text(fields, "标题") or self._field_text(fields, "主题")
        return f"record readback ok{f': {title[:80]}' if title else ''}"

    @staticmethod
    def _record_ids(frontmatter: dict[str, Any]) -> list[str]:
        result: list[str] = []
        for key in RECORD_KEYS:
            value = frontmatter.get(key)
            values = value if isinstance(value, list) else [value]
            for item in values:
                text = str(item or "").strip()
                if text.startswith("rec") and text not in result:
                    result.append(text)
        return result

    @staticmethod
    def _table_ref(frontmatter: dict[str, Any]) -> dict[str, str] | None:
        app_token = str(frontmatter.get("app_token") or "").strip()
        table_id = str(frontmatter.get("table_id") or "").strip()
        if app_token and table_id:
            return {"app_token": app_token, "table_id": table_id}
        for key in TABLE_KEYS:
            table = BitableRecordDeletionAdapter._parse_table_url(str(frontmatter.get(key) or ""))
            if table:
                return table
        return None

    @staticmethod
    def _parse_table_url(url: str) -> dict[str, str] | None:
        if not url:
            return None
        parsed = urllib.parse.urlparse(url)
        segments = [item for item in parsed.path.split("/") if item]
        app_token = ""
        for index, segment in enumerate(segments):
            if segment in {"base", "bitable"} and index + 1 < len(segments):
                app_token = segments[index + 1]
                break
        query = urllib.parse.parse_qs(parsed.query)
        table_id = (query.get("table") or query.get("table_id") or [""])[0]
        if app_token and table_id:
            return {"app_token": app_token, "table_id": table_id}
        return None

    @staticmethod
    def _parse_target(target: str) -> dict[str, str] | None:
        parts = target.split("/")
        if len(parts) != 3:
            return None
        return {"app_token": parts[0], "table_id": parts[1], "record_id": parts[2]}

    @staticmethod
    def _field_text(fields: dict[str, Any], name: str) -> str:
        value = fields.get(name, "")
        if isinstance(value, dict):
            return str(value.get("text") or value.get("name") or value.get("value") or "").strip()
        if isinstance(value, list):
            return "".join(str(item.get("text", item)) if isinstance(item, dict) else str(item) for item in value).strip()
        return str(value or "").strip()
