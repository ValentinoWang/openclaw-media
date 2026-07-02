from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable

from ..services.feishu_docx_renderer import FeishuDocxBlockRenderer, NATIVE_TABLE_KIND


class CreationFeishuDocumentWriter(ABC):
    """Canonical writer for creation task-pool child documents."""

    @property
    @abstractmethod
    def parent_node_token(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def heading_block(self, level: int, text: str) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def text_block(self, text: str) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def replace_child_doc_blocks(self, doc_title: str, blocks: list[dict[str, Any]]) -> dict[str, str]:
        raise NotImplementedError

    def blocks_from_text(self, doc_title: str, record_type: str, content: str) -> list[dict[str, Any]]:
        return FeishuDocxBlockRenderer(self.heading_block, self.text_block).render(
            content,
            leading_blocks=[
                self.heading_block(1, doc_title),
                self.text_block(f"标签：{record_type}"),
            ],
        )

    def sync_text_child_doc(self, doc_title: str, record_type: str, content: str) -> dict[str, str]:
        return self.replace_child_doc_blocks(doc_title, self.blocks_from_text(doc_title, record_type, content))


class RouterCreationFeishuDocumentWriter(CreationFeishuDocumentWriter):
    def __init__(
        self,
        *,
        feishu_service: Any,
        parent_node_token: str,
        heading_factory: Callable[[int, str], dict[str, Any]],
        text_factory: Callable[[str], dict[str, Any]],
    ) -> None:
        self.feishu_service = feishu_service
        self._parent_node_token = parent_node_token
        self._heading_factory = heading_factory
        self._text_factory = text_factory

    @property
    def parent_node_token(self) -> str:
        return self._parent_node_token

    def heading_block(self, level: int, text: str) -> dict[str, Any]:
        return self._heading_factory(level, text)

    def text_block(self, text: str) -> dict[str, Any]:
        return self._text_factory(text)

    def replace_child_doc_blocks(self, doc_title: str, blocks: list[dict[str, Any]]) -> dict[str, str]:
        if not hasattr(self.feishu_service, "replace_child_entry_under_node_blocks"):
            raise RuntimeError("FeishuService 缺少按父节点替换子文档 blocks 的能力，拒绝写入创作任务池")
        return self.feishu_service.replace_child_entry_under_node_blocks(self.parent_node_token, doc_title, blocks)
