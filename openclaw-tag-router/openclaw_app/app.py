from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from .adapters.mac_agent_client import MacAgentClient
from .router.tag_router import TagRouter
from .services.archive_service import ArchiveService
from .services.completion_guard import CompletionGuard
from .services.content_flow_client import ContentFlowClient
from .services.feishu_service import FeishuService
from .services.obsidian_daily_checklist_service import ObsidianDailyChecklistService
from .services.reminder_service import ReminderService
from .services.rule_service import RuleService
from .services.schedule_service import ScheduleService
from .services.stage2_gateway import Stage2Gateway
from .services.utils import parse_tag_message_with_metadata
from .services.vlog_storage_service import VlogStorageService


class OpenClawApp:
    def __init__(self, settings_path: str | Path, *, stage2_gateway: Stage2Gateway | None = None):
        self.settings_path = Path(settings_path)
        self.settings = yaml.safe_load(self.settings_path.read_text(encoding="utf-8"))
        workspace_root = self.settings["workspace_root"]
        archive_service = ArchiveService(workspace_root)
        rule_service = RuleService(Path(workspace_root) / "rules" / "user_rules.yaml")
        feishu_cfg = self.settings["feishu"]
        content_cfg = self.settings["content_flow"]
        mac_cfg = self.settings["mac_agent"]
        reminder_cfg = self.settings.get("feishu_reminder", {})
        obsidian_root = Path(mac_cfg.get("obsidian_root", "/home/ubuntu/obsidian-日记"))
        checklist_cfg = self.settings.get("daily_checklist", {})
        checklist_archive_root = Path(
            checklist_cfg.get("archive_root")
            or os.getenv("OPENCLAW_WEEKLY_ARCHIVE_ROOT", "")
            or "/home/ubuntu/obsidian-日记/Archieve"
        )
        feishu_service = FeishuService(
            feishu_cfg.get("mode", "local_markdown"),
            feishu_cfg["local_docs_dir"],
            feishu_cfg.get("webhook_url", ""),
            feishu_cfg.get("app_id", ""),
            feishu_cfg.get("app_secret", ""),
            feishu_cfg.get("api_base_url", ""),
            feishu_cfg.get("web_base_url", ""),
            feishu_cfg.get("folder_token", ""),
            feishu_cfg.get("knowledge_base_space_id", ""),
            feishu_cfg.get("knowledge_base_parent_node_token", ""),
            feishu_cfg.get("knowledge_base_obj_type", "docx"),
            feishu_cfg.get("knowledge_base_spaces", []),
        )
        content_flow_client = ContentFlowClient(content_cfg.get("base_url", ""), content_cfg.get("poll_interval_seconds", 0.2), content_cfg.get("poll_attempts", 10), workspace_root)
        mac_agent = MacAgentClient(mac_cfg.get("mode", "queue"), mac_cfg["queue_dir"], mac_cfg["obsidian_root"], mac_cfg["local_obsidian_root"])
        schedule_service = ScheduleService(self.settings.get("timezone", "Asia/Shanghai"), mac_agent, mac_cfg["obsidian_root"] if mac_cfg.get("mode") != "local" else mac_cfg["local_obsidian_root"])
        obsidian_daily_checklist_service = ObsidianDailyChecklistService(checklist_archive_root)
        reminder_service = ReminderService(
            reminder_cfg.get("enabled", False),
            reminder_cfg.get("command", "/usr/bin/python3"),
            reminder_cfg.get("script", "/home/ubuntu/openclaw-feishu-reminder/reminder.py"),
            reminder_cfg.get("env_files", []),
            reminder_cfg.get("timeout_seconds", 30),
            reminder_cfg.get("bitable_url", ""),
            reminder_cfg.get("config_paths", {}),
        )
        vlog_storage_service = VlogStorageService(workspace_root, self.settings.get("timezone", "Asia/Shanghai"))
        completion_guard = CompletionGuard(content_flow_client)
        self.router = TagRouter(
            workspace_root,
            self.settings.get("source", "qq"),
            self.settings.get("chat_type", "private"),
            self.settings.get("timezone", "Asia/Shanghai"),
            archive_service,
            rule_service,
            feishu_service,
            content_flow_client,
            schedule_service,
            reminder_service,
            obsidian_daily_checklist_service,
            vlog_storage_service,
            completion_guard,
        )
        # Stage 2 stays disabled unless a server-owned gateway is explicitly
        # supplied by an authenticated integration layer.
        self.stage2_gateway = stage2_gateway

    def process_text(
        self,
        text: str,
        *,
        source: str | None = None,
        chat_type: str | None = None,
        created_at: datetime | None = None,
        metadata: dict[str, Any] | None = None,
    ):
        tag, body, tag_metadata = parse_tag_message_with_metadata(text)
        message_metadata = dict(metadata or {})
        message_metadata.update(tag_metadata)
        return self.router.route(tag, body, created_at=created_at, source=source, chat_type=chat_type, metadata=message_metadata)

    def process_stage2(self, mode: str, payload: dict[str, Any]) -> dict[str, Any]:
        if self.stage2_gateway is None:
            raise RuntimeError("stage2_unavailable")
        return self.stage2_gateway.run(mode, payload)
