from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest

from openclaw_app.services.stage2_external_document import (
    BindingIdentity,
    ExternalDocumentWriter,
    ExternalReadbackOutcome,
    ExternalWriteOutcome,
    IdempotencyConflict,
    OrganizationWriteRequest,
)
from openclaw_app.services.stage2_production_factory import _FeishuOrganizationAdapter


DIGEST = "sha256:" + "a" * 64
TENANT_A = "tenant-a"
TENANT_B = "tenant-b"


def _binding(tenant_id: str = TENANT_A, binding_id: str = "binding-a", generation: int = 1) -> BindingIdentity:
    return BindingIdentity(tenant_id, binding_id, generation)


def _record(binding: BindingIdentity, *, space_id: str | None = None, parent: str | None = None) -> dict[str, object]:
    return {
        "tenantId": binding.tenant_id,
        "bindingId": binding.binding_id,
        "generation": binding.binding_generation,
        "status": "active",
        "credentialGeneration": f"credential-{binding.binding_generation}",
        "spaceId": space_id or f"space-{binding.tenant_id}",
        "parentNodeToken": parent or f"parent-{binding.tenant_id}",
        "trustedOpenUrl": f"https://{binding.tenant_id}.feishu.cn/wiki/parent-{binding.tenant_id}",
    }


def _request(binding: BindingIdentity, key: str = "idem-1", *, body: str = "Body") -> OrganizationWriteRequest:
    return OrganizationWriteRequest(
        binding,
        key,
        DIGEST,
        title="Document",
        body=body,
        content_format="markdown",
    )


class FakeFeishuService:
    def __init__(self) -> None:
        self.mode = "knowledge_base"
        self.knowledge_base_spaces = [
            {"space_id": "default-space", "parent_node_token": "default-parent", "pattern": "*"}
        ]
        self.knowledge_base_space_id = "default-space"
        self.knowledge_base_parent_node_token = "default-parent"
        self.folder_token = "global-folder"
        self.revision = "rev-1"
        self.readback_text = "Body"
        self.readback_digest: str | None = None
        self.return_space_id: str | None = None
        self.return_url = "https://tenant-a.feishu.cn/wiki/node-1"
        self.append_calls: list[dict[str, object]] = []
        self.readback_calls = 0
        self.on_append = None
        self.delay = 0.0

    def _content_to_docx_blocks(self, body: str) -> list[dict[str, str]]:
        return [{"text": body}]

    def append_entry_blocks(self, title: str, blocks: list[dict[str, str]]) -> dict[str, str]:
        target = dict(self.knowledge_base_spaces[0])
        self.append_calls.append(
            {
                "title": title,
                "space_id": target.get("space_id"),
                "parent_node_token": target.get("parent_node_token"),
                "folder_token": self.folder_token,
            }
        )
        if callable(self.on_append):
            self.on_append()
        if self.delay:
            time.sleep(self.delay)
        return {
            "status": "synced",
            "doc": self.return_url,
            "document_id": "doc-1",
            "space_id": self.return_space_id or str(target.get("space_id")),
        }

    def _request(self, method: str, path: str, **kwargs):
        return {"data": {"document": {"revision_id": self.revision}}}

    def read_document_text(self, url: str) -> dict[str, object]:
        self.readback_calls += 1
        result: dict[str, object] = {"ok": True, "text": self.readback_text}
        if self.readback_digest is not None:
            result["contentDigest"] = self.readback_digest
        return result

    def resolve_document_reference(self, url: str) -> dict[str, str]:
        return {"document_id": "doc-1"}


def _adapter(service: FakeFeishuService, records: dict[str, dict[str, object]]) -> _FeishuOrganizationAdapter:
    return _FeishuOrganizationAdapter(service, lambda tenant_id: records.get(tenant_id))


def test_binding_mismatch_and_missing_resolver_fail_closed_before_write() -> None:
    service = FakeFeishuService()
    requested = _binding()
    records = {TENANT_A: _record(_binding(binding_id="different-binding"))}

    result = ExternalDocumentWriter().write(_request(requested), _adapter(service, records))

    assert result.status == "needs_attention"
    assert result.error_code == "write_failed"
    assert service.append_calls == []
    assert service.knowledge_base_spaces[0]["space_id"] == "default-space"

    result_without_resolver = ExternalDocumentWriter().write(
        _request(requested, key="missing-resolver"),
        _FeishuOrganizationAdapter(service),
    )
    assert result_without_resolver.status == "needs_attention"
    assert service.append_calls == []


