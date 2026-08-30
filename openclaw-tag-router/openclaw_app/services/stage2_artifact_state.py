"""Fail-closed Stage-2 artifact registration and readback state machine.

The module owns no transport or persistence integration. Callers provide
server-derived identities and step receipts, making the boundary suitable for
personal Web artifacts and organization Lark artifacts alike.
"""

from __future__ import annotations

import copy
import hashlib
import json
import threading
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any

from common.canonical_digest import normalize_prefixed_digest

from openclaw_app.services.stage2_errors import IDEMPOTENCY_CONFLICT, Stage2CodedError


PERSONAL_MODE = "personal_web/internal"
ORGANIZATION_MODE = "organization_lark/lark"
SCHEMA_VERSION = "stage2.artifact_state.v1"

_SUCCESS = frozenset({"ok", "success", "succeeded", "written", "registered", "confirmed"})
_FORBIDDEN_BROWSER_FIELDS = frozenset(
    {
        "tenantId",
        "tenant_id",
        "bindingId",
        "binding_id",
        "bindingGeneration",
        "binding_generation",
        "authorityMode",
        "authority_mode",
        "remoteRef",
        "remote_ref",
        "credentials",
    }
)


class ArtifactStateError(Stage2CodedError):
    pass


class IdempotencyConflict(ArtifactStateError):
    def __init__(self, message: str = "idempotency key was reused with another request") -> None:
        super().__init__(IDEMPOTENCY_CONFLICT, message)


def _text(value: Any, label: str, maximum: int = 512) -> str:
    if not isinstance(value, str):
        raise ArtifactStateError("invalid_request", f"{label} must be a string")
    normalized = value.strip()
    if not normalized or len(normalized) > maximum or any(ord(char) < 32 for char in normalized):
        raise ArtifactStateError("invalid_request", f"{label} is invalid")
    return normalized


def _optional_text(value: Any, label: str) -> str | None:
    return None if value is None else _text(value, label)


def _digest(value: Any, label: str = "content_digest") -> str:
    normalized = _text(value, label, 80)
    if normalize_prefixed_digest(normalized) is None:
        raise ArtifactStateError("invalid_request", f"{label} must be a sha256 digest")
    return normalized


