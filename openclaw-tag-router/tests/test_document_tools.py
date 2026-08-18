from __future__ import annotations

import copy
import io
import os
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime
from unittest.mock import patch

from openclaw_app.models.message import Message
from openclaw_app.models.task import TaskResult
from openclaw_app.router.commercial_delivery import CommercialDeliveryMixin, COMMERCIAL_DELIVERY_FIELD_SPECS
from openclaw_app.router.document_tools import DocumentToolsMixin
from openclaw_app.router.tag_router import TagRouter
from openclaw_app.services.document_edit_contract import (
    DOCUMENT_EDIT_CONTRACT_OWNER,
    DOCUMENT_EDIT_DOWNSTREAM_CONSUMER_TEST,
    DOCUMENT_EDIT_MIGRATION_PLAN,
    DOCUMENT_EDIT_PATCH_CONTRACT_ID,
    DocumentEditPatchPlan,
    load_document_edit_op_whitelist,
)
from openclaw_app.services.feishu_service import FeishuService


class DocumentToolsHarness(DocumentToolsMixin):
    pass


class FakeArchiveService:
    class Entry:
        local_path = "/tmp/openclaw-document-edit-archive.md"
        frontmatter = {"id": "document_edit_test"}

    def __init__(self) -> None:
        self.rows: list[tuple[str, str]] = []
        self.frontmatter: dict[str, object] = {}

    def save_archive(self, _message: Message, _title: str, rows: list[tuple[str, str]], _extra: dict) -> "FakeArchiveService.Entry":
        self.rows = rows
        return self.Entry()

    def update_frontmatter(self, _path: str, data: dict[str, object]) -> None:
        self.frontmatter.update(data)


class FakeContentFlowClient:
    def __init__(
        self,
        content: str,
        record_fields: dict[str, object] | None = None,
        *,
        omit_required_schema: bool = False,
    ) -> None:
        self.content = content
        self.record_fields = record_fields or {}
        self.omit_required_schema = omit_required_schema
        self.calls: list[tuple[object, ...]] = []

    def _content_flow_env(self) -> dict[str, str]:
        return {}

    def _call_postprocess_json(self, *_args: object, **_kwargs: object) -> dict[str, object]:
        self.calls.append(_args)
        if self.omit_required_schema:
            return {"status": "done", "content": self.content, "changed_sections": ["标题"]}
        user_payload = json.loads(str(_args[1])) if len(_args) > 1 else {}
        compact_view = str(user_payload.get("compact_view") or "")
        target_block_id = "block-title"
        for line in compact_view.splitlines():
            if line.startswith("[") and "PROTECTED" not in line:
                target_block_id = line.split("]", 1)[0].strip("[").split("|", 1)[0]
                break
        result: dict[str, object] = {
            "status": "done",
            "operations": [
                {
                    "op": "replace_text",
                    "operation_id": "op-title",
                    "block_id": target_block_id,
                    "new_text": self.content,
                    "source_evidence": ["fixture"],
                }
            ],
            "manual_actions": [],
            "changed_sections": ["标题"],
        }
        if self.record_fields:
            result["commercial_delivery_record_fields"] = self.record_fields
        return result


class StageAwareContentFlowClient:
    def __init__(self, stage1_result: dict[str, object], stage2_result: dict[str, object] | list[dict[str, object]]) -> None:
        self.stage1_result = stage1_result
        self.stage2_results = stage2_result if isinstance(stage2_result, list) else [stage2_result]
        self.stage2_index = 0
        self.calls: list[tuple[object, ...]] = []
        self.payloads: list[dict[str, object]] = []
        self.kwargs: list[dict[str, object]] = []

    def _content_flow_env(self) -> dict[str, str]:
        return {}

    def _call_postprocess_json(self, *_args: object, **kwargs: object) -> dict[str, object]:
        self.calls.append(_args)
        self.kwargs.append(kwargs)
        user_payload = json.loads(str(_args[1])) if len(_args) > 1 else {}
        self.payloads.append(user_payload)
        planner_stage = str(user_payload.get("planner_stage") or "")
        if planner_stage == "stage1_locate_targets":
            return copy.deepcopy(self.stage1_result)
        if planner_stage == "stage2_generate_patch":
            if self.stage2_index >= len(self.stage2_results):
                raise AssertionError("unexpected extra stage2_generate_patch call")
            result = copy.deepcopy(self.stage2_results[self.stage2_index])
            self.stage2_index += 1
            return result
        raise AssertionError(f"unexpected planner_stage: {planner_stage}")


class SafeFeishuService:
    def __init__(
        self,
        *,
        unsupported: bool = False,
        changed: bool = False,
        fail_replace: bool = False,
        readback_fail: bool = False,
        empty_record_readback: bool = False,
        stale_record_readback: bool = False,
        source_text: str | None = None,
        patchable_blocks: list[dict[str, object]] | None = None,
        protected_blocks: list[dict[str, object]] | None = None,
        protected_table_shapes: list[dict[str, object]] | None = None,
        records: list[dict[str, object]] | None = None,
    ) -> None:
        self.calls: list[str] = []
        self.unsupported = unsupported
        self.changed = changed
        self.fail_replace = fail_replace
        self.readback_fail = readback_fail
        self.empty_record_readback = empty_record_readback
        self.stale_record_readback = stale_record_readback
        self.replaced_content = ""
        self.source_text = source_text or "# 原标题\n\n## 正文\n\n这是原文档的稳定正文，长度足够用于修改测试。"
        self.patchable_blocks = patchable_blocks
        self.protected_blocks = protected_blocks
        self.protected_table_shapes = protected_table_shapes
        self.records = records or []
        self.record_fields: dict[str, object] = {}

    def prepare_document_edit_source(self, doc_url: str, **_kwargs: object) -> dict[str, object]:
        self.calls.append("preflight")
        payload: dict[str, object] = {
            "ok": True,
            "url": doc_url,
            "document_id": "doc-test",
            "text": self.source_text,
            "source_hash": "hash-before",
            "snapshot_path": "/tmp/openclaw-document-edit-snapshot.json",
            "document_family": "generic_docx",
        }
        if self.unsupported:
            payload["unsupported_blocks"] = [{"block_id": "blk-img", "block_type": 27}]
        return payload

    def prepare_document_edit_patch_source(self, doc_url: str, **_kwargs: object) -> dict[str, object]:
        self.calls.append("patch_preflight")
        protected_blocks = list(self.protected_blocks or [])
        if self.unsupported:
            protected_blocks.append({"block_id": "blk-img", "block_type": 27, "kind": "image", "path": "1"})
        patchable_blocks = self.patchable_blocks or [
            {
                "block_id": "block-title",
                "path": ["0"],
                "block_type": "2",
                "text": self.source_text,
                "protected": False,
                "has_non_plain_text_elements": False,
            }
        ]
        protected_table_shapes = self.protected_table_shapes or []
        return {
            "ok": True,
            "status": "document_edit_patch_preflight_ok",
            "url": doc_url,
            "document_id": "doc-test",
            "text": self.source_text,
            "source_hash": "hash-before",
            "revision_token": "docx-sha256:hash-before",
            "snapshot_path": "/tmp/openclaw-document-edit-snapshot.json",
            "snapshot_depth": 1,
            "snapshot_max_blocks": 500,
            "document_family": "generic_docx",
            "root_blocks": [
                {
                    "block_id": "block-title",
                    "path": "0",
                    "block_type": 2,
                    "kind": "text",
                    "text": self.source_text,
                    "is_plain_text_patchable": True,
                },
                *protected_blocks,
            ],
            "patchable_blocks": patchable_blocks,
            "protected_block_ids": [item["block_id"] for item in protected_blocks],
            "protected_blocks": protected_blocks,
            "protected_table_shapes": protected_table_shapes,
            "safe_to_patch": True,
        }

    def verify_document_edit_source_unchanged(self, _source: dict[str, object]) -> dict[str, object]:
        self.calls.append("hash")
        if self.changed:
            return {"ok": False, "status": "document_changed_since_read", "reply": "changed"}
        return {"ok": True}

    def replace_document_url_safely(self, doc_url: str, content: str, **_kwargs: object) -> dict[str, object]:
        self.calls.append("replace")
        if self.fail_replace:
            return {"ok": False, "status": "document_edit_replace_failed", "error": "write failed"}
        self.replaced_content = content
        return {"ok": True, "doc": doc_url, "document_id": "doc-test"}

    def apply_document_edit_patch_plan(self, plan_payload: dict[str, object]) -> dict[str, object]:
        self.calls.append("patch_apply")
        if self.changed:
            return {"ok": False, "status": "document_changed_since_read", "reply": "changed"}
        if self.fail_replace:
            return {"ok": False, "status": "document_edit_patch_apply_failed", "error": "write failed"}
        operations = list(plan_payload.get("operations") or [])
        self.replaced_content = "\n".join(str(item.get("new_text") or "") for item in operations if isinstance(item, dict))
        return {
            "ok": True,
            "status": "patch_apply_ok",
            "doc": "https://tcnwueberajc.feishu.cn/docx/doc-test",
            "document_id": "doc-test",
            "source_hash": "hash-before",
            "revision_token": "docx-sha256:hash-before",
            "applied_operations": operations,
            "manual_actions": list(plan_payload.get("manual_actions") or []),
            "errors": [],
        }

    def verify_document_edit_readback(self, _doc_url: str, _content: str, _source: dict[str, object]) -> dict[str, object]:
        self.calls.append("readback")
        if self.readback_fail:
            return {"ok": False, "status": "document_edit_readback_failed", "reply": "readback failed"}
        return {"ok": True, "status": "document_edit_readback_ok"}

    def verify_document_edit_patch_readback(self, _plan_payload: dict[str, object], _apply_result: dict[str, object]) -> dict[str, object]:
        self.calls.append("patch_readback")
        if self.readback_fail:
            return {"ok": False, "status": "document_edit_patch_readback_failed", "reply": "readback failed"}
        return {
            "ok": True,
            "status": "document_edit_patch_readback_ok",
            "text": self.replaced_content or self.source_text,
            "native_table_count": 1,
            "markdown_table_residue_found": False,
            "family_requirements_checked": ["patch_readback"],
        }

    def _request(self, method: str, path: str, *, json_body: dict | None = None, params: dict | None = None) -> dict[str, object]:
        self.calls.append(f"{method} {path}")
        if method == "GET" and path.endswith("/records"):
            return {"data": {"items": self.records, "has_more": False}}
        if method == "GET" and path.endswith("/fields"):
            return {
                "data": {
                    "items": [
                        {"field_name": name, "field_id": f"fld-{index}", "type": field_type, "property": {"options": []}}
                        for index, (name, field_type) in enumerate(COMMERCIAL_DELIVERY_FIELD_SPECS.items(), 1)
                    ]
                }
            }
        if method == "PUT" and "/fields/fld-" in path:
            return {"data": {}}
        if method == "PUT" and path.endswith("/records/rec-commercial"):
            self.record_fields.update((json_body or {}).get("fields") or {})
            return {"data": {"record": {"record_id": "rec-commercial", "fields": dict(self.record_fields)}}}
        raise AssertionError(f"unexpected request: {method} {path}")

    def read_bitable_record(self, _app_token: str, _table_id: str, record_id: str) -> dict[str, object]:
        self.calls.append("record_readback")
        if self.empty_record_readback:
            return {"record_id": record_id, "fields": {}}
        if record_id == "rec-commercial":
            fields = dict(self.records[0].get("fields") or {}) if self.records else {}
            if not self.stale_record_readback:
                fields.update(self.record_fields)
            return {"record_id": record_id, "fields": fields}
        return {}


