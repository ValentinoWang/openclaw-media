"""Content OS v0.2 project lifecycle.

This module owns the only writable project-stage record: the frontmatter of
``08_内容项目/{project_id}/00_项目总览.md``.  It deliberately has no knowledge
of project_registry.md, Feishu, or the Mac result queue.  Those are projections
or evidence consumers and must not become a second state writer.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
import re
from typing import Any, Iterable

import yaml


CONTENT_OS_SPEC_VERSION = "content_os_v0.2"
PROJECT_STATUSES = (
    "captured",
    "planned",
    "edit_ready",
    "editing",
    "final_ready",
    "published",
)
EDITOR_BACKENDS = ("handoff_pack", "otio_kdenlive")


class ContentOSContractError(ValueError):
    """Raised when a request would violate the v0.2 Content OS contract."""


@dataclass(frozen=True)
class ProjectState:
    project_id: str
    status: str
    project_revision: int
    editor_backend: str
    blocked: bool
    blocked_reason: str
    updated_at: str
    overview_path: Path
    frontmatter: dict[str, Any]


def _now_iso(now: datetime | None = None) -> str:
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


def _validate_project_id(project_id: str) -> str:
    value = str(project_id or "").strip()
    if not value or value in {".", ".."} or Path(value).name != value or "/" in value or "\\" in value:
        raise ContentOSContractError("project_id 必须是单个项目目录名")
    return value


def project_overview_path(vault_root: Path, project_id: str) -> Path:
    return Path(vault_root) / "08_内容项目" / _validate_project_id(project_id) / "00_项目总览.md"


def _read_frontmatter(path: Path) -> tuple[dict[str, Any], str]:
    if not path.exists():
        raise ContentOSContractError(f"项目总览不存在：{path}")
    text = path.read_text(encoding="utf-8", errors="replace")
    match = re.match(r"\A---\n(?P<frontmatter>.*?)\n---\n?(?P<body>.*)\Z", text, flags=re.S)
    if not match:
        raise ContentOSContractError(f"项目总览缺少 frontmatter：{path}")
    try:
        frontmatter = yaml.safe_load(match.group("frontmatter")) or {}
    except yaml.YAMLError as exc:
        raise ContentOSContractError(f"项目总览 frontmatter 无法读取：{path}") from exc
    if not isinstance(frontmatter, dict):
        raise ContentOSContractError(f"项目总览 frontmatter 必须是对象：{path}")
    return frontmatter, match.group("body")


def _write_frontmatter(path: Path, frontmatter: dict[str, Any], body: str) -> None:
    rendered = yaml.safe_dump(frontmatter, allow_unicode=True, sort_keys=False).strip()
    payload = f"---\n{rendered}\n---\n\n{body.lstrip()}".rstrip() + "\n"
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(payload, encoding="utf-8")
    os.replace(temporary, path)


def _as_revision(value: Any, *, field_name: str = "project_revision") -> int:
    if isinstance(value, bool):
        raise ContentOSContractError(f"{field_name} 必须是从 1 开始的整数")
    try:
        revision = int(value)
    except (TypeError, ValueError) as exc:
        raise ContentOSContractError(f"{field_name} 必须是从 1 开始的整数") from exc
    if revision < 1:
        raise ContentOSContractError(f"{field_name} 必须是从 1 开始的整数")
    return revision


def _validate_editor_backend(value: Any) -> str:
    backend = str(value or "").strip()
    if backend not in EDITOR_BACKENDS:
        raise ContentOSContractError("剪辑方式只能是 handoff_pack 或 otio_kdenlive，且不允许自动切换")
    return backend


def read_project_state(vault_root: Path, project_id: str) -> ProjectState:
    path = project_overview_path(vault_root, project_id)
    frontmatter, _ = _read_frontmatter(path)
    if str(frontmatter.get("spec_version") or "") != CONTENT_OS_SPEC_VERSION:
        raise ContentOSContractError(f"项目总览不是 {CONTENT_OS_SPEC_VERSION}：{path}")
    if str(frontmatter.get("doc_type") or "") not in {"project_overview", "project_index"}:
        raise ContentOSContractError(f"项目总览 doc_type 不正确：{path}")
    recorded_id = str(frontmatter.get("project_id") or "").strip()
    if recorded_id != _validate_project_id(project_id):
        raise ContentOSContractError("项目目录与项目总览 project_id 不一致")
    status = str(frontmatter.get("status") or "").strip()
    if status not in PROJECT_STATUSES:
        raise ContentOSContractError(f"项目阶段不在 v0.2 枚举中：{status or '空'}")
    if "project_revision" not in frontmatter:
        raise ContentOSContractError("项目总览缺少 project_revision")
    if "editor_backend" not in frontmatter:
        raise ContentOSContractError("项目总览缺少 editor_backend；系统不会自动选择")
    return ProjectState(
        project_id=recorded_id,
        status=status,
        project_revision=_as_revision(frontmatter.get("project_revision")),
        editor_backend=_validate_editor_backend(frontmatter.get("editor_backend")),
        blocked=bool(frontmatter.get("blocked", False)),
        blocked_reason=str(frontmatter.get("blocked_reason") or "").strip(),
        updated_at=str(frontmatter.get("updated_at") or "").strip(),
        overview_path=path,
        frontmatter=dict(frontmatter),
    )


def _load_transition_rules(vault_root: Path) -> dict[str, Any]:
    path = Path(vault_root) / "00_入口与总览" / "state_transition_rules.yaml"
    if not path.exists():
        raise ContentOSContractError("缺少 state_transition_rules.yaml")
    try:
        rules = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ContentOSContractError("state_transition_rules.yaml 无法读取") from exc
    if not isinstance(rules, dict) or rules.get("spec_version") != CONTENT_OS_SPEC_VERSION:
        raise ContentOSContractError(f"state_transition_rules.yaml 必须使用 {CONTENT_OS_SPEC_VERSION}")
    statuses = tuple(rules.get("project_statuses") or ())
    if statuses != PROJECT_STATUSES:
        raise ContentOSContractError("状态规则与 Content OS v0.2 的六个项目阶段不一致")
    transitions = rules.get("transitions")
    if not isinstance(transitions, dict):
        raise ContentOSContractError("state_transition_rules.yaml 缺少 transitions")
    return rules


def _allowed_actors(value: Any) -> set[str]:
    actor = str(value or "").strip()
    aliases = {
        "cloud_openclaw_or_human": {"cloud_openclaw", "human"},
    }
    return aliases.get(actor, {actor} if actor else set())


def _transition_rule(rules: dict[str, Any], from_status: str, to_status: str) -> dict[str, Any]:
    for rule in (rules.get("transitions") or {}).values():
        if isinstance(rule, dict) and rule.get("from") == from_status and rule.get("to") == to_status:
            return rule
    raise ContentOSContractError(f"不允许项目阶段直接从 {from_status} 变为 {to_status}")


def _evidence_exists(
    project_dir: Path,
    evidence_name: str,
    supplied: set[str],
    *,
    frontmatter: dict[str, Any],
) -> bool:
    if evidence_name == "human_published_confirmation":
        return bool(
            str(frontmatter.get("publication_confirmed_at") or "").strip()
            and str(frontmatter.get("publication_confirmed_by") or "").strip()
        )
    if evidence_name in supplied:
        return True
    candidate = Path(evidence_name)
    if candidate.is_absolute() or ".." in candidate.parts:
        return False
    return candidate.suffix in {".md", ".json", ".yaml", ".yml"} and (project_dir / candidate).exists()


def _append_state_log(project_dir: Path, *, actor: str, from_status: str, to_status: str, reason: str, now: datetime | None) -> None:
    path = project_dir / "00_state_log.md"
    if not path.exists():
        path.write_text("# 项目阶段记录\n\n| 时间 | 操作人 | 原阶段 | 新阶段 | 原因 |\n| --- | --- | --- | --- | --- |\n", encoding="utf-8")
    safe_reason = str(reason or "").replace("|", "/").replace("\n", " ").strip()
    row = f"| {_now_iso(now)} | {actor} | {from_status} | {to_status} | {safe_reason} |"
    path.write_text(path.read_text(encoding="utf-8", errors="replace").rstrip() + "\n" + row + "\n", encoding="utf-8")


def transition_project_status(
    vault_root: Path,
    project_id: str,
    *,
    to_status: str,
    actor: str,
    reason: str,
    evidence: Iterable[str],
    now: datetime | None = None,
) -> ProjectState:
    """Move one project through a permitted v0.2 transition.

    A Mac actor is intentionally rejected even when it supplies valid artifact
    evidence.  Mac results are evidence only; a cloud/human lifecycle action
    makes the phase change after verification.
    """

    state = read_project_state(vault_root, project_id)
    target = str(to_status or "").strip()
    performer = str(actor or "").strip()
    if performer == "mac_openclaw":
        raise ContentOSContractError("Mac 回传只能提供证据，不能推进项目阶段")
    if target not in PROJECT_STATUSES:
        raise ContentOSContractError(f"目标项目阶段不在 v0.2 枚举中：{target or '空'}")
    if state.status == target:
        raise ContentOSContractError("项目已在目标阶段，不能重复推进")
    rules = _load_transition_rules(vault_root)
    rule = _transition_rule(rules, state.status, target)
    if performer not in _allowed_actors(rule.get("allowed_actor")):
        raise ContentOSContractError(f"{performer or '未指定操作人'} 无权推进 {state.status} -> {target}")
    supplied = {str(item).strip() for item in evidence if str(item).strip()}
    project_dir = state.overview_path.parent
    missing = [
        str(item)
        for item in (rule.get("required_evidence") or [])
        if not _evidence_exists(project_dir, str(item), supplied, frontmatter=state.frontmatter)
    ]
    if missing:
        raise ContentOSContractError(f"推进项目阶段缺少证据：{', '.join(missing)}")

    frontmatter, body = _read_frontmatter(state.overview_path)
    frontmatter["status"] = target
    frontmatter["updated_at"] = _now_iso(now)
    _write_frontmatter(state.overview_path, frontmatter, body)
    _append_state_log(project_dir, actor=performer, from_status=state.status, to_status=target, reason=reason, now=now)
    return read_project_state(vault_root, project_id)


def set_project_blocked(
    vault_root: Path,
    project_id: str,
    *,
    blocked: bool,
    reason: str = "",
    now: datetime | None = None,
) -> ProjectState:
    """Set independent blocking information without changing the project phase."""

    state = read_project_state(vault_root, project_id)
    message = str(reason or "").strip()
    if blocked and not message:
        raise ContentOSContractError("设置阻塞时必须提供面向人的阻塞原因")
    frontmatter, body = _read_frontmatter(state.overview_path)
    frontmatter["blocked"] = bool(blocked)
    frontmatter["blocked_reason"] = message if blocked else ""
    frontmatter["updated_at"] = _now_iso(now)
    _write_frontmatter(state.overview_path, frontmatter, body)
    return read_project_state(vault_root, project_id)


def activate_confirmed_revision(
    vault_root: Path,
    project_id: str,
    *,
    expected_revision: int,
    editor_backend: str,
    change_request_id: str,
    human_confirmed_impact: bool,
    now: datetime | None = None,
) -> ProjectState:
    """Start one confirmed substantive revision without changing project phase."""

    if not human_confirmed_impact:
        raise ContentOSContractError("只有人工确认影响后才能开始实际修改")
    state = read_project_state(vault_root, project_id)
    if state.project_revision != _as_revision(expected_revision, field_name="expected_revision"):
        raise ContentOSContractError("修改单版本已过期；请重新确认后再执行")
    backend = _validate_editor_backend(editor_backend)
    request_id = str(change_request_id or "").strip()
    if not request_id:
        raise ContentOSContractError("实际修改必须关联 change_request_id")
    frontmatter, body = _read_frontmatter(state.overview_path)
    frontmatter["project_revision"] = state.project_revision + 1
    frontmatter["editor_backend"] = backend
    frontmatter["active_change_request_id"] = request_id
    frontmatter["updated_at"] = _now_iso(now)
    _write_frontmatter(state.overview_path, frontmatter, body)
    return read_project_state(vault_root, project_id)


def set_project_reviewed_at(vault_root: Path, project_id: str, *, reviewed_at: str, now: datetime | None = None) -> ProjectState:
    """Record review evidence timing without inventing another project stage."""

    state = read_project_state(vault_root, project_id)
    value = str(reviewed_at or "").strip()
    if not value:
        raise ContentOSContractError("reviewed_at 不能为空")
    frontmatter, body = _read_frontmatter(state.overview_path)
    frontmatter["reviewed_at"] = value
    frontmatter["updated_at"] = _now_iso(now)
    _write_frontmatter(state.overview_path, frontmatter, body)
    return read_project_state(vault_root, project_id)
