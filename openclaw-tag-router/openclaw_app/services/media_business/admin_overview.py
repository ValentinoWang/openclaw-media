from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol
from uuid import UUID


SCHEMA_VERSION = "media_web_business_pages_v2"
MAX_RECENT_ACTIONS = 8
AUDIT_WINDOW = timedelta(hours=24)
HEALTH_STATUSES = frozenset({"healthy", "degraded", "unavailable", "unknown"})
SERVICE_TABLES = (
    ("\u8eab\u4efd\u670d\u52a1", "openclaw_account.users"),
    ("\u4efb\u52a1\u670d\u52a1", "media_product.creation_runs"),
    ("\u8ba1\u8d39\u670d\u52a1", "openclaw_account.model_operations"),
    ("\u5ba1\u8ba1\u670d\u52a1", "openclaw_account.admin_audit"),
)
ABNORMAL_RUN_STATUSES = (
    "failed",
    "needs_attention",
    "pending_manual",
    "unknown_reconcile",
    "error",
    "aborted",
    "cancelled",
)
SAFE_ACTION_STATUSES = frozenset(
    {"succeeded", "failed", "recorded", "pending", "unknown_reconcile", "cancelled", "degraded", "unknown"}
)
SAFE_ACTION_NAME = re.compile(r"^[a-z][a-z0-9_.-]{2,127}$")
SAFE_REGISTRATION_MODES = frozenset({"controlled", "open"})
SAFE_TARGET_TYPES = frozenset({"platform", "user", "tenant", "billing", "admission", "session", "unknown"})


class DatabaseConnection(Protocol):
    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> Any: ...

    def __enter__(self) -> "DatabaseConnection": ...

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None: ...


class Database(Protocol):
    def connect(self) -> DatabaseConnection: ...


class AdminOverviewError(RuntimeError):
    def __init__(self, code: str, message: str, *, status: int = 503) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status

    @property
    def detail(self) -> str:
        """Backward-compatible alias for ``message`` (see exc-1 audit)."""
        return self.message


