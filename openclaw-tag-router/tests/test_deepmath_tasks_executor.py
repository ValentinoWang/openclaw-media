from datetime import datetime, timezone
from unittest.mock import patch

import requests

from openclaw_app.services import deepmath_approval_callback as callback_module
from openclaw_app.services.deepmath_approval_callback import DeepMathApprovalCallbackConfig
from openclaw_app.services.deepmath_approval_service import DeepMathExecutionClaim
from openclaw_app.services.deepmath_resources import DeepMathResourceConfig
from openclaw_app.services.deepmath_tasks_executor import (
    DeepMathTasksExecutor,
    DeepMathTasksTransport,
    DeepMathTasksUpstreamRejected,
)


TASKLIST_ID = "canonical-tasklist"
TASK_GUID = "created-task"


class Response:
    def __init__(self, payload=None, status=200, headers=None, json_error=False):
        self.payload = payload
        self.status_code = status
        self.headers = headers or {}
        self.json_error = json_error

    def json(self):
        if self.json_error:
            raise ValueError("not json")
        return self.payload


class Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        value = self.responses.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


def resource():
    return DeepMathResourceConfig(
        tenant_key="deepmath",
        base_name="DeepMath CEO Thinking",
        tasklist_name="DeepMath CEO Actions",
        calendar_name="DeepMath CEO Calendar",
        timezone="Asia/Shanghai",
        base_id="canonical-base",
        tasklist_id=TASKLIST_ID,
        calendar_id="canonical-calendar",
        base_url="https://example.invalid/base/canonical-base",
        tenant_proof="tenant-proof",
    )


def claim(**payload_updates):
    payload = {
        "object_type": "任务",
        "action": "创建",
        "tasklist_id": TASKLIST_ID,
        "summary": "完成一个可验收实验",
        "purpose": "验证关键假设",
        "source_thought_id": "thought-reference",
        "deliverable": "实验记录",
        "acceptance_criteria": "记录结果并给出结论",
        "due": {"timestamp": "1785945600000", "timezone": "Asia/Shanghai", "is_all_day": False},
        "reminders": [{"relative_fire_minute": 30}],
        "people_assignment": {
            "status": "confirmed",
            "resolved_assignments": [
                {"directory_id": "dri-user", "role": "DRI"},
                {"directory_id": "reviewer-user", "role": "Reviewer"},
            ],
        },
    }
    payload.update(payload_updates)
    return DeepMathExecutionClaim({
        "tenant_key": "deepmath",
        "execution_state": "执行中",
        "claim_token": "claim-token",
        "execution_key": "execution-key-stable",
        "canonical_payload": payload,
    })


def task_from_body(body):
    return {
        "guid": TASK_GUID,
        "url": "https://example.invalid/task",
        "summary": body["summary"],
        "description": body["description"],
        "due": body["due"],
        "members": body["members"],
        "tasklists": body["tasklists"],
        "reminders": body["reminders"],
    }


def test_exact_create_then_readback_and_sanitized_receipt():
    expected_body = {
        "summary": "完成一个可验收实验",
        "description": "【目的】\n验证关键假设\n\n【思考来源】\nthought-reference\n\n【交付物】\n实验记录\n\n【验收标准】\n记录结果并给出结论",
        "due": {"timestamp": "1785945600000", "is_all_day": False},
        "members": [
            {"id": "dri-user", "type": "user", "role": "assignee"},
            {"id": "reviewer-user", "type": "user", "role": "follower"},
        ],
        "tasklists": [{"tasklist_guid": TASKLIST_ID}],
        "client_token": "execution-key-stable",
        "reminders": [{"relative_fire_minute": 30}],
    }
    task = task_from_body(expected_body)
    session = Session([
        Response({"code": 0, "data": {"task": task}}, headers={"X-Request-Id": "create-request"}),
        Response({"code": 0, "data": {"task": task}}, headers={"X-Request-Id": "read-request"}),
    ])
    executor = DeepMathTasksExecutor(
        DeepMathTasksTransport("access-token", session=session),
        resource(),
        clock=lambda: datetime(2026, 8, 4, 12, tzinfo=timezone.utc),
    )
    result = executor(claim())
    assert result["status"] == "success"
    assert result["receipt"]["readback_verified"] is True
    assert result["receipt"]["member_roles"] == ["assignee", "follower"]
    assert len(session.calls) == 2
    assert session.calls[0][0] == "POST"
    assert session.calls[0][2]["json"] == expected_body
    assert session.calls[1][0] == "GET"
    assert session.calls[0][2]["params"] == {"user_id_type": "open_id"}
    assert "client_token" not in str(result["receipt"])


