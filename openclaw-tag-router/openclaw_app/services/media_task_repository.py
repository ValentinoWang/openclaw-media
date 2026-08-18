from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping, Sequence


RECEIPT_SCHEMA_VERSION = "media_e2e_receipt_v1"
ACTIVE_ATTEMPT_STATUSES = (
    "claimed",
    "running",
    "waiting_database_readback",
    "waiting_external_readback",
    "waiting_web_readback",
)
TERMINAL_TASK_STATUSES = frozenset(
    {"multi_system_readback_complete", "pending_manual", "failed", "cancelled"}
)
REPRESENTATIVE_CAPABILITIES = frozenset(
    {"selfmedia_creation_consultation", "selfmedia_creation"}
)
ACCOUNT_REQUIRED_CAPABILITIES = REPRESENTATIVE_CAPABILITIES
ACCOUNT_BOUND_CAPABILITIES = frozenset(
    {
        "account_track_strategy",
        "creation_decision_brief",
        "shooting_execution_plan",
        "publishing_pack_build",
        "owned_media_account_lookup",
        "selfmedia_creation",
        "selfmedia_creation_consultation",
        "selfmedia_data_review",
        "work_acceptance_report",
        "style_polish_run",
        "post_review_signal",
    }
)
OWNED_ACCOUNT_FIELD_KEY = "field_311bb313fdec"
ALLOWED_WORKSPACE_MODES = frozenset({"personal_web", "organization_lark"})
ALLOWED_ACCOUNT_ROLES = frozenset({"user", "admin"})
SENSITIVE_KEY = re.compile(
    r"password|cookie|token|secret|credential|private[_-]?(body|text|content)|raw[_-]?(body|text|content)",
    re.IGNORECASE,
)


