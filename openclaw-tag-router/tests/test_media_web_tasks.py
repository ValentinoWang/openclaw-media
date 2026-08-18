from __future__ import annotations

import base64
import fcntl
import hashlib
import inspect
import json
import re
import time
import uuid
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import pytest

from openclaw_app.models.task import TaskResult
from openclaw_app.router.document_tools import DocumentToolsMixin
from openclaw_app.router.media_creation import MediaCreationMixin
from openclaw_app.router.media_growth import MediaGrowthMixin
from openclaw_app.router.media_review import MediaReviewMixin
from openclaw_app.services.capability_registry import CAPABILITY_REGISTRY
from openclaw_app.services.media_web_tasks import MediaWebTaskError, MediaWebTaskService
from common.model_transport_context import bind_model_transport, current_model_transport
from scripts.migrate_media_web_tasks_to_tenants import migrate


TENANT_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
TENANT_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
TENANT_C = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"


def tenant_dir(root: Path, category: str, tenant_id: str = TENANT_A) -> Path:
    return root / category / hashlib.sha256(tenant_id.encode("utf-8")).hexdigest()


class FakeApp:
    def __init__(self, result: TaskResult | None = None) -> None:
        self.calls: list[dict[str, object]] = []
        self.result = result or TaskResult(ok=True, status="completed", reply="任务完成", task_id="runtime_1")
        class FakeRouter:
            def __getattr__(self, _name):
                return lambda message: None

        self.router = FakeRouter()

    def process_capability_invocation(self, **kwargs):
        self.calls.append(kwargs)
        return self.result


def request(
    capability_id: str = "platform_hotlist",
    *,
    variant_id: str = "default",
    params: dict | None = None,
    upload_ids: list[str] | None = None,
    idempotency_key: str = "idempotency_task_0001",
    initiation: str = "manual",
    confirmation_receipt: dict | None = None,
) -> dict:
    if params is None:
        params = {"platform": "小红书", "field_1f7f0db90f93": "跑步"}
    return {
        "schemaVersion": "3",
        "capabilityId": capability_id,
        "variantId": variant_id,
        "params": params,
        "uploadIds": upload_ids or [],
        "idempotencyKey": idempotency_key,
        "catalogVersion": CAPABILITY_REGISTRY.catalog_version,
        "initiation": initiation,
        "confirmationReceipt": confirmation_receipt,
    }


def seed_confirmation_preview(
    service: MediaWebTaskService,
    *,
    capability_id: str,
    variant_id: str,
    params: dict,
    kind: str,
    receipt_fields: dict,
    status: str = "succeeded",
) -> tuple[str, dict]:
    task_id = f"mwt_{uuid.uuid4().hex}"
    receipt = {"kind": kind, "previewTaskId": task_id, **receipt_fields}
    service._write_task({
        "schema_version": "media_web_task_v3",
        "task_id": task_id,
        "tenant_id": TENANT_A,
        "invocation": {
            "capability_id": capability_id,
            "variant_id": variant_id,
            "params": params,
        },
        "status": status,
        "result": {
            "ok": status == "succeeded",
            "status": "completed" if status == "succeeded" else "needs_attention",
            "receipt": receipt,
        },
    })
    return task_id, receipt


def wait_terminal(service: MediaWebTaskService, task_id: str, tenant_id: str = TENANT_A) -> dict:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        task = service.get_task(task_id, tenant_id=tenant_id)
        if task["terminal"]:
            return task
        time.sleep(0.02)
    raise AssertionError("task did not reach terminal state")


def valid_params(capability_id: str, variant_id: str) -> dict[str, object]:
    capability = CAPABILITY_REGISTRY.get(capability_id)
    assert capability is not None
    variant = next(item for item in capability.variants if item.variant_id == variant_id)
    fields = {item.key: item for item in capability.fields}
    keys = set(variant.required_fields) | {item.key for item in capability.fields if item.required}
    keys.update(group[0] for group in variant.required_any_of)
    params: dict[str, object] = {}
    for key in keys:
        field = fields[key]
        allowed = variant.field_values.get(key) or tuple(option.value for option in field.options)
        if allowed:
            params[key] = allowed[0]
        elif field.input_type == "url":
            params[key] = "https://example.com/qa"
        elif field.value_type == "number":
            params[key] = 1
        elif field.value_type == "array":
            params[key] = ["QA"]
        else:
            params[key] = "QA"
    return params


TENANT_MODEL_CAPABILITIES = (
    "viral_deconstruction",
    "selfmedia_creation",
    "shooting_execution_plan",
    "selfmedia_creation_consultation",
    "selfmedia_data_review",
    "document_edit",
)


@pytest.mark.parametrize("capability_id", TENANT_MODEL_CAPABILITIES)
def test_tenant_model_capabilities_are_catalogued_and_can_create_tasks(
    tmp_path: Path,
    capability_id: str,
) -> None:
    service = MediaWebTaskService(FakeApp(), root=tmp_path / capability_id, start_worker=False)
    capability = CAPABILITY_REGISTRY.get(capability_id)
    assert capability is not None
    variant_id = capability.variants[0].variant_id
    params = valid_params(capability_id, variant_id)
    try:
        catalog_ids = {
            item["capabilityId"]
            for item in service.capability_catalog(is_maintainer=True)["capabilities"]
        }
        assert capability_id in catalog_ids
        task, created = service.create_task(
            request(
                capability_id,
                variant_id=variant_id,
                params=params,
                idempotency_key=f"tenant_model_capability_{capability_id}",
            ),
            tenant_id=TENANT_A,
            is_maintainer=True,
        )
        assert created is True
        assert task["capabilityId"] == capability_id
        assert task["status"] in {"queued", "awaiting_confirmation"}
    finally:
        service.close()


@pytest.mark.parametrize(
    ("owner", "method_name"),
    (
        (MediaCreationMixin, "handle_拆解"),
        (MediaCreationMixin, "handle_creation"),
        (MediaCreationMixin, "handle_shooting_execution"),
        (MediaCreationMixin, "handle_创作咨询"),
        (MediaReviewMixin, "handle_数据复盘"),
        (MediaGrowthMixin, "handle_media_growth"),
        (DocumentToolsMixin, "handle_修改"),
        (DocumentToolsMixin, "_handle_shooting_execution_backwash"),
    ),
)
def test_tenant_model_handlers_do_not_delegate_to_media_subprocess(owner: type, method_name: str) -> None:
    source = inspect.getsource(getattr(owner, method_name))
    assert "run_media_subprocess_with_watchdog" not in source


def test_media_web_execution_binds_tenant_model_transport(tmp_path: Path) -> None:
    transport = object()

    class TransportCheckingApp(FakeApp):
        def process_capability_invocation(self, **kwargs):
            assert current_model_transport() is transport
            return super().process_capability_invocation(**kwargs)

    class Gateway:
        def prepare(self) -> None:
            return None

        @contextmanager
        def bind(self, tenant_id: str, task_id: str, request_root: str):
            assert tenant_id == TENANT_A
            assert task_id.startswith("mwt_")
            assert request_root.startswith("mreq_")
            with bind_model_transport(transport):
                yield

        def task_calls(self, tenant_id: str, task_id: str) -> list[dict[str, object]]:
            return []

    app = TransportCheckingApp()
    service = MediaWebTaskService(app, root=tmp_path, tenant_model_gateway=Gateway())
    try:
        task, created = service.create_task(
            request(idempotency_key="tenant_transport_scope_0001"),
            tenant_id=TENANT_A,
        )
        terminal = wait_terminal(service, task["taskId"])
        assert created is True
        assert terminal["status"] == "succeeded"
        assert len(app.calls) == 1
    finally:
        service.close()


def test_media_web_model_call_fails_closed_without_tenant_gateway(tmp_path: Path) -> None:
    class ModelCallingApp(FakeApp):
        def process_capability_invocation(self, **kwargs):
            current_model_transport()
            raise AssertionError("unreachable shared provider path")

    service = MediaWebTaskService(ModelCallingApp(), root=tmp_path)
    try:
        task, _ = service.create_task(
            request(idempotency_key="tenant_transport_fail_closed_0001"),
            tenant_id=TENANT_A,
        )
        terminal = wait_terminal(service, task["taskId"])
        assert terminal["status"] == "failed"
        assert terminal["error"]["code"] == "task_execution_failed"
    finally:
        service.close()


def test_unknown_model_settlement_cannot_be_reported_as_success(tmp_path: Path) -> None:
    transport = object()

    class Gateway:
        def __init__(self) -> None:
            self.execution_finished = False

        def prepare(self) -> None:
            return None

        @contextmanager
        def bind(self, tenant_id: str, task_id: str, request_root: str):
            with bind_model_transport(transport):
                yield
            self.execution_finished = True

        def task_calls(self, tenant_id: str, task_id: str) -> list[dict[str, object]]:
            if not self.execution_finished:
                return []
            return [{"requestId": "mreq_unknown", "usageId": None, "status": "unknown_reconcile"}]

    service = MediaWebTaskService(FakeApp(), root=tmp_path, tenant_model_gateway=Gateway())
    try:
        task, _ = service.create_task(
            request(idempotency_key="unknown_settlement_0001"),
            tenant_id=TENANT_A,
        )
        terminal = wait_terminal(service, task["taskId"])
        assert terminal["status"] == "pending_manual"
        assert terminal["error"]["code"] == "model_settlement_unknown"
    finally:
        service.close()


