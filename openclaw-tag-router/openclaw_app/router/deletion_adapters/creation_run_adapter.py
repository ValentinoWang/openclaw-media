from __future__ import annotations

import json
import subprocess
import sys
from typing import Any

from ..deletion_discovery import DiscoveryResult, RUN_ID_RE
from ..deletion_plan import DeletionEntity, DeletionPlan
from .base import DeletionContext


class CreationRunDeletionAdapter:
    adapter_id = "creation_run"
    capability_id = "creation_run_cleanup"
    labels = ("删除",)

    _projection_tables = (
        ("creation_run_sources", "创作运行来源"),
        ("creation_run_decisions", "创作运行决定"),
        ("creation_run_outputs", "创作运行输出"),
        ("creation_runs", "创作运行主记录"),
    )

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
            [sys.executable, str(script_path), "--run-id", discovery.target_id, "--tenant-id", context.tenant_id],
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
        try:
            projection_counts = self._projection_counts(discovery.target_id, context)
        except Exception as exc:
            plan.add_entity(
                DeletionEntity(
                    "postgres_creation_run",
                    discovery.target_id,
                    "postgres_delete",
                    status="failed",
                    detail=f"PostgreSQL 创作运行读取失败：{str(exc)[:300]}",
                )
            )
            plan.blocked = True
            return plan
        present = False
        for table, label in self._projection_tables:
            count = projection_counts[table]
            if count <= 0:
                continue
            present = True
            plan.add_entity(
                DeletionEntity(
                    f"postgres_{table}",
                    discovery.target_id,
                    "postgres_delete",
                    detail=f"{label} {count} 条",
                )
            )
        if not present:
            plan.add_entity(
                DeletionEntity(
                    "postgres_creation_run",
                    discovery.target_id,
                    "postgres_delete",
                    status="already_absent",
                    detail="PostgreSQL 创作运行投影已不存在",
                )
            )
        return plan

    def execute(self, plan: DeletionPlan, context: DeletionContext) -> DeletionPlan:
        if plan.blocked or any(entity.status in {"failed", "manual_required"} for entity in plan.entities):
            plan.mode = "apply"
            return plan
        script_path = context.creation_cleanup_script_path
        completed = subprocess.run(
            [sys.executable, str(script_path), "--run-id", plan.target_id, "--tenant-id", context.tenant_id, "--apply"],
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
        plan.blocked = any(entity.status in {"failed", "manual_required"} for entity in plan.entities)
        if plan.blocked:
            return plan
        try:
            plan.entities.extend(self._delete_projection(plan.target_id, context))
        except Exception as exc:
            plan.entities.append(
                DeletionEntity(
                    "postgres_creation_run",
                    plan.target_id,
                    "postgres_delete",
                    status="failed",
                    detail=f"PostgreSQL 创作运行删除或读回失败：{str(exc)[:500]}",
                )
            )
            plan.blocked = True
            return plan
        if not plan.blocked:
            try:
                context.tenant_owned_resources.registry.archive(
                    "media.creation_run",
                    plan.target_id,
                    session_tenant_id=context.tenant_id,
                )
            except Exception as exc:
                plan.entities.append(
                    DeletionEntity(
                        "resource_owner",
                        plan.target_id,
                        "archive",
                        status="failed",
                        detail=str(exc)[:300],
                    )
                )
                plan.blocked = True
        return plan

    def _projection_counts(self, run_id: str, context: DeletionContext) -> dict[str, int]:
        database = context.account_database
        if database is None or not hasattr(database, "connect"):
            raise RuntimeError("未配置 canonical PostgreSQL 数据库")
        with database.connect() as connection:
            return self._projection_counts_from_connection(connection, run_id, context.tenant_id)

    def _projection_counts_from_connection(
        self,
        connection: Any,
        run_id: str,
        tenant_id: str,
    ) -> dict[str, int]:
        row = connection.execute(
            """
            SELECT
              (SELECT COUNT(*) FROM media_product.creation_run_sources
                WHERE tenant_id = %s AND public_run_id = %s),
              (SELECT COUNT(*) FROM media_product.creation_run_decisions
                WHERE tenant_id = %s AND public_run_id = %s),
              (SELECT COUNT(*) FROM media_product.creation_run_outputs
                WHERE tenant_id = %s AND public_run_id = %s),
              (SELECT COUNT(*) FROM media_product.creation_runs
                WHERE tenant_id = %s AND public_id = %s)
            """,
            (
                tenant_id,
                run_id,
                tenant_id,
                run_id,
                tenant_id,
                run_id,
                tenant_id,
                run_id,
            ),
        ).fetchone()
        if not isinstance(row, (tuple, list)) or len(row) != len(self._projection_tables):
            raise RuntimeError("PostgreSQL 创作运行计数读回无效")
        return {
            table: int(row[index] or 0)
            for index, (table, _) in enumerate(self._projection_tables)
        }

    def _delete_projection(self, run_id: str, context: DeletionContext) -> list[DeletionEntity]:
        database = context.account_database
        if database is None or not hasattr(database, "connect"):
            raise RuntimeError("未配置 canonical PostgreSQL 数据库")
        with database.connect() as connection:
            before = self._projection_counts_from_connection(connection, run_id, context.tenant_id)
            try:
                for table, _ in self._projection_tables:
                    id_column = "public_id" if table == "creation_runs" else "public_run_id"
                    connection.execute(
                        f"DELETE FROM media_product.{table} WHERE tenant_id = %s AND {id_column} = %s",
                        (context.tenant_id, run_id),
                    )
                remaining = self._projection_counts_from_connection(connection, run_id, context.tenant_id)
                residual = {table: count for table, count in remaining.items() if count > 0}
                if residual:
                    labels = "、".join(f"{table}={count}" for table, count in residual.items())
                    raise RuntimeError(f"删除后仍有 PostgreSQL 残留：{labels}")
                connection.commit()
            except Exception:
                rollback = getattr(connection, "rollback", None)
                if callable(rollback):
                    rollback()
                raise
        deleted = [
            DeletionEntity(
                f"postgres_{table}",
                run_id,
                "postgres_delete",
                status="deleted",
                detail=f"{label}已删除并读回不存在",
            )
            for table, label in self._projection_tables
            if before[table] > 0
        ]
        return deleted or [
            DeletionEntity(
                "postgres_creation_run",
                run_id,
                "postgres_delete",
                status="already_absent",
                detail="PostgreSQL 创作运行投影已不存在",
            )
        ]
