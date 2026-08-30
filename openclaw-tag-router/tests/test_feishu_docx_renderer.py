from __future__ import annotations

import unittest

from common.feishu_docx_table_limits import (
    FeishuDocxTableBudgetError,
    FeishuDocxTableLimitError,
    validate_docx_table_create_shape,
    validate_docx_table_official_shape,
)
from openclaw_app.services.feishu_docx_renderer import NATIVE_TABLE_KIND
from openclaw_app.services.feishu_service import FeishuService


class FeishuDocxRendererTest(unittest.TestCase):
    def test_service_text_renderer_converts_markdown_headings_lists_and_tables(self) -> None:
        service = FeishuService("local_markdown", "/tmp/openclaw-feishu-doc-test")

        blocks = service._content_to_docx_blocks(
            "\n".join(
                [
                    "# 总标题",
                    "## 分镜脚本",
                    "- 不要保留 markdown 列表符",
                    "| 时间 | 画面 | 字幕 |",
                    "| --- | --- | --- |",
                    "| 0-3s | 起跑 | 毕业前后 |",
                    "[来源](https://example.com)",
                ]
            )
        )

        self.assertEqual(blocks[0]["block_type"], 3)
        self.assertEqual(blocks[1]["block_type"], 4)
        text_blocks = [block for block in blocks if block.get("block_type") == 2]
        self.assertTrue(any("• 不要保留 markdown 列表符" in str(block) for block in text_blocks))
        self.assertTrue(any("来源：https://example.com" in str(block) for block in text_blocks))
        table_blocks = [block for block in blocks if block.get("_openclaw_kind") == NATIVE_TABLE_KIND]
        self.assertEqual(len(table_blocks), 1)
        self.assertEqual(table_blocks[0]["rows"][0], ["时间", "画面", "字幕"])

    def test_service_text_renderer_expands_literal_newlines_in_tag_examples(self) -> None:
        service = FeishuService("local_markdown", "/tmp/openclaw-feishu-doc-test")

        blocks = service._content_to_docx_blocks("输入格式：`【活动】\\n平台：小红书\\n活动链接：https://example.com`")

        text_blocks = [block for block in blocks if block.get("block_type") == 2]
        rendered = text_blocks[0]["text"]["elements"][0]["text_run"]["content"]
        self.assertNotIn("\\n", rendered)
        self.assertIn("【活动】\n平台：小红书\n活动链接：https://example.com", rendered)

    def test_docx_block_summary_marks_plain_text_patchable(self) -> None:
        service = FeishuService("local_markdown", "/tmp/openclaw-feishu-doc-test")

        summary = service._summarize_docx_block(
            {
                "block_id": "blk-text",
                "block_type": 2,
                "text": {"elements": [{"text_run": {"content": "plain", "text_element_style": {}}}]},
            },
            path="0",
        )

        self.assertTrue(summary["is_plain_text_patchable"])
        self.assertEqual(summary["text_element_kinds"], ["text_run_plain"])
        self.assertEqual(summary["non_plain_text_element_kinds"], [])

    def test_docx_block_summary_protects_rich_text_elements(self) -> None:
        service = FeishuService("local_markdown", "/tmp/openclaw-feishu-doc-test")

        summary = service._summarize_docx_block(
            {
                "block_id": "blk-rich",
                "block_type": 2,
                "text": {
                    "elements": [
                        {"text_run": {"content": "bold", "text_element_style": {"bold": True}}},
                        {"text_run": {"content": "link", "text_element_style": {}, "link": {"url": "https://example.com"}}},
                        {"mention_user": {"user_id": "ou_xxx"}},
                    ]
                },
            },
            path="0",
        )

        self.assertFalse(summary["is_plain_text_patchable"])
        self.assertIn("text_run_styled", summary["non_plain_text_element_kinds"])
        self.assertIn("mention_user", summary["non_plain_text_element_kinds"])

    def test_docx_source_hash_ignores_volatile_block_metadata(self) -> None:
        left = {
            "document_id": "doc-test",
            "text": "标题\n正文",
            "root_blocks": [
                {
                    "block_id": "block-1",
                    "path": "0",
                    "block_type": 2,
                    "kind": "text",
                    "text": "正文",
                    "raw_keys": ["block_id", "text"],
                    "parent_id": "parent-a",
                    "children": [],
                }
            ],
        }
        right = {
            "document_id": "doc-test",
            "text": "标题\n正文",
            "root_blocks": [
                {
                    "block_id": "block-1",
                    "path": "0",
                    "block_type": 2,
                    "kind": "text",
                    "text": "正文",
                    "raw_keys": ["text", "block_id", "updated_at"],
                    "parent_id": "parent-b",
                    "temporary": {"read_id": "different"},
                    "children": [],
                }
            ],
        }
        changed_text = {
            **right,
            "text": "标题\n正文已改",
            "root_blocks": [{**right["root_blocks"][0], "text": "正文已改"}],
        }
        raw_content_only_change = {
            **right,
            "text": "飞书 raw_content 视图顺序临时变化，但 block tree 没变",
        }

        self.assertEqual(FeishuService._docx_source_hash(left), FeishuService._docx_source_hash(right))
        self.assertEqual(FeishuService._docx_source_hash(left), FeishuService._docx_source_hash(raw_content_only_change))
        self.assertNotEqual(FeishuService._docx_source_hash(left), FeishuService._docx_source_hash(changed_text))

    def test_document_edit_patch_helpers_emit_block_level_requests(self) -> None:
        class RecordingFeishuService(FeishuService):
            def __init__(self) -> None:
                super().__init__("local_markdown", "/tmp/openclaw-feishu-doc-test")
                self.requests: list[tuple[str, str, dict | None, dict | None]] = []

            def _request(self, method: str, path: str, *, json_body: dict | None = None, params: dict | None = None) -> dict:  # type: ignore[override]
                self.requests.append((method, path, json_body, params))
                return {"data": {"items": [{"block_id": "anchor"}, {"block_id": "next"}]}}

        service = RecordingFeishuService()

        service._patch_docx_text_elements("doc", "blk-text", "new text")
        index = service._resolve_docx_child_insert_index("doc", "parent", "anchor", after=True)
        service._insert_docx_children_at("doc", "parent", index, [service._text_block("inserted")])
        service._delete_docx_child_range("doc", "parent", 1, 2)

        self.assertEqual(service.requests[0][0], "PATCH")
        self.assertEqual(service.requests[0][1], "/docx/v1/documents/doc/blocks/blk-text")
        self.assertEqual(service.requests[0][2]["update_text_elements"]["elements"][0]["text_run"]["content"], "new text")
        self.assertEqual(service.requests[2][0], "POST")
        self.assertEqual(service.requests[2][2]["index"], 1)
        self.assertEqual(service.requests[3][0], "DELETE")
        self.assertEqual(service.requests[3][1], "/docx/v1/documents/doc/blocks/parent/children/batch_delete")

    def test_document_edit_insert_helper_rejects_static_large_batches(self) -> None:
        service = FeishuService("local_markdown", "/tmp/openclaw-feishu-doc-test")

        with self.assertRaisesRegex(RuntimeError, "document_edit_patch_batch_too_large"):
            service._insert_docx_children_at("doc", "parent", 0, [service._text_block(str(index)) for index in range(21)])

    def test_service_text_renderer_converts_bulleted_pipe_tables(self) -> None:
        service = FeishuService("local_markdown", "/tmp/openclaw-feishu-doc-test")

        blocks = service._content_to_docx_blocks(
            "\n".join(
                [
                    "## 分镜脚本",
                    "- | 时间 | 画面 | 字幕/口播 | 声音/拍摄注意 |",
                    "- |---|---|---|---|",
                    "- | 0-3秒 | 学位服集合 | 3小时拍完毕业照 | 先拍空景再入画 |",
                    "• | 3-8秒 | 调整学位帽 | 先整理状态 | 保留现场笑声 |",
                ]
            )
        )

        table_blocks = [block for block in blocks if block.get("_openclaw_kind") == NATIVE_TABLE_KIND]
        self.assertEqual(len(table_blocks), 1)
        self.assertEqual(table_blocks[0]["rows"][0], ["时间", "画面", "字幕/口播", "声音/拍摄注意"])
        self.assertEqual(table_blocks[0]["rows"][1][0], "0-3秒")
        self.assertEqual(table_blocks[0]["rows"][2][0], "3-8秒")

    def test_native_table_chunks_keep_commercial_script_rows_contiguous(self) -> None:
        image_rows = [["序号", "图片内容/画面", "拍摄指导", "画面文案", "产品露出", "道具/备注"]]
        image_rows.extend([[str(index), "画面", "指导", "文案", "露出", "备注"] for index in range(1, 6)])
        video_rows = [["镜号", "场景/画面", "时长/节奏", "拍摄指导", "口播/字幕", "产品露出", "道具/备注"]]
        video_rows.extend([[str(index), "场景", "节奏", "指导", "口播", "露出", "备注"] for index in range(1, 6)])

        image_chunks = FeishuService._table_chunks(image_rows)
        video_chunks = FeishuService._table_chunks(video_rows)

        self.assertEqual([len(chunk) for chunk in image_chunks], [6])
        self.assertEqual([len(chunk) for chunk in video_chunks], [6])
        self.assertTrue(all(chunk[0] == image_rows[0] for chunk in image_chunks))
        self.assertTrue(all(chunk[0] == video_rows[0] for chunk in video_chunks))

    def test_native_table_chunks_use_live_feishu_docx_create_limits(self) -> None:
        rows = [["c1", "c2", "c3", "c4"]]
        rows.extend([[str(index), "a", "b", "c"] for index in range(1, 505)])

        chunks = FeishuService._table_chunks(rows)

        self.assertEqual([len(chunk) for chunk in chunks], [9] * 63)
        self.assertTrue(all(chunk[0] == rows[0] for chunk in chunks))

    def test_native_table_rejects_more_than_live_create_columns(self) -> None:
        rows = [[f"c{index}" for index in range(10)]]

        with self.assertRaises(FeishuDocxTableLimitError):
            FeishuService._table_chunks(rows)

    def test_table_limit_helper_separates_official_and_live_create_limits(self) -> None:
        validate_docx_table_official_shape(10, 1)
        validate_docx_table_official_shape(1, 10)

        with self.assertRaises(FeishuDocxTableLimitError):
            validate_docx_table_create_shape(10, 1)
        with self.assertRaises(FeishuDocxTableLimitError):
            validate_docx_table_create_shape(1, 10)

        validate_docx_table_create_shape(9, 9)

    def test_native_table_append_does_not_insert_continuation_paragraphs(self) -> None:
        class RecordingFeishuService(FeishuService):
            def __init__(self) -> None:
                super().__init__("local_markdown", "/tmp/openclaw-feishu-doc-test")
                self.events: list[tuple[str, list[list[str]]]] = []

            def _append_blocks_to_document(self, document_id: str, children: list[dict]) -> None:  # type: ignore[override]
                self.events.append(("blocks", [[str(children)]]))

            def _append_native_table_chunk(self, document_id: str, rows: list[list[str]]) -> None:  # type: ignore[override]
                self.events.append(("table", rows))

        rows = [["镜号", "场景/画面", "时长/节奏", "拍摄指导", "口播/字幕", "产品露出", "道具/备注"]]
        rows.extend([[str(index), "场景", "节奏", "指导", "口播", "露出", "备注"] for index in range(1, 6)])
        service = RecordingFeishuService()

        service._append_native_table_to_document("doc-test", rows)

        self.assertEqual([event[0] for event in service.events], ["table"])
        self.assertNotIn("续表", str(service.events))

    def test_native_table_append_rejects_cumulative_write_budget_before_writing(self) -> None:
        class RecordingFeishuService(FeishuService):
            def __init__(self) -> None:
                super().__init__("local_markdown", "/tmp/openclaw-feishu-doc-test")
                self.writes = 0

            def _append_native_table_chunk(self, document_id: str, rows: list[list[str]]) -> None:  # type: ignore[override]
                self.writes += 1

        rows = [["c1", "c2", "c3", "c4"]]
        rows.extend([[str(index), "a", "b", "c"] for index in range(1, 2001)])
        service = RecordingFeishuService()

        with self.assertRaises(FeishuDocxTableBudgetError):
            service._append_native_table_to_document("doc-test", rows)

        self.assertEqual(service.writes, 0)

    def test_native_table_chunk_cleans_created_table_on_cell_write_failure(self) -> None:
        class FailingCellWriteService(FeishuService):
            def __init__(self) -> None:
                super().__init__("local_markdown", "/tmp/openclaw-feishu-doc-test")
                self.root_child_count = 0
                self.deleted_ranges: list[dict[str, int]] = []

            def _list_document_child_blocks(self, document_id: str) -> list[dict]:  # type: ignore[override]
                return [{} for _ in range(self.root_child_count)]

            def _request(self, method: str, path: str, **kwargs):  # type: ignore[override]
                if method == "POST" and path.endswith("/blocks/doc-test/children"):
                    self.root_child_count = 1
                    return {
                        "data": {
                            "children": [
                                {
                                    "block_id": "table-1",
                                    "block_type": 31,
                                    "table": {"cells": ["cell-1"], "property": {"row_size": 1, "column_size": 1}},
                                }
                            ]
                        }
                    }
                if method == "POST" and path.endswith("/blocks/cell-1/children"):
                    raise RuntimeError("cell write failed")
                if method == "DELETE" and path.endswith("/children/batch_delete"):
                    body = kwargs.get("json_body") or {}
                    self.deleted_ranges.append(body)
                    self.root_child_count = int(body.get("start_index") or 0)
                    return {"code": 0}
                raise AssertionError(f"unexpected request: {method} {path}")

        service = FailingCellWriteService()

        with self.assertRaisesRegex(RuntimeError, "cell write failed"):
            service._append_native_table_chunk("doc-test", [["x"]])

        self.assertEqual(service.deleted_ranges, [{"start_index": 0, "end_index": 1}])


if __name__ == "__main__":
    unittest.main()