def test_wrapped_model_error_still_uses_ledger_settlement_state(tmp_path: Path) -> None:
    transport = object()

    class ModelErrorApp(FakeApp):
        def process_capability_invocation(self, **kwargs):
            raise RuntimeError("wrapped downstream model failure")

    class Gateway:
        def prepare(self) -> None:
            return None

        @contextmanager
        def bind(self, tenant_id: str, task_id: str, request_root: str):
            with bind_model_transport(transport):
                yield

        def task_calls(self, tenant_id: str, task_id: str) -> list[dict[str, object]]:
            return [{"requestId": "mreq_wrapped", "usageId": None, "status": "unknown_reconcile"}]

    service = MediaWebTaskService(ModelErrorApp(), root=tmp_path, tenant_model_gateway=Gateway())
    try:
        task, _ = service.create_task(
            request(idempotency_key="wrapped_unknown_settlement_0001"),
            tenant_id=TENANT_A,
        )
        terminal = wait_terminal(service, task["taskId"])
        assert terminal["status"] == "pending_manual"
        assert terminal["error"]["code"] == "model_settlement_unknown"
    finally:
        service.close()


def test_task_executes_only_through_structured_invocation_and_is_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENCLAW_MEDIA_WEB_OPERATOR_ID", "ou_media_web_operator")
    app = FakeApp()
    service = MediaWebTaskService(app, root=tmp_path)
    try:
        payload = request()
        first, created = service.create_task(payload, tenant_id=TENANT_A)
        second, created_again = service.create_task(payload, tenant_id=TENANT_A)
        terminal = wait_terminal(service, first["taskId"])

        assert created is True
        assert created_again is False
        assert second["taskId"] == first["taskId"]
        assert terminal["status"] == "succeeded"
        assert len(app.calls) == 1
        assert app.calls[0]["capability_id"] == "platform_hotlist"
        assert app.calls[0]["variant_id"] == "default"
        assert app.calls[0]["params"] == payload["params"]
        assert app.calls[0]["source"] == "web"
        assert app.calls[0]["metadata"]["channel"] == "media_web"
        assert app.calls[0]["metadata"]["account_id"] == "media"
        assert app.calls[0]["metadata"]["bot"] == "Media bot"
        assert app.calls[0]["metadata"]["tenant_id"] == TENANT_A
        assert app.calls[0]["metadata"]["tenant_context"] == {"tenant_id": TENANT_A}
        assert app.calls[0]["metadata"]["canonical_capability_id"] == "platform_hotlist"
        assert app.calls[0]["metadata"]["operator_id"] == "ou_media_web_operator"
    finally:
        service.close()


def test_idempotency_key_is_bound_to_the_canonical_task_request(tmp_path: Path) -> None:
    service = MediaWebTaskService(FakeApp(), root=tmp_path, start_worker=False)
    try:
        first_payload = request(idempotency_key="bound_task_request_0001")
        first, created = service.create_task(first_payload, tenant_id=TENANT_A)
        replay, replay_created = service.create_task(first_payload, tenant_id=TENANT_A)
        conflicting_payload = request(
            params={"platform": "抖音", "field_1f7f0db90f93": "越野跑"},
            idempotency_key="bound_task_request_0001",
        )

        with pytest.raises(MediaWebTaskError) as raised:
            service.create_task(conflicting_payload, tenant_id=TENANT_A)

        persisted = json.loads(
            (tenant_dir(tmp_path, "tasks") / f"{first['taskId']}.json").read_text(encoding="utf-8")
        )
        assert created is True
        assert replay_created is False
        assert replay["taskId"] == first["taskId"]
        assert raised.value.code == "idempotency_conflict"
        assert re.fullmatch(r"sha256:[a-f0-9]{64}", persisted["request_fingerprint"])
    finally:
        service.close()


def test_numeric_tenant_identity_is_rejected_without_compatibility(tmp_path: Path) -> None:
    service = MediaWebTaskService(FakeApp(), root=tmp_path, start_worker=False)
    with pytest.raises(MediaWebTaskError) as raised:
        service.create_task(request(), tenant_id="101")
    assert raised.value.code == "invalid_tenant"


def test_same_confirmation_decision_replays_without_second_transition(tmp_path: Path) -> None:
    service = MediaWebTaskService(FakeApp(), root=tmp_path, start_worker=False)
    try:
        task, _ = service.create_task(
            request(
                "selfmedia_creation",
                variant_id="default",
                params=valid_params("selfmedia_creation", "default"),
                idempotency_key="confirm_replay_task_0001",
            ),
            tenant_id=TENANT_A,
        )
        first = service.confirm_task(
            task["taskId"],
            {"decision": "approve", "note": "确认执行"},
            tenant_id=TENANT_A,
        )
        replay = service.confirm_task(
            task["taskId"],
            {"decision": "approve", "note": "确认执行"},
            tenant_id=TENANT_A,
        )
        assert replay == first
    finally:
        service.close()


def test_maintainer_catalog_and_task_authorization_share_one_tenant_gate(tmp_path: Path) -> None:
    service = MediaWebTaskService(FakeApp(), root=tmp_path)
    capability_id = "document_edit"
    capability = CAPABILITY_REGISTRY.get(capability_id)
    assert capability is not None
    variant_id = capability.variants[0].variant_id
    params = valid_params(capability_id, variant_id)
    payload = request(
        capability_id,
        variant_id=variant_id,
        params=params,
        idempotency_key="idempotency_maintainer_document_edit",
    )
    try:
        public_ids = {item["capabilityId"] for item in service.capability_catalog()["capabilities"]}
        maintainer_ids = {item["capabilityId"] for item in service.capability_catalog(is_maintainer=True)["capabilities"]}
        assert capability_id not in public_ids
        assert capability_id in maintainer_ids
        assert "universal_deletion" in public_ids
        with pytest.raises(MediaWebTaskError) as denied:
            service.create_task(payload, tenant_id=TENANT_A)
        assert denied.value.code == "capability_not_found"
        task, _ = service.create_task(payload, tenant_id=TENANT_C, is_maintainer=True)
        assert task["status"] == "awaiting_confirmation"
    finally:
        service.close()


@pytest.mark.parametrize(
    "capability_id",
    [
        "activity_archive", "selfmedia_creation", "selfmedia_cognition_accumulation",
        "id_business", "viral_deconstruction", "vlog_inspiration_capture",
    ],
)
def test_persisting_media_capabilities_never_execute_before_confirmation(tmp_path: Path, capability_id: str) -> None:
    capability = CAPABILITY_REGISTRY.get(capability_id)
    assert capability is not None
    variant_id = capability.variants[0].variant_id
    params = valid_params(capability_id, variant_id)
    assert CAPABILITY_REGISTRY.validation_issues(capability_id, variant_id, params) == ()
    app = FakeApp()
    service = MediaWebTaskService(app, root=tmp_path / capability_id)
    try:
        task, _ = service.create_task(request(
            capability_id,
            variant_id=variant_id,
            params=params,
            idempotency_key=f"idempotency_confirmation_{capability_id}",
        ), tenant_id=TENANT_A)
        assert task["status"] == "awaiting_confirmation"
        time.sleep(0.05)
        assert app.calls == []
    finally:
        service.close()


@pytest.mark.parametrize("legacy_field", ["input", "command_text", "validationOnly"])
def test_legacy_request_fields_are_rejected(legacy_field: str, tmp_path: Path) -> None:
    app = FakeApp()
    service = MediaWebTaskService(app, root=tmp_path)
    try:
        payload = request(idempotency_key=f"legacy_{legacy_field}_0001")
        payload[legacy_field] = "forbidden"
        with pytest.raises(MediaWebTaskError) as raised:
            service.create_task(payload, tenant_id=TENANT_A)
        assert raised.value.code == "invalid_request"
        assert app.calls == []
    finally:
        service.close()


def test_persisted_task_contains_only_structured_invocation(tmp_path: Path) -> None:
    service = MediaWebTaskService(FakeApp(), root=tmp_path, start_worker=False)
    task, _ = service.create_task(request(), tenant_id=TENANT_A)
    persisted_text = (tenant_dir(tmp_path, "tasks") / f"{task['taskId']}.json").read_text(encoding="utf-8")
    persisted = json.loads(persisted_text)
    assert persisted["tenant_id"] == TENANT_A
    assert "principal" not in persisted
    assert set(persisted["invocation"]) == {
        "capability_id", "variant_id", "params", "upload_ids", "initiation",
        "catalog_version", "confirmation_receipt",
    }
    assert "command_text" not in persisted_text
    assert '"input"' not in persisted_text
    assert "validationOnly" not in persisted_text


def test_safe_result_does_not_expose_paths_or_raw_runtime_fields(tmp_path: Path) -> None:
    result = TaskResult(
        ok=True,
        status="completed",
        reply="产物位于 /home/ubuntu/private/result.json 和 media://creation_runs/raw",
        task_id="internal_task",
        local_path="/home/ubuntu/private/result.json",
        extra={"raw_prompt": "secret"},
    )
    service = MediaWebTaskService(FakeApp(result), root=tmp_path)
    try:
        task, _ = service.create_task(request(idempotency_key="idempotency_task_0002"), tenant_id=TENANT_A)
        projection = wait_terminal(service, task["taskId"])
        rendered = json.dumps(projection, ensure_ascii=False).lower()
        assert "/home/" not in rendered
        assert "media://" not in rendered
        assert "raw_prompt" not in rendered
        assert "internal_task" not in rendered
        assert projection["result"]["receipt"] is None
    finally:
        service.close()


def test_safe_result_removes_storage_locations_and_non_docx_feishu_links(tmp_path: Path) -> None:
    service = MediaWebTaskService(FakeApp(), root=tmp_path, start_worker=False)
    try:
        result = service._safe_result(
            TaskResult(
                ok=True,
                status="completed",
                reply=(
                    "任务已完成\n"
                    "本地归档：/srv/private/result.json\n"
                    "Obsidian：/srv/notes/private.md\n"
                    "多维表格：https://tenant.feishu.cn/base/AppSecret?table=tblSecret\n"
                    "结果可在业务页面查看"
                ),
                task_id="internal_task",
            )
        )
        assert result["reply"] == "任务已完成\n结果可在业务页面查看"
        rendered = json.dumps(result, ensure_ascii=False).lower()
        assert "/srv/" not in rendered
        assert "feishu.cn/base/" not in rendered
    finally:
        service.close()


