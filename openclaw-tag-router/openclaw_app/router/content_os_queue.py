"""Content OS v0.2 Mac queue and evidence reconciliation.

This module binds every Mac task/result to one project version, one selected
editing backend, and (for modifications) one confirmed change request.  It
accepts Mac results as evidence only; project-stage transitions stay in
``content_os_project_lifecycle`` and are performed by a cloud or human action.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from typing import Any, Iterable

import yaml

from .content_os_change_requests import (
    ChangeRequest,
    load_change_request,
    mark_change_request_executing,
)
from .content_os_project_lifecycle import (
    CONTENT_OS_SPEC_VERSION,
    ContentOSContractError,
    EDITOR_BACKENDS,
    ProjectState,
    activate_confirmed_revision,
    read_project_state,
)


READY_DIRECTORY = Path("98_Agent任务队列") / "01_cloud_to_mac_ready"
RESULT_DIRECTORY = Path("98_Agent任务队列") / "02_mac_to_cloud_results"
DONE_DIRECTORY = Path("98_Agent任务队列") / "04_mac_done"

TASK_BACKENDS: dict[str, frozenset[str]] = {
    "local_material_match": frozenset(EDITOR_BACKENDS),
    "generate_edit_handoff_pack": frozenset({"handoff_pack"}),
    "revise_local_edit_artifacts": frozenset(EDITOR_BACKENDS),
    "generate_otio_kdenlive_timeline": frozenset({"otio_kdenlive"}),
    "local_output_review": frozenset(EDITOR_BACKENDS),
    "generate_ai_edit_log": frozenset(EDITOR_BACKENDS),
}


@dataclass(frozen=True)
class ReadyTask:
    task_id: str
    task_type: str
    project_id: str
    project_revision: int
    change_request_id: str
    editor_backend: str
    path: Path
    payload: dict[str, Any]


@dataclass(frozen=True)
class AcceptedMacResult:
    task: ReadyTask
    result_path: Path
    done_task_path: Path


def _now_iso(now: datetime | None = None) -> str:
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


def _now_date(now: datetime | None = None) -> str:
    return (now or datetime.now(timezone.utc)).strftime("%Y%m%d")


def _safe_task_id(value: str) -> str:
    task_id = str(value or "").strip()
    if not re.fullmatch(r"task_\d{8}_\d{3}", task_id):
        raise ContentOSContractError("task_id 格式不正确")
    return task_id


def _as_revision(value: Any, *, name: str) -> int:
    if isinstance(value, bool):
        raise ContentOSContractError(f"{name} 必须是从 1 开始的整数")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ContentOSContractError(f"{name} 必须是从 1 开始的整数") from exc
    if parsed < 1:
        raise ContentOSContractError(f"{name} 必须是从 1 开始的整数")
    return parsed


def _tenant_id(value: Any, *, name: str = "tenant_id") -> str:
    tenant_id = str(value or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,160}", tenant_id):
        raise ContentOSContractError(f"{name} 格式不正确")
    return tenant_id


def _queue_root(vault_root: Path, directory: Path) -> Path:
    return Path(vault_root) / directory


def _write_yaml(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = yaml.safe_dump(payload, allow_unicode=True, sort_keys=False).rstrip() + "\n"
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(rendered, encoding="utf-8")
    os.replace(temporary, path)


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ContentOSContractError("任务不存在")
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ContentOSContractError("任务或结果无法读取") from exc
    if not isinstance(payload, dict):
        raise ContentOSContractError("任务或结果必须是对象")
    return payload


def _task_path(vault_root: Path, task_id: str, task_type: str) -> Path:
    return _queue_root(vault_root, READY_DIRECTORY) / f"{_safe_task_id(task_id)}_{task_type}.yaml"


def _validate_task_type_backend(task_type: str, editor_backend: str) -> tuple[str, str]:
    type_name = str(task_type or "").strip()
    backend = str(editor_backend or "").strip()
    if type_name not in TASK_BACKENDS:
        raise ContentOSContractError("任务类型不在 Content OS v0.2 白名单中")
    if backend not in EDITOR_BACKENDS:
        raise ContentOSContractError("任务未选择受支持的剪辑方式")
    if backend not in TASK_BACKENDS[type_name]:
        raise ContentOSContractError("这个任务类型不支持所选剪辑方式；系统不会自动切换")
    return type_name, backend


def _to_ready_task(path: Path, payload: dict[str, Any]) -> ReadyTask:
    if payload.get("spec_version") != CONTENT_OS_SPEC_VERSION or payload.get("doc_type") != "mac_task":
        raise ContentOSContractError("任务不是 Content OS v0.2 格式")
    if payload.get("status") != "ready" or payload.get("owner") != "mac_openclaw":
        raise ContentOSContractError("任务不在可执行的 Mac ready 状态")
    task_id = _safe_task_id(str(payload.get("task_id") or ""))
    task_type, backend = _validate_task_type_backend(payload.get("task_type"), payload.get("editor_backend"))
    if path.name != f"{task_id}_{task_type}.yaml":
        raise ContentOSContractError("任务文件名必须包含 task_id 和 task_type")
    project_id = str(payload.get("project_id") or "").strip()
    if not project_id:
        raise ContentOSContractError("任务缺少 project_id")
    request_id = str(payload.get("change_request_id") or "").strip()
    return ReadyTask(
        task_id=task_id,
        task_type=task_type,
        project_id=project_id,
        project_revision=_as_revision(payload.get("project_revision"), name="project_revision"),
        change_request_id=request_id,
        editor_backend=backend,
        path=path,
        payload=payload,
    )


def load_ready_task(vault_root: Path, task_id: str) -> ReadyTask:
    task_id = _safe_task_id(task_id)
    matches = list(_queue_root(vault_root, READY_DIRECTORY).glob(f"{task_id}_*.yaml"))
    if len(matches) != 1:
        raise ContentOSContractError("找不到唯一的 ready 任务")
    path = matches[0]
    return _to_ready_task(path, _read_yaml(path))


def _next_task_id(vault_root: Path, now: datetime | None) -> str:
    date = _now_date(now)
    pattern = re.compile(rf"task_{date}_(\d{{3}})_[A-Za-z0-9_]+\.yaml\Z")
    highest = 0
    for directory in (READY_DIRECTORY, RESULT_DIRECTORY, DONE_DIRECTORY):
        root = _queue_root(vault_root, directory)
        if not root.exists():
            continue
        for path in root.glob(f"task_{date}_*.yaml"):
            match = pattern.fullmatch(path.name)
            if match:
                highest = max(highest, int(match.group(1)))
    return f"task_{date}_{highest + 1:03d}"


def _require_current_identity(state: ProjectState, *, project_revision: int, editor_backend: str) -> None:
    if state.project_revision != project_revision:
        raise ContentOSContractError("项目版本已变化；任务或结果已过期")
    if state.editor_backend != editor_backend:
        raise ContentOSContractError("项目当前剪辑方式与任务不一致；不允许自动回退")


def _assert_no_active_task(vault_root: Path, project_id: str, project_revision: int) -> None:
    root = _queue_root(vault_root, READY_DIRECTORY)
    if not root.exists():
        return
    for path in root.glob("task_*.yaml"):
        try:
            task = _to_ready_task(path, _read_yaml(path))
        except ContentOSContractError:
            continue
        if task.project_id == project_id and task.project_revision == project_revision:
            raise ContentOSContractError("这个项目版本已有待执行的 Mac 任务，不能重复派发")


def create_ready_task(
    vault_root: Path,
    project_id: str,
    *,
    task_type: str,
    project_revision: int,
    change_request_id: str,
    editor_backend: str,
    human_confirmed_impact: bool = False,
    inputs: dict[str, Any] | None = None,
    expected_outputs: Iterable[str] | None = None,
    allowed_actions: Iterable[str] | None = None,
    notes: Iterable[str] | None = None,
    tenant_id: str | None = None,
    now: datetime | None = None,
) -> ReadyTask:
    """Create one canonical Mac task after its identity is checked against SSOT."""

    task_type, backend = _validate_task_type_backend(task_type, editor_backend)
    state = read_project_state(vault_root, project_id)
    revision = _as_revision(project_revision, name="project_revision")
    _require_current_identity(state, project_revision=revision, editor_backend=backend)
    _assert_no_active_task(vault_root, state.project_id, revision)
    idea_id = str(state.frontmatter.get("idea_id") or "").strip()
    if not idea_id:
        raise ContentOSContractError("项目总览缺少 idea_id，不能派发 Mac 任务")
    is_change_task = bool(str(change_request_id or "").strip())
    if task_type == "revise_local_edit_artifacts" and not (is_change_task and human_confirmed_impact):
        raise ContentOSContractError("修改任务必须关联修改单且已人工确认影响")
    task_id = _next_task_id(vault_root, now)
    payload: dict[str, Any] = {
        "spec_version": CONTENT_OS_SPEC_VERSION,
        "doc_type": "mac_task",
        "task_id": task_id,
        "task_type": task_type,
        "created_by": "cloud_openclaw",
        "owner": "mac_openclaw",
        "status": "ready",
        "project_id": state.project_id,
        "project_revision": revision,
        "idea_id": idea_id,
        "change_request_id": str(change_request_id or "").strip(),
        "editor_backend": backend,
        "human_confirmed_impact": bool(human_confirmed_impact),
        "created_at": _now_iso(now),
        "inputs": dict(inputs or {}),
        "expected_outputs": [str(item).strip() for item in (expected_outputs or []) if str(item).strip()],
        "allowed_actions": [str(item).strip() for item in (allowed_actions or []) if str(item).strip()],
        "notes": [str(item).strip() for item in (notes or []) if str(item).strip()],
    }
    if tenant_id is not None:
        payload["tenant_id"] = _tenant_id(tenant_id)
    path = _task_path(vault_root, task_id, task_type)
    _write_yaml(path, payload)
    return _to_ready_task(path, payload)


def enqueue_confirmed_change(
    vault_root: Path,
    change_request_id: str,
    *,
    task_type: str,
    inputs: dict[str, Any] | None = None,
    expected_outputs: Iterable[str] | None = None,
    allowed_actions: Iterable[str] | None = None,
    notes: Iterable[str] | None = None,
    tenant_id: str | None = None,
    now: datetime | None = None,
) -> ReadyTask:
    """Start the next revision and queue work only for a human-confirmed change."""

    request: ChangeRequest = load_change_request(vault_root, change_request_id)
    if request.status != "confirmed" or request.payload.get("execution_intent") != "apply_change":
        raise ContentOSContractError("只有人工确认影响的修改单才能创建执行任务")
    _validate_task_type_backend(task_type, request.editor_backend)
    state = read_project_state(vault_root, request.project_id)
    if state.project_revision != request.project_revision:
        raise ContentOSContractError("项目已有新版本；修改单已过期，不能执行")
    if request.target_revision != state.project_revision + 1:
        raise ContentOSContractError("修改单目标版本不正确，不能执行")
    _assert_no_active_task(vault_root, state.project_id, request.target_revision)
    next_state = activate_confirmed_revision(
        vault_root,
        request.project_id,
        expected_revision=request.project_revision,
        editor_backend=request.editor_backend,
        change_request_id=request.change_request_id,
        human_confirmed_impact=True,
        now=now,
    )
    if next_state.project_revision != request.target_revision:
        raise ContentOSContractError("项目版本与修改单目标版本不一致")
    try:
        task = create_ready_task(
            vault_root,
            request.project_id,
            task_type=task_type,
            project_revision=next_state.project_revision,
            change_request_id=request.change_request_id,
            editor_backend=request.editor_backend,
            human_confirmed_impact=True,
            inputs=inputs,
            expected_outputs=expected_outputs,
            allowed_actions=allowed_actions,
            notes=notes,
            tenant_id=tenant_id,
            now=now,
        )
    except Exception as exc:
        # The revision is intentionally not silently rolled back. It records
        # the human decision and makes an interrupted handoff visible for
        # recovery rather than risking a second hidden source of truth.
        raise ContentOSContractError("已确认修改，但创建 Mac 任务失败；请处理后从当前版本重新派发") from exc
    mark_change_request_executing(vault_root, request.change_request_id, task_id=task.task_id, now=now)
    return task


def validate_mac_result(
    vault_root: Path,
    result: dict[str, Any],
    *,
    expected_tenant_id: str | None = None,
) -> ReadyTask:
    """Verify a Mac result identity without writing project state or registry."""

    if not isinstance(result, dict):
        raise ContentOSContractError("Mac result 必须是对象")
    if result.get("spec_version") != CONTENT_OS_SPEC_VERSION or result.get("doc_type") != "mac_result":
        raise ContentOSContractError("Mac result 不是 Content OS v0.2 格式")
    if result.get("completed_by") != "mac_openclaw" or result.get("status") not in {"done", "blocked"}:
        raise ContentOSContractError("Mac result 的完成者或状态不正确")
    if "proposed_next_status" in result or "project_status" in result:
        raise ContentOSContractError("Mac result 不得提出或写入项目阶段")
    task = load_ready_task(vault_root, str(result.get("task_id") or ""))
    task_tenant_id = task.payload.get("tenant_id")
    if expected_tenant_id is not None:
        authenticated_tenant_id = _tenant_id(expected_tenant_id, name="authenticated tenant_id")
        if _tenant_id(task_tenant_id, name="task tenant_id") != authenticated_tenant_id:
            raise ContentOSContractError("Mac 任务不属于当前设备租户；结果已拒绝")
        if _tenant_id(result.get("tenant_id"), name="result tenant_id") != authenticated_tenant_id:
            raise ContentOSContractError("Mac result 的 tenant_id 与当前设备租户不一致；结果已拒绝")
    elif task_tenant_id is not None:
        if _tenant_id(result.get("tenant_id"), name="result tenant_id") != _tenant_id(task_tenant_id, name="task tenant_id"):
            raise ContentOSContractError("Mac result 的 tenant_id 与任务不一致；结果已拒绝")
    for field, expected in (
        ("task_type", task.task_type),
        ("project_id", task.project_id),
        ("project_revision", task.project_revision),
        ("change_request_id", task.change_request_id),
        ("editor_backend", task.editor_backend),
    ):
        observed = result.get(field)
        if field == "project_revision":
            observed = _as_revision(observed, name="result.project_revision")
        else:
            observed = str(observed or "").strip()
        if observed != expected:
            raise ContentOSContractError(f"Mac result 的 {field} 与任务不一致；结果已过期或投递错误")
    state = read_project_state(vault_root, task.project_id)
    _require_current_identity(state, project_revision=task.project_revision, editor_backend=task.editor_backend)
    return task


def accept_mac_result(
    vault_root: Path,
    result: dict[str, Any],
    *,
    expected_tenant_id: str | None = None,
    now: datetime | None = None,
) -> AcceptedMacResult:
    """Store validated Mac evidence and close its task without altering project stage."""

    result_root = _queue_root(vault_root, RESULT_DIRECTORY)
    done_root = _queue_root(vault_root, DONE_DIRECTORY)
    task_id = _safe_task_id(str(result.get("task_id") or ""))
    task_type = str(result.get("task_type") or "").strip()
    if task_type not in TASK_BACKENDS:
        raise ContentOSContractError("Mac result 的 task_type 不受支持")
    result_path = result_root / f"accepted_{task_id.removeprefix('task_')}_{task_type}.yaml"
    done_path = done_root / f"{task_id}_{task_type}.yaml"
    if result_path.exists() or done_path.exists():
        # A retry after a lost acknowledgement is safe when it is byte-equivalent
        # to the evidence already committed. Changed evidence remains a conflict.
        if result_path.is_file() and done_path.is_file():
            stored = _read_yaml(result_path)
            stored_source = {key: value for key, value in stored.items() if key not in {"accepted_by", "accepted_at"}}
            incoming = json.loads(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
            existing = json.loads(json.dumps(stored_source, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
            if incoming == existing:
                done_payload = _read_yaml(done_path)
                if expected_tenant_id is not None:
                    authenticated_tenant_id = _tenant_id(expected_tenant_id, name="authenticated tenant_id")
                    if _tenant_id(result.get("tenant_id"), name="result tenant_id") != authenticated_tenant_id:
                        raise ContentOSContractError("Mac result 的 tenant_id 与当前设备租户不一致；结果已拒绝")
                return AcceptedMacResult(
                    task=ReadyTask(
                        task_id=task_id,
                        task_type=task_type,
                        project_id=str(done_payload.get("project_id") or ""),
                        project_revision=_as_revision(done_payload.get("project_revision"), name="done.project_revision"),
                        change_request_id=str(done_payload.get("change_request_id") or ""),
                        editor_backend=str(done_payload.get("editor_backend") or ""),
                        path=done_path,
                        payload=done_payload,
                    ),
                    result_path=result_path,
                    done_task_path=done_path,
                )
        raise ContentOSContractError("这个任务已有已接收的不同结果，不能覆盖原有证据")
    task = validate_mac_result(vault_root, result, expected_tenant_id=expected_tenant_id)
    accepted_payload = dict(result)
    accepted_payload["accepted_by"] = "cloud_openclaw"
    accepted_payload["accepted_at"] = _now_iso(now)
    _write_yaml(result_path, accepted_payload)
    done_payload = dict(task.payload)
    done_payload.update({"status": str(result.get("status") or "done"), "completed_at": _now_iso(now), "result_path": str(result_path.relative_to(vault_root))})
    _write_yaml(done_path, done_payload)
    task.path.unlink()
    return AcceptedMacResult(task=task, result_path=result_path, done_task_path=done_path)
