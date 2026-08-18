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


def test_clear_doc_reads_only_one_delete_batch_per_iteration(monkeypatch) -> None:
    sync = load_sync_module()
    list_calls: list[tuple[int, int | None]] = []
    delete_calls: list[dict] = []

    def fake_list(_document_id: str, _token: str, *, page_size: int = 100, max_items: int | None = None):
        list_calls.append((page_size, max_items))
        return [{"block_id": str(index)} for index in range(20)] if len(list_calls) == 1 else []

    def fake_request(_method: str, _path: str, _token: str | None = None, **kwargs):
        delete_calls.append(kwargs["json"])
        return {"code": 0}

    monkeypatch.setattr(sync, "list_root_children", fake_list)
    monkeypatch.setattr(sync, "request_json", fake_request)
    monkeypatch.setattr(sync.time, "sleep", lambda _seconds: None)

    sync.clear_doc("doc", "token")

    assert list_calls == [(20, 20), (20, 20)]
    assert delete_calls == [{"start_index": 0, "end_index": 20}]
