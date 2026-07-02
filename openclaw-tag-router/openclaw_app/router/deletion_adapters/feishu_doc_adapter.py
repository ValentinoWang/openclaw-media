from __future__ import annotations

from typing import Any

from ..deletion_discovery import DiscoveryResult
from ..deletion_plan import DeletionEntity, DeletionPlan
from .base import DeletionContext


DOC_KEYS = ("feishu_doc", "doc_url", "wiki_url", "feishu_doc_url")


class FeishuDocDeletionAdapter:
    adapter_id = "feishu_doc"
    capability_id = "feishu_doc"
    labels: tuple[str, ...] = ()

    def can_handle(self, discovery: DiscoveryResult) -> bool:
        if "feishu.cn/" in discovery.target_id or "larksuite.com/" in discovery.target_id:
            return True
        return any(self._doc_urls(candidate.frontmatter) for candidate in discovery.archive_candidates)

    def build_plan(self, discovery: DiscoveryResult, context: DeletionContext) -> DeletionPlan:
        plan = DeletionPlan(
            target_id=discovery.target_id,
            capability_id=self.capability_id,
            capability_label="飞书文档",
            matched_by=list(discovery.matched_by),
        )
        urls: list[tuple[str, dict[str, Any]]] = []
        if "feishu.cn/" in discovery.target_id or "larksuite.com/" in discovery.target_id:
            urls.append((discovery.target_id, {}))
        for candidate in discovery.archive_candidates:
            for url in self._doc_urls(candidate.frontmatter):
                urls.append((url, candidate.frontmatter))
        seen: set[str] = set()
        for url, frontmatter in urls:
            if url in seen:
                continue
            seen.add(url)
            owned = self._owned_by_target(frontmatter, discovery.target_id)
            status = "planned" if owned else "manual_required"
            detail = self._doc_detail(context, url)
            if not owned:
                detail = (detail + "；" if detail else "") + "缺少 feishu_doc_delete_allowed 或 created_by_run_id 归属证明"
            plan.add_entity(DeletionEntity("feishu_doc", url, "feishu_delete_document_reference", "high", status, detail))
        return plan

    def execute(self, plan: DeletionPlan, context: DeletionContext) -> DeletionPlan:
        plan.mode = "apply"
        results: list[DeletionEntity] = []
        service = context.feishu_service
        for entity in plan.entities:
            if entity.status == "manual_required":
                results.append(entity)
                continue
            if service is None or not hasattr(service, "resolve_document_reference") or not hasattr(service, "delete_document_reference"):
                results.append(DeletionEntity(entity.kind, entity.target, entity.operation, entity.risk, "failed", "missing feishu document delete service"))
                continue
            try:
                ref = service.resolve_document_reference(entity.target)
                service.delete_document_reference(ref)
                status = "deleted"
                detail = entity.detail
                if hasattr(service, "read_document_reference"):
                    try:
                        readback = service.read_document_reference(ref)
                        if isinstance(readback, dict) and readback.get("ok"):
                            status = "failed"
                            detail = "delete API returned but document readback still succeeds"
                    except Exception as exc:
                        detail = f"readback absent: {str(exc)[:160]}"
                results.append(DeletionEntity(entity.kind, entity.target, entity.operation, entity.risk, status, detail))
            except Exception as exc:
                text = str(exc)
                status = "manual_required" if "未启用" in text or "不支持" in text else "failed"
                results.append(DeletionEntity(entity.kind, entity.target, entity.operation, entity.risk, status, text[:500]))
        plan.entities = results
        plan.blocked = any(entity.status == "failed" for entity in results)
        return plan

    @staticmethod
    def _doc_urls(frontmatter: dict[str, Any]) -> list[str]:
        result: list[str] = []
        for key in DOC_KEYS:
            value = frontmatter.get(key)
            values = value if isinstance(value, list) else [value]
            for item in values:
                text = str(item or "").strip()
                if ("feishu.cn/" in text or "larksuite.com/" in text) and text not in result:
                    result.append(text)
        return result

    @staticmethod
    def _owned_by_target(frontmatter: dict[str, Any], target_id: str) -> bool:
        if str(frontmatter.get("feishu_doc_delete_allowed") or "").strip().lower() in {"1", "true", "yes", "on"}:
            return True
        for key in ("created_by_run_id", "run_id", "id"):
            if str(frontmatter.get(key) or "").strip() == target_id:
                return True
        return False

    @staticmethod
    def _doc_detail(context: DeletionContext, url: str) -> str:
        service = context.feishu_service
        if service is None or not hasattr(service, "resolve_document_reference"):
            return "未配置飞书文档 readback 服务"
        try:
            ref = service.resolve_document_reference(url)
        except Exception as exc:
            return f"document resolve failed: {str(exc)[:160]}"
        kind = ref.get("kind") or ""
        token = ref.get("token") or ""
        document_id = ref.get("document_id") or ""
        return f"kind={kind} token={token} document_id={document_id}"
