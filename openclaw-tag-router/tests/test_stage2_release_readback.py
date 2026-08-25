"""Protected acceptance tests for the future Stage-2 release readback guard.

The implementation is intentionally absent in this acceptance-design change.
These tests define the injected evaluator boundary and must remain protected.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from typing import Any


GUARD_PATH = Path(__file__).resolve().parents[1] / "scripts" / "qa" / "check_stage2_release_process.py"
RELEASE_ROOT = "/srv/openclaw-stage2/releases/release-20260825T000000Z"
SETTINGS_PATH = f"{RELEASE_ROOT}/config/settings.yaml"
POINTER_PATH = "/srv/openclaw-stage2/current"
RELEASE_ID = "openclaw-stage2-release-20260825T000000Z"
COMMIT_SHA = "59e2adfd34853b6929d9fa69e69585806ac9c83a"
MANIFEST_SHA = "a" * 64


def expected_identity() -> dict[str, Any]:
    return {
        "service_name": "openclaw-stage2.service",
        "release_root": RELEASE_ROOT,
        "settings_path": SETTINGS_PATH,
        "port": 8892,
        "pointer_path": POINTER_PATH,
        "manifest_identity": {
            "release_id": RELEASE_ID,
            "commit_sha": COMMIT_SHA,
            "manifest_sha256": MANIFEST_SHA,
        },
        "http_statuses": [
            {"surface": "direct", "path": "/healthz", "status": 200},
            {"surface": "direct", "path": "/readyz", "status": 200},
            {"surface": "direct", "path": "/stage2/healthz", "status": 404},
            {"surface": "direct", "path": "/stage2/readyz", "status": 404},
            {"surface": "public", "path": "/stage2/healthz", "status": 200},
            {"surface": "public", "path": "/stage2/readyz", "status": 200},
        ],
    }


def complete_observation() -> dict[str, Any]:
    return {
        "systemd": {
            "ActiveState": "active",
            "SubState": "running",
            "MainPID": "24680",
            "ExecStart": (
                f"/usr/bin/python3 -m openclaw_app.server_cli --settings {SETTINGS_PATH} "
                "--host 127.0.0.1 --port 8892"
            ),
        },
        "process": {
            "pid": 24680,
            "cwd": RELEASE_ROOT,
            "argv": [
                "/usr/bin/python3",
                "-m",
                "openclaw_app.server_cli",
                "--settings",
                SETTINGS_PATH,
                "--host",
                "127.0.0.1",
                "--port",
                "8892",
            ],
        },
        "pointer": {"path": POINTER_PATH, "target": RELEASE_ROOT},
        "manifest": {
            "release_id": RELEASE_ID,
            "commit_sha": COMMIT_SHA,
            "manifest_sha256": MANIFEST_SHA,
        },
        "http_probes": [
            {"surface": "direct", "path": "/healthz", "status": 200},
            {"surface": "direct", "path": "/readyz", "status": 200},
            {"surface": "direct", "path": "/stage2/healthz", "status": 404},
            {"surface": "direct", "path": "/stage2/readyz", "status": 404},
            {"surface": "public", "path": "/stage2/healthz", "status": 200},
            {"surface": "public", "path": "/stage2/readyz", "status": 200},
        ],
    }


def evaluate(observed: dict[str, Any], expected: dict[str, Any]) -> Any:
    if not GUARD_PATH.is_file():
        raise AssertionError(
            "INTENDED_GUARD_MISSING: "
            "openclaw-tag-router/scripts/qa/check_stage2_release_process.py"
        )
    spec = importlib.util.spec_from_file_location("stage2_release_readback_guard", GUARD_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError("INTENDED_GUARD_UNLOADABLE: Stage-2 release readback guard")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    evaluator = getattr(module, "evaluate_readback", None)
    if evaluator is None:
        raise AssertionError("INTENDED_GUARD_INTERFACE_MISSING: evaluate_readback")
    return evaluator(observed, expected)


class Stage2ReleaseReadbackProtectedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        if not GUARD_PATH.is_file():
            raise AssertionError(
                "INTENDED_GUARD_MISSING: "
                "openclaw-tag-router/scripts/qa/check_stage2_release_process.py"
            )

    def assert_failure(
        self, observed: dict[str, Any], expected: dict[str, Any], code: str
    ) -> None:
        result = evaluate(observed, expected)
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["code"], code)

    def test_accepts_complete_readback(self) -> None:
        result = evaluate(complete_observation(), expected_identity())
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["code"], "OK")

    def test_rejects_inactive_service(self) -> None:
        observed = complete_observation()
        observed["systemd"]["ActiveState"] = "inactive"
        self.assert_failure(observed, expected_identity(), "SERVICE_INACTIVE")

    def test_rejects_missing_or_bad_main_pid(self) -> None:
        for value in (None, "not-a-pid", "0", "-1"):
            with self.subTest(main_pid=value):
                observed = complete_observation()
                if value is None:
                    del observed["systemd"]["MainPID"]
                else:
                    observed["systemd"]["MainPID"] = value
                self.assert_failure(
                    observed, expected_identity(), "MAIN_PID_MISSING_OR_INVALID"
                )

    def test_rejects_pid_cwd_drift(self) -> None:
        observed = complete_observation()
        observed["process"]["cwd"] = "/srv/openclaw-stage2/releases/older"
        self.assert_failure(observed, expected_identity(), "PID_CWD_DRIFT")

    def test_rejects_execstart_or_module_mismatch(self) -> None:
        observed = complete_observation()
        observed["systemd"]["ExecStart"] = observed["systemd"]["ExecStart"].replace(
            "openclaw_app.server_cli", "other.server"
        )
        self.assert_failure(observed, expected_identity(), "EXECSTART_MODULE_MISMATCH")

        observed = complete_observation()
        observed["process"]["argv"][2] = "other.server"
        self.assert_failure(observed, expected_identity(), "EXECSTART_MODULE_MISMATCH")

    def test_rejects_settings_or_port_mismatch(self) -> None:
        observed = complete_observation()
        observed["process"]["argv"][4] = "/srv/openclaw-stage2/releases/other/config/settings.yaml"
        self.assert_failure(observed, expected_identity(), "SETTINGS_OR_PORT_MISMATCH")

        observed = complete_observation()
        observed["process"]["argv"][-1] = "8893"
        self.assert_failure(observed, expected_identity(), "SETTINGS_OR_PORT_MISMATCH")

    def test_rejects_pointer_or_release_root_drift(self) -> None:
        observed = complete_observation()
        observed["pointer"]["target"] = "/srv/openclaw-stage2/releases/older"
        self.assert_failure(observed, expected_identity(), "POINTER_RELEASE_ROOT_DRIFT")

    def test_rejects_manifest_identity_mismatch(self) -> None:
        observed = complete_observation()
        observed["manifest"]["commit_sha"] = "0" * 40
        self.assert_failure(observed, expected_identity(), "MANIFEST_IDENTITY_MISMATCH")

    def test_rejects_missing_required_property(self) -> None:
        for property_name in ("ActiveState", "SubState", "ExecStart"):
            with self.subTest(property_name=property_name):
                observed = complete_observation()
                del observed["systemd"][property_name]
                self.assert_failure(observed, expected_identity(), "REQUIRED_PROPERTY_MISSING")

    def test_rejects_http_status_mismatch(self) -> None:
        observed = complete_observation()
        observed["http_probes"][-1]["status"] = 503
        self.assert_failure(observed, expected_identity(), "HTTP_STATUS_MISMATCH")

    def test_keeps_direct_and_public_routes_distinct(self) -> None:
        expected = expected_identity()
        observed = complete_observation()
        observed["http_probes"][2]["status"] = 200
        self.assert_failure(observed, expected, "HTTP_STATUS_MISMATCH")

        observed = complete_observation()
        observed["http_probes"][-1]["status"] = 404
        self.assert_failure(observed, expected, "HTTP_STATUS_MISMATCH")

    def test_redacts_sensitive_observation_material(self) -> None:
        observed = complete_observation()
        observed["raw_capture"] = {
            "argv": ["--token", "SYNTHETIC_TOKEN_SENTINEL"],
            "environment": {"OPENCLAW_SECRET": "SYNTHETIC_ENV_SENTINEL"},
        }
        observed["http_probes"][0]["headers"] = {
            "Authorization": "Bearer SYNTHETIC_AUTH_SENTINEL",
            "Cookie": "session=SYNTHETIC_COOKIE_SENTINEL",
        }
        observed["http_probes"][0]["status"] = 503
        result = evaluate(observed, expected_identity())
        rendered = json.dumps(result, ensure_ascii=True, sort_keys=True)
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["code"], "HTTP_STATUS_MISMATCH")
        for sentinel in (
            "SYNTHETIC_TOKEN_SENTINEL",
            "SYNTHETIC_ENV_SENTINEL",
            "SYNTHETIC_AUTH_SENTINEL",
            "SYNTHETIC_COOKIE_SENTINEL",
            SETTINGS_PATH,
            RELEASE_ROOT,
        ):
            self.assertNotIn(sentinel, rendered)

    def test_evaluator_uses_injected_observation_only(self) -> None:
        with patch("subprocess.run", side_effect=AssertionError("external command invoked")), \
            patch("socket.create_connection", side_effect=AssertionError("network invoked")), \
            patch("urllib.request.urlopen", side_effect=AssertionError("HTTP invoked")):
            result = evaluate(complete_observation(), expected_identity())
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["code"], "OK")


if __name__ == "__main__":
    unittest.main()
