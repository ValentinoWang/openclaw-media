from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from openclaw_app.services.stage2_artifact_state import (
    ArtifactStateError,
    ArtifactStateMachine,
    IdempotencyConflict,
)


DIGEST = "sha256:" + "a" * 64


def personal(**overrides):
    value = {
        "tenantId": "tenant-personal",
        "authorityMode": "personal_web/internal",
        "idempotencyKey": "idem-1",
        "contentDigest": DIGEST,
        "writeStatus": "written",
        "registrationStatus": "registered",
        "readbackStatus": "confirmed",
        "artifactRef": "artifact-1",
        "revision": "revision-1",
        "readbackContentDigest": DIGEST,
        "readbackArtifactRef": "artifact-1",
        "readbackRevision": "revision-1",
    }
    value.update(overrides)
    return value


def organization(**overrides):
    value = {
        "tenantId": "tenant-org",
        "authorityMode": "organization_lark/lark",
        "idempotencyKey": "idem-org-1",
        "contentDigest": DIGEST,
        "writeStatus": "written",
        "registrationStatus": "registered",
        "readbackStatus": "confirmed",
        "artifactRef": "artifact-org-1",
        "revision": "mirror-1",
        "bindingId": "binding-1",
        "bindingGeneration": 4,
        "remoteRef": "doc-1",
        "remoteRevision": "remote-1",
        "readbackContentDigest": DIGEST,
        "readbackArtifactRef": "artifact-org-1",
        "readbackRevision": "mirror-1",
        "readbackBindingId": "binding-1",
        "readbackBindingGeneration": 4,
        "readbackRemoteRef": "doc-1",
        "readbackRemoteRevision": "remote-1",
    }
    value.update(overrides)
    return value


def test_personal_artifact_reaches_verified_without_external_identity() -> None:
    result = ArtifactStateMachine().record(personal())
    assert result.status == "readback_verified"
    assert result.ready_for_publish is True
    assert result.publishable is False
    assert result.receipt["remoteRef"] is None


def test_organization_requires_binding_identity() -> None:
    with pytest.raises(ArtifactStateError) as error:
        ArtifactStateMachine().record(organization(bindingId=None))
    assert error.value.code == "binding_required"


def test_personal_rejects_remote_identity() -> None:
    with pytest.raises(ArtifactStateError) as error:
        ArtifactStateMachine().record(personal(remoteRef="doc-1"))
    assert error.value.code == "personal_remote_authority_forbidden"


def test_missing_registration_fails_closed_and_preserves_refs() -> None:
    result = ArtifactStateMachine().record(organization(registrationStatus="failed"))
    assert result.status == "needs_attention"
    assert result.error_code == "registration_failed"
    assert result.ready_for_publish is False
    assert result.receipt["remoteRef"] == "doc-1"


def test_readback_mismatch_fails_closed() -> None:
    result = ArtifactStateMachine().record(organization(readbackRemoteRevision="remote-2"))
    assert result.error_code == "readback_incomplete"
    assert result.publishable is False


def test_partial_write_preserves_auditable_reference() -> None:
    result = ArtifactStateMachine().record(organization(writeStatus="failed"))
    assert result.error_code == "write_failed"
    assert result.receipt["artifactRef"] == "artifact-org-1"
    assert result.receipt["remoteRef"] == "doc-1"


def test_browser_authority_claims_are_rejected() -> None:
    with pytest.raises(ArtifactStateError) as error:
        ArtifactStateMachine().record(personal(browserClaims={"tenantId": "other"}))
    assert error.value.code == "authority_override_forbidden"


def test_exact_replay_is_deterministic_and_conflict_is_rejected() -> None:
    state = ArtifactStateMachine()
    first = state.record(personal())
    replay = state.record(personal())
    assert replay.replayed is True
    assert replay.receipt == first.receipt
    with pytest.raises(IdempotencyConflict):
        state.record(personal(contentDigest="sha256:" + "b" * 64))


def test_concurrent_exact_replay_keeps_one_receipt() -> None:
    state = ArtifactStateMachine()
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: state.record(personal()), range(16)))
    assert sum(result.replayed for result in results) == 15
    assert len({result.receipt["receiptDigest"] for result in results}) == 1
