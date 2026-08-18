from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime
import os
from pathlib import Path
import re
from typing import Any

import yaml

from .adapters.mac_agent_client import MacAgentClient
from .models.task import TaskResult
from .router.tag_router import TagRouter
from .services.archive_service import ArchiveService
from .services.completion_guard import CompletionGuard
from .services.content_flow_client import ContentFlowClient
from .services.feishu_service import FeishuService
from .services.guidance_plan import CompletedPlanRecovery, GuidancePlanService, GuidancePlanStore, PendingContinuationRecovery
from .services.capability_registry import CAPABILITY_REGISTRY
from .services.content_os_feishu_project_board import FeishuBitableProjectBoardClient
from .services.obsidian_daily_checklist_service import ObsidianDailyChecklistService
from .services.reminder_service import ReminderService
from .services.rule_service import RuleService
from .services.schedule_service import ScheduleService
from .services.utils import parse_tag_message_with_metadata
from .services.vlog_storage_service import VlogStorageService
from .services.resource_owner_registry import ResourceOwnerRegistry
from .services.tenant_owned_resources import TenantOwnedResourceService
from .services.tenant_execution_context import bind_session_tenant_id
from .services.deepmath_resources import load_resource_config
from .services.deepmath_thinking_intake import DeepMathThinkingIntakeService
from .services.deepmath_people_runtime import load_people_capability_base_id


