"""Organization-only Stage-2 document and readback boundary.

All transport work is injected through ``ExternalDocumentWriter``. The module
never obtains credentials or chooses a tenant/Binding on behalf of a caller.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import threading
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from openclaw_app.services.stage2_external_document import (
    BindingIdentity,
    ExternalDocumentAdapter,
    ExternalDocumentError,
    ExternalDocumentWriter,
    OrganizationWriteRequest,
)


SCHEMA_VERSION = "stage2.organization_pipeline.v1"
ORGANIZATION_MODE = "organization_lark/lark"
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


class OrganizationPipelineError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


class IdempotencyConflict(OrganizationPipelineError):
    def __init__(self) -> None:
        super().__init__("idempotency_conflict", "idempotency key was reused with another request")


def _text(value: Any, label: str, maximum: int = 512) -> str:
    if not isinstance(value, str):
        raise OrganizationPipelineError("invalid_request", f"{label} must be a string")
    normalized = value.strip()
    if not normalized or len(normalized) > maximum or any(ord(char) < 32 for char in normalized):
        raise OrganizationPipelineError("invalid_request", f"{label} is invalid")
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


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _content_digest(value: Any) -> str:
    normalized = _text(value, "content_digest", 80)
    if _DIGEST_RE.fullmatch(normalized) is None:
        raise OrganizationPipelineError("invalid_request", "content_digest must be a sha256 digest")
    return normalized


def _assert_org_context(context: Any, binding: BindingIdentity) -> str:
    workspace = _lookup(context, "workspace_mode", "workspaceMode", "workspace")
    authority = _lookup(context, "body_authority", "bodyAuthority", "authority")
    mode = _lookup(context, "authority_mode", "authorityMode") or f"{workspace}/{authority}"
    if mode != ORGANIZATION_MODE:
        raise OrganizationPipelineError("organization_context_required", "organization_lark/lark context is required")
    tenant_id = _text(_lookup(context, "tenant_id", "tenantId"), "tenant_id")
    if tenant_id != binding.tenant_id:
        raise OrganizationPipelineError("binding_tenant_mismatch", "Binding tenant does not match context")
    return tenant_id


def _assert_browser_claims(claims: Mapping[str, Any] | None) -> None:
    if claims is None:
        return
    if not isinstance(claims, Mapping):
        raise OrganizationPipelineError("invalid_request", "browser claims must be an object")
    forbidden = {
        "tenantId", "tenant_id", "bindingId", "binding_id", "bindingGeneration", "binding_generation",
        "remoteRef", "remote_ref", "credentials", "larkAppId", "larkSpaceId",
    }.intersection(claims)
    if forbidden:
        raise OrganizationPipelineError("authority_override_forbidden", "browser claims cannot choose organization identity")


@dataclass(frozen=True, slots=True)
class _Stored:
    fingerprint: str
    result: Mapping[str, Any]


class OrganizationContentPipeline:
    def __init__(self, *, document_writer: ExternalDocumentWriter | None = None) -> None:
        self._document_writer = document_writer or ExternalDocumentWriter()
        self._artifacts: dict[str, dict[str, Any]] = {}
        self._replays: dict[str, _Stored] = {}
        self._lock = threading.RLock()

    def build_scope(
        self,
        context: Any,
        binding: BindingIdentity,
        sources: Iterable[Mapping[str, Any]],
        *,
        browser_claims: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        _assert_browser_claims(browser_claims)
        if not isinstance(binding, BindingIdentity):
            raise OrganizationPipelineError("binding_required", "active Binding identity is required")
        if binding.status != "active":
            raise OrganizationPipelineError("binding_inactive", "organization Binding is inactive")
        tenant_id = _assert_org_context(context, binding)
        normalized: list[dict[str, Any]] = []
        for raw in sources:
            if not isinstance(raw, Mapping):
                raise OrganizationPipelineError("invalid_source", "organization source must be an object")
            source_tenant = _text(_lookup(raw, "tenant_id", "tenantId"), "source tenant")
            if source_tenant != tenant_id:
                raise OrganizationPipelineError("source_tenant_mismatch", "organization source belongs to another tenant")
            if _lookup(raw, "workspace_mode", "workspaceMode", "workspace") != "organization_lark":
                raise OrganizationPipelineError("personal_source_forbidden", "organization scope cannot read personal sources")
            if _lookup(raw, "body_authority", "bodyAuthority", "authority") != "lark":
                raise OrganizationPipelineError("source_authority_mismatch", "organization source must use Lark authority")
            source_binding_id = _lookup(raw, "binding_id", "bindingId")
            source_generation = _lookup(raw, "binding_generation", "bindingGeneration")
            if source_binding_id != binding.binding_id or source_generation != binding.binding_generation:
                raise OrganizationPipelineError("binding_generation_mismatch", "source Binding does not match active Binding")
            source_id = _text(_lookup(raw, "source_id", "sourceId", "id"), "source_id")
            source_kind = _text(_lookup(raw, "source_kind", "sourceKind", "kind"), "source_kind", 160)
            payload = _lookup(raw, "payload", "data", default={})
            if not isinstance(payload, Mapping):
                raise OrganizationPipelineError("invalid_source", "organization source payload must be an object")
            row = {
                "sourceId": source_id,
                "sourceKind": source_kind,
                "tenantId": tenant_id,
                "bindingId": binding.binding_id,
                "bindingGeneration": binding.binding_generation,
                "payload": copy.deepcopy(dict(payload)),
            }
            row["sourceDigest"] = _digest(row)
            normalized.append(row)
        normalized.sort(key=lambda item: (item["sourceKind"], item["sourceId"]))
        scope = {
            "schemaVersion": SCHEMA_VERSION,
            "tenantId": tenant_id,
            "authorityMode": ORGANIZATION_MODE,
            "bindingId": binding.binding_id,
            "bindingGeneration": binding.binding_generation,
            "sources": normalized,
        }
        scope["scopeDigest"] = _digest(scope)
        return scope

    def write_document(
        self,
        context: Any,
        scope: Mapping[str, Any],
        *,
        title: str,
        body: str,
        idempotency_key: str,
        binding: BindingIdentity,
        adapter: ExternalDocumentAdapter,
        credential_generation: str,
    ) -> dict[str, Any]:
        tenant_id = _assert_org_context(context, binding)
        if scope.get("tenantId") != tenant_id or scope.get("bindingId") != binding.binding_id or scope.get("bindingGeneration") != binding.binding_generation:
            raise OrganizationPipelineError("scope_binding_mismatch", "organization scope does not match active Binding")
        content = {"title": _text(title, "title", 240), "body": _text(body, "body"), "format": "markdown"}
        digest = _digest(content)
        key = _text(idempotency_key, "idempotency_key", 256)
        fingerprint = _digest({"tenantId": tenant_id, "bindingId": binding.binding_id, "bindingGeneration": binding.binding_generation, "digest": digest})
        replay_key = f"write:{tenant_id}:{binding.binding_id}:{key}"
        with self._lock:
            previous = self._replays.get(replay_key)
            if previous is not None:
                if previous.fingerprint != fingerprint:
                    raise IdempotencyConflict()
                replay = copy.deepcopy(dict(previous.result))
                replay["replayed"] = True
                return replay
            request = OrganizationWriteRequest(binding=binding, idempotency_key=key, content_digest=digest)
            try:
                external = self._document_writer.write(request, adapter)
            except ExternalDocumentError as exc:
                raise OrganizationPipelineError(exc.code, exc.message) from exc
            if external.status != "written" or not external.remote_ref or not external.remote_revision:
                result = {
                    "schemaVersion": SCHEMA_VERSION,
                    "status": "needs_attention",
                    "publishable": False,
                    "tenantId": tenant_id,
                    "bindingId": binding.binding_id,
                    "bindingGeneration": binding.binding_generation,
                    "remoteRef": external.remote_ref,
                    "remoteRevision": external.remote_revision,
                    "errorCode": external.error_code or "external_write_needs_attention",
                }
                self._replays[replay_key] = _Stored(fingerprint, copy.deepcopy(result))
                return result
            artifact_ref = "org-artifact-" + digest[7:31]
            artifact = {
                "schemaVersion": SCHEMA_VERSION,
                "status": "registered",
                "publishable": False,
                "editable": False,
                "tenantId": tenant_id,
                "bindingId": binding.binding_id,
                "bindingGeneration": binding.binding_generation,
                "credentialGeneration": _text(credential_generation, "credential_generation", 160),
                "artifactRef": artifact_ref,
                "remoteRef": external.remote_ref,
                "remoteRevision": external.remote_revision,
                "contentDigest": digest,
                "scopeDigest": scope["scopeDigest"],
                "mirror": None,
                "replayed": False,
            }
            self._artifacts[artifact_ref] = copy.deepcopy(artifact)
            self._replays[replay_key] = _Stored(fingerprint, copy.deepcopy(artifact))
            return artifact

    def readback_mirror(
        self,
        artifact_ref: str,
        *,
        tenant_id: str,
        binding: BindingIdentity,
        remote_ref: str,
        remote_revision: str,
        content_digest: str,
        trusted_open_url: str,
    ) -> dict[str, Any]:
        if not trusted_open_url.startswith("https://") or any(char.isspace() for char in trusted_open_url):
            raise OrganizationPipelineError("untrusted_remote_url", "only an HTTPS trusted open URL is allowed")
        with self._lock:
            artifact = self._artifacts.get(_text(artifact_ref, "artifact_ref"))
            if artifact is None:
                raise OrganizationPipelineError("artifact_not_found", "organization artifact does not exist")
            if artifact["tenantId"] != tenant_id or artifact["bindingId"] != binding.binding_id or artifact["bindingGeneration"] != binding.binding_generation:
                raise OrganizationPipelineError("binding_mismatch", "readback Binding does not match artifact")
            if remote_ref != artifact["remoteRef"]:
                raise OrganizationPipelineError("remote_ref_mismatch", "readback document does not match artifact")
            if remote_revision != artifact["remoteRevision"]:
                raise OrganizationPipelineError("remote_revision_mismatch", "readback revision does not match artifact")
            if content_digest != artifact["contentDigest"]:
                raise OrganizationPipelineError("content_digest_mismatch", "readback content does not match artifact")
            mirror = {
                "schemaVersion": SCHEMA_VERSION,
                "artifactRef": artifact["artifactRef"],
                "tenantId": tenant_id,
                "bindingId": binding.binding_id,
                "bindingGeneration": binding.binding_generation,
                "remoteRef": remote_ref,
                "remoteRevision": remote_revision,
                "contentDigest": content_digest,
                "trustedOpenUrl": trusted_open_url,
                "editable": False,
                "readOnly": True,
            }
            mirror["mirrorDigest"] = _digest(mirror)
            artifact["mirror"] = copy.deepcopy(mirror)
            artifact["status"] = "readback_verified"
            return mirror

    def record_remote_edit_and_readback(
        self,
        artifact_ref: str,
        *,
        tenant_id: str,
        binding: BindingIdentity,
        remote_ref: str,
        remote_revision: str,
        content_digest: str,
        trusted_open_url: str,
    ) -> dict[str, Any]:
        with self._lock:
            artifact = self._artifacts.get(_text(artifact_ref, "artifact_ref"))
            if artifact is None:
                raise OrganizationPipelineError("artifact_not_found", "organization artifact does not exist")
            if (
                artifact["tenantId"] != tenant_id
                or artifact["bindingId"] != binding.binding_id
                or artifact["bindingGeneration"] != binding.binding_generation
            ):
                raise OrganizationPipelineError("binding_mismatch", "readback Binding does not match artifact")
            if remote_ref != artifact["remoteRef"]:
                raise OrganizationPipelineError("remote_ref_mismatch", "readback document does not match artifact")
            normalized_revision = _text(remote_revision, "remote_revision", 160)
            normalized_digest = _content_digest(content_digest)
            if normalized_revision == artifact["remoteRevision"]:
                raise OrganizationPipelineError("remote_revision_unchanged", "remote edit must produce a new revision")
            artifact["remoteRevision"] = normalized_revision
            artifact["contentDigest"] = normalized_digest
        return self.readback_mirror(
            artifact_ref,
            tenant_id=tenant_id,
            binding=binding,
            remote_ref=remote_ref,
            remote_revision=remote_revision,
            content_digest=content_digest,
            trusted_open_url=trusted_open_url,
        )


__all__ = [
    "BindingIdentity",
    "IdempotencyConflict",
    "OrganizationContentPipeline",
    "OrganizationPipelineError",
    "ORGANIZATION_MODE",
    "SCHEMA_VERSION",
]
