from __future__ import annotations

import unittest

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


if __name__ == "__main__":
    unittest.main()
