#!/usr/bin/env python3
"""Single-owner worker for durable Codex maintenance tasks."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import signal
import subprocess
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from openclaw_app.services import codex_maintenance_tasks as tasks


DEFAULT_POLL_SECONDS = 2.0
HEARTBEAT_SECONDS = 30
LEASE_SECONDS = 90
PROGRESS_NOTIFICATION_SECONDS = 120
NOTIFICATION_RETRY_SECONDS = 30
TASK_MAX_SECONDS = 21600
MESSAGE_TIMEOUT_SECONDS = 20
MAX_AGENT_ATTEMPTS = 3
AGENT_RETRY_DELAYS_SECONDS = (15, 45)


def progress_notification_due(
    state: dict[str, Any], *, now: datetime, interval_seconds: int = PROGRESS_NOTIFICATION_SECONDS
) -> bool:
    anchor = tasks.parse_timestamp(state.get("lastProgressNotificationAt") or state.get("startedAt"))
    return bool(anchor and (now - anchor).total_seconds() >= interval_seconds)


def retry_due(state: dict[str, Any], key: str, *, now: datetime) -> bool:
    scheduled = tasks.parse_timestamp(state.get(key))
    return scheduled is None or now >= scheduled


def agent_failure_detail(events_output: str, stderr_output: str = "") -> str:
    messages: list[str] = []
    for line in events_output.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "turn.failed" and isinstance(event.get("error"), dict):
            message = str(event["error"].get("message") or "").strip()
        elif event.get("type") == "error":
            message = str(event.get("message") or "").strip()
        else:
            message = ""
        if message:
            messages.append(message)
    detail = messages[-1] if messages else stderr_output.strip()
    return " ".join(detail.split())[:500]


def is_model_capacity_failure(detail: str) -> bool:
    return "selected model is at capacity" in detail.casefold()


def agent_retry_delay(attempt: int) -> int:
    index = min(max(attempt, 1), len(AGENT_RETRY_DELAYS_SECONDS)) - 1
    return AGENT_RETRY_DELAYS_SECONDS[index]


def parse_message_id(output: str) -> str:
    payload = tasks.parse_openclaw_json(output)
    nested = payload.get("payload") if isinstance(payload.get("payload"), dict) else {}
    return str(payload.get("messageId") or nested.get("messageId") or "").strip()


class CodexMaintenanceWorker:
    def __init__(
        self,
        *,
        root: Path | None = None,
        poll_seconds: float = DEFAULT_POLL_SECONDS,
        heartbeat_seconds: int = HEARTBEAT_SECONDS,
        progress_seconds: int = PROGRESS_NOTIFICATION_SECONDS,
        task_max_seconds: int = TASK_MAX_SECONDS,
        working_directory: Path | None = None,
    ) -> None:
        self.root = root or tasks.task_root()
        self.working_directory = working_directory or tasks.codex_working_directory()
        self.poll_seconds = max(0.2, poll_seconds)
        self.heartbeat_seconds = max(5, heartbeat_seconds)
        self.progress_seconds = max(1, progress_seconds)
        self.task_max_seconds = max(60, task_max_seconds)
        self.stopping = False
        self.reload_requested = False
        self.active_process: subprocess.Popen[Any] | None = None
        self.active_directory: Path | None = None

    def install_signal_handlers(self) -> None:
        def stop(_signum: int, _frame: object) -> None:
            self.stopping = True

        def reload_after_task(_signum: int, _frame: object) -> None:
            self.reload_requested = True

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        signal.signal(signal.SIGHUP, reload_after_task)

    def task_directories(self) -> list[Path]:
        return sorted(
            (path for path in self.root.glob("codex_*") if path.is_dir() and tasks.TASK_ID_RE.fullmatch(path.name)),
            key=lambda path: path.stat().st_mtime,
        )

    def fail_orphaned_running_tasks(self) -> None:
        for directory in self.task_directories():
            state = tasks.read_state(directory)
            if state.get("status") != "running":
                continue
            now = tasks.iso_now()
            state.update(
                {
                    "status": "failed",
                    "phase": "worker_interrupted",
                    "outcome": "failure",
                    "failureCode": "codex_maintenance_worker_interrupted",
                    "safeSummary": "Codex worker 中断，该任务已失败关闭，不会自动重跑。",
                    "updatedAt": now,
                    "heartbeatAt": now,
                    "completedAt": now,
                    "notificationState": "pending" if state.get("delivery") else "disabled",
                }
            )
            (directory / "request.md").unlink(missing_ok=True)
            tasks.write_state(directory, state)

    def next_queued_task(self) -> Path | None:
        now = datetime.now(UTC)
        for directory in self.task_directories():
            state = tasks.read_state(directory)
            if state.get("status") == "queued" and retry_due(state, "nextAttemptAt", now=now):
                return directory
        return None

    def send_feishu(self, state: dict[str, Any], text: str) -> dict[str, str]:
        delivery = state.get("delivery") if isinstance(state.get("delivery"), dict) else {}
        if delivery.get("channel") != "feishu" or not delivery.get("accountId") or not delivery.get("target"):
            return {"error": "delivery_not_configured"}
        command = [
            tasks.openclaw_bin(),
            "message",
            "send",
            "--channel",
            "feishu",
            "--account",
            str(delivery["accountId"]),
            "--target",
            str(delivery["target"]),
            "--message",
            text,
            "--json",
        ]
        try:
            process = subprocess.run(
                command,
                text=True,
                capture_output=True,
                timeout=MESSAGE_TIMEOUT_SECONDS,
                env=tasks.execution_environment(state),
            )
        except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
            return {"error": str(exc)}
        message_id = parse_message_id(process.stdout)
        if process.returncode != 0 or not message_id:
            return {"error": (process.stderr or process.stdout or "send_failed")[-1000:]}
        return {"message_id": message_id}

    def progress_text(self, state: dict[str, Any]) -> str:
        return (
            "Codex 维护任务运行中\n"
            f"任务ID：{state['taskId']}\n"
            f"阶段：{state.get('phase') or 'running'}\n"
            f"已运行：{tasks.elapsed_seconds(state)} 秒\n"
            f"最近心跳：{state.get('heartbeatAt') or '未知'}\n"
            f"计划模型：{state.get('plannedModel') or tasks.PLANNED_MODEL}\n"
            f"安全摘要：{state.get('safeSummary') or '维护代理正在执行。'}"
        )

    def terminal_text(self, state: dict[str, Any]) -> str:
        if state.get("status") == "succeeded":
            reply = str(state.get("reply") or "任务已完成。").strip()
            return (
                "Codex 维护任务完成\n"
                f"任务ID：{state['taskId']}\n"
                f"模型：{state.get('runtimeModel') or state.get('plannedModel')}\n\n"
                f"{reply}"
            )
        text = (
            "Codex 维护任务失败\n"
            f"任务ID：{state['taskId']}\n"
            f"错误码：{state.get('failureCode') or 'codex_maintenance_failed'}\n"
            f"阶段：{state.get('phase') or 'failed'}\n"
            f"原因：{state.get('safeSummary') or '任务未完成。'}"
        )
        detail = str(state.get("failureDetail") or "").strip()
        action = str(state.get("suggestedAction") or "").strip()
        if detail:
            text += f"\n详情：{detail}"
        if action:
            text += f"\n建议：{action}"
        return text

    def maybe_send_progress(self, directory: Path, state: dict[str, Any]) -> None:
        if state.get("notificationState") == "disabled":
            return
        now = datetime.now(UTC)
        if not progress_notification_due(state, now=now, interval_seconds=self.progress_seconds):
            return
        if not retry_due(state, "nextProgressNotificationAttemptAt", now=now):
            return
        receipt = self.send_feishu(state, self.progress_text(state))
        if receipt.get("message_id"):
            state["lastProgressNotificationAt"] = now.isoformat()
            state["progressNotificationCount"] = int(state.get("progressNotificationCount") or 0) + 1
            state.setdefault("notifications", {})["lastProgress"] = {
                "messageId": receipt["message_id"],
                "sentAt": now.isoformat(),
            }
            state.pop("nextProgressNotificationAttemptAt", None)
            state.pop("notificationError", None)
        else:
            state["nextProgressNotificationAttemptAt"] = (
                now + timedelta(seconds=NOTIFICATION_RETRY_SECONDS)
            ).isoformat()
            state["notificationError"] = receipt.get("error") or "send_failed"
        tasks.write_state(directory, state)

    def maybe_send_terminal(self, directory: Path, state: dict[str, Any]) -> None:
        if state.get("status") not in tasks.TERMINAL_STATUSES:
            return
        if state.get("notificationState") in {"sent", "disabled"}:
            return
        now = datetime.now(UTC)
        if not retry_due(state, "nextNotificationAttemptAt", now=now):
            return
        receipt = self.send_feishu(state, self.terminal_text(state))
        if receipt.get("message_id"):
            state["notificationState"] = "sent"
            state.setdefault("notifications", {})["terminal"] = {
                "messageId": receipt["message_id"],
                "sentAt": now.isoformat(),
            }
            state.pop("nextNotificationAttemptAt", None)
            state.pop("notificationError", None)
        else:
            state["notificationState"] = "retrying"
            state["nextNotificationAttemptAt"] = (
                now + timedelta(seconds=NOTIFICATION_RETRY_SECONDS)
            ).isoformat()
            state["notificationError"] = receipt.get("error") or "send_failed"
        tasks.write_state(directory, state)

    def retry_terminal_notifications(self) -> None:
        for directory in self.task_directories():
            state = tasks.read_state(directory)
            self.maybe_send_terminal(directory, state)

    def finish_failure(
        self, directory: Path, state: dict[str, Any], *, code: str, phase: str, summary: str
    ) -> None:
        now = tasks.iso_now()
        state.update(
            {
                "status": "failed",
                "phase": phase,
                "outcome": "failure",
                "failureCode": code,
                "safeSummary": summary,
                "updatedAt": now,
                "heartbeatAt": now,
                "completedAt": now,
                "notificationState": "pending" if state.get("delivery") else "disabled",
            }
        )
        (directory / "request.md").unlink(missing_ok=True)
        tasks.write_state(directory, state)
        self.maybe_send_terminal(directory, state)

    def requeue_agent_retry(
        self,
        directory: Path,
        state: dict[str, Any],
        *,
        detail: str,
        resume_thread_id: str,
        events_path: Path,
        error_path: Path,
    ) -> None:
        attempt = int(state.get("attempt") or 0)
        delay = agent_retry_delay(attempt)
        now = datetime.now(UTC)
        for path in (events_path, error_path):
            if path.exists():
                path.replace(directory / f"{path.stem}.attempt-{attempt}{path.suffix}")
        state.update(
            {
                "status": "queued",
                "phase": "agent_retry_wait",
                "outcome": "pending",
                "lastFailureCode": "codex_maintenance_model_capacity",
                "lastFailureDetail": detail,
                "resumeThreadId": resume_thread_id,
                "nextAttemptAt": (now + timedelta(seconds=delay)).isoformat(),
                "updatedAt": now.isoformat(),
                "heartbeatAt": now.isoformat(),
                "leaseExpiresAt": None,
                "childPid": None,
                "safeSummary": (
                    f"计划模型 {state.get('plannedModel') or tasks.PLANNED_MODEL} 容量暂满；"
                    f"第 {attempt} 次运行已保存，将在 {delay} 秒后按同一冻结契约恢复原 thread。"
                ),
            }
        )
        tasks.write_state(directory, state)

    def process_task(self, directory: Path) -> None:
        state = tasks.read_state(directory)
        if state.get("status") != "queued":
            return
        request_path = directory / "request.md"
        if not request_path.is_file():
            self.finish_failure(
                directory,
                state,
                code="codex_maintenance_request_missing",
                phase="request_missing",
                summary="v2 任务缺少请求文件，未启动 Codex。",
            )
            return
        now = tasks.iso_now()
        attempt = int(state.get("attempt") or 0) + 1
        state.pop("nextAttemptAt", None)
        for key in ("completedAt", "failureCode", "failureDetail", "suggestedAction"):
            state.pop(key, None)
        state.update(
            {
                "status": "running",
                "phase": "agent_start",
                "outcome": "pending",
                "workerPid": os.getpid(),
                "attempt": attempt,
                "startedAt": state.get("startedAt") or now,
                "lastAttemptStartedAt": now,
                "updatedAt": now,
                "heartbeatAt": now,
                "leaseExpiresAt": (datetime.now(UTC) + timedelta(seconds=LEASE_SECONDS)).isoformat(),
                "safeSummary": "独立 Codex worker 已领取任务，正在启动本地维护代理。",
            }
        )
        tasks.write_state(directory, state)
        events_path = directory / "events.jsonl"
        final_path = directory / "final.txt"
        error_path = directory / "agent.stderr.log"
        final_path.unlink(missing_ok=True)
        with (
            request_path.open("r", encoding="utf-8") as stdin,
            events_path.open("w", encoding="utf-8") as stdout,
            error_path.open("w", encoding="utf-8") as stderr,
        ):
            os.chmod(events_path, 0o600)
            os.chmod(error_path, 0o600)
            try:
                process = subprocess.Popen(
                    tasks.agent_command(
                        directory,
                        str(state["taskId"]),
                        str(state.get("plannedProvider") or ""),
                        resume_thread_id=str(state.get("resumeThreadId") or ""),
                        working_directory=self.working_directory,
                    ),
                    stdin=stdin,
                    stdout=stdout,
                    stderr=stderr,
                    text=True,
                    start_new_session=True,
                    close_fds=True,
                    cwd=self.working_directory,
                    env=tasks.execution_environment(state),
                )
            except (OSError, ValueError) as exc:
                state["failureDetail"] = str(exc)
                self.finish_failure(
                    directory,
                    state,
                    code="codex_maintenance_agent_start_failed",
                    phase="agent_start_failed",
                    summary="本地 Codex 维护代理无法启动或恢复。",
                )
                return
            self.active_process = process
            self.active_directory = directory
            state["childPid"] = process.pid
            state["phase"] = "agent_running"
            state["safeSummary"] = "Codex 维护代理正在执行；进度每 120 秒主动通知。"
            tasks.write_state(directory, state)
            started = time.monotonic()
            last_heartbeat = started
            while process.poll() is None:
                if self.stopping:
                    tasks.terminate_process_group(process)
                    self.finish_failure(
                        directory,
                        state,
                        code="codex_maintenance_worker_interrupted",
                        phase="worker_interrupted",
                        summary="Codex worker 收到终止信号，已终止模型进程并失败关闭任务。",
                    )
                    return
                elapsed = time.monotonic() - started
                if elapsed >= self.task_max_seconds:
                    tasks.terminate_process_group(process)
                    self.finish_failure(
                        directory,
                        state,
                        code="codex_maintenance_deadline",
                        phase="deadline",
                        summary="Codex 维护任务超过最大运行时限，已终止。",
                    )
                    return
                if time.monotonic() - last_heartbeat >= self.heartbeat_seconds:
                    timestamp = tasks.iso_now()
                    state.update(
                        {
                            "updatedAt": timestamp,
                            "heartbeatAt": timestamp,
                            "leaseExpiresAt": (
                                datetime.now(UTC) + timedelta(seconds=LEASE_SECONDS)
                            ).isoformat(),
                        }
                    )
                    tasks.write_state(directory, state)
                    tasks.write_worker_health(self.root)
                    last_heartbeat = time.monotonic()
                self.maybe_send_progress(directory, state)
                time.sleep(1)
        self.active_process = None
        self.active_directory = None
        events_output = events_path.read_text(encoding="utf-8", errors="replace")
        error_output = error_path.read_text(encoding="utf-8", errors="replace")
        try:
            os.chmod(final_path, 0o600)
            reply = final_path.read_text(encoding="utf-8").strip()
        except (FileNotFoundError, OSError):
            reply = ""
        runtime = tasks.extract_runtime_contract(events_output)
        if process.returncode != 0 or not reply:
            detail = agent_failure_detail(events_output, error_output)
            capacity_failure = is_model_capacity_failure(detail)
            resume_thread_id = tasks.thread_id_from_events(events_output)
            if capacity_failure and resume_thread_id and attempt < MAX_AGENT_ATTEMPTS:
                self.requeue_agent_retry(
                    directory,
                    state,
                    detail=detail,
                    resume_thread_id=resume_thread_id,
                    events_path=events_path,
                    error_path=error_path,
                )
                return
            if capacity_failure:
                state["failureDetail"] = detail
                state["suggestedAction"] = (
                    "模型容量恢复后重新提交相同维护目标。"
                    if resume_thread_id
                    else "原 Codex thread 标识不可用，无法安全续跑；请重新提交维护目标。"
                )
                self.finish_failure(
                    directory,
                    state,
                    code="codex_maintenance_model_capacity",
                    phase="model_capacity",
                    summary=(
                        f"计划模型容量暂满；已按同一冻结契约恢复原 thread {attempt} 次，任务仍未完成。"
                        if resume_thread_id
                        else "计划模型容量暂满，但原 Codex thread 标识不可用，未进行不安全重放。"
                    ),
                )
                return
            state["failureDetail"] = detail or "Codex CLI 未返回底层错误详情。"
            state["suggestedAction"] = "根据详情修复运行条件后重新提交任务。"
            self.finish_failure(
                directory,
                state,
                code="codex_maintenance_agent_failed",
                phase="agent_failed",
                summary="本地 Codex 维护代理未成功返回最终结果；底层详情已保留。",
            )
            return
        if not tasks.runtime_contract_matches(runtime, state):
            state["runtimeContract"] = runtime
            self.finish_failure(
                directory,
                state,
                code="codex_maintenance_runtime_contract_mismatch",
                phase="runtime_contract_mismatch",
                summary="Codex 实际 provider、model 或 thinking 与冻结运行契约不一致。",
            )
            return
        completed = tasks.iso_now()
        state.update(
            {
                "status": "succeeded",
                "phase": "completed",
                "outcome": "success",
                "reply": reply,
                "runtimeProvider": runtime["provider"],
                "runtimeModel": runtime["model"],
                "runtimeThinking": runtime["thinking"],
                "safeSummary": "Codex 维护任务已完成，实际运行契约已校验。",
                "updatedAt": completed,
                "heartbeatAt": completed,
                "completedAt": completed,
                "leaseExpiresAt": None,
                "notificationState": "pending" if state.get("delivery") else "disabled",
            }
        )
        request_path.unlink(missing_ok=True)
        tasks.write_state(directory, state)
        self.maybe_send_terminal(directory, state)

    def run_forever(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        os.chmod(self.root, 0o700)
        self.install_signal_handlers()
        lock_path = self.root / "worker.lock"
        with lock_path.open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            tasks.write_worker_health(self.root)
            self.fail_orphaned_running_tasks()
            while not self.stopping:
                tasks.write_worker_health(self.root)
                self.retry_terminal_notifications()
                directory = self.next_queued_task()
                if directory is not None:
                    self.process_task(directory)
                    if self.reload_requested:
                        return
                    continue
                if self.reload_requested:
                    return
                time.sleep(self.poll_seconds)
        tasks.worker_health_path(self.root).unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the v2 Codex maintenance worker.")
    parser.add_argument("--task-root", type=Path)
    parser.add_argument("--poll-seconds", type=float, default=DEFAULT_POLL_SECONDS)
    args = parser.parse_args()
    CodexMaintenanceWorker(root=args.task_root, poll_seconds=args.poll_seconds).run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
