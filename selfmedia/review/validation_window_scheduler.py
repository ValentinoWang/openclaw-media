"""Durable, tenant-local validation-window review tasks.

The scheduler only creates work after a separately verified publication event.
It never treats a reminder, a retry, or a local artifact as proof that a
review happened; only a successful data-review write with supplied external
evidence completes a task.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from media_vault import MediaVault, require_tenant_id
from selfmedia.business.commercial_loop import has_external_evidence


VALIDATION_WINDOW_SCHEDULE_SCHEMA_VERSION = "validation_window_schedule_v1"
SCHEDULE_FILENAME_PREFIX = "validation_window_schedule_"
WINDOW_DURATIONS = {
    "1h": timedelta(hours=1),
    "2h": timedelta(hours=2),
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
}
WINDOW_ALIASES = {
    "1h": "1h",
    "1小时": "1h",
    "一小时": "1h",
    "首小时": "1h",
    "firsthour": "1h",
    "twohour": "2h",
    "2h": "2h",
    "2小时": "2h",
    "两小时": "2h",
    "twentyfourhour": "24h",
    "24h": "24h",
    "24小时": "24h",
    "一天": "24h",
    "一日": "24h",
    "sevenday": "7d",
    "7d": "7d",
    "7天": "7d",
    "七天": "7d",
}


class ValidationWindowScheduleError(ValueError):
    """The schedule cannot safely be created or consumed."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _schedule_id(creation_run_id: str) -> str:
    return hashlib.sha256(creation_run_id.encode("utf-8")).hexdigest()[:24]


def _task_id(creation_run_id: str, task_kind: str, window: str) -> str:
    digest = hashlib.sha256(f"{creation_run_id}|{task_kind}|{window}".encode("utf-8")).hexdigest()[:24]
    return f"validation_review_{digest}"


def canonical_review_window(value: Any) -> str:
    text = "".join(str(value or "").strip().casefold().split()).replace("_", "").replace("-", "")
    return WINDOW_ALIASES.get(text, "")