@pytest.mark.parametrize(
    "url",
    ["http://tenant-a.feishu.cn/wiki/node-1", "javascript:alert(1)", "https://example.com/wiki/node-1"],
)
def test_unsafe_remote_or_binding_url_never_becomes_success(url: str) -> None:
    service = FakeFeishuService()
    service.return_url = url
    binding = _binding()
    records = {TENANT_A: _record(binding)}
    if url.startswith("javascript"):
        records[TENANT_A] = {**records[TENANT_A], "trustedOpenUrl": url}

    result = ExternalDocumentWriter().write(_request(binding), _adapter(service, records))

    assert result.status == "needs_attention"
    assert result.publishable is False
    assert service.readback_calls == 0


def test_concurrent_binding_targets_are_isolated_and_restored() -> None:
    service = FakeFeishuService()
    service.delay = 0.02
    binding_a = _binding(TENANT_A, "binding-a", 1)
    binding_b = _binding(TENANT_B, "binding-b", 2)
    records = {TENANT_A: _record(binding_a), TENANT_B: _record(binding_b)}
    adapter = _adapter(service, records)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda item: adapter.write(_request(item[0], item[1])),
                ((binding_a, "idem-a"), (binding_b, "idem-b")),
            )
        )

    assert [result.status for result in results] == ["written", "written"]
    assert [(call["space_id"], call["parent_node_token"], call["folder_token"]) for call in service.append_calls] == [
        ("space-tenant-a", "parent-tenant-a", ""),
        ("space-tenant-b", "parent-tenant-b", ""),
    ]
    assert service.knowledge_base_spaces[0]["space_id"] == "default-space"
    assert service.knowledge_base_parent_node_token == "default-parent"
    assert service.folder_token == "global-folder"


def test_binding_change_during_write_is_attention_and_readback_is_recoverable() -> None:
    service = FakeFeishuService()
    binding = _binding()
    changed = _binding(binding.tenant_id, "binding-b", 2)
    records = {TENANT_A: _record(binding)}
    service.on_append = lambda: records.__setitem__(TENANT_A, _record(changed))
    writer = ExternalDocumentWriter()
    request = _request(binding, "binding-change")
    adapter = _adapter(service, records)

    partial = writer.write(request, adapter)

    assert partial.status == "needs_attention"
    assert partial.error_code == "binding_changed"
    assert partial.remote_ref is not None
    assert partial.remote_revision == "rev-1"
    assert service.readback_calls == 0

    records[TENANT_A] = _record(binding)
    resumed = writer.resume_readback(request, adapter)
    assert resumed.status == "written"
    assert resumed.remote_ref == partial.remote_ref
    assert service.readback_calls == 1
    assert len(service.append_calls) == 1


@pytest.mark.parametrize("mismatch", ["revision", "content"])
def test_readback_version_or_content_mismatch_fails_closed(mismatch: str) -> None:
    service = FakeFeishuService()
    binding = _binding()
    records = {TENANT_A: _record(binding)}
    writer = ExternalDocumentWriter()
    adapter = _adapter(service, records)
    if mismatch == "revision":
        service.revision = "rev-1"
        original_request = _request(binding, "revision-mismatch")
        service.revision = "rev-2"
    else:
        original_request = _request(binding, "content-mismatch")
        service.readback_text = "different content"

    result = writer.write(original_request, adapter)

    assert result.status == "needs_attention"
    assert result.publishable is False
    assert result.error_code == "readback_incomplete"
    assert len(service.append_calls) == 1
    assert service.readback_calls == 1


def test_idempotent_replay_and_conflicting_payload_do_not_write_again() -> None:
    service = FakeFeishuService()
    binding = _binding()
    adapter = _adapter(service, {TENANT_A: _record(binding)})
    writer = ExternalDocumentWriter()
    request = _request(binding, "replay")

    first = writer.write(request, adapter)
    replay = writer.write(request, adapter)

    assert replay == first
    assert len(service.append_calls) == 1
    assert service.readback_calls == 1
    with pytest.raises(IdempotencyConflict):
        writer.write(replace(request, body="different body"), adapter)
    assert len(service.append_calls) == 1


def test_missing_remote_revision_and_target_response_are_never_successful() -> None:
    service = FakeFeishuService()
    binding = _binding()
    records = {TENANT_A: _record(binding)}
    service.revision = ""
    result = ExternalDocumentWriter().write(_request(binding, "missing-revision"), _adapter(service, records))
    assert result.status == "needs_attention"
    assert result.error_code == "write_failed"

    service.revision = "rev-1"
    service.return_space_id = "wrong-space"
    result = ExternalDocumentWriter().write(_request(binding, "wrong-target"), _adapter(service, records))
    assert result.status == "needs_attention"
    assert result.error_code == "write_failed"