class GenericReplaceOnlyFeishuService(SafeFeishuService):
    replace_document_url_safely = None
    apply_document_edit_patch_plan = None

    def replace_document_url(self, *_args: object, **_kwargs: object) -> dict[str, object]:
        self.calls.append("unsafe_replace_document_url")
        return {"ok": True, "doc": "https://tcnwueberajc.feishu.cn/docx/doc-test"}


class HandleDocumentEditHarness(DocumentToolsMixin):
    def __init__(
        self,
        feishu_service: object,
        content: str | None = None,
        record_fields: dict[str, object] | None = None,
        *,
        omit_required_schema: bool = False,
    ) -> None:
        self.feishu_service = feishu_service
        self.content_flow_client = FakeContentFlowClient(
            content or "# 新标题\n\n## 正文\n\n这是修改后的完整正文，已经把要求吸收到原文结构里，不是补丁。",
            record_fields=record_fields,
            omit_required_schema=omit_required_schema,
        )
        self.archive_service = FakeArchiveService()

    def _conversation_context_prompt(self, _message: Message) -> str:
        return ""

    def _subprocess_env_with_context(self, _message: Message) -> dict[str, str]:
        return {}

    def _parse_openclaw_json(self, _value: str) -> dict[str, object]:
        return {}


class HandleDocumentEditStyleContextHarness(HandleDocumentEditHarness):
    def _document_edit_style_context_prompt(self, edit_request: dict[str, object], original_text: str) -> str:
        return "STYLE_CONTEXT_FIXTURE" if self._document_edit_needs_style_context(str(edit_request.get("edit_requirements") or "")) else ""


class HandleShootingExecutionBackwashHarness(HandleDocumentEditHarness):
    def __init__(self, feishu_service: object) -> None:
        super().__init__(feishu_service)
        self.backwash_calls: list[dict[str, object]] = []

    def _handle_shooting_execution_backwash(
        self, message: Message, edit_request: dict[str, object], source: dict[str, object]
    ) -> TaskResult:
        self.backwash_calls.append({"message": message, "edit_request": edit_request, "source": source})
        return TaskResult(
            ok=True,
            status="shooting_execution_backwashed",
            reply="backwashed",
            task_id="run-test",
            feishu_doc=str(edit_request.get("target_doc_url") or ""),
        )


class HandleCommercialDocumentEditHarness(DocumentToolsMixin, CommercialDeliveryMixin):
    def __init__(
        self,
        feishu_service: object,
        content: str | None = None,
        record_fields: dict[str, object] | None = None,
        *,
        omit_required_schema: bool = False,
    ) -> None:
        self.feishu_service = feishu_service
        self.content_flow_client = FakeContentFlowClient(
            content
            or "# 清扬 PK 瓶双赛道图文\n\n## 1. 作品信息\n### 初稿时间\n20260706\n\n### 发布时间\n20260707\n\n## 2. 作品内容\n### 标题\n多重身份也能扛得住\n\n## 3. PR备注\n无特殊备注",
            record_fields=record_fields,
            omit_required_schema=omit_required_schema,
        )
        self.archive_service = FakeArchiveService()

    def _conversation_context_prompt(self, _message: Message) -> str:
        return ""


class DocumentEditRouteHarness(TagRouter):
    def __init__(self) -> None:
        self.source = "feishu"
        self.chat_type = "private"
        self.timezone = "Asia/Shanghai"

    def handle_修改(self, _message: Message) -> TaskResult:
        return TaskResult(ok=True, status="document_edit_called", reply="called", task_id="")


class FakeReadbackFeishuService(FeishuService):
    def __init__(self, *, text: str, root_blocks: list[dict[str, object]]) -> None:
        self._text = text
        self._root_blocks = root_blocks

    def _resolve_docx_url_for_snapshot(self, _url: str) -> dict[str, str]:
        return {"document_id": "doc-readback", "kind": "docx", "doc_url": "https://tcnwueberajc.feishu.cn/docx/doc-readback"}

    def read_document_text(self, url: str) -> dict[str, object]:
        return {"ok": True, "url": url, "kind": "docx", "token": "doc-readback", "text": self._text, "error": ""}

    def _read_docx_block_tree(self, _document_id: str, *, max_depth: int = 6, max_blocks: int = 2000) -> list[dict[str, object]]:
        return self._root_blocks