class AdminOverviewService:
    """Build the redacted platform-level dashboard from canonical PostgreSQL facts."""

    def __init__(
        self,
        database: Database,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        health_probes: Mapping[str, Callable[[], str]] | None = None,
    ) -> None:
        self.database = database
        self.clock = clock
        self.health_probes = dict(health_probes or {})

    @staticmethod
    def public_action_id(action_id: UUID | str) -> str:
        digest = hashlib.sha256(str(action_id).encode("utf-8")).hexdigest()
        return f"act_{digest[:24]}"

    def dashboard(self) -> dict[str, Any]:
        generated_at = self._utc_datetime(self.clock())
        cutoff = generated_at - AUDIT_WINDOW
        try:
            with self.database.connect() as connection:
                counts_row = connection.execute(_COUNTS_SQL, (cutoff,)).fetchone()
                audit_row = connection.execute(_AUDIT_SUMMARY_SQL, (cutoff, cutoff)).fetchone()
                action_rows = connection.execute(
                    _RECENT_ACTIONS_SQL,
                    (cutoff, MAX_RECENT_ACTIONS),
                ).fetchall()
                summary = {
                    "counts": self._counts(counts_row),
                    "governanceTodos": self._governance_todos(counts_row),
                    "serviceHealth": self._service_health(connection, generated_at),
                    "auditSummary24h": self._audit_summary(audit_row, cutoff, generated_at),
                    "recentActions": [self._action_summary(row) for row in action_rows],
                    "generatedAt": generated_at.isoformat(),
                    "revision": self._revision(counts_row),
                }
        except AdminOverviewError:
            raise
        except Exception as exc:
            raise AdminOverviewError(
                "admin_overview_unavailable",
                "\u7ba1\u7406\u5458\u603b\u89c8\u6682\u65f6\u4e0d\u53ef\u7528\u3002",
            ) from exc
        return {
            "schemaVersion": SCHEMA_VERSION,
            "revision": summary["revision"],
            "summary": summary,
        }

    @staticmethod
    def _utc_datetime(value: datetime) -> datetime:
        if not isinstance(value, datetime):
            raise AdminOverviewError("admin_overview_unavailable", "dashboard clock returned an invalid time")
        if value.tzinfo is None:
            raise AdminOverviewError("admin_overview_unavailable", "dashboard clock must be timezone-aware")
        return value.astimezone(timezone.utc)

    @staticmethod
    def _count(value: Any) -> int:
        if type(value) is not int:
            raise AdminOverviewError("admin_overview_unavailable", "dashboard aggregate is invalid")
        if value < 0:
            raise AdminOverviewError("admin_overview_unavailable", "dashboard aggregate is negative")
        return value

    @classmethod
    def _counts(cls, row: tuple[Any, ...] | None) -> dict[str, int]:
        if row is None or len(row) != 7:
            raise AdminOverviewError("admin_overview_unavailable", "dashboard aggregate is incomplete")
        return {
            "tenants": cls._count(row[0]),
            "users": cls._count(row[1]),
            "pendingAdmission": cls._count(row[2]),
            "abnormalRuns": cls._count(row[3]),
        }

    @classmethod
    def _governance_todos(cls, row: tuple[Any, ...] | None) -> list[str]:
        if row is None or len(row) != 7:
            raise AdminOverviewError("admin_overview_unavailable", "governance aggregate is incomplete")
        expired_invites = cls._count(row[4])
        pending_admission = cls._count(row[2])
        abnormal_runs = cls._count(row[3])
        registration_mode = row[5] if type(row[5]) is str and row[5] in SAFE_REGISTRATION_MODES else "unknown"
        return [
            f"\u9080\u8bf7\u5230\u671f\uff1a{expired_invites}",
            f"\u51c6\u5165\u5e93\u5b58\uff1a{pending_admission}",
            f"\u6ce8\u518c\u7b56\u7565\u590d\u6838\uff1a{registration_mode}",
            f"\u79df\u6237\u8fd0\u884c\u5f02\u5e38\uff1a{abnormal_runs}",
        ]

    @classmethod
    def _revision(cls, row: tuple[Any, ...] | None) -> int:
        if row is None or len(row) != 7:
            raise AdminOverviewError("admin_overview_unavailable", "dashboard revision is incomplete")
        return cls._count(row[6])

    @classmethod
    def _audit_summary(
        cls,
        row: tuple[Any, ...] | None,
        cutoff: datetime,
        generated_at: datetime,
    ) -> dict[str, Any]:
        if row is None or len(row) != 2:
            raise AdminOverviewError("admin_overview_unavailable", "audit aggregate is incomplete")
        return {
            "actionCount": cls._count(row[0]),
            "failedCount": cls._count(row[1]),
            "from": cutoff.isoformat(),
            "to": generated_at.isoformat(),
        }

    def _service_health(
        self,
        connection: DatabaseConnection,
        checked_at: datetime,
    ) -> list[dict[str, str]]:
        result: list[dict[str, str]] = []
        for service, table in SERVICE_TABLES:
            try:
                probe = self.health_probes.get(service)
                status = probe() if probe is not None else self._table_status(connection, table)
            except Exception:
                status = "unavailable"
            if not isinstance(status, str) or status not in HEALTH_STATUSES:
                status = "unknown"
            result.append(
                {
                    "service": service,
                    "status": status,
                    "checkedAt": checked_at.isoformat(),
                }
            )
        return result

    @staticmethod
    def _table_status(connection: DatabaseConnection, table: str) -> str:
        row = connection.execute("SELECT to_regclass(%s)", (table,)).fetchone()
        return "healthy" if row is not None and row[0] is not None else "unavailable"

    @classmethod
    def _action_summary(cls, row: tuple[Any, ...]) -> dict[str, str]:
        if len(row) != 5:
            raise AdminOverviewError("admin_overview_unavailable", "audit action is incomplete")
        action_id, action, has_target_user, metadata, created_at = row
        if not isinstance(action, str) or not action.strip():
            raise AdminOverviewError("admin_overview_unavailable", "audit action name is invalid")
        normalized_action = action.strip()
        if SAFE_ACTION_NAME.fullmatch(normalized_action) is None:
            raise AdminOverviewError("admin_overview_unavailable", "audit action name is invalid")
        if type(has_target_user) is not bool:
            raise AdminOverviewError("admin_overview_unavailable", "audit target flag is invalid")
        metadata_map = cls._metadata(metadata)
        return {
            "publicActionId": cls.public_action_id(action_id),
            "action": normalized_action,
            "targetType": cls._target_type(has_target_user, metadata_map),
            "reasonSummary": "\u7ba1\u7406\u5458\u64cd\u4f5c\u539f\u56e0\u5df2\u7559\u75d5\u3002",
            "status": cls._action_status(metadata_map),
            "createdAt": cls._timestamp(created_at),
        }

    @staticmethod
    def _metadata(value: Any) -> dict[str, Any]:
        if isinstance(value, Mapping):
            return dict(value)
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError as exc:
                raise AdminOverviewError("admin_overview_unavailable", "audit metadata is invalid") from exc
            if isinstance(parsed, dict):
                return parsed
        raise AdminOverviewError("admin_overview_unavailable", "audit metadata is invalid")

    @staticmethod
    def _action_status(metadata: Mapping[str, Any]) -> str:
        if "status" in metadata:
            status = metadata["status"]
            if isinstance(status, str) and status in SAFE_ACTION_STATUSES:
                return status
            return "unknown"
        if metadata.get("ok") is False:
            return "failed"
        return "recorded"

    @staticmethod
    def _target_type(has_target_user: bool, metadata: Mapping[str, Any]) -> str:
        target_type = metadata.get("targetType")
        if isinstance(target_type, str) and target_type in SAFE_TARGET_TYPES:
            return target_type
        if has_target_user:
            return "user"
        return "unknown"

    @staticmethod
    def _timestamp(value: Any) -> str:
        if not isinstance(value, datetime):
            raise AdminOverviewError("admin_overview_unavailable", "audit timestamp is invalid")
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()