def _as_utc(value: datetime | str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value or "").strip()
        if not text:
            raise ValidationWindowScheduleError("published_at is required")
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValidationWindowScheduleError("published_at must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ValidationWindowScheduleError("published_at must include a timezone")
    return parsed.astimezone(timezone.utc).replace(microsecond=0)


def _task_due_at(published_at: datetime, window: str) -> str:
    return (published_at + WINDOW_DURATIONS[window]).isoformat()


class ValidationWindowScheduler:
    """Read and consume review work within one authenticated tenant partition."""

    def __init__(
        self,
        *,
        tenant_id: str,
        root: str | Path | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.tenant_id = require_tenant_id(tenant_id)
        self.vault = MediaVault(tenant_id=self.tenant_id, root=root)
        self._clock = clock or _utc_now

    def schedule_for_publication(
        self,
        *,
        creation_run_id: str,
        published_url: str,
        publication_evidence_uri: str,
        publication_confirmed: bool,
        published_at: datetime | str | None = None,
    ) -> dict[str, Any]:
        """Create all target tasks for an already-confirmed publication.

        Missing confirmation or external proof yields a durable blocked plan.
        This makes an attempted call visible without creating work that may be
        mistaken for a published post.
        """
        run_id = str(creation_run_id or "").strip()
        if not run_id:
            raise ValidationWindowScheduleError("creation_run_id is required")
        schedule = self._load_or_empty(run_id)
        if not publication_confirmed:
            return self._write_blocked_schedule(
                schedule,
                creation_run_id=run_id,
                reason="publication_confirmation_missing",
            )
        if not has_external_evidence(published_url) or not has_external_evidence(publication_evidence_uri):
            return self._write_blocked_schedule(
                schedule,
                creation_run_id=run_id,
                reason="publication_external_evidence_missing",
            )

        publication_time = _as_utc(published_at if published_at is not None else self._clock())
        source = self._load_creation_source(run_id)
        desired = self._desired_schedule(
            creation_run_id=run_id,
            published_url=published_url,
            publication_evidence_uri=publication_evidence_uri,
            published_at=publication_time,
            source=source,
        )
        if schedule.get("status") == "scheduled":
            if schedule.get("source_fingerprint") == desired["source_fingerprint"]:
                return {**schedule, "replayed": True}
            return self._write_blocked_schedule(
                schedule,
                creation_run_id=run_id,
                reason="scheduled_source_changed",
                block_pending_tasks=True,
            )
        return self._write_schedule(desired)

    def read_schedule(self, creation_run_id: str) -> dict[str, Any]:
        run_id = str(creation_run_id or "").strip()
        if not run_id:
            raise ValidationWindowScheduleError("creation_run_id is required")
        path = self._schedule_path(run_id)
        if not path.is_file():
            return {"status": "not_found", "creation_run_id": run_id, "tasks": []}
        return self._read_schedule_file(path, run_id)

    def due_pending_windows(self, *, now: datetime | str | None = None) -> list[dict[str, Any]]:
        """Enumerate tenant-local pending tasks that are due at ``now``."""
        current = _as_utc(now if now is not None else self._clock())
        result: list[dict[str, Any]] = []
        root = self._schedule_root()
        if not root.is_dir():
            return result
        for path in sorted(root.glob(f"{SCHEDULE_FILENAME_PREFIX}*.json")):
            try:
                schedule = self._read_schedule_file(path, "")
            except ValidationWindowScheduleError:
                continue
            if schedule.get("status") != "scheduled":
                continue
            for task in schedule.get("tasks", []):
                if not isinstance(task, dict) or task.get("status") != "pending":
                    continue
                try:
                    due_at = _as_utc(str(task.get("due_at") or ""))
                except ValidationWindowScheduleError:
                    continue
                if due_at <= current:
                    result.append(dict(task))
        return result

    def consume_due_task(
        self,
        *,
        creation_run_id: str,
        task_id: str,
        evidence_uri: str,
        review_runner: Callable[[dict[str, Any]], Mapping[str, Any]],
        now: datetime | str | None = None,
        retry_blocked: bool = False,
    ) -> dict[str, Any]:
        """Pass actual evidence to the review runner and record its outcome.

        The runner is deliberately injected. This module owns task state, while
        ``data_review`` remains the semantic validator and evidence writer.
        """
        run_id = str(creation_run_id or "").strip()
        task_identity = str(task_id or "").strip()
        if not run_id or not task_identity:
            raise ValidationWindowScheduleError("creation_run_id and task_id are required")
        if not callable(review_runner):
            raise ValidationWindowScheduleError("review_runner is required")
        schedule = self.read_schedule(run_id)
        if schedule.get("status") != "scheduled":
            return {"status": "blocked", "reason": "schedule_not_ready", "schedule": schedule}
        task = self._task_by_id(schedule, task_identity)
        if task is None:
            raise ValidationWindowScheduleError("validation review task was not found")
        if task.get("status") == "completed":
            return {"status": "completed", "replayed": True, "task": dict(task)}
        if task.get("status") == "blocked" and retry_blocked:
            task.pop("blocking_reason", None)
            task["status"] = "pending"
        if task.get("status") != "pending":
            return {"status": "blocked", "reason": str(task.get("blocking_reason") or "task_blocked"), "task": dict(task)}
        current = _as_utc(now if now is not None else self._clock())
        if _as_utc(str(task.get("due_at") or "")) > current:
            return {"status": "pending", "reason": "task_not_due", "task": dict(task)}
        evidence = str(evidence_uri or "").strip()
        if not has_external_evidence(evidence):
            return self._block_task(schedule, task, "review_external_evidence_missing")
        try:
            result = dict(review_runner(dict(task)))
        except Exception as exc:  # A dependency failure must remain visible and retryable.
            return self._block_task(schedule, task, f"data_review_failed:{type(exc).__name__}")
        if not result.get("ok") or result.get("status") != "written":
            return self._block_task(schedule, task, "data_review_not_written")
        task["status"] = "completed"
        task["completed_at"] = current.isoformat()
        task["review_evidence_uri"] = evidence
        task["data_review_record_id"] = str(result.get("record_id") or "")
        task["attempts"] = int(task.get("attempts") or 0) + 1
        task.pop("blocking_reason", None)
        self._write_schedule(schedule)
        return {"status": "completed", "replayed": False, "task": dict(task), "data_review": result}

    def _desired_schedule(
        self,
        *,
        creation_run_id: str,
        published_url: str,
        publication_evidence_uri: str,
        published_at: datetime,
        source: dict[str, Any],
    ) -> dict[str, Any]:
        validation_targets = source["validation_targets"]
        first_hour_action = source["first_hour_action"]
        source_fingerprint = hashlib.sha256(
            _canonical_json(
                {
                    "creation_run_id": creation_run_id,
                    "published_url": published_url,
                    "publication_evidence_uri": publication_evidence_uri,
                    "published_at": published_at.isoformat(),
                    "validation_targets": validation_targets,
                    "first_hour_action": first_hour_action,
                }
            ).encode("utf-8")
        ).hexdigest()
        tasks = [
            {
                "task_id": _task_id(creation_run_id, "first_hour_action", "1h"),
                "task_kind": "first_hour_action",
                "window": "1h",
                "due_at": _task_due_at(published_at, "1h"),
                "validation_targets": [],
                "first_hour_action": first_hour_action,
                "status": "pending" if first_hour_action else "blocked",
                "blocking_reason": "first_hour_action_missing" if not first_hour_action else "",
                "attempts": 0,
                "creation_run_id": creation_run_id,
                "published_url": published_url,
            }
        ]
        for window in ("1h", "2h", "24h", "7d"):
            metrics = validation_targets.get(window, [])
            if not metrics:
                continue
            tasks.append(
                {
                    "task_id": _task_id(creation_run_id, "validation_review", window),
                    "task_kind": "validation_review",
                    "window": window,
                    "due_at": _task_due_at(published_at, window),
                    "validation_targets": list(metrics),
                    "first_hour_action": "",
                    "status": "pending",
                    "attempts": 0,
                    "creation_run_id": creation_run_id,
                    "published_url": published_url,
                }
            )
        return {
            "schema_version": VALIDATION_WINDOW_SCHEDULE_SCHEMA_VERSION,
            "schedule_id": f"validation_schedule_{_schedule_id(creation_run_id)}",
            "tenant_id": self.tenant_id,
            "creation_run_id": creation_run_id,
            "status": "scheduled",
            "published_url": published_url,
            "publication_evidence_uri": publication_evidence_uri,
            "published_at": published_at.isoformat(),
            "source_fingerprint": source_fingerprint,
            "tasks": tasks,
        }

    def _load_creation_source(self, creation_run_id: str) -> dict[str, Any]:
        path = self.vault.creation_run_dir(creation_run_id) / "draft_output.json"
        if not path.is_file():
            raise ValidationWindowScheduleError("creation_run_draft_output_not_found")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValidationWindowScheduleError("creation_run_draft_output_unreadable") from exc
        if not isinstance(payload, dict):
            raise ValidationWindowScheduleError("creation_run_draft_output_invalid")
        report = payload.get("creator_report") if isinstance(payload.get("creator_report"), dict) else {}
        pack = payload.get("publishing_pack")
        if not isinstance(pack, dict):
            pack = report.get("publishing_pack") if isinstance(report.get("publishing_pack"), dict) else {}
        raw_targets = payload.get("validation_targets")
        if not isinstance(raw_targets, dict):
            raw_targets = report.get("validation_targets") if isinstance(report.get("validation_targets"), dict) else {}
        targets: dict[str, list[str]] = {}
        for raw_window, raw_metrics in raw_targets.items():
            window = canonical_review_window(raw_window)
            if not window:
                continue
            values = raw_metrics if isinstance(raw_metrics, list) else [raw_metrics]
            cleaned = [str(value).strip() for value in values if str(value or "").strip()]
            if cleaned:
                targets[window] = list(dict.fromkeys(cleaned))
        return {"validation_targets": targets, "first_hour_action": str(pack.get("first_hour_action") or "").strip()}

    def _schedule_root(self) -> Path:
        return self.vault.root / "review_signals" / "validation_windows"

    def _schedule_path(self, creation_run_id: str) -> Path:
        return self._schedule_root() / f"{SCHEDULE_FILENAME_PREFIX}{_schedule_id(creation_run_id)}.json"

    def _load_or_empty(self, creation_run_id: str) -> dict[str, Any]:
        path = self._schedule_path(creation_run_id)
        if not path.is_file():
            return {
                "schema_version": VALIDATION_WINDOW_SCHEDULE_SCHEMA_VERSION,
                "schedule_id": f"validation_schedule_{_schedule_id(creation_run_id)}",
                "tenant_id": self.tenant_id,
                "creation_run_id": creation_run_id,
                "status": "pending",
                "tasks": [],
            }
        return self._read_schedule_file(path, creation_run_id)

    def _read_schedule_file(self, path: Path, expected_run_id: str) -> dict[str, Any]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValidationWindowScheduleError("validation schedule is unreadable") from exc
        if not isinstance(payload, dict) or payload.get("schema_version") != VALIDATION_WINDOW_SCHEDULE_SCHEMA_VERSION:
            raise ValidationWindowScheduleError("validation schedule schema is unsupported")
        if payload.get("tenant_id") != self.tenant_id:
            raise ValidationWindowScheduleError("validation schedule ownership mismatch")
        if expected_run_id and payload.get("creation_run_id") != expected_run_id:
            raise ValidationWindowScheduleError("validation schedule creation run mismatch")
        if not isinstance(payload.get("tasks"), list):
            raise ValidationWindowScheduleError("validation schedule tasks are invalid")
        return payload

    def _write_blocked_schedule(
        self,
        schedule: dict[str, Any],
        *,
        creation_run_id: str,
        reason: str,
        block_pending_tasks: bool = False,
    ) -> dict[str, Any]:
        blocked = dict(schedule)
        blocked["schema_version"] = VALIDATION_WINDOW_SCHEDULE_SCHEMA_VERSION
        blocked["tenant_id"] = self.tenant_id
        blocked["creation_run_id"] = creation_run_id
        blocked["status"] = "blocked"
        blocked["blocking_reason"] = reason
        tasks = [dict(item) for item in blocked.get("tasks", []) if isinstance(item, dict)]
        if block_pending_tasks:
            for task in tasks:
                if task.get("status") == "pending":
                    task["status"] = "blocked"
                    task["blocking_reason"] = reason
        blocked["tasks"] = tasks
        self._write_schedule(blocked)
        return {**blocked, "replayed": False}

    def _write_schedule(self, schedule: dict[str, Any]) -> dict[str, Any]:
        run_id = str(schedule.get("creation_run_id") or "").strip()
        if not run_id:
            raise ValidationWindowScheduleError("validation schedule creation_run_id is required")
        self.vault.write_json_artifact(
            self._schedule_root(),
            self._schedule_path(run_id).name,
            schedule,
            owner_type="CreationRun",
            owner_id=run_id,
            artifact_type="validation_window_schedule",
            artifact_id=str(schedule.get("schedule_id") or ""),
        )
        return schedule

    @staticmethod
    def _task_by_id(schedule: dict[str, Any], task_id: str) -> dict[str, Any] | None:
        for task in schedule.get("tasks", []):
            if isinstance(task, dict) and task.get("task_id") == task_id:
                return task
        return None

    def _block_task(self, schedule: dict[str, Any], task: dict[str, Any], reason: str) -> dict[str, Any]:
        task["status"] = "blocked"
        task["blocking_reason"] = reason
        task["attempts"] = int(task.get("attempts") or 0) + 1
        self._write_schedule(schedule)
        return {"status": "blocked", "reason": reason, "task": dict(task)}
