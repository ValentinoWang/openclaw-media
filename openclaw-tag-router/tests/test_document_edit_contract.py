from __future__ import annotations

import unittest

from openclaw_app.services.document_edit_contract import (
    DOCUMENT_EDIT_PATCH_CONCURRENCY_SEMANTICS,
    DocumentEditContractViolation,
    DocumentEditIntentOperation,
    DocumentEditPatchPlan,
    DocumentEditWorkingCopy,
    load_document_edit_op_whitelist,
)


class DocumentEditPatchContractTest(unittest.TestCase):
    def _source(self) -> dict[str, object]:
        return {
            "url": "https://tcnwueberajc.feishu.cn/docx/doc-test",
            "document_id": "doc-test",
            "source_hash": "hash-before",
            "revision_token": "rev-before",
            "snapshot_path": "/tmp/document-edit-snapshot.json",
            "text": "旧正文",
            "protected_block_ids": ["image-block"],
            "protected_table_shapes": [],
            "product_facts_checked": ["source text only"],
        }

    def _plain_block(self) -> dict[str, object]:
        return {
            "block_id": "block-1",
            "path": ["root", "0"],
            "block_type": "paragraph",
            "text": "旧正文",
        }

    def _rich_block(self) -> dict[str, object]:
        return {
            "block_id": "rich-1",
            "path": ["root", "1"],
            "block_type": "paragraph",
            "text": "旧正文",
            "text_elements": [
                {"text_run": {"content": "旧"}},
                {"mention_user": {"user_id": "ou-test"}},
            ],
        }

    def test_patch_plan_rejects_executable_operation_without_block_id(self) -> None:
        with self.assertRaisesRegex(DocumentEditContractViolation, "block_id"):
            DocumentEditPatchPlan.from_mapping(
                {
                    "source": self._source(),
                    "block_refs": [self._plain_block()],
                    "operations": [
                        {
                            "op": "replace_text",
                            "path": ["root", "0"],
                            "expected_old_text": "旧正文",
                            "new_text": "新正文",
                        }
                    ],
                },
                executable_op_whitelist={"replace_text"},
            )

    def test_patch_plan_rejects_executable_operation_outside_whitelist(self) -> None:
        with self.assertRaisesRegex(DocumentEditContractViolation, "whitelist"):
            DocumentEditPatchPlan.from_mapping(
                {
                    "source": self._source(),
                    "block_refs": [self._plain_block()],
                    "operations": [
                        {
                            "op": "delete_image",
                            "block_id": "block-1",
                            "path": ["root", "0"],
                            "expected_old_text": "旧正文",
                            "new_text": "",
                        }
                    ],
                },
                executable_op_whitelist={"replace_text"},
            )

    def test_patch_plan_rejects_rich_text_executable_without_style_run_proof(self) -> None:
        with self.assertRaisesRegex(DocumentEditContractViolation, "rich text block without style-run proof"):
            DocumentEditPatchPlan.from_mapping(
                {
                    "source": self._source(),
                    "block_refs": [self._rich_block()],
                    "operations": [
                        {
                            "op": "replace_text",
                            "block_id": "rich-1",
                            "path": ["root", "1"],
                            "expected_old_text": "旧正文",
                            "new_text": "新正文",
                        }
                    ],
                },
                executable_op_whitelist={"replace_text"},
            )

    def test_patch_plan_allows_manual_action_for_rich_text_block(self) -> None:
        plan = DocumentEditPatchPlan.from_mapping(
            {
                "source": self._source(),
                "block_refs": [self._rich_block()],
                "manual_actions": [
                    {
                        "requested_op": "replace_text",
                        "block_id": "rich-1",
                        "path": ["root", "1"],
                        "reason": "rich_text_elements_without_style_run_proof",
                        "instructions": "Manual review is required before changing this rich text block.",
                    }
                ],
            },
            executable_op_whitelist={"replace_text"},
        )

        self.assertEqual(plan.manual_actions[0].block_id, "rich-1")
        self.assertEqual(plan.operations, [])
        self.assertIn("document_changed_since_read", DOCUMENT_EDIT_PATCH_CONCURRENCY_SEMANTICS)

    def test_patch_plan_uses_canonical_op_whitelist_file(self) -> None:
        whitelist = load_document_edit_op_whitelist()

        self.assertIn("replace_text", whitelist)
        self.assertIn("insert_table_row", whitelist)
        plan = DocumentEditPatchPlan.from_mapping(
            {
                "source": self._source(),
                "block_refs": [self._plain_block()],
                "operations": [
                    {
                        "op": "replace_text",
                        "block_id": "block-1",
                        "path": ["root", "0"],
                        "expected_old_text": "旧正文",
                        "new_text": "新正文",
                    }
                ],
            },
            executable_op_whitelist=whitelist,
        )

        self.assertEqual(plan.operations[0].op, "replace_text")

    def test_patch_plan_allows_proven_append_table_row_on_protected_table(self) -> None:
        plan = DocumentEditPatchPlan.from_mapping(
            {
                "source": {
                    **self._source(),
                    "protected_block_ids": ["table-1"],
                    "protected_table_shapes": [
                        {"block_id": "table-1", "path": "2", "table_shape": {"row_size": 3, "column_size": 5}}
                    ],
                },
                "operations": [
                    {
                        "op": "insert_table_row",
                        "operation_id": "op-img-4",
                        "block_id": "table-1",
                        "table_block_id": "table-1",
                        "path": ["2"],
                        "block_type": "31",
                        "table_shape": {"row_size": 3, "column_size": 5},
                        "protected": True,
                        "protection_reason": "table_shape_protected",
                        "row_index": -1,
                        "cell_texts": ["图4", "草坪球场补图", "H5活动", "球赛氛围", "不放产品"],
                        "minimum_rows": 9,
                        "content_spec": "图文至少9张",
                        "source_evidence": ["用户要求图片至少9张"],
                    }
                ],
            },
            executable_op_whitelist={"insert_table_row"},
        )

        self.assertEqual(plan.operations[0].op, "insert_table_row")
        self.assertEqual(plan.operations[0].row_index, -1)
        self.assertEqual(plan.operations[0].cell_texts[0], "图4")
        self.assertEqual(plan.operations[0].minimum_rows, 9)
        self.assertEqual(plan.operations[0].content_spec, "图文至少9张")
        self.assertIn("草坪球场补图", plan.operations[0].new_text)

    def test_insert_table_row_rejects_static_index_and_non_append(self) -> None:
        base = {
            "source": self._source(),
            "operations": [
                {
                    "op": "insert_table_row",
                    "block_id": "table-1",
                    "table_block_id": "table-1",
                    "path": ["2"],
                    "block_type": "31",
                    "table_shape": {"row_size": 3, "column_size": 5},
                    "row_index": 1,
                    "cell_texts": ["图4"],
                    "static_index": 1,
                }
            ],
        }

        with self.assertRaisesRegex(DocumentEditContractViolation, "static index"):
            DocumentEditPatchPlan.from_mapping(base, executable_op_whitelist={"insert_table_row"})
        without_static_index = dict(base)
        without_static_index["operations"] = [dict(base["operations"][0])]
        without_static_index["operations"][0].pop("static_index")
        with self.assertRaisesRegex(DocumentEditContractViolation, "row_index=-1"):
            DocumentEditPatchPlan.from_mapping(without_static_index, executable_op_whitelist={"insert_table_row"})

    def test_working_copy_projects_single_compact_view_and_patch_map(self) -> None:
        working_copy = DocumentEditWorkingCopy.from_patch_source(
            {
                "ok": True,
                "url": "https://tcnwueberajc.feishu.cn/docx/doc-test",
                "document_id": "doc-test",
                "source_hash": "hash-before",
                "revision_token": "docx-sha256:hash-before",
                "snapshot_path": "/tmp/document-edit-snapshot.json",
                "text": "标题\n正文",
                "patchable_blocks": [
                    {
                        "block_id": "block-title",
                        "path": ["0"],
                        "block_type": "2",
                        "text": "标题",
                    }
                ],
                "protected_blocks": [
                    {
                        "block_id": "block-image",
                        "path": ["1"],
                        "block_type": "image",
                        "reason": "image_block",
                    },
                    {
                        "block_id": "block-table",
                        "path": ["2"],
                        "block_type": "table",
                        "reason": "native_table_structure",
                        "table_shape": {"row_size": 3, "column_size": 2},
                    },
                ],
                "protected_table_shapes": [{"block_id": "block-table", "row_size": 3, "column_size": 2}],
            }
        )

        compact_view = working_copy.compact_view()

        self.assertIn("[block-title]", compact_view)
        self.assertIn("[block-image|PROTECTED]", compact_view)
        self.assertIn("[block-table|PROTECTED|table|rows=3|cols=2]", compact_view)
        self.assertEqual([item["block_id"] for item in working_copy.block_map()], ["block-title"])
        self.assertEqual(working_copy.patch_source()["protected_block_ids"], ["block-image", "block-table"])
        self.assertEqual(working_copy.summary()["contract_id"], "openclaw.document_edit.working_copy.v1")

    def test_manual_action_accepts_reason_only_llm_shape(self) -> None:
        plan = DocumentEditPatchPlan.from_mapping(
            {
                "source": self._source(),
                "manual_actions": [
                    {
                        "reason": "图片数量确认涉及受保护图片脚本表格和非文本结构块，不能自动判断或修改。",
                        "action": "verify_image_count",
                        "block_ids": ["block-image-script", "block-table"],
                    }
                ],
            },
            executable_op_whitelist={"replace_text"},
        )

        self.assertEqual(plan.manual_actions[0].instructions, plan.manual_actions[0].reason)
        self.assertEqual(plan.manual_actions[0].requested_op, "verify_image_count")
        self.assertEqual(plan.manual_actions[0].block_id, "block-image-script")

    def test_manual_action_accepts_action_only_instruction_shape(self) -> None:
        plan = DocumentEditPatchPlan.from_mapping(
            {
                "source": self._source(),
                "manual_actions": [
                    {
                        "action": "请人工删除或调整图片脚本中的图4；该区域包含受保护表格/非文本结构，不能自动执行。",
                        "block_ids": ["block-table"],
                    }
                ],
            },
            executable_op_whitelist={"replace_text"},
        )

        self.assertEqual(plan.manual_actions[0].reason, plan.manual_actions[0].instructions)
        self.assertIn("图4", plan.manual_actions[0].instructions)
        self.assertEqual(plan.manual_actions[0].block_id, "block-table")

    def test_working_copy_marks_truncated_snapshot_in_summary_and_compact_view(self) -> None:
        working_copy = DocumentEditWorkingCopy.from_patch_source(
            {
                "ok": True,
                "url": "https://tcnwueberajc.feishu.cn/docx/doc-test",
                "document_id": "doc-test",
                "source_hash": "hash-before",
                "revision_token": "docx-sha256:hash-before",
                "snapshot_path": "/tmp/document-edit-snapshot.json",
                "root_blocks": [{"block_id": "root", "tree_truncated": True}],
                "patchable_blocks": [
                    {
                        "block_id": "block-1",
                        "path": ["0"],
                        "block_type": "paragraph",
                        "text": "第一段",
                    },
                    {
                        "block_id": "block-2",
                        "path": ["1"],
                        "block_type": "paragraph",
                        "text": "第二段",
                    },
                ],
            }
        )

        compact_view = working_copy.compact_view(max_lines=1)

        self.assertTrue(working_copy.truncated)
        self.assertTrue(working_copy.summary()["truncated"])
        self.assertIn("[TRUNCATED]", compact_view)
        self.assertIn("chunked planning", compact_view)
        self.assertIn("[block-1]", compact_view)
        self.assertNotIn("[block-2]", compact_view)

    def test_working_copy_heading_chunk_view_filters_blocks_and_preserves_truncated_marker(self) -> None:
        working_copy = DocumentEditWorkingCopy.from_patch_source(
            {
                "ok": True,
                "url": "https://tcnwueberajc.feishu.cn/docx/doc-test",
                "document_id": "doc-test",
                "source_hash": "hash-before",
                "revision_token": "docx-sha256:hash-before",
                "snapshot_path": "/tmp/document-edit-snapshot.json",
                "truncated": True,
                "patchable_blocks": [
                    {
                        "block_id": "block-body",
                        "path": ["0"],
                        "block_type": "paragraph",
                        "heading_path": ["正文"],
                        "text": "正文段",
                    },
                    {
                        "block_id": "block-script",
                        "path": ["1"],
                        "block_type": "paragraph",
                        "heading_path": ["脚本"],
                        "text": "脚本段",
                    },
                ],
                "protected_blocks": [
                    {
                        "block_id": "block-image",
                        "path": ["2"],
                        "block_type": "image",
                        "heading_path": ["正文"],
                        "reason": "image_block",
                    }
                ],
            }
        )

        self.assertEqual(working_copy.visible_heading_paths(), [["正文"], ["脚本"]])
        chunk_view = working_copy.compact_view_for_heading_paths([["正文"]])

        self.assertIn("[h=正文][block-body]", chunk_view)
        self.assertIn("[h=正文][block-image|PROTECTED]", chunk_view)
        self.assertNotIn("[h=脚本][block-script]", chunk_view)
        self.assertIn("[TRUNCATED] visible heading chunk only", chunk_view)

    def test_replace_terms_intent_fans_out_to_replace_text_operations(self) -> None:
        working_copy = DocumentEditWorkingCopy.from_patch_source(
            {
                "ok": True,
                "url": "https://tcnwueberajc.feishu.cn/docx/doc-test",
                "document_id": "doc-test",
                "source_hash": "hash-before",
                "revision_token": "docx-sha256:hash-before",
                "snapshot_path": "/tmp/document-edit-snapshot.json",
                "patchable_blocks": [
                    {
                        "block_id": "block-1",
                        "path": ["0"],
                        "block_type": "paragraph",
                        "text": "苹果很好，苹果很甜",
                    },
                    {
                        "block_id": "block-2",
                        "path": ["1"],
                        "block_type": "paragraph",
                        "text": "没有匹配",
                    },
                ],
                "protected_blocks": [
                    {
                        "block_id": "block-image-caption",
                        "path": ["2"],
                        "block_type": "image",
                        "text": "苹果图片",
                        "reason": "image_block",
                    }
                ],
            }
        )

        plan = DocumentEditPatchPlan.from_intent_mapping(
            {
                "intent_operations": [
                    {
                        "op": "replace_terms",
                        "operation_id": "intent-1",
                        "old_text": "苹果",
                        "new_text": "梨",
                        "source_evidence": ["用户要求替换该词"],
                    }
                ]
            },
            working_copy=working_copy,
            executable_op_whitelist={"replace_text"},
        )

        self.assertEqual(len(plan.intent_operations), 1)
        self.assertEqual(len(plan.operations), 1)
        self.assertEqual(plan.operations[0].op, "replace_text")
        self.assertEqual(plan.operations[0].block.block_id, "block-1")
        self.assertEqual(plan.operations[0].expected_old_text, "苹果很好，苹果很甜")
        self.assertEqual(plan.operations[0].new_text, "梨很好，梨很甜")
        self.assertEqual(plan.operations[0].source_evidence, ["用户要求替换该词"])
        self.assertEqual(len(plan.manual_actions), 1)
        self.assertEqual(plan.manual_actions[0].block_id, "block-image-caption")
        self.assertEqual(plan.manual_actions[0].reason, "image_block")
        self.assertNotIn("intent_operations", plan.to_mapping())
        self.assertEqual(len(DocumentEditPatchPlan.from_mapping(plan.to_mapping(), executable_op_whitelist={"replace_text"}).operations), 1)

    def test_replace_terms_intent_scoped_absent_or_unmatched_blocks_becomes_manual_only(self) -> None:
        working_copy = DocumentEditWorkingCopy.from_patch_source(
            {
                "ok": True,
                "url": "https://tcnwueberajc.feishu.cn/docx/doc-test",
                "document_id": "doc-test",
                "source_hash": "hash-before",
                "revision_token": "docx-sha256:hash-before",
                "snapshot_path": "/tmp/document-edit-snapshot.json",
                "patchable_blocks": [
                    {
                        "block_id": "block-1",
                        "path": ["0"],
                        "block_type": "paragraph",
                        "text": "没有目标词",
                    }
                ],
            }
        )

        missing_target_plan = DocumentEditPatchPlan.from_intent_mapping(
            {
                "intent_operations": [
                    {
                        "op": "replace_terms",
                        "operation_id": "intent-missing",
                        "target_block_ids": ["block-missing"],
                        "old_text": "苹果",
                        "new_text": "梨",
                    }
                ]
            },
            working_copy=working_copy,
            executable_op_whitelist={"replace_text"},
        )
        unmatched_plan = DocumentEditPatchPlan.from_intent_mapping(
            {
                "intent_operations": [
                    {
                        "op": "replace_terms",
                        "operation_id": "intent-unmatched",
                        "target_block_ids": ["block-1"],
                        "old_text": "苹果",
                        "new_text": "梨",
                    }
                ]
            },
            working_copy=working_copy,
            executable_op_whitelist={"replace_text"},
        )

        self.assertEqual(missing_target_plan.operations, [])
        self.assertEqual(missing_target_plan.manual_actions[0].reason, "intent_target_block_not_found")
        self.assertEqual(missing_target_plan.manual_actions[0].block_id, "block-missing")
        self.assertEqual(unmatched_plan.operations, [])
        self.assertEqual(unmatched_plan.manual_actions[0].reason, "replace_terms_no_exact_match")

    def test_replace_terms_intent_rejects_non_exact_matching(self) -> None:
        with self.assertRaisesRegex(DocumentEditContractViolation, "exact match_mode"):
            DocumentEditIntentOperation.from_mapping(
                {
                    "op": "replace_terms",
                    "old_text": "苹果.*",
                    "new_text": "梨",
                    "match_mode": "regex",
                    "regex": True,
                }
            )

    def test_patch_plan_rejects_unexpanded_replace_terms_intent(self) -> None:
        with self.assertRaisesRegex(DocumentEditContractViolation, "WorkingCopy fanout"):
            DocumentEditPatchPlan.from_mapping(
                {
                    "source": self._source(),
                    "block_refs": [self._plain_block()],
                    "intent_operations": [
                        {
                            "op": "replace_terms",
                            "old_text": "旧",
                            "new_text": "新",
                        }
                    ],
                },
                executable_op_whitelist={"replace_text"},
            )

    def test_intent_patch_plan_rejects_mixed_llm_operations(self) -> None:
        working_copy = DocumentEditWorkingCopy.from_patch_source(
            {
                "ok": True,
                "url": "https://tcnwueberajc.feishu.cn/docx/doc-test",
                "document_id": "doc-test",
                "source_hash": "hash-before",
                "revision_token": "docx-sha256:hash-before",
                "snapshot_path": "/tmp/document-edit-snapshot.json",
                "patchable_blocks": [self._plain_block()],
            }
        )

        with self.assertRaisesRegex(DocumentEditContractViolation, "cannot mix"):
            DocumentEditPatchPlan.from_intent_mapping(
                {
                    "intent_operations": [
                        {
                            "op": "replace_terms",
                            "old_text": "旧",
                            "new_text": "新",
                        }
                    ],
                    "operations": [
                        {
                            "op": "replace_text",
                            "block_id": "block-1",
                            "new_text": "新正文",
                        }
                    ],
                },
                working_copy=working_copy,
                executable_op_whitelist={"replace_text"},
            )


if __name__ == "__main__":
    unittest.main()