@pytest.mark.parametrize(
    ("feishu_doc", "expected"),
    (
        (
            "https://tcnwueberajc.feishu.cn/docx/DoxcnTenantResult123",
            [{"label": "查看交付文档", "url": "https://tcnwueberajc.feishu.cn/docx/DoxcnTenantResult123"}],
        ),
        ("http://tcnwueberajc.feishu.cn/docx/DoxcnTenantResult123", []),
        ("https://attacker.example/docx/DoxcnTenantResult123", []),
        ("https://open.feishu.cn/docx/DoxcnTenantResult123", []),
        ("https://tcnwueberajc.feishu.cn/wiki/DoxcnTenantResult123", []),
        ("https://tcnwueberajc.feishu.cn/base/AppTenantSecret123?table=tblSecret", []),
        ("https://tcnwueberajc.feishu.cn/bitable/AppTenantSecret123", []),
        ("https://tcnwueberajc.feishu.cn/docx/DoxcnTenantResult123?table=tblSecret", []),
        ("https://tcnwueberajc.feishu.cn/docx/DoxcnTenantResult123#view", []),
        ("https://user:password@tcnwueberajc.feishu.cn/docx/DoxcnTenantResult123", []),
        ("https://tcnwueberajc.feishu.cn:443/docx/DoxcnTenantResult123", []),
    ),
)
def test_safe_result_only_exposes_strict_feishu_docx_links(
    tmp_path: Path,
    feishu_doc: str,
    expected: list[dict[str, str]],
) -> None:
    service = MediaWebTaskService(FakeApp(), root=tmp_path, start_worker=False)
    try:
        result = service._safe_result(
            TaskResult(
                ok=True,
                status="completed",
                reply="任务完成",
                task_id="internal_task",
                feishu_doc=feishu_doc,
            )
        )
        assert result["links"] == expected
        assert "base/" not in json.dumps(result, ensure_ascii=False).lower()
        assert "bitable/" not in json.dumps(result, ensure_ascii=False).lower()
    finally:
        service.close()


def test_safe_result_exposes_only_allowlisted_creator_candidate_receipt(tmp_path: Path) -> None:
    result = TaskResult(
        ok=True,
        status="creator_profile_candidate_ready",
        reply="run_id：20260729T130854Z\nevidence_uri：media://creator_profiles/private",
        task_id="internal_task",
        local_path="/home/ubuntu/private/result.json",
        extra={
            "creator_profile_candidate": {
                "run_id": "20260729T130854Z",
                "evidence_uri": "media://creator_profiles/private",
                "candidate_payload": {"private": "secret"},
            }
        },
    )
    service = MediaWebTaskService(FakeApp(result), root=tmp_path)
    try:
        task, _ = service.create_task(request(idempotency_key="idempotency_candidate_receipt"), tenant_id=TENANT_A)
        projection = wait_terminal(service, task["taskId"])
        receipt = projection["result"]["receipt"]
        assert receipt["kind"] == "creator_profile_candidate"
        assert receipt["previewTaskId"] == task["taskId"]
        assert receipt["runId"] == "20260729T130854Z"
        assert receipt["candidateDigest"].startswith("sha256:")
        assert receipt["expiresAt"]
        rendered = json.dumps(projection, ensure_ascii=False).lower()
        assert "media://" not in rendered
        assert "/home/" not in rendered
        assert "candidate_payload" not in rendered
        assert "secret" not in rendered
    finally:
        service.close()


def test_safe_result_exposes_track_membership_preview_receipt(tmp_path: Path) -> None:
    service = MediaWebTaskService(FakeApp(), root=tmp_path, start_worker=False)
    try:
        result = service._safe_result(
            TaskResult(
                ok=False,
                status="track_creator_membership_pending_manual",
                reply="请确认赛道关系。",
                task_id="internal_task",
            ),
            task={
                "task_id": "mwt_membership_preview_0001",
                "invocation": {
                    "capability_id": "track_creator_membership_query",
                    "variant_id": "preview",
                    "params": {
                        "action": "关系预览",
                        "id": "track_qa",
                        "profile_id": "profile_qa",
                    },
                },
            },
        )
        receipt = result["receipt"]
        assert receipt["kind"] == "track_creator_membership_preview"
        assert receipt["previewTaskId"] == "mwt_membership_preview_0001"
        assert receipt["fieldsDigest"].startswith("sha256:")
        assert receipt["expiresAt"]
    finally:
        service.close()


def test_safe_result_removes_backend_status_connectors_and_identifiers(tmp_path: Path) -> None:
    result = TaskResult(
        ok=False,
        status="pending_manual",
        reply=(
            "【热榜】\n"
            "平台：小红书｜关键词：跑步\n"
            "状态：pending_manual\n"
            "阻塞来源：brave_web_search\n"
            "原因：公开候选搜索来源限流。\n"
            "处理建议：更新登录态或提供有效 xsec_token。\n"
            "追溯ID：holder_20260730T005912_6c01671349d4"
        ),
        task_id="holder_20260730T005912_6c01671349d4",
    )
    service = MediaWebTaskService(FakeApp(result), root=tmp_path)
    try:
        task, _ = service.create_task(request(idempotency_key="idempotency_safe_public_receipt"), tenant_id=TENANT_A)
        projection = wait_terminal(service, task["taskId"])
        rendered = json.dumps(projection["result"], ensure_ascii=False).lower()
        assert projection["status"] == "pending_manual"
        assert projection["result"]["status"] == "needs_attention"
        assert "原因：公开候选搜索来源限流。" in projection["result"]["reply"]
        for token in ("pending_manual", "brave_web_search", "xsec_token", "holder_"):
            assert token not in rendered
    finally:
        service.close()


def test_upload_validates_content_deduplicates_and_becomes_consumed(tmp_path: Path) -> None:
    app = FakeApp()
    service = MediaWebTaskService(app, root=tmp_path)
    try:
        content = base64.b64encode(b"plain source evidence").decode("ascii")
        upload, created = service.create_upload(
            {"filename": "source.txt", "mimeType": "text/plain", "contentBase64": content},
            tenant_id=TENANT_A,
        )
        duplicate, created_again = service.create_upload(
            {"filename": "renamed.txt", "mimeType": "text/plain", "contentBase64": content},
            tenant_id=TENANT_A,
        )
        assert created is True
        assert created_again is False
        assert duplicate["uploadId"] == upload["uploadId"]

        task, _ = service.create_task(request(
            "source_asset_intake",
            params={"field_c675ffae69a2": "读取上传证据"},
            upload_ids=[upload["uploadId"]],
            idempotency_key="idempotency_task_0003",
        ), tenant_id=TENANT_A)
        service.confirm_task(task["taskId"], {"decision": "approve", "note": ""}, tenant_id=TENANT_A)
        wait_terminal(service, task["taskId"])
        metadata = json.loads((tenant_dir(tmp_path, "uploads") / f"{upload['uploadId']}.json").read_text(encoding="utf-8"))
        assert metadata["status"] == "consumed"
        assert metadata["tenant_id"] == TENANT_A
        assert "principal" not in metadata
        assert "storage_path" not in upload
        upload_path = str(tenant_dir(tmp_path, "uploads") / f"{upload['uploadId']}.bin")
        assert app.calls[0]["metadata"]["downloaded_paths"] == [upload_path]
        assert app.calls[0]["metadata"]["attachments"] == [
            {
                "file_name": "source.txt",
                "mime_type": "text/plain",
                "local_path": upload_path,
                "sha256": upload["sha256"],
            }
        ]
    finally:
        service.close()


def test_confirmation_reject_prevents_execution(tmp_path: Path) -> None:
    app = FakeApp()
    service = MediaWebTaskService(app, root=tmp_path)
    try:
        task, _ = service.create_task(request(
            "source_asset_intake",
            params={"field_c675ffae69a2": "保持事实，只调整标题"},
            idempotency_key="idempotency_task_0004",
        ), tenant_id=TENANT_A)
        assert task["status"] == "awaiting_confirmation"
        rejected = service.confirm_task(task["taskId"], {"decision": "reject", "note": "取消"}, tenant_id=TENANT_A)
        assert rejected["status"] == "cancelled"
        assert app.calls == []
    finally:
        service.close()


