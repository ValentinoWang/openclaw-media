"""Redacted outbound client for the frozen Media device/archive contract.

The client owns HTTP concerns only.  It does not open a listener, persist a
credential, accept cloud commands, or upload local paths/media bytes.
"""

from __future__ import annotations

from hashlib import sha256
import json
import logging
from collections.abc import Mapping
from typing import Any, Protocol
from urllib.parse import urlencode, urlsplit

import httpx

from .generated_product_contract import MediaProductClient, PATH_PARAMETERS, ProductTransport
from .safe_transport import SafeEndpointTransport, SafeTransportError


API_BASE = "/openclaw/media/api"
API_VERSION = "1"
_LOG = logging.getLogger(__name__)
_IDEMPOTENT = {
    "pair_code_create", "device_pair", "device_heartbeat", "device_revoke",
    "job_create", "job_lease", "job_ack", "job_start", "job_result",
    "archive_commit", "archive_delete_plan", "archive_delete", "archive_readback",
}
_SECRET_KEYS = {"api_key", "authorization", "credential", "device_credential", "password", "token"}
_PATH_KEYS = {"local_path", "absolute_path", "workspace_path", "source_path"}


class RemoteError(RuntimeError):
    """A stable, redacted remote operation failure."""

    def __init__(self, code: str, *, status: int | None = None, retryable: bool = False) -> None:
        self.code = code
        self.status = status
        self.retryable = retryable
        super().__init__(code)


class RequestTransport(Protocol):
    def request(
        self,
        method: str,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        content: bytes | None = None,
        credential: str | None = None,
    ) -> httpx.Response: ...


