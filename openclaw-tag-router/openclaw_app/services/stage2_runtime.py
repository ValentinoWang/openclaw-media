"""Dependency-injected composition boundary for the Stage-2 content flows.

The facade owns request composition and receipt identity only. Server session
facts, source readers, writers, adapters, persistence, clocks, and generation
are supplied by callers or by the existing Stage-2 services. No transport,
credential, database, or filesystem implementation belongs here.
"""

from __future__ import annotations

import copy
import hashlib
import inspect
import json
import threading
from collections.abc import Callable, Iterable, Mapping, MutableMapping
from dataclasses import asdict, dataclass, is_dataclass
from datetime import date, datetime, timezone
from typing import Any, Protocol
from uuid import UUID

from openclaw_app.services.stage2_artifact_state import (
    ArtifactRecordRequest,
    ArtifactStateError,
    ArtifactStateMachine,
    ArtifactStateResult,
)
from openclaw_app.services.stage2_context import (
    AIExecutionContext,
    CapabilityEffectRegistry,
    ContextBuildResult,
    ContextBuilder,
    DEFAULT_CAPABILITY_EFFECT_REGISTRY,
    DOCUMENT_WRITER_FIXTURE_ID,
    ORGANIZATION_AUTHORITY_MODE,
    OrganizationBinding as ContextBinding,
    PERSONAL_AUTHORITY_MODE,
    ServerSessionFacts,
    Stage2ContextError,
)
from openclaw_app.services.stage2_external_document import (
    BindingIdentity,
    ExternalDocumentAdapter,
)
from openclaw_app.services.stage2_organization_pipeline import (
    OrganizationContentPipeline,
    OrganizationPipelineError,
)
from openclaw_app.services.stage2_personal_pipeline import (
    PersonalContentPipeline,
    PersonalContentStore,
    PersonalPipelineError,
)


SCHEMA_VERSION = "stage2.runtime_receipt.v1"
PERSONAL_MODE = PERSONAL_AUTHORITY_MODE
ORGANIZATION_MODE = ORGANIZATION_AUTHORITY_MODE

_ATTENTION_CODES = frozenset(
    {
        "artifact_identity_conflict",
        "artifact_state_failed",
        "content_digest_mismatch",
        "external_write_needs_attention",
        "personal_remote_ref_forbidden",
        "pipeline_failed",
        "readback_failed",
        "readback_incomplete",
        "remote_ref_mismatch",
        "remote_revision_mismatch",
        "registration_failed",
        "untrusted_remote_url",
        "write_failed",
        "writer_failed",
    }
)
_BROWSER_AUTHORITY_FIELDS = frozenset(
    {
        "authority",
        "authority_mode",
        "authority_override",
        "authoritymode",
        "binding",
        "binding_generation",
        "bindinggeneration",
        "binding_id",
        "bindingid",
        "body_authority",
        "bodyauthority",
        "capability",
        "capability_id",
        "capabilityid",
        "container_id",
        "containerid",
        "credentials",
        "credential",
        "lark_app_id",
        "larkappid",
        "lark_space_id",
        "larkspaceid",
        "organization_id",
        "organizationid",
        "parent_node_id",
        "parentnodeid",
        "role",
        "route",
        "tenant",
        "tenant_id",
        "tenantid",
        "tenant_type",
        "tenanttype",
        "workspace",
        "workspace_mode",
        "workspacemode",
    }
)
_MODE_ALIASES = {
    "personal": PERSONAL_MODE,
    "personal_web": PERSONAL_MODE,
    "internal": PERSONAL_MODE,
    "personal_web/internal": PERSONAL_MODE,
    "organization": ORGANIZATION_MODE,
    "organization_lark": ORGANIZATION_MODE,
    "lark": ORGANIZATION_MODE,
    "feishu": ORGANIZATION_MODE,
    "organization_lark/lark": ORGANIZATION_MODE,
}