def test_deletion_preview_is_safe_and_apply_requires_confirmation(tmp_path: Path) -> None:
    class RejectingModelGateway:
        def __init__(self) -> None:
            self.prepare_calls = 0
            self.bind_calls = 0
            self.task_call_checks = 0

        def prepare(self) -> None:
            self.prepare_calls += 1
            raise AssertionError("local deletion must not prepare model credentials")

        @contextmanager
        def bind(self, tenant_id: str, task_id: str, request_root: str):
            self.bind_calls += 1
            raise AssertionError("local deletion must not bind a model transport")
            yield

        def task_calls(self, tenant_id: str, task_id: str) -> list[dict[str, object]]:
            self.task_call_checks += 1
            raise AssertionError("local deletion has no model calls to settle")

    gateway = RejectingModelGateway()
    preview_app = FakeApp(TaskResult(
        ok=True,
        status="deletion_dry_run",
        reply="删除预览：将删除 1 条素材",
        task_id="",
        extra={"deletion": [{
            "target_id": "asset_0123456789abcdef",
            "capability_id": "source_asset",
            "entities": [{"kind": "bitable_record", "target": "rec_1", "status": "planned"}],
        }]},
    ))
    refreshes: list[str] = []
    preview_service = MediaWebTaskService(
        preview_app,
        root=tmp_path / "preview",
        projection_refresher=lambda tenant_id: refreshes.append(tenant_id),
        tenant_model_gateway=gateway,
    )
    try:
        catalog = preview_service.capability_catalog()["capabilities"]
        deletion = next(item for item in catalog if item["capabilityId"] == "universal_deletion")
        assert deletion["requiresConfirmation"] is True
        preview, _ = preview_service.create_task(request(
            "universal_deletion",
            variant_id="preview",
            params={"id": "asset_0123456789abcdef"},
            idempotency_key="idempotency_delete_preview_0001",
        ), tenant_id=TENANT_A)
        assert preview["status"] == "queued"
        terminal = wait_terminal(preview_service, preview["taskId"])
        assert terminal["result"]["status"] == "completed"
        assert terminal["result"]["receipt"]["kind"] == "deletion_preview"
        preview_receipt = terminal["result"]["receipt"]
        assert len(preview_app.calls) == 1
        preview_app.result = TaskResult(ok=True, status="deletion_applied", reply="删除执行结果：已删除", task_id="")
        apply_task, _ = preview_service.create_task(request(
            "universal_deletion",
            variant_id="confirm",
            params={"id": "asset_0123456789abcdef", "action": "确认删除"},
            idempotency_key="idempotency_delete_apply_0001",
            confirmation_receipt=preview_receipt,
        ), tenant_id=TENANT_A)
        assert apply_task["status"] == "awaiting_confirmation"
        assert len(preview_app.calls) == 1
        preview_service.confirm_task(apply_task["taskId"], {"decision": "approve", "note": ""}, tenant_id=TENANT_A)
        terminal = wait_terminal(preview_service, apply_task["taskId"])
        assert terminal["status"] == "succeeded"
        assert terminal["result"]["status"] == "completed"
        assert refreshes == [TENANT_A]
        repeated, created_again = preview_service.create_task(request(
            "universal_deletion",
            variant_id="confirm",
            params={"id": "asset_0123456789abcdef", "action": "确认删除"},
            idempotency_key="idempotency_delete_apply_repeat",
            confirmation_receipt=preview_receipt,
        ), tenant_id=TENANT_A)
        assert created_again is False
        assert repeated["taskId"] == apply_task["taskId"]
        preview_service.confirm_task(apply_task["taskId"], {"decision": "approve", "note": ""}, tenant_id=TENANT_A)
        assert len(preview_app.calls) == 2
        assert gateway.prepare_calls == 0
        assert gateway.bind_calls == 0
        assert gateway.task_call_checks == 0
    finally:
        preview_service.close()


def test_deletion_preview_is_logically_idempotent_across_transport_keys(tmp_path: Path) -> None:
    service = MediaWebTaskService(FakeApp(), root=tmp_path, start_worker=False)
    try:
        first, created = service.create_task(request(
            "universal_deletion",
            variant_id="preview",
            params={"id": "asset_bbbbbbbbbbbbbbbb、asset_aaaaaaaaaaaaaaaa"},
            idempotency_key="idempotency_delete_preview_reload_1",
        ), tenant_id=TENANT_A)
        repeated, created_again = service.create_task(request(
            "universal_deletion",
            variant_id="preview",
            params={"id": "asset_aaaaaaaaaaaaaaaa,asset_bbbbbbbbbbbbbbbb"},
            idempotency_key="idempotency_delete_preview_reload_2",
        ), tenant_id=TENANT_A)
        changed, changed_created = service.create_task(request(
            "universal_deletion",
            variant_id="preview",
            params={"id": "asset_cccccccccccccccc"},
            idempotency_key="idempotency_delete_preview_reload_3",
        ), tenant_id=TENANT_A)

        assert created is True
        assert created_again is False
        assert repeated["taskId"] == first["taskId"]
        assert changed_created is True
        assert changed["taskId"] != first["taskId"]
    finally:
        service.close()


def test_task_reservation_is_idempotent_across_service_instances(tmp_path: Path) -> None:
    first_service = MediaWebTaskService(FakeApp(), root=tmp_path, start_worker=False)
    second_service = MediaWebTaskService(FakeApp(), root=tmp_path, start_worker=False)
    barrier = threading.Barrier(2)
    idempotency_key = "cross_process_reservation_0001"

    def delay_second_lookup(service: MediaWebTaskService) -> None:
        original = service._find_by_idempotency
        calls = 0

        def synchronized(tenant_id: str, key: str):
            nonlocal calls
            calls += 1
            if key == idempotency_key and calls == 2:
                try:
                    barrier.wait(timeout=0.25)
                except threading.BrokenBarrierError:
                    pass
            return original(tenant_id, key)

        service._find_by_idempotency = synchronized  # type: ignore[method-assign]

    delay_second_lookup(first_service)
    delay_second_lookup(second_service)
    payload = request(
        "universal_deletion",
        variant_id="preview",
        params={"id": "asset_0123456789abcdef"},
        idempotency_key=idempotency_key,
    )
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(
                lambda service: service.create_task(payload, tenant_id=TENANT_A),
                (first_service, second_service),
            ))
        assert sorted(created for _, created in results) == [False, True]
        assert len({task["taskId"] for task, _ in results}) == 1
        assert len(list(tenant_dir(tmp_path, "tasks").glob("*.json"))) == 1
    finally:
        first_service.close()
        second_service.close()


def test_deletion_preview_receipt_falls_back_when_internal_plan_is_absent(tmp_path: Path) -> None:
    service = MediaWebTaskService(FakeApp(), root=tmp_path, start_worker=False)
    try:
        safe = service._safe_result(
            TaskResult(ok=True, status="deletion_dry_run", reply="删除预览：将删除 1 条素材", task_id=""),
            task={
                "task_id": "mwt_preview_fallback_0001",
                "invocation": {"params": {"id": "asset_0123456789abcdef"}},
            },
        )
        assert safe["receipt"]["kind"] == "deletion_preview"
        assert safe["receipt"]["targetIds"] == ["asset_0123456789abcdef"]
        assert safe["receipt"]["entityCount"] == 0
        assert safe["reply"] == "删除影响范围已生成。"
    finally:
        service.close()


def test_deletion_preview_failure_has_complete_public_message(tmp_path: Path) -> None:
    service = MediaWebTaskService(FakeApp(), root=tmp_path, start_worker=False)
    try:
        safe = service._safe_result(
            TaskResult(
                ok=False,
                status="deletion_failed",
                reply=(
                    "删除预览：\n失败：\n"
                    "- 创作运行清理脚本：`run_internal`（Traceback internal/path.py）"
                ),
                task_id="",
            ),
            task={
                "task_id": "mwt_preview_failure_0001",
                "invocation": {
                    "capability_id": "universal_deletion",
                    "variant_id": "preview",
                    "params": {"id": "run_internal"},
                },
            },
        )

        assert safe["ok"] is False
        assert safe["status"] == "failed"
        assert safe["receipt"] is None
        assert safe["reply"] == "删除预览生成失败，本次未执行删除。请刷新后重试。"
        assert "Traceback" not in safe["reply"]
        assert "）" not in safe["reply"]
    finally:
        service.close()


def test_delete_confirm_requires_and_reserves_successful_preview(tmp_path: Path) -> None:
    service = MediaWebTaskService(FakeApp(), root=tmp_path, start_worker=False)
    try:
        with pytest.raises(MediaWebTaskError) as missing_preview:
            service.create_task(request(
                "universal_deletion",
                variant_id="confirm",
                params={"id": "asset_0123456789abcdef", "action": "确认删除"},
                idempotency_key="idempotency_delete_confirm_missing",
            ), tenant_id=TENANT_A)
        assert missing_preview.value.code == "deletion_preview_required"

        preview, _ = service.create_task(request(
            "universal_deletion",
            variant_id="preview",
            params={"id": "asset_0123456789abcdef"},
            idempotency_key="idempotency_delete_confirm_preview",
        ), tenant_id=TENANT_A)
        stored = service._load_task(preview["taskId"], tenant_id=TENANT_A)
        stored["status"] = "succeeded"
        stored["progress"] = 100
        stored["result"] = {
            "ok": True,
            "status": "completed",
            "reply": "删除影响范围已生成。",
            "links": [],
            "receipt": {
                "kind": "deletion_preview",
                "previewTaskId": preview["taskId"],
                "targetIds": ["asset_0123456789abcdef"],
                "targetCount": 1,
                "entityCount": 1,
                "planDigest": "sha256:" + "a" * 64,
                "expiresAt": "2099-01-01T00:00:00Z",
            },
        }
        service._write_task(stored)
        preview_receipt = stored["result"]["receipt"]

        confirm, created = service.create_task(request(
            "universal_deletion",
            variant_id="confirm",
            params={"id": "asset_0123456789abcdef", "action": "确认删除"},
            idempotency_key="idempotency_delete_confirm_first",
            confirmation_receipt=preview_receipt,
        ), tenant_id=TENANT_A)
        repeated, created_again = service.create_task(request(
            "universal_deletion",
            variant_id="confirm",
            params={"id": "asset_0123456789abcdef", "action": "确认删除"},
            idempotency_key="idempotency_delete_confirm_second",
            confirmation_receipt=preview_receipt,
        ), tenant_id=TENANT_A)

        assert created is True
        assert created_again is False
        assert repeated["taskId"] == confirm["taskId"]
        assert confirm["confirmationReceipt"]["previewTaskId"] == preview["taskId"]
        with pytest.raises(MediaWebTaskError) as cross_tenant:
            service.create_task(request(
                "universal_deletion",
                variant_id="confirm",
                params={"id": "asset_0123456789abcdef", "action": "确认删除"},
                idempotency_key="idempotency_delete_confirm_tenant_b",
                confirmation_receipt=preview_receipt,
            ), tenant_id=TENANT_B)
        assert cross_tenant.value.code == "deletion_preview_required"

        service.confirm_task(confirm["taskId"], {"decision": "reject", "note": "取消"}, tenant_id=TENANT_A)
        replacement, replacement_created = service.create_task(request(
            "universal_deletion",
            variant_id="preview",
            params={"id": "asset_0123456789abcdef"},
            idempotency_key="idempotency_delete_preview_after_reject",
        ), tenant_id=TENANT_A)
        assert replacement_created is True
        assert replacement["taskId"] != preview["taskId"]
    finally:
        service.close()