_COUNTS_SQL = """
SELECT
    (SELECT count(*) FROM openclaw_account.tenants WHERE status = 'active'),
    (SELECT count(*) FROM openclaw_account.users WHERE status = 'active'),
    (SELECT count(*) FROM openclaw_account.admission_codes WHERE status = 'active'),
    (
        SELECT count(*)
        FROM media_product.creation_runs
        WHERE COALESCE(canonical_data ->> 'status', '') IN (
            'failed', 'needs_attention', 'pending_manual',
            'unknown_reconcile', 'error', 'aborted', 'cancelled'
        )
    ),
    (
        SELECT count(*)
        FROM openclaw_account.affiliate_profiles
        WHERE signup_enabled
          AND signup_expires_at IS NOT NULL
          AND signup_expires_at <= %s
    ),
    (SELECT mode FROM openclaw_account.registration_policy WHERE singleton),
    GREATEST(
        COALESCE((SELECT extract(epoch FROM max(updated_at))::bigint FROM openclaw_account.users), 0),
        COALESCE((SELECT extract(epoch FROM max(updated_at))::bigint FROM openclaw_account.tenants), 0),
        COALESCE((SELECT extract(epoch FROM max(updated_at))::bigint FROM openclaw_account.affiliate_profiles), 0),
        COALESCE((SELECT extract(epoch FROM max(updated_at))::bigint FROM openclaw_account.registration_policy), 0),
        COALESCE((SELECT extract(epoch FROM max(created_at))::bigint FROM openclaw_account.admission_batches), 0),
        COALESCE((SELECT extract(epoch FROM max(updated_at))::bigint FROM media_product.creation_runs), 0),
        COALESCE((SELECT extract(epoch FROM max(created_at))::bigint FROM openclaw_account.admin_audit), 0)
    )
"""

_AUDIT_SUMMARY_SQL = """
SELECT
    count(*) FILTER (WHERE created_at >= %s),
    count(*) FILTER (
        WHERE created_at >= %s
          AND (
              action LIKE '%%failed%%'
              OR action LIKE '%%error%%'
              OR lower(COALESCE(metadata ->> 'status', '')) IN ('failed', 'error', 'unavailable')
              OR metadata ->> 'ok' = 'false'
          )
    )
FROM openclaw_account.admin_audit
"""

_RECENT_ACTIONS_SQL = """
SELECT id, action, target_user_id IS NOT NULL, metadata, created_at
FROM openclaw_account.admin_audit
WHERE created_at >= %s
ORDER BY created_at DESC, id DESC
LIMIT %s
"""