class Stage2RuntimeError(RuntimeError):
    """Fail-closed facade error carrying a stable machine code."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


class IdempotencyConflict(Stage2RuntimeError):
    def __init__(self) -> None:
        super().__init__("idempotency_conflict", "operation id was reused with another request")


class IdempotencyInProgress(Stage2RuntimeError):
    """Another process has already claimed this operation for execution."""

    def __init__(self) -> None:
        super().__init__("idempotency_in_progress", "operation is already in progress")


@dataclass(frozen=True, slots=True)
class ReceiptRecord:
    request_fingerprint: str
    response: Mapping[str, Any]


class ReceiptStore(Protocol):
    def get(self, key: str) -> ReceiptRecord | Mapping[str, Any] | None: ...

    def put(self, key: str, request_fingerprint: str, response: Mapping[str, Any]) -> None: ...

    def claim(self, key: str, request_fingerprint: str) -> ReceiptRecord | Mapping[str, Any] | None: ...

    def release(self, key: str, request_fingerprint: str) -> None: ...


class InMemoryReceiptStore:
    """Thread-safe default store; production persistence remains injected."""

    def __init__(self) -> None:
        self._records: dict[str, ReceiptRecord] = {}
        self._lock = threading.RLock()

    @property
    def records(self) -> dict[str, ReceiptRecord]:
        with self._lock:
            return copy.deepcopy(self._records)

    def get(self, key: str) -> ReceiptRecord | None:
        with self._lock:
            record = self._records.get(key)
            return copy.deepcopy(record) if record is not None else None

    def put(self, key: str, request_fingerprint: str, response: Mapping[str, Any]) -> None:
        with self._lock:
            existing = self._records.get(key)
            if existing is not None and existing.request_fingerprint != request_fingerprint:
                raise IdempotencyConflict()
            if existing is None:
                self._records[key] = ReceiptRecord(
                    request_fingerprint=request_fingerprint,
                    response=copy.deepcopy(dict(response)),
                )

    def claim(self, key: str, request_fingerprint: str) -> ReceiptRecord | None:
        with self._lock:
            record = self._records.get(key)
            if record is not None:
                if record.request_fingerprint != request_fingerprint:
                    raise IdempotencyConflict()
                return copy.deepcopy(record)
            return None

    def release(self, key: str, request_fingerprint: str) -> None:
        # In-memory records are only written after operation completion, so a
        # failed operation has no reservation to release.
        return None


class _CapturingPersonalWriter:
    """Record the injected writer outcome without adding a transport layer."""

    def __init__(self, delegate: Any) -> None:
        self.delegate = delegate
        self.result: Any = None

    def write(self, *args: Any, **kwargs: Any) -> Mapping[str, Any]:
        result = self.delegate.write(*args, **kwargs)
        self.result = result
        return result


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


def _canonical(value: Any) -> Any:
    """Convert trusted request/result values into deterministic JSON facts."""

    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        normalized = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
        return normalized.astimezone(timezone.utc).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if hasattr(value, "as_dict") and callable(value.as_dict):
        converted = value.as_dict()
        if converted is not value:
            return _canonical(converted)
    if hasattr(value, "to_dict") and callable(value.to_dict):
        converted = value.to_dict()
        if converted is not value:
            return _canonical(converted)
    if is_dataclass(value):
        return _canonical(asdict(value))
    if isinstance(value, Mapping):
        return {
            str(key): _canonical(child)
            for key, child in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_canonical(child) for child in value]
    if isinstance(value, (set, frozenset)):
        return sorted((_canonical(child) for child in value), key=lambda item: repr(item))
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return {"type": type(value).__name__}


def _canonical_json(value: Any) -> str:
    return json.dumps(_canonical(value), ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _text(value: Any, label: str, maximum: int = 512) -> str:
    if not isinstance(value, str):
        raise Stage2RuntimeError("invalid_request", f"{label} must be a string")
    normalized = value.strip()
    if not normalized or len(normalized) > maximum or any(ord(char) < 32 for char in normalized):
        raise Stage2RuntimeError("invalid_request", f"{label} is invalid")
    return normalized


def _normalize_mode(value: Any) -> str:
    if not isinstance(value, str):
        raise Stage2RuntimeError("route_mismatch", "authority mode must be a supported string")
    normalized = value.strip().lower().replace(":", "/")
    mode = _MODE_ALIASES.get(normalized)
    if mode is None:
        raise Stage2RuntimeError("route_mismatch", "authority mode is not supported")
    return mode


def _assert_browser_claims(claims: Mapping[str, Any] | None) -> None:
    if claims is None:
        return
    if not isinstance(claims, Mapping):
        raise Stage2RuntimeError("invalid_request", "browser claims must be an object")
    found = sorted(
        str(key)
        for key in claims
        if str(key).replace("-", "_").lower() in _BROWSER_AUTHORITY_FIELDS
    )
    if found:
        raise Stage2RuntimeError(
            "authority_override",
            "browser authority claims are not authorization facts",
        )


def _materialize_sources(value: Iterable[Any] | None) -> list[Any] | None:
    if value is None:
        return None
    if isinstance(value, (str, bytes, Mapping)):
        raise Stage2RuntimeError("invalid_request", "sources must be an iterable of source objects")
    try:
        return list(value)
    except TypeError as exc:
        raise Stage2RuntimeError("invalid_request", "sources must be an iterable of source objects") from exc


def _choose_sources(
    sources: Iterable[Any] | None,
    source_rows: Iterable[Any] | None,
) -> list[Any] | None:
    if sources is not None and source_rows is not None:
        raise Stage2RuntimeError("invalid_request", "sources and source_rows cannot both be provided")
    return _materialize_sources(sources if sources is not None else source_rows)


def _materialize_texts(value: Iterable[str], label: str) -> list[str]:
    if isinstance(value, str):
        return [_text(value, label, 1000)]
    try:
        values = list(value)
    except TypeError as exc:
        raise Stage2RuntimeError("invalid_request", f"{label} must be an iterable of strings") from exc
    return [_text(item, label, 1000) for item in values]


def _operation_key(operation_id: str | None, idempotency_key: str | None) -> str:
    if operation_id is not None and idempotency_key is not None and operation_id != idempotency_key:
        raise Stage2RuntimeError("invalid_request", "operation_id and idempotency_key must match")
    return _text(operation_id if operation_id is not None else idempotency_key, "operation_id", 256)


def _receipt_storage_key(mode: str, tenant_id: str, operation_id: str) -> str:
    identity = _canonical_json(
        {
            "mode": mode,
            "operationId": operation_id,
            "tenantId": tenant_id,
        }
    )
    return "stage2-runtime:" + hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _error_details(exc: Exception, fallback: str = "Stage-2 operation failed") -> tuple[str, str]:
    code = getattr(exc, "code", None)
    if not isinstance(code, str) or not code.strip():
        code = "pipeline_failed"
    message = getattr(exc, "message", None) or getattr(exc, "detail", None) or str(exc)
    message = str(message).strip() or fallback
    return code.strip(), message[:240]


def _as_runtime_error(exc: Exception) -> Stage2RuntimeError:
    if isinstance(exc, Stage2RuntimeError):
        return exc
    code, message = _error_details(exc)
    return Stage2RuntimeError(code, message)


def _binding_pair(binding: ContextBinding | BindingIdentity) -> tuple[ContextBinding, BindingIdentity]:
    if isinstance(binding, ContextBinding):
        return binding, BindingIdentity(
            tenant_id=binding.tenant_id,
            binding_id=binding.binding_id,
            binding_generation=binding.generation,
            status=binding.status,
        )
    if isinstance(binding, BindingIdentity):
        return (
            ContextBinding(
                binding_id=binding.binding_id,
                tenant_id=binding.tenant_id,
                generation=binding.binding_generation,
                status=binding.status,
            ),
            binding,
        )
    raise Stage2RuntimeError("binding_required", "an active server-owned Binding is required")


def _binding_descriptor(binding: ContextBinding | BindingIdentity) -> dict[str, Any]:
    if isinstance(binding, ContextBinding):
        return {
            "tenantId": binding.tenant_id,
            "bindingId": binding.binding_id,
            "bindingGeneration": binding.generation,
            "status": binding.status,
        }
    return {
        "tenantId": binding.tenant_id,
        "bindingId": binding.binding_id,
        "bindingGeneration": binding.binding_generation,
        "status": binding.status,
    }


def _context_sources(result: ContextBuildResult) -> list[dict[str, Any]]:
    # ContextSourceRow payloads are immutable mapping proxies. The downstream
    # pipelines intentionally accept JSON-shaped mappings, so normalize the
    # server-owned rows before handing them across that boundary.
    return [_canonical(item.as_dict()) for item in result.items]


class Stage2Runtime:
    """Compose the personal and organization Stage-2 services."""

    def __init__(
        self,
        *,
        context_builder: ContextBuilder | None = None,
        source_reader: Any | None = None,
        personal_pipeline: PersonalContentPipeline | None = None,
        personal_store: PersonalContentStore | None = None,
        organization_pipeline: OrganizationContentPipeline | None = None,
        personal_writer: Any | None = None,
        organization_adapter: ExternalDocumentAdapter | None = None,
        artifact_state: ArtifactStateMachine | None = None,
        receipt_store: ReceiptStore | MutableMapping[str, Any] | None = None,
        effect_registry: CapabilityEffectRegistry | None = None,
        content_generator: Any | None = None,
        clock: Callable[[], Any] | None = None,
    ) -> None:
        if context_builder is not None and source_reader is not None:
            raise ValueError("context_builder and source_reader cannot both be supplied")
        if personal_pipeline is not None and personal_store is not None:
            raise ValueError("personal_pipeline and personal_store cannot both be supplied")
        self.effect_registry = effect_registry or DEFAULT_CAPABILITY_EFFECT_REGISTRY
        self.context_builder = context_builder or ContextBuilder(
            source_reader=source_reader,
            effect_registry=self.effect_registry,
            clock=clock,
        )
        self.personal_pipeline = personal_pipeline or PersonalContentPipeline(store=personal_store)
        self.organization_pipeline = organization_pipeline or OrganizationContentPipeline()
        self.personal_writer = personal_writer
        self.organization_adapter = organization_adapter
        self.artifact_state = artifact_state or ArtifactStateMachine()
        self.receipt_store = receipt_store if receipt_store is not None else InMemoryReceiptStore()
        self.content_generator = content_generator
        self.clock = clock
        self._lock = threading.RLock()

    def run_personal(
        self,
        *,
        session: ServerSessionFacts,
        capability_id: str,
        title: str,
        topic: str,
        target: str,
        confirmed_by: str | None,
        confirmation_ref: str | None,
        operation_id: str | None = None,
        idempotency_key: str | None = None,
        sources: Iterable[Any] | None = None,
        source_rows: Iterable[Any] | None = None,
        body: str | None = None,
        tradeoffs: Iterable[str] = (),
        risks: Iterable[str] = (),
        platform_constraints: Mapping[str, Any] | None = None,
        browser_claims: Mapping[str, Any] | None = None,
        expected_authority_mode: str | None = None,
        authority_mode: str | None = None,
        route: str | None = None,
        writer: Any | None = None,
    ) -> dict[str, Any]:
        key = _operation_key(operation_id, idempotency_key)
        session = self._require_session(session)
        mode = self._expected_mode(PERSONAL_MODE, expected_authority_mode, authority_mode, route)
        if session.tenant_type != "personal":
            raise Stage2RuntimeError("route_mismatch", "personal operation requires a personal session")
        if session.binding_generation is not None:
            raise Stage2RuntimeError("personal_binding_forbidden", "personal operation cannot carry Binding identity")
        _assert_browser_claims(browser_claims)
        self._authorize_capability(capability_id, mode)
        selected_writer = writer or self.personal_writer
        if selected_writer is None:
            raise Stage2RuntimeError("writer_required", "personal writer dependency is required")
        if body is None and self.content_generator is None:
            raise Stage2RuntimeError("generation_required", "body or an injected content generator is required")
        title = _text(title, "title", 240)
        topic = _text(topic, "topic", 500)
        target = _text(target, "target", 500)
        if not confirmed_by or not confirmation_ref:
            raise Stage2RuntimeError("human_confirmation_required", "decision brief requires human confirmation")
        confirmed_by = _text(confirmed_by, "confirmed_by", 256)
        confirmation_ref = _text(confirmation_ref, "confirmation_ref", 256)
        tradeoffs = _materialize_texts(tradeoffs, "tradeoff")
        risks = _materialize_texts(risks, "risk")
        selected_sources = _choose_sources(sources, source_rows)
        if platform_constraints is None:
            platform_constraints = {}
        if not isinstance(platform_constraints, Mapping):
            raise Stage2RuntimeError("invalid_request", "platform_constraints must be an object")
        payload = {
            "operationId": key,
            "route": mode,
            "capabilityId": capability_id,
            "session": session,
            "sources": selected_sources,
            "title": title,
            "body": body,
            "topic": topic,
            "target": target,
            "tradeoffs": tradeoffs,
            "risks": risks,
            "confirmedBy": confirmed_by,
            "confirmationRef": confirmation_ref,
            "platformConstraints": platform_constraints,
            "browserClaims": browser_claims,
        }
        return self._run_once(
            key,
            payload,
            mode,
            session.tenant_id,
            lambda: self._execute_personal(
                key=key,
                session=session,
                capability_id=capability_id,
                selected_sources=selected_sources,
                title=title,
                body=body,
                topic=topic,
                target=target,
                tradeoffs=tradeoffs,
                risks=risks,
                confirmed_by=confirmed_by,
                confirmation_ref=confirmation_ref,
                platform_constraints=platform_constraints,
                browser_claims=browser_claims,
                writer=selected_writer,
            ),
        )

    personal_operation = run_personal
    execute_personal = run_personal

    def run_organization(
        self,
        *,
        session: ServerSessionFacts,
        binding: ContextBinding | BindingIdentity,
        capability_id: str,
        title: str,
        credential_generation: str,
        trusted_open_url: str,
        operation_id: str | None = None,
        idempotency_key: str | None = None,
        sources: Iterable[Any] | None = None,
        source_rows: Iterable[Any] | None = None,
        body: str | None = None,
        browser_claims: Mapping[str, Any] | None = None,
        expected_authority_mode: str | None = None,
        authority_mode: str | None = None,
        route: str | None = None,
        adapter: ExternalDocumentAdapter | None = None,
    ) -> dict[str, Any]:
        key = _operation_key(operation_id, idempotency_key)
        session = self._require_session(session)
        mode = self._expected_mode(ORGANIZATION_MODE, expected_authority_mode, authority_mode, route)
        if session.tenant_type != "organization":
            raise Stage2RuntimeError("route_mismatch", "organization operation requires an organization session")
        _assert_browser_claims(browser_claims)
        context_binding, external_binding = _binding_pair(binding)
        if context_binding.status != "active" or external_binding.status != "active":
            raise Stage2RuntimeError("binding_inactive", "organization Binding is not active")
        if context_binding.tenant_id != session.tenant_id:
            raise Stage2RuntimeError("binding_tenant_mismatch", "organization Binding tenant does not match session")
        if session.binding_generation is None:
            raise Stage2RuntimeError("binding_required", "organization session has no active Binding generation")
        if context_binding.generation != session.binding_generation:
            raise Stage2RuntimeError("binding_generation_mismatch", "organization Binding generation does not match session")
        self._authorize_capability(capability_id, mode)
        selected_adapter = adapter or self.organization_adapter
        if selected_adapter is None:
            raise Stage2RuntimeError("adapter_required", "organization document adapter dependency is required")
        if body is None and self.content_generator is None:
            raise Stage2RuntimeError("generation_required", "body or an injected content generator is required")
        title = _text(title, "title", 240)
        credential_generation = _text(credential_generation, "credential_generation", 160)
        trusted_open_url = _text(trusted_open_url, "trusted_open_url", 2048)
        if not trusted_open_url.startswith("https://") or any(char.isspace() for char in trusted_open_url):
            raise Stage2RuntimeError("untrusted_remote_url", "only an HTTPS trusted open URL is allowed")
        selected_sources = _choose_sources(sources, source_rows)
        payload = {
            "operationId": key,
            "route": mode,
            "capabilityId": capability_id,
            "session": session,
            "binding": binding,
            "sources": selected_sources,
            "title": title,
            "body": body,
            "credentialGeneration": credential_generation,
            "trustedOpenUrl": trusted_open_url,
            "browserClaims": browser_claims,
        }
        return self._run_once(
            key,
            payload,
            mode,
            session.tenant_id,
            lambda: self._execute_organization(
                key=key,
                session=session,
                context_binding=context_binding,
                external_binding=external_binding,
                capability_id=capability_id,
                selected_sources=selected_sources,
                title=title,
                body=body,
                credential_generation=credential_generation,
                trusted_open_url=trusted_open_url,
                browser_claims=browser_claims,
                adapter=selected_adapter,
            ),
        )

    organization_operation = run_organization
    execute_organization = run_organization

    @staticmethod
    def _require_session(session: Any) -> ServerSessionFacts:
        if not isinstance(session, ServerSessionFacts):
            raise Stage2RuntimeError("invalid_context", "server session facts are required")
        return session

    @staticmethod
    def _expected_mode(
        required: str,
        expected_authority_mode: str | None,
        authority_mode: str | None,
        route: str | None,
    ) -> str:
        supplied = [value for value in (expected_authority_mode, authority_mode, route) if value is not None]
        normalized = [_normalize_mode(value) for value in supplied]
        if normalized and any(value != normalized[0] for value in normalized):
            raise Stage2RuntimeError("route_mismatch", "authority mode declarations conflict")
        if normalized and normalized[0] != required:
            raise Stage2RuntimeError("route_mismatch", "operation route does not match the server-owned flow")
        return required

    def _authorize_capability(self, capability_id: str, mode: str) -> None:
        try:
            self.effect_registry.authorize(
                capability_id,
                authority_mode=mode,
                document_side_effect=True,
                readback_required=True,
            )
        except Exception as exc:
            raise _as_runtime_error(exc) from exc

    def _build_context(
        self,
        *,
        session: ServerSessionFacts,
        capability_id: str,
        mode: str,
        binding: ContextBinding | None,
        browser_claims: Mapping[str, Any] | None,
        source_rows: list[Any] | None,
    ) -> ContextBuildResult:
        try:
            result = self.context_builder.build_for_session(
                session,
                capability_id,
                binding=binding,
                browser_claims=browser_claims,
                source_rows=source_rows,
            )
        except Exception as exc:
            raise _as_runtime_error(exc) from exc
        if not isinstance(result, ContextBuildResult) or not isinstance(result.context, AIExecutionContext):
            raise Stage2RuntimeError("invalid_context", "context builder did not return a trusted context result")
        if result.context.authority_mode != mode or result.context.tenant_id != session.tenant_id:
            raise Stage2RuntimeError("route_mismatch", "context builder returned an unexpected trusted route")
        if mode == PERSONAL_MODE and result.context.binding_id is not None:
            raise Stage2RuntimeError("personal_binding_forbidden", "personal context cannot carry Binding identity")
        if mode == ORGANIZATION_MODE:
            if binding is None:
                raise Stage2RuntimeError("binding_required", "organization context requires an active Binding")
            if (
                result.context.binding_id != binding.binding_id
                or result.context.binding_generation != binding.generation
            ):
                raise Stage2RuntimeError("binding_mismatch", "trusted context Binding does not match the active Binding")
        return result

    def _execute_personal(
        self,
        *,
        key: str,
        session: ServerSessionFacts,
        capability_id: str,
        selected_sources: list[Any] | None,
        title: str,
        body: str | None,
        topic: str,
        target: str,
        tradeoffs: list[str],
        risks: list[str],
        confirmed_by: str,
        confirmation_ref: str,
        platform_constraints: Mapping[str, Any],
        browser_claims: Mapping[str, Any] | None,
        writer: Any,
    ) -> dict[str, Any]:
        result = self._build_context(
            session=session,
            capability_id=capability_id,
            mode=PERSONAL_MODE,
            binding=None,
            browser_claims=browser_claims,
            source_rows=selected_sources,
        )
        try:
            scope = self.personal_pipeline.build_scope(
                result.context,
                _context_sources(result),
                browser_claims=browser_claims,
            )
            research = self.personal_pipeline.build_research_brief(scope)
            decision = self.personal_pipeline.build_decision_brief(
                scope,
                topic=topic,
                target=target,
                tradeoffs=tradeoffs,
                risks=risks,
                confirmed_by=confirmed_by,
                confirmation_ref=confirmation_ref,
            )
            context_bundle = self.personal_pipeline.build_context_bundle(
                scope,
                research,
                decision,
                platform_constraints=platform_constraints,
            )
            resolved_title, resolved_body = self._resolve_content(
                context=result.context,
                material=context_bundle,
                title=title,
                body=body,
                operation_id=key,
            )
            capturing_writer = _CapturingPersonalWriter(writer)
            artifact = self.personal_pipeline.create_artifact(
                result.context,
                context_bundle,
                title=resolved_title,
                body=resolved_body,
                idempotency_key=key,
                writer=capturing_writer,
                context_receipt=result.receipt.as_dict(),
            )
        except PersonalPipelineError as exc:
            code, message = _error_details(exc)
            if code in _ATTENTION_CODES:
                return self._failure_receipt(
                    key=key,
                    mode=PERSONAL_MODE,
                    tenant_id=session.tenant_id,
                    context_result=result,
                    error_code=code,
                    error_message=message,
                )
            raise Stage2RuntimeError(code, message) from exc
        except Stage2RuntimeError:
            raise
        except Exception as exc:
            code, message = _error_details(exc)
            return self._failure_receipt(
                key=key,
                mode=PERSONAL_MODE,
                tenant_id=session.tenant_id,
                context_result=result,
                error_code="pipeline_failed" if code == "pipeline_failed" else code,
                error_message=message,
            )

        try:
            revision = artifact["revisions"][0]
            state = self.artifact_state.record(
                ArtifactRecordRequest(
                    tenant_id=session.tenant_id,
                    authority_mode=PERSONAL_MODE,
                    idempotency_key=key,
                    content_digest=revision["contentDigest"],
                    write_status=str(_lookup(capturing_writer.result, "status", default="written")),
                    registration_status=str(
                        _lookup(
                            _lookup(capturing_writer.result, "registration", default=None),
                            "status",
                            default="registered",
                        )
                    ),
                    readback_status=str(
                        _lookup(
                            _lookup(capturing_writer.result, "readback", default=None),
                            "status",
                            default="confirmed",
                        )
                    ),
                    artifact_ref=artifact["artifactRef"],
                    revision=str(revision["revision"]),
                    readback_content_digest=revision["contentDigest"],
                    readback_artifact_ref=artifact["artifactRef"],
                    readback_revision=str(revision["revision"]),
                )
            )
        except (ArtifactStateError, KeyError, IndexError, TypeError) as exc:
            code, message = _error_details(exc, "artifact state registration failed")
            return self._failure_receipt(
                key=key,
                mode=PERSONAL_MODE,
                tenant_id=session.tenant_id,
                context_result=result,
                error_code="artifact_state_failed",
                error_message=message,
                artifact=artifact if isinstance(artifact, Mapping) else None,
            )
        return self._success_receipt(
            key=key,
            mode=PERSONAL_MODE,
            tenant_id=session.tenant_id,
            context_result=result,
            artifact=artifact,
            state=state,
        )

    def _execute_organization(
        self,
        *,
        key: str,
        session: ServerSessionFacts,
        context_binding: ContextBinding,
        external_binding: BindingIdentity,
        capability_id: str,
        selected_sources: list[Any] | None,
        title: str,
        body: str | None,
        credential_generation: str,
        trusted_open_url: str,
        browser_claims: Mapping[str, Any] | None,
        adapter: ExternalDocumentAdapter,
    ) -> dict[str, Any]:
        result = self._build_context(
            session=session,
            capability_id=capability_id,
            mode=ORGANIZATION_MODE,
            binding=context_binding,
            browser_claims=browser_claims,
            source_rows=selected_sources,
        )
        try:
            scope = self.organization_pipeline.build_scope(
                result.context,
                external_binding,
                _context_sources(result),
                browser_claims=browser_claims,
            )
            resolved_title, resolved_body = self._resolve_content(
                context=result.context,
                material=scope,
                title=title,
                body=body,
                operation_id=key,
            )
            artifact = self.organization_pipeline.write_document(
                result.context,
                scope,
                title=resolved_title,
                body=resolved_body,
                idempotency_key=key,
                binding=external_binding,
                adapter=adapter,
                credential_generation=credential_generation,
            )
        except OrganizationPipelineError as exc:
            code, message = _error_details(exc)
            if code in _ATTENTION_CODES:
                return self._failure_receipt(
                    key=key,
                    mode=ORGANIZATION_MODE,
                    tenant_id=session.tenant_id,
                    context_result=result,
                    error_code=code,
                    error_message=message,
                )
            raise Stage2RuntimeError(code, message) from exc
        except Stage2RuntimeError:
            raise
        except Exception as exc:
            code, message = _error_details(exc)
            return self._failure_receipt(
                key=key,
                mode=ORGANIZATION_MODE,
                tenant_id=session.tenant_id,
                context_result=result,
                error_code="pipeline_failed" if code == "pipeline_failed" else code,
                error_message=message,
            )

        if not isinstance(artifact, Mapping) or str(artifact.get("status", "")).lower() != "registered":
            error_code = str(artifact.get("errorCode", "external_write_needs_attention")) if isinstance(artifact, Mapping) else "external_write_needs_attention"
            return self._failure_receipt(
                key=key,
                mode=ORGANIZATION_MODE,
                tenant_id=session.tenant_id,
                context_result=result,
                error_code=error_code,
                error_message="organization document write is not registered",
                artifact=artifact if isinstance(artifact, Mapping) else None,
            )

        try:
            mirror = self.organization_pipeline.readback_mirror(
                artifact["artifactRef"],
                tenant_id=session.tenant_id,
                binding=external_binding,
                remote_ref=artifact["remoteRef"],
                remote_revision=artifact["remoteRevision"],
                content_digest=artifact["contentDigest"],
                trusted_open_url=trusted_open_url,
            )
        except OrganizationPipelineError as exc:
            code, message = _error_details(exc)
            if code in {"binding_mismatch", "remote_ref_mismatch", "remote_revision_mismatch", "content_digest_mismatch", "untrusted_remote_url", "readback_incomplete"}:
                return self._failure_receipt(
                    key=key,
                    mode=ORGANIZATION_MODE,
                    tenant_id=session.tenant_id,
                    context_result=result,
                    error_code=code,
                    error_message=message,
                    artifact=artifact,
                )
            raise Stage2RuntimeError(code, message) from exc
        except Exception as exc:
            code, message = _error_details(exc, "organization readback failed")
            return self._failure_receipt(
                key=key,
                mode=ORGANIZATION_MODE,
                tenant_id=session.tenant_id,
                context_result=result,
                error_code="readback_failed",
                error_message=message,
                artifact=artifact,
            )

        final_artifact = copy.deepcopy(dict(artifact))
        final_artifact["status"] = "readback_verified"
        final_artifact["mirror"] = copy.deepcopy(mirror)
        try:
            state = self.artifact_state.record(
                ArtifactRecordRequest(
                    tenant_id=session.tenant_id,
                    authority_mode=ORGANIZATION_MODE,
                    idempotency_key=key,
                    content_digest=artifact["contentDigest"],
                    write_status="written",
                    registration_status="registered",
                    readback_status="confirmed",
                    artifact_ref=artifact["artifactRef"],
                    revision=str(artifact["remoteRevision"]),
                    binding_id=external_binding.binding_id,
                    binding_generation=external_binding.binding_generation,
                    remote_ref=artifact["remoteRef"],
                    remote_revision=artifact["remoteRevision"],
                    readback_content_digest=artifact["contentDigest"],
                    readback_artifact_ref=artifact["artifactRef"],
                    readback_revision=str(artifact["remoteRevision"]),
                    readback_binding_id=external_binding.binding_id,
                    readback_binding_generation=external_binding.binding_generation,
                    readback_remote_ref=artifact["remoteRef"],
                    readback_remote_revision=artifact["remoteRevision"],
                )
            )
        except (ArtifactStateError, KeyError, TypeError) as exc:
            code, message = _error_details(exc, "artifact state registration failed")
            return self._failure_receipt(
                key=key,
                mode=ORGANIZATION_MODE,
                tenant_id=session.tenant_id,
                context_result=result,
                error_code="artifact_state_failed",
                error_message=message,
                artifact=final_artifact,
                mirror=mirror,
            )
        return self._success_receipt(
            key=key,
            mode=ORGANIZATION_MODE,
            tenant_id=session.tenant_id,
            context_result=result,
            artifact=final_artifact,
            state=state,
            mirror=mirror,
        )

    def _resolve_content(
        self,
        *,
        context: AIExecutionContext,
        material: Mapping[str, Any],
        title: str,
        body: str | None,
        operation_id: str,
    ) -> tuple[str, str]:
        if body is not None:
            return title, body
        generator = self.content_generator
        if generator is None:
            raise Stage2RuntimeError("generation_required", "body or an injected content generator is required")
        target = getattr(generator, "generate", None)
        if target is None and callable(generator):
            target = generator
        if target is None or not callable(target):
            raise Stage2RuntimeError("generator_invalid", "content generator is not callable")
        values = {
            "context": context,
            "trusted_context": context,
            "material": material,
            "scope": material,
            "context_bundle": material,
            "operation_id": operation_id,
            "operationId": operation_id,
            "title": title,
        }
        try:
            signature = inspect.signature(target)
        except (TypeError, ValueError):
            generated = target(context, material)
        else:
            positional: list[Any] = []
            keyword: dict[str, Any] = {}
            has_var_keyword = False
            for parameter in signature.parameters.values():
                if parameter.kind is inspect.Parameter.VAR_KEYWORD:
                    has_var_keyword = True
                    continue
                if parameter.kind is inspect.Parameter.VAR_POSITIONAL:
                    continue
                if parameter.name in values:
                    if parameter.kind is inspect.Parameter.POSITIONAL_ONLY:
                        positional.append(values[parameter.name])
                    else:
                        keyword[parameter.name] = values[parameter.name]
                    continue
                if parameter.default is inspect.Parameter.empty:
                    if len(signature.parameters) == 1:
                        generated = target(material)
                        break
                    if len(signature.parameters) == 2:
                        generated = target(context, material)
                        break
                    raise Stage2RuntimeError("generator_invalid", f"unsupported generator parameter {parameter.name!r}")
            else:
                if has_var_keyword:
                    keyword.update(values)
                generated = target(*positional, **keyword)
        if isinstance(generated, str):
            return title, generated
        if not isinstance(generated, Mapping):
            raise Stage2RuntimeError("generator_invalid", "content generator must return text or an object")
        generated_title = generated.get("title", title)
        generated_body = generated.get("body", generated.get("content"))
        return _text(generated_title, "generated_title", 240), _text(generated_body, "generated_body")

    def _run_once(
        self,
        key: str,
        payload: Mapping[str, Any],
        mode: str,
        tenant_id: str,
        operation: Callable[[], dict[str, Any]],
    ) -> dict[str, Any]:
        fingerprint = _digest(payload)
        storage_key = _receipt_storage_key(mode, tenant_id, key)
        with self._lock:
            existing = self._read_record(storage_key)
            if existing is not None:
                if existing.request_fingerprint != fingerprint:
                    raise IdempotencyConflict()
                replay = copy.deepcopy(existing.response)
                replay["replayed"] = True
                return replay
            claim = getattr(self.receipt_store, "claim", None)
            release = getattr(self.receipt_store, "release", None)
            if callable(claim):
                try:
                    claimed = claim(storage_key, fingerprint)
                except IdempotencyInProgress:
                    raise
                if claimed is not None:
                    existing = self._coerce_receipt_record(claimed)
                    replay = copy.deepcopy(existing.response)
                    replay["replayed"] = True
                    return replay
            try:
                response = operation()
            except Stage2RuntimeError:
                if callable(release):
                    release(storage_key, fingerprint)
                raise
            except (Stage2ContextError,) as exc:
                if callable(release):
                    release(storage_key, fingerprint)
                raise _as_runtime_error(exc) from exc
            except Exception as exc:
                code, message = _error_details(exc)
                if code == "idempotency_conflict":
                    if callable(release):
                        release(storage_key, fingerprint)
                    raise IdempotencyConflict() from exc
                response = self._failure_receipt(
                    key=key,
                    mode=mode,
                    tenant_id=tenant_id,
                    error_code="pipeline_failed",
                    error_message=message,
                )
            try:
                self._write_record(storage_key, fingerprint, response)
            except Exception:
                if callable(release):
                    release(storage_key, fingerprint)
                raise
            return copy.deepcopy(response)

    @staticmethod
    def _coerce_receipt_record(raw: ReceiptRecord | Mapping[str, Any]) -> ReceiptRecord:
        if isinstance(raw, ReceiptRecord):
            return copy.deepcopy(raw)
        if isinstance(raw, Mapping):
            fingerprint = _lookup(raw, "request_fingerprint", "requestFingerprint", "fingerprint")
            response = _lookup(raw, "response")
            if isinstance(fingerprint, str) and isinstance(response, Mapping):
                return ReceiptRecord(fingerprint, copy.deepcopy(dict(response)))
        raise Stage2RuntimeError("receipt_store_invalid", "receipt store returned an invalid record")

    def _read_record(self, key: str) -> ReceiptRecord | None:
        if isinstance(self.receipt_store, MutableMapping):
            raw = self.receipt_store.get(key)
        else:
            raw = self.receipt_store.get(key)
        if raw is None:
            return None
        if isinstance(raw, ReceiptRecord):
            return copy.deepcopy(raw)
        if isinstance(raw, Mapping):
            fingerprint = _lookup(raw, "request_fingerprint", "requestFingerprint", "fingerprint")
            response = _lookup(raw, "response")
            if isinstance(fingerprint, str) and isinstance(response, Mapping):
                return ReceiptRecord(fingerprint, copy.deepcopy(dict(response)))
        raise Stage2RuntimeError("receipt_store_invalid", "receipt store returned an invalid record")

    def _write_record(self, key: str, fingerprint: str, response: Mapping[str, Any]) -> None:
        if isinstance(self.receipt_store, MutableMapping):
            existing = self._read_record(key)
            if existing is not None:
                if existing.request_fingerprint != fingerprint:
                    raise IdempotencyConflict()
                return
            self.receipt_store[key] = ReceiptRecord(fingerprint, copy.deepcopy(dict(response)))
            return
        self.receipt_store.put(key, fingerprint, response)

    def _observed_at(self) -> str | None:
        if self.clock is None:
            return None
        value = self.clock()
        if isinstance(value, datetime):
            normalized = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
            return normalized.astimezone(timezone.utc).isoformat()
        return _text(value, "clock value", 128)

    def _make_receipt(
        self,
        *,
        key: str,
        mode: str,
        tenant_id: str | None,
        artifact_status: str,
        ready_for_publish: bool,
        artifact: Mapping[str, Any] | None = None,
        context_result: ContextBuildResult | None = None,
        state: ArtifactStateResult | None = None,
        mirror: Mapping[str, Any] | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> dict[str, Any]:
        workspace, body_authority = mode.split("/", 1)
        context_receipt = (
            _canonical(context_result.receipt.as_dict()) if context_result is not None else None
        )
        state_receipt = state.as_dict() if state is not None else None
        payload: dict[str, Any] = {
            "schemaVersion": SCHEMA_VERSION,
            "operationId": key,
            "route": mode,
            "authorityMode": mode,
            "workspaceMode": workspace,
            "bodyAuthority": body_authority,
            "tenantId": tenant_id,
            "bindingId": context_result.context.binding_id if context_result is not None else None,
            "bindingGeneration": context_result.context.binding_generation if context_result is not None else None,
            "artifactStatus": artifact_status,
            "publishable": False,
            "readyForPublish": bool(ready_for_publish),
            "artifact": copy.deepcopy(dict(artifact)) if isinstance(artifact, Mapping) else None,
            "mirror": copy.deepcopy(dict(mirror)) if isinstance(mirror, Mapping) else None,
            "contextReceipt": context_receipt,
            "artifactState": state_receipt,
            "error": {"code": error_code, "message": error_message} if error_code else None,
        }
        observed_at = self._observed_at()
        if observed_at is not None:
            payload["observedAt"] = observed_at
        payload["receiptDigest"] = _digest(payload)
        payload["replayed"] = False
        return payload

    def _success_receipt(
        self,
        *,
        key: str,
        mode: str,
        tenant_id: str,
        context_result: ContextBuildResult,
        artifact: Mapping[str, Any],
        state: ArtifactStateResult,
        mirror: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._make_receipt(
            key=key,
            mode=mode,
            tenant_id=tenant_id,
            artifact_status=state.status,
            ready_for_publish=state.ready_for_publish,
            artifact=artifact,
            context_result=context_result,
            state=state,
            mirror=mirror,
        )

    def _failure_receipt(
        self,
        *,
        key: str,
        mode: str,
        tenant_id: str,
        context_result: ContextBuildResult | None = None,
        error_code: str = "pipeline_failed",
        error_message: str = "Stage-2 operation failed",
        artifact: Mapping[str, Any] | None = None,
        mirror: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._make_receipt(
            key=key,
            mode=mode,
            tenant_id=tenant_id,
            artifact_status="needs_attention",
            ready_for_publish=False,
            artifact=artifact,
            context_result=context_result,
            mirror=mirror,
            error_code=error_code,
            error_message=error_message,
        )


Stage2RuntimeFacade = Stage2Runtime
RuntimeFacade = Stage2Runtime


__all__ = [
    "IdempotencyConflict",
    "IdempotencyInProgress",
    "InMemoryReceiptStore",
    "ORGANIZATION_MODE",
    "PERSONAL_MODE",
    "ReceiptRecord",
    "ReceiptStore",
    "RuntimeFacade",
    "SCHEMA_VERSION",
    "Stage2Runtime",
    "Stage2RuntimeError",
    "Stage2RuntimeFacade",
]
