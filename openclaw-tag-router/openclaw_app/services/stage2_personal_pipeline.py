"""Personal-only Stage-2 content pipeline boundary.

The pipeline keeps personal source scope, briefs, revisions, and export packages
inside an injected process boundary. It never performs external publishing or
remote document writes.
"""

from __future__ import annotations

import copy
import hashlib
import json
import threading
from collections.abc import Iterable, Mapping
from typing import Any, Protocol

from openclaw_app.services.stage2_personal_store import (
    InMemoryPersonalContentStore,
    PersonalContentStore,
    SQLitePersonalContentStore,
    SqlitePersonalContentStore,
    _StoreConflict,
)


SCHEMA_VERSION = "stage2.personal_pipeline.v1"
PERSONAL_MODE = "personal_web/internal"
_SUCCESS = frozenset({"ok", "success", "succeeded", "written", "registered", "confirmed"})
_FORBIDDEN_BROWSER_FIELDS = frozenset(
    {
        "tenantId",
        "tenant_id",
        "bindingId",
        "binding_id",
        "workspace",
        "authority",
        "bodyAuthority",
        "body_authority",
        "role",
    }
)


class PersonalPipelineError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


class RevisionConflict(PersonalPipelineError):
    def __init__(self) -> None:
        super().__init__("revision_conflict", "baseline revision does not match the current revision")


class IdempotencyConflict(PersonalPipelineError):
    def __init__(self) -> None:
        super().__init__("idempotency_conflict", "idempotency key was reused with another request")


class PersonalWriter(Protocol):
    def write(
        self,
        context: Any,
        content: Mapping[str, Any],
        capability_id: str,
        idempotency_key: str,
        context_receipt: Any | None = None,
    ) -> Mapping[str, Any]: ...


def _text(value: Any, label: str, maximum: int = 1000000) -> str:
    if not isinstance(value, str):
        raise PersonalPipelineError("invalid_request", f"{label} must be a string")
    normalized = value.strip()
    if not normalized or len(normalized) > maximum or any(ord(char) < 9 for char in normalized):
        raise PersonalPipelineError("invalid_request", f"{label} is invalid")
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


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _context_mode(context: Any) -> str:
    mode = _lookup(context, "authority_mode", "authorityMode")
    if mode is None:
        workspace = _lookup(context, "workspace_mode", "workspace", "workspaceMode")
        authority = _lookup(context, "body_authority", "authority", "bodyAuthority")
        mode = f"{workspace}/{authority}"
    return str(mode)


def _assert_personal_context(context: Any) -> tuple[str, str]:
    if _context_mode(context) != PERSONAL_MODE:
        raise PersonalPipelineError("personal_context_required", "personal_web/internal context is required")
    if _lookup(context, "binding_id", "bindingId", "active_binding", "activeBinding") is not None:
        raise PersonalPipelineError("personal_binding_forbidden", "personal context cannot carry Binding identity")
    tenant_id = _text(_lookup(context, "tenant_id", "tenantId", "tenant_scope"), "tenant_id", 256)
    capability_id = _text(_lookup(context, "capability_id", "capabilityId", default="personal_content_writer"), "capability_id", 160)
    return tenant_id, capability_id


def _reject_browser_claims(claims: Mapping[str, Any] | None) -> None:
    if claims is None:
        return
    if not isinstance(claims, Mapping):
        raise PersonalPipelineError("invalid_request", "browser claims must be an object")
    forbidden = sorted(set(claims).intersection(_FORBIDDEN_BROWSER_FIELDS))
    if forbidden:
        raise PersonalPipelineError(
            "authority_override_forbidden",
            "browser authority claims are forbidden: " + ",".join(forbidden),
        )