def test_invalid_claim_never_calls_tasks_api():
    for broken in (
        claim(tasklist_id="other"),
        claim(due={"timestamp": "1", "timezone": "UTC", "is_all_day": False}),
        claim(due={"timestamp": "1785945600001", "timezone": "Asia/Shanghai", "is_all_day": False}),
        claim(reminders=[]),
        claim(people_assignment={"status": "confirmed", "resolved_assignments": [{"directory_id": "x", "role": "Reviewer"}]}),
    ):
        session = Session([])
        result = DeepMathTasksExecutor(DeepMathTasksTransport("token", session=session), resource())(broken)
        assert result["status"] == "failed"
        assert session.calls == []


def test_explicit_create_rejection_is_failed():
    session = Session([Response({"code": 1470403, "msg": "denied"}, status=403)])
    result = DeepMathTasksExecutor(DeepMathTasksTransport("token", session=session), resource())(claim())
    assert result["status"] == "failed"
    assert result["error_code"] == "tasks_upstream_rejected"
    assert len(session.calls) == 1


def test_timeout_or_non_json_is_result_unknown_without_retry():
    for response in (requests.Timeout(), Response(json_error=True)):
        session = Session([response])
        result = DeepMathTasksExecutor(DeepMathTasksTransport("token", session=session), resource())(claim())
        assert result["status"] == "result_unknown"
        assert result["receipt"]["retry"] == "forbidden_without_reconciliation"
        assert len(session.calls) == 1


def test_post_success_readback_mismatch_is_unknown_and_not_recreated():
    expected = DeepMathTasksExecutor(DeepMathTasksTransport("token", session=Session([])), resource())
    from openclaw_app.services.deepmath_tasks_executor import canonical_task_request
    body = canonical_task_request(claim(), resource()).body()
    created = task_from_body(body)
    mismatched = {**created, "summary": "changed"}
    session = Session([
        Response({"code": 0, "data": {"task": created}}),
        Response({"code": 0, "data": {"task": mismatched}}),
    ])
    result = DeepMathTasksExecutor(DeepMathTasksTransport("token", session=session), resource())(claim())
    assert result["status"] == "result_unknown"
    assert [call[0] for call in session.calls] == ["POST", "GET"]


def test_post_success_missing_task_identity_is_result_unknown():
    session = Session([Response({"code": 0, "data": {"task": {}}})])
    result = DeepMathTasksExecutor(DeepMathTasksTransport("token", session=session), resource())(claim())
    assert result["status"] == "result_unknown"
    assert result["receipt"]["reason"] == "created task guid is required"
    assert len(session.calls) == 1


def test_same_execution_key_is_forwarded_unchanged_for_durable_claim_replay():
    from openclaw_app.services.deepmath_tasks_executor import canonical_task_request
    first = canonical_task_request(claim(), resource()).body()
    second = canonical_task_request(claim(), resource()).body()
    assert first["client_token"] == second["client_token"] == "execution-key-stable"


def test_callback_factory_maps_explicit_auth_rejection_to_failed():
    config = DeepMathApprovalCallbackConfig(
        state_path="controlled", approver_user_id="approver", authorized_actor_ids=frozenset({"approver"}),
        resource_config_path="controlled-resource", token_signing_secret="signing-secret",
    )
    item = claim().item
    executor = callback_module._tasks_executor_registry(config).resolve(item)
    assert executor is not None
    with patch.object(callback_module, "load_resource_config", return_value=resource()), \
         patch("openclaw_app.services.deepmath_runtime_config.load_deepmath_account", return_value=("app", "secret")), \
         patch.object(callback_module.DeepMathTasksTransport, "from_app_credentials", side_effect=DeepMathTasksUpstreamRejected("rejected")):
        result = executor(DeepMathExecutionClaim(item))
    assert result["status"] == "failed"
    assert result["error_code"] == "tasks_auth_rejected"


def test_transport_exposes_no_calendar_or_base_mutation_methods():
    public = {name for name in dir(DeepMathTasksTransport) if not name.startswith("_")}
    assert public == {"create", "from_app_credentials", "get"}
