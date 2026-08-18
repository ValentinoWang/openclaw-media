"""Canonical DeepMath-only Feishu Tasks v2 executor for approved U7 claims."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Callable, Mapping

import requests

from .deepmath_approval_service import DeepMathExecutionClaim
from .deepmath_resources import (
    DEFAULT_TIMEZONE,
    DEEP_MATH_TENANT_KEY,
    TASKLIST_NAME,
    DeepMathResourceConfig,
)


FEISHU_API = "https://open.feishu.cn/open-apis"
TASK_CREATE_PATH = "/task/v2/tasks"
TASK_GET_PATH = "/task/v2/tasks/{task_guid}"
USER_ID_TYPE = "open_id"


class DeepMathTasksContractError(ValueError):
    """The approved claim is not a complete canonical task-create request."""


class DeepMathTasksUpstreamRejected(RuntimeError):
    """Feishu explicitly rejected a request before creation was acknowledged."""

    def __init__(self, message: str, *, request_id: str | None = None) -> None:
        super().__init__(message)
        self.request_id = request_id


class DeepMathTasksResultUnknown(RuntimeError):
    """A task may exist or its exact state could not be proved by readback."""


@dataclass(frozen=True)
class CanonicalTaskRequest:
    summary: str
    description: str
    due: Mapping[str, Any]
    members: tuple[Mapping[str, str], ...]
    tasklist_id: str
    client_token: str
    reminder: Mapping[str, int]

    def body(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "description": self.description,
            "due": dict(self.due),
            "members": [dict(item) for item in self.members],
            "tasklists": [{"tasklist_guid": self.tasklist_id}],
            "client_token": self.client_token,
            "reminders": [dict(self.reminder)],
        }


def _text(value: Any, field: str, *, limit: int = 10000) -> str:
    result = str(value or "").strip()
    if not result:
        raise DeepMathTasksContractError(f"{field} is required")
    return result[:limit]


def _description(payload: Mapping[str, Any]) -> str:
    purpose = _text(payload.get("purpose"), "purpose")
    source = _text(payload.get("source_thought_id") or payload.get("thought_link"), "thought source")
    deliverable = _text(payload.get("deliverable"), "deliverable")
    acceptance = _text(payload.get("acceptance_criteria"), "acceptance_criteria")
    return "\n\n".join((
        f"【目的】\n{purpose}",
        f"【思考来源】\n{source}",
        f"【交付物】\n{deliverable}",
        f"【验收标准】\n{acceptance}",
    ))


def canonical_task_request(claim: DeepMathExecutionClaim, resource: DeepMathResourceConfig) -> CanonicalTaskRequest:
    item = claim.item
    payload = claim.payload
    if str(item.get("tenant_key") or "") != DEEP_MATH_TENANT_KEY:
        raise DeepMathTasksContractError("tenant_key must be deepmath")
    if str(item.get("execution_state") or "") != "执行中":
        raise DeepMathTasksContractError("claim must be executing")
    _text(item.get("claim_token"), "claim_token")
    execution_key = _text(item.get("execution_key"), "execution_key", limit=100)
    if not 10 <= len(execution_key) <= 100:
        raise DeepMathTasksContractError("execution_key length is invalid")
    if payload.get("object_type") != "任务" or payload.get("action") != "创建":
        raise DeepMathTasksContractError("only task create is supported")
    if resource.tenant_key != DEEP_MATH_TENANT_KEY or resource.tasklist_name != TASKLIST_NAME:
        raise DeepMathTasksContractError("resource is not the canonical DeepMath tasklist")
    if resource.timezone != DEFAULT_TIMEZONE or not resource.tasklist_id:
        raise DeepMathTasksContractError("canonical task resource is incomplete")
    if str(payload.get("tasklist_id") or "") != resource.tasklist_id:
        raise DeepMathTasksContractError("tasklist_id is not canonical")

    due = payload.get("due")
    if not isinstance(due, Mapping) or str(due.get("timezone") or "") != DEFAULT_TIMEZONE:
        raise DeepMathTasksContractError("due timezone must be Asia/Shanghai")
    timestamp = _text(due.get("timestamp"), "due.timestamp")
    if not timestamp.isdigit() or int(timestamp) <= 0 or int(timestamp) % 1000:
        raise DeepMathTasksContractError("due.timestamp must be positive whole-second milliseconds")
    if not isinstance(due.get("is_all_day"), bool):
        raise DeepMathTasksContractError("due.is_all_day must be boolean")

    reminders = payload.get("reminders")
    if not isinstance(reminders, list) or len(reminders) != 1 or not isinstance(reminders[0], Mapping):
        raise DeepMathTasksContractError("exactly one reminder is required")
    relative = reminders[0].get("relative_fire_minute")
    if isinstance(relative, bool) or not isinstance(relative, int) or relative < 0:
        raise DeepMathTasksContractError("reminder must be a non-negative minute offset")

    people = payload.get("people_assignment")
    if not isinstance(people, Mapping) or people.get("status") != "confirmed":
        raise DeepMathTasksContractError("confirmed people_assignment is required")
    assignments = people.get("resolved_assignments")
    if not isinstance(assignments, list) or not assignments:
        raise DeepMathTasksContractError("resolved_assignments are required")
    roles: dict[str, str] = {}
    for assignment in assignments:
        if not isinstance(assignment, Mapping):
            raise DeepMathTasksContractError("assignment is invalid")
        role = str(assignment.get("role") or "").strip()
        identity = _text(assignment.get("directory_id"), "assignment.directory_id", limit=200)
        if role not in {"DRI", "Reviewer"} or role in roles:
            raise DeepMathTasksContractError("assignments require one DRI and at most one Reviewer")
        roles[role] = identity
    if set(roles) not in ({"DRI"}, {"DRI", "Reviewer"}):
        raise DeepMathTasksContractError("assignments require exactly one DRI")
    members = tuple(
        {"id": roles[role], "type": "user", "role": api_role}
        for role, api_role in (("DRI", "assignee"), ("Reviewer", "follower"))
        if role in roles
    )
    return CanonicalTaskRequest(
        summary=_text(payload.get("summary"), "summary", limit=300),
        description=_description(payload),
        due={"timestamp": timestamp, "is_all_day": due["is_all_day"]},
        members=members,
        tasklist_id=resource.tasklist_id,
        client_token=execution_key,
        reminder={"relative_fire_minute": relative},
    )


class DeepMathTasksTransport:
    """Minimal Tasks v2 transport: authenticate, create once, then read once."""

    def __init__(self, access_token: str, *, session: Any = requests, timeout: int = 30) -> None:
        self._token = _text(access_token, "access_token", limit=1000)
        self._session = session
        self._timeout = timeout

    @classmethod
    def from_app_credentials(cls, app_id: str, app_secret: str, *, session: Any = requests, timeout: int = 30) -> "DeepMathTasksTransport":
        try:
            response = session.post(
                FEISHU_API + "/auth/v3/tenant_access_token/internal",
                json={"app_id": app_id, "app_secret": app_secret},
                timeout=timeout,
            )
            payload = response.json()
        except (requests.Timeout, requests.ConnectionError, ValueError) as exc:
            raise DeepMathTasksResultUnknown("DeepMath Tasks authentication result is unknown") from exc
        if response.status_code >= 400 or not isinstance(payload, Mapping) or payload.get("code") not in (None, 0):
            raise DeepMathTasksUpstreamRejected("DeepMath Tasks authentication was rejected")
        return cls(_text(payload.get("tenant_access_token"), "tenant_access_token"), session=session, timeout=timeout)

    @staticmethod
    def _request_id(response: Any) -> str | None:
        headers = getattr(response, "headers", {}) or {}
        return str(headers.get("X-Tt-Logid") or headers.get("X-Request-Id") or "").strip() or None

    def _request(self, method: str, path: str, *, body: Mapping[str, Any] | None = None, mutated: bool) -> tuple[dict[str, Any], str | None]:
        try:
            response = self._session.request(
                method,
                FEISHU_API + path,
                headers={"Authorization": f"Bearer {self._token}"},
                params={"user_id_type": USER_ID_TYPE},
                json=dict(body) if body is not None else None,
                timeout=self._timeout,
            )
        except (requests.Timeout, requests.ConnectionError) as exc:
            raise DeepMathTasksResultUnknown("Feishu Tasks transport result is unknown") from exc
        request_id = self._request_id(response)
        try:
            payload = response.json()
        except ValueError as exc:
            raise DeepMathTasksResultUnknown("Feishu Tasks returned non-JSON") from exc
        if not isinstance(payload, Mapping):
            raise DeepMathTasksResultUnknown("Feishu Tasks returned invalid JSON")
        if response.status_code >= 400 or payload.get("code") not in (None, 0):
            if mutated:
                raise DeepMathTasksResultUnknown("Feishu Tasks readback was rejected")
            raise DeepMathTasksUpstreamRejected("Feishu Tasks create was rejected", request_id=request_id)
        return dict(payload), request_id

    def create(self, body: Mapping[str, Any]) -> tuple[dict[str, Any], str | None]:
        return self._request("POST", TASK_CREATE_PATH, body=body, mutated=False)

    def get(self, task_guid: str) -> tuple[dict[str, Any], str | None]:
        path = TASK_GET_PATH.format(task_guid=_text(task_guid, "task_guid", limit=200))
        return self._request("GET", path, mutated=True)


def _task(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    data = payload.get("data")
    if isinstance(data, Mapping) and isinstance(data.get("task"), Mapping):
        return data["task"]
    raise DeepMathTasksResultUnknown("Feishu Tasks response did not contain a task")


def _normalize_members(value: Any) -> set[tuple[str, str, str]]:
    if not isinstance(value, list):
        return set()
    return {
        (str(item.get("id") or ""), str(item.get("type") or ""), str(item.get("role") or ""))
        for item in value if isinstance(item, Mapping)
    }


def _verify_readback(task: Mapping[str, Any], expected: CanonicalTaskRequest) -> None:
    if str(task.get("summary") or "") != expected.summary or str(task.get("description") or "") != expected.description:
        raise DeepMathTasksResultUnknown("task text readback mismatch")
    due = task.get("due")
    if not isinstance(due, Mapping) or str(due.get("timestamp") or "") != str(expected.due["timestamp"]) or due.get("is_all_day") is not expected.due["is_all_day"]:
        raise DeepMathTasksResultUnknown("task due readback mismatch")
    if _normalize_members(task.get("members")) != _normalize_members([dict(item) for item in expected.members]):
        raise DeepMathTasksResultUnknown("task member readback mismatch")
    tasklists = task.get("tasklists")
    if not isinstance(tasklists, list) or {str(item.get("tasklist_guid") or item.get("guid") or "") for item in tasklists if isinstance(item, Mapping)} != {expected.tasklist_id}:
        raise DeepMathTasksResultUnknown("tasklist readback mismatch")
    reminders = task.get("reminders")
    if not isinstance(reminders, list) or len(reminders) != 1 or reminders[0].get("relative_fire_minute") != expected.reminder["relative_fire_minute"]:
        raise DeepMathTasksResultUnknown("task reminder readback mismatch")


class DeepMathTasksExecutor:
    def __init__(self, transport: DeepMathTasksTransport, resource: DeepMathResourceConfig, *, clock: Callable[[], datetime] | None = None) -> None:
        self.transport = transport
        self.resource = resource
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def __call__(self, claim: DeepMathExecutionClaim) -> dict[str, Any]:
        try:
            expected = canonical_task_request(claim, self.resource)
        except DeepMathTasksContractError as exc:
            return {"status": "failed", "error_code": "invalid_task_claim", "receipt": {"status": "failed", "reason": str(exc)}}
        try:
            created_payload, create_request_id = self.transport.create(expected.body())
            created = _task(created_payload)
            task_guid = _text(created.get("guid"), "created task guid", limit=200)
            readback_payload, read_request_id = self.transport.get(task_guid)
            readback = _task(readback_payload)
            if str(readback.get("guid") or "") != task_guid:
                raise DeepMathTasksResultUnknown("task identity readback mismatch")
            _verify_readback(readback, expected)
            task_url = str(readback.get("url") or "").strip() or None
            now = self._clock()
            if now.tzinfo is None:
                now = now.replace(tzinfo=timezone.utc)
            readback_at = now.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
            return {
                "status": "success",
                "upstream_request_id": read_request_id or create_request_id,
                "external_object_id": task_guid,
                "external_url": task_url,
                "last_readback_at": readback_at,
                "receipt": {
                    "status": "success",
                    "execution_key_sha256": hashlib.sha256(expected.client_token.encode("utf-8")).hexdigest(),
                    "tasklist": TASKLIST_NAME,
                    "timezone": DEFAULT_TIMEZONE,
                    "member_roles": [item["role"] for item in expected.members],
                    "reminder_count": 1,
                    "readback_verified": True,
                },
            }
        except DeepMathTasksUpstreamRejected as exc:
            return {
                "status": "failed",
                "error_code": "tasks_upstream_rejected",
                "upstream_request_id": exc.request_id,
                "receipt": {"status": "failed", "reason": "upstream_rejected"},
            }
        except (DeepMathTasksResultUnknown, DeepMathTasksContractError) as exc:
            return {
                "status": "result_unknown",
                "error_code": "tasks_result_unknown",
                "receipt": {"status": "result_unknown", "reason": str(exc), "retry": "forbidden_without_reconciliation"},
            }


__all__ = [
    "CanonicalTaskRequest",
    "DeepMathTasksContractError",
    "DeepMathTasksExecutor",
    "DeepMathTasksResultUnknown",
    "DeepMathTasksTransport",
    "DeepMathTasksUpstreamRejected",
    "canonical_task_request",
]
