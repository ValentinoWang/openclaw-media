from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..deletion_discovery import DiscoveryResult
from ..deletion_plan import DeletionEntity, DeletionPlan, is_path_under
from .base import DeletionContext


PATH_KEYS = ("weekly_path", "obsidian_weekly_path", "obsidian_path", "local_path")


class ObsidianBlockDeletionAdapter:
    adapter_id = "obsidian_block"
    capability_id = "obsidian_block"
    labels: tuple[str, ...] = ()

    def can_handle(self, discovery: DiscoveryResult) -> bool:
        return any(self._candidate_paths(candidate.frontmatter) for candidate in discovery.archive_candidates)

    def build_plan(self, discovery: DiscoveryResult, context: DeletionContext) -> DeletionPlan:
        plan = DeletionPlan(
            target_id=discovery.target_id,
            capability_id=self.capability_id,
            capability_label="Obsidian 块删除",
            matched_by=list(discovery.matched_by),
        )
        for candidate in discovery.archive_candidates:
            record_ids = self._record_ids(candidate.frontmatter)
            for path in self._candidate_paths(candidate.frontmatter):
                self._add_blocks_from_file(plan, path, discovery.target_id, record_ids)
        return plan

    def execute(self, plan: DeletionPlan, context: DeletionContext) -> DeletionPlan:
        plan.mode = "apply"
        results: list[DeletionEntity] = []
        for entity in plan.entities:
            parsed = self._parse_target(entity.target)
            if not parsed:
                results.append(DeletionEntity(entity.kind, entity.target, entity.operation, entity.risk, "failed", "invalid obsidian block target"))
                continue
            path = Path(parsed["path"])
            if not is_path_under(path, context.allowed_roots):
                results.append(DeletionEntity(entity.kind, entity.target, entity.operation, entity.risk, "failed", "path is outside allowed deletion roots"))
                continue
            try:
                if not path.exists():
                    results.append(DeletionEntity(entity.kind, entity.target, entity.operation, entity.risk, "already_absent", entity.detail))
                    continue
                text = path.read_text(encoding="utf-8", errors="replace")
                new_text, removed = self._remove_block(text, parsed["anchor"])
                if not removed:
                    results.append(DeletionEntity(entity.kind, entity.target, entity.operation, entity.risk, "already_absent", "anchor/comment already absent"))
                    continue
                path.write_text(new_text, encoding="utf-8")
                readback = path.read_text(encoding="utf-8", errors="replace")
                status = "deleted" if parsed["anchor"] not in readback else "failed"
                detail = entity.detail if status == "deleted" else "anchor still present after write"
                results.append(DeletionEntity(entity.kind, entity.target, entity.operation, entity.risk, status, detail))
            except OSError as exc:
                results.append(DeletionEntity(entity.kind, entity.target, entity.operation, entity.risk, "failed", str(exc)))
        plan.entities = results
        plan.blocked = any(entity.status == "failed" for entity in results)
        return plan

    def _add_blocks_from_file(self, plan: DeletionPlan, path: Path, target_id: str, record_ids: list[str]) -> None:
        if not path.exists() or not path.is_file():
            return
        text = path.read_text(encoding="utf-8", errors="replace")
        start = f"<!-- openclaw-delete:{target_id}:start"
        end = f"<!-- openclaw-delete:{target_id}:end -->"
        if start in text and end in text:
            plan.add_entity(DeletionEntity("obsidian_block", f"{path}#openclaw-delete:{target_id}", "delete_markdown_block", "normal", detail="openclaw-delete start/end anchor"))
        for record_id in record_ids:
            marker = f"openclaw:feishu_record={record_id}"
            if marker in text:
                plan.add_entity(DeletionEntity("obsidian_block", f"{path}#{marker}", "delete_markdown_line", "normal", detail="openclaw checklist comment"))
        for match in re.finditer(r"<!-- content_os_auto:(?P<section>[^:]+):start -->", text):
            section = match.group("section")
            if section == target_id:
                plan.add_entity(DeletionEntity("obsidian_block", f"{path}#content_os_auto:{section}", "delete_markdown_block", "normal", detail="content_os_auto section"))

    @staticmethod
    def _candidate_paths(frontmatter: dict[str, Any]) -> list[Path]:
        result: list[Path] = []
        for key in PATH_KEYS:
            text = str(frontmatter.get(key) or "").strip()
            if text.startswith("/") and Path(text) not in result:
                result.append(Path(text))
        return result

    @staticmethod
    def _record_ids(frontmatter: dict[str, Any]) -> list[str]:
        result: list[str] = []
        for key in ("record_id", "feishu_record_id", "reminder_record_id"):
            text = str(frontmatter.get(key) or "").strip()
            if text.startswith("rec") and text not in result:
                result.append(text)
        return result

    @staticmethod
    def _parse_target(target: str) -> dict[str, str] | None:
        path, sep, anchor = target.partition("#")
        if not sep or not path or not anchor:
            return None
        return {"path": path, "anchor": anchor}

    @staticmethod
    def _remove_block(text: str, anchor: str) -> tuple[str, bool]:
        if anchor.startswith("openclaw-delete:"):
            target = anchor.split(":", 1)[1]
            pattern = re.compile(
                rf"\n?<!-- openclaw-delete:{re.escape(target)}:start[^>]*-->.*?<!-- openclaw-delete:{re.escape(target)}:end -->\n?",
                flags=re.S,
            )
            new_text, count = pattern.subn("\n", text, count=1)
            return new_text, count > 0
        if anchor.startswith("openclaw:feishu_record="):
            lines = text.splitlines()
            kept = [line for line in lines if anchor not in line]
            return "\n".join(kept).rstrip() + ("\n" if text.endswith("\n") else ""), len(kept) != len(lines)
        if anchor.startswith("content_os_auto:"):
            section = anchor.split(":", 1)[1]
            pattern = re.compile(
                rf"\n?<!-- content_os_auto:{re.escape(section)}:start -->.*?<!-- content_os_auto:{re.escape(section)}:end -->\n?",
                flags=re.S,
            )
            new_text, count = pattern.subn("\n", text, count=1)
            return new_text, count > 0
        return text, False