@pytest.mark.parametrize("capability_id,variant_id", [("track_registry_lookup", "query"), ("track_creator_membership_query", "preview")])
def test_non_mutating_variants_of_write_capabilities_do_not_require_confirmation(
    tmp_path: Path,
    capability_id: str,
    variant_id: str,
) -> None:
    params = {} if variant_id == "query" else {
        "action": "关系预览",
        "id": "track_qa",
        "id_869e433eadc3": "creator_qa",
        "field_c47b54e84e79": "候选博主",
        "field_76a17ec0d96f": 0.8,
        "field_f93c8842699c": "QA 证据",
        "field_6dfd296647d8": "media://qa/evidence",
    }
    service = MediaWebTaskService(FakeApp(), root=tmp_path / capability_id)
    try:
        task, _ = service.create_task(request(
            capability_id,
            variant_id=variant_id,
            params=params,
            idempotency_key=f"idempotency_{capability_id}_{variant_id}",
        ), tenant_id=TENANT_A)
        assert task["status"] == "queued"
        assert task["confirmation"]["state"] == "not_required"
    finally:
        service.close()


@pytest.mark.parametrize(
    "status",
    [
        "creator_profile_upserted",
        "creator_profile_confirmed_written",
        "creator_profile_batch_upserted",
        "creator_profile_batch_partial",
        "track_registry_upserted",
        "track_creator_membership_confirmed",
    ],
)
def test_successful_media_mutations_refresh_projection(tmp_path: Path, status: str) -> None:
    refreshes: list[str] = []
    service = MediaWebTaskService(
        FakeApp(TaskResult(ok=True, status=status, reply="写入完成", task_id="record_1")),
        root=tmp_path / status,
        projection_refresher=lambda tenant_id: refreshes.append(f"{tenant_id}:{status}"),
    )
    try:
        _, preview_receipt = seed_confirmation_preview(
            service,
            capability_id="creator_profile_upsert",
            variant_id="candidate",
            params={"run_id": "run_0123456789abcdef"},
            kind="creator_profile_candidate",
            receipt_fields={
                "runId": "run_0123456789abcdef",
                "candidateDigest": "sha256:" + "a" * 64,
                "expiresAt": "2099-01-01T00:00:00Z",
            },
        )
        task, _ = service.create_task(request(
            "creator_profile_upsert",
            variant_id="confirm",
            params={"run_id": "run_0123456789abcdef", "action": "确认写入"},
            idempotency_key=f"idempotency_{status}",
            confirmation_receipt=preview_receipt,
        ), tenant_id=TENANT_A)
        if task["status"] == "awaiting_confirmation":
            service.confirm_task(task["taskId"], {"decision": "approve", "note": ""}, tenant_id=TENANT_A)
        terminal = wait_terminal(service, task["taskId"])
        assert terminal["status"] == "succeeded"
        assert refreshes == [f"{TENANT_A}:{status}"]
    finally:
        service.close()


def test_source_asset_intake_completion_refreshes_projection(tmp_path: Path) -> None:
    refreshes: list[str] = []
    projected: list[tuple[str, dict, list]] = []
    artifact = {
        "artifact_id": "source_asset_1",
        "artifact_type": "SourceAsset",
        "artifact_uri": f"media://tenants/{TENANT_A}/source_assets/source_asset_1/result.json",
        "display_title": "素材已入池",
        "display_summary": "已保存来源素材",
        "urls": ["https://example.com/source"],
        "source_kind": "source_url",
        "created_at": "2026-08-08T00:00:00Z",
    }
    service = MediaWebTaskService(
        FakeApp(TaskResult(
            ok=True,
            status="media_growth_done",
            reply="素材已入池",
            task_id="source_asset_1",
            extra={"artifact": artifact},
        )),
        root=tmp_path,
        projection_refresher=refreshes.append,
        source_asset_projector=lambda tenant_id, item, uploads: projected.append(
            (tenant_id, dict(item), list(uploads))
        ),
    )
    try:
        task, _ = service.create_task(
            request(
                "source_asset_intake",
                params={"field_c675ffae69a2": "https://example.com/source"},
                idempotency_key="source_asset_projection_refresh",
            ),
            tenant_id=TENANT_A,
        )
        assert task["status"] == "awaiting_confirmation"
        service.confirm_task(task["taskId"], {"decision": "approve", "note": ""}, tenant_id=TENANT_A)
        terminal = wait_terminal(service, task["taskId"])
        assert terminal["status"] == "succeeded"
        assert terminal["result"]["status"] == "completed"
        assert refreshes == [TENANT_A]
        assert projected == [(TENANT_A, artifact, [])]
    finally:
        service.close()


def test_source_asset_projection_failure_is_repairable_needs_attention(tmp_path: Path) -> None:
    artifact = {
        "artifact_id": "source_asset_1",
        "artifact_type": "SourceAsset",
        "artifact_uri": f"media://tenants/{TENANT_A}/source_assets/source_asset_1/result.json",
        "urls": ["https://example.com/source"],
    }

    def fail_projection(_tenant_id: str, _artifact: dict, _uploads: list) -> None:
        raise RuntimeError("private database failure")

    service = MediaWebTaskService(
        FakeApp(TaskResult(
            ok=True,
            status="media_growth_done",
            reply="素材已入池",
            task_id="source_asset_1",
            extra={"artifact": artifact},
        )),
        root=tmp_path,
        source_asset_projector=fail_projection,
    )
    try:
        task, _ = service.create_task(
            request(
                "source_asset_intake",
                params={"field_c675ffae69a2": "https://example.com/source"},
                idempotency_key="source_asset_projection_failure",
            ),
            tenant_id=TENANT_A,
        )
        service.confirm_task(task["taskId"], {"decision": "approve", "note": ""}, tenant_id=TENANT_A)
        terminal = wait_terminal(service, task["taskId"])
        assert terminal["status"] == "pending_manual"
        assert terminal["result"]["status"] == "needs_attention"
        assert "private database failure" not in terminal["result"]["reply"]
    finally:
        service.close()


def test_other_media_growth_completion_does_not_refresh_projection(tmp_path: Path) -> None:
    refreshes: list[str] = []
    service = MediaWebTaskService(
        FakeApp(TaskResult(ok=True, status="media_growth_done", reply="任务完成", task_id="other_growth_1")),
        root=tmp_path,
        projection_refresher=refreshes.append,
    )
    try:
        task, _ = service.create_task(
            request("platform_hotlist", idempotency_key="other_growth_no_projection_refresh"),
            tenant_id=TENANT_A,
        )
        terminal = wait_terminal(service, task["taskId"])
        assert terminal["status"] == "succeeded"
        assert refreshes == []
    finally:
        service.close()


def test_projection_refresh_failure_keeps_public_status_contract(tmp_path: Path) -> None:
    def fail_refresh(_tenant_id: str) -> None:
        raise RuntimeError("private projection failure")

    service = MediaWebTaskService(
        FakeApp(TaskResult(ok=True, status="creator_profile_confirmed_written", reply="写入完成", task_id="record_1")),
        root=tmp_path,
        projection_refresher=fail_refresh,
    )
    try:
        _, preview_receipt = seed_confirmation_preview(
            service,
            capability_id="creator_profile_upsert",
            variant_id="candidate",
            params={"run_id": "run_0123456789abcdef"},
            kind="creator_profile_candidate",
            receipt_fields={
                "runId": "run_0123456789abcdef",
                "candidateDigest": "sha256:" + "a" * 64,
                "expiresAt": "2099-01-01T00:00:00Z",
            },
        )
        task, _ = service.create_task(request(
            "creator_profile_upsert",
            variant_id="confirm",
            params={"run_id": "run_0123456789abcdef", "action": "确认写入"},
            idempotency_key="idempotency_projection_failure",
            confirmation_receipt=preview_receipt,
        ), tenant_id=TENANT_A)
        service.confirm_task(task["taskId"], {"decision": "approve", "note": ""}, tenant_id=TENANT_A)
        terminal = wait_terminal(service, task["taskId"])
        assert terminal["status"] == "pending_manual"
        assert terminal["result"]["status"] == "needs_attention"
        rendered = json.dumps(terminal["result"], ensure_ascii=False).lower()
        assert "creator_profile_confirmed_written" not in rendered
        assert "projection_pending" not in rendered
        assert "private projection failure" not in rendered
    finally:
        service.close()