class OpenClawApp:
    def __init__(self, settings_path: str | Path):
        self.settings_path = Path(settings_path)
        self.settings = yaml.safe_load(self.settings_path.read_text(encoding="utf-8"))
        deepmath_cfg = self.settings.get("deepmath_ceo_thinking", {})
        self.deepmath_resource_config = load_resource_config(
            deepmath_cfg.get(
                "resource_config_path",
                "/home/ubuntu/selfmedia-tools/openclaw-tag-router/config/deepmath_ceo_thinking_resources.json",
            )
        )
        workspace_root = self.settings["workspace_root"]
        archive_service = ArchiveService(workspace_root)
        rule_service = RuleService(Path(workspace_root) / "rules" / "user_rules.yaml")
        feishu_cfg = self.settings["feishu"]
        content_cfg = self.settings["content_flow"]
        mac_cfg = self.settings["mac_agent"]
        reminder_cfg = self.settings.get("feishu_reminder", {})
        obsidian_root = Path(mac_cfg.get("obsidian_root", "/home/ubuntu/obsidian-日记"))
        checklist_cfg = self.settings.get("daily_checklist", {})
        checklist_archive_root = Path(checklist_cfg.get("weekly_archive_root") or "/home/ubuntu/obsidian-日记/Archieve")
        development_checklist_cfg = self.settings.get("development_checklist", {})
        development_checklist_archive_root = Path(development_checklist_cfg.get("weekly_archive_root") or "/home/ubuntu/obsidian-日记/Archieve")
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
        self.feishu_service = feishu_service
        content_flow_client = ContentFlowClient(content_cfg.get("base_url", ""), content_cfg.get("poll_interval_seconds", 0.2), content_cfg.get("poll_attempts", 10), workspace_root)
        mac_agent = MacAgentClient(mac_cfg.get("mode", "queue"), mac_cfg["queue_dir"], mac_cfg["obsidian_root"], mac_cfg["local_obsidian_root"])
        schedule_service = ScheduleService(self.settings.get("timezone", "Asia/Shanghai"), mac_agent, mac_cfg["obsidian_root"] if mac_cfg.get("mode") != "local" else mac_cfg["local_obsidian_root"])
        obsidian_daily_checklist_service = ObsidianDailyChecklistService(checklist_archive_root)
        obsidian_development_checklist_service = ObsidianDailyChecklistService(development_checklist_archive_root, heading_label="开发待办")
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
        owner_cfg = self.settings.get("resource_owner_registry", {})
        owner_registry = ResourceOwnerRegistry(
            Path(
                os.getenv("OPENCLAW_RESOURCE_OWNER_DB_PATH")
                or owner_cfg.get("path")
                or "/home/ubuntu/.openclaw/state/resource_owners.sqlite3"
            )
        )
        tenant_owned_resources = TenantOwnedResourceService(owner_registry)
        self.guidance_plan_service = GuidancePlanService(
            store=GuidancePlanStore(Path("/home/ubuntu/.openclaw/state/capability_guidance_plans"))
        )
        self.guidance_plan_service.purge_expired()
        deepmath_intake = None
        if bool(deepmath_cfg.get("enabled", False)):
            deepmath_intake = DeepMathThinkingIntakeService(
                str(deepmath_cfg.get("resource_config_path")),
                content_flow_client,
                people_capability_base_id=load_people_capability_base_id(self.settings_path),
                approval_state_path=str(deepmath_cfg.get("approval_state_path") or ""),
                approver_open_id=str(deepmath_cfg.get("approver_open_id") or ""),
            )
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
            obsidian_development_checklist_service,
            vlog_storage_service,
            completion_guard,
            self.settings.get("daily_journal", {}),
            self.guidance_plan_service,
            tenant_owned_resources,
            deepmath_intake,
        )
        board_cfg = self.settings.get("content_os_project_board", {})
        if bool(board_cfg.get("enabled", False)):
            client = FeishuBitableProjectBoardClient(
                feishu_service=feishu_service,
                base_token=str(board_cfg.get("base_token") or ""),
                table_name=str(board_cfg.get("table_name") or "00_Projects_项目看板"),
                tenant_owned_resources=tenant_owned_resources,
            )
            self.router.configure_content_os_feishu_project_board(client)
        else:
            self.router.configure_content_os_feishu_project_board(None)

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
        trusted_tenant_id = message_metadata.get("tenant_id")
        message_metadata.update(tag_metadata)
        if trusted_tenant_id is None:
            message_metadata.pop("tenant_id", None)
        else:
            message_metadata["tenant_id"] = trusted_tenant_id
        match = re.search(r"路径续接ID\s*[：:]\s*(capplan_[A-Za-z0-9_-]{16,128})", str(body or ""))
        guard = self.guidance_plan_service.submission_guard(match.group(1)) if match else nullcontext()
        with guard, bind_session_tenant_id(trusted_tenant_id):
            if preflight := self._guidance_plan_preflight(tag, body, submitted_text=text):
                return preflight
            result = self.router.route(tag, body, created_at=created_at, source=source, chat_type=chat_type, metadata=message_metadata)
            return self._append_guidance_continuation(tag, body, result)

    def process_capability_invocation(
        self,
        *,
        capability_id: str,
        variant_id: str,
        params: dict[str, Any],
        source: str | None = None,
        chat_type: str | None = None,
        metadata: dict[str, Any] | None = None,
    ):
        """Dispatch one validated structured invocation to its canonical handler."""

        definition = CAPABILITY_REGISTRY.require_valid_invocation(capability_id, variant_id, params)
        message_metadata = dict(metadata or {})
        body = CAPABILITY_REGISTRY.render_chat_body(capability_id, params)
        text_sections: list[str] = []
        for attachment in message_metadata.get("attachments") or []:
            if not isinstance(attachment, dict) or attachment.get("mime_type") not in {"text/plain", "text/markdown"}:
                continue
            try:
                content = Path(str(attachment["local_path"])).read_text(encoding="utf-8").strip()
            except (OSError, UnicodeDecodeError) as exc:
                raise ValueError("文本附件必须使用 UTF-8 编码且可读取。") from exc
            text_sections.append(f"文件：{attachment.get('file_name') or 'upload.txt'}\n内容：\n{content}")
        if text_sections:
            body = (body + "\n\nWeb 上传附件：\n" + "\n\n".join(text_sections)).strip()
        with bind_session_tenant_id(message_metadata.get("tenant_id")):
            return self.router.route(
                definition.label,
                body,
                source=source,
                chat_type=chat_type,
                metadata=message_metadata,
            )

    def _guidance_plan_preflight(self, tag: str, body: str, *, submitted_text: str | None = None):
        match = re.search(r"路径续接ID\s*[：:]\s*(capplan_[A-Za-z0-9_-]{16,128})", str(body or ""))
        if not match:
            return None
        copy_text = submitted_text if submitted_text is not None else f"【{tag}】\n{body}"
        try:
            recovery = self.guidance_plan_service.validate_submitted_step(match.group(1), tag=tag, text=copy_text)
        except Exception as exc:
            code = getattr(exc, "code", "guidance_plan_preflight_failed")
            return TaskResult(
                ok=False,
                status=code,
                reply=f"路径续接未执行（{code}）：{getattr(exc, 'message', '请重新使用【说明】生成完整指令。')}",
                task_id="",
            )
        if isinstance(recovery, CompletedPlanRecovery):
            receipt = recovery.receipt
            changed_note = (
                "\n\n检测到本次正文与原路径不同。以上是原执行结果；如需按新内容重新创作，请删除旧路径续接ID后重新发送。"
                if recovery.submitted_text_changed
                else ""
            )
            return TaskResult(
                ok=True,
                status="guidance_plan_completed_recovered",
                reply=f"该路径已完成，已恢复原执行结果：\n{receipt.get('reply') or '任务已完成。'}{changed_note}",
                task_id=str(receipt.get("task_id") or ""),
                local_path=str(receipt.get("local_path") or ""),
                feishu_doc=str(receipt.get("feishu_doc") or ""),
                extra={
                    "guidance_continuation": {
                        "ok": True,
                        "recovered": True,
                        "completed": True,
                        "submittedTextChanged": recovery.submitted_text_changed,
                        "guidancePlanId": recovery.guidance_plan_id,
                    }
                },
            )
        if isinstance(recovery, PendingContinuationRecovery):
            try:
                next_ready = self._compose_guidance_continuation(recovery.context)
            except Exception as exc:
                code, detail, failure_reply = self._guidance_continuation_failure(exc)
                return TaskResult(
                    ok=False,
                    status=code,
                    reply=(
                        f"【{recovery.submitted_label}】已完成，未重复执行。\n\n"
                        f"{failure_reply}"
                    ),
                    task_id="",
                    extra={"guidance_continuation": {"ok": False, "code": code, "detail": detail, "retried": True}},
                )
            return TaskResult(
                ok=True,
                status="guidance_plan_recovered",
                reply=(
                    f"【{recovery.submitted_label}】已完成，未重复执行；续接指令已重新生成。\n\n"
                    f"当前步骤【{CAPABILITY_REGISTRY.get(str(recovery.context.step['capabilityId'])).label}】，直接复制发送：\n{next_ready.copy_text}"
                ),
                task_id="",
                extra={
                    "guidance_continuation": {
                        "ok": True,
                        "recovered": True,
                        "retried": True,
                        "guidancePlanId": recovery.guidance_plan_id,
                        "submittedStepOrder": recovery.submitted_step_order,
                        "stepOrder": next_ready.step_order,
                    }
                },
            )
        if recovery is not None:
            return TaskResult(
                ok=True,
                status="guidance_plan_recovered",
                reply=(
                    f"路径已推进，无需重复执行【{recovery.submitted_label}】。\n\n"
                    f"当前步骤【{recovery.current_label}】，直接复制发送：\n{recovery.copy_text}"
                ),
                task_id="",
                extra={
                    "guidance_continuation": {
                        "ok": True,
                        "recovered": True,
                        "guidancePlanId": recovery.guidance_plan_id,
                        "submittedStepOrder": recovery.submitted_step_order,
                        "stepOrder": recovery.current_step_order,
                    }
                },
            )
        return None

    def _append_guidance_continuation(self, tag: str, body: str, result):
        """Advance a copy-ready plan only after the tagged handler has a real result."""

        match = re.search(r"路径续接ID\s*[：:]\s*(capplan_[A-Za-z0-9_-]{16,128})", str(body or ""))
        if not match:
            return result
        plan_id = match.group(1)
        if not bool(getattr(result, "ok", False)):
            return result
        try:
            step_order = self.guidance_plan_service.current_ready_step(plan_id)
            plan = self.guidance_plan_service.get_public_response(plan_id)
            planned = CAPABILITY_REGISTRY.get(str(plan["steps"][step_order - 1]["capabilityId"]))
            if planned is None:
                raise ValueError("引导计划引用的能力已不存在。")
            planned_tag = planned.label
            if tag != planned_tag:
                result.extra["guidance_continuation"] = {"ok": False, "code": "guidance_plan_tag_mismatch"}
                result.reply = f"{result.reply}\n\n路径续接未推进（guidance_plan_tag_mismatch）；请发送当前步骤【{planned_tag}】。"
                return result
            context = self.guidance_plan_service.bind_step_result(plan_id, step_order=step_order, task_result=result)
            if context is None:
                return result
            next_ready = self._compose_guidance_continuation(context)
        except Exception as exc:
            code, detail, failure_reply = self._guidance_continuation_failure(exc)
            result.extra["guidance_continuation"] = {"ok": False, "code": code, "detail": detail}
            result.reply = f"{result.reply}\n\n{failure_reply}"
            return result
        result.extra["guidance_continuation"] = {
            "ok": True,
            "guidancePlanId": next_ready.guidance_plan_id,
            "stepOrder": next_ready.step_order,
        }
        result.reply = f"{result.reply}\n\n下一步，直接复制发送：\n{next_ready.copy_text}"
        return result

    def _compose_guidance_continuation(self, context):
        from .services.capability_matcher import CapabilityMatcher

        step = CapabilityMatcher().compose_continuation(
            {
                "guidancePlanId": context.guidance_plan_id,
                "originalQuery": context.original_query,
                "step": context.step,
            },
            context.bindings,
        )
        return self.guidance_plan_service.finalize_next_step(
            context.guidance_plan_id,
            step_order=context.step_order,
            step=step,
        )

    @staticmethod
    def _guidance_continuation_failure(exc: Exception) -> tuple[str, str, str]:
        code = getattr(exc, "code", "guidance_continuation_failed")
        detail = str(getattr(exc, "message", "") or str(exc) or "底层错误未提供详情。").strip()
        reason = {
            "invalid_model_response": "能力匹配模型已返回结果，但续接指令未通过可执行指令契约校验。",
            "provider_unavailable": "续接模型调用未完成，未取得可供校验的结果。",
            "invalid_guidance_plan": "续接结果未通过路径计划校验。",
        }.get(code, "路径续接未能生成可执行的下一步指令。")
        action = "请重新发送同一条原指令；系统只会重试生成后续指令，不会重复执行已完成步骤。若再次失败，请携带错误代码和详情排查续接链路。"
        reply = "\n".join(
            (
                "后续可复制指令未生成。",
                f"错误代码：{code}",
                f"原因：{reason}",
                f"详情：{detail}",
                f"建议：{action}",
            )
        )
        return code, detail, reply
