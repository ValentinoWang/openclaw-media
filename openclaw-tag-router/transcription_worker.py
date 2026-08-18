from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


DEFAULT_DATA_ROOT = Path("/home/ubuntu/.openclaw/workspace/openclaw-tag-router")
DEFAULT_PLUGIN_ROOT = Path("/home/ubuntu/.openclaw/extensions/openclaw-tag-router")
LEASE_SECONDS = 120
BRIDGE_TIMEOUT_SECONDS = 7200
FINAL_NOTIFICATION_LIMIT = 12000


def iso_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def parse_time(value: object) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return None


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    descriptor = os.open(temporary, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    temporary.replace(path)


def append_event(path: Path, stage: str, **details: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "stage": stage,
        "at": iso_now(),
        **{key: value for key, value in details.items() if value not in (None, "", [], {})},
    }
    descriptor = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        os.write(descriptor, (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
    finally:
        os.close(descriptor)


def parse_json_object(text: str) -> dict[str, Any]:
    value = text.strip()
    if not value:
        return {}
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        pass
    decoder = json.JSONDecoder()
    candidates: list[dict[str, Any]] = []
    for index, char in enumerate(value):
        if char != "{":
            continue
        try:
            parsed, _ = decoder.raw_decode(value[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            candidates.append(parsed)
    return candidates[-1] if candidates else {}


def pid_alive(pid: object) -> bool:
    try:
        value = int(pid)
        if value <= 0:
            return False
        os.kill(value, 0)
        return True
    except (OSError, TypeError, ValueError):
        return False


def result_postprocess_resume_dir(result: dict[str, Any]) -> Path | None:
    extra = result.get("extra") if isinstance(result.get("extra"), dict) else {}
    postprocess = extra.get("postprocess") if isinstance(extra.get("postprocess"), dict) else {}
    artifacts = (
        postprocess.get("postprocess_artifacts")
        if isinstance(postprocess.get("postprocess_artifacts"), dict)
        else {}
    )
    value = str(artifacts.get("dir") or "").strip()
    if not value:
        return None
    path = Path(value)
    return path if path.is_dir() else None


def transcription_message_result_id(job_id: str, payload: dict[str, Any]) -> str:
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    identity = {
        "text": str(payload.get("text") or ""),
        "downloaded_paths": [str(value) for value in metadata.get("downloaded_paths", [])],
        "resume_postprocess_dir": str(metadata.get("transcription_resume_postprocess_dir") or ""),
        "resume_from_asr": metadata.get("transcription_resume_from_asr") is True,
    }
    digest = hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]
    return f"{job_id}:{digest}"


class TranscriptionWorker:
    def __init__(
        self,
        *,
        data_root: Path = DEFAULT_DATA_ROOT,
        plugin_root: Path = DEFAULT_PLUGIN_ROOT,
        settings_path: Path | None = None,
        poll_seconds: float = 2.0,
    ) -> None:
        self.data_root = data_root
        self.jobs_root = data_root / "transcription-jobs"
        self.plugin_root = plugin_root
        self.settings_path = settings_path or plugin_root / "config" / "settings.yaml"
        self.poll_seconds = max(0.2, poll_seconds)
        self.stopping = False

    def job_paths(self) -> list[Path]:
        def fifo_key(path: Path) -> tuple[float, str, str]:
            job = self.read_job(path) or {}
            created_at = parse_time(job.get("created_at"))
            if created_at is not None:
                created_timestamp = created_at.timestamp()
            else:
                try:
                    created_timestamp = path.stat().st_mtime
                except OSError:
                    created_timestamp = float("inf")
            return (
                created_timestamp,
                str(job.get("enqueue_order") or ""),
                str(job.get("id") or path.parent.name),
            )

        return sorted(self.jobs_root.glob("tr-*/job.json"), key=fifo_key)

    def read_job(self, path: Path) -> dict[str, Any] | None:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) and payload.get("version") == 1 else None

    def write_job(self, path: Path, job: dict[str, Any]) -> None:
        job["updated_at"] = iso_now()
        atomic_write_json(path, job)

    def claimable(self, job: dict[str, Any]) -> bool:
        if job.get("state") == "queued":
            return True
        if job.get("state") != "processing":
            return False
        lease = parse_time(job.get("lease_expires_at"))
        return not pid_alive(job.get("worker_pid")) or lease is None or lease <= datetime.now(timezone.utc).astimezone()

    def run_once(self) -> int:
        processed = 0
        for path in self.job_paths():
            job = self.read_job(path)
            if not job:
                continue
            state = str(job.get("state") or "")
            if self.claimable(job):
                self.process_job(path, job)
                processed += 1
            elif state == "persisted" and job.get("notification_state") != "sent":
                self.finish_persisted_job(path, job)
                processed += 1
            elif state == "pending_manual" and job.get("notification_state") != "sent":
                self.notify_failure(path, job)
                processed += 1
        return processed

    def run_forever(self) -> None:
        self.jobs_root.mkdir(parents=True, exist_ok=True)
        lock_path = self.jobs_root / "worker.lock"
        with lock_path.open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            while not self.stopping:
                self.run_once()
                time.sleep(self.poll_seconds)

    def process_job(self, path: Path, job: dict[str, Any]) -> None:
        progress_path = Path(str(job.get("progress_path") or path.parent / "stage-events.jsonl"))
        job.update(
            {
                "state": "processing",
                "attempts": int(job.get("attempts") or 0) + 1,
                "worker_pid": os.getpid(),
                "processing_started_at": job.get("processing_started_at") or iso_now(),
                "lease_expires_at": (datetime.now(timezone.utc).astimezone() + timedelta(seconds=LEASE_SECONDS)).isoformat(),
                "failure": None,
            }
        )
        self.write_job(path, job)
        append_event(progress_path, "worker_claimed", attempt=job["attempts"])

        payload = dict(job.get("payload") or {})
        metadata = dict(payload.get("metadata") or {})
        metadata["transcription_job_id"] = job["id"]
        metadata["transcription_progress_path"] = str(progress_path)
        metadata["transcription_defer_source_delete"] = True
        if job.get("resume_postprocess_dir"):
            metadata["transcription_resume_postprocess_dir"] = str(job["resume_postprocess_dir"])
        payload["metadata"] = metadata
        resume_paths = self.resume_transcripts(path, job, progress_path)
        if resume_paths:
            original_body = str(payload.get("text") or "").split("】", 1)[-1].strip()
            payload["text"] = (
                "【转写-文字】\n"
                "要求：从已完成 ASR 的录音文字稿恢复统一会议纪要。\n"
                f"补充要求：{original_body}"
            )
            payload["metadata"] = {
                **metadata,
                "downloaded_paths": resume_paths,
                "transcription_resume_from_asr": True,
            }
            append_event(progress_path, "resumed_from_clean_transcripts", transcript_count=len(resume_paths))
        payload_metadata = dict(payload.get("metadata") or {})
        payload_metadata["message_result_id"] = transcription_message_result_id(str(job["id"]), payload)
        payload["metadata"] = payload_metadata
        stdout_path = path.parent / "bridge-result.json"
        stderr_path = path.parent / "bridge.log"
        command = [
            sys.executable,
            str(self.plugin_root / "bridge.py"),
            "ingest",
            str(self.data_root),
            str(self.settings_path),
        ]
        environment = dict(os.environ)
        python_path = environment.get("PYTHONPATH", "")
        environment["PYTHONPATH"] = ":".join(
            item for item in ("/home/ubuntu/selfmedia-tools", str(self.plugin_root), python_path) if item
        )
        started = time.monotonic()
        progress_offset = 0
        last_heartbeat = 0.0
        with stdout_path.open("w", encoding="utf-8") as stdout, stderr_path.open("w", encoding="utf-8") as stderr:
            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=stdout,
                stderr=stderr,
                text=True,
                env=environment,
                cwd=str(self.plugin_root),
            )
            assert process.stdin is not None
            process.stdin.write(json.dumps(payload, ensure_ascii=False))
            process.stdin.close()
            while process.poll() is None:
                now = time.monotonic()
                if now - started > BRIDGE_TIMEOUT_SECONDS:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                    self.fail_job(path, job, "TRANSCRIPTION_JOB_TIMEOUT", "后台转写超过最大执行时间", "bridge")
                    return
                progress_offset = self.consume_progress(path, job, progress_path, progress_offset)
                if now - last_heartbeat >= 10:
                    job["lease_expires_at"] = (
                        datetime.now(timezone.utc).astimezone() + timedelta(seconds=LEASE_SECONDS)
                    ).isoformat()
                    job["bridge_pid"] = process.pid
                    self.write_job(path, job)
                    last_heartbeat = now
                time.sleep(1)
        progress_offset = self.consume_progress(path, job, progress_path, progress_offset)
        result = parse_json_object(stdout_path.read_text(encoding="utf-8"))
        atomic_write_json(path.parent / "result.json", result)
        if process.returncode != 0 or result.get("status") != "archived":
            resume_dir = result_postprocess_resume_dir(result)
            if resume_dir is not None:
                job["resume_postprocess_dir"] = str(resume_dir)
                self.write_job(path, job)
            stage = str(job.get("current_stage") or "bridge")
            self.fail_job(
                path,
                job,
                "TRANSCRIPTION_PIPELINE_FAILED",
                "转写或整理未通过完成校验，已有产物已保留用于恢复",
                stage,
            )
            return

        job["state"] = "persisted"
        job["result_path"] = str(path.parent / "result.json")
        job["result_status"] = result.get("status")
        job["result_task_id"] = result.get("task_id")
        job["result_local_path"] = result.get("local_path")
        job["lease_expires_at"] = None
        self.write_job(path, job)
        append_event(progress_path, "pipeline_persisted", task_id=result.get("task_id"))
        self.finish_persisted_job(path, job)

    def consume_progress(self, path: Path, job: dict[str, Any], progress_path: Path, offset: int) -> int:
        if not progress_path.exists():
            return offset
        with progress_path.open("r", encoding="utf-8") as handle:
            handle.seek(offset)
            lines = handle.readlines()
            offset = handle.tell()
        for line in lines:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            stage = str(event.get("stage") or "")
            if not stage:
                continue
            job["current_stage"] = stage
            job["last_progress_at"] = event.get("at") or iso_now()
            if stage == "asr_started":
                job["asr_attachment_count"] = int(event.get("attachment_count") or 0)
                self.notify_stage(path, job, stage, "录音转写中")
            elif stage == "asr_file_completed":
                attachment_id = str(event.get("attachment_id") or "")
                clean_path = str(event.get("clean_transcript_path") or "")
                if attachment_id and clean_path:
                    job.setdefault("resume_transcripts", {})[attachment_id] = {
                        "path": clean_path,
                        "display_name": str(event.get("display_name") or attachment_id),
                    }
            elif stage == "postprocess_started":
                self.notify_stage(path, job, stage, "录音文字已生成，正在整理会议纪要")
        self.write_job(path, job)
        return offset

    def resume_transcripts(self, path: Path, job: dict[str, Any], progress_path: Path) -> list[str]:
        if progress_path.exists():
            self.consume_progress(path, job, progress_path, 0)
        entries = job.get("resume_transcripts") if isinstance(job.get("resume_transcripts"), dict) else {}
        expected = int(job.get("asr_attachment_count") or 0)
        if expected <= 0 or len(entries) < expected:
            return []
        resume_dir = path.parent / "resume-transcripts"
        resume_dir.mkdir(parents=True, exist_ok=True)
        resolved: list[str] = []
        for index, attachment_id in enumerate(sorted(entries), start=1):
            item = entries[attachment_id]
            source = Path(str(item.get("path") or ""))
            if not source.is_file():
                return []
            display_stem = Path(str(item.get("display_name") or attachment_id)).stem
            safe_stem = "".join(char if char.isalnum() or char in "-_" else "-" for char in display_stem).strip("-")
            target = resume_dir / f"{index:02d}-{safe_stem or attachment_id}.txt"
            if target.exists() or target.is_symlink():
                target.unlink()
            target.symlink_to(source)
            resolved.append(str(target))
        job["resume_mode"] = "clean_transcripts"
        self.write_job(path, job)
        return resolved

    def notify_stage(self, path: Path, job: dict[str, Any], stage: str, label: str) -> None:
        if (job.get("notifications") or {}).get(stage, {}).get("message_id"):
            return
        text = f"{label}\n任务ID：{job['id']}\n阶段：{stage}"
        receipt = self.send_feishu(job, text)
        if receipt.get("message_id"):
            job.setdefault("notifications", {})[stage] = {
                "message_id": receipt["message_id"],
                "sent_at": iso_now(),
            }
            self.write_job(path, job)

    def finish_persisted_job(self, path: Path, job: dict[str, Any]) -> None:
        result_path = Path(str(job.get("result_path") or path.parent / "result.json"))
        try:
            result = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self.fail_job(path, job, "TRANSCRIPTION_RESULT_MISSING", "完成结果文件不可读", "persisted")
            return
        cleanup: list[dict[str, object]] = []
        for value in ((job.get("payload") or {}).get("metadata") or {}).get("downloaded_paths", []):
            source = Path(str(value))
            existed = source.exists()
            try:
                source.unlink(missing_ok=True)
                cleanup.append({"path": str(source), "deleted": existed})
            except OSError as exc:
                cleanup.append({"path": str(source), "deleted": False, "error": str(exc)})
        job["source_cleanup"] = cleanup
        reply = str(result.get("reply") or "").strip()
        text = f"转写任务完成\n任务ID：{job['id']}"
        cleanup_ok = bool(cleanup) and all(item.get("deleted") is True for item in cleanup)
        if cleanup:
            text += "\n原始录音清理：" + ("已完成" if cleanup_ok else "部分文件未删除，请查看任务记录")
        if reply:
            text += "\n\n" + reply[:FINAL_NOTIFICATION_LIMIT]
        receipt = self.send_feishu(job, text)
        if not receipt.get("message_id"):
            job["notification_state"] = "retrying"
            job["notification_error"] = receipt.get("error") or "send_failed"
            self.write_job(path, job)
            return
        job["notification_state"] = "sent"
        job.setdefault("notifications", {})["final"] = {
            "message_id": receipt["message_id"],
            "sent_at": iso_now(),
        }
        job["state"] = "completed"
        job["completed_at"] = iso_now()
        self.write_job(path, job)
        append_event(Path(job["progress_path"]), "notification_sent", message_id=receipt["message_id"])

    def fail_job(self, path: Path, job: dict[str, Any], code: str, reason: str, stage: str) -> None:
        job["state"] = "pending_manual"
        job["failure"] = {"code": code, "reason": reason, "stage": stage, "at": iso_now()}
        job["lease_expires_at"] = None
        job["notification_state"] = "pending"
        self.write_job(path, job)
        append_event(Path(job["progress_path"]), "failed", code=code, stage_name=stage)
        self.notify_failure(path, job)

    def notify_failure(self, path: Path, job: dict[str, Any]) -> None:
        failure = dict(job.get("failure") or {})
        text = (
            "转写任务未完成\n"
            f"任务ID：{job['id']}\n"
            f"错误码：{failure.get('code') or 'TRANSCRIPTION_PENDING_MANUAL'}\n"
            f"阶段：{failure.get('stage') or 'unknown'}\n"
            f"原因：{failure.get('reason') or '任务未通过完成校验'}\n"
            "建议：已有中间产物已保留，请修复后从当前任务恢复。"
        )
        receipt = self.send_feishu(job, text)
        if receipt.get("message_id"):
            job["notification_state"] = "sent"
            job.setdefault("notifications", {})["failure"] = {
                "message_id": receipt["message_id"],
                "sent_at": iso_now(),
            }
        else:
            job["notification_state"] = "retrying"
            job["notification_error"] = receipt.get("error") or "send_failed"
        self.write_job(path, job)

    def send_feishu(self, job: dict[str, Any], text: str) -> dict[str, str]:
        command = [
            "openclaw",
            "message",
            "send",
            "--channel",
            "feishu",
            "--account",
            str(job.get("account_id") or "daily"),
            "--target",
            str(job.get("target") or ""),
            "--message",
            text,
            "--json",
        ]
        try:
            process = subprocess.run(command, text=True, capture_output=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {"error": str(exc)}
        payload = parse_json_object(process.stdout)
        message_id = str(
            payload.get("messageId")
            or (payload.get("payload") or {}).get("messageId")
            or ""
        )
        if process.returncode != 0 or not message_id:
            return {"error": (process.stderr or process.stdout or "send_failed")[-1000:]}
        return {"message_id": message_id}


def main() -> int:
    parser = argparse.ArgumentParser(description="Process persistent asynchronous transcription jobs.")
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--plugin-root", type=Path, default=DEFAULT_PLUGIN_ROOT)
    parser.add_argument("--settings-path", type=Path)
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    worker = TranscriptionWorker(
        data_root=args.data_root,
        plugin_root=args.plugin_root,
        settings_path=args.settings_path,
        poll_seconds=args.poll_seconds,
    )

    def stop(_signum: int, _frame: object) -> None:
        worker.stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    if args.once:
        worker.run_once()
    else:
        worker.run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
