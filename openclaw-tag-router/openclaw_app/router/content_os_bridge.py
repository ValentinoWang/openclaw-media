from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from ..models.message import Message
from ..services.utils import make_record_id
from .tag_router_common import CONTENT_OS_SCRIPT_GENERATION_MODEL, CONTENT_OS_SCRIPT_GENERATION_THINKING


class ContentOSBridgeMixin:
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
        if not local_project_path:
            return {}
        if not self._inspiration_requests_content_os_project(raw):
            return {}

        vault_root = Path(os.environ.get("CONTENT_OS_VAULT_ROOT", "/home/ubuntu/obsidian-media"))
        projects_root = vault_root / "08_内容项目"
        registries_root = vault_root / "90_索引与注册表"
        task_ready_root = vault_root / "98_Agent任务队列" / "01_cloud_to_mac_ready"
        projects_root.mkdir(parents=True, exist_ok=True)
        registries_root.mkdir(parents=True, exist_ok=True)
        task_ready_root.mkdir(parents=True, exist_ok=True)

        created_date = self._content_os_date(message.created_at)
        title = str(result.get("title") or result.get("theme") or self._content_os_path_name(local_project_path) or "未命名内容").strip()
        project_slug_source = self._content_os_project_slug_source(local_project_path, title)
        project_id = self._unique_content_os_project_id(projects_root, created_date, project_slug_source)
        idea_id = self._next_content_os_id(registries_root / "idea_registry.md", f"idea_{created_date}_")
        task_id = self._next_content_os_task_id(vault_root, created_date)
        project_dir = projects_root / project_id
        project_dir.mkdir(parents=True, exist_ok=True)

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

        task_path = task_ready_root / f"{task_id}_material_match.yaml"
        task_content = self._render_content_os_material_match_task(
            task_id=task_id,
            project_id=project_id,
            idea_id=idea_id,
            local_project_path=local_project_path,
        )
        self._write_text_if_absent(task_path, task_content)

        self._append_registry_row(
            registries_root / "idea_registry.md",
            header="# Idea Registry\n\n| idea_id | 标题/方向 | 来源 | status | project_id | 创建时间 |\n| --- | --- | --- | --- | --- | --- |\n",
            key=idea_id,
            row=f"| {idea_id} | {self._md_cell(title)} | cloud_openclaw | brief_ready | {project_id} | {created_date} |",
        )
        self._append_registry_row(
            registries_root / "project_registry.md",
            header="# Project Registry\n\n| project_id | 标题/主题 | status | 本地项目路径 | idea_id | post_id | review_id |\n| --- | --- | --- | --- | --- | --- | --- |\n",
            key=project_id,
            row=f"| {project_id} | {self._md_cell(theme or title)} | brief_ready | `{local_project_path}` | {idea_id} |  |  |",
        )
        self._append_registry_row(
            registries_root / "task_registry.md",
            header="# Task Registry\n\n| task_id | project_id | task_type | status | owner | result_path | 下一步 |\n| --- | --- | --- | --- | --- | --- | --- |\n",
            key=task_id,
            row=f"| {task_id} | {project_id} | local_material_match | ready | mac_openclaw |  | Mac 读取 task，分析本地素材并回写 result |",
        )

        return {
            "project_id": project_id,
            "idea_id": idea_id,
            "task_id": task_id,
            "project_path": str(project_dir),
            "task_path": str(task_path),
        }
    def _maybe_write_content_os_creation_output(self, message: Message, parsed: dict[str, Any], reply: str) -> dict[str, Any]:
        vault_root = self._content_os_vault_root()
        project_id = self._extract_content_os_project_id(message.raw_text, vault_root)
        if not project_id:
            return {}
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
                "spec_version": "content_os_v0.1",
                "doc_type": "script",
                "project_id": project_id,
                "idea_id": idea_id,
                "status": "cloud_draft_ready",
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
        self._upsert_content_os_auto_section(
            project_dir / "09_publish_pack.md",
            frontmatter={
                "spec_version": "content_os_v0.1",
                "doc_type": "publish_pack",
                "project_id": project_id,
                "idea_id": idea_id,
                "status": "draft",
                "writer_agent": "cloud_openclaw",
                "owner_agent": "cloud_openclaw",
                "next_owner": "human",
                "created_at": created_date,
            },
            section_id="cloud_creation_publish_pack",
            title="云端发布包",
            content=publish_content,
        )
        status_reply = self._maybe_advance_content_os_status(
            project_id=project_id,
            from_status=self._content_os_project_status(project_id, vault_root),
            to_status="script_publish_pack_draft_ready",
            actor="cloud_openclaw",
            evidence={"04_script.md", "09_publish_pack.md", "result_yaml_valid"},
            reason="【创作】写入 04_script.md 和 09_publish_pack.md",
            vault_root=vault_root,
        )
        reply_line = f"Content OS 已写入：08_内容项目/{project_id}/04_script.md、09_publish_pack.md"
        if status_reply:
            reply_line = f"{reply_line}\n{status_reply}"
        return {"project_id": project_id, "script_path": str(project_dir / "04_script.md"), "publish_pack_path": str(project_dir / "09_publish_pack.md"), "reply": reply_line}
    def _maybe_create_content_os_task_from_recreation(self, message: Message, unified_index: dict[str, str], fs: dict[str, str]) -> dict[str, Any]:
        text = str(message.raw_text or message.body or "")
        if not any(signal in text for signal in ("Mac", "本地素材", "素材匹配", "Storyboard", "EDL", "分镜", "本地处理")):
            return {}
        vault_root = self._content_os_vault_root()
        project_id = self._extract_content_os_project_id(text, vault_root)
        if not project_id:
            return {}
        project_dir = self._content_os_project_dir(project_id, vault_root)
        if not project_dir.exists():
            return {"project_id": project_id, "status": "blocked_missing_project"}
        existing = self._find_content_os_ready_task(vault_root, project_id, "local_material_match")
        if existing:
            return {"project_id": project_id, "task_id": existing.stem, "task_path": str(existing), "status": "ready_task_exists"}
        local_project_path = self._extract_content_os_local_project_path(text) or self._content_os_project_local_path(project_id, vault_root)
        if not local_project_path:
            return {"project_id": project_id, "status": "blocked_missing_local_project_path"}
        idea_id = self._content_os_project_idea_id(project_id, vault_root)
        task_id = self._next_content_os_task_id(vault_root, self._content_os_date(message.created_at))
        task_root = vault_root / "98_Agent任务队列" / "01_cloud_to_mac_ready"
        task_root.mkdir(parents=True, exist_ok=True)
        task_path = task_root / f"{task_id}_material_match.yaml"
        task_path.write_text(
            self._render_content_os_material_match_task(task_id=task_id, project_id=project_id, idea_id=idea_id, local_project_path=local_project_path).rstrip() + "\n",
            encoding="utf-8",
        )
        self._append_registry_row(
            vault_root / "90_索引与注册表" / "task_registry.md",
            header="# Task Registry\n\n| task_id | project_id | task_type | status | owner | result_path | 下一步 |\n| --- | --- | --- | --- | --- | --- | --- |\n",
            key=task_id,
            row=f"| {task_id} | {project_id} | local_material_match | ready | mac_openclaw |  | Mac 读取 task，分析本地素材并回写 result |",
        )
        return {"project_id": project_id, "task_id": task_id, "task_path": str(task_path), "status": "created"}
    def _maybe_apply_content_os_work_acceptance(self, message: Message, verdict: str, result: dict[str, Any], items: list[dict[str, str]]) -> dict[str, Any]:
        vault_root = self._content_os_vault_root()
        project_id = self._extract_content_os_project_id(message.raw_text, vault_root)
        if not project_id:
            return {}
        current_status = self._content_os_project_status(project_id, vault_root)
        if not current_status:
            return {"project_id": project_id, "reply": f"Content OS 状态未推进：项目不存在或缺少状态 {project_id}"}
        if verdict != "通过":
            return {"project_id": project_id, "reply": f"Content OS 状态未推进：验收结果为 {verdict}"}
        target_status = self._extract_labeled_value(message.raw_text, "目标状态") or self._extract_labeled_value(message.raw_text, "to")
        if target_status:
            target_status = re.split(r"\s+", target_status.strip(), maxsplit=1)[0]
        if not target_status and current_status == "output_reviewed":
            target_status = "final_ready"
        if not target_status:
            return {"project_id": project_id, "reply": f"Content OS 状态未推进：当前状态 {current_status} 没有可自动推断的下一状态"}
        evidence = {"human_final_selected"}
        if re.search(r"(/Users/|\.mp4|\.mov|Final|final|成片路径|导出路径|视频路径)", message.raw_text):
            evidence.add("output_video_exists")
        status_reply = self._maybe_advance_content_os_status(
            project_id=project_id,
            from_status=current_status,
            to_status=target_status,
            actor="human",
            evidence=evidence,
            reason="【作品验收】通过",
            vault_root=vault_root,
        )
        return {"project_id": project_id, "from": current_status, "to": target_status, "reply": status_reply or f"Content OS 状态未推进：{current_status} -> {target_status} 缺少状态机许可或证据"}
    def _maybe_write_content_os_data_review(self, message: Message, parsed: dict[str, Any], reply: str) -> dict[str, Any]:
        vault_root = self._content_os_vault_root()
        project_id = self._extract_content_os_project_id(message.raw_text, vault_root)
        if not project_id:
            return {}
        project_dir = self._content_os_project_dir(project_id, vault_root)
        if not project_dir.exists():
            return {"project_id": project_id, "reply": f"Content OS 复盘未写入：项目不存在 {project_id}"}
        review_path = project_dir / "10_review.md"
        idea_id = self._content_os_project_idea_id(project_id, vault_root)
        self._upsert_content_os_auto_section(
            review_path,
            frontmatter={
                "spec_version": "content_os_v0.1",
                "doc_type": "review",
                "project_id": project_id,
                "idea_id": idea_id,
                "status": "reviewed",
                "writer_agent": "cloud_openclaw",
                "owner_agent": "cloud_openclaw",
                "next_owner": "done",
                "created_at": self._content_os_date(message.created_at),
            },
            section_id="data_review",
            title="数据复盘",
            content=self._render_content_os_data_review_section(message, parsed, reply),
        )
        review_id = str(parsed.get("record_id") or parsed.get("review_id") or f"review_{self._content_os_date(message.created_at)}_{make_record_id(message.raw_text)[:6]}")
        self._append_registry_row(
            vault_root / "90_索引与注册表" / "review_registry.md",
            header="# Review Registry\n\n| review_id | project_id | 平台 | 复盘节点 | 文档 | 创建时间 |\n| --- | --- | --- | --- | --- | --- |\n",
            key=review_id,
            row=f"| {review_id} | {project_id} | {self._md_cell(self._extract_labeled_value(message.raw_text, '平台') or '未指定')} | {self._md_cell(self._extract_labeled_value(message.raw_text, '复盘节点') or '未指定')} | `08_内容项目/{project_id}/10_review.md` | {self._content_os_date(message.created_at)} |",
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
                status_lines.append(advanced)
                current_status = "published"
        if current_status == "published":
            advanced = self._maybe_advance_content_os_status(
                project_id=project_id,
                from_status="published",
                to_status="reviewed",
                actor="cloud_openclaw",
                evidence={"10_review.md", "result_yaml_valid"},
                reason="【数据复盘】写入 10_review.md",
                vault_root=vault_root,
            )
            if advanced:
                status_lines.append(advanced)
        reply_line = f"Content OS 复盘已写入：08_内容项目/{project_id}/10_review.md"
        if status_lines:
            reply_line = reply_line + "\n" + "\n".join(status_lines)
        elif current_status not in {"published", "reviewed"}:
            reply_line = f"{reply_line}\nContent OS 状态未推进：当前状态 {current_status or '未记录'} 不是可复盘推进状态"
        return {"project_id": project_id, "review_path": str(review_path), "reply": reply_line}
