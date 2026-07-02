from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

import yaml

from ..deletion_discovery import DiscoveryResult
from ..deletion_plan import DeletionEntity, DeletionPlan, is_path_under
from .base import DeletionContext


class ContentOSDeletionAdapter:
    adapter_id = "content_os"
    capability_id = "content_os"
    labels: tuple[str, ...] = ()

    def can_handle(self, discovery: DiscoveryResult) -> bool:
        root = Path("/home/ubuntu/obsidian-自媒体")
        if (root / "08_内容项目" / discovery.target_id).exists():
            return True
        if self._looks_like_task_id(discovery.target_id):
            return True
        for candidate in discovery.archive_candidates:
            refs = self._content_os_refs(candidate.frontmatter, candidate.body)
            if any(refs.values()):
                return True
        return False

    def build_plan(self, discovery: DiscoveryResult, context: DeletionContext) -> DeletionPlan:
        plan = DeletionPlan(
            target_id=discovery.target_id,
            capability_id=self.capability_id,
            capability_label="Content OS / Mac 队列",
            matched_by=list(discovery.matched_by),
        )
        refs = self._discover_refs(discovery, context.content_os_vault_root)
        for project_id in sorted(refs["project_ids"]):
            project_dir = context.content_os_vault_root / "08_内容项目" / project_id
            if project_dir.exists():
                plan.add_entity(DeletionEntity("local_dir", str(project_dir), "rmtree", "high", detail=f"Content OS project_id={project_id}"))
            for registry in ("project_registry.md", "idea_registry.md", "task_registry.md"):
                path = context.content_os_vault_root / "90_索引与注册表" / registry
                if path.exists() and project_id in path.read_text(encoding="utf-8", errors="replace"):
                    plan.add_entity(DeletionEntity("obsidian_block", f"{path}#{project_id}", "delete_markdown_table_row", "normal", detail=f"registry row for {project_id}"))
        for task_path in sorted(refs["task_paths"]):
            if task_path.exists():
                plan.add_entity(DeletionEntity("mac_queue_task", str(task_path), "unlink", "normal"))
                task_id = task_path.name.split("_openclaw", 1)[0].split("_material", 1)[0]
                registry = context.content_os_vault_root / "90_索引与注册表" / "task_registry.md"
                if registry.exists():
                    plan.add_entity(DeletionEntity("obsidian_block", f"{registry}#{task_id}", "delete_markdown_table_row", "normal", detail=f"registry row for {task_id}"))
        return plan

    def execute(self, plan: DeletionPlan, context: DeletionContext) -> DeletionPlan:
        plan.mode = "apply"
        results: list[DeletionEntity] = []
        ordered = sorted(plan.entities, key=lambda entity: {"mac_queue_task": 0, "obsidian_block": 1, "local_dir": 2}.get(entity.kind, 3))
        for entity in ordered:
            if entity.kind == "mac_queue_task":
                results.append(self._delete_file_entity(entity, context))
            elif entity.kind == "local_dir":
                results.append(self._delete_dir_entity(entity, context))
            elif entity.kind == "obsidian_block":
                results.append(self._delete_registry_row(entity, context))
            else:
                results.append(entity)
        plan.entities = results
        plan.blocked = any(entity.status == "failed" for entity in results)
        return plan

    def _discover_refs(self, discovery: DiscoveryResult, vault_root: Path) -> dict[str, set[Any]]:
        project_ids: set[str] = set()
        task_ids: set[str] = set()
        task_paths: set[Path] = set()
        if (vault_root / "08_内容项目" / discovery.target_id).exists():
            project_ids.add(discovery.target_id)
        if self._looks_like_task_id(discovery.target_id):
            task_ids.add(discovery.target_id)
        for candidate in discovery.archive_candidates:
            refs = self._content_os_refs(candidate.frontmatter, candidate.body)
            project_ids.update(refs["project_ids"])
            task_ids.update(refs["task_ids"])
            task_paths.update(Path(path) for path in refs["task_paths"])
        queue_root = vault_root / "98_Agent任务队列" / "01_cloud_to_mac_ready"
        if queue_root.exists():
            for path in queue_root.glob("*.yaml"):
                try:
                    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                except Exception:
                    continue
                if not isinstance(payload, dict):
                    continue
                if payload.get("project_id") in project_ids or payload.get("task_id") in task_ids or payload.get("creation_run_id") == discovery.target_id:
                    task_paths.add(path)
                    if payload.get("project_id"):
                        project_ids.add(str(payload.get("project_id")))
                if path.stem in task_ids or any(task_id in path.name for task_id in task_ids):
                    task_paths.add(path)
        return {"project_ids": project_ids, "task_ids": task_ids, "task_paths": task_paths}

    @staticmethod
    def _content_os_refs(frontmatter: dict[str, Any], body: str) -> dict[str, set[str]]:
        project_ids: set[str] = set()
        task_ids: set[str] = set()
        task_paths: set[str] = set()
        for key in ("project_id", "content_os_project_id"):
            text = str(frontmatter.get(key) or "").strip()
            if text:
                project_ids.add(text)
        for key in ("task_id", "content_os_task_id"):
            text = str(frontmatter.get(key) or "").strip()
            if text:
                task_ids.add(text)
        for key in ("task_path", "mac_task_path"):
            text = str(frontmatter.get(key) or "").strip()
            if text.startswith("/"):
                task_paths.add(text)
        nested = frontmatter.get("content_os_project")
        if isinstance(nested, dict):
            for key in ("project_id", "task_id", "task_path", "project_path"):
                text = str(nested.get(key) or "").strip()
                if key == "project_id" and text:
                    project_ids.add(text)
                elif key == "task_id" and text:
                    task_ids.add(text)
                elif key == "task_path" and text.startswith("/"):
                    task_paths.add(text)
                elif key == "project_path" and text:
                    project_ids.add(Path(text).name)
        for label, bucket in (("Content OS 项目", project_ids), ("project_id", project_ids), ("Mac 任务", task_paths), ("task_path", task_paths), ("task_id", task_ids)):
            for match in re.findall(rf"{re.escape(label)}[：:=]\s*([^\n`]+)", body or ""):
                value = match.strip().strip("` ")
                if value.startswith("/") and bucket is task_paths:
                    bucket.add(value)
                elif value:
                    bucket.add(value.split()[0].strip("，,。；;"))
        return {"project_ids": project_ids, "task_ids": task_ids, "task_paths": task_paths}

    @staticmethod
    def _looks_like_task_id(value: str) -> bool:
        return bool(re.fullmatch(r"task_\d{8}_\d{3}", value or ""))

    @staticmethod
    def _delete_file_entity(entity: DeletionEntity, context: DeletionContext) -> DeletionEntity:
        path = Path(entity.target)
        if not is_path_under(path, context.allowed_roots):
            return DeletionEntity(entity.kind, entity.target, entity.operation, entity.risk, "failed", "path is outside allowed deletion roots")
        if not path.exists():
            return DeletionEntity(entity.kind, entity.target, entity.operation, entity.risk, "already_absent", entity.detail)
        try:
            path.unlink()
            return DeletionEntity(entity.kind, entity.target, entity.operation, entity.risk, "deleted", entity.detail)
        except OSError as exc:
            return DeletionEntity(entity.kind, entity.target, entity.operation, entity.risk, "failed", str(exc))

    @staticmethod
    def _delete_dir_entity(entity: DeletionEntity, context: DeletionContext) -> DeletionEntity:
        path = Path(entity.target)
        if not is_path_under(path, context.allowed_roots):
            return DeletionEntity(entity.kind, entity.target, entity.operation, entity.risk, "failed", "path is outside allowed deletion roots")
        if not path.exists():
            return DeletionEntity(entity.kind, entity.target, entity.operation, entity.risk, "already_absent", entity.detail)
        try:
            shutil.rmtree(path)
            return DeletionEntity(entity.kind, entity.target, entity.operation, entity.risk, "deleted", entity.detail)
        except OSError as exc:
            return DeletionEntity(entity.kind, entity.target, entity.operation, entity.risk, "failed", str(exc))

    @staticmethod
    def _delete_registry_row(entity: DeletionEntity, context: DeletionContext) -> DeletionEntity:
        path_text, sep, key = entity.target.partition("#")
        path = Path(path_text)
        if not sep or not key:
            return DeletionEntity(entity.kind, entity.target, entity.operation, entity.risk, "failed", "invalid registry row target")
        if not is_path_under(path, context.allowed_roots):
            return DeletionEntity(entity.kind, entity.target, entity.operation, entity.risk, "failed", "path is outside allowed deletion roots")
        if not path.exists():
            return DeletionEntity(entity.kind, entity.target, entity.operation, entity.risk, "already_absent", entity.detail)
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            kept = [line for line in lines if not (line.startswith("|") and key in [cell.strip() for cell in line.strip("|").split("|")])]
            if len(kept) == len(lines):
                return DeletionEntity(entity.kind, entity.target, entity.operation, entity.risk, "already_absent", "registry row already absent")
            path.write_text("\n".join(kept).rstrip() + "\n", encoding="utf-8")
            readback = path.read_text(encoding="utf-8", errors="replace")
            status = "deleted" if key not in readback else "failed"
            detail = entity.detail if status == "deleted" else "registry key still present after write"
            return DeletionEntity(entity.kind, entity.target, entity.operation, entity.risk, status, detail)
        except OSError as exc:
            return DeletionEntity(entity.kind, entity.target, entity.operation, entity.risk, "failed", str(exc))
