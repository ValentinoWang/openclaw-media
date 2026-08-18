from __future__ import annotations

from dataclasses import replace

import pytest

from openclaw_app.services.stage2_external_document import (
    BindingIdentity,
    ExternalDocumentWriter,
    ExternalDocumentError,
    ExternalReadbackOutcome,
    ExternalWriteOutcome,
    IdempotencyConflict,
    OrganizationWriteRequest,
)


DIGEST = "sha256:" + "a" * 64
TENANT = "tenant-1"


class FakeAdapter:
    def __init__(self, write: ExternalWriteOutcome, readback: ExternalReadbackOutcome) -> None:
        self.write_outcome = write
        self.readback_outcome = readback
        self.write_calls = 0
        self.readback_calls = 0

    def write(self, request: OrganizationWriteRequest) -> ExternalWriteOutcome:
        self.write_calls += 1
        return self.write_outcome

    def readback(
        self,
        request: OrganizationWriteRequest,
        write: ExternalWriteOutcome,
    ) -> ExternalReadbackOutcome:
        self.readback_calls += 1
        return self.readback_outcome


def binding() -> BindingIdentity:
    return BindingIdentity(TENANT, "binding-1", 7)


def request(key: str = "idem-1") -> OrganizationWriteRequest:
    return OrganizationWriteRequest(binding(), key, DIGEST)


def successful_write() -> ExternalWriteOutcome:
    return ExternalWriteOutcome("succeeded", "doc-1", "rev-1", TENANT, "binding-1", 7, DIGEST)


def successful_readback() -> ExternalReadbackOutcome:
    return ExternalReadbackOutcome("confirmed", "doc-1", "rev-1", TENANT, "binding-1", 7, DIGEST)


def test_matching_write_and_readback_is_ready_for_registration_but_not_publishable() -> None:
    adapter = FakeAdapter(successful_write(), successful_readback())

    result = ExternalDocumentWriter().write(request(), adapter)

    assert result.status == "written"
    assert result.publishable is False
    assert result.ready_for_registration is True
    assert result.remote_ref == "doc-1"
    assert result.remote_revision == "rev-1"
    assert adapter.write_calls == 1
    assert adapter.readback_calls == 1


def test_missing_or_inactive_binding_fails_before_adapter_call() -> None:
    adapter = FakeAdapter(successful_write(), successful_readback())
    writer = ExternalDocumentWriter()

    with pytest.raises(ExternalDocumentError) as missing:
        writer.write(OrganizationWriteRequest(None, "idem-missing", DIGEST), adapter)
    assert getattr(missing.value, "code") == "binding_required"

    inactive = OrganizationWriteRequest(
        BindingIdentity(TENANT, "binding-1", 7, status="revoked"), "idem-inactive", DIGEST
    )
    with pytest.raises(ExternalDocumentError) as rejected:
        writer.write(inactive, adapter)
    assert getattr(rejected.value, "code") == "binding_inactive"
    assert adapter.write_calls == 0


def test_binding_generation_mismatch_is_never_read_back() -> None:
    adapter = FakeAdapter(
        replace(successful_write(), binding_generation=8),
        successful_readback(),
    )

    result = ExternalDocumentWriter().write(request(), adapter)

    assert result.status == "needs_attention"
    assert result.publishable is False
    assert result.error_code == "external_write_needs_attention"
    assert adapter.readback_calls == 0


def test_missing_remote_ref_is_needs_attention() -> None:
    adapter = FakeAdapter(replace(successful_write(), remote_ref=None), successful_readback())

    result = ExternalDocumentWriter().write(request(), adapter)

    assert result.status == "needs_attention"
    assert result.publishable is False
    assert result.remote_ref is None
    assert adapter.readback_calls == 0


def test_readback_digest_or_revision_mismatch_is_not_publishable() -> None:
    adapter = FakeAdapter(
        successful_write(),
        replace(successful_readback(), content_digest="sha256:" + "b" * 64),
    )

    result = ExternalDocumentWriter().write(request(), adapter)

    assert result.status == "needs_attention"
    assert result.publishable is False
    assert result.error_code == "readback_incomplete"
    assert result.remote_ref == "doc-1"


def test_partial_external_success_preserves_reference_but_fails_closed() -> None:
    adapter = FakeAdapter(
        replace(successful_write(), status="failed", error_code="external_write_needs_attention"),
        successful_readback(),
    )

    result = ExternalDocumentWriter().write(request(), adapter)

    assert result.status == "needs_attention"
    assert result.publishable is False
    assert result.remote_ref == "doc-1"
    assert adapter.readback_calls == 0


def test_exact_replay_is_deterministic_and_does_not_write_twice() -> None:
    adapter = FakeAdapter(successful_write(), successful_readback())
    writer = ExternalDocumentWriter()

    first = writer.write(request(), adapter)
    replay = writer.write(request(), adapter)

    assert replay == first
    assert adapter.write_calls == 1
    assert adapter.readback_calls == 1


def test_conflicting_idempotency_payload_is_rejected() -> None:
    adapter = FakeAdapter(successful_write(), successful_readback())
    writer = ExternalDocumentWriter()
    writer.write(request(), adapter)

    with pytest.raises(IdempotencyConflict) as conflict:
        writer.write(replace(request(), content_digest="sha256:" + "b" * 64), adapter)

    assert conflict.value.code == "idempotency_conflict"
    assert adapter.write_calls == 1


def test_partial_write_readback_can_resume_without_second_external_write() -> None:
    adapter = FakeAdapter(
        successful_write(),
        replace(successful_readback(), remote_revision="wrong-revision"),
    )
    writer = ExternalDocumentWriter()

    partial = writer.write(request(), adapter)
    adapter.readback_outcome = successful_readback()
    resumed = writer.resume_readback(request(), adapter)

    assert partial.status == "needs_attention"
    assert resumed.status == "written"
    assert resumed.publishable is False
    assert resumed.ready_for_registration is True
    assert adapter.write_calls == 1
    assert adapter.readback_calls == 2


def test_resume_without_remote_identity_stays_fail_closed() -> None:
    adapter = FakeAdapter(replace(successful_write(), remote_ref=None), successful_readback())
    writer = ExternalDocumentWriter()

    partial = writer.write(request(), adapter)
    resumed = writer.resume_readback(request(), adapter)

    assert resumed == partial
    assert resumed.publishable is False
    assert adapter.write_calls == 1
    assert adapter.readback_calls == 0
