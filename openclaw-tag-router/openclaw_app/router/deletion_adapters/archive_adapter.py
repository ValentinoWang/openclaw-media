from __future__ import annotations

from ..deletion_discovery import DiscoveryResult, tag_from_record_id
from ..deletion_plan import DeletionEntity, DeletionPlan
from .base import DeletionContext


class ArchiveDeletionAdapter:
    adapter_id = "archive"
    capability_id = "archive_local"
    labels: tuple[str, ...] = ()

    def can_handle(self, discovery: DiscoveryResult) -> bool:
        return bool(discovery.archive_candidates or discovery.inbox_paths)

    def build_plan(self, discovery: DiscoveryResult, context: DeletionContext) -> DeletionPlan:
        tag = sorted(discovery.entry_tags)[0] if discovery.entry_tags else tag_from_record_id(discovery.target_id)
        plan = DeletionPlan(
            target_id=discovery.target_id,
            capability_id=self.capability_id,
            capability_label=f"【{tag}】" if tag else "【未知能力】",
            matched_by=list(discovery.matched_by),
        )
        for path in discovery.inbox_paths:
            plan.add_entity(DeletionEntity("inbox_json", str(path), "unlink"))
        for candidate in discovery.archive_candidates:
            plan.add_entity(DeletionEntity("archive_markdown", str(candidate.path), "unlink"))
            self._add_frontmatter_paths(plan, candidate.frontmatter)
        if not plan.entities:
            plan.warnings.append("未找到 inbox/archive 记录。")
        return plan

    def _add_frontmatter_paths(self, plan: DeletionPlan, frontmatter: dict[str, object]) -> None:
        for key in ("local_path", "obsidian_path"):
            value = str(frontmatter.get(key) or "").strip()
            if value:
                plan.add_entity(DeletionEntity("obsidian_note" if key == "obsidian_path" else "local_file", value, "unlink"))
        for key in ("media_dir", "assets_dir"):
            value = str(frontmatter.get(key) or "").strip()
            if value:
                plan.add_entity(DeletionEntity("local_dir", value, "rmtree"))
        feishu_doc = str(frontmatter.get("feishu_doc") or "").strip()
        if feishu_doc:
            plan.add_entity(DeletionEntity("feishu_doc", feishu_doc, "manual", status="manual_required", detail="普通归档 adapter 不自动删除飞书文档"))