def test_candidate_only_batch_does_not_refresh_projection(tmp_path: Path) -> None:
    refreshes: list[str] = []
    service = MediaWebTaskService(
        FakeApp(TaskResult(ok=True, status="creator_profile_batch_candidates_ready", reply="候选完成", task_id="")),
        root=tmp_path,
        projection_refresher=refreshes.append,
    )
    try:
        _, preview_receipt = seed_confirmation_preview(
            service,
            capability_id="creator_profile_upsert",
            variant_id="candidate",
            params={"run_id": "run_0123456789abcdef"},
            kind="creator_profile_candidate",
            receipt_fields={
                "runId": "run_0123456789abcdef",
                "candidateDigest": "sha256:" + "a" * 64,
                "expiresAt": "2099-01-01T00:00:00Z",
            },
        )
        task, _ = service.create_task(request(
            "creator_profile_upsert",
            variant_id="confirm",
            params={"run_id": "run_0123456789abcdef", "action": "确认写入"},
            idempotency_key="idempotency_candidate_batch_no_refresh",
            confirmation_receipt=preview_receipt,
        ), tenant_id=TENANT_A)
        service.confirm_task(task["taskId"], {"decision": "approve", "note": ""}, tenant_id=TENANT_A)
        terminal = wait_terminal(service, task["taskId"])
        assert terminal["status"] == "succeeded"
        assert refreshes == []
    finally:
        service.close()


def test_restart_recovers_non_terminal_task(tmp_path: Path) -> None:
    initial = MediaWebTaskService(FakeApp(), root=tmp_path, start_worker=False)
    task, _ = initial.create_task(request(idempotency_key="idempotency_task_0005"), tenant_id=TENANT_A)
    app = FakeApp()
    recovered = MediaWebTaskService(app, root=tmp_path)
    try:
        terminal = wait_terminal(recovered, task["taskId"])
        assert terminal["status"] == "succeeded"
        assert len(app.calls) == 1
        events = recovered.get_events(task["taskId"], tenant_id=TENANT_A)
        assert any("服务恢复" in event["message"] for event in events)
    finally:
        recovered.close()


def test_restart_does_not_replay_task_after_canonical_boundary(tmp_path: Path) -> None:
    initial = MediaWebTaskService(FakeApp(), root=tmp_path, start_worker=False)
    task, _ = initial.create_task(request(idempotency_key="idempotency_task_0008"), tenant_id=TENANT_A)
    task_path = tenant_dir(tmp_path, "tasks") / f"{task['taskId']}.json"
    persisted = json.loads(task_path.read_text(encoding="utf-8"))
    persisted["status"] = "generating"
    persisted["progress"] = 40
    persisted["canonical_execution_started_at"] = "2026-07-29T00:00:00Z"
    task_path.write_text(json.dumps(persisted), encoding="utf-8")

    app = FakeApp()
    recovered = MediaWebTaskService(app, root=tmp_path)
    try:
        projection = recovered.get_task(task["taskId"], tenant_id=TENANT_A)
        assert projection["status"] == "pending_manual"
        assert projection["error"]["code"] == "recovery_requires_manual_review"
        assert app.calls == []
    finally:
        recovered.close()


def test_recovery_respects_cross_process_worker_lease(tmp_path: Path) -> None:
    initial = MediaWebTaskService(FakeApp(), root=tmp_path, start_worker=False)
    task, _ = initial.create_task(request(idempotency_key="idempotency_task_0009"), tenant_id=TENANT_A)
    lease = (tmp_path / "worker.lock").open("a+")
    fcntl.flock(lease.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    app = FakeApp()
    recovered = MediaWebTaskService(app, root=tmp_path)
    try:
        time.sleep(0.05)
        assert recovered.get_task(task["taskId"], tenant_id=TENANT_A)["status"] == "queued"
        assert app.calls == []
        fcntl.flock(lease.fileno(), fcntl.LOCK_UN)
        recovered._recover_tasks()
        assert wait_terminal(recovered, task["taskId"])["status"] == "succeeded"
        assert len(app.calls) == 1
    finally:
        lease.close()
        recovered.close()


def test_upload_quarantine_rejects_eicar_fixture(tmp_path: Path) -> None:
    service = MediaWebTaskService(FakeApp(), root=tmp_path, start_worker=False)
    eicar = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"

    upload, created = service.create_upload(
        {
            "filename": "eicar.txt",
            "mimeType": "text/plain",
            "contentBase64": base64.b64encode(eicar).decode("ascii"),
        },
        tenant_id=TENANT_A,
    )

    metadata = json.loads((tenant_dir(tmp_path, "uploads") / f"{upload['uploadId']}.json").read_text(encoding="utf-8"))
    assert created is True
    assert upload["status"] == "rejected"
    assert metadata["scan"]["code"] == "eicar_test_signature"
    assert metadata["storage_path"] == ""
    assert not (tenant_dir(tmp_path, "uploads") / f"{upload['uploadId']}.quarantine").exists()
    audit = (tmp_path / "audit" / f"{hashlib.sha256(TENANT_A.encode('utf-8')).hexdigest()}.jsonl").read_text(encoding="utf-8")
    assert '"result":"quarantined"' in audit
    assert '"result":"rejected"' in audit


def test_retention_cleanup_removes_only_task_state_events_and_upload_bytes(tmp_path: Path) -> None:
    now = datetime(2026, 7, 29, tzinfo=timezone.utc).timestamp()
    service = MediaWebTaskService(
        FakeApp(),
        root=tmp_path,
        clock=lambda: now,
        start_worker=False,
        start_cleanup_worker=False,
    )
    task, _ = service.create_task(request(idempotency_key="idempotency_task_0010"), tenant_id=TENANT_A)
    task_path = tenant_dir(tmp_path, "tasks") / f"{task['taskId']}.json"
    persisted_task = json.loads(task_path.read_text(encoding="utf-8"))
    persisted_task["status"] = "succeeded"
    persisted_task["updated_at"] = "2026-06-01T00:00:00Z"
    task_path.write_text(json.dumps(persisted_task), encoding="utf-8")
    upload, _ = service.create_upload(
        {
            "filename": "old.txt",
            "mimeType": "text/plain",
            "contentBase64": base64.b64encode(b"retention evidence").decode("ascii"),
        },
        tenant_id=TENANT_A,
    )
    upload_path = tenant_dir(tmp_path, "uploads") / f"{upload['uploadId']}.json"
    persisted_upload = json.loads(upload_path.read_text(encoding="utf-8"))
    persisted_upload["created_at"] = "2026-07-27T00:00:00Z"
    upload_path.write_text(json.dumps(persisted_upload), encoding="utf-8")

    result = service.cleanup_retention()

    assert result == {"tasks": 1, "uploads": 1}
    assert not task_path.exists()
    assert not (tenant_dir(tmp_path, "events") / f"{task['taskId']}.jsonl").exists()
    cleaned_upload = json.loads(upload_path.read_text(encoding="utf-8"))
    assert cleaned_upload["status"] == "deleted"
    assert cleaned_upload["storage_path"] == ""
    assert not (tenant_dir(tmp_path, "uploads") / f"{upload['uploadId']}.bin").exists()
    assert (tmp_path / "audit" / f"{hashlib.sha256(TENANT_A.encode('utf-8')).hexdigest()}.jsonl").exists()


def test_owner_boundary_and_invalid_tag_are_rejected(tmp_path: Path) -> None:
    service = MediaWebTaskService(FakeApp(), root=tmp_path, start_worker=False)
    task, _ = service.create_task(request(idempotency_key="idempotency_task_0006"), tenant_id=TENANT_A)
    with pytest.raises(MediaWebTaskError, match="未找到"):
        service.get_task(task["taskId"], tenant_id=TENANT_B)
    with pytest.raises(MediaWebTaskError, match="字段"):
        service.create_task(request(
            params={"platform": "小红书", "field_1f7f0db90f93": "跑步", "unknown": "不允许"},
            idempotency_key="idempotency_task_0007",
        ), tenant_id=TENANT_A)


def test_tenant_ab_all_task_methods_are_isolated_with_uniform_not_found(tmp_path: Path) -> None:
    service = MediaWebTaskService(FakeApp(), root=tmp_path, start_worker=False)
    task_a, _ = service.create_task(
        request(idempotency_key="tenant_ab_shared_idempotency"),
        tenant_id=TENANT_A,
    )
    task_b, created_b = service.create_task(
        request(idempotency_key="tenant_ab_shared_idempotency"),
        tenant_id=TENANT_B,
    )

    assert created_b is True
    assert task_a["taskId"] != task_b["taskId"]
    assert [item["taskId"] for item in service.list_tasks(tenant_id=TENANT_A)["tasks"]] == [task_a["taskId"]]
    assert [item["taskId"] for item in service.list_tasks(tenant_id=TENANT_B)["tasks"]] == [task_b["taskId"]]

    cross_tenant_calls = (
        lambda: service.get_task(task_b["taskId"], tenant_id=TENANT_A),
        lambda: service.get_events(task_b["taskId"], tenant_id=TENANT_A),
        lambda: service.cancel_task(task_b["taskId"], tenant_id=TENANT_A),
        lambda: service.confirm_task(
            task_b["taskId"],
            {"decision": "approve", "note": ""},
            tenant_id=TENANT_A,
        ),
    )
    for call in cross_tenant_calls:
        with pytest.raises(MediaWebTaskError) as denied:
            call()
        assert denied.value.code == "task_not_found"
        assert denied.value.message == "未找到该任务。"


def test_tenant_ab_upload_hash_dedup_and_references_are_isolated(tmp_path: Path) -> None:
    service = MediaWebTaskService(FakeApp(), root=tmp_path, start_worker=False)
    payload = {
        "filename": "evidence.txt",
        "mimeType": "text/plain",
        "contentBase64": base64.b64encode(b"same bytes for both tenants").decode("ascii"),
    }
    upload_a, created_a = service.create_upload(payload, tenant_id=TENANT_A)
    upload_b, created_b = service.create_upload(payload, tenant_id=TENANT_B)

    assert created_a is True
    assert created_b is True
    assert upload_a["uploadId"] != upload_b["uploadId"]
    with pytest.raises(MediaWebTaskError) as denied:
        service.create_task(
            request(
                "source_asset_intake",
                params={"field_c675ffae69a2": "读取上传证据"},
                upload_ids=[upload_b["uploadId"]],
                idempotency_key="tenant_a_references_tenant_b_upload",
            ),
            tenant_id=TENANT_A,
        )
    assert denied.value.code == "upload_not_found"
    assert denied.value.message == "未找到该上传文件。"


@pytest.mark.parametrize(
    "reserved_key",
    [
        "tenant",
        "tenant_id",
        "tenantId",
        "principal",
        "owner_id",
        "api_key",
        "apiKey",
        "secret_ref",
        "access_token",
        "refresh_token",
        "Authorization",
    ],
)
def test_client_tenant_fields_are_rejected_at_every_write_boundary(tmp_path: Path, reserved_key: str) -> None:
    service = MediaWebTaskService(FakeApp(), root=tmp_path, start_worker=False)
    task_payload = request(idempotency_key=f"spoof_task_{reserved_key}")
    task_payload[reserved_key] = TENANT_B
    with pytest.raises(MediaWebTaskError) as task_denied:
        service.create_task(task_payload, tenant_id=TENANT_A)
    assert task_denied.value.code == "invalid_request"

    nested_payload = request(idempotency_key=f"spoof_nested_{reserved_key}")
    nested_payload["params"] = {
        "platform": "小红书",
        "field_1f7f0db90f93": "跑步",
        "nested": {reserved_key: TENANT_B},
    }
    with pytest.raises(MediaWebTaskError) as nested_denied:
        service.create_task(nested_payload, tenant_id=TENANT_A)
    assert nested_denied.value.code == "invalid_request"

    upload_payload = {
        "filename": "evidence.txt",
        "mimeType": "text/plain",
        "contentBase64": base64.b64encode(b"tenant spoof").decode("ascii"),
        reserved_key: TENANT_B,
    }
    with pytest.raises(MediaWebTaskError) as upload_denied:
        service.create_upload(upload_payload, tenant_id=TENANT_A)
    assert upload_denied.value.code == "invalid_request"

    confirmation_task, _ = service.create_task(
        request(
            "source_asset_intake",
            params={"field_c675ffae69a2": "读取上传证据"},
            idempotency_key=f"spoof_confirm_{reserved_key}",
        ),
        tenant_id=TENANT_A,
    )
    with pytest.raises(MediaWebTaskError) as confirmation_denied:
        service.confirm_task(
            confirmation_task["taskId"],
            {"decision": "approve", "note": "", reserved_key: TENANT_B},
            tenant_id=TENANT_A,
        )
    assert confirmation_denied.value.code == "invalid_request"


def test_event_and_audit_records_persist_canonical_tenant_owner(tmp_path: Path) -> None:
    service = MediaWebTaskService(FakeApp(), root=tmp_path, start_worker=False)
    task, _ = service.create_task(request(idempotency_key="tenant_owner_persistence"), tenant_id=TENANT_A)
    events = service.get_events(task["taskId"], tenant_id=TENANT_A)
    assert events
    assert {event["tenant_id"] for event in events} == {TENANT_A}

    audit_path = tmp_path / "audit" / f"{hashlib.sha256(TENANT_A.encode('utf-8')).hexdigest()}.jsonl"
    audit_entries = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]
    assert audit_entries
    assert {entry["tenant_id"] for entry in audit_entries} == {TENANT_A}
    assert all("actor" not in entry and "principal" not in entry for entry in audit_entries)


