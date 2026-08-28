from __future__ import annotations

import json
from pathlib import Path

from media_vault import MediaVault

from .deletion_adapters import adapters_for
from .deletion_adapters.base import DeletionContext
from .deletion_discovery import APPLY_KEYWORDS, discover_target, extract_target_ids
from .deletion_plan import DeletionEntity, DeletionPlan, execute_local_plan, render_deletion_reply
from .tag_router_common import *
from ..services.tenant_execution_context import current_session_tenant_id


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
REPOSITORY_AGENT_RESULTS_CONTRACT_PATH = REPOSITORY_ROOT / "docs/ai-harness/agent_result_vault_contract.json"
LEGACY_AGENT_RESULTS_CONTRACT_PATH = Path("/home/ubuntu/docs/ai-harness/agent_result_vault_contract.json")


def _agent_results_contract_path() -> Path:
    override = os.getenv("OPENCLAW_AGENT_RESULTS_CONTRACT_PATH")
    if override:
        return Path(override)
    if REPOSITORY_AGENT_RESULTS_CONTRACT_PATH.is_file():
        return REPOSITORY_AGENT_RESULTS_CONTRACT_PATH
    return LEGACY_AGENT_RESULTS_CONTRACT_PATH


AGENT_RESULTS_CONTRACT_PATH = _agent_results_contract_path()


def _agent_results_base() -> Path:
    contract = json.loads(AGENT_RESULTS_CONTRACT_PATH.read_text(encoding="utf-8"))
    return Path(str(contract["physical_root"]))


def _agent_results_required_folders() -> tuple[str, ...]:
    contract = json.loads(AGENT_RESULTS_CONTRACT_PATH.read_text(encoding="utf-8"))
    folders = contract.get("required_folders")
    if not isinstance(folders, list) or not all(isinstance(folder, str) for folder in folders):
        raise RuntimeError(f"invalid agent result vault contract folders: {AGENT_RESULTS_CONTRACT_PATH}")
    return tuple(folders)


class DeletionMixin:
    def _creation_cleanup_script_path(self) -> Path:
        return Path(__file__).resolve().parents[2] / "scripts" / "cleanup_creation_runs.py"

    def _deletion_workspace_root(self) -> Path:
        return Path(getattr(self, "workspace_root", Path("/home/ubuntu/.openclaw/workspace/openclaw-tag-router")))

    def _deletion_allowed_roots(self, tenant_id: str | None = None) -> list[Path]:
        workspace_root = self._deletion_workspace_root()
        agent_results_base = _agent_results_base()
        agent_results_roots = [agent_results_base / folder for folder in _agent_results_required_folders()]
        verified_tenant_id = str(tenant_id or current_session_tenant_id())
        tenant_vault_root = MediaVault(tenant_id=verified_tenant_id).root
        return [
            workspace_root,
            tenant_vault_root,
            *agent_results_roots,
            Path("/home/ubuntu/obsidian-日记"),
            Path("/home/ubuntu/obsidian-自媒体"),
            Path("/home/ubuntu/98_Agent任务队列"),
        ]

    def _is_delete_apply_request(self, body: str) -> bool:
        return any(keyword in (body or "") for keyword in APPLY_KEYWORDS)

    def _deletion_context(self) -> DeletionContext:
        tenant_id = str(current_session_tenant_id())
        return DeletionContext(
            workspace_root=self._deletion_workspace_root(),
            allowed_roots=self._deletion_allowed_roots(tenant_id),
            creation_cleanup_script_path=self._creation_cleanup_script_path(),
            feishu_service=getattr(self, "feishu_service", None),
            media_feishu_service=getattr(self, "media_source_feishu_service", None),
            reminder_service=getattr(self, "reminder_service", None),
            tenant_id=tenant_id,
            tenant_owned_resources=getattr(self, "tenant_owned_resources", None),
            source_asset_projection=getattr(self, "source_asset_projection", None),
            account_database=getattr(self, "account_database", None),
        )

    def handle_删除(self, message: Message) -> TaskResult:
        target_ids = extract_target_ids(message.body)
        if not target_ids:
            return TaskResult(
                ok=False,
                status="delete_missing_target_id",
                reply=(
                    "请提供要删除的明确目标 ID。\n"
                    "预览：`【删除】20260412-030515-qq-灵感-0056` 或 `【删除】run_router_xxx`\n"
                    "执行：`【删除】确认删除 20260412-030515-qq-灵感-0056`\n"
                    "未写确认删除时只预览，不会删除文件、文档或记录。"
                ),
                task_id="",
            )

        context = self._deletion_context()
        apply = self._is_delete_apply_request(message.body)
        plans: list[DeletionPlan] = []
        for target_id in target_ids:
            discovery = discover_target(context.workspace_root, target_id)
            adapters = adapters_for(discovery)
            if not adapters:
                plan = DeletionPlan(
                    target_id=target_id,
                    capability_id="unknown",
                    capability_label="未识别能力",
                    matched_by=discovery.matched_by,
                    warnings=discovery.warnings,
                )
                plan.add_entity(
                    DeletionEntity(
                        "external_reference",
                        target_id,
                        "manual",
                        status="manual_required",
                        detail="没有匹配到可自动删除的能力适配器；请先补充该能力的删除契约。",
                    )
                )
                if apply:
                    plan = execute_local_plan(plan, context.allowed_roots)
                plans.append(plan)
                continue
            for adapter in adapters:
                plan = adapter.build_plan(discovery, context)
                if discovery.warnings:
                    plan.warnings.extend(discovery.warnings)
                if apply:
                    execute = getattr(adapter, "execute", None)
                    plan = execute(plan, context) if callable(execute) else execute_local_plan(plan, context.allowed_roots)
                plans.append(plan)

        ok = not any(
            plan.blocked or any(entity.status == "failed" for entity in plan.entities)
            for plan in plans
        )
        return TaskResult(
            ok=ok,
            status=("deletion_applied" if apply else "deletion_dry_run") if ok else "deletion_failed",
            reply=render_deletion_reply(plans, apply=apply),
            task_id="",
            extra={"deletion": [plan.to_dict() for plan in plans]},
        )