class PersonalContentPipeline:
    def __init__(self, *, store: PersonalContentStore | None = None) -> None:
        self.store = store or InMemoryPersonalContentStore()
        self._lock = threading.RLock()

    def _record_failure(self, *, replay_key: str, fingerprint: str, code: str, message: str) -> None:
        try:
            self.store.record_failure(
                replay_key=replay_key,
                fingerprint=fingerprint,
                failure={"status": "failed", "errorCode": code, "errorMessage": message},
            )
        except Exception:
            # The original pipeline error remains the user-visible outcome. A
            # storage failure must not turn a known failure into a false success.
            return

    def build_scope(
        self,
        context: Any,
        sources: Iterable[Mapping[str, Any]],
        *,
        browser_claims: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        _reject_browser_claims(browser_claims)
        tenant_id, capability_id = _assert_personal_context(context)
        normalized: list[dict[str, Any]] = []
        for raw in sources:
            if not isinstance(raw, Mapping):
                raise PersonalPipelineError("invalid_source", "personal source must be an object")
            source_tenant = _text(_lookup(raw, "tenant_id", "tenantId"), "source tenant", 256)
            if source_tenant != tenant_id:
                raise PersonalPipelineError("source_tenant_mismatch", "personal source belongs to another tenant")
            workspace = _lookup(raw, "workspace_mode", "workspaceMode", "workspace")
            authority = _lookup(raw, "body_authority", "bodyAuthority", "authority")
            if workspace != "personal_web" or authority != "internal":
                raise PersonalPipelineError("organization_source_forbidden", "personal scope cannot read organization sources")
            if _lookup(raw, "binding_id", "bindingId", "binding") is not None:
                raise PersonalPipelineError("personal_binding_forbidden", "personal source cannot carry Binding identity")
            source_id = _text(_lookup(raw, "source_id", "sourceId", "id"), "source_id", 256)
            source_kind = _text(_lookup(raw, "source_kind", "sourceKind", "kind"), "source_kind", 160)
            revision = _text(str(_lookup(raw, "revision", default="1")), "revision", 160)
            payload = _lookup(raw, "payload", "data", default={})
            if not isinstance(payload, Mapping):
                raise PersonalPipelineError("invalid_source", "personal source payload must be an object")
            normalized.append(
                {
                    "sourceId": source_id,
                    "sourceKind": source_kind,
                    "revision": revision,
                    "payload": copy.deepcopy(dict(payload)),
                    "sourceDigest": _digest(
                        {
                            "tenantId": tenant_id,
                            "sourceId": source_id,
                            "sourceKind": source_kind,
                            "revision": revision,
                            "payload": payload,
                        }
                    ),
                }
            )
        normalized.sort(key=lambda item: (item["sourceKind"], item["sourceId"], item["revision"]))
        scope = {
            "schemaVersion": SCHEMA_VERSION,
            "tenantId": tenant_id,
            "authorityMode": PERSONAL_MODE,
            "capabilityId": capability_id,
            "sources": normalized,
        }
        scope["scopeDigest"] = _digest(scope)
        return scope

    @staticmethod
    def build_research_brief(scope: Mapping[str, Any]) -> dict[str, Any]:
        if scope.get("authorityMode") != PERSONAL_MODE:
            raise PersonalPipelineError("personal_scope_required", "personal scope is required")
        sources = scope.get("sources")
        if not isinstance(sources, list):
            raise PersonalPipelineError("invalid_scope", "personal source list is missing")
        citations = [
            {
                "sourceId": item["sourceId"],
                "sourceKind": item["sourceKind"],
                "sourceDigest": item["sourceDigest"],
            }
            for item in sources
        ]
        brief = {
            "schemaVersion": SCHEMA_VERSION,
            "kind": "personal_research_brief",
            "tenantId": scope["tenantId"],
            "scopeDigest": scope["scopeDigest"],
            "citations": citations,
        }
        brief["briefDigest"] = _digest(brief)
        return brief

    @staticmethod
    def build_decision_brief(
        scope: Mapping[str, Any],
        *,
        topic: str,
        target: str,
        tradeoffs: Iterable[str],
        risks: Iterable[str],
        confirmed_by: str | None,
        confirmation_ref: str | None,
    ) -> dict[str, Any]:
        if not confirmed_by or not confirmation_ref:
            raise PersonalPipelineError("human_confirmation_required", "decision brief requires human confirmation")
        brief = {
            "schemaVersion": SCHEMA_VERSION,
            "kind": "personal_decision_brief",
            "tenantId": scope["tenantId"],
            "scopeDigest": scope["scopeDigest"],
            "topic": _text(topic, "topic", 500),
            "target": _text(target, "target", 500),
            "tradeoffs": [_text(item, "tradeoff", 1000) for item in tradeoffs],
            "risks": [_text(item, "risk", 1000) for item in risks],
            "confirmedBy": _text(confirmed_by, "confirmed_by", 256),
            "confirmationRef": _text(confirmation_ref, "confirmation_ref", 256),
        }
        brief["briefDigest"] = _digest(brief)
        return brief

    @staticmethod
    def build_context_bundle(
        scope: Mapping[str, Any],
        research: Mapping[str, Any],
        decision: Mapping[str, Any],
        *,
        platform_constraints: Mapping[str, Any],
    ) -> dict[str, Any]:
        tenant_id = scope.get("tenantId")
        if research.get("tenantId") != tenant_id or decision.get("tenantId") != tenant_id:
            raise PersonalPipelineError("context_tenant_mismatch", "brief tenant identity does not match scope")
        if research.get("scopeDigest") != scope.get("scopeDigest") or decision.get("scopeDigest") != scope.get("scopeDigest"):
            raise PersonalPipelineError("context_receipt_mismatch", "brief scope receipt is stale")
        bundle = {
            "schemaVersion": SCHEMA_VERSION,
            "tenantId": tenant_id,
            "authorityMode": PERSONAL_MODE,
            "scopeDigest": scope["scopeDigest"],
            "researchBriefDigest": research["briefDigest"],
            "decisionBriefDigest": decision["briefDigest"],
            "platformConstraints": copy.deepcopy(dict(platform_constraints)),
        }
        bundle["contextBundleDigest"] = _digest(bundle)
        return bundle

    def create_artifact(
        self,
        context: Any,
        context_bundle: Mapping[str, Any],
        *,
        title: str,
        body: str,
        idempotency_key: str,
        writer: PersonalWriter,
        context_receipt: Any | None = None,
    ) -> dict[str, Any]:
        tenant_id, capability_id = _assert_personal_context(context)
        if context_bundle.get("tenantId") != tenant_id or context_bundle.get("authorityMode") != PERSONAL_MODE:
            raise PersonalPipelineError("context_tenant_mismatch", "personal context bundle does not match context")
        key = _text(idempotency_key, "idempotency_key", 256)
        normalized_content = {
            "title": _text(title, "title", 240),
            "body": _text(body, "body"),
            "format": "markdown",
        }
        fingerprint = _digest(
            {
                "tenantId": tenant_id,
                "contextBundleDigest": context_bundle.get("contextBundleDigest"),
                "content": normalized_content,
            }
        )
        replay_key = f"artifact:{tenant_id}:{key}"
        with self._lock:
            replay = self.store.get_replay(replay_key)
            if replay is not None:
                if replay.fingerprint != fingerprint:
                    raise IdempotencyConflict()
                value = copy.deepcopy(dict(replay.result))
                value["replayed"] = True
                return value
            failure = self.store.get_failure(replay_key)
            if failure is not None:
                if failure.fingerprint != fingerprint:
                    raise IdempotencyConflict()
                details = failure.result
                raise PersonalPipelineError(
                    str(details.get("errorCode", "writer_failed")),
                    str(details.get("errorMessage", "personal artifact write failed")),
                )
            try:
                result = writer.write(
                    context,
                    normalized_content,
                    capability_id,
                    key,
                    context_receipt=context_receipt,
                )
            except Exception as exc:
                self._record_failure(
                    replay_key=replay_key,
                    fingerprint=fingerprint,
                    code="writer_failed",
                    message="personal artifact writer raised an exception",
                )
                raise PersonalPipelineError(
                    "writer_failed", "personal artifact writer raised an exception"
                ) from exc
            if not isinstance(result, Mapping) or str(result.get("status", "")).lower() not in _SUCCESS:
                self._record_failure(
                    replay_key=replay_key,
                    fingerprint=fingerprint,
                    code="writer_failed",
                    message="personal artifact writer did not succeed",
                )
                raise PersonalPipelineError("writer_failed", "personal artifact writer did not succeed")
            if _lookup(result, "remote_ref", "remoteRef") is not None:
                self._record_failure(
                    replay_key=replay_key,
                    fingerprint=fingerprint,
                    code="personal_remote_ref_forbidden",
                    message="personal writer returned a remote document",
                )
                raise PersonalPipelineError("personal_remote_ref_forbidden", "personal writer returned a remote document")
            artifact_ref = _text(_lookup(result, "artifact_ref", "artifactRef"), "artifact_ref", 256)
            readback = _lookup(result, "readback", default={})
            if not isinstance(readback, Mapping) or str(readback.get("status", "")).lower() not in _SUCCESS:
                self._record_failure(
                    replay_key=replay_key,
                    fingerprint=fingerprint,
                    code="readback_incomplete",
                    message="personal artifact readback is required",
                )
                raise PersonalPipelineError("readback_incomplete", "personal artifact readback is required")
            if _lookup(readback, "remote_ref", "remoteRef") is not None:
                self._record_failure(
                    replay_key=replay_key,
                    fingerprint=fingerprint,
                    code="personal_remote_ref_forbidden",
                    message="personal readback returned a remote document",
                )
                raise PersonalPipelineError("personal_remote_ref_forbidden", "personal readback returned a remote document")
            registration = _lookup(result, "registration", default={})
            if not isinstance(registration, Mapping):
                registration = {}
            revision = {
                "revision": 1,
                "content": normalized_content,
                "contentDigest": _digest(normalized_content),
                "baselineRevision": None,
                "verified": True,
            }
            artifact = {
                "schemaVersion": SCHEMA_VERSION,
                "tenantId": tenant_id,
                "authorityMode": PERSONAL_MODE,
                "artifactRef": artifact_ref,
                "contextBundleDigest": context_bundle["contextBundleDigest"],
                "revisions": [revision],
                "currentRevision": 1,
                "published": False,
                "replayed": False,
                "writeReceipt": {
                    "idempotencyKey": key,
                    "writeStatus": str(result.get("status", "")).lower(),
                    "registrationStatus": str(registration.get("status", "")).lower(),
                    "readbackStatus": str(readback.get("status", "")).lower(),
                    "readback": copy.deepcopy(dict(readback)),
                    "failure": None,
                },
            }
            existing_artifact = self.store.get_artifact(artifact_ref, tenant_id=tenant_id)
            if existing_artifact is not None:
                self._record_failure(
                    replay_key=replay_key,
                    fingerprint=fingerprint,
                    code="artifact_identity_conflict",
                    message="writer returned an artifact identity that already exists",
                )
                raise PersonalPipelineError(
                    "artifact_identity_conflict",
                    "writer returned an artifact identity that already exists",
                )
            try:
                stored, replayed = self.store.create_artifact(
                    artifact,
                    tenant_id=tenant_id,
                    replay_key=replay_key,
                    fingerprint=fingerprint,
                )
            except _StoreConflict as exc:
                if exc.code == "idempotency_conflict":
                    raise IdempotencyConflict() from exc
                raise PersonalPipelineError(exc.code, exc.message) from exc
            value = copy.deepcopy(dict(stored))
            value["replayed"] = replayed
            return value

    def save_revision(
        self,
        artifact_ref: str,
        *,
        tenant_id: str,
        title: str,
        body: str,
        baseline_revision: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        artifact_key = _text(artifact_ref, "artifact_ref", 256)
        owner_tenant_id = _text(tenant_id, "tenant_id", 256)
        replay_key = f"revision:{owner_tenant_id}:{artifact_key}:{_text(idempotency_key, 'idempotency_key', 256)}"
        content = {"title": _text(title, "title", 240), "body": _text(body, "body"), "format": "markdown"}
        fingerprint = _digest({"tenantId": owner_tenant_id, "artifactRef": artifact_key, "baselineRevision": baseline_revision, "content": content})
        with self._lock:
            replay = self.store.get_replay(replay_key)
            if replay is not None:
                if replay.fingerprint != fingerprint:
                    raise IdempotencyConflict()
                value = copy.deepcopy(dict(replay.result))
                value["replayed"] = True
                return value
            failure = self.store.get_failure(replay_key)
            if failure is not None:
                if failure.fingerprint != fingerprint:
                    raise IdempotencyConflict()
                details = failure.result
                raise PersonalPipelineError(
                    str(details.get("errorCode", "revision_conflict")),
                    str(details.get("errorMessage", "personal revision write failed")),
                )
            artifact = self.store.get_artifact(artifact_key, tenant_id=owner_tenant_id)
            if artifact is None:
                self._record_failure(
                    replay_key=replay_key,
                    fingerprint=fingerprint,
                    code="artifact_not_found",
                    message="personal artifact does not exist",
                )
                raise PersonalPipelineError("artifact_not_found", "personal artifact does not exist")
            if isinstance(baseline_revision, bool) or baseline_revision != artifact["currentRevision"]:
                self._record_failure(
                    replay_key=replay_key,
                    fingerprint=fingerprint,
                    code="revision_conflict",
                    message="baseline revision does not match the current revision",
                )
                raise RevisionConflict()
            revision_number = artifact["currentRevision"] + 1
            revision = {
                "revision": revision_number,
                "content": content,
                "contentDigest": _digest(content),
                "baselineRevision": baseline_revision,
                "verified": True,
                "replayed": False,
            }
            try:
                stored, replayed = self.store.save_revision(
                    artifact_key,
                    revision,
                    tenant_id=owner_tenant_id,
                    baseline_revision=baseline_revision,
                    replay_key=replay_key,
                    fingerprint=fingerprint,
                )
            except _StoreConflict as exc:
                if exc.code == "idempotency_conflict":
                    raise IdempotencyConflict() from exc
                if exc.code == "revision_conflict":
                    raise RevisionConflict() from exc
                raise PersonalPipelineError(exc.code, exc.message) from exc
            value = copy.deepcopy(dict(stored))
            value["replayed"] = replayed
            return value

    def build_publish_package(
        self,
        artifact_ref: str,
        *,
        tenant_id: str,
        revision: int,
        platform: str,
        platform_fields: Mapping[str, Any],
    ) -> dict[str, Any]:
        artifact_key = _text(artifact_ref, "artifact_ref", 256)
        owner_tenant_id = _text(tenant_id, "tenant_id", 256)
        with self._lock:
            artifact = self.store.get_artifact(artifact_key, tenant_id=owner_tenant_id)
            if artifact is None:
                raise PersonalPipelineError("artifact_not_found", "personal artifact does not exist")
            if isinstance(revision, bool) or revision != artifact["currentRevision"]:
                raise PersonalPipelineError("stale_revision", "publish package must use current verified revision")
            selected = artifact["revisions"][revision - 1]
            if selected["revision"] != revision or selected["verified"] is not True:
                raise PersonalPipelineError("revision_not_verified", "publish package revision is not verified")
            package = {
                "schemaVersion": SCHEMA_VERSION,
                "kind": "personal_publish_package",
                "tenantId": artifact["tenantId"],
                "artifactRef": artifact_key,
                "revision": revision,
                "contentDigest": selected["contentDigest"],
                "platform": _text(platform, "platform", 160),
                "platformFields": copy.deepcopy(dict(platform_fields)),
                "externalPublishStatus": "not_published",
                "publishable": False,
            }
            package["packageDigest"] = _digest(package)
            return package


__all__ = [
    "IdempotencyConflict",
    "InMemoryPersonalContentStore",
    "PersonalContentPipeline",
    "PersonalContentStore",
    "PersonalPipelineError",
    "PersonalWriter",
    "RevisionConflict",
    "SQLitePersonalContentStore",
    "SqlitePersonalContentStore",
    "SCHEMA_VERSION",
]