def _generation(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ArtifactStateError("binding_invalid", "binding_generation must be a positive integer")
    return value


def _lookup(value: Mapping[str, Any], *names: str, default: Any = None) -> Any:
    for name in names:
        if name in value:
            return value[name]
    return default


def _status(value: Any, label: str) -> str:
    return _text(value, label, 64).lower()


@dataclass(frozen=True, slots=True)
class ArtifactRecordRequest:
    tenant_id: str
    authority_mode: str
    idempotency_key: str
    content_digest: str
    write_status: str
    registration_status: str
    readback_status: str
    artifact_ref: str | None = None
    revision: str | None = None
    binding_id: str | None = None
    binding_generation: int | None = None
    remote_ref: str | None = None
    remote_revision: str | None = None
    readback_content_digest: str | None = None
    readback_artifact_ref: str | None = None
    readback_revision: str | None = None
    readback_binding_id: str | None = None
    readback_binding_generation: int | None = None
    readback_remote_ref: str | None = None
    readback_remote_revision: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "tenant_id", _text(self.tenant_id, "tenant_id"))
        if self.authority_mode not in {PERSONAL_MODE, ORGANIZATION_MODE}:
            raise ArtifactStateError("authority_pair_invalid", "authority_mode is not supported")
        object.__setattr__(self, "idempotency_key", _text(self.idempotency_key, "idempotency_key"))
        object.__setattr__(self, "content_digest", _digest(self.content_digest))
        for name in ("write_status", "registration_status", "readback_status"):
            object.__setattr__(self, name, _status(getattr(self, name), name))
        for name in (
            "artifact_ref",
            "revision",
            "binding_id",
            "remote_ref",
            "remote_revision",
            "readback_artifact_ref",
            "readback_revision",
            "readback_binding_id",
            "readback_remote_ref",
            "readback_remote_revision",
        ):
            object.__setattr__(self, name, _optional_text(getattr(self, name), name))
        if self.binding_generation is not None:
            object.__setattr__(self, "binding_generation", _generation(self.binding_generation))
        if self.readback_binding_generation is not None:
            object.__setattr__(
                self,
                "readback_binding_generation",
                _generation(self.readback_binding_generation),
            )
        if self.readback_content_digest is not None:
            object.__setattr__(
                self,
                "readback_content_digest",
                _digest(self.readback_content_digest, "readback_content_digest"),
            )
        if self.authority_mode == PERSONAL_MODE:
            if any(
                value is not None
                for value in (
                    self.binding_id,
                    self.binding_generation,
                    self.remote_ref,
                    self.remote_revision,
                    self.readback_binding_id,
                    self.readback_binding_generation,
                    self.readback_remote_ref,
                    self.readback_remote_revision,
                )
            ):
                raise ArtifactStateError(
                    "personal_remote_authority_forbidden",
                    "personal artifacts cannot carry Binding or remote document identity",
                )
        elif self.binding_id is None or self.binding_generation is None:
            raise ArtifactStateError("binding_required", "organization artifact requires Binding identity")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ArtifactRecordRequest":
        if not isinstance(value, Mapping):
            raise ArtifactStateError("invalid_request", "artifact state request must be an object")
        browser_claims = _lookup(value, "browser_claims", "browserClaims", default={})
        if not isinstance(browser_claims, Mapping):
            raise ArtifactStateError("invalid_request", "browser claims must be an object")
        forbidden = sorted(set(browser_claims).intersection(_FORBIDDEN_BROWSER_FIELDS))
        if forbidden:
            raise ArtifactStateError(
                "authority_override_forbidden",
                "browser authority claims are forbidden: " + ",".join(forbidden),
            )
        return cls(
            tenant_id=_lookup(value, "tenant_id", "tenantId"),
            authority_mode=_lookup(value, "authority_mode", "authorityMode"),
            idempotency_key=_lookup(value, "idempotency_key", "idempotencyKey"),
            content_digest=_lookup(value, "content_digest", "contentDigest"),
            write_status=_lookup(value, "write_status", "writeStatus"),
            registration_status=_lookup(value, "registration_status", "registrationStatus"),
            readback_status=_lookup(value, "readback_status", "readbackStatus"),
            artifact_ref=_lookup(value, "artifact_ref", "artifactRef"),
            revision=_lookup(value, "revision"),
            binding_id=_lookup(value, "binding_id", "bindingId"),
            binding_generation=_lookup(value, "binding_generation", "bindingGeneration"),
            remote_ref=_lookup(value, "remote_ref", "remoteRef"),
            remote_revision=_lookup(value, "remote_revision", "remoteRevision"),
            readback_content_digest=_lookup(value, "readback_content_digest", "readbackContentDigest"),
            readback_artifact_ref=_lookup(value, "readback_artifact_ref", "readbackArtifactRef"),
            readback_revision=_lookup(value, "readback_revision", "readbackRevision"),
            readback_binding_id=_lookup(value, "readback_binding_id", "readbackBindingId"),
            readback_binding_generation=_lookup(
                value, "readback_binding_generation", "readbackBindingGeneration"
            ),
            readback_remote_ref=_lookup(value, "readback_remote_ref", "readbackRemoteRef"),
            readback_remote_revision=_lookup(value, "readback_remote_revision", "readbackRemoteRevision"),
        )


@dataclass(frozen=True, slots=True)
class ArtifactStateResult:
    status: str
    publishable: bool
    ready_for_publish: bool
    error_code: str | None
    receipt: Mapping[str, Any]
    replayed: bool = False

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["receipt"] = copy.deepcopy(dict(self.receipt))
        return value


@dataclass(frozen=True, slots=True)
class _Stored:
    fingerprint: str
    result: ArtifactStateResult


