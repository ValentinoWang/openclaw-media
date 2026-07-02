from __future__ import annotations

import unittest

from openclaw_app.router.creation_feishu_writer import NATIVE_TABLE_KIND
from openclaw_app.router.router_shared_helpers import RouterSharedHelpersMixin
from openclaw_app.router.unified_creation import UNIFIED_CREATION_PARENT_NODE_TOKEN, UnifiedCreationMixin


class FakeFeishuService:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def replace_child_entry_under_node_blocks(self, parent_node_token, child_doc_name, children):
        self.calls.append(
            {
                "parent_node_token": parent_node_token,
                "child_doc_name": child_doc_name,
                "children": children,
            }
        )
        return {"status": "synced", "doc": "https://example.com/doc", "render_mode": "docx_blocks"}

    def replace_child_entry_under_node(self, *_args, **_kwargs):
        raise AssertionError("creation task-pool docs must use native docx blocks")


class CreationDocHarness(UnifiedCreationMixin, RouterSharedHelpersMixin):
    def __init__(self) -> None:
        self.feishu_service = FakeFeishuService()


class CreationFeishuWriterTest(unittest.TestCase):
    def test_unified_creation_child_doc_uses_block_writer_and_native_table_marker(self) -> None:
        harness = CreationDocHarness()

        result = harness._sync_unified_creation_child_doc(
            "素材创作｜毕业百米",
            "素材创作",
            "\n".join(
                [
                    "## 分镜脚本",
                    "| 时间 | 画面 | 字幕 |",
                    "| --- | --- | --- |",
                    "| 0-3 秒 | 起跑和冲线 | 毕业前后，我又站上 100 米起点 |",
                ]
            ),
        )

        self.assertEqual(result["render_mode"], "docx_blocks")
        self.assertEqual(harness.feishu_service.calls[0]["parent_node_token"], UNIFIED_CREATION_PARENT_NODE_TOKEN)
        blocks = harness.feishu_service.calls[0]["children"]
        self.assertTrue(any(block.get("_openclaw_kind") == NATIVE_TABLE_KIND for block in blocks))


if __name__ == "__main__":
    unittest.main()
