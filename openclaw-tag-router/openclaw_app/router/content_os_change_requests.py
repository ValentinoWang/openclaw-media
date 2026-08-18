"""Human-first Content OS v0.2 modification requests.

Creating or noting a modification records an operator's idea only.  It cannot
alter a project phase, increment its revision, create a Mac task, or set a
blocker.  A separate explicit human confirmation is required before queueing
real work.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
import re
from typing import Any, Iterable

import yaml

from .content_os_project_lifecycle import (
    CONTENT_OS_SPEC_VERSION,
    ContentOSContractError,
    EDITOR_BACKENDS,
    read_project_state,
)


CHANGE_REQUEST_DIRECTORY = Path("98_Agent任务队列") / "00_change_requests"
CHANGE_REQUEST_STATUSES = ("pending_confirmation", "noted", "confirmed", "executing", "completed", "superseded")
URGENCY_LEVELS = ("normal", "urgent")


@dataclass(frozen=True)
class ChangeRequest:
    change_request_id: str
    project_id: str
    project_revision: int
    target_revision: int
    status: str
    requested_location: str
    requested_change: str
    reason: str
    urgency: str
    submitted_by: str
    editor_backend: str
    path: Path
    payload: dict[str, Any]


def _now_iso(now: datetime | None = None) -> str:
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


def _now_date(now: datetime | None = None) -> str:
    value = now or datetime.now(timezone.utc)
    return value.strftime("%Y%m%d")


def _request_root(vault_root: Path) -> Path:
    return Path(vault_root) / CHANGE_REQUEST_DIRECTORY


def _safe_request_id(change_request_id: str) -> str:
    value = str(change_request_id or "").strip()
    if not re.fullmatch(r"change_\d{8}_\d{3}", value):
        raise ContentOSContractError("change_request_id 格式不正确")
    return value


def change_request_path(vault_root: Path, change_request_id: str) -> Path:
    return _request_root(vault_root) / f"{_safe_request_id(change_request_id)}.yaml"


def _read_payload(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ContentOSContractError("修改单不存在")
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ContentOSContractError("修改单无法读取") from exc
    if not isinstance(payload, dict):
        raise ContentOSContractError("修改单内容必须是对象")
    return payload


def _as_revision(value: Any) -> int:
    if isinstance(value, bool):
        raise ContentOSContractError("修改单项目版本必须从 1 开始")
    try:
        revision = int(value)
    except (TypeError, ValueError) as exc:
        raise ContentOSContractError("修改单项目版本必须从 1 开始") from exc
    if revision < 1:
        raise ContentOSContractError("修改单项目版本必须从 1 开始")
    return revision


def _to_change_request(path: Path, payload: dict[str, Any]) -> ChangeRequest:
    if payload.get("spec_version") != CONTENT_OS_SPEC_VERSION or payload.get("doc_type") != "content_revision_request":
        raise ContentOSContractError("修改单不是 Content OS v0.2 格式")
    request_id = _safe_request_id(str(payload.get("change_id") or ""))
    if path.name != f"{request_id}.yaml":
        raise ContentOSContractError("修改单文件名与 change_request_id 不一致")
    status = str(payload.get("request_status") or "").strip()
    if status not in CHANGE_REQUEST_STATUSES:
        raise ContentOSContractError("修改单状态不正确")
    urgency = str(payload.get("urgency") or "").strip()
    if urgency not in URGENCY_LEVELS:
        raise ContentOSContractError("修改单紧急程度不正确")
    backend = str(payload.get("editor_backend") or "").strip()
    if backend not in EDITOR_BACKENDS:
        raise ContentOSContractError("修改单必须明确选择剪辑方式，不能自动回退")
    required = ("project_id", "requested_location", "requested_change", "reason", "submitted_by")
    if any(not str(payload.get(field) or "").strip() for field in required):
        raise ContentOSContractError("修改单缺少必要说明")
    base_revision = _as_revision(payload.get("base_revision"))
    target_revision = _as_revision(payload.get("target_revision"))
    if target_revision != base_revision + 1:
        raise ContentOSContractError("修改单目标版本必须恰好比基础版本高一版")
    return ChangeRequest(
        change_request_id=request_id,
        project_id=str(payload["project_id"]).strip(),
        project_revision=base_revision,
        target_revision=target_revision,
        status=status,
        requested_location=str(payload["requested_location"]).strip(),
        requested_change=str(payload["requested_change"]).strip(),
        reason=str(payload["reason"]).strip(),
        urgency=urgency,
        submitted_by=str(payload["submitted_by"]).strip(),
        editor_backend=backend,
        path=path,
        payload=payload,
    )


def load_change_request(vault_root: Path, change_request_id: str) -> ChangeRequest:
    path = change_request_path(vault_root, change_request_id)
    return _to_change_request(path, _read_payload(path))


def find_open_change_request(vault_root: Path, project_id: str) -> ChangeRequest | None:
    """Return the sole actionable request for a project, if it is unambiguous."""

    matches: list[ChangeRequest] = []
    for path in sorted(_request_root(vault_root).glob("change_*.yaml")):
        request = _to_change_request(path, _read_payload(path))
        if request.project_id == str(project_id or "").strip() and request.status in {"pending_confirmation", "confirmed"}:
            matches.append(request)
    if len(matches) > 1:
        raise ContentOSContractError("这个项目有多条待处理修改，请在对话中说明要处理的那一条")
    return matches[0] if matches else None


def _write_payload(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = yaml.safe_dump(payload, allow_unicode=True, sort_keys=False).rstrip() + "\n"
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(rendered, encoding="utf-8")
    os.replace(temporary, path)


def _next_request_id(vault_root: Path, now: datetime | None) -> str:
    date = _now_date(now)
    pattern = re.compile(rf"change_{date}_(\d{{3}})\.yaml\Z")
    highest = 0
    root = _request_root(vault_root)
    if root.exists():
        for path in root.glob(f"change_{date}_*.yaml"):
            match = pattern.fullmatch(path.name)
            if match:
                highest = max(highest, int(match.group(1)))
    return f"change_{date}_{highest + 1:03d}"


def _clean_references(references: Iterable[str] | None) -> list[str]:
    return [str(item).strip() for item in (references or []) if str(item).strip()]


def create_change_request(
    vault_root: Path,
    project_id: str,
    *,
    requested_location: str,
    requested_change: str,
    reason: str,
    urgency: str,
    submitted_by: str,
    editor_backend: str,
    references: Iterable[str] | None = None,
    now: datetime | None = None,
) -> ChangeRequest:
    """Create a pending modification request without changing project state."""

    state = read_project_state(vault_root, project_id)
    location = str(requested_location or "").strip()
    change = str(requested_change or "").strip()
    why = str(reason or "").strip()
    submitter = str(submitted_by or "").strip()
    selected_urgency = str(urgency or "").strip()
    selected_backend = str(editor_backend or "").strip()
    if not all((location, change, why, submitter)):
        raise ContentOSContractError("提交修改需说明想改哪里、希望改成什么、为什么，以及提交人")
    if selected_urgency not in URGENCY_LEVELS:
        raise ContentOSContractError("紧急程度只能是 normal 或 urgent")
    if selected_backend not in EDITOR_BACKENDS:
        raise ContentOSContractError("必须选择 handoff_pack 或 otio_kdenlive，系统不会自动选择")
    request_id = _next_request_id(vault_root, now)
    path = change_request_path(vault_root, request_id)
    payload: dict[str, Any] = {
        "spec_version": CONTENT_OS_SPEC_VERSION,
        "doc_type": "content_revision_request",
        "change_id": request_id,
        "project_id": state.project_id,
        "base_revision": state.project_revision,
        "target_revision": state.project_revision + 1,
        "request_status": "pending_confirmation",
        "requested_location": location,
        "requested_change": change,
        "reason": why,
        "urgency": selected_urgency,
        "references": _clean_references(references),
        "submitted_by": submitter,
        "submitted_at": _now_iso(now),
        "editor_backend": selected_backend,
        "execution_intent": "pending_confirmation",
        "assigned_owner": "",
        "execution_confirmed_at": "",
    }
    _write_payload(path, payload)
    return _to_change_request(path, payload)


def note_change_request(vault_root: Path, change_request_id: str, *, noted_by: str, now: datetime | None = None) -> ChangeRequest:
    """Record an idea as note-only. No phase, revision, task, or block changes."""

    request = load_change_request(vault_root, change_request_id)
    if request.status != "pending_confirmation":
        raise ContentOSContractError("只有待确认的修改单可以先记下")
    actor = str(noted_by or "").strip()
    if not actor:
        raise ContentOSContractError("需要记录是谁选择了先记下")
    payload = dict(request.payload)
    payload.update(
        {
            "request_status": "noted",
            "noted_by": actor,
            "noted_at": _now_iso(now),
            "execution_intent": "note_only",
        }
    )
    _write_payload(request.path, payload)
    return _to_change_request(request.path, payload)


def confirm_change_request(
    vault_root: Path,
    change_request_id: str,
    *,
    confirmed_by: str,
    now: datetime | None = None,
) -> ChangeRequest:
    """Record explicit human impact confirmation, but do not enqueue work yet."""

    request = load_change_request(vault_root, change_request_id)
    if request.status != "pending_confirmation":
        raise ContentOSContractError("只有待确认的修改单可以确认执行")
    confirmer = str(confirmed_by or "").strip()
    if not confirmer:
        raise ContentOSContractError("确认执行时必须记录确认人")
    state = read_project_state(vault_root, request.project_id)
    if state.project_revision != request.project_revision:
        raise ContentOSContractError("项目已有新版本；这条修改单已过期，请重新提交")
    payload = dict(request.payload)
    payload.update(
        {
            "request_status": "confirmed",
            "execution_intent": "apply_change",
            "confirmed_by": confirmer,
            "confirmed_at": _now_iso(now),
        }
    )
    _write_payload(request.path, payload)
    return _to_change_request(request.path, payload)


def mark_change_request_executing(vault_root: Path, change_request_id: str, *, task_id: str, now: datetime | None = None) -> ChangeRequest:
    """Mark a confirmed request executing after a queue task has been created."""

    request = load_change_request(vault_root, change_request_id)
    if request.status != "confirmed":
        raise ContentOSContractError("只有人工确认的修改单可以开始执行")
    task = str(task_id or "").strip()
    if not task:
        raise ContentOSContractError("开始执行必须关联任务编号")
    payload = dict(request.payload)
    payload.update(
        {
            "request_status": "executing",
            "execution_task_id": task,
            "assigned_owner": "mac_openclaw",
            "execution_confirmed_at": str(payload.get("confirmed_at") or _now_iso(now)),
            "executing_at": _now_iso(now),
        }
    )
    _write_payload(request.path, payload)
    return _to_change_request(request.path, payload)
