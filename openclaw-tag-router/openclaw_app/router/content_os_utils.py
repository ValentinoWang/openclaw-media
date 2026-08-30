from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from ..services.markdown_frontmatter import read_frontmatter_tolerant
from ..services.utils import cleanup_generated_file_duplicates, now_in_tz


class ContentOSUtilsMixin:
    @staticmethod
    def _inspiration_requests_content_os_project(raw: str) -> bool:
        text = str(raw or "")
        project_signals = ("立项", "项目包", "Content OS", "初步脚本", "初稿脚本", "先出脚本", "brief", "Brief", "script", "Script")
        target_signals = ("目标", "后续", "生成", "创建", "写", "做成内容", "初稿", "脚本", "项目")
        return any(item in text for item in project_signals) and any(item in text for item in target_signals)
    @staticmethod
    def _creation_requests_content_os_project(raw: str) -> bool:
        text = str(raw or "")
        if not text.strip():
            return False
        direct_signals = (
            "已有素材",
            "已经拍好",
            "拍好素材",
            "本地素材",
            "素材匹配",
            "Mac",
            "Storyboard",
            "EDL",
            "分镜",
            "剪辑说明",
            "剪辑顺序",
            "同款翻拍",
            "反推",
        )
        if any(item in text for item in direct_signals):
            return True
        return "希望产出" in text and any(item in text for item in ("剪辑", "脚本", "分镜", "素材"))
    @staticmethod
    def _extract_content_os_local_project_path(raw: str) -> str:
        text = str(raw or "").replace("\\_", "_")
        for label in ("本地素材路径", "本地素材", "素材路径", "素材", "local_project_path"):
            match = re.search(rf"{label}\s*[：:=]\s*(?P<path>/Users/[^\n\r]+)", text)
            if match:
                path = match.group("path").strip().strip("`")
                if not path.endswith("00_批次说明.md"):
                    return path
        for match in re.finditer(r"(?P<path>/Users/[^\n\r]+)", text):
            path = match.group("path").strip().strip("`")
            if not path.endswith("00_批次说明.md"):
                return path
        return ""
    @staticmethod
    def _extract_content_os_batch_note_path(raw: str) -> str:
        text = str(raw or "").replace("\\_", "_")
        labels = ("批次说明路径", "批次说明", "batch_note_path")
        for label in labels:
            match = re.search(rf"{label}\s*[：:=]\s*(?P<path>[^\n\r]+00_批次说明\.md)", text)
            if match:
                return match.group("path").strip().strip("`")
        match = re.search(r"(?P<path>(?:/Users/[^\n\r]+|00_Inbox_Mac_Intake/[^\n\r]+)00_批次说明\.md)", text)
        return match.group("path").strip().strip("`") if match else ""
    @staticmethod
    def _extract_content_os_inbox_batch_path(raw: str) -> str:
        text = str(raw or "").replace("\\_", "_")
        for label in ("Inbox批次路径", "本地批次路径", "批次路径", "inbox_batch_path"):
            match = re.search(rf"{label}\s*[：:=]\s*(?P<path>[^\n\r]+)", text)
            if match:
                return match.group("path").strip().strip("`")
        batch_note = ContentOSUtilsMixin._extract_content_os_batch_note_path(text)
        if batch_note.endswith("/00_批次说明.md"):
            return batch_note[: -len("/00_批次说明.md")]
        match = re.search(r"(?P<path>00_Inbox_Mac_Intake/[^\n\r]+)", text)
        return match.group("path").strip().strip("`") if match else ""
    @staticmethod
    def _extract_labeled_value(raw: str, label: str) -> str:
        match = re.search(rf"{label}\s*[：:=]\s*(?P<value>[^\n\r]+)", str(raw or ""))
        if not match:
            return ""
        value = match.group("value").strip()
        value = re.split(
            r"\s+(?:平台|账号|目标|目标状态|成片路径|导出路径|视频路径|创作要求|作品内容|本地素材路径|本地素材|素材路径|素材|情绪|赛道|复盘节点|作品链接|发布链接|local_project_path)\s*[：:=]",
            value,
            maxsplit=1,
        )[0]
        return value.strip()
    @staticmethod
    def _content_os_date(value: datetime | None) -> str:
        if value is None:
            return now_in_tz("Asia/Shanghai").strftime("%Y%m%d")
        if value.tzinfo is not None:
            return value.astimezone(now_in_tz("Asia/Shanghai").tzinfo).strftime("%Y%m%d")
        return value.strftime("%Y%m%d")
    @staticmethod
    def _content_os_path_name(path: str) -> str:
        clean = str(path or "").rstrip("/")
        return clean.split("/")[-1] if clean else ""
    def _content_os_project_slug_source(self, local_project_path: str, title: str) -> str:
        path_name = self._content_os_path_name(local_project_path)
        if path_name and re.search(r"[\u4e00-\u9fffA-Za-z0-9]", path_name):
            return path_name
        return title
    @staticmethod
    def _content_os_slug(value: str, *, limit: int = 36) -> str:
        text = str(value or "").replace("\\_", "_")
        text = re.sub(r"^\d{8}[_-]?", "", text)
        text = re.sub(r"[^\w\u4e00-\u9fff]+", "_", text)
        text = re.sub(r"_+", "_", text).strip("_")
        return (text or "未命名内容")[:limit]
    def _unique_content_os_project_id(self, projects_root: Path, created_date: str, slug_source: str) -> str:
        base = f"{created_date}_{self._content_os_slug(slug_source)}"
        candidate = base
        index = 2
        while (projects_root / candidate).exists():
            candidate = f"{base}_{index}"
            index += 1
        return candidate
    @staticmethod
    def _next_content_os_id(registry_path: Path, prefix: str) -> str:
        max_seq = 0
        if registry_path.exists():
            for match in re.finditer(rf"{re.escape(prefix)}(?P<seq>\d{{3}})", registry_path.read_text(encoding="utf-8", errors="replace")):
                max_seq = max(max_seq, int(match.group("seq")))
        return f"{prefix}{max_seq + 1:03d}"
    def _next_content_os_task_id(self, vault_root: Path, created_date: str) -> str:
        max_seq = 0
        pattern = re.compile(rf"task_{re.escape(created_date)}_(?P<seq>\d{{3}})")
        for root in (vault_root / "98_Agent任务队列").glob("*"):
            if root.is_dir():
                for path in root.glob(f"*task_{created_date}_*.yaml"):
                    match = pattern.search(path.name)
                    if match:
                        max_seq = max(max_seq, int(match.group("seq")))
        registry_path = vault_root / "90_索引与注册表" / "task_registry.md"
        if registry_path.exists():
            for match in pattern.finditer(registry_path.read_text(encoding="utf-8", errors="replace")):
                max_seq = max(max_seq, int(match.group("seq")))
        return f"task_{created_date}_{max_seq + 1:03d}"
    @staticmethod
    def _md_cell(value: Any) -> str:
        return str(value or "").replace("|", "/").replace("\n", " ").strip()
    @staticmethod
    def _yaml_scalar(value: str) -> str:
        return json.dumps(str(value or ""), ensure_ascii=False)
    @staticmethod
    def _write_text_if_absent(path: Path, content: str) -> None:
        if path.exists():
            cleanup_generated_file_duplicates(path)
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content.rstrip() + "\n", encoding="utf-8")
        cleanup_generated_file_duplicates(path)
    def _append_registry_row(self, path: Path, *, header: str, key: str, row: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        text = path.read_text(encoding="utf-8", errors="replace") if path.exists() else header
        if key in text:
            cleanup_generated_file_duplicates(path)
            return
        if not text.endswith("\n"):
            text += "\n"
        path.write_text(text + row.rstrip() + "\n", encoding="utf-8")
        cleanup_generated_file_duplicates(path)

    @staticmethod
    def _content_os_vault_root() -> Path:
        return Path(os.environ.get("CONTENT_OS_VAULT_ROOT", "/home/ubuntu/obsidian-自媒体"))
    @staticmethod
    def _content_os_cloud_markdown_enabled() -> bool:
        value = os.environ.get("CONTENT_OS_CLOUD_MARKDOWN", "").strip().lower()
        return value in {"1", "true", "yes", "on"}
    def _extract_content_os_project_id(self, raw: str, vault_root: Path | None = None) -> str:
        text = str(raw or "")
        candidates: list[str] = []
        for label in ("project_id", "项目ID", "项目"):
            value = self._extract_labeled_value(text, label)
            if value:
                candidate = re.split(r"\s+", value, maxsplit=1)[0].strip("`，,。；;")
                if candidate:
                    candidates.append(candidate)
        vault_root = vault_root or self._content_os_vault_root()
        projects_root = vault_root / "08_内容项目"
        if projects_root.exists():
            project_ids = sorted((path.name for path in projects_root.iterdir() if path.is_dir()), key=len, reverse=True)
            for candidate in candidates:
                if candidate in project_ids:
                    return candidate
            for project_id in project_ids:
                if project_id in text:
                    return project_id
            for project_id in project_ids:
                frontmatter, _ = self._read_markdown_frontmatter(projects_root / project_id / "00_项目总览.md")
                title = str(frontmatter.get("title") or frontmatter.get("theme") or "").strip()
                if title and title in text:
                    return project_id
        return candidates[0] if candidates else ""
    def _content_os_project_dir(self, project_id: str, vault_root: Path | None = None) -> Path:
        return (vault_root or self._content_os_vault_root()) / "08_内容项目" / project_id
    @staticmethod
    def _read_markdown_frontmatter(path: Path) -> tuple[dict[str, Any], str]:
        return read_frontmatter_tolerant(path)
    @staticmethod
    def _write_markdown_frontmatter(path: Path, frontmatter: dict[str, Any], body: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        frontmatter_text = yaml.safe_dump(frontmatter, allow_unicode=True, sort_keys=False).strip()
        path.write_text(f"---\n{frontmatter_text}\n---\n\n{body.lstrip()}".rstrip() + "\n", encoding="utf-8")
        cleanup_generated_file_duplicates(path)
    def _content_os_project_index_path(self, project_id: str, vault_root: Path | None = None) -> Path:
        return self._content_os_project_dir(project_id, vault_root) / "00_项目总览.md"
    def _content_os_project_status(self, project_id: str, vault_root: Path | None = None) -> str:
        frontmatter, _ = self._read_markdown_frontmatter(self._content_os_project_index_path(project_id, vault_root))
        return str(frontmatter.get("status") or "").strip()
    def _content_os_project_local_path(self, project_id: str, vault_root: Path | None = None) -> str:
        frontmatter, _ = self._read_markdown_frontmatter(self._content_os_project_index_path(project_id, vault_root))
        return str(frontmatter.get("local_project_path") or "").strip()
    def _content_os_project_batch_note_path(self, project_id: str, vault_root: Path | None = None) -> str:
        frontmatter, _ = self._read_markdown_frontmatter(self._content_os_project_index_path(project_id, vault_root))
        return str(frontmatter.get("batch_note_path") or "").strip()
    def _content_os_project_inbox_batch_path(self, project_id: str, vault_root: Path | None = None) -> str:
        frontmatter, _ = self._read_markdown_frontmatter(self._content_os_project_index_path(project_id, vault_root))
        return str(frontmatter.get("inbox_batch_path") or "").strip()
    def _upsert_content_os_auto_section(
        self,
        path: Path,
        *,
        frontmatter: dict[str, Any],
        section_id: str,
        title: str,
        content: str,
    ) -> None:
        start = f"<!-- content_os_auto:{section_id}:start -->"
        end = f"<!-- content_os_auto:{section_id}:end -->"
        block = f"{start}\n\n## {title}\n\n{content.rstrip()}\n\n{end}"
        if not path.exists():
            body = f"# {title}\n\n{block}\n"
            self._write_markdown_frontmatter(path, frontmatter, body)
            return
        existing_frontmatter, body = self._read_markdown_frontmatter(path)
        if existing_frontmatter:
            frontmatter = {**existing_frontmatter, **{key: value for key, value in frontmatter.items() if key not in existing_frontmatter}}
        pattern = re.compile(re.escape(start) + r".*?" + re.escape(end), flags=re.S)
        if pattern.search(body):
            body = pattern.sub(block, body)
        else:
            body = body.rstrip() + "\n\n" + block + "\n"
        self._write_markdown_frontmatter(path, frontmatter, body)
    def _content_os_project_idea_id(self, project_id: str, vault_root: Path) -> str:
        frontmatter, _ = self._read_markdown_frontmatter(self._content_os_project_index_path(project_id, vault_root))
        idea_id = str(frontmatter.get("idea_id") or "").strip()
        return idea_id or f"idea_{self._content_os_date(now_in_tz('Asia/Shanghai'))}_000"
    def _find_content_os_ready_task(self, vault_root: Path, project_id: str, task_type: str) -> Path | None:
        queue_root = vault_root / "98_Agent任务队列" / "01_cloud_to_mac_ready"
        if not queue_root.exists():
            return None
        for path in sorted(queue_root.glob("*.yaml")):
            try:
                task = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            except Exception:
                continue
            if task.get("project_id") == project_id and task.get("task_type") == task_type and task.get("status") == "ready":
                return path
        return None
    @staticmethod
    def _markdown_list(value: Any) -> str:
        if isinstance(value, list):
            return "\n".join(f"- {str(item).strip()}" for item in value if str(item).strip())
        text = str(value or "").strip()
        if not text:
            return ""
        return "\n".join(f"- {line.strip()}" for line in text.splitlines() if line.strip())
