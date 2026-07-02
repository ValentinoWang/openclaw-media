from __future__ import annotations

from pathlib import Path

import yaml

from ..services.utils import cleanup_generated_file_duplicates, now_in_tz


class ContentOSStateMixin:
    def _set_content_os_project_status(self, project_id: str, status: str, *, actor: str, reason: str, vault_root: Path | None = None) -> None:
        vault_root = vault_root or self._content_os_vault_root()
        index_path = self._content_os_project_index_path(project_id, vault_root)
        frontmatter, body = self._read_markdown_frontmatter(index_path)
        if not frontmatter:
            raise ValueError(f"项目总览缺少 frontmatter：{index_path}")
        old_status = str(frontmatter.get("status") or "").strip()
        frontmatter["status"] = status
        frontmatter["updated_at"] = self._content_os_date(now_in_tz("Asia/Shanghai"))
        self._write_markdown_frontmatter(index_path, frontmatter, body)
        self._update_content_os_project_registry_status(project_id, status, vault_root)
        self._append_content_os_state_log(project_id, old_status, status, actor=actor, reason=reason, vault_root=vault_root)
    def _update_content_os_project_registry_status(self, project_id: str, status: str, vault_root: Path) -> None:
        path = vault_root / "90_索引与注册表" / "project_registry.md"
        if not path.exists():
            return
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        out = []
        for line in lines:
            if line.startswith("|") and f"| {project_id} |" in line:
                cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
                if len(cells) >= 3:
                    cells[2] = status
                    line = "| " + " | ".join(cells) + " |"
            out.append(line)
        path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
        cleanup_generated_file_duplicates(path)
    def _append_content_os_state_log(self, project_id: str, old_status: str, new_status: str, *, actor: str, reason: str, vault_root: Path) -> None:
        path = self._content_os_project_dir(project_id, vault_root) / "00_state_log.md"
        if not path.exists():
            path.write_text("# State Log\n\n| time | actor | from | to | reason |\n| --- | --- | --- | --- | --- |\n", encoding="utf-8")
        text = path.read_text(encoding="utf-8", errors="replace")
        now = now_in_tz("Asia/Shanghai").isoformat(timespec="seconds")
        row = f"| {now} | {self._md_cell(actor)} | {self._md_cell(old_status)} | {self._md_cell(new_status)} | {self._md_cell(reason)} |"
        path.write_text(text.rstrip() + "\n" + row + "\n", encoding="utf-8")
        cleanup_generated_file_duplicates(path)
    def _content_os_transition_allowed(
        self,
        *,
        vault_root: Path,
        from_status: str,
        to_status: str,
        actor: str,
        project_id: str,
        evidence: set[str],
    ) -> tuple[bool, list[str]]:
        rules_path = vault_root / "00_入口与总览" / "state_transition_rules.yaml"
        if not rules_path.exists():
            return False, ["state_transition_rules.yaml"]
        rules = yaml.safe_load(rules_path.read_text(encoding="utf-8")) or {}
        transitions = rules.get("transitions") if isinstance(rules.get("transitions"), dict) else {}
        selected = None
        for item in transitions.values():
            if isinstance(item, dict) and item.get("from") == from_status and item.get("to") == to_status:
                selected = item
                break
        if not selected:
            return False, [f"{from_status}->{to_status}"]
        if str(selected.get("allowed_actor") or "") != actor:
            return False, [f"actor:{actor}"]
        missing = []
        project_dir = self._content_os_project_dir(project_id, vault_root)
        for item in selected.get("required_evidence") or []:
            item = str(item)
            if item in evidence:
                continue
            if item.endswith((".md", ".json", ".yaml", ".yml")) and (project_dir / item).exists():
                continue
            missing.append(item)
        return not missing, missing
    def _maybe_advance_content_os_status(
        self,
        *,
        project_id: str,
        from_status: str,
        to_status: str,
        actor: str,
        evidence: set[str],
        reason: str,
        vault_root: Path,
    ) -> str:
        if not from_status or from_status == to_status:
            return ""
        allowed, missing = self._content_os_transition_allowed(
            vault_root=vault_root,
            from_status=from_status,
            to_status=to_status,
            actor=actor,
            project_id=project_id,
            evidence=evidence,
        )
        if not allowed:
            return f"Content OS 状态未推进：{from_status} -> {to_status} 缺少 {', '.join(missing)}"
        self._set_content_os_project_status(project_id, to_status, actor=actor, reason=reason, vault_root=vault_root)
        return f"Content OS 状态已推进：{from_status} -> {to_status}"
