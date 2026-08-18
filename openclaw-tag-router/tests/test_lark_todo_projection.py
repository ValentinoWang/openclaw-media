from __future__ import annotations

from integrations.feishu.lark_document_gateway import AuthenticatedLarkDocumentClient


def todo_block(checked: bool) -> dict[str, object]:
    return {
        "id": "todo_public_1",
        "type": "todo_item",
        "attrs": {"checked": checked},
        "content": [{"type": "text", "text": "待办", "marks": []}],
    }


def test_todo_writer_uses_feishu_todo_style_done() -> None:
    encoded = AuthenticatedLarkDocumentClient._encode_block(todo_block(True))

    assert "done" not in encoded
    assert encoded["todo"]["style"]["done"] is True


def test_todo_reader_uses_feishu_todo_style_done() -> None:
    decoded = AuthenticatedLarkDocumentClient._decode_native(
        {
            "block_id": "todo_remote_1",
            "block_type": 17,
            "todo": {
                "elements": [
                    {
                        "text_run": {
                            "content": "待办",
                            "text_element_style": {},
                        }
                    }
                ],
                "style": {"done": True},
            },
        },
        0,
    )

    assert decoded["attrs"]["checked"] is True