def test_one_time_migration_moves_proven_owner_and_archives_unknown_owner(tmp_path: Path) -> None:
    tasks = tmp_path / "tasks"
    events = tmp_path / "events"
    uploads = tmp_path / "uploads"
    for directory in (tasks, events, uploads):
        directory.mkdir()
    task_id = "mwt_0123456789abcdef"
    upload_id = "mwu_0123456789abcdef"
    (tasks / f"{task_id}.json").write_text(
        json.dumps(
            {
                "schema_version": "media_web_task_v3",
                "task_id": task_id,
                "principal": "legacy-a",
                "idempotency_key": "legacy_task_0001",
                "invocation": {
                    "capability_id": "platform_hotlist",
                    "variant_id": "default",
                    "params": {"platform": "抖音", "field_1f7f0db90f93": "跑步"},
                    "upload_ids": [],
                    "initiation": "direct",
                    "catalog_version": CAPABILITY_REGISTRY.catalog_version,
                },
            }
        ),
        encoding="utf-8",
    )
    (events / f"{task_id}.jsonl").write_text(
        json.dumps({"eventId": 1, "taskId": task_id}) + "\n",
        encoding="utf-8",
    )
    upload_binary = uploads / f"{upload_id}.bin"
    upload_binary.write_bytes(b"legacy upload")
    (uploads / f"{upload_id}.json").write_text(
        json.dumps(
            {
                "schema_version": "media_web_task_v3",
                "upload_id": upload_id,
                "principal": "legacy-a",
                "storage_path": str(upload_binary),
            }
        ),
        encoding="utf-8",
    )
    orphan_id = "mwt_fedcba9876543210"
    (tasks / f"{orphan_id}.json").write_text(
        json.dumps({"schema_version": "media_web_task_v3", "task_id": orphan_id, "principal": "unknown"}),
        encoding="utf-8",
    )
    (tmp_path / "audit.jsonl").write_text(
        json.dumps({"actor": "legacy-a", "action": "task.create"}) + "\n",
        encoding="utf-8",
    )

    counts = migrate(tmp_path, {"legacy-a": TENANT_A})

    assert counts == {"tasks": 1, "uploads": 1, "audit": 1, "orphaned": 1}
    migrated_task = json.loads((tenant_dir(tmp_path, "tasks") / f"{task_id}.json").read_text(encoding="utf-8"))
    assert migrated_task["tenant_id"] == TENANT_A
    assert "principal" not in migrated_task
    migrated_events = (tenant_dir(tmp_path, "events") / f"{task_id}.jsonl").read_text(encoding="utf-8")
    assert json.loads(migrated_events)["tenant_id"] == TENANT_A
    migrated_upload = json.loads((tenant_dir(tmp_path, "uploads") / f"{upload_id}.json").read_text(encoding="utf-8"))
    assert migrated_upload["tenant_id"] == TENANT_A
    assert migrated_upload["storage_path"] == str(tenant_dir(tmp_path, "uploads") / f"{upload_id}.bin")
    assert not (tasks / f"{task_id}.json").exists()
    assert (tmp_path / "migration_archive" / "orphaned" / "tasks" / f"{orphan_id}.json").exists()


def test_confirmation_receipt_binds_exact_preview_not_latest_or_equivalent_task(tmp_path: Path) -> None:
    service = MediaWebTaskService(FakeApp(), root=tmp_path, start_worker=False)
    params = {"id": "asset_0123456789abcdef", "action": "确认删除"}

    def preview(digest: str, expires_at: str = "2099-01-01T00:00:00Z") -> tuple[str, dict]:
        return seed_confirmation_preview(
            service,
            capability_id="universal_deletion",
            variant_id="preview",
            params={"id": "asset_0123456789abcdef"},
            kind="deletion_preview",
            receipt_fields={
                "targetIds": ["asset_0123456789abcdef"],
                "targetCount": 1,
                "entityCount": 1,
                "planDigest": digest,
                "expiresAt": expires_at,
            },
        )

    try:
        first_id, receipt = preview("sha256:" + "a" * 64)
        second_id, _ = preview("sha256:" + "b" * 64)
        created, is_new = service.create_task(
            request("universal_deletion", variant_id="confirm", params=params, idempotency_key="receipt_confirm_first_0001", confirmation_receipt=receipt),
            tenant_id=TENANT_A,
        )
        repeated, repeated_new = service.create_task(
            request("universal_deletion", variant_id="confirm", params=params, idempotency_key="receipt_confirm_second_0001", confirmation_receipt=receipt),
            tenant_id=TENANT_A,
        )
        assert is_new is True and repeated_new is False
        assert repeated["taskId"] == created["taskId"]
        assert created["confirmationReceipt"] == receipt
        assert created["confirmationReceipt"]["previewTaskId"] == first_id
        assert created["confirmationReceipt"]["previewTaskId"] != second_id

        for invalid_receipt in (
            {**receipt, "previewTaskId": "mwt_not_a_real_preview_0001"},
            {**receipt, "planDigest": "sha256:" + "c" * 64},
        ):
            with pytest.raises(MediaWebTaskError) as rejected:
                service.create_task(
                    request("universal_deletion", variant_id="confirm", params=params, idempotency_key=f"receipt_invalid_{uuid.uuid4().hex}", confirmation_receipt=invalid_receipt),
                    tenant_id=TENANT_A,
                )
            assert rejected.value.code == "deletion_preview_required"

        _, expired = preview("sha256:" + "d" * 64, "1970-01-01T00:00:00Z")
        with pytest.raises(MediaWebTaskError) as expired_error:
            service.create_task(request(
                "universal_deletion",
                variant_id="confirm",
                params=params,
                idempotency_key="receipt_expired_0001",
                confirmation_receipt=expired,
            ), tenant_id=TENANT_A)
        assert expired_error.value.code == "deletion_preview_required"
    finally:
        service.close()


