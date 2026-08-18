from __future__ import annotations

import copy
from typing import Any

import pytest

from openclaw_app.services.media_business.documents import (
    DocumentConflict,
    DocumentUnavailable,
)
from openclaw_app.services.media_business.foundation import body_checksum
from integrations.feishu.lark_document_gateway import (
    AuthenticatedLarkDocumentClient,
    ProductionLarkDocumentGateway,
)


BODY = {
    "schemaVersion": "media.document.body.v1",
    "blocks": [
        {
            "id": "block_public_1",
            "type": "paragraph",
            "attrs": {},
            "content": [{"type": "text", "text": "original", "marks": []}],
        }
    ],
}


def revision(body: dict[str, Any], version: str, *, complete: bool = True) -> dict[str, Any]:
    return {
        "remoteDocumentVersion": version,
        "complete": complete,
        "body": copy.deepcopy(body),
        "bodyChecksum": body_checksum(body),
        "blockCount": 1,
        "protectedBlockCount": 0,
        "blocks": [
            {
                "publicBlockId": "block_public_1",
                "remoteBlockId": f"remote_{version}",
                "blockChecksum": body_checksum(body["blocks"][0]),
                "isProtected": False,
                "protectionReason": None,
            }
        ],
    }


class FakeClient:
    def __init__(self) -> None:
        self.current = "v1"
        self.revisions = {"v1": revision(BODY, "v1")}
        self.receipts: dict[str, dict[str, Any]] = {}
        self.read_versions: list[str] = []
        self.write_calls = 0

    def current_version(self, document_id: str) -> str:
        return self.current

    def read_canonical_revision(self, document_id: str, version: str) -> dict[str, Any]:
        self.read_versions.append(version)
        return copy.deepcopy(self.revisions[version])

    def write_canonical_revision(self, document_id: str, body: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        self.write_calls += 1
        key = kwargs["idempotency_key"]
        expected = kwargs["expected_remote_version"]
        if key in self.receipts:
            return copy.deepcopy(self.receipts[key])
        if expected != self.current:
            raise DocumentConflict("stale remote version")
        self.current = "v2"
        self.revisions["v2"] = revision(body, "v2")
        receipt = {
            "idempotencyKey": key,
            "baseRemoteDocumentVersion": expected,
            "remoteDocumentVersion": "v2",
            "bodyChecksum": body_checksum(body),
        }
        self.receipts[key] = receipt
        return copy.deepcopy(receipt)

    def get_write_receipt(self, document_id: str, key: str) -> dict[str, Any] | None:
        receipt = self.receipts.get(key)
        return copy.deepcopy(receipt) if receipt else None


def gateway(client: FakeClient) -> ProductionLarkDocumentGateway:
    return ProductionLarkDocumentGateway(client, lambda tenant, artifact: "doc_123")


def test_read_without_version_first_pins_and_then_reads_exact_revision() -> None:
    client = FakeClient()

    snapshot = gateway(client).read_revision("tenant_1", "artifact_1", None)

    assert snapshot.remote_document_version == "v1"
    assert client.read_versions == ["v1"]


def test_read_fails_closed_for_incomplete_or_different_revision() -> None:
    client = FakeClient()
    client.revisions["v1"]["complete"] = False
    with pytest.raises(DocumentUnavailable, match="inventory is incomplete"):
        gateway(client).read_revision("tenant_1", "artifact_1", "v1")

    client.revisions["v1"]["complete"] = True
    client.revisions["v1"]["remoteDocumentVersion"] = "v2"
    with pytest.raises(DocumentConflict, match="different document version"):
        gateway(client).read_revision("tenant_1", "artifact_1", "v1")


def test_read_rejects_incomplete_mapping_and_protection_inventory() -> None:
    client = FakeClient()
    client.revisions["v1"]["blockCount"] = 2
    with pytest.raises(DocumentUnavailable, match="inventory count"):
        gateway(client).read_revision("tenant_1", "artifact_1", "v1")

    client.revisions["v1"]["blockCount"] = 1
    client.revisions["v1"]["protectedBlockCount"] = 1
    with pytest.raises(DocumentUnavailable, match="protected block count"):
        gateway(client).read_revision("tenant_1", "artifact_1", "v1")


def test_read_rejects_block_checksum_that_does_not_match_canonical_block() -> None:
    client = FakeClient()
    client.revisions["v1"]["blocks"][0]["blockChecksum"] = "f" * 64

    with pytest.raises(DocumentConflict, match="block checksum"):
        gateway(client).read_revision("tenant_1", "artifact_1", "v1")


def test_save_is_idempotent_and_requires_exact_version_readback() -> None:
    client = FakeClient()
    changed = copy.deepcopy(BODY)
    changed["blocks"][0]["content"][0]["text"] = "changed"

    first = gateway(client).save_draft(
        "tenant_1", "artifact_1", changed, "v1", "sync_00000001"
    )
    second = gateway(client).save_draft(
        "tenant_1", "artifact_1", changed, "v1", "sync_00000001"
    )

    assert first == second
    assert first.remote_document_version == "v2"
    assert client.read_versions == ["v1", "v2", "v1", "v2"]


def test_save_rejects_changes_to_protected_blocks_before_external_write() -> None:
    client = FakeClient()
    client.revisions["v1"]["blocks"][0].update(
        {"isProtected": True, "protectionReason": "synced_block"}
    )
    client.revisions["v1"]["protectedBlockCount"] = 1
    changed = copy.deepcopy(BODY)
    changed["blocks"][0]["content"][0]["text"] = "changed"

    with pytest.raises(Exception) as caught:
        gateway(client).save_draft(
            "tenant_1", "artifact_1", changed, "v1", "sync_00000001"
        )

    assert getattr(caught.value, "code", None) == "unsupported_document_block"
    assert client.write_calls == 0


def test_reconcile_requires_matching_durable_receipt() -> None:
    client = FakeClient()
    with pytest.raises(DocumentUnavailable, match="no durable external receipt"):
        gateway(client).reconcile_save(
            "tenant_1", "artifact_1", "sync_00000001", "v1"
        )

    client.current = "v2"
    with pytest.raises(DocumentConflict, match="advanced without a matching"):
        gateway(client).reconcile_save(
            "tenant_1", "artifact_1", "sync_00000001", "v1"
        )


def test_reconcile_proves_receipt_against_fixed_revision_and_checksum() -> None:
    client = FakeClient()
    changed = copy.deepcopy(BODY)
    changed["blocks"][0]["content"][0]["text"] = "changed"
    client.write_canonical_revision(
        "doc_123",
        changed,
        expected_remote_version="v1",
        idempotency_key="sync_00000001",
    )

    snapshot = gateway(client).reconcile_save(
        "tenant_1", "artifact_1", "sync_00000001", "v1"
    )

    assert snapshot.remote_document_version == "v2"
    assert snapshot.body == changed


class FakeAuthenticatedFeishuService:
    def __init__(self, responses: list[dict[str, Any] | Exception]) -> None:
        self._responses = list(responses)
        self.requests: list[
            tuple[str, str, dict[str, Any] | None, dict[str, Any] | None]
        ] = []

    def _request(self, method: str, path: str, *, json_body: dict[str, Any] | None = None, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self.requests.append(
            (method, path, copy.deepcopy(params), copy.deepcopy(json_body))
        )
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def test_callout_reuses_native_container_text_child_with_styled_content() -> None:
    service = FakeAuthenticatedFeishuService([{}])
    client = AuthenticatedLarkDocumentClient(service)
    calls: list[tuple[str, list[dict[str, Any]]]] = []

    def create_children(
        _document_id: str,
        parent_id: str,
        children: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        calls.append((parent_id, copy.deepcopy(children)))
        return [
            {
                "block_id": "remote_callout",
                "children": ["remote_callout_text"],
            }
        ]

    client._create_children = create_children  # type: ignore[method-assign]
    client.current_version = lambda _document_id: "v1"  # type: ignore[method-assign]
    remote_ids = client._write_block(
        "doc_123",
        "doc_123",
        {
            "id": "callout_1",
            "type": "callout",
            "attrs": {},
            "content": [
                {"type": "text", "text": "重点", "marks": ["bold"]},
            ],
        },
        {},
    )

    assert remote_ids == ["remote_callout", "remote_callout_text"]
    assert calls == [("doc_123", [{"block_type": 19, "callout": {}}])]
    assert service.requests == [
        (
            "PATCH",
            "/docx/v1/documents/doc_123/blocks/remote_callout_text",
            {"document_revision_id": "v1"},
            {
                "update_text_elements": {
                    "elements": [
                        {
                            "text_run": {
                                "content": "重点",
                                "text_element_style": {"bold": True},
                            }
                        }
                    ]
                }
            },
        )
    ]


def test_table_reuses_each_native_cell_text_child() -> None:
    service = FakeAuthenticatedFeishuService([{}])
    client = AuthenticatedLarkDocumentClient(service)
    calls: list[tuple[str, list[dict[str, Any]]]] = []

    def create_children(
        _document_id: str,
        parent_id: str,
        children: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        calls.append((parent_id, copy.deepcopy(children)))
        return [{"block_id": "remote_table", "children": ["remote_cell"]}]

    client._create_children = create_children  # type: ignore[method-assign]
    client.current_version = lambda _document_id: "v1"  # type: ignore[method-assign]
    client._list_children = lambda *_args: [  # type: ignore[method-assign]
        {"block_id": "remote_cell_text", "block_type": 2}
    ]

    remote_ids = client._write_table(
        "doc_123",
        "doc_123",
        [
            {
                "cells": [
                    {
                        "content": [
                            {"type": "text", "text": "单元格", "marks": ["bold"]}
                        ]
                    }
                ]
            }
        ],
    )

    assert remote_ids == ["remote_table", "remote_cell", "remote_cell_text"]
    assert calls == [
        (
            "doc_123",
            [
                {
                    "block_type": 31,
                    "table": {"property": {"row_size": 1, "column_size": 1}},
                }
            ],
        )
    ]
    assert service.requests == [
        (
            "PATCH",
            "/docx/v1/documents/doc_123/blocks/remote_cell_text",
            {"document_revision_id": "v1"},
            {
                "update_text_elements": {
                    "elements": [
                        {
                            "text_run": {
                                "content": "单元格",
                                "text_element_style": {"bold": True},
                            }
                        }
                    ]
                }
            },
        )
    ]


def test_fixed_revision_child_read_retries_only_99991400(monkeypatch) -> None:
    service = FakeAuthenticatedFeishuService(
        [
            RuntimeError("Feishu API returned code=99991400, msg=temporary busy"),
            {
                "data": {
                    "document_revision_id": 42,
                    "items": [{"block_id": "remote_text", "block_type": 2}],
                }
            },
        ]
    )
    client = AuthenticatedLarkDocumentClient(service)
    pauses: list[float] = []
    monkeypatch.setattr("integrations.feishu.lark_document_gateway.time.sleep", pauses.append)

    blocks = client._list_children("doc_123", "doc_123", "42")

    assert [block["block_id"] for block in blocks] == ["remote_text"]
    assert [request[0] for request in service.requests] == ["GET", "GET"]
    assert pauses == [0.2]


def test_fixed_revision_child_read_does_not_retry_other_errors(monkeypatch) -> None:
    service = FakeAuthenticatedFeishuService(
        [RuntimeError("Feishu API returned code=99991401, msg=not retryable")]
    )
    client = AuthenticatedLarkDocumentClient(service)
    pauses: list[float] = []
    monkeypatch.setattr("integrations.feishu.lark_document_gateway.time.sleep", pauses.append)

    with pytest.raises(RuntimeError, match="99991401"):
        client._list_children("doc_123", "doc_123", "42")

    assert len(service.requests) == 1
    assert pauses == []


def test_callout_decode_reads_styled_native_text_child() -> None:
    decoded = AuthenticatedLarkDocumentClient._decode_native(
        {
            "block_id": "remote_callout",
            "block_type": 19,
            "callout": {},
            "_hydrated_children": [
                {
                    "block_id": "remote_callout_text",
                    "block_type": 2,
                    "text": {
                        "elements": [
                            {
                                "text_run": {
                                    "content": "重点",
                                    "text_element_style": {"bold": True},
                                }
                            }
                        ]
                    },
                }
            ],
        },
        0,
    )

    assert decoded == {
        "id": "remote_callout",
        "type": "callout",
        "attrs": {},
        "content": [{"type": "text", "text": "重点", "marks": ["bold"]}],
    }
