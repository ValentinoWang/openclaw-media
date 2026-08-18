from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading

import httpx
import pytest

from openclaw_media.remote_client import RemoteClient, RemoteError


class _Handler(BaseHTTPRequestHandler):
    calls = []
    result_attempts = 0

    def log_message(self, *_args):
        return

    def do_POST(self):
        size = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(size)
        self.__class__.calls.append((self.path, dict(self.headers), body))
        if self.path.endswith("/result") and self.__class__.result_attempts == 0:
            self.__class__.result_attempts += 1
            self.send_response(503)
            self.end_headers()
            return
        if self.path.endswith("/devices/pair"):
            value = {"device": {"device_id": "dev_1", "state": "paired", "revision": 1}, "device_credential": "device-secret"}
        elif self.path.endswith("/heartbeat"):
            value = {"device_id": "dev_1", "accepted_at": "2026-08-04T00:00:00Z", "revision": 2, "state": "online", "accepted_client_version": "0.2.0", "catalog_digest": "sha256:x", "api_compatible": True, "catalog_compatible": True, "claimable_job": None}
        else:
            value = {"job": {"job_id": "job_1", "revision": 3, "state": "succeeded"}}
        encoded = json.dumps(value).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def test_frozen_routes_auth_retry_and_body_redaction_use_local_fake_http():
    _Handler.calls = []
    _Handler.result_attempts = 0
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = RemoteClient(f"http://127.0.0.1:{server.server_port}", local_endpoint_enabled=True, retry_backoff=0)
        try:
            client.pair(pair_code="one-time-code", device_label="Test Mac", client_version="0.2.0")
            client.device_credential = "device-secret"
            heartbeat = client.heartbeat(device_id="dev_1", observed_at="2026-08-04T00:00:00Z", client_version="0.2.0", api_version="1", catalog_digest="sha256:x", capabilities=[], expected_revision=1)
            assert heartbeat["state"] == "online"
            client.job_result("job_1", result_status="succeeded", result_refs=["artifacts/report.json"], artifact_refs=["artifacts/report.json"], failure_code=None, expected_revision=2)
        finally:
            client.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
    heartbeat_calls = [item for item in _Handler.calls if item[0].endswith("/heartbeat")]
    assert heartbeat_calls and b"dev_1" not in heartbeat_calls[0][2]
    assert b"device-secret" not in heartbeat_calls[0][2]
    assert b"/home/" not in heartbeat_calls[0][2]
    result_calls = [item for item in _Handler.calls if item[0].endswith("/result")]
    assert len(result_calls) == 2
    assert result_calls[0][1]["Idempotency-Key"] == result_calls[1][1]["Idempotency-Key"]


def test_raw_media_bytes_and_absolute_paths_fail_before_http():
    client = RemoteClient.__new__(RemoteClient)
    with pytest.raises(RemoteError) as raised:
        client._request("archive_commit", "POST", "/archives/commit", {"manifest": {"content": b"media"}}, auth_source="session", idempotency_required=True)
    assert raised.value.code == "media_bytes_forbidden"
    with pytest.raises(RemoteError) as raised:
        client._request("archive_commit", "POST", "/archives/commit", {"local_path": "/private/media.mp4"}, auth_source="session", idempotency_required=True)
    assert raised.value.code == "local_path_forbidden"


class _CredentialTransport:
    def __init__(self):
        self.credentials = []

    def request(self, method, path, *, headers=None, content=None, credential=None):
        self.credentials.append(credential)
        return httpx.Response(200, json={})


def test_session_or_device_auth_prefers_device_then_falls_back_to_session_and_closes():
    transport = _CredentialTransport()
    client = RemoteClient(
        "https://example.invalid",
        device_credential="device-secret",
        session_credential="session-secret",
        transport=transport,
    )
    client.job_list()
    client.device_credential = None
    client.job_list()
    assert transport.credentials == ["device-secret", "session-secret"]

    client.session_credential = None
    with pytest.raises(RemoteError) as raised:
        client.job_list()
    assert raised.value.code == "credential_not_configured"
