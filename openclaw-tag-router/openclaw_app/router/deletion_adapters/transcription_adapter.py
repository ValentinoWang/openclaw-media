from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..deletion_discovery import DiscoveryResult, archive_prefix
from ..deletion_plan import DeletionEntity, DeletionPlan
from .archive_adapter import ArchiveDeletionAdapter
from .base import DeletionContext


class TranscriptionDeletionAdapter(ArchiveDeletionAdapter):
    adapter_id = "transcription"
    capability_id = "transcription"
    labels = ("转写", "转写-文字")

    def can_handle(self, discovery: DiscoveryResult) -> bool:
        return bool(discovery.entry_tags & set(self.labels))

    def build_plan(self, discovery: DiscoveryResult, context: DeletionContext) -> DeletionPlan:
        plan = DeletionPlan(
            target_id=discovery.target_id,
            capability_id="transcription",
            capability_label="【转写】",
            matched_by=list(discovery.matched_by),
        )
        for path in discovery.inbox_paths:
            plan.add_entity(DeletionEntity("inbox_json", str(path), "unlink"))
        for candidate in discovery.archive_candidates:
            plan.add_entity(DeletionEntity("archive_markdown", str(candidate.path), "unlink"))
            self._add_transcription_frontmatter(plan, candidate.frontmatter)
            self._add_transcription_body_paths(plan, candidate.body)
        self._add_task_dirs(plan, context.workspace_root, discovery.target_id)
        if not any(entity.kind == "obsidian_note" for entity in plan.entities):
            plan.add_entity(
                DeletionEntity(
                    "external_reference",
                    "Knowledge 周记摘要",
                    "manual",
                    status="manual_required",
                    detail="缺少 openclaw block anchor，不能按关键词删除周记段落",
                )
            )
        return plan

    def _add_transcription_frontmatter(self, plan: DeletionPlan, frontmatter: dict[str, Any]) -> None:
        media_dir = str(frontmatter.get("media_dir") or "").strip()
        if media_dir:
            plan.add_entity(DeletionEntity("local_dir", media_dir, "rmtree"))
        for key in ("transcript_paths", "text_attachment_paths"):
            for value in self._flatten_paths(frontmatter.get(key)):
                plan.add_entity(DeletionEntity("content_flow_artifact", value, "unlink"))
        obsidian_path = str(frontmatter.get("obsidian_path") or "").strip()
        if obsidian_path:
            plan.add_entity(DeletionEntity("obsidian_note", obsidian_path, "unlink"))
        obsidian_transcript_path = str(frontmatter.get("obsidian_transcript_path") or "").strip()
        if obsidian_transcript_path:
            plan.add_entity(DeletionEntity("obsidian_transcript", obsidian_transcript_path, "unlink"))
        obsidian_topical_attachments_path = str(
            frontmatter.get("obsidian_topical_attachments_path") or ""
        ).strip()
        if obsidian_topical_attachments_path:
            plan.add_entity(
                DeletionEntity("obsidian_topical_attachments", obsidian_topical_attachments_path, "unlink")
            )
        for value in self._flatten_paths(frontmatter.get("postprocess_artifacts")):
            plan.add_entity(DeletionEntity("content_flow_artifact", value, "unlink"))

    def _add_transcription_body_paths(self, plan: DeletionPlan, body: str) -> None:
        for label, kind in (
            ("Obsidian 会议纪要", "obsidian_note"),
            ("Obsidian 原字稿", "obsidian_transcript"),
            ("Obsidian 专题附件", "obsidian_topical_attachments"),
            ("文字稿任务目录", "local_dir"),
            ("素材目录", "local_dir"),
            ("逐字稿路径", "content_flow_artifact"),
            ("音频路径", "content_flow_artifact"),
            ("视频路径", "content_flow_artifact"),
        ):
            for value in re.findall(rf"{re.escape(label)}[：:]\s*([^\n`]+)", body or ""):
                target = value.strip().strip("- ").strip()
                if target:
                    plan.add_entity(DeletionEntity(kind, target, "rmtree" if kind == "local_dir" else "unlink"))

    def _add_task_dirs(self, plan: DeletionPlan, workspace_root: Path, target_id: str) -> None:
        prefix = archive_prefix(target_id)
        for bucket in ("uploaded_transcripts", "text_transcripts"):
            root = workspace_root / "content_flow" / bucket
            if not root.exists():
                continue
            for path in sorted(root.glob(f"{prefix}-*")):
                if path.is_dir():
                    plan.add_entity(DeletionEntity("local_dir", str(path), "rmtree"))

    def _flatten_paths(self, value: Any) -> list[str]:
        result: list[str] = []
        if isinstance(value, dict):
            for item in value.values():
                result.extend(self._flatten_paths(item))
        elif isinstance(value, (list, tuple, set)):
            for item in value:
                result.extend(self._flatten_paths(item))
        elif isinstance(value, str):
            text = value.strip()
            if text.startswith("/"):
                result.append(text)
        return result
