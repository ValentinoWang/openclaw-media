from __future__ import annotations

import json
import subprocess
import sys

from ..deletion_discovery import DiscoveryResult, RUN_ID_RE
from ..deletion_plan import DeletionEntity, DeletionPlan
from .base import DeletionContext


class CreationRunDeletionAdapter:
    adapter_id = "creation_run"
    capability_id = "creation_run_cleanup"
    labels = ("删除",)

    def can_handle(self, discovery: DiscoveryResult) -> bool:
        return bool(RUN_ID_RE.match(discovery.target_id))

    def build_plan(self, discovery: DiscoveryResult, context: DeletionContext) -> DeletionPlan:
        plan = DeletionPlan(
            target_id=discovery.target_id,
            capability_id=self.capability_id,
            capability_label="【删除】",
            matched_by=["run_id"],
        )
        script_path = context.creation_cleanup_script_path
        if not script_path.exists():
            plan.add_entity(DeletionEntity("creation_run_script", str(script_path), "script", status="failed", detail="删除脚本不存在"))
            return plan
        completed = subprocess.run(
            [sys.executable, str(script_path), "--run-id", discovery.target_id],
            cwd=str(script_path.parents[1]),
            text=True,
            capture_output=True,
            timeout=180,
            check=False,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()
            plan.add_entity(DeletionEntity("creation_run_script", discovery.target_id, "script", status="failed", detail=detail[:500]))
            return plan
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError:
            plan.add_entity(DeletionEntity("creation_run_script", discovery.target_id, "script", status="failed", detail="脚本未返回有效 JSON"))
            return plan
        for run in payload.get("runs") or []:
            for action in run.get("actions") or []:
                plan.add_entity(
                    DeletionEntity(
                        str(action.get("kind") or "creation_run_script"),
                        str(action.get("target") or discovery.target_id),
                        "script",
                        status=str(action.get("status") or "planned"),
                        detail=str(action.get("detail") or ""),
                    )
                )
            for warning in run.get("warnings") or []:
                plan.warnings.append(str(warning))
        if not plan.entities:
            plan.add_entity(DeletionEntity("creation_run_script", discovery.target_id, "script", detail="脚本未发现可删除项"))
        return plan

    def execute(self, plan: DeletionPlan, context: DeletionContext) -> DeletionPlan:
        script_path = context.creation_cleanup_script_path
        completed = subprocess.run(
            [sys.executable, str(script_path), "--run-id", plan.target_id, "--apply"],
            cwd=str(script_path.parents[1]),
            text=True,
            capture_output=True,
            timeout=180,
            check=False,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()
            plan.mode = "apply"
            plan.entities = [DeletionEntity("creation_run_script", plan.target_id, "script", status="failed", detail=detail[:1000])]
            plan.blocked = True
            return plan
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError:
            plan.mode = "apply"
            plan.entities = [DeletionEntity("creation_run_script", plan.target_id, "script", status="failed", detail="脚本未返回有效 JSON")]
            plan.blocked = True
            return plan
        entities: list[DeletionEntity] = []
        for run in payload.get("runs") or []:
            for action in run.get("actions") or []:
                entities.append(
                    DeletionEntity(
                        str(action.get("kind") or "creation_run_script"),
                        str(action.get("target") or plan.target_id),
                        "script",
                        status=str(action.get("status") or "failed"),
                        detail=str(action.get("detail") or ""),
                    )
                )
        plan.mode = "apply"
        plan.entities = entities or [DeletionEntity("creation_run_script", plan.target_id, "script", status="already_absent")]
        plan.blocked = any(entity.status == "failed" for entity in plan.entities)
        return plan