def test_expired_deletion_confirmation_can_be_rejected_but_not_approved(tmp_path: Path) -> None:
    now = [1_000.0]

    def create_confirmation(root: Path, suffix: str) -> tuple[MediaWebTaskService, dict]:
        service = MediaWebTaskService(
            FakeApp(),
            root=root,
            clock=lambda: now[0],
            start_worker=False,
        )
        _, receipt = seed_confirmation_preview(
            service,
            capability_id="universal_deletion",
            variant_id="preview",
            params={"id": "asset_0123456789abcdef"},
            kind="deletion_preview",
            receipt_fields={
                "targetIds": ["asset_0123456789abcdef"],
                "targetCount": 1,
                "entityCount": 1,
                "planDigest": "sha256:" + suffix * 64,
                "expiresAt": datetime.fromtimestamp(1_100, timezone.utc).isoformat(),
            },
        )
        confirmation, _ = service.create_task(
            request(
                "universal_deletion",
                variant_id="confirm",
                params={"id": "asset_0123456789abcdef", "action": "确认删除"},
                idempotency_key=f"expired_confirmation_{suffix}",
                confirmation_receipt=receipt,
            ),
            tenant_id=TENANT_A,
        )
        return service, confirmation

    rejecting_service, reject_task = create_confirmation(tmp_path / "reject", "a")
    approving_service, approve_task = create_confirmation(tmp_path / "approve", "b")
    now[0] = 1_200.0
    try:
        rejected = rejecting_service.confirm_task(
            reject_task["taskId"],
            {"decision": "reject", "note": ""},
            tenant_id=TENANT_A,
        )
        assert rejected["status"] == "cancelled"
        assert rejected["confirmation"]["state"] == "rejected"

        with pytest.raises(MediaWebTaskError) as expired:
            approving_service.confirm_task(
                approve_task["taskId"],
                {"decision": "approve", "note": ""},
                tenant_id=TENANT_A,
            )
        assert expired.value.code == "deletion_preview_required"
        unchanged = approving_service.get_task(approve_task["taskId"], tenant_id=TENANT_A)
        assert unchanged["status"] == "awaiting_confirmation"
        assert unchanged["confirmation"]["state"] == "required"
    finally:
        rejecting_service.close()
        approving_service.close()


def test_creator_confirmation_receipt_binds_exact_candidate_and_replays(tmp_path: Path) -> None:
    service = MediaWebTaskService(FakeApp(), root=tmp_path, start_worker=False)
    confirm_params = {"run_id": "run_0123456789abcdef", "action": "确认写入"}
    try:
        with pytest.raises(MediaWebTaskError) as missing_receipt:
            service.create_task(request(
                "creator_profile_upsert",
                variant_id="confirm",
                params=confirm_params,
                idempotency_key="creator_receipt_missing_0001",
            ), tenant_id=TENANT_A)
        assert missing_receipt.value.code == "creator_profile_candidate_required"

        first_id, receipt = seed_confirmation_preview(
            service,
            capability_id="creator_profile_upsert",
            variant_id="candidate",
            params={"run_id": confirm_params["run_id"]},
            kind="creator_profile_candidate",
            receipt_fields={
                "runId": confirm_params["run_id"],
                "candidateDigest": "sha256:" + "a" * 64,
                "expiresAt": "2099-01-01T00:00:00Z",
            },
        )
        second_id, _ = seed_confirmation_preview(
            service,
            capability_id="creator_profile_upsert",
            variant_id="candidate",
            params={"run_id": confirm_params["run_id"]},
            kind="creator_profile_candidate",
            receipt_fields={
                "runId": confirm_params["run_id"],
                "candidateDigest": "sha256:" + "b" * 64,
                "expiresAt": "2099-01-01T00:00:00Z",
            },
        )
        created, is_new = service.create_task(request(
            "creator_profile_upsert",
            variant_id="confirm",
            params=confirm_params,
            idempotency_key="creator_receipt_confirm_first_0001",
            confirmation_receipt=receipt,
        ), tenant_id=TENANT_A)
        repeated, repeated_new = service.create_task(request(
            "creator_profile_upsert",
            variant_id="confirm",
            params=confirm_params,
            idempotency_key="creator_receipt_confirm_second_0001",
            confirmation_receipt=receipt,
        ), tenant_id=TENANT_A)
        assert is_new is True and repeated_new is False
        assert repeated["taskId"] == created["taskId"]
        assert created["confirmationReceipt"]["previewTaskId"] == first_id
        assert created["confirmationReceipt"]["previewTaskId"] != second_id

        for invalid_receipt in (
            {**receipt, "previewTaskId": "mwt_not_a_real_candidate_0001"},
            {**receipt, "candidateDigest": "sha256:" + "c" * 64},
        ):
            with pytest.raises(MediaWebTaskError) as rejected:
                service.create_task(request(
                    "creator_profile_upsert",
                    variant_id="confirm",
                    params=confirm_params,
                    idempotency_key=f"creator_receipt_invalid_{uuid.uuid4().hex}",
                    confirmation_receipt=invalid_receipt,
                ), tenant_id=TENANT_A)
            assert rejected.value.code == "creator_profile_candidate_required"

        _, expired = seed_confirmation_preview(
            service,
            capability_id="creator_profile_upsert",
            variant_id="candidate",
            params={"run_id": confirm_params["run_id"]},
            kind="creator_profile_candidate",
            receipt_fields={
                "runId": confirm_params["run_id"],
                "candidateDigest": "sha256:" + "d" * 64,
                "expiresAt": "1970-01-01T00:00:00Z",
            },
        )
        with pytest.raises(MediaWebTaskError) as expired_error:
            service.create_task(request(
                "creator_profile_upsert",
                variant_id="confirm",
                params=confirm_params,
                idempotency_key="creator_receipt_expired_0001",
                confirmation_receipt=expired,
            ), tenant_id=TENANT_A)
        assert expired_error.value.code == "creator_profile_candidate_required"
    finally:
        service.close()


def test_track_confirmation_receipt_binds_exact_preview_and_fields(tmp_path: Path) -> None:
    service = MediaWebTaskService(FakeApp(), root=tmp_path, start_worker=False)
    confirm_params = {
        "action": "关系确认",
        "id": "track_qa",
        "id_869e433eadc3": "creator_qa",
        "field_c47b54e84e79": "候选博主",
        "field_76a17ec0d96f": 0.8,
        "field_f93c8842699c": "QA 证据 A",
        "field_6dfd296647d8": "media://qa/evidence",
        "confirmation": "是",
    }
    preview_params = {**confirm_params, "action": "关系预览"}
    try:
        with pytest.raises(MediaWebTaskError) as missing_receipt:
            service.create_task(request(
                "track_creator_membership_query",
                variant_id="confirm",
                params=confirm_params,
                idempotency_key="track_receipt_missing_0001",
            ), tenant_id=TENANT_A)
        assert missing_receipt.value.code == "track_creator_membership_preview_required"

        first_digest = service._confirmation_fields_digest(preview_params)
        first_id, receipt = seed_confirmation_preview(
            service,
            capability_id="track_creator_membership_query",
            variant_id="preview",
            params=preview_params,
            kind="track_creator_membership_preview",
            receipt_fields={
                "fieldsDigest": first_digest,
                "expiresAt": "2099-01-01T00:00:00Z",
            },
            status="pending_manual",
        )
        updated_params = {**preview_params, "field_f93c8842699c": "QA 证据 B"}
        second_id, _ = seed_confirmation_preview(
            service,
            capability_id="track_creator_membership_query",
            variant_id="preview",
            params=updated_params,
            kind="track_creator_membership_preview",
            receipt_fields={
                "fieldsDigest": service._confirmation_fields_digest(updated_params),
                "expiresAt": "2099-01-01T00:00:00Z",
            },
            status="pending_manual",
        )
        created, is_new = service.create_task(request(
            "track_creator_membership_query",
            variant_id="confirm",
            params=confirm_params,
            idempotency_key="track_receipt_confirm_first_0001",
            confirmation_receipt=receipt,
        ), tenant_id=TENANT_A)
        repeated, repeated_new = service.create_task(request(
            "track_creator_membership_query",
            variant_id="confirm",
            params=confirm_params,
            idempotency_key="track_receipt_confirm_second_0001",
            confirmation_receipt=receipt,
        ), tenant_id=TENANT_A)
        assert is_new is True and repeated_new is False
        assert repeated["taskId"] == created["taskId"]
        assert created["confirmationReceipt"]["previewTaskId"] == first_id
        assert created["confirmationReceipt"]["previewTaskId"] != second_id

        for invalid_receipt in (
            {**receipt, "previewTaskId": "mwt_not_a_real_membership_0001"},
            {**receipt, "fieldsDigest": "sha256:" + "c" * 64},
        ):
            with pytest.raises(MediaWebTaskError) as rejected:
                service.create_task(request(
                    "track_creator_membership_query",
                    variant_id="confirm",
                    params=confirm_params,
                    idempotency_key=f"track_receipt_invalid_{uuid.uuid4().hex}",
                    confirmation_receipt=invalid_receipt,
                ), tenant_id=TENANT_A)
            assert rejected.value.code == "track_creator_membership_preview_required"

        changed_confirm = {**confirm_params, "field_f93c8842699c": "QA 证据 B"}
        with pytest.raises(MediaWebTaskError) as changed_error:
            service.create_task(request(
                "track_creator_membership_query",
                variant_id="confirm",
                params=changed_confirm,
                idempotency_key="track_receipt_changed_fields_0001",
                confirmation_receipt=receipt,
            ), tenant_id=TENANT_A)
        assert changed_error.value.code == "track_creator_membership_preview_required"

        _, expired = seed_confirmation_preview(
            service,
            capability_id="track_creator_membership_query",
            variant_id="preview",
            params=preview_params,
            kind="track_creator_membership_preview",
            receipt_fields={
                "fieldsDigest": first_digest,
                "expiresAt": "1970-01-01T00:00:00Z",
            },
            status="pending_manual",
        )
        with pytest.raises(MediaWebTaskError) as expired_error:
            service.create_task(request(
                "track_creator_membership_query",
                variant_id="confirm",
                params=confirm_params,
                idempotency_key="track_receipt_expired_0001",
                confirmation_receipt=expired,
            ), tenant_id=TENANT_A)
        assert expired_error.value.code == "track_creator_membership_preview_required"
    finally:
        service.close()