class MediaTaskRepositoryError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ClaimedMediaTask:
    task: dict[str, Any]
    attempt_public_id: str
    runner_public_id: str
    executor_public_id: str
    lease_generation: int
    lease_expires_at: str


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def digest_json(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def task_requires_owned_account(
    capability_id: str,
    params: Mapping[str, Any],
) -> bool:
    if capability_id in ACCOUNT_REQUIRED_CAPABILITIES:
        return True
    if capability_id not in ACCOUNT_BOUND_CAPABILITIES:
        return False
    return bool(str(params.get(OWNED_ACCOUNT_FIELD_KEY) or "").strip())


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_value(value: Any, fallback: Any) -> Any:
    if value is None:
        return fallback
    if isinstance(value, str):
        return json.loads(value)
    return value


def _iso(value: Any) -> str:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return str(value or "")


def _no_sensitive_keys(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if SENSITIVE_KEY.search(str(key)):
                raise MediaTaskRepositoryError(
                    "sensitive_projection_rejected",
                    "任务持久化投影包含禁止字段。",
                )
            _no_sensitive_keys(item)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for item in value:
            _no_sensitive_keys(item)


class PostgresMediaTaskRepository:
    """Transactional authority for Web tasks and independent runner settlement."""

    _TASK_COLUMNS = """
        tenant_id, task_public_id, actor_public_id, owned_account_public_id,
        idempotency_key, request_fingerprint, capability_id, variant_id,
        catalog_version, invocation, capability_path, authorization_projection, confirmation,
        status, settlement_stage, progress, summary, result_projection,
        error_projection, cancel_requested, model_request_root, event_cursor,
        created_at, updated_at
    """

    def __init__(
        self,
        connection_factory: Callable[[], Any],
        *,
        now: Callable[[], datetime] = utc_now,
    ) -> None:
        self._connection_factory = connection_factory
        self._now = now

    @staticmethod
    def _workspace_not_allowed() -> MediaTaskRepositoryError:
        return MediaTaskRepositoryError(
            "workspace_not_allowed",
            "当前会话不能在该工作区创建任务。",
        )

    def _authorize_task_context_tx(
        self,
        connection: Any,
        *,
        tenant_id: str,
        user_public_id: str,
        workspace_mode: str,
        role: str,
        is_maintainer: bool,
    ) -> dict[str, Any]:
        if not isinstance(is_maintainer, bool):
            raise self._workspace_not_allowed()
        normalized_user = user_public_id.strip()
        normalized_workspace = workspace_mode.strip()
        normalized_role = role.strip()
        if (
            not normalized_user
            or normalized_workspace not in ALLOWED_WORKSPACE_MODES
            or normalized_role not in ALLOWED_ACCOUNT_ROLES
        ):
            raise self._workspace_not_allowed()
        row = connection.execute(
            """
            SELECT tenant.workspace_mode, account_user.role, account_user.is_maintainer
            FROM openclaw_account.tenants AS tenant
            JOIN openclaw_account.users AS account_user
              ON account_user.id::text = %s
             AND account_user.status = 'active'
            JOIN openclaw_account.tenant_members AS membership
              ON membership.tenant_id = tenant.id
             AND membership.user_id = account_user.id
             AND membership.status = 'active'
            WHERE tenant.id = %s
              AND tenant.status = 'active'
              AND tenant.workspace_mode = %s
              AND account_user.role = %s
              AND account_user.is_maintainer = %s
            FOR SHARE OF tenant, account_user, membership
            """,
            (
                normalized_user,
                tenant_id,
                normalized_workspace,
                normalized_role,
                is_maintainer,
            ),
        ).fetchone()
        if row is None:
            raise self._workspace_not_allowed()
        return {
            "workspace_mode": str(row[0]),
            "role": str(row[1]),
            "is_maintainer": bool(row[2]),
        }

    def authorize_task_context(
        self,
        *,
        tenant_id: str,
        user_public_id: str,
        workspace_mode: str,
        role: str,
        is_maintainer: bool,
    ) -> dict[str, Any]:
        with self._connection_factory() as connection:
            return self._authorize_task_context_tx(
                connection,
                tenant_id=tenant_id,
                user_public_id=user_public_id,
                workspace_mode=workspace_mode,
                role=role,
                is_maintainer=is_maintainer,
            )

    def resolve_owned_account(
        self,
        *,
        tenant_id: str,
        user_public_id: str,
        platform: str,
        submitted_account_ref: str,
    ) -> dict[str, str]:
        normalized_user = user_public_id.strip()
        normalized_platform = platform.strip().casefold()
        normalized_account = submitted_account_ref.strip().casefold()
        if not normalized_user or not normalized_platform or not normalized_account:
            raise MediaTaskRepositoryError(
                "required_input_missing",
                "缺少创建任务所需输入",
            )
        submitted_digest = digest_json(
            {"platform": normalized_platform, "account": normalized_account}
        )
        query = """
            SELECT binding.id, account.public_id
            FROM media_product.media_task_account_bindings AS binding
            JOIN media_product.owned_media_accounts AS account
              ON account.tenant_id = binding.tenant_id
             AND account.public_id = binding.owned_account_public_id
            JOIN openclaw_account.users AS account_user
              ON account_user.id::text = binding.actor_public_id
             AND account_user.status = 'active'
            JOIN openclaw_account.tenant_members AS membership
              ON membership.tenant_id = binding.tenant_id
             AND membership.user_id = account_user.id
             AND membership.status = 'active'
            JOIN openclaw_account.tenants AS tenant
              ON tenant.id = binding.tenant_id
             AND tenant.status = 'active'
            WHERE binding.tenant_id = %s
              AND binding.actor_public_id = %s
              AND binding.platform = %s
              AND binding.submitted_account_ref_digest = %s
              AND binding.status = 'active'
              AND account.account_category = 'customer_owned'
              AND lower(btrim(account.canonical_data->>'platform')) = %s
              AND lower(btrim(account.canonical_data->>'account_name')) = %s
            ORDER BY binding.id
            LIMIT 2
        """
        with self._connection_factory() as connection:
            rows = connection.execute(
                query,
                (
                    tenant_id,
                    normalized_user,
                    normalized_platform,
                    submitted_digest,
                    normalized_platform,
                    normalized_account,
                ),
            ).fetchall()
            if not rows:
                raise MediaTaskRepositoryError(
                    "account_relationship_unavailable",
                    "无法确认所选客户账号关系",
                )
            if len(rows) != 1:
                raise MediaTaskRepositoryError(
                    "account_relationship_conflict",
                    "所选客户账号关系存在冲突",
                )
            relationship_id, owned_account_public_id = rows[0]
        return {
            "actor_public_id": normalized_user,
            "owned_account_public_id": str(owned_account_public_id),
            "relationship_ref": f"relationship:{relationship_id}",
            "platform": normalized_platform,
            "normalized_account": normalized_account,
            "submitted_account_ref_digest": submitted_digest,
        }

    def create_task(self, task: Mapping[str, Any]) -> tuple[dict[str, Any], bool]:
        _no_sensitive_keys(task.get("invocation") or {})
        _no_sensitive_keys(task.get("authorization") or {})
        tenant_id = str(task["tenant_id"])
        actor_public_id = str(task["actor_public_id"])
        authorization = task.get("authorization")
        if not isinstance(authorization, Mapping) or set(authorization) != {
            "workspace_mode",
            "role",
            "is_maintainer",
        }:
            raise self._workspace_not_allowed()
        if not isinstance(authorization["is_maintainer"], bool):
            raise self._workspace_not_allowed()
        now = self._now()
        with self._connection_factory() as connection:
            self._authorize_task_context_tx(
                connection,
                tenant_id=tenant_id,
                user_public_id=actor_public_id,
                workspace_mode=str(authorization["workspace_mode"]),
                role=str(authorization["role"]),
                is_maintainer=authorization["is_maintainer"],
            )
            invocation = task.get("invocation")
            params = invocation.get("params") if isinstance(invocation, Mapping) else None
            if task_requires_owned_account(
                str(task["capability_id"]),
                params if isinstance(params, Mapping) else {},
            ):
                self._verify_task_account_binding_tx(connection, task)
            existing = connection.execute(
                f"SELECT {self._TASK_COLUMNS} FROM media_product.media_web_tasks WHERE tenant_id = %s AND actor_public_id = %s AND idempotency_key = %s FOR UPDATE",
                (tenant_id, actor_public_id, str(task["idempotency_key"])),
            ).fetchone()
            if existing is not None:
                projected = self._task_row(existing)
                if projected["request_fingerprint"] != task["request_fingerprint"]:
                    raise MediaTaskRepositoryError(
                        "idempotency_conflict",
                        "幂等键已绑定其他任务请求。",
                    )
                return projected, False
            connection.execute(
                """
                INSERT INTO media_product.media_web_tasks (
                    tenant_id, task_public_id, actor_public_id, owned_account_public_id,
                    idempotency_key, request_fingerprint, capability_id, variant_id,
                    catalog_version, invocation, capability_path, authorization_projection,
                    confirmation, status, settlement_stage, progress, summary,
                    model_request_root, created_at, updated_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb,
                    %s, %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    tenant_id,
                    task["task_id"],
                    task["actor_public_id"],
                    task.get("owned_account_public_id"),
                    task["idempotency_key"],
                    task["request_fingerprint"],
                    task["capability_id"],
                    task["variant_id"],
                    task["catalog_version"],
                    _json(task["invocation"]),
                    _json(task["capability_path"]),
                    _json(task.get("authorization") or {}),
                    _json(task.get("confirmation") or {}),
                    task["status"],
                    task["settlement_stage"],
                    int(task.get("progress") or 0),
                    str(task.get("summary") or ""),
                    task.get("model_request_root"),
                    now,
                    now,
                ),
            )
            self._append_event_tx(
                connection,
                tenant_id=tenant_id,
                task_public_id=str(task["task_id"]),
                event_type="task.created",
                status=str(task["status"]),
                progress=int(task.get("progress") or 0),
                message="任务已提交并持久排队。",
            )
            row = connection.execute(
                f"SELECT {self._TASK_COLUMNS} FROM media_product.media_web_tasks WHERE tenant_id = %s AND task_public_id = %s",
                (tenant_id, str(task["task_id"])),
            ).fetchone()
        assert row is not None
        return self._task_row(row), True

    def _verify_task_account_binding_tx(
        self,
        connection: Any,
        task: Mapping[str, Any],
    ) -> None:
        invocation = task.get("invocation")
        binding_projection = (
            invocation.get("account_binding") if isinstance(invocation, Mapping) else None
        )
        if not isinstance(binding_projection, Mapping):
            raise MediaTaskRepositoryError(
                "account_relationship_unavailable",
                "无法确认所选客户账号关系",
            )
        tenant_id = str(task["tenant_id"])
        actor_public_id = str(task["actor_public_id"])
        owned_account_public_id = str(task.get("owned_account_public_id") or "")
        platform = str(binding_projection.get("platform") or "")
        normalized_account = str(binding_projection.get("normalized_account") or "")
        submitted_digest = str(
            binding_projection.get("submitted_account_ref_digest") or ""
        )
        projected_actor = str(binding_projection.get("actor_public_id") or "")
        projected_account = str(binding_projection.get("owned_account_public_id") or "")
        projected_relationship = str(binding_projection.get("relationship_ref") or "")
        expected_digest = digest_json(
            {"platform": platform, "account": normalized_account}
        )
        if (
            projected_actor != actor_public_id
            or projected_account != owned_account_public_id
            or submitted_digest != expected_digest
        ):
            raise MediaTaskRepositoryError(
                "account_relationship_unavailable",
                "无法确认所选客户账号关系",
            )
        rows = connection.execute(
            """
            SELECT binding.id
            FROM media_product.media_task_account_bindings AS binding
            JOIN media_product.owned_media_accounts AS account
              ON account.tenant_id = binding.tenant_id
             AND account.public_id = binding.owned_account_public_id
            WHERE binding.tenant_id = %s
              AND binding.actor_public_id = %s
              AND binding.owned_account_public_id = %s
              AND binding.platform = %s
              AND binding.submitted_account_ref_digest = %s
              AND binding.status = 'active'
              AND account.account_category = 'customer_owned'
              AND lower(btrim(account.canonical_data->>'platform')) = %s
              AND lower(btrim(account.canonical_data->>'account_name')) = %s
            ORDER BY binding.id
            LIMIT 2
            FOR SHARE OF binding, account
            """,
            (
                tenant_id,
                actor_public_id,
                owned_account_public_id,
                platform,
                submitted_digest,
                platform,
                normalized_account,
            ),
        ).fetchall()
        if not rows:
            raise MediaTaskRepositoryError(
                "account_relationship_unavailable",
                "无法确认所选客户账号关系",
            )
        if len(rows) != 1:
            raise MediaTaskRepositoryError(
                "account_relationship_conflict",
                "所选客户账号关系存在冲突",
            )
        if projected_relationship != f"relationship:{rows[0][0]}":
            raise MediaTaskRepositoryError(
                "account_relationship_unavailable",
                "无法确认所选客户账号关系",
            )

    def find_task_by_idempotency(
        self,
        tenant_id: str,
        actor_public_id: str,
        idempotency_key: str,
    ) -> dict[str, Any] | None:
        with self._connection_factory() as connection:
            row = connection.execute(
                f"SELECT {self._TASK_COLUMNS} FROM media_product.media_web_tasks WHERE tenant_id = %s AND actor_public_id = %s AND idempotency_key = %s",
                (tenant_id, actor_public_id, idempotency_key),
            ).fetchone()
        return None if row is None else self._task_row(row)

    def get_task(
        self,
        tenant_id: str,
        actor_public_id: str,
        task_public_id: str,
    ) -> dict[str, Any]:
        with self._connection_factory() as connection:
            row = connection.execute(
                f"SELECT {self._TASK_COLUMNS} FROM media_product.media_web_tasks WHERE tenant_id = %s AND actor_public_id = %s AND task_public_id = %s",
                (tenant_id, actor_public_id, task_public_id),
            ).fetchone()
        if row is None:
            raise MediaTaskRepositoryError("task_not_found", "未找到该任务。")
        return self._task_row(row)

    def _get_task_unscoped(self, tenant_id: str, task_public_id: str) -> dict[str, Any]:
        with self._connection_factory() as connection:
            row = connection.execute(
                f"SELECT {self._TASK_COLUMNS} FROM media_product.media_web_tasks WHERE tenant_id = %s AND task_public_id = %s",
                (tenant_id, task_public_id),
            ).fetchone()
        if row is None:
            raise MediaTaskRepositoryError("task_not_found", "未找到该任务。")
        return self._task_row(row)

    def get_task_for_runner(self, tenant_id: str, task_public_id: str) -> dict[str, Any]:
        return self._get_task_unscoped(tenant_id, task_public_id)

    def list_tasks(
        self,
        tenant_id: str,
        actor_public_id: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        with self._connection_factory() as connection:
            rows = connection.execute(
                f"SELECT {self._TASK_COLUMNS} FROM media_product.media_web_tasks WHERE tenant_id = %s AND actor_public_id = %s ORDER BY created_at DESC, task_public_id DESC LIMIT %s",
                (tenant_id, actor_public_id, max(1, min(int(limit), 100))),
            ).fetchall()
        return [self._task_row(row) for row in rows]

    def list_events(
        self,
        tenant_id: str,
        actor_public_id: str,
        task_public_id: str,
        after: int,
    ) -> list[dict[str, Any]]:
        self.get_task(tenant_id, actor_public_id, task_public_id)
        with self._connection_factory() as connection:
            rows = connection.execute(
                """
                SELECT event_number, event_type, status, progress, message, created_at
                FROM media_product.media_web_task_events
                WHERE tenant_id = %s AND task_public_id = %s AND event_number > %s
                ORDER BY event_number
                """,
                (tenant_id, task_public_id, max(0, int(after))),
            ).fetchall()
        return [
            {
                "eventId": int(row[0]),
                "taskId": task_public_id,
                "type": str(row[1]),
                "status": str(row[2]),
                "progress": int(row[3]),
                "message": str(row[4]),
                "createdAt": _iso(row[5]),
            }
            for row in rows
        ]

    def request_cancel(
        self,
        tenant_id: str,
        actor_public_id: str,
        task_public_id: str,
    ) -> dict[str, Any]:
        with self._connection_factory() as connection:
            row = connection.execute(
                f"SELECT {self._TASK_COLUMNS} FROM media_product.media_web_tasks WHERE tenant_id = %s AND actor_public_id = %s AND task_public_id = %s FOR UPDATE",
                (tenant_id, actor_public_id, task_public_id),
            ).fetchone()
            if row is None:
                raise MediaTaskRepositoryError("task_not_found", "未找到该任务。")
            task = self._task_row(row)
            if task["status"] in TERMINAL_TASK_STATUSES:
                return task
            terminal = task["status"] in {"queued", "awaiting_confirmation"}
            status = "cancelled" if terminal else task["status"]
            stage = "cancelled" if terminal else task["settlement_stage"]
            progress = 100 if terminal else task["progress"]
            connection.execute(
                """
                UPDATE media_product.media_web_tasks
                SET cancel_requested = true, status = %s, settlement_stage = %s,
                    progress = %s, updated_at = %s
                WHERE tenant_id = %s AND actor_public_id = %s AND task_public_id = %s
                """,
                (status, stage, progress, self._now(), tenant_id, actor_public_id, task_public_id),
            )
            self._append_event_tx(
                connection,
                tenant_id=tenant_id,
                task_public_id=task_public_id,
                event_type="task.cancelled" if terminal else "task.status",
                status=status,
                progress=progress,
                message="任务已取消。" if terminal else "取消请求已记录，已发生的写入不会伪装回滚。",
            )
        return self.get_task(tenant_id, actor_public_id, task_public_id)

    def decide_confirmation(
        self,
        tenant_id: str,
        actor_public_id: str,
        task_public_id: str,
        *,
        decision: str,
        note: str,
    ) -> dict[str, Any]:
        with self._connection_factory() as connection:
            row = connection.execute(
                f"SELECT {self._TASK_COLUMNS} FROM media_product.media_web_tasks WHERE tenant_id = %s AND actor_public_id = %s AND task_public_id = %s FOR UPDATE",
                (tenant_id, actor_public_id, task_public_id),
            ).fetchone()
            if row is None:
                raise MediaTaskRepositoryError("task_not_found", "未找到该任务。")
            task = self._task_row(row)
            state = "approved" if decision == "approve" else "rejected"
            if task["confirmation"].get("state") == state:
                return task
            if task["status"] != "awaiting_confirmation":
                raise MediaTaskRepositoryError("task_conflict", "任务当前状态不允许此操作。")
            confirmation = dict(task["confirmation"])
            confirmation.update({"state": state, "note": note, "decided_at": _iso(self._now())})
            status = "queued" if decision == "approve" else "cancelled"
            stage = "queued" if decision == "approve" else "cancelled"
            progress = 0 if decision == "approve" else 100
            connection.execute(
                """
                UPDATE media_product.media_web_tasks
                SET confirmation = %s::jsonb, status = %s, settlement_stage = %s,
                    progress = %s, updated_at = %s
                WHERE tenant_id = %s AND actor_public_id = %s AND task_public_id = %s
                """,
                (
                    _json(confirmation), status, stage, progress, self._now(),
                    tenant_id, actor_public_id, task_public_id,
                ),
            )
            self._append_event_tx(
                connection,
                tenant_id=tenant_id,
                task_public_id=task_public_id,
                event_type="task.confirmation" if decision == "approve" else "task.cancelled",
                status=status,
                progress=progress,
                message="任务确认已通过并重新排队。" if decision == "approve" else "任务确认已拒绝。",
            )
        return self.get_task(tenant_id, actor_public_id, task_public_id)

    def claim_next(
        self,
        *,
        runner_public_id: str,
        executor_public_id: str,
        lease_seconds: int,
    ) -> ClaimedMediaTask | None:
        if runner_public_id == executor_public_id:
            raise MediaTaskRepositoryError(
                "runner_identity_conflict",
                "账号聚合 runner 与任务执行器必须使用不同身份。",
            )
        now = self._now()
        expires = now + timedelta(seconds=max(15, int(lease_seconds)))
        with self._connection_factory() as connection:
            self._recover_expired_tx(connection, now)
            row = connection.execute(
                f"""
                SELECT {self._TASK_COLUMNS}
                FROM media_product.media_web_tasks
                WHERE status = 'queued' AND cancel_requested = false
                ORDER BY created_at, task_public_id
                FOR UPDATE SKIP LOCKED
                LIMIT 1
                """
            ).fetchone()
            if row is None:
                return None
            task = self._task_row(row)
            tenant_id = task["tenant_id"]
            task_public_id = task["task_id"]
            number_row = connection.execute(
                """
                SELECT COALESCE(MAX(attempt_number), 0),
                       (SELECT attempt_public_id
                          FROM media_product.media_task_execution_attempts
                         WHERE tenant_id = %s AND task_public_id = %s
                         ORDER BY attempt_number DESC LIMIT 1)
                FROM media_product.media_task_execution_attempts
                WHERE tenant_id = %s AND task_public_id = %s
                """,
                (tenant_id, task_public_id, tenant_id, task_public_id),
            ).fetchone()
            attempt_number = int(number_row[0]) + 1
            prior_attempt = str(number_row[1]) if number_row[1] else None
            attempt_public_id = f"mta_{uuid.uuid4().hex}"
            connection.execute(
                """
                INSERT INTO media_product.media_task_execution_attempts (
                    tenant_id, task_public_id, attempt_public_id, runner_public_id,
                    executor_public_id, status, attempt_number,
                    recovery_of_attempt_public_id, started_at, heartbeat_at
                ) VALUES (%s, %s, %s, %s, %s, 'claimed', %s, %s, %s, %s)
                """,
                (
                    tenant_id,
                    task_public_id,
                    attempt_public_id,
                    runner_public_id,
                    executor_public_id,
                    attempt_number,
                    prior_attempt,
                    now,
                    now,
                ),
            )
            connection.execute(
                """
                INSERT INTO media_product.media_task_runner_leases (
                    tenant_id, task_public_id, attempt_public_id, runner_public_id,
                    lease_generation, lease_expires_at, heartbeat_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    tenant_id,
                    task_public_id,
                    attempt_public_id,
                    runner_public_id,
                    attempt_number,
                    expires,
                    now,
                ),
            )
            connection.execute(
                """
                UPDATE media_product.media_web_tasks
                SET status = 'runner_claimed', settlement_stage = 'runner_claimed',
                    progress = 5, updated_at = %s
                WHERE tenant_id = %s AND task_public_id = %s
                """,
                (now, tenant_id, task_public_id),
            )
            self._append_event_tx(
                connection,
                tenant_id=tenant_id,
                task_public_id=task_public_id,
                event_type="task.runner_claimed",
                status="runner_claimed",
                progress=5,
                message="独立 runner 已领取任务。",
            )
            task.update(
                {
                    "status": "runner_claimed",
                    "settlement_stage": "runner_claimed",
                    "progress": 5,
                }
            )
        return ClaimedMediaTask(
            task=task,
            attempt_public_id=attempt_public_id,
            runner_public_id=runner_public_id,
            executor_public_id=executor_public_id,
            lease_generation=attempt_number,
            lease_expires_at=_iso(expires),
        )

    def heartbeat(self, claim: ClaimedMediaTask, *, lease_seconds: int) -> str:
        now = self._now()
        expires = now + timedelta(seconds=max(15, int(lease_seconds)))
        with self._connection_factory() as connection:
            cursor = connection.execute(
                """
                UPDATE media_product.media_task_runner_leases
                SET heartbeat_at = %s, lease_expires_at = %s
                WHERE tenant_id = %s AND task_public_id = %s
                  AND attempt_public_id = %s AND runner_public_id = %s
                  AND lease_generation = %s AND lease_expires_at > %s
                """,
                (
                    now,
                    expires,
                    claim.task["tenant_id"],
                    claim.task["task_id"],
                    claim.attempt_public_id,
                    claim.runner_public_id,
                    claim.lease_generation,
                    now,
                ),
            )
            if cursor.rowcount != 1:
                raise MediaTaskRepositoryError("runner_lease_lost", "runner 租约已经失效。")
            connection.execute(
                """
                UPDATE media_product.media_task_execution_attempts
                SET heartbeat_at = %s
                WHERE tenant_id = %s AND attempt_public_id = %s
                """,
                (now, claim.task["tenant_id"], claim.attempt_public_id),
            )
        return _iso(expires)

    def transition_claim(
        self,
        claim: ClaimedMediaTask,
        *,
        task_status: str,
        settlement_stage: str,
        attempt_status: str,
        progress: int,
        message: str,
    ) -> dict[str, Any]:
        now = self._now()
        tenant_id = claim.task["tenant_id"]
        task_public_id = claim.task["task_id"]
        with self._connection_factory() as connection:
            self._assert_lease_tx(connection, claim, now)
            connection.execute(
                """
                UPDATE media_product.media_task_execution_attempts
                SET status = %s, heartbeat_at = %s
                WHERE tenant_id = %s AND attempt_public_id = %s
                """,
                (attempt_status, now, tenant_id, claim.attempt_public_id),
            )
            connection.execute(
                """
                UPDATE media_product.media_web_tasks
                SET status = %s, settlement_stage = %s, progress = %s, updated_at = %s
                WHERE tenant_id = %s AND task_public_id = %s
                """,
                (task_status, settlement_stage, progress, now, tenant_id, task_public_id),
            )
            self._append_event_tx(
                connection,
                tenant_id=tenant_id,
                task_public_id=task_public_id,
                event_type="task.status",
                status=task_status,
                progress=progress,
                message=message,
            )
        return self._get_task_unscoped(tenant_id, task_public_id)

    def record_execution_result(
        self,
        claim: ClaimedMediaTask,
        *,
        result_projection: Mapping[str, Any],
        artifact_records: Sequence[Mapping[str, str]],
        external_objects: Sequence[Mapping[str, str]],
        external_readback: Mapping[str, Any],
    ) -> dict[str, Any]:
        _no_sensitive_keys(result_projection)
        _no_sensitive_keys(external_readback)
        now = self._now()
        task = claim.task
        tenant_id = task["tenant_id"]
        task_public_id = task["task_id"]
        if not artifact_records:
            raise MediaTaskRepositoryError(
                "artifact_required",
                "任务必须产生至少一个结构化产物后才能进入读回阶段。",
            )
        artifacts = sorted(str(item["artifact_public_id"]) for item in artifact_records)
        if len(artifacts) != len(set(artifacts)):
            raise MediaTaskRepositoryError(
                "duplicate_artifact",
                "任务结果包含重复产物编号。",
            )
        artifact_set_digest = digest_json(artifacts)
        result_digest = digest_json(result_projection)
        external_required = task["capability_id"] == "selfmedia_creation"
        consultation = task["capability_id"] == "selfmedia_creation_consultation"
        external_status = str(external_readback.get("status") or "unknown")
        if consultation:
            if external_objects or external_status != "not_applicable":
                raise MediaTaskRepositoryError(
                    "consultation_external_write_detected",
                    "只读咨询链检测到外部写入或缺少无写入证明。",
                )
            applicability = {
                "mode": "not_applicable",
                "noNewFeishuObject": external_readback.get("noNewFeishuObject") is True,
                "externalWriteSetEmpty": external_readback.get("externalWriteSet") == [],
            }
            if not all(applicability.values()):
                raise MediaTaskRepositoryError(
                    "consultation_external_proof_missing",
                    "只读咨询链缺少无飞书新增和空写入集合证明。",
                )
        elif external_required:
            if not external_objects or external_status != "verified":
                raise MediaTaskRepositoryError(
                    "external_readback_incomplete",
                    "写入创作链尚未完成飞书对象及声明应用身份读回。",
                )
            applicability = {"mode": "required"}
        else:
            if external_objects:
                raise MediaTaskRepositoryError(
                    "unexpected_external_objects",
                    "未声明外部写入的能力返回了外部对象。",
                )
            external_status = "not_applicable"
            applicability = {"mode": "not_applicable", "reason": "capability_contract"}
        with self._connection_factory() as connection:
            self._assert_lease_tx(connection, claim, now)
            for item in artifact_records:
                saved = connection.execute(
                    """
                    INSERT INTO media_product.media_task_artifacts (
                        tenant_id, task_public_id, attempt_public_id,
                        artifact_public_id, artifact_kind, content_digest
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (tenant_id, artifact_public_id) DO UPDATE
                    SET artifact_public_id = EXCLUDED.artifact_public_id
                    WHERE media_product.media_task_artifacts.task_public_id = EXCLUDED.task_public_id
                      AND media_product.media_task_artifacts.attempt_public_id = EXCLUDED.attempt_public_id
                      AND media_product.media_task_artifacts.artifact_kind = EXCLUDED.artifact_kind
                      AND media_product.media_task_artifacts.content_digest = EXCLUDED.content_digest
                    RETURNING task_public_id
                    """,
                    (
                        tenant_id,
                        task_public_id,
                        claim.attempt_public_id,
                        item["artifact_public_id"],
                        item["artifact_kind"],
                        item["content_digest"],
                    ),
                ).fetchone()
                if saved is None:
                    raise MediaTaskRepositoryError(
                        "artifact_identity_conflict",
                        "产物编号已属于其他任务、尝试或内容。",
                    )
            for item in external_objects:
                saved = connection.execute(
                    """
                    INSERT INTO media_product.media_task_external_objects (
                        tenant_id, task_public_id, attempt_public_id, external_system,
                        external_object_public_ref, object_digest, declared_application_ref
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (external_system, external_object_public_ref) DO UPDATE
                    SET external_object_public_ref = EXCLUDED.external_object_public_ref
                    WHERE media_product.media_task_external_objects.tenant_id = EXCLUDED.tenant_id
                      AND media_product.media_task_external_objects.task_public_id = EXCLUDED.task_public_id
                      AND media_product.media_task_external_objects.attempt_public_id = EXCLUDED.attempt_public_id
                      AND media_product.media_task_external_objects.object_digest = EXCLUDED.object_digest
                      AND media_product.media_task_external_objects.declared_application_ref = EXCLUDED.declared_application_ref
                    RETURNING task_public_id
                    """,
                    (
                        tenant_id,
                        task_public_id,
                        claim.attempt_public_id,
                        item["external_system"],
                        item["external_object_public_ref"],
                        item["object_digest"],
                        item["declared_application_ref"],
                    ),
                ).fetchone()
                if saved is None:
                    raise MediaTaskRepositoryError(
                        "external_object_identity_conflict",
                        "外部对象已经属于其他任务、尝试、应用身份或内容。",
                    )
            self._upsert_readback_tx(
                connection,
                tenant_id=tenant_id,
                task_public_id=task_public_id,
                attempt_public_id=claim.attempt_public_id,
                system_kind="database",
                status="verified",
                required=True,
                artifact_set_digest=artifact_set_digest,
                evidence_refs=[task_public_id, claim.attempt_public_id, *artifacts],
                applicability={},
                checked_at=now,
            )
            self._upsert_readback_tx(
                connection,
                tenant_id=tenant_id,
                task_public_id=task_public_id,
                attempt_public_id=claim.attempt_public_id,
                system_kind="external",
                status=external_status,
                required=external_required,
                artifact_set_digest=artifact_set_digest,
                evidence_refs=[str(item["external_object_public_ref"]) for item in external_objects],
                applicability=applicability,
                checked_at=now,
            )
            self._upsert_readback_tx(
                connection,
                tenant_id=tenant_id,
                task_public_id=task_public_id,
                attempt_public_id=claim.attempt_public_id,
                system_kind="web",
                status="pending",
                required=True,
                artifact_set_digest=artifact_set_digest,
                evidence_refs=[],
                applicability={},
                checked_at=None,
            )
            connection.execute(
                """
                UPDATE media_product.media_task_execution_attempts
                SET status = 'waiting_web_readback', result_digest = %s, heartbeat_at = %s
                WHERE tenant_id = %s AND attempt_public_id = %s
                """,
                (result_digest, now, tenant_id, claim.attempt_public_id),
            )
            connection.execute(
                """
                UPDATE media_product.media_web_tasks
                SET status = 'waiting_web_readback', settlement_stage = 'web_readback',
                    progress = 90, result_projection = %s::jsonb,
                    error_projection = NULL, updated_at = %s
                WHERE tenant_id = %s AND task_public_id = %s
                """,
                (_json(result_projection), now, tenant_id, task_public_id),
            )
            self._append_event_tx(
                connection,
                tenant_id=tenant_id,
                task_public_id=task_public_id,
                event_type="task.readback",
                status="waiting_web_readback",
                progress=90,
                message="数据库及适用的外部读回已完成，等待网页读回。",
            )
        return self._get_task_unscoped(tenant_id, task_public_id)

    def record_failure(
        self,
        claim: ClaimedMediaTask,
        *,
        code: str,
        message: str,
        action: str,
        needs_manual: bool,
    ) -> dict[str, Any]:
        now = self._now()
        tenant_id = claim.task["tenant_id"]
        task_public_id = claim.task["task_id"]
        task_status = "pending_manual" if needs_manual else "failed"
        attempt_status = "needs_manual" if needs_manual else "failed"
        stage = "needs_manual" if needs_manual else "failed"
        error = {"code": code, "message": message, "action": action}
        _no_sensitive_keys(error)
        with self._connection_factory() as connection:
            self._assert_lease_tx(connection, claim, now)
            connection.execute(
                """
                UPDATE media_product.media_task_execution_attempts
                SET status = %s, failure_code = %s, finished_at = %s, heartbeat_at = %s
                WHERE tenant_id = %s AND attempt_public_id = %s
                """,
                (attempt_status, code, now, now, tenant_id, claim.attempt_public_id),
            )
            connection.execute(
                """
                UPDATE media_product.media_web_tasks
                SET status = %s, settlement_stage = %s, progress = 100,
                    error_projection = %s::jsonb, updated_at = %s
                WHERE tenant_id = %s AND task_public_id = %s
                """,
                (task_status, stage, _json(error), now, tenant_id, task_public_id),
            )
            connection.execute(
                "DELETE FROM media_product.media_task_runner_leases WHERE tenant_id = %s AND task_public_id = %s AND attempt_public_id = %s",
                (tenant_id, task_public_id, claim.attempt_public_id),
            )
            self._append_event_tx(
                connection,
                tenant_id=tenant_id,
                task_public_id=task_public_id,
                event_type="task.error",
                status=task_status,
                progress=100,
                message="任务需要人工核对。" if needs_manual else "任务执行未完成。",
            )
        return self._get_task_unscoped(tenant_id, task_public_id)

    def confirm_web_readback(
        self,
        tenant_id: str,
        actor_public_id: str,
        task_public_id: str,
    ) -> dict[str, Any]:
        now = self._now()
        with self._connection_factory() as connection:
            row = connection.execute(
                f"SELECT {self._TASK_COLUMNS} FROM media_product.media_web_tasks WHERE tenant_id = %s AND actor_public_id = %s AND task_public_id = %s FOR UPDATE",
                (tenant_id, actor_public_id, task_public_id),
            ).fetchone()
            if row is None:
                raise MediaTaskRepositoryError("task_not_found", "未找到该任务。")
            task = self._task_row(row)
            if task["status"] == "multi_system_readback_complete":
                return task
            if task["status"] != "waiting_web_readback":
                return task
            attempt = connection.execute(
                """
                SELECT attempt_public_id, runner_public_id, executor_public_id,
                       started_at, heartbeat_at, recovery_of_attempt_public_id,
                       result_digest
                FROM media_product.media_task_execution_attempts
                WHERE tenant_id = %s AND task_public_id = %s
                  AND status = 'waiting_web_readback'
                ORDER BY attempt_number DESC LIMIT 1 FOR UPDATE
                """,
                (tenant_id, task_public_id),
            ).fetchone()
            if attempt is None:
                raise MediaTaskRepositoryError("receipt_invariant_failed", "任务缺少可结算执行尝试。")
            artifact_rows = connection.execute(
                """
                SELECT artifact_public_id, content_digest
                FROM media_product.media_task_artifacts
                WHERE tenant_id = %s AND task_public_id = %s
                ORDER BY artifact_public_id
                """,
                (tenant_id, task_public_id),
            ).fetchall()
            artifacts = [str(item[0]) for item in artifact_rows]
            artifact_set_digest = digest_json(artifacts)
            self._upsert_readback_tx(
                connection,
                tenant_id=tenant_id,
                task_public_id=task_public_id,
                attempt_public_id=str(attempt[0]),
                system_kind="web",
                status="verified",
                required=True,
                artifact_set_digest=artifact_set_digest,
                evidence_refs=[task_public_id, *artifacts],
                applicability={},
                checked_at=now,
            )
            readback_rows = connection.execute(
                """
                SELECT system_kind, status, required, artifact_set_digest,
                       evidence_refs, applicability, checked_at
                FROM media_product.media_task_readbacks
                WHERE tenant_id = %s AND task_public_id = %s
                ORDER BY system_kind
                """,
                (tenant_id, task_public_id),
            ).fetchall()
            readbacks = {
                str(item[0]): {
                    "status": str(item[1]),
                    "required": bool(item[2]),
                    "artifactSetDigest": str(item[3] or ""),
                    "evidenceRefs": _json_value(item[4], []),
                    "applicability": _json_value(item[5], {}),
                    "checkedAt": _iso(item[6]),
                }
                for item in readback_rows
            }
            self._validate_readbacks(task, readbacks, artifact_set_digest)
            binding = connection.execute(
                """
                SELECT binding.id, binding.actor_public_id,
                       binding.owned_account_public_id, binding.platform,
                       binding.submitted_account_ref_digest,
                       lower(btrim(account.canonical_data->>'platform')),
                       lower(btrim(account.canonical_data->>'account_name'))
                FROM media_product.media_task_account_bindings AS binding
                JOIN media_product.owned_media_accounts AS account
                  ON account.tenant_id = binding.tenant_id
                 AND account.public_id = binding.owned_account_public_id
                WHERE binding.tenant_id = %s
                  AND binding.actor_public_id = %s
                  AND binding.owned_account_public_id = %s
                  AND binding.status = 'active'
                  AND account.account_category = 'customer_owned'
                """,
                (tenant_id, task["actor_public_id"], task["owned_account_public_id"]),
            ).fetchone()
            receipt_requires_account = task_requires_owned_account(
                str(task["capability_id"]),
                task["invocation"].get("params") or {},
            )
            frozen_value = task["invocation"].get("account_binding")
            frozen_binding = dict(frozen_value) if isinstance(frozen_value, Mapping) else None
            receipt_binding: dict[str, str] | None = None
            if receipt_requires_account:
                if frozen_binding is None or binding is None:
                    raise MediaTaskRepositoryError("receipt_invariant_failed", "任务账号绑定不可用。")
                expected_binding = {
                    "actor_public_id": str(frozen_binding.get("actor_public_id") or "").strip(),
                    "owned_account_public_id": str(
                        frozen_binding.get("owned_account_public_id") or ""
                    ).strip(),
                    "relationship_ref": str(frozen_binding.get("relationship_ref") or "").strip(),
                    "platform": str(frozen_binding.get("platform") or "").strip().casefold(),
                    "normalized_account": str(
                        frozen_binding.get("normalized_account") or ""
                    ).strip().casefold(),
                    "submitted_account_ref_digest": str(
                        frozen_binding.get("submitted_account_ref_digest") or ""
                    ).strip(),
                }
                current_binding = {
                    "actor_public_id": str(binding[1]),
                    "owned_account_public_id": str(binding[2]),
                    "relationship_ref": f"relationship:{binding[0]}",
                    "platform": str(binding[3] or "").strip().casefold(),
                    "normalized_account": str(binding[6] or "").strip().casefold(),
                    "submitted_account_ref_digest": str(binding[4] or "").strip(),
                }
                current_account_platform = str(binding[5] or "").strip().casefold()
                expected_digest = digest_json(
                    {
                        "platform": expected_binding["platform"],
                        "account": expected_binding["normalized_account"],
                    }
                )
                if (
                    not all(expected_binding.values())
                    or expected_binding["actor_public_id"] != task["actor_public_id"]
                    or expected_binding["owned_account_public_id"]
                    != task["owned_account_public_id"]
                    or expected_binding["submitted_account_ref_digest"] != expected_digest
                    or current_account_platform != expected_binding["platform"]
                    or current_binding != expected_binding
                ):
                    raise MediaTaskRepositoryError(
                        "receipt_invariant_failed",
                        "任务账号绑定与入队冻结值不一致。",
                    )
                receipt_binding = expected_binding
            receipt_public_id = f"mtr_{uuid.uuid4().hex}"
            receipt = {
                "schemaVersion": RECEIPT_SCHEMA_VERSION,
                "receiptId": receipt_public_id,
                "capturedAt": _iso(now),
                "tenantRef": tenant_id,
                "actorPublicId": task["actor_public_id"],
                "account": None
                if receipt_binding is None
                else {
                    "ownedAccountPublicId": receipt_binding["owned_account_public_id"],
                    "relationshipRef": receipt_binding["relationship_ref"],
                    "platform": receipt_binding["platform"],
                    "normalizedAccount": receipt_binding["normalized_account"],
                    "submittedAccountRefDigest": receipt_binding[
                        "submitted_account_ref_digest"
                    ],
                },
                "context": {
                    "digest": digest_json(task["invocation"].get("params") or {}),
                    "sourcePublicRefs": self._source_public_refs(task["invocation"].get("params") or {}),
                },
                "task": {
                    "taskId": task_public_id,
                    "capabilityId": task["capability_id"],
                    "variantId": task["variant_id"],
                    "idempotencyKeyDigest": digest_json(task["idempotency_key"]),
                },
                "attempt": {
                    "attemptId": str(attempt[0]),
                    "runnerId": str(attempt[1]),
                    "executorId": str(attempt[2]),
                    "recoveryOfAttemptId": str(attempt[5] or "") or None,
                    "startedAt": _iso(attempt[3]),
                    "finishedAt": _iso(now),
                },
                "result": {
                    "resultDigest": str(attempt[6]),
                    "artifactPublicIds": artifacts,
                },
                "readbacks": readbacks,
                "settlement": {"stage": "multi_system_readback_complete"},
            }
            _no_sensitive_keys(receipt)
            receipt_digest = digest_json(receipt)
            connection.execute(
                """
                INSERT INTO media_product.media_task_receipts (
                    tenant_id, task_public_id, attempt_public_id, receipt_public_id,
                    schema_version, receipt_digest, receipt_projection,
                    settlement_stage, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb,
                          'multi_system_readback_complete', %s)
                """,
                (
                    tenant_id,
                    task_public_id,
                    str(attempt[0]),
                    receipt_public_id,
                    RECEIPT_SCHEMA_VERSION,
                    receipt_digest,
                    _json(receipt),
                    now,
                ),
            )
            connection.execute(
                """
                UPDATE media_product.media_task_execution_attempts
                SET status = 'completed', finished_at = %s, heartbeat_at = %s
                WHERE tenant_id = %s AND attempt_public_id = %s
                """,
                (now, now, tenant_id, str(attempt[0])),
            )
            connection.execute(
                """
                UPDATE media_product.media_web_tasks
                SET status = 'multi_system_readback_complete',
                    settlement_stage = 'multi_system_readback_complete',
                    progress = 100, updated_at = %s
                WHERE tenant_id = %s AND task_public_id = %s
                """,
                (now, tenant_id, task_public_id),
            )
            connection.execute(
                "DELETE FROM media_product.media_task_runner_leases WHERE tenant_id = %s AND task_public_id = %s AND attempt_public_id = %s",
                (tenant_id, task_public_id, str(attempt[0])),
            )
            self._append_event_tx(
                connection,
                tenant_id=tenant_id,
                task_public_id=task_public_id,
                event_type="task.receipt",
                status="multi_system_readback_complete",
                progress=100,
                message="数据库、适用的外部系统和网页读回已由同一收据结算。",
            )
        return self.get_task(tenant_id, actor_public_id, task_public_id)

    def get_settlement(
        self,
        tenant_id: str,
        actor_public_id: str,
        task_public_id: str,
    ) -> dict[str, Any]:
        self.get_task(tenant_id, actor_public_id, task_public_id)
        with self._connection_factory() as connection:
            attempt = connection.execute(
                """
                SELECT attempt_public_id, runner_public_id, executor_public_id,
                       status, attempt_number, recovery_of_attempt_public_id,
                       started_at, heartbeat_at, finished_at
                FROM media_product.media_task_execution_attempts
                WHERE tenant_id = %s AND task_public_id = %s
                ORDER BY attempt_number DESC LIMIT 1
                """,
                (tenant_id, task_public_id),
            ).fetchone()
            readbacks = connection.execute(
                """
                SELECT system_kind, status, required, applicability, checked_at
                FROM media_product.media_task_readbacks
                WHERE tenant_id = %s AND task_public_id = %s
                ORDER BY system_kind
                """,
                (tenant_id, task_public_id),
            ).fetchall()
            receipt = connection.execute(
                """
                SELECT receipt_public_id, schema_version, receipt_digest, settlement_stage, created_at
                FROM media_product.media_task_receipts
                WHERE tenant_id = %s AND task_public_id = %s
                """,
                (tenant_id, task_public_id),
            ).fetchone()
        return {
            "attempt": None
            if attempt is None
            else {
                "attemptId": str(attempt[0]),
                "runnerId": str(attempt[1]),
                "executorId": str(attempt[2]),
                "status": str(attempt[3]),
                "attemptNumber": int(attempt[4]),
                "recoveryOfAttemptId": str(attempt[5] or "") or None,
                "startedAt": _iso(attempt[6]),
                "heartbeatAt": _iso(attempt[7]),
                "finishedAt": _iso(attempt[8]) or None,
            },
            "readbacks": {
                str(item[0]): {
                    "status": str(item[1]),
                    "required": bool(item[2]),
                    "applicability": _json_value(item[3], {}),
                    "checkedAt": _iso(item[4]) or None,
                }
                for item in readbacks
            },
            "receipt": None
            if receipt is None
            else {
                "receiptId": str(receipt[0]),
                "schemaVersion": str(receipt[1]),
                "digest": str(receipt[2]),
                "status": str(receipt[3]),
                "createdAt": _iso(receipt[4]),
            },
        }

    def _recover_expired_tx(self, connection: Any, now: datetime) -> None:
        rows = connection.execute(
            """
            SELECT l.tenant_id, l.task_public_id, l.attempt_public_id,
                   task.cancel_requested
            FROM media_product.media_task_runner_leases AS l
            JOIN media_product.media_web_tasks AS task
              ON task.tenant_id = l.tenant_id
             AND task.task_public_id = l.task_public_id
            WHERE l.lease_expires_at <= %s
              AND task.status NOT IN (
                  'multi_system_readback_complete', 'pending_manual', 'failed', 'cancelled'
              )
            FOR UPDATE OF l, task SKIP LOCKED
            """,
            (now,),
        ).fetchall()
        for tenant_id, task_public_id, attempt_public_id, cancel_requested in rows:
            connection.execute(
                """
                UPDATE media_product.media_task_execution_attempts
                SET status = 'expired', finished_at = %s, failure_code = 'runner_lease_expired'
                WHERE tenant_id = %s AND attempt_public_id = %s
                  AND status IN ('claimed', 'running', 'waiting_database_readback', 'waiting_external_readback', 'waiting_web_readback')
                """,
                (now, tenant_id, attempt_public_id),
            )
            if cancel_requested:
                status = "pending_manual"
                stage = "needs_manual"
                progress = 100
                summary = "取消请求后 runner 租约失效，任务需要人工对账。"
                error_projection = {
                    "code": "cancelled_lease_expired",
                    "message": summary,
                    "action": "核对可能已经发生的外部写入后再决定后续处理。",
                }
            else:
                status = "queued"
                stage = "queued"
                progress = 0
                summary = "runner 租约过期，任务已进入恢复队列。"
                error_projection = None
            connection.execute(
                """
                UPDATE media_product.media_web_tasks
                SET status = %s, settlement_stage = %s, progress = %s,
                    summary = %s, error_projection = %s::jsonb, updated_at = %s
                WHERE tenant_id = %s AND task_public_id = %s
                """,
                (
                    status,
                    stage,
                    progress,
                    summary,
                    None if error_projection is None else _json(error_projection),
                    now,
                    tenant_id,
                    task_public_id,
                ),
            )
            connection.execute(
                "DELETE FROM media_product.media_task_runner_leases WHERE tenant_id = %s AND task_public_id = %s AND attempt_public_id = %s",
                (tenant_id, task_public_id, attempt_public_id),
            )
            self._append_event_tx(
                connection,
                tenant_id=str(tenant_id),
                task_public_id=str(task_public_id),
                event_type="task.error" if cancel_requested else "task.recovered",
                status=status,
                progress=progress,
                message=summary,
            )

    def _assert_lease_tx(self, connection: Any, claim: ClaimedMediaTask, now: datetime) -> None:
        row = connection.execute(
            """
            SELECT 1
            FROM media_product.media_task_runner_leases
            WHERE tenant_id = %s AND task_public_id = %s
              AND attempt_public_id = %s AND runner_public_id = %s
              AND lease_generation = %s AND lease_expires_at > %s
            FOR UPDATE
            """,
            (
                claim.task["tenant_id"],
                claim.task["task_id"],
                claim.attempt_public_id,
                claim.runner_public_id,
                claim.lease_generation,
                now,
            ),
        ).fetchone()
        if row is None:
            raise MediaTaskRepositoryError("runner_lease_lost", "runner 租约已经失效。")

    def _append_event_tx(
        self,
        connection: Any,
        *,
        tenant_id: str,
        task_public_id: str,
        event_type: str,
        status: str,
        progress: int,
        message: str,
    ) -> None:
        row = connection.execute(
            """
            UPDATE media_product.media_web_tasks
            SET event_cursor = event_cursor + 1, updated_at = %s
            WHERE tenant_id = %s AND task_public_id = %s
            RETURNING event_cursor
            """,
            (self._now(), tenant_id, task_public_id),
        ).fetchone()
        if row is None:
            raise MediaTaskRepositoryError("task_not_found", "未找到该任务。")
        connection.execute(
            """
            INSERT INTO media_product.media_web_task_events (
                tenant_id, task_public_id, event_number, event_type,
                status, progress, message, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                tenant_id,
                task_public_id,
                int(row[0]),
                event_type,
                status,
                max(0, min(int(progress), 100)),
                message,
                self._now(),
            ),
        )

    @staticmethod
    def _upsert_readback_tx(
        connection: Any,
        *,
        tenant_id: str,
        task_public_id: str,
        attempt_public_id: str,
        system_kind: str,
        status: str,
        required: bool,
        artifact_set_digest: str,
        evidence_refs: Sequence[str],
        applicability: Mapping[str, Any],
        checked_at: datetime | None,
    ) -> None:
        connection.execute(
            """
            INSERT INTO media_product.media_task_readbacks (
                tenant_id, task_public_id, attempt_public_id, system_kind,
                status, required, artifact_set_digest, evidence_refs,
                applicability, checked_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s)
            ON CONFLICT (tenant_id, task_public_id, system_kind) DO UPDATE
            SET attempt_public_id = EXCLUDED.attempt_public_id,
                status = EXCLUDED.status,
                required = EXCLUDED.required,
                artifact_set_digest = EXCLUDED.artifact_set_digest,
                evidence_refs = EXCLUDED.evidence_refs,
                applicability = EXCLUDED.applicability,
                checked_at = EXCLUDED.checked_at
            """,
            (
                tenant_id,
                task_public_id,
                attempt_public_id,
                system_kind,
                status,
                required,
                artifact_set_digest,
                _json(list(evidence_refs)),
                _json(dict(applicability)),
                checked_at,
            ),
        )

    @staticmethod
    def _validate_readbacks(
        task: Mapping[str, Any],
        readbacks: Mapping[str, Mapping[str, Any]],
        artifact_set_digest: str,
    ) -> None:
        expected = {"database", "external", "web"}
        if set(readbacks) != expected:
            raise MediaTaskRepositoryError("receipt_invariant_failed", "多系统读回集合不完整。")
        for kind in ("database", "web"):
            item = readbacks[kind]
            if item["status"] != "verified" or item["required"] is not True:
                raise MediaTaskRepositoryError("receipt_invariant_failed", f"{kind} 读回尚未验证。")
            if item["artifactSetDigest"] != artifact_set_digest:
                raise MediaTaskRepositoryError("receipt_invariant_failed", f"{kind} 读回产物集合不一致。")
        external = readbacks["external"]
        if task["capability_id"] == "selfmedia_creation":
            if external["status"] != "verified" or external["required"] is not True:
                raise MediaTaskRepositoryError("receipt_invariant_failed", "飞书读回尚未验证。")
        elif external["status"] != "not_applicable" or external["required"] is not False:
            raise MediaTaskRepositoryError("receipt_invariant_failed", "外部读回适用性不一致。")
        if external["artifactSetDigest"] != artifact_set_digest:
            raise MediaTaskRepositoryError("receipt_invariant_failed", "外部读回产物集合不一致。")

    @staticmethod
    def _source_public_refs(params: Mapping[str, Any]) -> list[str]:
        keys = ("source_asset_id", "publicAssetId", "publicProjectId", "publicRunId")
        return sorted(
            {
                str(params[key])
                for key in keys
                if isinstance(params.get(key), str) and str(params[key]).strip()
            }
        )

    @staticmethod
    def _task_row(row: Any) -> dict[str, Any]:
        if not isinstance(row, (tuple, list)) or len(row) != 24:
            raise MediaTaskRepositoryError("invalid_task_state", "任务数据库投影结构无效。")
        return {
            "tenant_id": str(row[0]),
            "task_id": str(row[1]),
            "actor_public_id": str(row[2]),
            "owned_account_public_id": str(row[3] or "") or None,
            "idempotency_key": str(row[4]),
            "request_fingerprint": str(row[5]),
            "capability_id": str(row[6]),
            "variant_id": str(row[7]),
            "catalog_version": str(row[8]),
            "invocation": _json_value(row[9], {}),
            "capability_path": _json_value(row[10], []),
            "authorization": _json_value(row[11], {}),
            "confirmation": _json_value(row[12], {}),
            "status": str(row[13]),
            "settlement_stage": str(row[14]),
            "progress": int(row[15]),
            "summary": str(row[16] or ""),
            "result": _json_value(row[17], None),
            "error": _json_value(row[18], None),
            "cancel_requested": bool(row[19]),
            "model_request_root": str(row[20] or ""),
            "event_cursor": int(row[21]),
            "created_at": _iso(row[22]),
            "updated_at": _iso(row[23]),
        }
