"""The Media Bot's human-facing Content OS modification entry.

This adapter deliberately sits before the generic Feishu Docx editor.  A
message with an explicit Feishu document target remains the existing document
editing workflow; only an explicit Content OS project request is turned into a
revision request and, after a human decision, a Mac task.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..models.message import Message
from ..models.task import TaskResult
from .content_os_change_requests import (
    confirm_change_request,
    create_change_request,
    find_open_change_request,
    note_change_request,
)
from .content_os_project_lifecycle import ContentOSContractError, read_project_state
from .content_os_queue import enqueue_confirmed_change


class ContentOSChangeRouterMixin:
    def _maybe_handle_content_os_change_request(self, message: Message) -> TaskResult | None:
        """Handle a project revision request, or return None for normal Docx edits."""

        raw = str(message.body or message.raw_text or "")
        doc_url, _source = self._extract_document_edit_target_url(message)
        if doc_url:
            return None
        project_signal = bool(re.search(r"(?:项目编号|项目ID|项目 id|Content\s*OS\s*项目)\s*[：:=]", raw, flags=re.I)) or "修改项目" in raw
        has_project_language = bool(re.search(r"Content\s*OS|内容项目", raw, flags=re.I))
        vault_root = self._content_os_vault_root()
        project_id = self._extract_content_os_project_id(raw, vault_root)
        if not project_signal and not (has_project_language and any(word in raw for word in ("修改", "改", "先记下", "现在修改"))):
            return None
        if not project_id:
            return TaskResult(
                ok=False,
                status="content_os_change_missing_project",
                reply=self._content_os_change_start_prompt(vault_root),
                task_id="",
            )
        try:
            state = read_project_state(vault_root, project_id)
        except ContentOSContractError:
            return TaskResult(
                ok=False,
                status="content_os_change_project_unavailable",
                reply="暂时找不到这个项目。请从机器人给出的项目名称中选择后再提交。",
                task_id="",
            )

        action = self._content_os_change_action(raw)
        try:
            request = self._content_os_change_request_from_message(vault_root, project_id, raw, message)
            if request is None:
                request = find_open_change_request(vault_root, project_id)
            if action == "note":
                if request is None:
                    return self._content_os_change_missing_fields_result(project_id, self._content_os_change_missing_fields(raw))
                noted = note_change_request(vault_root, request.change_request_id, noted_by=self._content_os_change_actor(message), now=message.created_at)
                return TaskResult(
                    ok=True,
                    status="content_os_change_noted",
                    reply="已先记下这条意见。项目阶段、当前版本、阻塞情况和执行安排都没有变化。",
                    task_id="",
                    extra={"content_os_change_request_id": noted.change_request_id, "project_id": project_id},
                )
            if action == "execute":
                if request is None:
                    return self._content_os_change_missing_fields_result(project_id, self._content_os_change_missing_fields(raw))
                if request.status == "pending_confirmation":
                    request = confirm_change_request(
                        vault_root,
                        request.change_request_id,
                        confirmed_by=self._content_os_change_actor(message),
                        now=message.created_at,
                    )
                task = enqueue_confirmed_change(
                    vault_root,
                    request.change_request_id,
                    task_type="revise_local_edit_artifacts",
                    inputs={
                        "project_overview_path": f"08_内容项目/{project_id}/00_项目总览.md",
                        "change_summary": {
                            "requested_location": request.requested_location,
                            "requested_change": request.requested_change,
                            "reason": request.reason,
                            "urgency": request.urgency,
                            "references": list(request.payload.get("references") or []),
                        },
                    },
                    expected_outputs=[
                        f"08_内容项目/{project_id}/04_script.md",
                        f"08_内容项目/{project_id}/05_storyboard.md",
                        f"08_内容项目/{project_id}/06_edit_decision_list.json",
                        f"90_Draft_Project/edit_handoff/{request.target_revision}/",
                    ],
                    allowed_actions=["apply_confirmed_revision"],
                    notes=["仅处理这张已确认修改单；不能自行改变项目阶段或切换剪辑方式。"],
                    tenant_id=str((message.metadata or {}).get("tenant_id") or "").strip() or None,
                    now=message.created_at,
                )
                sync_project_board = getattr(self, "_sync_content_os_feishu_project_board", None)
                if callable(sync_project_board):
                    sync_project_board(vault_root, project_id)
                return TaskResult(
                    ok=True,
                    status="content_os_change_execution_ready",
                    reply=(
                        "已确认并安排这次修改。项目阶段没有被自动改变；当前版本已更新，"
                        "等待剪辑处理完成后，再由负责人核验是否推进下一步。"
                    ),
                    task_id=task.task_id,
                    extra={"content_os_change_request_id": request.change_request_id, "project_id": project_id},
                )
            if request is None:
                missing = self._content_os_change_missing_fields(raw)
                if missing:
                    return self._content_os_change_missing_fields_result(project_id, missing)
                raise ContentOSContractError("修改单未创建")
            return TaskResult(
                ok=True,
                status="content_os_change_pending_confirmation",
                reply=(
                    f"我理解为：项目“{state.frontmatter.get('title') or '所选项目'}”的“{request.requested_location}”要改成“{request.requested_change}”，"
                    f"原因是“{request.reason}”。请回复“先记下”只保存意见，或回复“现在修改”确认开始处理。"
                ),
                task_id="",
                extra={"content_os_change_request_id": request.change_request_id, "project_id": project_id},
            )
        except ContentOSContractError:
            return TaskResult(
                ok=False,
                status="content_os_change_blocked",
                reply="这条项目修改暂时不能继续。请检查填写内容，或联系项目负责人确认后再试。",
                task_id="",
            )

    @staticmethod
    def _content_os_change_start_prompt(vault_root: Any) -> str:
        projects_root = Path(vault_root) / "08_内容项目"
        titles: list[str] = []
        if projects_root.exists():
            for project_dir in sorted((item for item in projects_root.iterdir() if item.is_dir()), key=lambda item: item.name):
                frontmatter_path = project_dir / "00_项目总览.md"
                try:
                    state = read_project_state(Path(vault_root), project_dir.name)
                except ContentOSContractError:
                    continue
                title = str(state.frontmatter.get("title") or "").strip()
                if title:
                    titles.append(title)
        choices = "\n".join(f"- {title}" for title in titles)
        return (
            "可以。请复制下面的填写单，在下一条消息里填完后发送：\n\n"
            "修改项目\n项目：<从下面选择项目名称>\n想改哪里：\n希望改成什么：\n为什么：\n是否很着急：是 / 否\n参考图片或说明：（可留空）"
            + (f"\n\n可选项目：\n{choices}" if choices else "")
        )

    def _content_os_change_request_from_message(self, vault_root: Any, project_id: str, raw: str, message: Message):
        """Create once when all five human-facing fields are present."""

        fields = self._content_os_change_fields(raw)
        if any(not fields[key] for key in ("requested_location", "requested_change", "reason", "urgency")):
            return None
        existing = find_open_change_request(vault_root, project_id)
        if existing is not None:
            return existing
        state = read_project_state(vault_root, project_id)
        return create_change_request(
            vault_root,
            project_id,
            requested_location=fields["requested_location"],
            requested_change=fields["requested_change"],
            reason=fields["reason"],
            urgency=fields["urgency"],
            submitted_by=self._content_os_change_actor(message),
            editor_backend=state.editor_backend,
            references=fields["references"],
            now=message.created_at,
        )

    def _content_os_change_fields(self, raw: str) -> dict[str, Any]:
        return {
            "requested_location": self._content_os_change_labeled_value(raw, "想改哪里", "改哪里", "修改位置", "位置"),
            "requested_change": self._content_os_change_labeled_value(raw, "希望改成什么", "改成什么", "希望修改", "改为", "修改内容"),
            "reason": self._content_os_change_labeled_value(raw, "为什么", "原因", "修改原因"),
            "urgency": self._content_os_change_urgency(raw),
            "references": self._content_os_change_references(raw),
        }

    @staticmethod
    def _content_os_change_labeled_value(raw: str, *labels: str) -> str:
        for label in labels:
            match = re.search(rf"(?:^|\n)\s*{re.escape(label)}\s*[：:]\s*(?P<value>[^\n\r]+)", raw, flags=re.I)
            if match and match.group("value").strip():
                return match.group("value").strip()
        return ""

    def _content_os_change_urgency(self, raw: str) -> str:
        value = self._content_os_change_labeled_value(raw, "是否很着急", "紧急程度", "紧急")
        if not value:
            return ""
        lowered = value.lower()
        if any(token in lowered for token in ("是", "紧急", "urgent", "很急")):
            return "urgent"
        if any(token in lowered for token in ("否", "不急", "普通", "normal")):
            return "normal"
        return ""

    def _content_os_change_references(self, raw: str) -> list[str]:
        value = self._content_os_change_labeled_value(raw, "参考图片", "参考说明", "参考")
        return [item.strip() for item in re.split(r"[，,；;]", value) if item.strip()] if value else []

    def _content_os_change_missing_fields(self, raw: str) -> list[str]:
        fields = self._content_os_change_fields(raw)
        labels = {
            "requested_location": "想改哪里",
            "requested_change": "希望改成什么",
            "reason": "为什么要改",
            "urgency": "是否很着急",
        }
        return [label for key, label in labels.items() if not fields[key]]

    @staticmethod
    def _content_os_change_missing_fields_result(project_id: str, missing: list[str]) -> TaskResult:
        readable = "、".join(missing) if missing else "项目修改说明"
        return TaskResult(
            ok=False,
            status="content_os_change_missing_fields",
            reply=f"这条项目修改还缺：{readable}。可选补充参考图片或说明。",
            task_id="",
        )

    @staticmethod
    def _content_os_change_action(raw: str) -> str:
        if "先记下" in raw:
            return "note"
        if any(phrase in raw for phrase in ("现在修改", "确认执行", "只改一小处")):
            return "execute"
        return "collect"

    @staticmethod
    def _content_os_change_actor(message: Message) -> str:
        metadata = message.metadata or {}
        for key in ("sender_name", "operator_name", "user_name", "sender_id"):
            value = str(metadata.get(key) or "").strip()
            if value:
                return value
        return "协作者"
