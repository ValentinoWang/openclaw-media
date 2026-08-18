from __future__ import annotations

import copy

import pytest

from openclaw_app.services.media_business.documents import prepare_autosave, prepare_export
from openclaw_app.services.media_business.foundation import (
    Conflict,
    Forbidden,
    NotFound,
    ProtectedDocumentBlock,
    ResultKind,
    ServiceResult,
    TenantContext,
    Validation,
    body_checksum,
    public_projection,
    require_context,
    validate_body,
)


BODY = {
    "schemaVersion": "media.document.body.v1",
    "blocks": [
        {
            "id": "blk_paragraph",
            "type": "paragraph",
            "attrs": {},
            "content": [{"type": "text", "text": "body", "marks": ["bold"]}],
        }
    ],
}


def table_body(rows: int, columns: int) -> dict:
    return {
        "schemaVersion": "media.document.body.v1",
        "blocks": [
            {
                "id": "blk_table",
                "type": "table",
                "attrs": {"semanticPurpose": "general", "headerRowCount": 1},
                "rows": [
                    {
                        "id": f"blk_row_{row}",
                        "cells": [
                            {
                                "id": f"blk_cell_{row}_{column}",
                                "content": [],
                            }
                            for column in range(columns)
                        ],
                    }
                    for row in range(rows)
                ],
            }
        ],
    }


def test_tenant_context_is_mandatory_and_cross_tenant_reads_are_masked() -> None:
    with pytest.raises(Forbidden):
        require_context(None)
    with pytest.raises(Forbidden):
        require_context(TenantContext("", "user_public"))
    with pytest.raises(NotFound):
        require_context(TenantContext("tenant_a", "user_public"), "tenant_b")

    context = TenantContext("tenant_a", "user_public")
    assert require_context(context, "tenant_a") is context


def test_admin_target_tenant_requires_a_nonblank_audit_reason() -> None:
    for reason in (None, "", "  \t"):
        with pytest.raises(Forbidden, match="audit reason"):
            require_context(
                TenantContext("admin_home", "admin_public", is_admin=True, audit_reason=reason),
                "tenant_target",
            )

    context = TenantContext(
        "admin_home",
        "admin_public",
        is_admin=True,
        audit_reason="case 2026-08-05-01",
    )
    assert require_context(context, "tenant_target") is context


def test_service_results_distinguish_all_non_success_outcomes() -> None:
    assert ServiceResult.empty().kind is ResultKind.EMPTY
    assert ServiceResult.not_found().kind is ResultKind.NOT_FOUND
    assert ServiceResult.forbidden().kind is ResultKind.FORBIDDEN
    assert ServiceResult.conflict().kind is ResultKind.CONFLICT
    assert ServiceResult.validation("bad body").kind is ResultKind.VALIDATION
    assert ServiceResult.validation("bad body").message == "bad body"


@pytest.mark.parametrize(
    "field",
    [
        "tenant_id",
        "tenantId",
        "feishuRecordId",
        "lark_table_url",
        "localPath",
        "rawPrompt",
        "raw_model_response",
        "accessToken",
        "credentialValue",
    ],
)
def test_public_projection_recursively_rejects_forbidden_fields(field: str) -> None:
    with pytest.raises(Validation, match=field):
        public_projection({"safe": [{"nested": {field: "private"}}]})


def test_public_projection_returns_an_independent_safe_value() -> None:
    source = {"schemaVersion": "1", "items": [{"publicResourceId": "resource_public"}]}
    projected = public_projection(source)
    assert projected == source
    assert projected is not source
    assert projected["items"] is not source["items"]


def test_document_body_checksum_is_deterministic_without_mutating_the_body() -> None:
    reordered = {"blocks": copy.deepcopy(BODY["blocks"]), "schemaVersion": BODY["schemaVersion"]}
    before = copy.deepcopy(BODY)
    assert body_checksum(BODY) == body_checksum(reordered)
    assert len(body_checksum(BODY)) == 64
    assert BODY == before


@pytest.mark.parametrize(
    "body",
    [
        None,
        {},
        {"schemaVersion": "media.document.body.v2", "blocks": []},
        {"schemaVersion": "media.document.body.v1", "blocks": {}, "extra": True},
        {
            "schemaVersion": "media.document.body.v1",
            "blocks": [{"id": "bad", "type": "unknown", "attrs": {}}],
        },
        {
            "schemaVersion": "media.document.body.v1",
            "blocks": [{"id": "bad", "type": "paragraph", "attrs": {}, "content": []}],
        },
        {
            "schemaVersion": "media.document.body.v1",
            "blocks": [
                {
                    "id": "blk_paragraph",
                    "type": "paragraph",
                    "attrs": {},
                    "content": [{"type": "text", "text": "x", "marks": ["rainbow"]}],
                }
            ],
        },
    ],
)
def test_document_body_v1_rejects_malformed_payloads(body: object) -> None:
    with pytest.raises(Validation):
        validate_body(body)


def test_document_body_v1_accepts_the_frozen_shape() -> None:
    assert validate_body(copy.deepcopy(BODY)) == BODY
    assert validate_body(table_body(9, 9))["blocks"][0]["type"] == "table"


@pytest.mark.parametrize("rows, columns", [(10, 1), (1, 10), (9, 10)])
def test_lark_table_shape_enforces_9_by_9_and_81_cells(rows: int, columns: int) -> None:
    with pytest.raises(Validation) as caught:
        validate_body(table_body(rows, columns))
    assert caught.value.code == "lark_table_shape_unsupported"


def test_autosave_is_draft_only_and_preserves_protected_lark_blocks() -> None:
    changed = copy.deepcopy(BODY)
    changed["blocks"][0]["content"][0]["text"] = "changed"

    with pytest.raises(Conflict):
        prepare_autosave(BODY, "ready")
    with pytest.raises(ProtectedDocumentBlock) as caught:
        prepare_autosave(
            changed,
            "draft",
            previous_body=BODY,
            protected_block_ids={"blk_paragraph"},
            targeted_block_ids={"blk_paragraph"},
        )
    assert caught.value.code == "unsupported_document_block"
    assert caught.value.block_ids == ("blk_paragraph",)

    saved = prepare_autosave(
        BODY,
        "draft",
        previous_body=BODY,
        protected_block_ids={"blk_paragraph"},
    )
    assert saved == {"body": BODY, "bodyChecksum": body_checksum(BODY)}


def test_export_is_ready_only_and_rejects_protected_lark_blocks() -> None:
    with pytest.raises(Conflict):
        prepare_export(BODY, "draft")
    with pytest.raises(ProtectedDocumentBlock) as caught:
        prepare_export(BODY, "ready", protected_block_ids={"blk_paragraph"})
    assert caught.value.code == "unsupported_document_block"
    assert caught.value.block_ids == ("blk_paragraph",)

    assert prepare_export(BODY, "ready") == {"sourceBodyChecksum": body_checksum(BODY)}