class ArtifactStateMachine:
    """Thread-safe artifact transition boundary with deterministic replay."""

    def __init__(self) -> None:
        self._records: dict[str, _Stored] = {}
        self._lock = threading.RLock()

    def record(self, value: ArtifactRecordRequest | Mapping[str, Any]) -> ArtifactStateResult:
        request = value if isinstance(value, ArtifactRecordRequest) else ArtifactRecordRequest.from_mapping(value)
        fingerprint = self._fingerprint(request)
        storage_key = f"{request.tenant_id}:{request.idempotency_key}"
        with self._lock:
            existing = self._records.get(storage_key)
            if existing is not None:
                if existing.fingerprint != fingerprint:
                    raise IdempotencyConflict()
                return ArtifactStateResult(
                    status=existing.result.status,
                    publishable=existing.result.publishable,
                    ready_for_publish=existing.result.ready_for_publish,
                    error_code=existing.result.error_code,
                    receipt=copy.deepcopy(dict(existing.result.receipt)),
                    replayed=True,
                )
            result = self._evaluate(request)
            self._records[storage_key] = _Stored(fingerprint, copy.deepcopy(result))
            return result

    register = record
    verify_readback = record

    @staticmethod
    def _fingerprint(request: ArtifactRecordRequest) -> str:
        encoded = json.dumps(asdict(request), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    @staticmethod
    def _evaluate(request: ArtifactRecordRequest) -> ArtifactStateResult:
        receipt = {
            "schemaVersion": SCHEMA_VERSION,
            "tenantId": request.tenant_id,
            "authorityMode": request.authority_mode,
            "idempotencyKey": request.idempotency_key,
            "contentDigest": request.content_digest,
            "artifactRef": request.artifact_ref,
            "revision": request.revision,
            "bindingId": request.binding_id,
            "bindingGeneration": request.binding_generation,
            "remoteRef": request.remote_ref,
            "remoteRevision": request.remote_revision,
            "writeStatus": request.write_status,
            "registrationStatus": request.registration_status,
            "readbackStatus": request.readback_status,
        }
        error_code: str | None = None
        if request.write_status not in _SUCCESS:
            error_code = "write_failed"
        elif request.artifact_ref is None or request.revision is None:
            error_code = "registration_failed"
        elif request.registration_status not in _SUCCESS:
            error_code = "registration_failed"
        elif request.authority_mode == ORGANIZATION_MODE and (
            request.remote_ref is None or request.remote_revision is None
        ):
            error_code = "external_write_needs_attention"
        elif request.readback_status not in _SUCCESS:
            error_code = "readback_incomplete"
        elif request.readback_content_digest != request.content_digest:
            error_code = "readback_incomplete"
        elif request.readback_artifact_ref != request.artifact_ref:
            error_code = "readback_incomplete"
        elif request.readback_revision != request.revision:
            error_code = "readback_incomplete"
        elif request.authority_mode == ORGANIZATION_MODE and (
            request.readback_binding_id != request.binding_id
            or request.readback_binding_generation != request.binding_generation
            or request.readback_remote_ref != request.remote_ref
            or request.readback_remote_revision != request.remote_revision
        ):
            error_code = "readback_incomplete"

        ready = error_code is None
        receipt["receiptDigest"] = "sha256:" + hashlib.sha256(
            json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return ArtifactStateResult(
            status="readback_verified" if ready else "needs_attention",
            # A verified artifact is eligible for a later release decision;
            # this boundary never publishes by itself.
            publishable=False,
            ready_for_publish=ready,
            error_code=error_code,
            receipt=receipt,
        )


__all__ = [
    "ArtifactRecordRequest",
    "ArtifactStateError",
    "ArtifactStateMachine",
    "ArtifactStateResult",
    "IdempotencyConflict",
    "ORGANIZATION_MODE",
    "PERSONAL_MODE",
    "SCHEMA_VERSION",
]