class DocumentToolsTest(unittest.TestCase):
    def _message(self, body: str, metadata: dict | None = None) -> Message:
        return Message(
            entry_tag="修改",
            raw_text=f"【修改】{body}",
            body=body,
            source="feishu",
            chat_type="private",
            created_at=datetime.now(),
            metadata=metadata or {},
        )

    def test_document_edit_patch_contract_downstream_consumer_surface(self) -> None:
        plan = DocumentEditPatchPlan.from_mapping(
            {
                "source": {
                    "url": "https://tcnwueberajc.feishu.cn/docx/doc-test",
                    "document_id": "doc-test",
                    "source_hash": "hash-before",
                    "revision_token": "docx-sha256:hash-before",
                    "snapshot_path": "/tmp/document-edit-snapshot.json",
                    "text": "# 原标题\n\n## 正文\n\n正文",
                    "protected_block_ids": [],
                    "protected_table_shapes": [],
                },
                "block_refs": [
                    {
                        "block_id": "block-title",
                        "path": ["0"],
                        "block_type": "2",
                        "text": "旧标题",
                    }
                ],
                "operations": [
                    {
                        "op": "replace_text",
                        "operation_id": "op-title",
                        "block_id": "block-title",
                        "path": ["0"],
                        "expected_old_text": "旧标题",
                        "new_text": "新标题",
                    }
                ],
            },
            executable_op_whitelist=load_document_edit_op_whitelist(),
        )

        self.assertEqual(DOCUMENT_EDIT_PATCH_CONTRACT_ID, "openclaw.document_edit.patch_first_schema.v1")
        self.assertEqual(DOCUMENT_EDIT_CONTRACT_OWNER, "openclaw-maintenance")
        self.assertIn("DocumentEditPatch", DOCUMENT_EDIT_MIGRATION_PLAN)
        self.assertIn("test_document_edit", DOCUMENT_EDIT_DOWNSTREAM_CONSUMER_TEST)
        self.assertEqual(plan.to_mapping()["contract_id"], DOCUMENT_EDIT_PATCH_CONTRACT_ID)

    def test_document_edit_patch_apply_rejects_partial_expected_old_text(self) -> None:
        class PatchService(FeishuService):
            def _build_docx_snapshot(self, *_args: object, **_kwargs: object) -> dict[str, object]:
                return {
                    "source_hash": "hash-before",
                    "root_blocks": [
                        {
                            "block_id": "block-body",
                            "path": "0",
                            "block_type": 2,
                            "kind": "text",
                            "text": "看到世界杯里C罗在球场上冲刺奔跑，我真的很容易共情。",
                        }
                    ],
                }

            def _request(self, *_args: object, **_kwargs: object) -> dict[str, object]:
                raise AssertionError("must not patch when expected_old_text is only a fragment")

        service = PatchService("local_markdown", "/tmp/openclaw-document-edit-unit")
        result = service.apply_document_edit_patch_plan(
            {
                "source": {
                    "url": "https://tcnwueberajc.feishu.cn/docx/doc-test",
                    "document_id": "doc-test",
                    "source_hash": "hash-before",
                    "revision_token": "docx-sha256:hash-before",
                    "snapshot_path": "/tmp/document-edit-snapshot.json",
                    "text": "看到世界杯里C罗在球场上冲刺奔跑，我真的很容易共情。",
                },
                "block_refs": [
                    {
                        "block_id": "block-body",
                        "path": ["0"],
                        "block_type": "2",
                        "text": "看到世界杯里C罗在球场上冲刺奔跑，我真的很容易共情。",
                    }
                ],
                "operations": [
                    {
                        "op": "replace_text",
                        "operation_id": "op-fragment",
                        "block_id": "block-body",
                        "path": ["0"],
                        "expected_old_text": "看到世界杯里C罗在球场上冲刺奔跑",
                        "new_text": "看到足球赛事里球员在草坪球场上冲刺奔跑",
                    }
                ],
            }
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "patch_apply_failed")
        self.assertEqual(result["applied_operations"], [])
        self.assertIn("document_edit_patch_expected_old_text_mismatch", result["errors"][0]["error"])

    def test_feishu_writer_insert_table_row_reads_new_cells_without_deleting_existing_image(self) -> None:
        class TablePatchService(FeishuService):
            def __init__(self) -> None:
                super().__init__("local_markdown", "/tmp/openclaw-document-edit-table-row-unit")
                self.inserted = False
                self.requests: list[tuple[str, str, dict[str, object] | None]] = []
                self.cell_writes: list[tuple[str, str]] = []

            def _table_block(self) -> dict[str, object]:
                cell_ids = [f"cell-{index}" for index in range(1, 9 if self.inserted else 7)]
                return {
                    "block_id": "table-img",
                    "block_type": 31,
                    "table": {
                        "property": {
                            "row_size": 4 if self.inserted else 3,
                            "column_size": 2,
                        },
                        "cells": [{"block_id": cell_id} for cell_id in cell_ids],
                    },
                    "children": [{"block_id": cell_id} for cell_id in cell_ids],
                }

            def _request(
                self,
                method: str,
                path: str,
                *,
                json_body: dict | None = None,
                params: dict | None = None,
            ) -> dict[str, object]:
                self.requests.append((method, path, json_body))
                if method == "GET" and path.endswith("/blocks/table-img"):
                    return {"data": {"block": self._table_block()}}
                if method == "GET" and path.endswith("/blocks/table-img/children"):
                    return {"data": {"items": self._table_block()["children"]}}
                if method == "PATCH" and path.endswith("/blocks/table-img"):
                    self.inserted = True
                    return {"data": {"block": self._table_block()}}
                if method == "POST" and "/blocks/cell-" in path and path.endswith("/children"):
                    cell_id = path.split("/blocks/", 1)[1].split("/children", 1)[0]
                    text = str((json_body or {}).get("children", [{}])[0].get("text", {}).get("elements", [{}])[0].get("text_run", {}).get("content", ""))
                    self.cell_writes.append((cell_id, text))
                    return {"data": {"children": []}}
                raise AssertionError(f"unexpected request: {method} {path}")

        service = TablePatchService()

        result = service._insert_docx_table_row_with_values(
            "doc-test",
            "table-img",
            -1,
            ["图4", "草坪球场/H5活动补图"],
        )

        self.assertEqual(result["status"], "insert_table_row_ok")
        self.assertEqual(result["before_shape"], {"row_size": 3, "column_size": 2})
        self.assertEqual(result["after_shape"], {"row_size": 4, "column_size": 2})
        self.assertEqual(service.cell_writes, [("cell-7", "图4"), ("cell-8", "草坪球场/H5活动补图")])
        self.assertFalse(any(method == "DELETE" for method, _, _ in service.requests))

    def test_handle_document_edit_requires_patch_apply_api(self) -> None:
        service = GenericReplaceOnlyFeishuService()
        harness = HandleDocumentEditHarness(service)

        result = harness.handle_修改(
            self._message("文档链接：https://tcnwueberajc.feishu.cn/docx/doc-test\n修改要求：改标题")
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "document_edit_patch_apply_unavailable")
        self.assertNotIn("unsafe_replace_document_url", service.calls)

    def test_document_edit_patch_heading_is_rejected(self) -> None:
        harness = DocumentToolsHarness()

        reason = harness._patch_like_document_edit_reason(
            "# 原标题\n\n## 补充：AI 攻略 + 拍照教程 + 成果展示融合版\n\n新方案内容"
        )

        self.assertIn("文末补丁", reason)

    def test_stable_pending_info_heading_is_allowed(self) -> None:
        harness = DocumentToolsHarness()

        reason = harness._patch_like_document_edit_reason(
            "# 再创作任务卡\n\n## 待补充信息\n\n- 到现场确认开放线路"
        )

        self.assertEqual(reason, "")

    def test_standalone_fusion_version_heading_is_rejected(self) -> None:
        harness = DocumentToolsHarness()

        reason = harness._patch_like_document_edit_reason(
            "# 创作文档\n\n## AI 攻略 + 拍照教程 + 成果展示融合版\n\n新方案内容"
        )

        self.assertIn("融合版", reason)

    def test_document_edit_request_uses_explicit_body_url_and_fields(self) -> None:
        harness = DocumentToolsHarness()
        message = self._message(
            "\n".join(
                [
                    "文档链接：https://tcnwueberajc.feishu.cn/wiki/abc123",
                    "修改要求：标题更像真实体验",
                    "约束（选填）：发布时间、PR备注、不要新增功效",
                ]
            )
        )

        request = harness._build_document_edit_request(message)

        self.assertEqual(request["target_doc_url"], "https://tcnwueberajc.feishu.cn/wiki/abc123")
        self.assertEqual(request["target_source"], "explicit_body_url")
        self.assertEqual(request["edit_requirements"], "标题更像真实体验")
        self.assertEqual(request["target_sections"], [])
        self.assertEqual(request["preserve_constraints"], ["发布时间", "PR备注", "不要新增功效"])
        self.assertEqual(request["forbidden_changes"], [])

    def test_document_edit_request_accepts_simplified_optional_constraints(self) -> None:
        harness = DocumentToolsHarness()
        message = self._message(
            "\n".join(
                [
                    "文档链接：https://tcnwueberajc.feishu.cn/wiki/abc123",
                    "修改要求：把标题和开头改得更像真实体验",
                    "约束（选填）：保留发布时间，不要新增没有提供的数据",
                ]
            )
        )

        request = harness._build_document_edit_request(message)

        self.assertEqual(request["edit_requirements"], "把标题和开头改得更像真实体验")
        self.assertEqual(request["target_sections"], [])
        self.assertEqual(request["preserve_constraints"], ["保留发布时间", "不要新增没有提供的数据"])
        self.assertEqual(request["forbidden_changes"], [])

    def test_document_edit_request_separates_attached_time_scope_from_wiki_token(self) -> None:
        harness = DocumentToolsHarness()
        message = self._message(
            "【修改】根据brief修改：https://tcnwueberajc.feishu.cn/wiki/"
            "EN03w7cVciEnqWkfQhlcI9bfnEc90秒往后的内容，使整个分镜脚本前后内容一致"
        )

        request = harness._build_document_edit_request(message)

        self.assertEqual(
            request["target_doc_url"],
            "https://tcnwueberajc.feishu.cn/wiki/EN03w7cVciEnqWkfQhlcI9bfnEc",
        )
        self.assertIn("90秒往后的内容", request["edit_requirements"])

    def test_document_edit_preflight_does_not_expose_feishu_api_body(self) -> None:
        class MissingWikiService:
            def prepare_document_edit_patch_source(self, _url: str, **_kwargs: object) -> dict[str, object]:
                return {
                    "ok": False,
                    "status": "document_edit_patch_preflight_failed",
                    "error": (
                        "Feishu API request failed (GET /wiki/v2/spaces/get_node) status=400, "
                        "body={'code': 131005, 'msg': 'not found', 'error': {'log_id': 'secret', "
                        "'troubleshooter': 'https://open.feishu.cn/search'}}"
                    ),
                }

        result = HandleDocumentEditHarness(MissingWikiService()).handle_修改(
            self._message(
                "文档链接：https://tcnwueberajc.feishu.cn/wiki/EN03w7cVciEnqWkfQhlcI9bfnEc\n"
                "修改要求：调整90秒后的脚本"
            )
        )

        self.assertFalse(result.ok)
        self.assertIn("DOCUMENT_EDIT_TARGET_NOT_FOUND", result.reply)
        self.assertNotIn("131005", result.reply)
        self.assertNotIn("log_id", result.reply)
        self.assertNotIn("troubleshooter", result.reply)

    def test_document_edit_request_accepts_replied_document_metadata(self) -> None:
        harness = DocumentToolsHarness()
        message = self._message(
            "修改要求：把开头改得更直接",
            {"replied_message": {"text": "目标文档 https://tcnwueberajc.feishu.cn/docx/abc123"}},
        )

        request = harness._build_document_edit_request(message)

        self.assertEqual(request["target_doc_url"], "https://tcnwueberajc.feishu.cn/docx/abc123")
        self.assertEqual(request["target_source"], "replied_document")
        self.assertEqual(request["edit_requirements"], "把开头改得更直接")

    def test_document_edit_request_does_not_use_conversation_context_url(self) -> None:
        harness = DocumentToolsHarness()
        message = self._message(
            "修改要求：把标题改短",
            {"conversation_context": [{"text": "历史消息 https://tcnwueberajc.feishu.cn/wiki/old123"}]},
        )

        request = harness._build_document_edit_request(message)

        self.assertEqual(request["target_doc_url"], "")

    def test_handle_document_edit_requires_edit_requirements_before_preflight(self) -> None:
        service = SafeFeishuService()
        harness = HandleDocumentEditHarness(service)

        result = harness.handle_修改(
            self._message("文档链接：https://tcnwueberajc.feishu.cn/docx/doc-test")
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "missing_edit_requirements")
        self.assertEqual(service.calls, [])

    def test_removed_document_edit_legacy_entries_are_unsupported(self) -> None:
        router = DocumentEditRouteHarness()

        supplement = router.route("补充", "https://tcnwueberajc.feishu.cn/wiki/abc123 补充内容")
        depatch = router.route("去补丁", "https://tcnwueberajc.feishu.cn/wiki/abc123")

        self.assertFalse(supplement.ok)
        self.assertFalse(depatch.ok)
        self.assertEqual(supplement.status, "unsupported_tag")
        self.assertEqual(depatch.status, "unsupported_tag")

    def test_handle_document_edit_requires_safety_preflight(self) -> None:
        class UnsafeFeishuService:
            def read_document_text(self, _url: str) -> dict[str, object]:
                raise AssertionError("must not fall back to unsafe read")

            def replace_document_url(self, *_args: object) -> dict[str, object]:
                raise AssertionError("must not call unsafe replace")

        harness = HandleDocumentEditHarness(UnsafeFeishuService())

        result = harness.handle_修改(
            self._message("文档链接：https://tcnwueberajc.feishu.cn/docx/doc-test\n修改要求：改标题")
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "document_edit_patch_preflight_unavailable")

    def test_handle_document_edit_protects_unsupported_blocks_and_keeps_patching_text(self) -> None:
        service = SafeFeishuService(unsupported=True)
        harness = HandleDocumentEditHarness(service)

        result = harness.handle_修改(
            self._message("文档链接：https://tcnwueberajc.feishu.cn/docx/doc-test\n修改要求：改标题")
        )

        self.assertTrue(result.ok, result.reply)
        self.assertEqual(result.status, "document_edited")
        self.assertEqual(service.calls, ["patch_preflight", "patch_apply", "patch_readback"])
        self.assertIn("blk-img", result.extra["patch_plan"]["source"]["protected_block_ids"])

    def test_handle_document_edit_rechecks_hash_before_patch_apply(self) -> None:
        service = SafeFeishuService(changed=True)
        harness = HandleDocumentEditHarness(service)

        result = harness.handle_修改(
            self._message("文档链接：https://tcnwueberajc.feishu.cn/docx/doc-test\n修改要求：改标题")
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "document_changed_since_read")
        self.assertEqual(service.calls, ["patch_preflight", "patch_apply"])

    def test_handle_document_edit_uses_patch_apply_and_readback(self) -> None:
        service = SafeFeishuService()
        harness = HandleDocumentEditHarness(service)

        result = harness.handle_修改(
            self._message("文档链接：https://tcnwueberajc.feishu.cn/docx/doc-test\n修改要求：改标题")
        )

        self.assertTrue(result.ok, result.reply)
        self.assertEqual(service.calls, ["patch_preflight", "patch_apply", "patch_readback"])
        self.assertIn("新标题", service.replaced_content)
        self.assertEqual(result.extra["snapshot_path"], "/tmp/openclaw-document-edit-snapshot.json")
        user_content = json.loads(str(harness.content_flow_client.calls[0][1]))
        self.assertIn("working_copy_summary", user_content)
        self.assertIn("compact_view", user_content)
        self.assertNotIn("document_text", user_content)
        self.assertNotIn("block_refs", user_content)
        self.assertNotIn("protected_blocks", user_content)
        self.assertEqual(
            result.extra["patch_plan"]["operations"][0]["expected_old_text"],
            service.source_text,
        )
        self.assertEqual(result.extra["patch_plan"]["operations"][0]["path"], ["0"])
        envelope = result.extra["response_envelope"]
        self.assertEqual(envelope["schema"], "openclaw.document_edit.response_envelope.v1")
        self.assertEqual(envelope["stage"], "final")
        self.assertEqual(envelope["known_facts"]["patchable_block_count"], 1)
        self.assertEqual(envelope["known_facts"]["protected_block_count"], 0)
        self.assertEqual(len(envelope["applied_operations"]), 1)

    def test_shooting_execution_document_routes_to_creation_run_backwash_only(self) -> None:
        source_text = "\n".join(
            [
                "拍摄执行 - 上海灵瑙科技 2026 WAIC 第一视角展会探秘体验 - 145秒",
                "分镜脚本",
                "路线图",
                "必拍镜头清单",
                "发布包",
            ]
        )
        service = SafeFeishuService(source_text=source_text)
        harness = HandleShootingExecutionBackwashHarness(service)

        result = harness.handle_修改(
            self._message(
                "文档链接：https://tcnwueberajc.feishu.cn/wiki/wiki-test\n"
                "修改要求：从运动员恢复视角讲清睡眠的重要性"
            )
        )

        self.assertTrue(result.ok, result.reply)
        self.assertEqual(result.status, "shooting_execution_backwashed")
        self.assertEqual(service.calls, ["patch_preflight"])
        self.assertEqual(len(harness.backwash_calls), 1)
        source = harness.backwash_calls[0]["source"]
        self.assertEqual(source["document_family"], "shooting_execution")
        self.assertEqual(source["family_contract_id"], "document_edit.shooting_execution.creation_run")
        self.assertEqual(harness.content_flow_client.calls, [])

    def test_shooting_execution_backwash_failure_does_not_expose_traceback(self) -> None:
        service = SafeFeishuService()
        harness = HandleDocumentEditHarness(service)
        with patch(
            "selfmedia.creation.backwash.handle_shooting_execution_backwash",
            side_effect=RuntimeError(
                "Traceback: CreationRun mapping failed log_id=secret "
                "troubleshooter=https://example.test"
            ),
        ), patch(
            "openclaw_app.router.document_tools.current_session_tenant_id",
            return_value="101",
        ):
            result = harness._handle_shooting_execution_backwash(
                self._message("【修改】修改要求：调整90秒后的分镜"),
                {
                    "target_doc_url": "https://tcnwueberajc.feishu.cn/wiki/wiki-test",
                    "edit_requirements": "调整90秒后的分镜",
                },
                {"document_family": "shooting_execution"},
            )

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "shooting_execution_backwash_failed")
        self.assertEqual(result.extra["error_code"], "SHOOTING_EXECUTION_BACKWASH_FAILED")
        self.assertNotIn("Traceback", result.reply)
        self.assertNotIn("log_id", result.reply)
        self.assertNotIn("troubleshooter", result.reply)
        self.assertNotIn("source", result.extra)

    def test_document_edit_progress_file_env_does_not_write_stdout(self) -> None:
        service = SafeFeishuService()
        harness = HandleDocumentEditHarness(service)
        stdout = io.StringIO()
        with tempfile.TemporaryDirectory() as tempdir:
            progress_path = os.path.join(tempdir, "document-edit-progress.jsonl")
            with patch.dict(os.environ, {"OPENCLAW_TAG_ROUTER_PROGRESS_FILE": progress_path}):
                with redirect_stdout(stdout):
                    result = harness.handle_修改(
                        self._message("文档链接：https://tcnwueberajc.feishu.cn/docx/doc-test\n修改要求：改标题")
                    )
            with open(progress_path, encoding="utf-8") as handle:
                raw_events = [line for line in handle.read().splitlines() if line.strip()]

        self.assertTrue(result.ok, result.reply)
        self.assertEqual(stdout.getvalue(), "")
        events = [json.loads(line) for line in raw_events]
        self.assertEqual([event["stage"] for event in events], ["source_loaded", "planning", "applying_patch", "readback", "final"])
        self.assertTrue(all(event["schema"] == "openclaw.document_edit.progress_event.v1" for event in events))
        self.assertTrue(all(event["workflow"] == "document_edit" for event in events))
        self.assertEqual(events[0]["known_facts"]["document_id"], "doc-test")
        self.assertEqual(events[0]["known_facts"]["patchable_block_count"], 1)

    def test_build_document_edit_patch_plan_stops_on_truncated_working_copy_without_visible_heading(self) -> None:
        service = SafeFeishuService()
        harness = HandleDocumentEditHarness(service)
        source = service.prepare_document_edit_patch_source("https://tcnwueberajc.feishu.cn/docx/doc-test")
        source["truncated"] = True

        result = harness._build_document_edit_patch_plan(
            source,
            {"target_doc_url": source["url"], "edit_requirements": "改标题"},
            self._message("文档链接：https://tcnwueberajc.feishu.cn/docx/doc-test\n修改要求：改标题"),
        )

        self.assertEqual(result["status"], "pending_manual")
        self.assertEqual(result["error_code"], "DOCUMENT_EDIT_WORKING_COPY_TRUNCATED")
        self.assertEqual(result["manual_actions"][0]["reason"], "working_copy_truncated")
        self.assertEqual(harness.content_flow_client.calls, [])

    def test_build_document_edit_patch_plan_truncated_visible_heading_chunk_can_plan_with_unknown_sections_manual(self) -> None:
        source = {
            "ok": True,
            "url": "https://tcnwueberajc.feishu.cn/docx/doc-test",
            "document_id": "doc-test",
            "source_hash": "hash-before",
            "revision_token": "docx-sha256:hash-before",
            "snapshot_path": "/tmp/openclaw-document-edit-snapshot.json",
            "truncated": True,
            "text": "正文可见段\n脚本可见段",
            "patchable_blocks": [
                {
                    "block_id": "block-visible-body",
                    "path": ["0"],
                    "block_type": "paragraph",
                    "heading_path": ["正文"],
                    "text": "正文可见段世界杯内容",
                },
                {
                    "block_id": "block-visible-script",
                    "path": ["1"],
                    "block_type": "paragraph",
                    "heading_path": ["脚本"],
                    "text": "脚本可见段",
                },
            ],
            "protected_blocks": [],
            "protected_table_shapes": [],
        }
        harness = HandleDocumentEditHarness(SafeFeishuService())
        harness.content_flow_client = StageAwareContentFlowClient(
            {
                "status": "done",
                "targets": [
                    {
                        "requirement_id": "r1",
                        "block_ids": ["block-visible-body"],
                        "reason": "只命中已读取正文 heading chunk",
                    }
                ],
                "intent_ops": [],
                "manual_actions": [],
            },
            {
                "status": "done",
                "operations": [
                    {
                        "op": "replace_text",
                        "operation_id": "op-visible-body",
                        "block_id": "block-visible-body",
                        "new_text": "正文可见段足球赛事内容",
                    }
                ],
                "manual_actions": [],
                "changed_sections": ["正文"],
            },
        )

        result = harness._build_document_edit_patch_plan(
            source,
            {"target_doc_url": source["url"], "edit_requirements": "只修改正文里世界杯的说法"},
            self._message("文档链接：https://tcnwueberajc.feishu.cn/docx/doc-test\n修改要求：只修改正文里世界杯的说法"),
        )

        self.assertEqual(result["status"], "done")
        self.assertEqual([payload["planner_stage"] for payload in harness.content_flow_client.payloads], ["stage1_locate_targets", "stage2_generate_patch"])
        stage2_view = str(harness.content_flow_client.payloads[1]["compact_view"])
        self.assertIn("[h=正文][block-visible-body]", stage2_view)
        self.assertIn("[TRUNCATED] visible heading chunk only", stage2_view)
        self.assertNotIn("[h=脚本][block-visible-script]", stage2_view)
        self.assertEqual(result["operations"][0]["expected_old_text"], "正文可见段世界杯内容")
        self.assertEqual(result["manual_actions"][0]["reason"], "working_copy_truncated_unknown_sections")

    def test_build_document_edit_patch_plan_truncated_stage1_timeout_does_not_degrade_to_full_visible_view(self) -> None:
        source = {
            "ok": True,
            "url": "https://tcnwueberajc.feishu.cn/docx/doc-test",
            "document_id": "doc-test",
            "source_hash": "hash-before",
            "revision_token": "docx-sha256:hash-before",
            "snapshot_path": "/tmp/openclaw-document-edit-snapshot.json",
            "truncated": True,
            "text": "正文可见段",
            "patchable_blocks": [
                {
                    "block_id": "block-visible-body",
                    "path": ["0"],
                    "block_type": "paragraph",
                    "heading_path": ["正文"],
                    "text": "正文可见段",
                },
            ],
            "protected_blocks": [],
            "protected_table_shapes": [],
        }
        harness = HandleDocumentEditHarness(SafeFeishuService())
        harness.content_flow_client = StageAwareContentFlowClient(
            {
                "status": "pending_manual",
                "reason": "Codex Responses SSE watchdog timeout: total_timeout=45s",
            },
            {
                "status": "done",
                "operations": [
                    {
                        "op": "replace_text",
                        "operation_id": "must-not-run",
                        "block_id": "block-visible-body",
                        "new_text": "不应写入",
                    }
                ],
                "manual_actions": [],
            },
        )

        result = harness._build_document_edit_patch_plan(
            source,
            {"target_doc_url": source["url"], "edit_requirements": "改正文"},
            self._message("文档链接：https://tcnwueberajc.feishu.cn/docx/doc-test\n修改要求：改正文"),
        )

        self.assertEqual(result["status"], "pending_manual")
        self.assertEqual(result["error_code"], "DOCUMENT_EDIT_PATCH_PLAN_TIMEOUT")
        self.assertEqual([payload["planner_stage"] for payload in harness.content_flow_client.payloads], ["stage1_locate_targets"])

    def test_build_document_edit_patch_plan_uses_stage1_stage2_scoped_compact_view(self) -> None:
        source = {
            "ok": True,
            "url": "https://tcnwueberajc.feishu.cn/docx/doc-test",
            "document_id": "doc-test",
            "source_hash": "hash-before",
            "revision_token": "docx-sha256:hash-before",
            "snapshot_path": "/tmp/openclaw-document-edit-snapshot.json",
            "text": "前文\n目标段\n后文\n远端段",
            "patchable_blocks": [
                {"block_id": "block-before", "path": ["0"], "block_type": "paragraph", "text": "前文"},
                {
                    "block_id": "block-target",
                    "path": ["1"],
                    "block_type": "paragraph",
                    "text": "看到世界杯里球员在草坪球场上冲刺奔跑。",
                },
                {"block_id": "block-after", "path": ["2"], "block_type": "paragraph", "text": "后文"},
                {"block_id": "block-far", "path": ["3"], "block_type": "paragraph", "text": "远端段"},
            ],
            "protected_blocks": [
                {"block_id": "block-image", "path": ["4"], "block_type": "image", "reason": "image_block"}
            ],
            "protected_table_shapes": [],
        }
        harness = HandleDocumentEditHarness(SafeFeishuService())
        harness.content_flow_client = StageAwareContentFlowClient(
            {
                "status": "done",
                "targets": [{"requirement_id": "r1", "block_ids": ["block-target"], "reason": "标题要求命中目标段"}],
                "intent_ops": [
                    {
                        "op": "replace_terms",
                        "operation_id": "intent-1",
                        "target_block_ids": ["block-target"],
                        "old_text": "世界杯",
                        "new_text": "足球赛事",
                        "source_evidence": ["用户明确要求替换"],
                    }
                ],
                "manual_actions": [],
            },
            {
                "status": "done",
                "operations": [
                    {
                        "op": "replace_text",
                        "operation_id": "op-target",
                        "block_id": "block-target",
                        "expected_old_text": "LLM 不应决定旧文本",
                        "new_text": "看到足球赛事里球员在草坪球场上冲刺奔跑。",
                    }
                ],
                "manual_actions": [],
                "changed_sections": ["block-target"],
            },
        )

        result = harness._build_document_edit_patch_plan(
            source,
            {"target_doc_url": source["url"], "edit_requirements": "把世界杯改成足球赛事"},
            self._message("文档链接：https://tcnwueberajc.feishu.cn/docx/doc-test\n修改要求：把世界杯改成足球赛事"),
        )

        self.assertEqual(result["status"], "done")
        self.assertEqual([payload["planner_stage"] for payload in harness.content_flow_client.payloads], ["stage1_locate_targets", "stage2_generate_patch"])
        for payload in harness.content_flow_client.payloads:
            self.assertIn("working_copy_summary", payload)
            self.assertIn("compact_view", payload)
            self.assertNotIn("document_text", payload)
            self.assertNotIn("block_refs", payload)
            self.assertNotIn("protected_blocks", payload)
        stage2_view = str(harness.content_flow_client.payloads[1]["compact_view"])
        self.assertIn("[block-before]", stage2_view)
        self.assertIn("[block-target]", stage2_view)
        self.assertIn("[block-after]", stage2_view)
        self.assertNotIn("[block-far]", stage2_view)
        self.assertEqual(harness.content_flow_client.kwargs[0]["thinking"], "low")
        self.assertEqual(harness.content_flow_client.kwargs[1]["thinking"], "medium")
        self.assertEqual(result["operations"][0]["expected_old_text"], "看到世界杯里球员在草坪球场上冲刺奔跑。")
        self.assertEqual(result["operations"][0]["path"], ["1"])
        self.assertEqual(result["intent_trace"][0]["contract_id"], "openclaw.document_edit.intent_ops.v1")
        self.assertEqual(result["operations"][1]["expected_old_text"], "看到世界杯里球员在草坪球场上冲刺奔跑。")

    def test_build_document_edit_patch_plan_stage2_chunks_keep_successful_requirement_when_other_times_out(self) -> None:
        source = {
            "ok": True,
            "url": "https://tcnwueberajc.feishu.cn/docx/doc-test",
            "document_id": "doc-test",
            "source_hash": "hash-before",
            "revision_token": "docx-sha256:hash-before",
            "snapshot_path": "/tmp/openclaw-document-edit-snapshot.json",
            "text": "标题\n第一段\n间隔段\n第二段\n结尾",
            "patchable_blocks": [
                {"block_id": "block-title", "path": ["0"], "block_type": "paragraph", "text": "标题"},
                {"block_id": "block-first", "path": ["1"], "block_type": "paragraph", "text": "第一段世界杯内容"},
                {"block_id": "block-gap", "path": ["2"], "block_type": "paragraph", "text": "间隔段"},
                {"block_id": "block-second", "path": ["3"], "block_type": "paragraph", "text": "第二段H5活动内容"},
                {"block_id": "block-tail", "path": ["4"], "block_type": "paragraph", "text": "结尾"},
            ],
            "protected_blocks": [],
            "protected_table_shapes": [],
        }
        harness = HandleDocumentEditHarness(SafeFeishuService())
        harness.content_flow_client = StageAwareContentFlowClient(
            {
                "status": "done",
                "targets": [
                    {"requirement_id": "r1", "block_ids": ["block-first"], "reason": "改第一段"},
                    {"requirement_id": "r2", "block_ids": ["block-second"], "reason": "改第二段"},
                ],
                "intent_ops": [],
                "manual_actions": [],
            },
            [
                {
                    "status": "pending_manual",
                    "reason": "Codex Responses SSE watchdog timeout: total_timeout=120s",
                },
                {
                    "status": "done",
                    "operations": [
                        {
                            "op": "replace_text",
                            "operation_id": "op-second",
                            "block_id": "block-second",
                            "new_text": "第二段H5活动和草坪球场内容",
                        }
                    ],
                    "manual_actions": [],
                    "changed_sections": ["block-second"],
                },
            ],
        )

        result = harness._build_document_edit_patch_plan(
            source,
            {"target_doc_url": source["url"], "edit_requirements": "第一段和第二段都改"},
            self._message("文档链接：https://tcnwueberajc.feishu.cn/docx/doc-test\n修改要求：第一段和第二段都改"),
        )

        self.assertEqual(result["status"], "done")
        self.assertEqual([payload["planner_stage"] for payload in harness.content_flow_client.payloads], ["stage1_locate_targets", "stage2_generate_patch", "stage2_generate_patch"])
        self.assertEqual([item["operation_id"] for item in result["operations"]], ["op-second"])
        self.assertEqual(result["operations"][0]["expected_old_text"], "第二段H5活动内容")
        self.assertEqual(result["manual_actions"][0]["reason"], "stage2_patch_plan_failed")
        self.assertEqual(result["manual_actions"][0]["requirement_id"], "r1")
        self.assertEqual(result["manual_actions"][0]["target_block_ids"], ["block-first"])
        self.assertEqual(result["manual_actions"][0]["error_code"], "DOCUMENT_EDIT_PATCH_PLAN_TIMEOUT")
        first_stage2_view = str(harness.content_flow_client.payloads[1]["compact_view"])
        second_stage2_view = str(harness.content_flow_client.payloads[2]["compact_view"])
        self.assertIn("[block-first]", first_stage2_view)
        self.assertNotIn("[block-second]", first_stage2_view)
        self.assertIn("[block-second]", second_stage2_view)

    def test_build_document_edit_patch_plan_stage2_chunk_schema_invalid_degrades_only_that_requirement(self) -> None:
        source = {
            "ok": True,
            "url": "https://tcnwueberajc.feishu.cn/docx/doc-test",
            "document_id": "doc-test",
            "source_hash": "hash-before",
            "revision_token": "docx-sha256:hash-before",
            "snapshot_path": "/tmp/openclaw-document-edit-snapshot.json",
            "text": "第一段\n第二段",
            "patchable_blocks": [
                {"block_id": "block-first", "path": ["0"], "block_type": "paragraph", "text": "第一段内容"},
                {"block_id": "block-second", "path": ["1"], "block_type": "paragraph", "text": "第二段内容"},
            ],
            "protected_blocks": [],
            "protected_table_shapes": [],
        }
        harness = HandleDocumentEditHarness(SafeFeishuService())
        harness.content_flow_client = StageAwareContentFlowClient(
            {
                "status": "done",
                "targets": [
                    {"requirement_id": "r1", "block_ids": ["block-first"], "reason": "非法 op fixture"},
                    {"requirement_id": "r2", "block_ids": ["block-second"], "reason": "合法 op fixture"},
                ],
                "intent_ops": [],
                "manual_actions": [],
            },
            [
                {
                    "status": "done",
                    "operations": [
                        {
                            "op": "replace_text",
                            "operation_id": "op-invalid",
                            "block_id": "block-first",
                        }
                    ],
                    "manual_actions": [],
                },
                {
                    "status": "done",
                    "operations": [
                        {
                            "op": "replace_text",
                            "operation_id": "op-second",
                            "block_id": "block-second",
                            "new_text": "第二段已安全修改",
                        }
                    ],
                    "manual_actions": [],
                },
            ],
        )

        result = harness._build_document_edit_patch_plan(
            source,
            {"target_doc_url": source["url"], "edit_requirements": "两段都改"},
            self._message("文档链接：https://tcnwueberajc.feishu.cn/docx/doc-test\n修改要求：两段都改"),
        )

        self.assertEqual(result["status"], "done")
        self.assertEqual([item["operation_id"] for item in result["operations"]], ["op-second"])
        self.assertEqual(result["manual_actions"][0]["reason"], "stage2_patch_plan_failed")
        self.assertEqual(result["manual_actions"][0]["requirement_id"], "r1")
        self.assertEqual(result["manual_actions"][0]["error_code"], "DOCUMENT_EDIT_PATCH_SCHEMA_INVALID")

    def test_document_edit_response_envelope_renders_known_facts_and_counts(self) -> None:
        harness = DocumentToolsHarness()
        envelope = harness._document_edit_response_envelope(
            "planning_failed",
            source={
                "document_id": "doc-test",
                "source_hash": "hash-before",
                "revision_token": "docx-sha256:hash-before",
                "snapshot_path": "/tmp/openclaw-document-edit-snapshot.json",
                "patchable_blocks": [{"block_id": "block-1"}, {"block_id": "block-2"}],
                "protected_blocks": [{"block_id": "block-image"}],
                "protected_table_shapes": [{"block_id": "block-table"}],
                "truncated": True,
            },
            error_code="DOCUMENT_EDIT_PATCH_PLAN_TIMEOUT",
            reason="planner timed out",
            manual_actions=[{"reason": "timeout"}],
            applied_operations=[{"operation_id": "op-1"}],
        )

        rendered = harness._render_document_edit_response_envelope(envelope)

        self.assertEqual(envelope["schema"], "openclaw.document_edit.response_envelope.v1")
        self.assertEqual(envelope["known_facts"]["block_count"], 3)
        self.assertTrue(envelope["known_facts"]["truncated"])
        self.assertIn("DOCUMENT_EDIT_PATCH_PLAN_TIMEOUT", rendered)
        self.assertIn("可改文字块 2，保护块 1，保护表格 1", rendered)
        self.assertIn("已执行 patch：1", rendered)
        self.assertIn("人工项：1", rendered)

    def test_handle_document_edit_requires_patch_schema_before_apply(self) -> None:
        service = SafeFeishuService()
        harness = HandleDocumentEditHarness(service, omit_required_schema=True)

        result = harness.handle_修改(
            self._message("文档链接：https://tcnwueberajc.feishu.cn/docx/doc-test\n修改要求：改标题")
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "document_edit_patch_schema_invalid")
        self.assertEqual(service.calls, ["patch_preflight"])

    def test_handle_document_edit_returns_stable_patch_plan_timeout_error_code(self) -> None:
        service = SafeFeishuService()
        harness = HandleDocumentEditHarness(service)
        harness.content_flow_client = StageAwareContentFlowClient(
            {
                "status": "done",
                "targets": [{"requirement_id": "r1", "block_ids": ["block-title"], "reason": "fixture"}],
                "intent_ops": [],
                "manual_actions": [],
            },
            {
                "status": "pending_manual",
                "reason": "Codex Responses SSE watchdog timeout: total_timeout=120s",
            },
        )

        result = harness.handle_修改(
            self._message("文档链接：https://tcnwueberajc.feishu.cn/docx/doc-test\n修改要求：改标题")
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "document_edit_pending_manual")
        self.assertEqual(result.extra["error_code"], "DOCUMENT_EDIT_PATCH_PLAN_TIMEOUT")
        self.assertIn("DOCUMENT_EDIT_PATCH_PLAN_TIMEOUT", result.reply)
        self.assertEqual(service.calls, ["patch_preflight"])
        kwargs = harness.content_flow_client.kwargs[1]
        self.assertEqual(kwargs["timeout_seconds"], 120.0)
        self.assertEqual(kwargs["max_retries"], 0)
        self.assertEqual(kwargs["thinking"], "medium")

    def test_handle_document_edit_does_not_apply_when_only_noop_text_and_manual_actions_remain(self) -> None:
        service = SafeFeishuService(source_text="当前文本已经包含球赛、足球赛事、H5活动和草坪球场。")
        harness = HandleDocumentEditHarness(service)
        harness.content_flow_client = StageAwareContentFlowClient(
            {
                "status": "done",
                "targets": [{"requirement_id": "r1", "block_ids": ["block-title"], "reason": "fixture"}],
                "intent_ops": [],
                "manual_actions": [],
            },
            {
                "status": "done",
                "operations": [
                    {
                        "op": "replace_text",
                        "operation_id": "op-noop",
                        "block_id": "block-title",
                        "new_text": "当前文本已经包含球赛、足球赛事、H5活动和草坪球场。",
                        "source_evidence": ["fixture"],
                    }
                ],
                "manual_actions": [
                    {
                        "action": "请人工确认图片数量至少9张，并处理图4删除。",
                        "block_ids": ["block-image-script"],
                    }
                ],
            },
        )

        result = harness.handle_修改(
            self._message("文档链接：https://tcnwueberajc.feishu.cn/docx/doc-test\n修改要求：图片至少9张，图4删除")
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "document_edit_pending_manual")
        self.assertIn("DOCUMENT_EDIT_ONLY_MANUAL_ACTIONS_REMAIN", result.reply)
        self.assertEqual(service.calls, ["patch_preflight"])
        self.assertEqual(len(result.extra["noop_operations"]), 1)

    def test_feishu_readback_requires_native_table_for_creation_family(self) -> None:
        service = FakeReadbackFeishuService(
            text="# 创作文档\n\n## 分镜脚本\n\n时间\n画面\n字幕/口播\n声音/拍摄注意\n\n## 证据附录\n\n- evidence",
            root_blocks=[
                {"block_type": 3, "text": "创作文档"},
                {"block_type": 4, "text": "分镜脚本"},
                {"block_type": 4, "text": "证据附录"},
            ],
        )

        result = service.verify_document_edit_readback(
            "https://tcnwueberajc.feishu.cn/docx/doc-readback",
            "content",
            {"document_family": "creation", "text": "## 分镜脚本\n\n## 证据附录", "native_table_count": 1},
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "document_edit_native_table_missing")

    def test_feishu_readback_accepts_creation_storyboard_and_last_evidence_appendix(self) -> None:
        service = FakeReadbackFeishuService(
            text="# 创作文档\n\n## 分镜脚本\n\n时间\n画面\n字幕/口播\n声音/拍摄注意\n\n## 证据附录\n\n- evidence",
            root_blocks=[
                {"block_type": 3, "text": "创作文档"},
                {"block_type": 4, "text": "分镜脚本"},
                {"block_type": 31, "kind": "table", "table_shape": {"row_size": 2, "column_size": 4}},
                {"block_type": 4, "text": "证据附录"},
            ],
        )

        result = service.verify_document_edit_readback(
            "https://tcnwueberajc.feishu.cn/docx/doc-readback",
            "content",
            {"document_family": "creation", "text": "## 分镜脚本\n\n## 证据附录", "native_table_count": 1},
        )

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["native_table_count"], 1)
        self.assertIn("storyboard_headers", result["family_requirements_checked"])

    def test_document_edit_style_request_includes_style_context_without_style_artifact(self) -> None:
        service = SafeFeishuService()
        harness = HandleDocumentEditStyleContextHarness(service)

        result = harness.handle_修改(
            self._message("文档链接：https://tcnwueberajc.feishu.cn/docx/doc-test\n修改要求：把标题改得更网感，不要像 AI 味")
        )

        self.assertTrue(result.ok, result.reply)
        self.assertEqual(len(harness.content_flow_client.calls), 2)
        user_content = str(harness.content_flow_client.calls[1][1])
        self.assertIn("STYLE_CONTEXT_FIXTURE", user_content)
        self.assertNotIn("style_polish_runs", result.reply)

    def test_handle_commercial_document_edit_syncs_unique_com01_record(self) -> None:
        old_url = os.environ.get("MEDIA_OS_COMMERCIAL_DELIVERY_URL")
        os.environ["MEDIA_OS_COMMERCIAL_DELIVERY_URL"] = "https://tcnwueberajc.feishu.cn/base/appTest?table=tblTest"
        try:
            service = SafeFeishuService(
                source_text="# 商单交付\n\n## 1. 作品信息\n\n### 初稿时间\n20260706\n\n## 2. 作品内容\n\n### 图片脚本\n脚本内容\n\n## 3. PR备注\n无特殊备注",
                records=[
                    {
                        "record_id": "rec-commercial",
                        "fields": {
                            "作品初稿链接": {"text": "https://tcnwueberajc.feishu.cn/docx/doc-test", "link": "https://tcnwueberajc.feishu.cn/docx/doc-test"},
                            "文档ID": "doc-test",
                            "标题": "旧标题",
                        },
                    }
                ],
            )
            harness = HandleCommercialDocumentEditHarness(
                service,
                record_fields={
                    "标题": "多重身份也能扛得住",
                    "一句话总结": "清扬 PK 瓶双赛道图文",
                    "PR备注": "无特殊备注",
                },
            )

            result = harness.handle_修改(
                self._message("文档链接：https://tcnwueberajc.feishu.cn/docx/doc-test\n修改要求：把标题改得更有冲击力")
            )

            self.assertTrue(result.ok, result.reply)
            self.assertEqual(result.status, "document_edited")
            self.assertEqual(service.record_fields["标题"], "多重身份也能扛得住")
            self.assertEqual(service.record_fields["一句话总结"], "清扬 PK 瓶双赛道图文")
            self.assertIn("作品初稿链接", service.record_fields)
            self.assertIn("文档ID", service.record_fields)
            self.assertIn("commercial_delivery_record_synced", str(result.extra["commercial_delivery_sync"]))
            self.assertIn("commercial_delivery_COM01_readback", result.extra["family_readback"]["family_requirements_checked"])
            self.assertLess(service.calls.index("patch_readback"), service.calls.index("PUT /bitable/v1/apps/appTest/tables/tblTest/records/rec-commercial"))
        finally:
            if old_url is None:
                os.environ.pop("MEDIA_OS_COMMERCIAL_DELIVERY_URL", None)
            else:
                os.environ["MEDIA_OS_COMMERCIAL_DELIVERY_URL"] = old_url

    def test_handle_commercial_document_edit_auto_inserts_image_script_rows_and_syncs_content_spec(self) -> None:
        old_url = os.environ.get("MEDIA_OS_COMMERCIAL_DELIVERY_URL")
        os.environ["MEDIA_OS_COMMERCIAL_DELIVERY_URL"] = "https://tcnwueberajc.feishu.cn/base/appTest?table=tblTest"
        try:
            service = SafeFeishuService(
                source_text="# 商单交付\n\n## 1. 作品信息\n\n## 2. 作品内容\n\n### 图片脚本\n图4：产品露出\n\n## 3. PR备注\n无特殊备注",
                patchable_blocks=[
                    {
                        "block_id": "cell-fig4",
                        "path": ["3.15"],
                        "block_type": "32",
                        "text": "图4：产品露出",
                        "heading_path": ["2. 作品内容", "图片脚本"],
                        "protected": False,
                        "has_non_plain_text_elements": False,
                    }
                ],
                protected_blocks=[
                    {
                        "block_id": "table-img",
                        "path": ["3"],
                        "block_type": 31,
                        "kind": "table",
                        "reason": "table_shape_protected",
                        "heading_path": ["2. 作品内容", "图片脚本"],
                        "table_shape": {"row_size": 7, "column_size": 5},
                    }
                ],
                protected_table_shapes=[
                    {"block_id": "table-img", "path": "3", "table_shape": {"row_size": 7, "column_size": 5}}
                ],
                records=[
                    {
                        "record_id": "rec-commercial",
                        "fields": {
                            "作品初稿链接": {"text": "https://tcnwueberajc.feishu.cn/docx/doc-test", "link": "https://tcnwueberajc.feishu.cn/docx/doc-test"},
                            "文档ID": "doc-test",
                            "内容规格": "图文6张",
                        },
                    }
                ],
            )
            harness = HandleCommercialDocumentEditHarness(service)
            harness.content_flow_client = StageAwareContentFlowClient(
                {
                    "status": "done",
                    "targets": [
                        {"requirement_id": "r1", "block_ids": ["table-img"], "reason": "图片至少9张命中图片脚本表格"},
                        {"requirement_id": "r3", "block_ids": ["cell-fig4"], "reason": "图4文字说明需要去产品"},
                    ],
                    "intent_ops": [],
                    "manual_actions": [],
                },
                {
                    "status": "done",
                    "operations": [
                        {
                            "op": "replace_text",
                            "operation_id": "op-fig4",
                            "block_id": "cell-fig4",
                            "new_text": "图4：不使用产品露出，改为球赛/H5活动氛围画面。",
                            "source_evidence": ["用户要求图4不需要产品"],
                        },
                        {
                            "op": "insert_table_row",
                            "operation_id": "op-img-8",
                            "table_block_id": "table-img",
                            "row_index": -1,
                            "cell_texts": ["图8", "草坪球场远景", "球赛/赛事氛围", "H5活动引导", "不放产品"],
                            "minimum_rows": 9,
                            "content_spec": "图文至少9张",
                            "source_evidence": ["用户要求图片至少9张"],
                        },
                        {
                            "op": "insert_table_row",
                            "operation_id": "op-img-9",
                            "table_block_id": "table-img",
                            "row_index": -1,
                            "cell_texts": ["图9", "草坪球场近景", "足球赛参与感", "H5活动收束", "不放产品"],
                            "minimum_rows": 9,
                            "content_spec": "图文至少9张",
                            "source_evidence": ["用户要求图片至少9张"],
                        },
                    ],
                    "manual_actions": [],
                    "changed_sections": ["图片脚本"],
                    "commercial_delivery_record_fields": {},
                },
            )

            result = harness.handle_修改(
                self._message(
                    "文档链接：https://tcnwueberajc.feishu.cn/docx/doc-test\n"
                    "修改要求：1.图片至少需要9张哈\n2.文案方向加一点球赛、赛事、足球赛和h5活动，室外场景带草坪球场\n3.图4不需要了咱们没有产品就不用了"
                )
            )

            self.assertTrue(result.ok, result.reply)
            self.assertEqual(result.status, "document_edited")
            self.assertEqual(service.record_fields["内容规格"], "图文至少9张")
            applied_ops = result.extra["apply"]["applied_operations"]
            self.assertEqual([item["op"] for item in applied_ops], ["replace_text", "insert_table_row", "insert_table_row"])
            self.assertEqual(result.extra["patch_plan"]["operations"][1]["table_block_id"], "table-img")
            self.assertIn("insert_table_row", str(result.extra["patch_plan"]))
            self.assertNotIn("manual_actions", result.status)
        finally:
            if old_url is None:
                os.environ.pop("MEDIA_OS_COMMERCIAL_DELIVERY_URL", None)
            else:
                os.environ["MEDIA_OS_COMMERCIAL_DELIVERY_URL"] = old_url

    def test_handle_commercial_document_edit_unresolved_com01_stops_before_replace(self) -> None:
        old_url = os.environ.get("MEDIA_OS_COMMERCIAL_DELIVERY_URL")
        os.environ["MEDIA_OS_COMMERCIAL_DELIVERY_URL"] = "https://tcnwueberajc.feishu.cn/base/appTest?table=tblTest"
        try:
            service = SafeFeishuService(
                source_text="# 商单交付\n\n## 1. 作品信息\n\n## 2. 作品内容\n\n### 图片脚本\n脚本内容\n\n## 3. PR备注\n无特殊备注",
                records=[
                    {"record_id": "rec-a", "fields": {"文档ID": "doc-test"}},
                    {"record_id": "rec-b", "fields": {"文档ID": "doc-test"}},
                ],
            )
            harness = HandleCommercialDocumentEditHarness(service)

            result = harness.handle_修改(
                self._message("文档链接：https://tcnwueberajc.feishu.cn/docx/doc-test\n修改要求：改标题")
            )

            self.assertFalse(result.ok)
            self.assertEqual(result.status, "commercial_delivery_record_unresolved")
            self.assertNotIn("hash", service.calls)
            self.assertNotIn("replace", service.calls)
            self.assertNotIn("patch_apply", service.calls)
        finally:
            if old_url is None:
                os.environ.pop("MEDIA_OS_COMMERCIAL_DELIVERY_URL", None)
            else:
                os.environ["MEDIA_OS_COMMERCIAL_DELIVERY_URL"] = old_url

    def test_handle_commercial_document_edit_readback_failure_does_not_patch_com01(self) -> None:
        old_url = os.environ.get("MEDIA_OS_COMMERCIAL_DELIVERY_URL")
        os.environ["MEDIA_OS_COMMERCIAL_DELIVERY_URL"] = "https://tcnwueberajc.feishu.cn/base/appTest?table=tblTest"
        try:
            service = SafeFeishuService(
                readback_fail=True,
                source_text="# 商单交付\n\n## 1. 作品信息\n\n## 2. 作品内容\n\n### 图片脚本\n脚本内容\n\n## 3. PR备注\n无特殊备注",
                records=[
                    {
                        "record_id": "rec-commercial",
                        "fields": {
                            "作品初稿链接": {"text": "https://tcnwueberajc.feishu.cn/docx/doc-test", "link": "https://tcnwueberajc.feishu.cn/docx/doc-test"},
                            "文档ID": "doc-test",
                        },
                    }
                ],
            )
            harness = HandleCommercialDocumentEditHarness(service, record_fields={"标题": "新标题"})

            result = harness.handle_修改(
                self._message("文档链接：https://tcnwueberajc.feishu.cn/docx/doc-test\n修改要求：改标题")
            )

            self.assertFalse(result.ok)
            self.assertEqual(result.status, "document_edit_patch_readback_failed")
            self.assertIn("patch_apply", service.calls)
            self.assertIn("patch_readback", service.calls)
            self.assertNotIn("PUT /bitable/v1/apps/appTest/tables/tblTest/records/rec-commercial", service.calls)
        finally:
            if old_url is None:
                os.environ.pop("MEDIA_OS_COMMERCIAL_DELIVERY_URL", None)
            else:
                os.environ["MEDIA_OS_COMMERCIAL_DELIVERY_URL"] = old_url

    def test_handle_commercial_document_edit_empty_com01_readback_is_not_success(self) -> None:
        old_url = os.environ.get("MEDIA_OS_COMMERCIAL_DELIVERY_URL")
        os.environ["MEDIA_OS_COMMERCIAL_DELIVERY_URL"] = "https://tcnwueberajc.feishu.cn/base/appTest?table=tblTest"
        try:
            service = SafeFeishuService(
                empty_record_readback=True,
                source_text="# 商单交付\n\n## 1. 作品信息\n\n## 2. 作品内容\n\n### 图片脚本\n脚本内容\n\n## 3. PR备注\n无特殊备注",
                records=[
                    {
                        "record_id": "rec-commercial",
                        "fields": {
                            "作品初稿链接": {"text": "https://tcnwueberajc.feishu.cn/docx/doc-test", "link": "https://tcnwueberajc.feishu.cn/docx/doc-test"},
                            "文档ID": "doc-test",
                        },
                    }
                ],
            )
            harness = HandleCommercialDocumentEditHarness(
                service,
                record_fields={
                    "标题": "多重身份也能扛得住",
                    "一句话总结": "清扬 PK 瓶双赛道图文",
                },
            )

            result = harness.handle_修改(
                self._message("文档链接：https://tcnwueberajc.feishu.cn/docx/doc-test\n修改要求：改标题")
            )

            self.assertFalse(result.ok)
            self.assertEqual(result.status, "commercial_delivery_record_readback_failed")
            self.assertIn("PUT /bitable/v1/apps/appTest/tables/tblTest/records/rec-commercial", service.calls)
            self.assertIn("record_readback", service.calls)
            self.assertNotEqual(result.status, "document_edited")
        finally:
            if old_url is None:
                os.environ.pop("MEDIA_OS_COMMERCIAL_DELIVERY_URL", None)
            else:
                os.environ["MEDIA_OS_COMMERCIAL_DELIVERY_URL"] = old_url

    def test_handle_commercial_document_edit_field_parity_failure_is_not_success(self) -> None:
        old_url = os.environ.get("MEDIA_OS_COMMERCIAL_DELIVERY_URL")
        os.environ["MEDIA_OS_COMMERCIAL_DELIVERY_URL"] = "https://tcnwueberajc.feishu.cn/base/appTest?table=tblTest"
        try:
            service = SafeFeishuService(
                stale_record_readback=True,
                source_text="# 商单交付\n\n## 作品信息\n\n## 作品内容\n\n### 图片脚本\n脚本内容\n\n## PR备注\n无特殊备注",
                records=[
                    {
                        "record_id": "rec-commercial",
                        "fields": {
                            "作品初稿链接": {"text": "https://tcnwueberajc.feishu.cn/docx/doc-test", "link": "https://tcnwueberajc.feishu.cn/docx/doc-test"},
                            "文档ID": "doc-test",
                            "标题": "旧标题",
                        },
                    }
                ],
            )
            harness = HandleCommercialDocumentEditHarness(
                service,
                record_fields={
                    "标题": "新标题",
                    "一句话总结": "新总结",
                },
            )

            result = harness.handle_修改(
                self._message("文档链接：https://tcnwueberajc.feishu.cn/docx/doc-test\n修改要求：改标题")
            )

            self.assertFalse(result.ok)
            self.assertEqual(result.status, "commercial_delivery_record_parity_failed")
            self.assertIn("PUT /bitable/v1/apps/appTest/tables/tblTest/records/rec-commercial", service.calls)
        finally:
            if old_url is None:
                os.environ.pop("MEDIA_OS_COMMERCIAL_DELIVERY_URL", None)
            else:
                os.environ["MEDIA_OS_COMMERCIAL_DELIVERY_URL"] = old_url


if __name__ == "__main__":
    unittest.main()
