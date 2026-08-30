from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from common.env import feishu_reminder_root

from ..content_os_utils import content_os_vault_root as _default_content_os_vault_root
from ..deletion_discovery import DiscoveryResult
from ..deletion_plan import DeletionPlan


def resolve_media_registry_table(
    registry: Any,
    *,
    legacy_key: str,
    table_key: str,
) -> dict[str, str]:
    if not isinstance(registry, dict):
        raise ValueError("Media 注册表根节点必须是对象")
    tables = registry.get("tables")
    if isinstance(tables, dict):
        entry = tables.get(legacy_key)
        binding_name = legacy_key
    elif isinstance(tables, list):
        matches = [
            item
            for item in tables
            if isinstance(item, dict)
            and str(item.get("table_key") or "").strip() == table_key
        ]
        if not matches:
            raise ValueError(f"注册表未登记 {table_key}")
        if len(matches) != 1:
            raise ValueError(f"注册表重复登记 {table_key}")
        entry = matches[0]
        binding_name = table_key
    else:
        raise ValueError("Media 注册表 tables 必须是对象或数组")

    if not isinstance(entry, dict):
        raise ValueError(f"注册表未登记 {binding_name}")

    app_token = str(entry.get("app_token") or "").strip()
    base_token = str(entry.get("base_token") or "").strip()
    if app_token and base_token and app_token != base_token:
        raise ValueError(f"{binding_name} 注册表的 app_token/base_token 冲突")

    nested_table = entry.get("table")
    if nested_table is not None and not isinstance(nested_table, dict):
        raise ValueError(f"{binding_name} 注册表的 table 必须是对象")
    table_id = str(entry.get("table_id") or "").strip()
    nested_table_id = str((nested_table or {}).get("table_id") or "").strip()
    if table_id and nested_table_id and table_id != nested_table_id:
        raise ValueError(f"{binding_name} 注册表的 table_id 冲突")

    canonical_app_token = app_token or base_token
    canonical_table_id = table_id or nested_table_id
    if not canonical_app_token or not canonical_table_id:
        raise ValueError(f"{binding_name} 注册表缺少 app_token/base_token 或 table_id")
    return {
        "app_token": canonical_app_token,
        "table_id": canonical_table_id,
    }


@dataclass
class DeletionContext:
    workspace_root: Path
    allowed_roots: list[Path]
    creation_cleanup_script_path: Path
    feishu_service: Any = None
    media_feishu_service: Any = None
    reminder_service: Any = None
    tenant_id: str = ""
    tenant_owned_resources: Any = None
    source_asset_projection: Any = None
    account_database: Any = None
    media_registry_path: Path = feishu_reminder_root() / "media-bitable-registry.json"
    daily_config_path: Path = feishu_reminder_root() / "config.json"
    knowledge_config_path: Path = feishu_reminder_root() / "knowledge-config.json"
    content_os_vault_root: Path = _default_content_os_vault_root()


class CapabilityDeletionAdapter(Protocol):
    adapter_id: str
    capability_id: str
    labels: tuple[str, ...]

    def can_handle(self, discovery: DiscoveryResult) -> bool:
        ...

    def build_plan(self, discovery: DiscoveryResult, context: DeletionContext) -> DeletionPlan:
        ...

    def execute(self, plan: DeletionPlan, context: DeletionContext) -> DeletionPlan:
        ...

    def readback(self, plan: DeletionPlan, context: DeletionContext) -> DeletionPlan:
        ...
