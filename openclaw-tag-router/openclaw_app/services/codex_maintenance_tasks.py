"""Durable v2 task contract for full-access Codex maintenance work."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import signal
import shutil
import subprocess
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from common.env import parse_env_file as _canonical_parse_env_file
from common.social_runtime import parse_iso_datetime

from .deepmath_runtime_config import DEEPMATH_ENV_FILE_ENV
from .deepmath_runtime_config import deepmath_env_file as _canonical_deepmath_env_file


SCHEMA_VERSION = 2
TASK_ID_RE = re.compile(r"^codex_[0-9a-f]{24}$")
STATUS_COMMAND_RE = re.compile(
    r"【\s*codex\s*】\s*(?:状态|进度|status)\s*[:：]?\s*(codex_[0-9a-f]{24})\b",
    flags=re.I,
)
TERMINAL_STATUSES = {"succeeded", "failed"}
PLANNED_MODEL = "gpt-5.6-sol"
PLANNED_THINKING = "high"
RESUME_INSTRUCTION = (
    "继续完成当前维护目标；不要重复已经完成的工具调用或写入。"
    "你就是当前维护任务的执行者；不要读取、轮询或等待当前 task 的 state.json、"
    "events.jsonl、final.txt 或 worker/child 进程，这些运行状态描述的是你自身。"
    "直接依据已完成上下文推进目标，完成后返回完整最终结果。"
)
OPENCLAW_BIN_ENV = "OPENCLAW_BIN"
CODEX_BIN_ENV = "OPENCLAW_CODEX_BIN"
CODEX_WORKING_DIRECTORY_ENV = "OPENCLAW_CODEX_WORKING_DIRECTORY"
WORKER_HEALTH_MAX_AGE_SECONDS = 15
DEEPMATH_TENANT_PROFILE = "deepmath"
DEEPMATH_ENV_FILE: Path | None = None
DEEPMATH_CODEX_EXECUTION_CONTRACT = """\
DeepMath tenant execution contract:
- This task originated from the DeepMath Feishu account. Use only the DeepMath tenant credentials supplied in the process environment. Never use the default/main, media, daily, social, or knowledge Feishu credentials.
- This is the same full-access Codex maintenance and development capability used by the other OpenClaw Bots. For local engineering requests, inspect and modify the relevant code, configuration, tests, Markdown, Obsidian notes, or other repository documentation under the authorized workspace, then run risk-proportional validation. Do not reject a local code or documentation task merely because it has no Feishu URL.
- Apply the remaining document rules only when the request asks to read or write a Feishu Wiki/Docx document. Such a write requires an explicit Feishu wiki/docx URL in the current request. If the Feishu target is missing or ambiguous, do not write; return needs_target/manual with the missing input.
- Before writing, resolve the Wiki node with the live API and verify it is readable through the DeepMath application identity.
- Read the live Docx block tree and build a structured working copy. Preserve images, attachments, callouts, native tables, and rich structures by default. Only apply operations proven safe for the current block type.
- Edit the same document in place. Do not append a patch section, create a v2 copy, or replace the document through Markdown/plain-text flattening.
- Re-read the changed blocks and raw content after writing. Report completion only when readback proves the requested change and protected structures remain present. Otherwise return pending/manual with the exact blocked operation.
- Do not modify OpenClaw code/config merely because the request asks to edit a Feishu document. Modify system code when the user explicitly requests engineering, maintenance, configuration, capability, or repository-documentation work.
"""


def parse_status_task_id(value: object) -> str:
    match = STATUS_COMMAND_RE.search(str(value or ""))
    return match.group(1).lower() if match else ""


def task_root() -> Path:
    configured = os.environ.get("OPENCLAW_CODEX_TASK_ROOT", "").strip()
    return Path(configured).expanduser() if configured else Path.home() / ".openclaw" / "state" / "codex_maintenance_tasks"


def codex_home() -> Path:
    configured = os.environ.get("CODEX_HOME", "").strip()
    return Path(configured).expanduser() if configured else Path.home() / ".codex"


def _executable_from_environment(environment_key: str, command_name: str) -> str:
    configured = os.environ.get(environment_key, "").strip()
    return configured or shutil.which(command_name) or command_name


def openclaw_bin() -> str:
    return _executable_from_environment(OPENCLAW_BIN_ENV, "openclaw")


def codex_bin() -> str:
    return _executable_from_environment(CODEX_BIN_ENV, "codex")


def deepmath_env_file() -> Path:
    configured = os.environ.get(DEEPMATH_ENV_FILE_ENV, "").strip()
    if configured:
        return Path(configured).expanduser()
    # DEEPMATH_ENV_FILE is a module-local injection seam (tests patch it
    # directly); the portable default itself is owned by
    # deepmath_runtime_config.deepmath_env_file().
    return DEEPMATH_ENV_FILE or _canonical_deepmath_env_file()


def codex_working_directory() -> Path:
    configured = os.environ.get(CODEX_WORKING_DIRECTORY_ENV, "").strip()
    return Path(configured).expanduser() if configured else Path.cwd()


def configured_provider() -> str:
    try:
        config = tomllib.loads((codex_home() / "config.toml").read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, tomllib.TOMLDecodeError):
        return ""
    return str(config.get("model_provider") or "").strip()


def worker_health_path(root: Path | None = None) -> Path:
    return (root or task_root()) / "worker.json"


def make_task_id(message: str, *, account_id: str, message_id: str) -> str:
    if not message_id:
        return "codex_" + secrets.token_hex(12)
    raw = json.dumps(
        {"accountId": account_id or "unknown", "messageId": message_id, "message": message},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return "codex_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def task_dir(task_id: str) -> Path:
    if not TASK_ID_RE.fullmatch(str(task_id or "")):
        raise ValueError("invalid codex task id")
    return task_root() / task_id


def iso_now() -> str:
    return datetime.now(UTC).isoformat()


def parse_timestamp(value: object) -> datetime | None:
    # Consolidated into common/social_runtime.parse_iso_datetime (H9). A
    # naive input is assumed UTC; an already tz-aware input is returned
    # as parsed (NOT forced to UTC).
    return parse_iso_datetime(value, assume_tz=UTC)


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    descriptor = os.open(temporary, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    temporary.replace(path)


def read_state(directory: Path) -> dict[str, Any]:
    try:
        value = json.loads((directory / "state.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}
    if not isinstance(value, dict) or value.get("schemaVersion") != SCHEMA_VERSION:
        return {}
    return value


def write_state(directory: Path, state: dict[str, Any]) -> None:
    if state.get("schemaVersion") != SCHEMA_VERSION:
        raise ValueError("Codex maintenance state must use schemaVersion 2")
    atomic_write_json(directory / "state.json", state)


def pid_is_alive(value: object) -> bool:
    try:
        pid = int(value)
        if pid <= 0:
            return False
        os.kill(pid, 0)
        return True
    except (TypeError, ValueError, ProcessLookupError):
        return False
    except PermissionError:
        return True


def write_worker_health(root: Path | None = None, *, pid: int | None = None) -> dict[str, Any]:
    now = iso_now()
    health = {
        "schemaVersion": SCHEMA_VERSION,
        "status": "running",
        "pid": int(pid or os.getpid()),
        "heartbeatAt": now,
    }
    atomic_write_json(worker_health_path(root), health)
    return health


def worker_is_available(root: Path | None = None, *, now: datetime | None = None) -> bool:
    try:
        health = json.loads(worker_health_path(root).read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return False
    heartbeat = parse_timestamp(health.get("heartbeatAt")) if isinstance(health, dict) else None
    if health.get("schemaVersion") != SCHEMA_VERSION or health.get("status") != "running" or heartbeat is None:
        return False
    current = now or datetime.now(UTC)
    return pid_is_alive(health.get("pid")) and 0 <= (current - heartbeat).total_seconds() <= WORKER_HEALTH_MAX_AGE_SECONDS


def elapsed_seconds(state: dict[str, Any]) -> int:
    started = parse_timestamp(state.get("startedAt") or state.get("createdAt"))
    return max(0, int((datetime.now(UTC) - started).total_seconds())) if started else 0


def delivery_from_payload(payload: dict[str, Any]) -> dict[str, str]:
    if str(payload.get("source") or "") != "feishu":
        return {}
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    account_id = str(metadata.get("account_id") or metadata.get("account") or "").strip()
    sender_id = str(metadata.get("source_sender_id") or "").strip()
    if not account_id or not sender_id:
        return {}
    return {"channel": "feishu", "accountId": account_id, "target": f"user:{sender_id}"}


def tenant_profile_for_account(account_id: str) -> str:
    return DEEPMATH_TENANT_PROFILE if str(account_id or "").strip().lower() == "deepmath" else "default"


def parse_env_file(path: Path) -> dict[str, str]:
    # Required-file contract preserved (dedup pe-01): this reader has no
    # exists() guard today, so a missing DeepMath env file raises OSError
    # straight out of execution_environment() below. require=True keeps
    # that fail-closed behavior (the same OSError subtype, e.g.
    # FileNotFoundError, propagates unchanged) instead of quietly
    # returning {} and falling through to a less specific error.
    return _canonical_parse_env_file(path, require=True)


def execution_environment(state: dict[str, Any], base: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(base or os.environ)
    if state.get("tenantProfile") != DEEPMATH_TENANT_PROFILE:
        return env
    values = parse_env_file(deepmath_env_file())
    required = {
        "OPENCLAW_STATE_DIR",
        "OPENCLAW_CONFIG_PATH",
        "OPENCLAW_DEEPMATH_APP_ID",
        "OPENCLAW_DEEPMATH_APP_SECRET",
    }
    missing = sorted(key for key in required if not values.get(key))
    if missing:
        raise ValueError(f"DeepMath execution environment missing: {', '.join(missing)}")
    for key in ("FEISHU_APP_ID", "FEISHU_APP_SECRET"):
        env.pop(key, None)
    env.update(values)
    return env


def agent_request(message: str, state: dict[str, Any]) -> str:
    if state.get("tenantProfile") != DEEPMATH_TENANT_PROFILE:
        return message
    return f"{DEEPMATH_CODEX_EXECUTION_CONTRACT}\nUser request (verbatim):\n{message}"


def unavailable_state(task_id: str, code: str, summary: str, *, planned_provider: str = "") -> dict[str, Any]:
    now = iso_now()
    return {
        "schemaVersion": SCHEMA_VERSION,
        "taskId": task_id,
        "status": "failed",
        "phase": "enqueue_rejected",
        "toolType": "Codex maintenance worker",
        "createdAt": now,
        "updatedAt": now,
        "heartbeatAt": now,
        "plannedProvider": planned_provider,
        "plannedModel": PLANNED_MODEL,
        "plannedThinking": PLANNED_THINKING,
        "outcome": "failure",
        "failureCode": code,
        "safeSummary": summary,
    }


def enqueue_task(
    message: str,
    *,
    account_id: str,
    message_id: str,
    delivery: dict[str, str],
    notification_required: bool,
) -> dict[str, Any]:
    identifier = make_task_id(message, account_id=account_id, message_id=message_id)
    root = task_root()
    directory = root / identifier
    existing = read_state(directory)
    if existing:
        return existing
    planned_provider = configured_provider()
    if not planned_provider:
        return unavailable_state(
            identifier,
            "codex_maintenance_provider_unavailable",
            "Codex model_provider 不可读，未创建任务。",
        )
    if not worker_is_available(root):
        return unavailable_state(
            identifier,
            "codex_maintenance_worker_unavailable",
            "Codex 维护 worker 心跳不可用，未创建任务。",
            planned_provider=planned_provider,
        )
    if notification_required and not delivery:
        return unavailable_state(
            identifier,
            "codex_maintenance_notification_target_missing",
            "无法确定飞书发起人，未创建需要主动通知的维护任务。",
            planned_provider=planned_provider,
        )
    root.mkdir(parents=True, exist_ok=True)
    os.chmod(root, 0o700)
    try:
        directory.mkdir(mode=0o700)
    except FileExistsError:
        for _ in range(20):
            existing = read_state(directory)
            if existing:
                return existing
        return unavailable_state(
            identifier,
            "codex_maintenance_state_missing",
            "任务目录已存在但 v2 状态不可读，未重复创建。",
            planned_provider=planned_provider,
        )

    tenant_profile = tenant_profile_for_account(account_id)
    request_path = directory / "request.md"
    descriptor = os.open(request_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(agent_request(message, {"tenantProfile": tenant_profile}))
        handle.flush()
        os.fsync(handle.fileno())
    now = iso_now()
    state: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "taskId": identifier,
        "status": "queued",
        "phase": "queued",
        "toolType": "Codex maintenance worker",
        "createdAt": now,
        "updatedAt": now,
        "heartbeatAt": now,
        "safeSummary": "任务已持久化，等待独立 Codex worker 领取。",
        "outcome": "pending",
        "plannedProvider": planned_provider,
        "plannedModel": PLANNED_MODEL,
        "plannedThinking": PLANNED_THINKING,
        "tenantProfile": tenant_profile,
        "delivery": dict(delivery),
        "notificationState": "pending" if delivery else "disabled",
        "notifications": {},
        "attempt": 0,
    }
    write_state(directory, state)
    return state


def status_snapshot(task_id: str) -> dict[str, Any]:
    try:
        return read_state(task_dir(task_id))
    except ValueError:
        return {}


def agent_command(
    directory: Path,
    task_id: str,
    planned_provider: str,
    *,
    resume_thread_id: str = "",
    working_directory: Path | None = None,
) -> list[str]:
    if not planned_provider.strip():
        raise ValueError("Codex maintenance task requires a frozen planned provider")
    command = [
        codex_bin(),
        "exec",
    ]
    if resume_thread_id:
        if session_path_for_thread(resume_thread_id) is None:
            raise ValueError("Codex maintenance resume thread is unavailable")
        command.append("resume")
    command.extend([
        "--dangerously-bypass-approvals-and-sandbox",
        "--dangerously-bypass-hook-trust",
        "--skip-git-repo-check",
        "--model",
        PLANNED_MODEL,
        "--config",
        f"model_provider={json.dumps(planned_provider)}",
        "--config",
        'model_reasoning_effort="high"',
        "--json",
        "--output-last-message",
        str(directory / "final.txt"),
    ])
    if resume_thread_id:
        command.extend([resume_thread_id, RESUME_INSTRUCTION])
    else:
        command.extend(["--cd", str(working_directory or codex_working_directory()), "-"])
    return command


def parse_openclaw_json(output: str) -> dict[str, Any]:
    text = output.strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        pass
    decoder = json.JSONDecoder()
    candidates: list[dict[str, Any]] = []
    for match in re.finditer(r"\{", text):
        try:
            parsed, _ = decoder.raw_decode(text[match.start() :])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            candidates.append(parsed)
    return candidates[-1] if candidates else {}


def thread_id_from_events(output: str) -> str:
    for line in output.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "thread.started":
            return str(event.get("thread_id") or "").strip()
    return ""


def session_path_for_thread(thread_id: str) -> Path | None:
    if not re.fullmatch(r"[0-9a-f-]{36}", thread_id):
        return None
    matches = list((codex_home() / "sessions").glob(f"**/*{thread_id}.jsonl"))
    return matches[0] if len(matches) == 1 else None


def extract_runtime_contract(events_output: str) -> dict[str, str]:
    session_path = session_path_for_thread(thread_id_from_events(events_output))
    if session_path is None:
        return {}
    provider = ""
    model = ""
    thinking = ""
    for line in session_path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        if event.get("type") == "session_meta":
            provider = str(payload.get("model_provider") or provider).strip()
        elif event.get("type") == "turn_context":
            model = str(payload.get("model") or model).strip()
            thinking = str(payload.get("effort") or thinking).strip()
    if not provider or not model or not thinking:
        return {}
    return {"provider": provider, "model": model, "thinking": thinking}


def runtime_contract_matches(runtime: dict[str, str], state: dict[str, Any]) -> bool:
    return runtime == {
        "provider": str(state.get("plannedProvider") or ""),
        "model": PLANNED_MODEL,
        "thinking": PLANNED_THINKING,
    }


def terminate_process_group(proc: subprocess.Popen[Any], *, grace_seconds: float = 15.0) -> None:
    if proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        proc.wait(timeout=grace_seconds)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    proc.wait(timeout=5)
