from __future__ import annotations

import http.client
import hashlib
import inspect
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

from openclaw_app.adapters.http_api import AuthConfig, HttpAuthorityConfig, make_server
from openclaw_app.router.content_os_bridge import ContentOSBridgeMixin
from openclaw_app.router.content_os_queue import create_ready_task
from openclaw_app.services.device_job_service import DeviceJobError, DeviceJobService
from openclaw_app.services.device_job_store import DeviceJobStore
from openclaw_app.services.media_device_job_contract import (
    MIN_CLIENT_VERSION,
    R1_OPERATION_IDS,
    SERVER_API_VERSION,
    catalog_digest,
    operation_path,
    resolve_r1_operation,
    validate_r1_response,
)


TENANT_A = "11111111-1111-4111-8111-111111111111"
TENANT_B = "22222222-2222-4222-8222-222222222222"


class HttpAccountAuth:
    def __init__(self) -> None:
        self.tenant_id = UUID(TENANT_A)

    def resolve_session(self, token: str | None):
        if token != "session-a":
            return None
        return SimpleNamespace(tenant_id=self.tenant_id, user_id=UUID("33333333-3333-4333-8333-333333333333"), role="user")

    def verify_csrf(self, token: str, supplied: str) -> bool:
        return token == "session-a" and supplied == "csrf-a"


class MutableClock:
    def __init__(self) -> None:
        self.value = 1_700_000_000.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class ContentOSMacResultRouter(ContentOSBridgeMixin):
    def __init__(self, vault_root: Path) -> None:
        self.vault_root = vault_root

    def _content_os_vault_root(self) -> Path:
        return self.vault_root


