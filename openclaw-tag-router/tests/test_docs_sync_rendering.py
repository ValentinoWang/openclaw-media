from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType


def load_sync_module() -> ModuleType:
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "sync_tag_router_docs_to_feishu.py"
    spec = importlib.util.spec_from_file_location("sync_tag_router_docs_to_feishu", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_markdown_to_parts_expands_literal_newlines_in_tag_examples() -> None:
    sync = load_sync_module()
    markdown = "- 输入格式：链接格式：`【活动】\\n平台：小红书\\n活动链接：https://example.com`。"

    parts = sync.markdown_to_parts(markdown, "test-hash")
    text = "\n".join(
        sync.block_text(block)
        for part in parts
        for block in part.get("blocks", [])
        if sync.block_text(block)
    )

    assert "\\n" not in text
    assert "【活动】\n平台：小红书\n活动链接：https://example.com" in text
