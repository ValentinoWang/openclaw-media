from __future__ import annotations

import http.client
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from openclaw_app.adapters.http_api import make_server
from openclaw_app.router.content_os_bridge import ContentOSBridgeMixin
from openclaw_app.router.content_os_project_lifecycle import CONTENT_OS_SPEC_VERSION
from openclaw_app.router.content_os_queue import create_ready_task
from openclaw_app.services.cloud_media_task_receiver import (
    CloudMediaTaskReceiver,
    CloudMediaTaskReceiverError,
)
from openclaw_app.services.device_job_service import DeviceJobService
from openclaw_app.services.device_job_store import DeviceJobStore


TENANT_A = "11111111-1111-4111-8111-111111111111"
TENANT_B = "22222222-2222-4222-8222-222222222222"


class ContentOSRouter(ContentOSBridgeMixin):
    def __init__(self, vault_root: Path) -> None:
        self._vault_root = vault_root

    def _content_os_vault_root(self) -> Path:
        return self._vault_root


class TimeoutContentOSRouter:
    def __init__(self, vault_root: Path) -> None:
        self._vault_root = vault_root

    def _content_os_vault_root(self) -> Path:
        return self._vault_root

    def _accept_content_os_mac_result(self, *_args, **_kwargs):
        raise TimeoutError("simulated cloud timeout")


class CloudMediaTaskReceiverTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.vault_root = Path(self.temporary.name) / "vault"
        self.project_id = "20260829_cloud_receiver"
        self._write_project_overview()
        self.store = DeviceJobStore(
            Path(self.temporary.name) / "device-jobs.sqlite3",
            credential_secret=b"cloud-receiver-test-secret-must-be-at-least-32-bytes",
        )
        self.device_jobs = DeviceJobService(self.store)
        self.router = ContentOSRouter(self.vault_root)
        self.receiver = CloudMediaTaskReceiver(self.device_jobs, self.router)
        _, self.credential_a = self._pair(TENANT_A, "pair-a")
        _, self.credential_b = self._pair(TENANT_B, "pair-b")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _write_project_overview(self) -> None:
        project_dir = self.vault_root / "08_内容项目" / self.project_id
        project_dir.mkdir(parents=True)
        (project_dir / "00_项目总览.md").write_text(
            "---\n"
            f"spec_version: {CONTENT_OS_SPEC_VERSION}\n"
            "doc_type: project_overview\n"
            f"project_id: {self.project_id}\n"
            "idea_id: idea_20260829_cloud_receiver\n"
            "status: captured\n"
            "project_revision: 1\n"
            "editor_backend: handoff_pack\n"
            "---\n\n# 云桥接收测试\n",
            encoding="utf-8",
        )

    def _pair(self, tenant_id: str, key: str) -> tuple[dict[str, object], str]:
        pair_code = self.device_jobs.create_pair_code(
            tenant_id,
            device_label="Cloud receiver test Mac",
            expires_in_seconds=300,
            idempotency_key=key,
        )
        return self.device_jobs.pair_device(
            pair_code=pair_code["pair_code"],
            device_label="Cloud receiver test Mac",
            device_platform="macos",
            client_version="1.0.0",
            idempotency_key=f"{key}-device",
        )

    def _task(self, *, task_type: str = "local_material_match", change_request_id: str = "", confirmed: bool = False):
        return create_ready_task(
            self.vault_root,
            self.project_id,
            task_type=task_type,
            project_revision=1,
            change_request_id=change_request_id,
            editor_backend="handoff_pack",
            human_confirmed_impact=confirmed,
            inputs={"change_summary": {"requested_change": "补充镜头节奏"}},
            expected_outputs=["08_内容项目/20260829_cloud_receiver/05_storyboard.md"],
            allowed_actions=["apply_confirmed_revision"],
            notes=["人工确认后可重试"],
            tenant_id=TENANT_A,
            now=datetime(2026, 8, 29, tzinfo=timezone.utc),
        )

    @staticmethod
    def _result(task, *, status: str = "done", tenant_id: str = TENANT_A) -> dict[str, object]:
        payload: dict[str, object] = {
            "spec_version": "content_os_v0.2",
            "doc_type": "mac_result",
            "task_id": task.task_id,
            "task_type": task.task_type,
            "completed_by": "mac_openclaw",
            "status": status,
            "project_id": task.project_id,
            "project_revision": task.project_revision,
            "change_request_id": task.change_request_id,
            "editor_backend": task.editor_backend,
            "tenant_id": tenant_id,
            "outputs": {"storyboard": "08_内容项目/20260829_cloud_receiver/05_storyboard.md"},
            "validation": {"storyboard_nonempty": True},
        }
        if status == "blocked":
            payload["blocked_reason"] = "execution_timeout"
            payload["blocked_detail"] = "本地执行超过租约时间"
        return payload

    def test_receive_readback_duplicate_contract_and_cross_tenant_fail_closed(self) -> None:
        task = self._task()
        result = self._result(task)

        with self.assertRaises(CloudMediaTaskReceiverError) as wrong_tenant:
            self.receiver.receive(credential=self.credential_b, result=result)
        self.assertEqual(wrong_tenant.exception.code, "content_os_result_rejected")

        with self.assertRaises(CloudMediaTaskReceiverError) as invalid_contract:
            self.receiver.receive(credential=self.credential_a, result={**result, "doc_type": "mac_task"})
        self.assertEqual(invalid_contract.exception.code, "invalid_content_os_result")

        accepted = self.receiver.receive(credential=self.credential_a, result=result, idempotency_key="receipt-a")
        self.assertFalse(accepted["replayed"])
        self.assertEqual(accepted["task"]["task_id"], task.task_id)
        self.assertEqual(accepted["task"]["project_revision"], 1)
        self.assertEqual(accepted["result"]["evidence"]["outputs"], result["outputs"])
        self.assertTrue(accepted["accepted"]["result_ref"].startswith("98_Agent任务队列/02_mac_to_cloud_results/"))

        duplicate = self.receiver.receive(credential=self.credential_a, result=result, idempotency_key="receipt-b")
        self.assertTrue(duplicate["replayed"])
        self.assertEqual(duplicate["accepted"], accepted["accepted"])

        readback = self.receiver.readback(credential=self.credential_a, task_id=task.task_id)
        self.assertTrue(readback["replayed"])
        self.assertEqual(readback["result"], accepted["result"])

        with self.assertRaises(CloudMediaTaskReceiverError) as replay_other_tenant:
            self.receiver.readback(credential=self.credential_b, task_id=task.task_id)
        self.assertEqual(replay_other_tenant.exception.code, "not_found")

        with self.assertRaises(CloudMediaTaskReceiverError) as changed_duplicate:
            self.receiver.receive(
                credential=self.credential_a,
                result={**result, "outputs": {"storyboard": "different.md"}},
                idempotency_key="receipt-c",
            )
        self.assertEqual(changed_duplicate.exception.code, "idempotency_conflict")

    def test_blocked_change_creates_one_retriable_task(self) -> None:
        task = self._task(
            task_type="revise_local_edit_artifacts",
            change_request_id="change_20260829_001",
            confirmed=True,
        )
        blocked = self.receiver.receive(
            credential=self.credential_a,
            result=self._result(task, status="blocked"),
            idempotency_key="blocked-receipt",
        )
        self.assertTrue(blocked["retry"]["available"])

        retry = self.receiver.retry_blocked_change(
            credential=self.credential_a,
            task_id=task.task_id,
            idempotency_key="retry-a",
            reason="timeout",
        )
        self.assertFalse(retry["replayed"])
        self.assertEqual(retry["source_task_id"], task.task_id)
        self.assertEqual(retry["task"]["state"], "ready")
        self.assertEqual(retry["task"]["change_request_id"], "change_20260829_001")

        duplicate = self.receiver.retry_blocked_change(
            credential=self.credential_a,
            task_id=task.task_id,
            idempotency_key="retry-b",
            reason="timeout",
        )
        self.assertTrue(duplicate["replayed"])
        self.assertEqual(duplicate["task"]["task_id"], retry["task"]["task_id"])

    def test_http_readback_missing_capability_and_timeout_do_not_report_success(self) -> None:
        task = self._task()
        result = self._result(task)
        server = make_server("127.0.0.1", 0, SimpleNamespace(router=self.router), device_job_service=self.device_jobs)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            status, body = self._request(server, "POST", "/internal/content-os/mac-result", result, self.credential_a)
            self.assertEqual(status, 200, body)
            self.assertEqual(body, {"ok": True, "status": "content_os_mac_result_accepted", "task_id": task.task_id})
            status, body = self._request(server, "GET", f"/internal/content-os/mac-result/{task.task_id}", credential=self.credential_a)
            self.assertEqual(status, 200, body)
            self.assertEqual(body["receipt"]["task"]["project_id"], self.project_id)

            retry_source = self._task(
                task_type="revise_local_edit_artifacts",
                change_request_id="change_20260829_http_retry",
                confirmed=True,
            )
            status, body = self._request(
                server,
                "POST",
                "/internal/content-os/mac-result",
                self._result(retry_source, status="blocked"),
                self.credential_a,
            )
            self.assertEqual(status, 200, body)
            retry_path = f"/internal/content-os/mac-result/{retry_source.task_id}/retry"
            status, body = self._request(
                server,
                "POST",
                retry_path,
                {"reason": "timeout"},
                self.credential_a,
                headers={"Idempotency-Key": "http-retry-a"},
            )
            self.assertEqual(status, 201, body)
            self.assertFalse(body["receipt"]["replayed"])
            retry_task_id = body["receipt"]["task"]["task_id"]
            status, duplicate_retry = self._request(
                server,
                "POST",
                retry_path,
                {"reason": "timeout"},
                self.credential_a,
                headers={"Idempotency-Key": "http-retry-b"},
            )
            self.assertEqual(status, 201, duplicate_retry)
            self.assertTrue(duplicate_retry["receipt"]["replayed"])
            self.assertEqual(duplicate_retry["receipt"]["task"]["task_id"], retry_task_id)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

        missing = make_server("127.0.0.1", 0, None, device_job_service=self.device_jobs)
        missing_thread = threading.Thread(target=missing.serve_forever, daemon=True)
        missing_thread.start()
        try:
            status, body = self._request(missing, "GET", f"/internal/content-os/mac-result/{task.task_id}", credential=self.credential_a)
            self.assertEqual(status, 503, body)
            self.assertEqual(body["error"]["code"], "content_os_unavailable")
        finally:
            missing.shutdown()
            missing.server_close()
            missing_thread.join(timeout=3)

        timeout = make_server(
            "127.0.0.1",
            0,
            SimpleNamespace(router=TimeoutContentOSRouter(self.vault_root)),
            device_job_service=self.device_jobs,
        )
        timeout_thread = threading.Thread(target=timeout.serve_forever, daemon=True)
        timeout_thread.start()
        try:
            timeout_result = {**result, "task_id": "task_20260829_999"}
            status, body = self._request(timeout, "POST", "/internal/content-os/mac-result", timeout_result, self.credential_a)
            self.assertEqual(status, 504, body)
            self.assertEqual(body["error"]["code"], "cloud_receiver_timeout")
            self.assertFalse(body["ok"])
        finally:
            timeout.shutdown()
            timeout.server_close()
            timeout_thread.join(timeout=3)

    def test_repository_frozen_contract_is_loadable_without_deployment_overrides(self) -> None:
        environment = dict(os.environ)
        environment.pop("OPENCLAW_MEDIA_FROZEN_CONTRACT", None)
        environment.pop("OPENCLAW_MEDIA_GENERATED_CONTRACT", None)
        environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
        output = subprocess.check_output(
            [
                sys.executable,
                "-c",
                "from openclaw_app.services.media_device_job_contract import FROZEN_CONTRACT; print(FROZEN_CONTRACT)",
            ],
            cwd=Path(__file__).resolve().parents[1],
            env=environment,
            text=True,
        ).strip()
        self.assertTrue(output.endswith("docs/ai-harness/openclaw-media-product-contract.json"), output)

    @staticmethod
    def _request(
        server,
        method: str,
        path: str,
        payload: dict[str, object] | None = None,
        credential: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, object]]:
        connection = http.client.HTTPConnection(*server.server_address, timeout=3)
        request_headers: dict[str, str] = dict(headers or {})
        body = None
        if credential is not None:
            request_headers["Authorization"] = f"Bearer {credential}"
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            request_headers["Content-Type"] = "application/json"
        connection.request(method, path, body=body, headers=request_headers)
        response = connection.getresponse()
        result = json.loads(response.read() or b"{}")
        connection.close()
        return response.status, result


if __name__ == "__main__":
    unittest.main()
