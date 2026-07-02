from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from ..deletion_discovery import DiscoveryResult
from ..deletion_plan import DeletionPlan


@dataclass
class DeletionContext:
    workspace_root: Path
    allowed_roots: list[Path]
    creation_cleanup_script_path: Path
    feishu_service: Any = None
    reminder_service: Any = None
    media_registry_path: Path = Path("/home/ubuntu/openclaw-feishu-reminder/media-bitable-registry.json")
    daily_config_path: Path = Path("/home/ubuntu/openclaw-feishu-reminder/config.json")
    knowledge_config_path: Path = Path("/home/ubuntu/openclaw-feishu-reminder/knowledge-config.json")
    content_os_vault_root: Path = Path("/home/ubuntu/obsidian-自媒体")


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
