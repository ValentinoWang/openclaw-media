"""Fail-closed external document write/readback boundary for Stage 2.

The adapter is deliberately transport-neutral.  A later integration layer may
provide a Feishu or database implementation, but this module only accepts
server-owned Binding facts and verifies the returned identity before declaring
the document write complete.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import threading
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any, Protocol


_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_SUCCESS_STATES = frozenset({"ok", "success", "succeeded", "written", "created"})


class ExternalDocumentError(RuntimeError):
    """Stable fail-closed error raised before an external adapter call."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


class IdempotencyConflict(ExternalDocumentError):
    def __init__(self) -> None:
        super().__init__("idempotency_conflict", "idempotency key was reused with a different request")


def _required_text(value: Any, label: str, maximum: int = 256) -> str:
    if not isinstance(value, str):
        raise ExternalDocumentError("invalid_request", f"{label} must be a string")
    normalized = value.strip()
    if not normalized or len(normalized) > maximum or any(ord(char) < 32 for char in normalized):
        raise ExternalDocumentError("invalid_request", f"{label} is invalid")
    return normalized


def _positive_generation(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ExternalDocumentError("binding_invalid", "binding_generation must be a positive integer")
    return value


def _digest(value: Any, label: str = "content_digest") -> str:
    normalized = _required_text(value, label, 80)
    if _DIGEST_RE.fullmatch(normalized) is None:
        raise ExternalDocumentError("invalid_request", f"{label} must be a sha256 digest")
    return normalized


def _lookup(value: Any, *names: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        for name in names:
            if name in value:
                return value[name]
        return default
    for name in names:
        if hasattr(value, name):
            return getattr(value, name)
    return default


@dataclass(frozen=True, slots=True)
class BindingIdentity:
    """Server-owned organization Binding identity; no credential material."""

    tenant_id: str
    binding_id: str
    binding_generation: int
    status: str = "active"

    def __post_init__(self) -> None:
        object.__setattr__(self, "tenant_id", _required_text(self.tenant_id, "tenant_id"))
        object.__setattr__(self, "binding_id", _required_text(self.binding_id, "binding_id"))
        object.__setattr__(self, "binding_generation", _positive_generation(self.binding_generation))
        object.__setattr__(self, "status", _required_text(self.status, "binding_status").lower())


@dataclass(frozen=True, slots=True)
class OrganizationWriteRequest:
    binding: BindingIdentity | None
    idempotency_key: str
    content_digest: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "idempotency_key", _required_text(self.idempotency_key, "idempotency_key"))
        object.__setattr__(self, "content_digest", _digest(self.content_digest))


@dataclass(frozen=True, slots=True)
class ExternalWriteOutcome:
    status: str
    remote_ref: str | None
    remote_revision: str | None
    tenant_id: str | None
    binding_id: str | None
    binding_generation: int | None
    content_digest: str | None
    error_code: str | None = None


@dataclass(frozen=True, slots=True)
class ExternalReadbackOutcome:
    status: str
    remote_ref: str | None
    remote_revision: str | None
    tenant_id: str | None
    binding_id: str | None
    binding_generation: int | None
    content_digest: str | None
    error_code: str | None = None


@dataclass(frozen=True, slots=True)
class ExternalDocumentWriteResult:
    status: str
    publishable: bool
    idempotency_key: str
    content_digest: str
    remote_ref: str | None
    remote_revision: str | None
    error_code: str | None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class ExternalDocumentAdapter(Protocol):
    def write(self, request: OrganizationWriteRequest) -> ExternalWriteOutcome | Mapping[str, Any]: ...

    def readback(
        self,
        request: OrganizationWriteRequest,
        write: ExternalWriteOutcome,
    ) -> ExternalReadbackOutcome | Mapping[str, Any]: ...


@dataclass(frozen=True, slots=True)
class _StoredReceipt:
    fingerprint: str
    result: ExternalDocumentWriteResult


class InMemoryWriteReceiptStore:
    """Thread-safe idempotency store; production persistence remains injected."""

    def __init__(self) -> None:
        self._records: dict[str, _StoredReceipt] = {}
        self._lock = threading.RLock()

    def get(self, key: str) -> _StoredReceipt | None:
        with self._lock:
            value = self._records.get(key)
            return copy.deepcopy(value) if value is not None else None

    def put(self, key: str, fingerprint: str, result: ExternalDocumentWriteResult) -> None:
        with self._lock:
            existing = self._records.get(key)
            if existing is not None and existing.fingerprint != fingerprint:
                raise IdempotencyConflict()
            if existing is None:
                self._records[key] = _StoredReceipt(fingerprint, copy.deepcopy(result))


def _fingerprint(request: OrganizationWriteRequest) -> str:
    payload = {
        "binding": asdict(request.binding) if request.binding is not None else None,
        "idempotency_key": request.idempotency_key,
        "content_digest": request.content_digest,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _write_outcome(value: ExternalWriteOutcome | Mapping[str, Any]) -> ExternalWriteOutcome:
    if isinstance(value, ExternalWriteOutcome):
        return value
    if not isinstance(value, Mapping):
        raise ExternalDocumentError("write_failed", "external adapter returned an invalid write outcome")
    return ExternalWriteOutcome(
        status=str(_lookup(value, "status", default="")),
        remote_ref=_lookup(value, "remote_ref", "remoteRef"),
        remote_revision=_lookup(value, "remote_revision", "remoteRevision"),
        tenant_id=_lookup(value, "tenant_id", "tenantId"),
        binding_id=_lookup(value, "binding_id", "bindingId"),
        binding_generation=_lookup(value, "binding_generation", "bindingGeneration"),
        content_digest=_lookup(value, "content_digest", "contentDigest"),
        error_code=_lookup(value, "error_code", "errorCode"),
    )


def _readback_outcome(value: ExternalReadbackOutcome | Mapping[str, Any]) -> ExternalReadbackOutcome:
    if isinstance(value, ExternalReadbackOutcome):
        return value
    if not isinstance(value, Mapping):
        raise ExternalDocumentError("readback_incomplete", "external adapter returned an invalid readback")
    return ExternalReadbackOutcome(
        status=str(_lookup(value, "status", default="")),
        remote_ref=_lookup(value, "remote_ref", "remoteRef"),
        remote_revision=_lookup(value, "remote_revision", "remoteRevision"),
        tenant_id=_lookup(value, "tenant_id", "tenantId"),
        binding_id=_lookup(value, "binding_id", "bindingId"),
        binding_generation=_lookup(value, "binding_generation", "bindingGeneration"),
        content_digest=_lookup(value, "content_digest", "contentDigest"),
        error_code=_lookup(value, "error_code", "errorCode"),
    )


class ExternalDocumentWriter:
    """Coordinate an injected write plus readback without external knowledge."""

    def __init__(self, store: InMemoryWriteReceiptStore | None = None) -> None:
        self._store = store or InMemoryWriteReceiptStore()
        self._lock = threading.RLock()

    def write(
        self,
        request: OrganizationWriteRequest,
        adapter: ExternalDocumentAdapter,
    ) -> ExternalDocumentWriteResult:
        self._validate_request(request)
        fingerprint = _fingerprint(request)
        with self._lock:
            stored = self._store.get(request.idempotency_key)
            if stored is not None:
                if stored.fingerprint != fingerprint:
                    raise IdempotencyConflict()
                return stored.result

            try:
                write = _write_outcome(adapter.write(request))
            except ExternalDocumentError as exc:
                result = self._attention(request, None, None, exc.code)
                self._store.put(request.idempotency_key, fingerprint, result)
                return result
            except Exception:
                result = self._attention(request, None, None, "write_failed")
                self._store.put(request.idempotency_key, fingerprint, result)
                return result

            if not self._write_matches(request, write):
                result = self._attention(
                    request,
                    write.remote_ref,
                    write.remote_revision,
                    write.error_code or "external_write_needs_attention",
                )
                self._store.put(request.idempotency_key, fingerprint, result)
                return result

            try:
                readback = _readback_outcome(adapter.readback(request, write))
            except Exception:
                result = self._attention(request, write.remote_ref, write.remote_revision, "readback_incomplete")
                self._store.put(request.idempotency_key, fingerprint, result)
                return result

            if not self._readback_matches(request, write, readback):
                result = self._attention(request, write.remote_ref, write.remote_revision, "readback_incomplete")
            else:
                result = ExternalDocumentWriteResult(
                    status="written",
                    publishable=True,
                    idempotency_key=request.idempotency_key,
                    content_digest=request.content_digest,
                    remote_ref=write.remote_ref,
                    remote_revision=write.remote_revision,
                    error_code=None,
                )
            self._store.put(request.idempotency_key, fingerprint, result)
            return result

    @staticmethod
    def _validate_request(request: OrganizationWriteRequest) -> None:
        if not isinstance(request, OrganizationWriteRequest):
            raise ExternalDocumentError("invalid_request", "organization write request is required")
        binding = request.binding
        if binding is None:
            raise ExternalDocumentError("binding_required", "organization Binding identity is required")
        if binding.status != "active":
            raise ExternalDocumentError("binding_inactive", "organization Binding is not active")

    @staticmethod
    def _write_matches(request: OrganizationWriteRequest, write: ExternalWriteOutcome) -> bool:
        binding = request.binding
        return (
            write.status.lower() in _SUCCESS_STATES
            and bool(write.remote_ref)
            and bool(write.remote_revision)
            and write.tenant_id == binding.tenant_id
            and write.binding_id == binding.binding_id
            and write.binding_generation == binding.binding_generation
            and write.content_digest == request.content_digest
        )

    @staticmethod
    def _readback_matches(
        request: OrganizationWriteRequest,
        write: ExternalWriteOutcome,
        readback: ExternalReadbackOutcome,
    ) -> bool:
        binding = request.binding
        return (
            readback.status.lower() in {"ok", "success", "succeeded", "confirmed", "read"}
            and readback.remote_ref == write.remote_ref
            and readback.remote_revision == write.remote_revision
            and readback.tenant_id == binding.tenant_id
            and readback.binding_id == binding.binding_id
            and readback.binding_generation == binding.binding_generation
            and readback.content_digest == request.content_digest
        )

    @staticmethod
    def _attention(
        request: OrganizationWriteRequest,
        remote_ref: str | None,
        remote_revision: str | None,
        error_code: str,
    ) -> ExternalDocumentWriteResult:
        return ExternalDocumentWriteResult(
            status="needs_attention",
            publishable=False,
            idempotency_key=request.idempotency_key,
            content_digest=request.content_digest,
            remote_ref=remote_ref,
            remote_revision=remote_revision,
            error_code=error_code,
        )


__all__ = [
    "BindingIdentity",
    "ExternalDocumentAdapter",
    "ExternalDocumentError",
    "ExternalDocumentWriteResult",
    "ExternalReadbackOutcome",
    "ExternalWriteOutcome",
    "ExternalDocumentWriter",
    "IdempotencyConflict",
    "InMemoryWriteReceiptStore",
    "OrganizationWriteRequest",
]