class DeviceJobR1Test(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "device-jobs.sqlite3"
        self.clock = MutableClock()
        self.store = DeviceJobStore(self.db_path, credential_secret=b"r1-test-secret-which-is-at-least-32-bytes", clock=self.clock)
        self.service = DeviceJobService(self.store, clock=self.clock)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def pair(self, tenant_id: str, *, label: str = "Mac", heartbeat: bool = True) -> tuple[dict[str, object], str]:
        code = self.service.create_pair_code(
            tenant_id,
            device_label=label,
            expires_in_seconds=300,
            idempotency_key=f"pair-code-{tenant_id}",
        )
        device, credential = self.service.pair_device(
            pair_code=str(code["pair_code"]),
            device_label=label,
            device_platform="macos",
            client_version="1.0.0",
            idempotency_key=f"pair-{tenant_id}",
        )
        if heartbeat:
            self.service.heartbeat(
                str(device["device_id"]), credential, observed_at="2023-11-14T22:13:20Z",
                client_version="1.0.0", api_version=SERVER_API_VERSION, reported_catalog_digest=catalog_digest(),
                capabilities=[], idempotency_key=f"initial-heartbeat-{tenant_id}", expected_revision=1,
            )
        return device, credential

    def create_job(self, tenant_id: str, device_id: str) -> dict[str, object]:
        return self.service.create_job(
            tenant_id,
            pipeline_id="pipeline.demo",
            pipeline_version="1.0.0",
            catalog_digest="sha256:catalog",
            device_id=device_id,
            input_refs=["input:one"],
            output_selection=["analysis"],
            confirmation_ref=None,
            idempotency_key=f"job-{tenant_id}-{device_id}",
        )

    def test_two_tenant_wrong_owner_rejection_is_uniform(self) -> None:
        device_a, credential_a = self.pair(TENANT_A)
        device_b, credential_b = self.pair(TENANT_B)
        job_b = self.create_job(TENANT_B, str(device_b["device_id"]))

        self.assertEqual(len(self.service.list_devices(TENANT_A)), 1)
        with self.assertRaises(DeviceJobError) as revoke_error:
            self.service.revoke_device(TENANT_A, str(device_b["device_id"]), idempotency_key="wrong-revoke")
        with self.assertRaises(DeviceJobError) as detail_error:
            self.service.get_job(TENANT_A, str(job_b["job_id"]))
        with self.assertRaises(DeviceJobError) as lease_error:
            self.service.lease_job(
                str(job_b["job_id"]), credential_a, lease_seconds=30, idempotency_key="wrong-lease"
            )

        self.assertEqual({revoke_error.exception.code, detail_error.exception.code, lease_error.exception.code}, {"not_found"})
        self.assertNotEqual(credential_a, credential_b)

    def test_atomic_double_claim_allows_one_winner(self) -> None:
        device, credential = self.pair(TENANT_A)
        job = self.create_job(TENANT_A, str(device["device_id"]))

        def claim() -> dict[str, object]:
            return self.service.lease_job(
                str(job["job_id"]), credential, lease_seconds=30, idempotency_key="claim-" + threading.current_thread().name
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(lambda _: self._claim_result(claim), range(2)))
        successes = [result for result, error in outcomes if result is not None]
        errors = [error for result, error in outcomes if error is not None]
        self.assertEqual(len(successes), 1)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].code, "invalid_state")

    @staticmethod
    def _claim_result(claim):
        try:
            return claim(), None
        except DeviceJobError as exc:
            return None, exc

    def test_stale_revision_is_rejected(self) -> None:
        device, credential = self.pair(TENANT_A)
        job = self.create_job(TENANT_A, str(device["device_id"]))
        with self.assertRaises(DeviceJobError) as raised:
            self.service.lease_job(
                str(job["job_id"]), credential, lease_seconds=30, idempotency_key="stale", expected_revision=2
            )
        self.assertEqual(raised.exception.code, "invalid_state")
        self.assertEqual(self.service.get_job(TENANT_A, str(job["job_id"]))["revision"], 1)

    def test_expired_lease_rejects_follow_up_action(self) -> None:
        device, credential = self.pair(TENANT_A)
        job = self.create_job(TENANT_A, str(device["device_id"]))
        leased = self.service.lease_job(
            str(job["job_id"]), credential, lease_seconds=1, idempotency_key="lease"
        )
        self.clock.advance(2)
        with self.assertRaises(DeviceJobError) as raised:
            self.service.ack_job(
                str(job["job_id"]), credential, ack_ref="ack", idempotency_key="ack", expected_revision=leased["revision"]
            )
        self.assertEqual(raised.exception.code, "invalid_state")
        self.assertEqual(self.service.get_job(TENANT_A, str(job["job_id"]))["state"], "expired")

    def test_revoke_invalidates_credential(self) -> None:
        device, credential = self.pair(TENANT_A)
        with self.store.connect() as connection:
            row = connection.execute("SELECT credential_hash, credential_version FROM devices WHERE device_id = ?", (device["device_id"],)).fetchone()
        self.assertEqual(row[0], hashlib.sha256(credential.encode("utf-8")).digest())
        self.assertEqual(row[1], 1)
        self.service.revoke_device(TENANT_A, str(device["device_id"]), idempotency_key="revoke")
        with self.assertRaises(DeviceJobError) as raised:
            self.service.heartbeat(
                str(device["device_id"]), credential, observed_at="2023-11-14T22:13:20Z",
                client_version="1.0.0", capabilities=[], idempotency_key="heartbeat",
            )
        self.assertEqual(raised.exception.code, "device_revoked")

    def test_wrong_action_is_rejected(self) -> None:
        device, credential = self.pair(TENANT_A)
        job = self.create_job(TENANT_A, str(device["device_id"]))
        with self.assertRaises(DeviceJobError) as raised:
            self.service.start_job(
                str(job["job_id"]), credential, start_ref="start", idempotency_key="start", expected_revision=1
            )
        self.assertEqual(raised.exception.code, "invalid_state")

    def test_result_is_idempotent(self) -> None:
        device, credential = self.pair(TENANT_A)
        job = self.create_job(TENANT_A, str(device["device_id"]))
        leased = self.service.lease_job(str(job["job_id"]), credential, lease_seconds=30, idempotency_key="lease")
        acked = self.service.ack_job(
            str(job["job_id"]), credential, ack_ref="ack", idempotency_key="ack", expected_revision=leased["revision"]
        )
        started = self.service.start_job(
            str(job["job_id"]), credential, start_ref="start", idempotency_key="start", expected_revision=acked["revision"]
        )
        first = self.service.result_job(
            str(job["job_id"]), credential, result_status="succeeded", result_refs=["result:one"],
            artifact_refs=[], failure_code=None, idempotency_key="result", expected_revision=started["revision"]
        )
        second = self.service.result_job(
            str(job["job_id"]), credential, result_status="succeeded", result_refs=["result:one"],
            artifact_refs=[], failure_code=None, idempotency_key="result", expected_revision=started["revision"]
        )
        self.assertEqual(first, second)
        self.assertEqual(first["state"], "succeeded")

    def test_restart_readback_persists_devices_jobs_and_lease_state(self) -> None:
        device, credential = self.pair(TENANT_A)
        job = self.create_job(TENANT_A, str(device["device_id"]))
        leased = self.service.lease_job(str(job["job_id"]), credential, lease_seconds=30, idempotency_key="lease")
        restarted_store = DeviceJobStore(self.db_path, credential_secret=b"r1-test-secret-which-is-at-least-32-bytes", clock=self.clock)
        restarted = DeviceJobService(restarted_store, clock=self.clock)
        self.assertEqual(restarted.list_devices(TENANT_A)[0]["device_id"], device["device_id"])
        self.assertEqual(restarted.get_job(TENANT_A, str(job["job_id"]))["lease_id"], leased["lease_id"])
        child_script = """
import json
import sys
from openclaw_app.services.device_job_service import DeviceJobService
from openclaw_app.services.device_job_store import DeviceJobStore
store = DeviceJobStore(sys.argv[1], credential_secret=b'r1-test-secret-which-is-at-least-32-bytes', clock=lambda: 1700000001.0)
service = DeviceJobService(store, clock=lambda: 1700000001.0)
print(json.dumps({'devices': service.list_devices(sys.argv[2]), 'job': service.get_job(sys.argv[2], sys.argv[3])}, sort_keys=True))
"""
        child_environment = dict(os.environ)
        child_environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
        child_output = subprocess.check_output(
            [sys.executable, "-c", child_script, str(self.db_path), TENANT_A, str(job["job_id"])],
            cwd=Path(__file__).resolve().parents[1],
            env=child_environment,
            text=True,
        )
        child_readback = json.loads(child_output)
        self.assertEqual(child_readback["devices"][0]["device_id"], device["device_id"])
        self.assertEqual(child_readback["job"]["lease_id"], leased["lease_id"])

    def test_migration_readback_has_one_durable_schema(self) -> None:
        with self.store.connect() as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 1)
            names = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                )
            }
            columns = {
                row["name"]: row
                for row in connection.execute("PRAGMA table_info(devices)")
            }
        self.assertTrue({"pair_codes", "devices", "jobs", "device_job_idempotency"}.issubset(names))
        self.assertEqual(columns["api_compatible"]["dflt_value"], "0")
        self.assertEqual(columns["catalog_compatible"]["dflt_value"], "0")

    def test_legacy_v1_tables_are_upgraded_before_runtime_use(self) -> None:
        with self.store.connect() as connection:
            connection.execute("PRAGMA foreign_keys=OFF")
            connection.executescript(
                """
                CREATE TABLE devices_legacy AS SELECT
                    device_id, tenant_id, device_label, device_platform, client_version,
                    capabilities_json, credential_hash, credential_version, state, revision,
                    last_observed_at, last_seen_at, created_at, revoked_at
                FROM devices;
                DROP TABLE devices;
                ALTER TABLE devices_legacy RENAME TO devices;
                CREATE TABLE jobs_legacy AS SELECT
                    job_id, tenant_id, pipeline_id, pipeline_version, catalog_digest, device_id,
                    input_refs_json, output_selection_json, confirmation_ref, state, revision,
                    lease_id, lease_expires_at, lease_device_id, ack_ref, start_ref, result_status,
                    result_refs_json, artifact_refs_json, failure_code, result_fingerprint,
                    created_at, updated_at
                FROM jobs;
                DROP TABLE jobs;
                ALTER TABLE jobs_legacy RENAME TO jobs;
                """
            )

        upgraded = DeviceJobStore(
            self.db_path,
            credential_secret=b"r1-test-secret-which-is-at-least-32-bytes",
            clock=self.clock,
        )
        with upgraded.connect() as connection:
            device_columns = {row["name"] for row in connection.execute("PRAGMA table_info(devices)")}
            job_columns = {row["name"] for row in connection.execute("PRAGMA table_info(jobs)")}
        self.assertTrue({"api_version", "reported_catalog_digest", "api_compatible", "catalog_compatible"}.issubset(device_columns))
        self.assertTrue({"leased_at", "acknowledged_at", "started_at", "completed_at"}.issubset(job_columns))

    def test_pair_readback_starts_incompatible_until_heartbeat(self) -> None:
        device, credential = self.pair(TENANT_A, heartbeat=False)
        with self.store.connect() as connection:
            row = connection.execute(
                "SELECT api_compatible, catalog_compatible FROM devices WHERE device_id = ?",
                (device["device_id"],),
            ).fetchone()
        self.assertEqual((row["api_compatible"], row["catalog_compatible"]), (0, 0))
        job = self.create_job(TENANT_A, str(device["device_id"]))
        self.assertEqual(self.service.list_jobs_for_device(credential, state=None), [])
        with self.assertRaises(DeviceJobError) as raised:
            self.service.lease_job(
                str(job["job_id"]), credential, lease_seconds=30, idempotency_key="before-heartbeat-lease",
                expected_revision=1,
            )
        self.assertEqual(raised.exception.code, "invalid_state")

    def test_packaged_cli_version_is_compatible_with_frozen_pipeline_minimum(self) -> None:
        self.assertEqual(MIN_CLIENT_VERSION, "0.1.0")
        device, credential = self.pair(TENANT_A, heartbeat=False)
        heartbeat = self.service.heartbeat(
            str(device["device_id"]), credential,
            observed_at="2023-11-14T22:13:20Z",
            client_version="0.2.0",
            api_version=SERVER_API_VERSION,
            reported_catalog_digest=catalog_digest(),
            capabilities=[],
            idempotency_key="packaged-cli-heartbeat",
            expected_revision=1,
        )
        self.assertTrue(heartbeat["api_compatible"])
        self.assertTrue(heartbeat["catalog_compatible"])

    def test_heartbeat_idempotency_fingerprint_covers_compatibility_inputs(self) -> None:
        device, credential = self.pair(TENANT_A, heartbeat=False)
        heartbeat_args = {
            "observed_at": "2023-11-14T22:13:20Z",
            "client_version": "1.0.0",
            "api_version": SERVER_API_VERSION,
            "reported_catalog_digest": catalog_digest(),
            "capabilities": [],
            "idempotency_key": "fingerprint-heartbeat",
            "expected_revision": 1,
        }
        self.service.heartbeat(str(device["device_id"]), credential, **heartbeat_args)
        for changed in (
            {"api_version": "999"},
            {"reported_catalog_digest": "sha256:changed"},
            {"expected_revision": 2},
        ):
            with self.subTest(changed=changed), self.assertRaises(DeviceJobError) as raised:
                self.service.heartbeat(str(device["device_id"]), credential, **{**heartbeat_args, **changed})
            self.assertEqual(raised.exception.code, "idempotency_conflict")

    def test_runtime_qa_all_declared_r1_methods_are_not_404(self) -> None:
        server = make_server("127.0.0.1", 0, None, device_job_service=self.service)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            host, port = server.server_address
            for operation_id in R1_OPERATION_IDS:
                path = "/openclaw/media/api" + operation_path(operation_id, {"device_id": "dev_qa", "job_id": "job_qa"})
                method = self.service.operation_metadata(operation_id)["method"]
                connection = http.client.HTTPConnection(host, port, timeout=3)
                connection.request(method, path, body=json.dumps({}), headers={"Content-Type": "application/json"})
                response = connection.getresponse()
                response.read()
                connection.close()
                self.assertNotEqual(response.status, 404, operation_id)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

    def test_route_parity_comes_from_generated_metadata(self) -> None:
        for operation_id in R1_OPERATION_IDS:
            route = "/openclaw/media/api" + operation_path(
                operation_id, {"device_id": "dev_parity", "job_id": "job_parity"}
            )
            resolved = resolve_r1_operation(route.removeprefix("/openclaw/media/api"), self.service.operation_metadata(operation_id)["method"])
            self.assertEqual(resolved[0], operation_id)

    def test_compatibility_mismatch_is_durable_and_blocks_discovery_and_lease(self) -> None:
        device, credential = self.pair(TENANT_A, heartbeat=False)
        job = self.create_job(TENANT_A, str(device["device_id"]))
        heartbeat = self.service.heartbeat(
            str(device["device_id"]), credential, observed_at="2023-11-14T22:13:20Z",
            client_version="1.0.0", api_version="999", reported_catalog_digest=catalog_digest(),
            capabilities=[], idempotency_key="compat-mismatch", expected_revision=1,
        )
        self.assertFalse(heartbeat["api_compatible"])
        self.assertTrue(heartbeat["catalog_compatible"])
        self.assertIsNone(heartbeat["claimable_job"])
        self.assertEqual(self.service.list_jobs_for_device(credential, state=None), [])
        with self.assertRaises(DeviceJobError) as raised:
            self.service.lease_job(str(job["job_id"]), credential, lease_seconds=30, idempotency_key="blocked-lease", expected_revision=1)
        self.assertEqual(raised.exception.code, "invalid_state")
        restarted = DeviceJobService(DeviceJobStore(self.db_path, credential_secret=b"r1-test-secret-which-is-at-least-32-bytes", clock=self.clock), clock=self.clock)
        self.assertEqual(restarted.list_jobs_for_device(credential, state=None), [])

    def test_device_discovery_is_bound_to_device_and_tenant(self) -> None:
        device_a, credential_a = self.pair(TENANT_A)
        device_b, _ = self.pair(TENANT_B)
        self.create_job(TENANT_A, str(device_a["device_id"]))
        self.create_job(TENANT_B, str(device_b["device_id"]))
        visible = self.service.list_jobs_for_device(credential_a, state=None)
        self.assertEqual(len(visible), 1)
        self.assertEqual(visible[0]["device_id"], device_a["device_id"])

    def test_revision_zero_is_rejected_for_heartbeat_and_revoke(self) -> None:
        device, credential = self.pair(TENANT_A)
        with self.assertRaises(DeviceJobError):
            self.service.heartbeat(
                str(device["device_id"]), credential, observed_at="2023-11-14T22:13:20Z",
                client_version="1.0.0", capabilities=[], idempotency_key="revision-zero", expected_revision=0,
            )
        with self.assertRaises(DeviceJobError):
            self.service.revoke_device(TENANT_A, str(device["device_id"]), idempotency_key="revoke-zero", expected_revision=0)

    def test_complete_projections_validate_against_frozen_schemas(self) -> None:
        device, credential = self.pair(TENANT_A)
        validate_r1_response("device_pair", {"device": device, "device_credential": credential})
        job = self.create_job(TENANT_A, str(device["device_id"]))
        validate_r1_response("job_create", {"job": job})
        self.assertEqual(set(job), {
            "job_id", "state", "pipeline_id", "pipeline_version", "catalog_digest", "device_id",
            "input_refs", "output_selection", "confirmation_ref", "revision", "lease_id",
            "lease_expires_at", "ack_ref", "acknowledged_at", "start_ref", "started_at", "result_status",
            "result_refs", "artifact_refs", "failure_code", "created_at", "updated_at", "leased_at", "completed_at",
        })

    def test_r1_route_set_is_fourteen_and_includes_pipeline_compatibility(self) -> None:
        self.assertEqual(len(R1_OPERATION_IDS), 14)
        self.assertIn("pipeline_list", R1_OPERATION_IDS)
        self.assertIn("cli_release_compatibility", R1_OPERATION_IDS)

    def test_http_round_trip_uses_session_or_device_credential_only(self) -> None:
        auth = HttpAccountAuth()
        auth_config = AuthConfig(
            session_secret=b"r1-http-secret-which-is-at-least-32-bytes",
            cookie_secure=False,
        )
        server = make_server(
            "127.0.0.1",
            0,
            None,
            auth_config=auth_config,
            account_auth=auth,
            authority_config=HttpAuthorityConfig("http://127.0.0.1"),
            device_job_service=self.service,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        def request(method: str, path: str, body: dict[str, object] | None = None, headers: dict[str, str] | None = None, *, include_session: bool = True):
            connection = http.client.HTTPConnection(*server.server_address, timeout=3)
            request_headers = {"Cookie": f"{auth_config.cookie_name}=session-a"} if include_session else {}
            request_headers.update(headers or {})
            encoded = None if body is None else json.dumps(body).encode("utf-8")
            if encoded is not None:
                request_headers["Content-Type"] = "application/json"
            connection.request(method, path, body=encoded, headers=request_headers)
            response = connection.getresponse()
            result = json.loads(response.read() or b"{}")
            connection.close()
            return response.status, result

        try:
            mutation_headers = {"Origin": f"http://127.0.0.1:{server.server_address[1]}", "X-OpenClaw-CSRF": "csrf-a", "Idempotency-Key": "http-pair-code"}
            status, pair_code = request("POST", "/openclaw/media/api/pair-codes", {"device_label": "HTTP Mac", "expires_in_seconds": 300}, mutation_headers)
            self.assertEqual(status, 201, pair_code)
            status, paired = request("POST", "/openclaw/media/api/devices/pair", {"pair_code": pair_code["pair_code"], "device_label": "HTTP Mac", "device_platform": "macos", "client_version": "1.0.0"}, {"Idempotency-Key": "http-pair"})
            self.assertEqual(status, 200, paired)
            credential = paired["device_credential"]
            device_id = paired["device"]["device_id"]
            status, heartbeat = request(
                "POST", f"/openclaw/media/api/devices/{device_id}/heartbeat",
                {"observed_at": "2023-11-14T22:13:20Z", "client_version": "1.0.0", "api_version": SERVER_API_VERSION, "catalog_digest": catalog_digest(), "capabilities": [], "expected_revision": 1},
                {"Authorization": f"Bearer {credential}", "Idempotency-Key": "http-heartbeat"},
            )
            self.assertEqual(status, 200, heartbeat)
            validate_r1_response("device_heartbeat", heartbeat)
            status, listed = request("GET", "/openclaw/media/api/devices")
            self.assertEqual(status, 200)
            self.assertEqual(listed["devices"][0]["device_id"], device_id)
            status, unauthenticated_pipelines = request("GET", "/openclaw/media/api/pipelines", include_session=False)
            self.assertEqual(status, 401, unauthenticated_pipelines)
            status, pipelines = request("GET", "/openclaw/media/api/pipelines")
            self.assertEqual(status, 200, pipelines)
            validate_r1_response("pipeline_list", pipelines)
            compatibility_body = {"cli_version": "1.0.0", "platform": "macos", "python_version": "3.12.5", "catalog_digest": catalog_digest(), "api_version": SERVER_API_VERSION}
            status, unauthenticated_compatibility = request(
                "POST", "/openclaw/media/api/cli/releases/compatibility", compatibility_body, include_session=False,
            )
            self.assertEqual(status, 401, unauthenticated_compatibility)
            status, compatibility = request(
                "POST", "/openclaw/media/api/cli/releases/compatibility",
                compatibility_body,
            )
            self.assertEqual(status, 200, compatibility)
            validate_r1_response("cli_release_compatibility", compatibility)
            self.assertEqual(compatibility["min_cli_version"], "0.1.0")
            self.assertEqual(compatibility["supported_python"], ">=3.12,<3.14")
            self.assertEqual(compatibility["supported_platforms"], ["macos"])
            for cli_version, python_version, expected in (
                ("0.10", "3.12.5", True),
                ("1.0", "3.13.0", True),
                ("10.0", "3.14.0", False),
                ("malformed", "3.12.5", False),
                ("1..0", "3.12beta", False),
                ("0.1.0", "3.14", False),
            ):
                status, version_result = request(
                    "POST", "/openclaw/media/api/cli/releases/compatibility",
                    {**compatibility_body, "cli_version": cli_version, "python_version": python_version},
                )
                self.assertEqual(status, 200)
                self.assertEqual(version_result["compatible"], expected, (cli_version, python_version))
            job_body = {"pipeline_id": "pipeline.demo", "pipeline_version": "1.0.0", "catalog_digest": "sha256:catalog", "device_id": device_id, "input_refs": ["input:one"], "output_selection": ["analysis"]}
            status, created = request("POST", "/openclaw/media/api/jobs", job_body, {**mutation_headers, "Idempotency-Key": "http-job"})
            self.assertEqual(status, 201, created)
            job_id = created["job"]["job_id"]
            status, leased = request("POST", f"/openclaw/media/api/jobs/{job_id}/lease", {"lease_seconds": 30, "expected_revision": 1}, {"Authorization": f"Bearer {credential}", "Idempotency-Key": "http-lease"})
            self.assertEqual(status, 200, leased)
            status, device_jobs = request(
                "GET", "/openclaw/media/api/jobs",
                headers={"Authorization": f"Bearer {credential}"}, include_session=False,
            )
            self.assertEqual(status, 200, device_jobs)
            self.assertEqual(device_jobs["jobs"], [])
            status, detail = request("GET", f"/openclaw/media/api/jobs/{job_id}")
            self.assertEqual(status, 200)
            self.assertEqual(detail["job"]["state"], "leased")
            job_body["tenant_id"] = TENANT_B
            status, rejected = request("POST", "/openclaw/media/api/jobs", job_body, {**mutation_headers, "Idempotency-Key": "http-body-tenant"})
            self.assertEqual(status, 400)
            self.assertEqual(rejected["error"]["code"], "invalid_request")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

    def test_mutating_service_does_not_accept_body_tenant_parameter(self) -> None:
        self.assertNotIn("body_tenant_id", inspect.signature(self.service.create_job).parameters)

    def test_internal_content_os_mac_result_requires_device_tenant_and_contract(self) -> None:
        vault_temporary = tempfile.TemporaryDirectory()
        server = None
        thread = None
        try:
            vault_root = Path(vault_temporary.name)
            project_id = "20260710_http_result"
            project_dir = vault_root / "08_内容项目" / project_id
            project_dir.mkdir(parents=True)
            (project_dir / "00_项目总览.md").write_text(
                "---\n"
                "spec_version: content_os_v0.2\n"
                "doc_type: project_overview\n"
                f"project_id: {project_id}\n"
                "idea_id: idea_20260710_http_result\n"
                "status: captured\n"
                "project_revision: 1\n"
                "editor_backend: handoff_pack\n"
                "---\n\n# HTTP 回传测试\n",
                encoding="utf-8",
            )
            task = create_ready_task(
                vault_root,
                project_id,
                task_type="local_material_match",
                project_revision=1,
                change_request_id=None,
                editor_backend="handoff_pack",
                human_confirmed_impact=False,
                tenant_id=TENANT_A,
                now=datetime(2026, 8, 28, tzinfo=timezone.utc),
            )
            _device, credential = self.pair(TENANT_A, heartbeat=False)
            app = SimpleNamespace(router=ContentOSMacResultRouter(vault_root))
            server = make_server("127.0.0.1", 0, app, device_job_service=self.service)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()

            def request(payload: dict[str, object], credential_value: str | None = None) -> tuple[int, dict[str, object]]:
                connection = http.client.HTTPConnection(*server.server_address, timeout=3)
                encoded = json.dumps(payload).encode("utf-8")
                headers = {"Content-Type": "application/json"}
                if credential_value is not None:
                    headers["Authorization"] = f"Bearer {credential_value}"
                connection.request("POST", "/internal/content-os/mac-result", body=encoded, headers=headers)
                response = connection.getresponse()
                body = json.loads(response.read() or b"{}")
                connection.close()
                return response.status, body

            result = {
                "spec_version": "content_os_v0.2",
                "doc_type": "mac_result",
                "task_id": task.task_id,
                "task_type": task.task_type,
                "completed_by": "mac_openclaw",
                "status": "done",
                "project_id": task.project_id,
                "project_revision": task.project_revision,
                "change_request_id": task.change_request_id,
                "editor_backend": task.editor_backend,
                "tenant_id": TENANT_A,
            }
            status, unauthenticated = request(result)
            self.assertEqual(status, 401, unauthenticated)
            status, invalid_type = request({**result, "doc_type": "mac_task"}, credential)
            self.assertEqual(status, 400, invalid_type)
            status, invalid_credential = request(result, "not-a-device-credential")
            self.assertEqual(status, 401, invalid_credential)
            status, wrong_tenant = request({**result, "tenant_id": TENANT_B}, credential)
            self.assertEqual(status, 422, wrong_tenant)
            status, accepted = request(result, credential)
            self.assertEqual(status, 200, accepted)
            self.assertEqual(accepted, {"ok": True, "status": "content_os_mac_result_accepted", "task_id": task.task_id})
            self.assertNotIn("result_path", accepted)
        finally:
            if server is not None:
                server.shutdown()
                server.server_close()
            if thread is not None:
                thread.join(timeout=3)
            vault_temporary.cleanup()


if __name__ == "__main__":
    unittest.main()
