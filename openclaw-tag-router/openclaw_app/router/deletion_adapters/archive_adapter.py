from __future__ import annotations

import json

from ..deletion_discovery import DiscoveryResult, PERSON_ID_RE, tag_from_record_id
from ..deletion_plan import DeletionEntity, DeletionPlan
from .base import DeletionContext


PERSON_ARCHIVE_METADATA_KEYS = {
    "person_directory",
    "person_view_directory",
    "person_view_manifest_path",
    "view_directory",
    "view_manifest_path",
    "delivery_state_path",
}


class ArchiveDeletionAdapter:
    adapter_id = "archive"
    capability_id = "archive_local"
    labels: tuple[str, ...] = ()

    def can_handle(self, discovery: DiscoveryResult) -> bool:
        return bool(discovery.archive_candidates or discovery.inbox_paths or PERSON_ID_RE.fullmatch(discovery.target_id))

    def build_plan(self, discovery: DiscoveryResult, context: DeletionContext) -> DeletionPlan:
        tag = sorted(discovery.entry_tags)[0] if discovery.entry_tags else tag_from_record_id(discovery.target_id)
        plan = DeletionPlan(
            target_id=discovery.target_id,
            capability_id=self.capability_id,
            capability_label=f"【{tag}】" if tag else "【未知能力】",
            matched_by=list(discovery.matched_by),
        )
        if PERSON_ID_RE.fullmatch(discovery.target_id):
            plan.add_entity(
                DeletionEntity(
                    "external_reference",
                    discovery.target_id,
                    "manual",
                    status="manual_required",
                    detail="人物删除已阻断：必须先提供与 person_id 一致的受管文件清单，并通过 allowed-root 校验。",
                )
            )
            plan.blocked = True
            return plan
        if not self._is_tenant_owned(discovery, context):
            plan.add_entity(
                DeletionEntity(
                    "archive_record",
                    discovery.target_id,
                    "manual",
                    status="manual_required",
                    detail="归档记录不存在或不属于当前租户，已阻断预览和删除。",
                )
            )
            plan.blocked = True
            return plan
        for path in discovery.inbox_paths:
            plan.add_entity(DeletionEntity("inbox_json", str(path), "unlink"))
        for candidate in discovery.archive_candidates:
            plan.add_entity(DeletionEntity("archive_markdown", str(candidate.path), "unlink"))
            self._add_frontmatter_paths(plan, candidate.frontmatter)
        if not plan.entities:
            plan.warnings.append("未找到 inbox/archive 记录。")
        return plan

    @classmethod
    def _is_tenant_owned(cls, discovery: DiscoveryResult, context: DeletionContext) -> bool:
        tenant_id = str(context.tenant_id or "").strip()
        if not tenant_id:
            return False
        for candidate in discovery.archive_candidates:
            if cls._tenant_marker(candidate.frontmatter) != tenant_id:
                return False
        for path in discovery.inbox_paths:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                return False
            if not isinstance(payload, dict) or cls._tenant_marker(payload) != tenant_id:
                return False
        return bool(discovery.archive_candidates or discovery.inbox_paths)

    @staticmethod
    def _tenant_marker(payload: dict[str, object]) -> str:
        return str(
            payload.get("tenant_id")
            or payload.get("tenantId")
            or payload.get("租户ID")
            or ""
        ).strip()

    def _add_frontmatter_paths(self, plan: DeletionPlan, frontmatter: dict[str, object]) -> None:
        # Route deletion is intentionally not an ownership signal for a person entity.
        protected = {str(frontmatter.get(key) or "").strip() for key in PERSON_ARCHIVE_METADATA_KEYS}
        protected.discard("")
        if protected:
            plan.warnings.append("路由记录关联的人物实体已保留；删除人物需要显式 person_id 和受管清单。")
        for key in ("local_path", "obsidian_path"):
            value = str(frontmatter.get(key) or "").strip()
            person_root = str(frontmatter.get("person_directory") or "").strip()
            is_person_path = value in protected or bool(person_root and (value == person_root or value.startswith(person_root.rstrip("/") + "/")))
            if value and not is_person_path:
                plan.add_entity(DeletionEntity("obsidian_note" if key == "obsidian_path" else "local_file", value, "unlink"))
        for key in ("media_dir", "assets_dir"):
            value = str(frontmatter.get(key) or "").strip()
            if value:
                plan.add_entity(DeletionEntity("local_dir", value, "rmtree"))
        feishu_doc = str(frontmatter.get("feishu_doc") or "").strip()
        if feishu_doc:
            plan.add_entity(DeletionEntity("feishu_doc", feishu_doc, "manual", status="manual_required", detail="普通归档 adapter 不自动删除飞书文档"))