def _canonical(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _idempotency(operation_id: str, path: str, request: Mapping[str, Any]) -> str:
    identity = {"operation": operation_id, "path": path, "request": request}
    return operation_id.replace("_", "-") + "-" + sha256(_canonical(identity)).hexdigest()[:32]


def _safe_request(value: Any, *, key: str | None = None, archive: bool = False) -> Any:
    """Reject transport-bound secrets, paths, bytes, and unknown binary values.

    Pair codes are deliberately allowed as the one-time pair request value and
    credentials are supplied only to the Authorization boundary, never inside
    a JSON request.  Archive content is already contract-shaped UTF-8/base64
    text; raw bytes are never accepted here.
    """

    if key is not None and key.lower() in _PATH_KEYS:
        raise RemoteError("local_path_forbidden")
    if isinstance(value, bytes | bytearray | memoryview):
        raise RemoteError("media_bytes_forbidden")
    if isinstance(value, Mapping):
        result = {}
        for item_key, item_value in value.items():
            if not isinstance(item_key, str):
                raise RemoteError("invalid_request")
            lowered = item_key.lower()
            if lowered in _PATH_KEYS:
                raise RemoteError("local_path_forbidden")
            if lowered in _SECRET_KEYS and lowered != "pair_code":
                raise RemoteError("secret_in_request_forbidden")
            result[item_key] = _safe_request(item_value, key=item_key, archive=archive)
        return result
    if isinstance(value, (list, tuple)):
        return [_safe_request(item, archive=archive) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        if isinstance(value, str) and key != "pair_code":
            path_like = value.startswith(("/", "\\")) or (len(value) > 2 and value[1] == ":" and value[2] in "/\\")
            private_path = any(marker in value for marker in ("/home/", "/Users/", "/private/", "C:\\Users\\"))
            if path_like or private_path:
                raise RemoteError("local_path_forbidden")
        return value
    raise RemoteError("invalid_request")


class _HttpProductTransport:
    def __init__(self, owner: "RemoteClient") -> None:
        self.owner = owner

    def request(
        self,
        *,
        operation_id: str,
        method: str,
        path: str,
        auth_source: str,
        owner_rule: str,
        idempotency: str,
        request: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        del owner_rule
        path_keys = set(PATH_PARAMETERS.get(operation_id, ()))
        payload = {key: value for key, value in request.items() if key not in path_keys}
        return self.owner._request(
            operation_id,
            method,
            path,
            payload,
            auth_source=auth_source,
            idempotency_required=idempotency == "required",
        )


class RemoteClient:
    """One outbound HTTPS client generated from ``generated_product_contract``."""

    def __init__(
        self,
        base_url: str,
        *,
        device_credential: str | None = None,
        session_credential: str | None = None,
        transport: RequestTransport | None = None,
        local_endpoint_enabled: bool = False,
        timeout: float = 30.0,
        retries: int = 2,
        retry_backoff: float = 0.05,
    ) -> None:
        if not isinstance(base_url, str) or not base_url.strip():
            raise RemoteError("invalid_endpoint")
        parsed = urlsplit(base_url)
        self._prefix = "" if parsed.path.rstrip("/") == API_BASE else API_BASE
        self._transport = transport or SafeEndpointTransport(
            base_url.rstrip("/") if self._prefix else base_url,
            local_endpoint_enabled=local_endpoint_enabled,
            timeout=timeout,
        )
        self.device_credential = device_credential
        self.session_credential = session_credential
        self.retries = max(0, min(int(retries), 5))
        self.retry_backoff = max(0.0, min(float(retry_backoff), 2.0))
        self._client = MediaProductClient(_HttpProductTransport(self))

    def close(self) -> None:
        close = getattr(self._transport, "close", None)
        if close is not None:
            close()

    def __enter__(self) -> "RemoteClient":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _credential_for(self, auth_source: str) -> str | None:
        if auth_source == "device_credential":
            return self.device_credential
        if auth_source == "session_or_device_credential":
            return self.device_credential or self.session_credential
        if auth_source == "session":
            return self.session_credential
        if auth_source == "pair_code":
            return None
        return self.session_credential

    def _request(
        self,
        operation_id: str,
        method: str,
        path: str,
        request: Mapping[str, Any],
        *,
        auth_source: str,
        idempotency_required: bool,
    ) -> Mapping[str, Any]:
        clean = _safe_request(request, archive=operation_id.startswith("archive_"))
        if not isinstance(clean, Mapping):
            raise RemoteError("invalid_request")
        headers = {"Accept": "application/json", "User-Agent": "openclaw-media"}
        if method.upper() != "GET":
            headers["Content-Type"] = "application/json"
        if idempotency_required:
            headers["Idempotency-Key"] = _idempotency(operation_id, path, clean)
        target = self._prefix + path
        body: bytes | None = None
        if method.upper() == "GET":
            params = [(key, str(value)) for key, value in clean.items() if value is not None]
            if params:
                target += "?" + urlencode(params, doseq=True)
        else:
            body = _canonical(clean)
        credential = self._credential_for(auth_source)
        if auth_source in {"device_credential", "session", "session_or_device_credential"} and not credential:
            raise RemoteError("credential_not_configured")
        attempts = self.retries + 1 if idempotency_required else 1
        last_code = "request_failed"
        for attempt in range(attempts):
            try:
                response = self._transport.request(
                    method,
                    target,
                    headers=headers,
                    content=body,
                    credential=credential,
                )
            except SafeTransportError as exc:
                last_code = exc.code
                if attempt + 1 >= attempts or exc.code in {"endpoint_not_allowed", "https_required", "invalid_endpoint"}:
                    raise RemoteError(last_code, retryable=attempt + 1 < attempts) from None
                continue
            except (httpx.TimeoutException, httpx.NetworkError):
                if attempt + 1 >= attempts:
                    raise RemoteError("request_failed", retryable=True) from None
                continue
            try:
                if response.status_code in {408, 429} or response.status_code >= 500:
                    last_code = "remote_unavailable"
                    if attempt + 1 < attempts:
                        continue
                    raise RemoteError(last_code, status=response.status_code, retryable=True)
                if response.status_code >= 400:
                    raise RemoteError("remote_rejected", status=response.status_code)
                if not response.content:
                    return {}
                try:
                    payload = response.json()
                except (ValueError, json.JSONDecodeError):
                    raise RemoteError("invalid_response", status=response.status_code) from None
                if not isinstance(payload, Mapping):
                    raise RemoteError("invalid_response", status=response.status_code)
                return dict(payload)
            finally:
                response.close()
        _LOG.debug("remote operation failed code=%s", last_code)
        raise RemoteError(last_code, retryable=True)

    def pair(self, *, pair_code: str, device_label: str, client_version: str) -> Mapping[str, Any]:
        return self._client.device_pair({"pair_code": pair_code, "device_label": device_label, "device_platform": "macos", "client_version": client_version})

    def heartbeat(self, **request: Any) -> Mapping[str, Any]:
        return self._client.device_heartbeat(request)

    def device_revoke(self, device_id: str, *, expected_revision: int) -> Mapping[str, Any]:
        return self._client.device_revoke({"device_id": device_id, "expected_revision": expected_revision})

    def job_list(self, **request: Any) -> Mapping[str, Any]:
        return self._client.job_list(request)

    def job_lease(self, job_id: str, **request: Any) -> Mapping[str, Any]:
        return self._client.job_lease({"job_id": job_id, **request})

    def job_ack(self, job_id: str, **request: Any) -> Mapping[str, Any]:
        return self._client.job_ack({"job_id": job_id, **request})

    def job_start(self, job_id: str, **request: Any) -> Mapping[str, Any]:
        return self._client.job_start({"job_id": job_id, **request})

    def job_result(self, job_id: str, **request: Any) -> Mapping[str, Any]:
        return self._client.job_result({"job_id": job_id, **request})

    def archive_commit(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        return self._client.archive_commit(request)

    def archive_list(self, **request: Any) -> Mapping[str, Any]:
        return self._client.archive_list(request)

    def archive_detail(self, archive_id: str) -> Mapping[str, Any]:
        return self._client.archive_detail({"archive_id": archive_id})

    def archive_delete_plan(self, archive_id: str, **request: Any) -> Mapping[str, Any]:
        return self._client.archive_delete_plan({"archive_id": archive_id, **request})

    def archive_delete(self, archive_id: str, **request: Any) -> Mapping[str, Any]:
        return self._client.archive_delete({"archive_id": archive_id, **request})

    def archive_readback(self, archive_id: str, **request: Any) -> Mapping[str, Any]:
        return self._client.archive_readback({"archive_id": archive_id, **request})


__all__ = ["API_BASE", "API_VERSION", "RemoteClient", "RemoteError"]
