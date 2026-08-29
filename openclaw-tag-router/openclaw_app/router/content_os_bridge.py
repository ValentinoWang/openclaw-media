from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import yaml

from ..models.message import Message
from ..services.archive_service import ArchiveService
from ..services.utils import cleanup_generated_file_duplicates, make_record_id
from .content_os_project_lifecycle import ContentOSContractError, read_project_state, set_project_reviewed_at, transition_project_status
from .content_os_projections import write_project_registry_projection
from .content_os_queue import RESULT_DIRECTORY, accept_mac_result, create_ready_task
from .tag_router_common import CONTENT_OS_SCRIPT_GENERATION_MODEL, CONTENT_OS_SCRIPT_GENERATION_THINKING


class ContentOSBridgeMixin:
    @staticmethod
    def _write_content_os_json_sidecar(path: Path, payload: dict[str, Any]) -> Path:
        sidecar = path.with_suffix(".json")
        sidecar.write_text(json.dumps({key: value for key, value in payload.items() if key != "ok"}, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
        return sidecar

    _CONTENT_OS_CREATOR_STAGE_LABELS = {
        "captured": "选题已收录",
        "planned": "创作准备中",
        "edit_ready": "等待开始剪辑",
        "editing": "剪辑中",
        "final_ready": "成片就绪",
        "published": "已发布",
    }

    @classmethod
    def _content_os_creator_stage_label(cls, status: str, *, fallback: str = "当前创作环节") -> str:
        return cls._CONTENT_OS_CREATOR_STAGE_LABELS.get(str(status or "").strip(), fallback)

    def _content_os_has_accepted_output_review(self, vault_root: Path, project_id: str) -> bool:
        """Return whether this revision has cloud-accepted terminal review evidence."""

        try:
            project_revision = read_project_state(vault_root, project_id).project_revision
        except ContentOSContractError:
            return False

        results_root = vault_root / RESULT_DIRECTORY
        if not results_root.exists():
            return False
        for result_path in sorted(results_root.glob("*.y*ml")):
            try:
                candidate = yaml.safe_load(result_path.read_text(encoding="utf-8")) or {}
            except (OSError, yaml.YAMLError):
                continue
            if not isinstance(candidate, dict):
                continue
            outputs = candidate.get("outputs")
            validation = candidate.get("validation")
            if not isinstance(outputs, dict) or not isinstance(validation, dict):
                continue
            output_review = str(outputs.get("output_review") or "").strip()
            if not output_review or Path(output_review).is_absolute() or ".." in Path(output_review).parts:
                continue
            result_revision = candidate.get("project_revision")
            if isinstance(result_revision, bool):
                continue
            try:
                revision_matches = int(result_revision) == project_revision
            except (TypeError, ValueError):
                revision_matches = False
            if not revision_matches:
                continue
            if (
                candidate.get("spec_version") == "content_os_v0.2"
                and candidate.get("doc_type") == "mac_result"
                and candidate.get("task_type") == "local_output_review"
                and candidate.get("completed_by") == "mac_openclaw"
                and candidate.get("status") == "done"
                and candidate.get("task_status") == "success"
                and candidate.get("project_id") == project_id
                and candidate.get("schema_version") == "output_review_result.v1"
                and candidate.get("accepted_by") == "cloud_openclaw"
                and bool(str(candidate.get("accepted_at") or "").strip())
                and validation.get("output_review_nonempty") is True
                and validation.get("metrics_json_parse_passed") is True
                and validation.get("result_yaml_parse_passed") is True
                and validation.get("human_final_ready_confirmation_required") is True
            ):
                return True
        return False

    def _content_os_transition_reply(self, *, current_status: str, target_status: str, advanced: bool) -> str:
        if advanced:
            return f"项目进度已更新：{self._content_os_creator_stage_label(target_status, fallback='下一创作环节')}。"
        return (
            f"项目进度暂未更新：当前处于{self._content_os_creator_stage_label(current_status)}，"
            f"暂不能标记为{self._content_os_creator_stage_label(target_status, fallback='下一创作环节')}。"
        )

    def _accept_content_os_mac_result(
        self,
        result: dict[str, Any],
        vault_root: Path | None = None,
        *,
        expected_tenant_id: str | None = None,
    ) -> dict[str, str]:
        """Receive a validated Mac result as evidence without touching project stage."""

        vault_root = vault_root or self._content_os_vault_root()
        accepted = accept_mac_result(vault_root, result, expected_tenant_id=expected_tenant_id)
        write_project_registry_projection(vault_root)
        sync_project_board = getattr(self, "_sync_content_os_feishu_project_board", None)
        if callable(sync_project_board):
            sync_project_board(vault_root, accepted.task.project_id)
        return {
            "status": "content_os_mac_result_accepted",
            "task_id": accepted.task.task_id,
            "project_id": accepted.task.project_id,
            "result_path": str(accepted.result_path),
        }

    def _maybe_create_content_os_project_from_inspiration(
        self,
        *,
        message: Message,
        result: dict[str, Any],
        record_text: str,
        doc_fs: dict[str, str],
        unified_index: dict[str, str],
    ) -> dict[str, Any]:
        raw = str(message.raw_text or message.body or "")
        local_project_path = self._extract_content_os_local_project_path(raw)
        if not self._inspiration_requests_content_os_project(raw):
            return {}
        if not self._content_os_cloud_markdown_enabled():
            return {}
        batch_note_path = self._extract_content_os_batch_note_path(raw)
        inbox_batch_path = self._extract_content_os_inbox_batch_path(raw)
        local_material_binding = "bound" if local_project_path or batch_note_path or inbox_batch_path else "unbound"

        vault_root = Path(os.environ.get("CONTENT_OS_VAULT_ROOT", "/home/ubuntu/obsidian-自媒体"))
        projects_root = vault_root / "08_内容项目"
        registries_root = vault_root / "90_索引与注册表"
        projects_root.mkdir(parents=True, exist_ok=True)
        registries_root.mkdir(parents=True, exist_ok=True)

        created_date = self._content_os_date(message.created_at)
        title = str(result.get("title") or result.get("theme") or self._content_os_path_name(local_project_path) or "未命名内容").strip()
        project_slug_source = self._content_os_project_slug_source(local_project_path, title)
        project_id = self._unique_content_os_project_id(projects_root, created_date, project_slug_source)
        idea_id = self._next_content_os_id(registries_root / "idea_registry.md", f"idea_{created_date}_")
        task = None
        project_dir = projects_root / project_id
        project_dir.mkdir(parents=True, exist_ok=True)
        mac_task_status = "ready" if local_material_binding == "bound" else "not_created"

        platform = str(result.get("platform") or self._extract_labeled_value(raw, "平台") or "").strip()
        account = str(self._extract_labeled_value(raw, "账号") or "").strip()
        emotion = str(self._extract_labeled_value(raw, "情绪") or "").strip()
        theme = str(result.get("theme") or title).strip()
        track = str(result.get("track") or "").strip()
        content_type = str(result.get("content_type") or "短视频").strip()
        inspiration_doc = str(doc_fs.get("doc") or "")
        inspiration_record_id = str(unified_index.get("record_id") or "")

        files = {
            "00_项目总览.md": self._render_content_os_project_index(
                project_id=project_id,
                idea_id=idea_id,
                title=title,
                theme=theme,
                local_project_path=local_project_path,
                batch_note_path=batch_note_path,
                inbox_batch_path=inbox_batch_path,
                local_material_binding=local_material_binding,
                mac_task_status=mac_task_status,
                platform=platform,
                content_type=content_type,
                created_date=created_date,
                account=account,
                inspiration_doc=inspiration_doc,
                inspiration_record_id=inspiration_record_id,
            ),
            "01_idea_card.md": self._render_content_os_idea_card(
                idea_id=idea_id,
                project_id=project_id,
                title=title,
                theme=theme,
                result=result,
                platform=platform,
                account=account,
                emotion=emotion,
                created_date=created_date,
                source_text=raw,
                inspiration_doc=inspiration_doc,
                inspiration_record_id=inspiration_record_id,
            ),
            "02_project_brief.md": self._render_content_os_project_brief(
                project_id=project_id,
                idea_id=idea_id,
                title=title,
                theme=theme,
                local_project_path=local_project_path,
                batch_note_path=batch_note_path,
                inbox_batch_path=inbox_batch_path,
                local_material_binding=local_material_binding,
                mac_task_status=mac_task_status,
                result=result,
                platform=platform,
                account=account,
                emotion=emotion,
                track=track,
                content_type=content_type,
                created_date=created_date,
            ),
            "04_script.md": self._render_content_os_initial_script(
                project_id=project_id,
                idea_id=idea_id,
                title=title,
                result=result,
                platform=platform,
                created_date=created_date,
                record_text=record_text,
            ),
        }
        for filename, content in files.items():
            self._write_text_if_absent(project_dir / filename, content)
        self._write_content_os_json_sidecar(project_dir / "04_script.md", result)

        transition_project_status(
            vault_root,
            project_id,
            to_status="planned",
            actor="cloud_openclaw",
            reason="已生成项目说明、创作要求和当前脚本",
            evidence={"01_idea_card.md", "02_project_brief.md", "04_script.md"},
            now=message.created_at,
        )

        if local_material_binding == "bound":
            task = create_ready_task(
                vault_root,
                project_id,
                task_type="local_material_match",
                project_revision=1,
                change_request_id="",
                editor_backend="handoff_pack",
                inputs={
                    "project_overview_path": f"08_内容项目/{project_id}/00_项目总览.md",
                    "project_brief_path": f"08_内容项目/{project_id}/02_project_brief.md",
                    "script_path": f"08_内容项目/{project_id}/04_script.md",
                    "batch_note_path": batch_note_path,
                    "inbox_batch_path": inbox_batch_path,
                    "local_project_hint": self._content_os_path_name(local_project_path),
                    "local_project_path": local_project_path,
                },
                expected_outputs=[
                    f"08_内容项目/{project_id}/03_material_match_report.md",
                    f"08_内容项目/{project_id}/05_storyboard.md",
                    f"08_内容项目/{project_id}/06_edit_decision_list.json",
                    f"08_内容项目/{project_id}/08_local_assets.md",
                ],
                allowed_actions=["analyze_project", "match_materials_to_brief", "generate_storyboard_edl", "write_local_assets"],
                notes=["Mac 只回传证据和本地负责的产物，不能推进项目阶段。"],
                tenant_id=str((message.metadata or {}).get("tenant_id") or "").strip() or None,
                now=message.created_at,
            )

        self._append_registry_row(
            registries_root / "idea_registry.md",
            header="# Idea Registry\n\n| idea_id | 标题/方向 | 来源 | status | project_id | 创建时间 |\n| --- | --- | --- | --- | --- | --- |\n",
            key=idea_id,
            row=f"| {idea_id} | {self._md_cell(title)} | cloud_openclaw | selected | {project_id} | {created_date} |",
        )
        write_project_registry_projection(vault_root)
        sync_project_board = getattr(self, "_sync_content_os_feishu_project_board", None)
        if callable(sync_project_board):
            sync_project_board(vault_root, project_id)

        response = {
            "project_id": project_id,
            "idea_id": idea_id,
            "project_path": str(project_dir),
            "local_material_binding": local_material_binding,
        }
        if task is not None:
            response.update({"task_id": task.task_id, "task_path": str(task.path)})
        return response
    def _maybe_write_content_os_creation_output(self, message: Message, parsed: dict[str, Any], reply: str) -> dict[str, Any]:
        vault_root = self._content_os_vault_root()
        project_id = self._extract_content_os_project_id(message.raw_text, vault_root)
        if not project_id:
            return {}
        if not self._content_os_cloud_markdown_enabled():
            return {}
        return self._write_content_os_creation_output_to_project(message, parsed, reply, project_id, vault_root)
    def _write_content_os_creation_output_to_project(self, message: Message, parsed: dict[str, Any], reply: str, project_id: str, vault_root: Path | None = None) -> dict[str, Any]:
        vault_root = vault_root or self._content_os_vault_root()
        project_dir = self._content_os_project_dir(project_id, vault_root)
        if not project_dir.exists():
            return {"reply": f"Content OS 未写入：项目不存在 {project_id}", "project_id": project_id, "status": "blocked_missing_project"}
        created_date = self._content_os_date(message.created_at)
        idea_id = self._content_os_project_idea_id(project_id, vault_root)
        doc_link = str(parsed.get("doc_link") or "")
        record_id = str(parsed.get("creation_record_id") or parsed.get("record_id") or "")
        script_content = self._render_content_os_creation_script_section(message, parsed, reply, doc_link, record_id)
        publish_content = self._render_content_os_publish_pack_section(message, parsed, reply, doc_link, record_id)
        self._upsert_content_os_auto_section(
            project_dir / "04_script.md",
            frontmatter={
                "spec_version": "content_os_v0.2",
                "doc_type": "script",
                "project_id": project_id,
                "idea_id": idea_id,
                "evidence_status": "current",
                "writer_agent": "cloud_openclaw",
                "owner_agent": "cloud_openclaw",
                "next_owner": "human",
                "generation_model": CONTENT_OS_SCRIPT_GENERATION_MODEL,
                "generation_thinking": CONTENT_OS_SCRIPT_GENERATION_THINKING,
                "created_at": created_date,
            },
            section_id="cloud_creation",
            title="云端创作稿",
            content=script_content,
        )
        self._write_content_os_json_sidecar(project_dir / "04_script.md", parsed)
        self._upsert_content_os_auto_section(
            project_dir / "09_publish_pack.md",
            frontmatter={
                "spec_version": "content_os_v0.2",
                "doc_type": "publish_pack",
                "project_id": project_id,
                "idea_id": idea_id,
                "evidence_status": "draft",
                "writer_agent": "cloud_openclaw",
                "owner_agent": "cloud_openclaw",
                "next_owner": "human",
                "created_at": created_date,
            },
            section_id="cloud_creation_publish_pack",
            title="云端发布包",
            content=publish_content,
        )
        reply_line = f"Content OS 已写入：08_内容项目/{project_id}/04_script.md、09_publish_pack.md"
        reply_line = f"{reply_line}\n项目阶段不会因单份创作稿或发布稿自动改变。"
        return {"project_id": project_id, "script_path": str(project_dir / "04_script.md"), "publish_pack_path": str(project_dir / "09_publish_pack.md"), "reply": reply_line}
    def _maybe_create_content_os_project_from_creation(self, message: Message, parsed: dict[str, Any], reply: str) -> dict[str, Any]:
        if not self._creation_requests_content_os_project(message.raw_text):
            return {}
        if not self._content_os_cloud_markdown_enabled():
            return {}
        project_message = Message(
            entry_tag=message.entry_tag,
            raw_text=f"目标：生成项目包和初稿脚本。\n{message.raw_text}",
            body=message.body,
            source=message.source,
            chat_type=message.chat_type,
            created_at=message.created_at,
            metadata=message.metadata,
        )
        draft = parsed.get("draft") if isinstance(parsed.get("draft"), dict) else {}
        request = parsed.get("request") if isinstance(parsed.get("request"), dict) else {}
        if not request and isinstance(parsed.get("creation_request"), dict):
            request = parsed.get("creation_request") or {}
        title = str(draft.get("title") or request.get("topic") or request.get("主题") or message.body or "未命名创作").strip()
        material_requirements: list[Any] = []
        if isinstance(draft.get("production_checklist"), list):
            material_requirements.extend(draft.get("production_checklist") or [])
        report = draft.get("creator_report") if isinstance(draft.get("creator_report"), dict) else {}
        checklist = report.get("material_checklist") if isinstance(report.get("material_checklist"), dict) else {}
        for key in ("must_have", "better_to_have"):
            values = checklist.get(key)
            if isinstance(values, list):
                material_requirements.extend(values)
        project = self._maybe_create_content_os_project_from_inspiration(
            message=project_message,
            result={
                "title": title,
                "theme": request.get("topic") or request.get("主题") or title,
                "platform": request.get("platform") or request.get("平台") or "",
                "content_type": request.get("content_type") or request.get("内容类型") or "视频",
                "track": request.get("track") or request.get("赛道") or "",
                "material_requirements": material_requirements,
                "publishable_formats": [request.get("content_type") or request.get("内容类型") or "视频"],
                "script_outline": draft.get("inspiration") or draft.get("production_checklist") or [],
                "risks": draft.get("risks_or_missing_info") or [],
                "hook_options": draft.get("hook_3s") or draft.get("hook_options") or [],
                "title_options": draft.get("script_options") or draft.get("title_options") or [],
                "final_copy": draft.get("final_copy") or "",
                "voiceover": draft.get("voiceover") or "",
                "account_profile": request.get("account_profile") or draft.get("account_profile") or {},
                "topic_strategy": draft.get("topic_strategy") or {},
                "creative_direction": draft.get("creative_direction") or draft.get("inspiration") or "",
                "next_actions": draft.get("next_actions") or [],
            },
            record_text=reply or str(parsed.get("reply") or message.raw_text or ""),
            doc_fs={"doc": str(parsed.get("doc_link") or "")},
            unified_index={"record_id": str(parsed.get("creation_record_id") or parsed.get("record_id") or "")},
        )
        project_id = str(project.get("project_id") or "")
        if not project_id:
            return project
        creation_output = self._write_content_os_creation_output_to_project(message, parsed, reply, project_id, self._content_os_vault_root())
        project.update(
            {
                "status": "content_os_project_written",
                "script_path": creation_output.get("script_path", ""),
                "publish_pack_path": creation_output.get("publish_pack_path", ""),
                "creation_output": creation_output,
                "reply": self._creation_content_os_project_reply(project, creation_output),
            }
        )
        return project
    def _creation_content_os_project_reply(self, project: dict[str, Any], creation_output: dict[str, Any]) -> str:
        lines = ["创作项目已创建。"]
        if creation_output.get("reply"):
            lines.append("创作内容已同步到项目档案。")
        if project.get("task_path"):
            if project.get("local_material_binding") == "bound":
                lines.append("本地素材匹配任务已创建。Mac 任务已登记。")
            else:
                lines.append("本地素材匹配任务已创建。")
        else:
            lines.append("Mac 素材未绑定。下一步：如需匹配本地素材，请补充素材位置。")
        return "\n".join(lines)
    def _write_standalone_creation_output(self, message: Message, parsed: dict[str, Any], reply: str) -> dict[str, Any]:
        if not self._content_os_cloud_markdown_enabled():
            return {}
        vault_root = self._content_os_vault_root()
        if self._extract_content_os_project_id(message.raw_text, vault_root):
            return {}
        scripts_root = vault_root / "03_脚本生产"
        scripts_root.mkdir(parents=True, exist_ok=True)
        created_date = self._content_os_date(message.created_at)
        draft = parsed.get("draft") if isinstance(parsed.get("draft"), dict) else {}
        request = parsed.get("creation_request") if isinstance(parsed.get("creation_request"), dict) else {}
        if not request:
            request = parsed.get("request") if isinstance(parsed.get("request"), dict) else {}
        title = str(
            draft.get("title")
            or parsed.get("title")
            or request.get("topic")
            or request.get("主题")
            or "未命名创作"
        ).strip()
        record_id = str(parsed.get("creation_record_id") or parsed.get("record_id") or "").strip()
        source_key = record_id or make_record_id(message.raw_text)
        script_path = scripts_root / f"{created_date}_{self._content_os_slug(source_key, limit=28)}_{self._content_os_slug(title, limit=48)}.md"
        doc_link = str(parsed.get("doc_link") or "")
        frontmatter = {
            "doc_type": "creation_script",
            "source": message.source,
            "entry_tag": message.entry_tag,
            "created_at": created_date,
            "status": "cloud_draft_ready",
            "title": title,
            "creation_record_id": record_id,
            "feishu_doc": doc_link,
            "writer_agent": "cloud_openclaw",
            "owner_agent": "cloud_openclaw",
            "generation_model": CONTENT_OS_SCRIPT_GENERATION_MODEL,
            "generation_thinking": CONTENT_OS_SCRIPT_GENERATION_THINKING,
        }
        sections = [
            (
                "来源",
                "\n".join(
                    [
                        f"- 飞书标签：`{message.entry_tag}`",
                        f"- 创作记录 ID：`{record_id or '未记录'}`",
                        f"- 飞书创作文档：{doc_link or '未记录'}",
                    ]
                ),
            ),
            ("原始输入", f"```text\n{message.raw_text[:3000]}\n```"),
            ("生成稿", f"```text\n{(reply or parsed.get('reply') or '未记录')[:8000]}\n```"),
        ]
        script_path.write_text(ArchiveService.render_markdown(frontmatter, title, sections), encoding="utf-8")
        self._write_content_os_json_sidecar(script_path, parsed)
        cleanup_generated_file_duplicates(script_path)
        rel_path = f"03_脚本生产/{script_path.name}"
        return {"status": "standalone_written", "script_path": str(script_path), "reply": f"创作稿已写入：{rel_path}"}
    def _maybe_apply_content_os_work_acceptance(self, message: Message, verdict: str, result: dict[str, Any], items: list[dict[str, str]]) -> dict[str, Any]:
        vault_root = self._content_os_vault_root()
        project_id = self._extract_content_os_project_id(message.raw_text, vault_root)
        if not project_id:
            return {}
        current_status = self._content_os_project_status(project_id, vault_root)
        if not current_status:
            return {"project_id": project_id, "reply": f"项目进度暂未更新：未找到项目或项目资料不完整（{project_id}）。"}
        if verdict != "通过":
            return {"project_id": project_id, "reply": f"项目暂不标记成片就绪：本次作品验收结果为{verdict}。"}
        target_status = self._extract_labeled_value(message.raw_text, "目标状态") or self._extract_labeled_value(message.raw_text, "to")
        if target_status:
            target_status = re.split(r"\s+", target_status.strip(), maxsplit=1)[0]
        if not target_status:
            return {
                "project_id": project_id,
                "reply": f"项目进度暂未更新：当前处于{self._content_os_creator_stage_label(current_status)}，请明确下一步创作安排。",
            }
        if target_status == "final_ready":
            if current_status != "editing":
                return {
                    "project_id": project_id,
                    "from": current_status,
                    "to": target_status,
                    "reply": self._content_os_transition_reply(
                        current_status=current_status,
                        target_status=target_status,
                        advanced=False,
                    ),
                }
            if not self._content_os_has_accepted_output_review(vault_root, project_id):
                return {
                    "project_id": project_id,
                    "from": current_status,
                    "to": target_status,
                    "reply": "项目仍在剪辑中：请先回传并接收本次成片质检结果，再确认标记成片就绪。",
                }
            receipt = message.metadata.get("content_os_acceptance") if isinstance(message.metadata, dict) else None
            if not isinstance(receipt, dict):
                return {
                    "project_id": project_id,
                    "from": current_status,
                    "to": target_status,
                    "reply": "项目暂不标记成片就绪：缺少结构化验收收据，请提供真实成片路径、验收证据和人工确认。",
                }
            human_selected = receipt.get("human_final_selected") is True
            review_evidence = receipt.get("output_review_evidence_exists") is True
            output_video_path = str(receipt.get("output_video_path") or "").strip()
            video_path = Path(output_video_path).expanduser() if output_video_path else None
            video_exists = bool(
                video_path
                and video_path.is_absolute()
                and video_path.is_file()
                and video_path.stat().st_size > 0
                and video_path.suffix.lower() in {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm"}
            )
            evidence = set()
            if human_selected:
                evidence.add("human_final_selected")
            if review_evidence:
                evidence.add("output_review_evidence_exists")
            if video_exists:
                evidence.add("output_video_exists")
            required_evidence = {"human_final_selected", "output_review_evidence_exists", "output_video_exists"}
            if evidence != required_evidence:
                return {
                    "project_id": project_id,
                    "from": current_status,
                    "to": target_status,
                    "reply": "项目暂不标记成片就绪：结构化收据中的人工确认、复核证据或真实视频文件不完整。",
                }
        else:
            evidence = set()
        status_reply = self._maybe_advance_content_os_status(
            project_id=project_id,
            from_status=current_status,
            to_status=target_status,
            actor="human",
            evidence=evidence,
            reason="【作品验收】通过",
            vault_root=vault_root,
        )
        return {
            "project_id": project_id,
            "from": current_status,
            "to": target_status,
            "reply": self._content_os_transition_reply(
                current_status=current_status,
                target_status=target_status,
                advanced=status_reply,
            ),
        }
    def _maybe_write_content_os_data_review(self, message: Message, parsed: dict[str, Any], reply: str) -> dict[str, Any]:
        vault_root = self._content_os_vault_root()
        project_id = self._extract_content_os_project_id(message.raw_text, vault_root)
        if not project_id:
            return {}
        project_dir = self._content_os_project_dir(project_id, vault_root)
        if not project_dir.exists():
            return {"project_id": project_id, "reply": f"复盘未写入项目档案：未找到项目（{project_id}）。"}
        review_path = project_dir / "10_review.md"
        idea_id = self._content_os_project_idea_id(project_id, vault_root)
        self._upsert_content_os_auto_section(
            review_path,
            frontmatter={
                "spec_version": "content_os_v0.2",
                "doc_type": "review",
                "project_id": project_id,
                "idea_id": idea_id,
                "evidence_status": "reviewed",
                "writer_agent": "cloud_openclaw",
                "owner_agent": "cloud_openclaw",
                "next_owner": "done",
                "created_at": self._content_os_date(message.created_at),
            },
            section_id="data_review",
            title="数据复盘",
            content=self._render_content_os_data_review_section(message, parsed, reply),
        )
        self._write_content_os_json_sidecar(review_path, parsed)
        review_id = str(parsed.get("record_id") or parsed.get("review_id") or f"review_{self._content_os_date(message.created_at)}_{make_record_id(message.raw_text)[:6]}")
        self._append_registry_row(
            vault_root / "90_索引与注册表" / "review_registry.md",
            header="# Review Registry\n\n| review_id | project_id | 平台 | 复盘节点 | 文档 | 创建时间 |\n| --- | --- | --- | --- | --- | --- |\n",
            key=review_id,
            row=f"| {review_id} | {project_id} | {self._md_cell(self._extract_labeled_value(message.raw_text, '平台') or '未指定')} | {self._md_cell(self._extract_labeled_value(message.raw_text, '复盘节点') or '未指定')} | `08_内容项目/{project_id}/10_review.md` | {self._content_os_date(message.created_at)} |",
        )
        set_project_reviewed_at(
            vault_root,
            project_id,
            reviewed_at=message.created_at.isoformat(timespec="seconds"),
            now=message.created_at,
        )
        current_status = self._content_os_project_status(project_id, vault_root)
        status_lines = []
        if current_status == "final_ready" and re.search(r"https?://|post_id|作品链接|发布链接", message.raw_text):
            advanced = self._maybe_advance_content_os_status(
                project_id=project_id,
                from_status="final_ready",
                to_status="published",
                actor="human",
                evidence={"post_url"},
                reason="【数据复盘】包含发布链接或作品 ID",
                vault_root=vault_root,
            )
            if advanced:
                status_lines.append(self._content_os_transition_reply(
                    current_status="final_ready",
                    target_status="published",
                    advanced=True,
                ))
                current_status = "published"
        reply_line = f"复盘已写入项目档案：08_内容项目/{project_id}/10_review.md"
        if status_lines:
            reply_line = reply_line + "\n" + "\n".join(status_lines)
        elif current_status != "published":
            reply_line = f"{reply_line}\n项目当前处于{self._content_os_creator_stage_label(current_status)}；发布后可继续记录发布效果。"
        return {"project_id": project_id, "review_path": str(review_path), "reply": reply_line}
