from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, ClassVar, Mapping


DOCUMENT_EDIT_CONTRACT_ID = "openclaw.document_edit.typed_schema.v1"
DOCUMENT_EDIT_CONTRACT_OWNER = "openclaw-maintenance"
DOCUMENT_EDIT_MIGRATION_PLAN = (
    "document_edit writes migrate to patch-first typed boundaries: "
    "DocumentEditPatchSource -> DocumentEditPatchPlan -> "
    "DocumentEditPatchApplyResult -> DocumentEditPatchReadbackResult. Full-document "
    "Markdown output and replace_document_url are not document_edit consumer paths."
)
DOCUMENT_EDIT_DOWNSTREAM_CONSUMER_TEST = (
    "tests/test_document_tools.py::test_document_edit_patch_contract_downstream_consumer_surface"
)
DOCUMENT_EDIT_PATCH_CONTRACT_ID = "openclaw.document_edit.patch_first_schema.v1"
DOCUMENT_EDIT_WORKING_COPY_CONTRACT_ID = "openclaw.document_edit.working_copy.v1"
DOCUMENT_EDIT_INTENT_OP_CONTRACT_ID = "openclaw.document_edit.intent_ops.v1"
DOCUMENT_EDIT_PATCH_CONCURRENCY_SEMANTICS = (
    "source_hash and revision_token both use the existing document_changed_since_read "
    "readback semantics; patch-first does not introduce a second concurrency model."
)
DOCUMENT_EDIT_OP_WHITELIST_PATH = Path(__file__).resolve().parents[2] / "data" / "document_edit_op_whitelist.json"


class DocumentEditContractViolation(ValueError):
    """Raised when a document_edit state cannot cross the typed contract boundary."""


def _text(value: Any) -> str:
    return str(value or "").strip()


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _text_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [_text(item) for item in value if _text(item)]
    if _text(value):
        return [_text(value)]
    return []


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise DocumentEditContractViolation(message)


def _has_key(payload: Mapping[str, Any], key: str) -> bool:
    return key in payload and payload.get(key) is not None


def _op_whitelist(value: Any) -> set[str]:
    if isinstance(value, (set, tuple, list)):
        return {_text(item) for item in value if _text(item)}
    return set()


def load_document_edit_op_whitelist(path: str | Path = DOCUMENT_EDIT_OP_WHITELIST_PATH) -> set[str]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    ops = payload.get("ops") if isinstance(payload, dict) else []
    return {
        _text(item.get("op"))
        for item in ops
        if isinstance(item, Mapping) and item.get("enabled") is True and _text(item.get("op"))
    }


def _plain_text_element(element: Any) -> bool:
    if not isinstance(element, Mapping):
        return False
    if set(element.keys()) != {"text_run"}:
        return False
    text_run = element.get("text_run")
    if not isinstance(text_run, Mapping):
        return False
    return set(text_run.keys()) <= {"content", "text"}


def _has_non_plain_text_elements(value: Any) -> bool:
    elements = _list(value)
    return bool(elements) and any(not _plain_text_element(element) for element in elements)


def _tree_has_flag(value: Any, *flags: str) -> bool:
    if isinstance(value, Mapping):
        if any(bool(value.get(flag)) for flag in flags):
            return True
        return any(_tree_has_flag(child, *flags) for child in value.values())
    if isinstance(value, list):
        return any(_tree_has_flag(item, *flags) for item in value)
    return False


def _tree_has_executable_truncation(value: Any) -> bool:
    if isinstance(value, Mapping):
        if bool(value.get("tree_truncated")):
            return True
        if bool(value.get("children_truncated")):
            block_type = _text(value.get("block_type") or value.get("type"))
            kind = _text(value.get("kind"))
            # Native table and cell descendants are protected by the patch contract.
            # Their unread child content must become manual_actions, not block safe
            # paragraph edits elsewhere in the document.
            if block_type not in {"31", "32"} and kind not in {"table", "table_cell"}:
                return True
        return any(_tree_has_executable_truncation(child) for child in value.values())
    if isinstance(value, list):
        return any(_tree_has_executable_truncation(item) for item in value)
    return False


@dataclass(frozen=True)
class DocumentEditContractMetadata:
    contract_id: str = DOCUMENT_EDIT_CONTRACT_ID
    contract_owner: str = DOCUMENT_EDIT_CONTRACT_OWNER
    migration_plan: str = DOCUMENT_EDIT_MIGRATION_PLAN
    downstream_consumer_test: str = DOCUMENT_EDIT_DOWNSTREAM_CONSUMER_TEST
    protected_invariant: str = (
        "A Feishu Docx may be overwritten by document_edit only after explicit "
        "targeting, snapshot, source hash verification, strict LLM output, safe "
        "replace, readback, and family-specific checks."
    )


@dataclass(frozen=True)
class DocumentEditSourcePreflight:
    url: str
    document_id: str
    text: str
    source_hash: str
    snapshot_path: str
    document_family: str = "generic_docx"
    producer_capability: str = ""
    family_contract_id: str = "document_edit.generic_docx"
    document_family_provenance: str = "generic_default"
    root_blocks: list[Any] = field(default_factory=list)
    unsupported_blocks: list[Any] = field(default_factory=list)
    native_table_count: int = 0

    contract: ClassVar[DocumentEditContractMetadata] = DocumentEditContractMetadata()

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any], *, target_doc_url: str) -> "DocumentEditSourcePreflight":
        _require(bool(payload.get("ok")), "preflight must be ok before source can enter document_edit")
        unsupported = _list(payload.get("unsupported_blocks") or payload.get("unsupported_document_blocks"))
        _require(not unsupported, "preflight source contains unsupported non-roundtrippable blocks")
        _require(payload.get("safe_to_replace") is not False, "preflight source is not marked safe to replace")
        text = _text(payload.get("text"))
        source_hash = _text(payload.get("source_hash") or payload.get("source_block_hash"))
        snapshot_path = _text(payload.get("snapshot_path"))
        _require(text, "preflight source text is empty")
        _require(source_hash, "preflight source_hash is required")
        _require(snapshot_path, "preflight snapshot_path is required")
        family = _text(payload.get("document_family") or "generic_docx")
        return cls(
            url=_text(payload.get("url") or target_doc_url),
            document_id=_text(payload.get("document_id")),
            text=text,
            source_hash=source_hash,
            snapshot_path=snapshot_path,
            document_family=family,
            producer_capability=_text(payload.get("producer_capability")),
            family_contract_id=_text(payload.get("family_contract_id") or f"document_edit.{family}"),
            document_family_provenance=_text(payload.get("document_family_provenance") or "generic_default"),
            root_blocks=_list(payload.get("root_blocks") or payload.get("source_block_snapshot")),
            unsupported_blocks=unsupported,
            native_table_count=int(payload.get("native_table_count") or 0),
        )

    def to_mapping(self) -> dict[str, Any]:
        payload = asdict(self)
        payload.update(
            {
                "ok": True,
                "source_block_snapshot": list(self.root_blocks),
                "source_block_hash": self.source_hash,
                "preflight_status": "passed",
                "unsupported_document_blocks": [],
                "unsupported_block_types": [],
                "contract_id": DOCUMENT_EDIT_CONTRACT_ID,
                "contract_owner": DOCUMENT_EDIT_CONTRACT_OWNER,
            }
        )
        return payload


@dataclass(frozen=True)
class DocumentEditPatchSource:
    url: str
    document_id: str
    source_hash: str
    revision_token: str
    snapshot_path: str
    text: str = ""
    snapshot_depth: int = 1
    snapshot_max_blocks: int = 500
    protected_block_ids: list[str] = field(default_factory=list)
    protected_table_shapes: list[Any] = field(default_factory=list)
    product_facts_checked: list[str] = field(default_factory=list)

    contract: ClassVar[DocumentEditContractMetadata] = DocumentEditContractMetadata(
        protected_invariant=(
            "Patch-first document_edit must use block-level operations and must validate "
            "source_hash/revision_token with document_changed_since_read semantics."
        )
    )

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "DocumentEditPatchSource":
        source_hash = _text(payload.get("source_hash") or payload.get("source_block_hash"))
        revision_token = _text(payload.get("revision_token"))
        _require(_text(payload.get("url") or payload.get("doc_url")), "patch source requires url")
        _require(_text(payload.get("document_id")), "patch source requires document_id")
        _require(source_hash, "patch source requires source_hash")
        _require(revision_token, "patch source requires revision_token")
        _require(_text(payload.get("snapshot_path")), "patch source requires snapshot_path")
        return cls(
            url=_text(payload.get("url") or payload.get("doc_url")),
            document_id=_text(payload.get("document_id")),
            source_hash=source_hash,
            revision_token=revision_token,
            snapshot_path=_text(payload.get("snapshot_path")),
            text=str(payload.get("text") or ""),
            snapshot_depth=int(payload.get("snapshot_depth") or 1),
            snapshot_max_blocks=int(payload.get("snapshot_max_blocks") or 500),
            protected_block_ids=_text_list(payload.get("protected_block_ids")),
            protected_table_shapes=_list(payload.get("protected_table_shapes")),
            product_facts_checked=_text_list(payload.get("product_facts_checked")),
        )

    def to_mapping(self) -> dict[str, Any]:
        payload = asdict(self)
        payload.update(
            {
                "ok": True,
                "contract_id": DOCUMENT_EDIT_PATCH_CONTRACT_ID,
                "concurrency_semantics": DOCUMENT_EDIT_PATCH_CONCURRENCY_SEMANTICS,
            }
        )
        return payload


@dataclass(frozen=True)
class DocumentEditBlockRef:
    block_id: str
    path: list[str]
    block_type: str = "text"
    text: str = ""
    table_shape: dict[str, Any] = field(default_factory=dict)
    protected: bool = False
    protection_reason: str = ""
    has_non_plain_text_elements: bool = False
    has_style_run_proof: bool = False

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "DocumentEditBlockRef":
        block_id = _text(payload.get("block_id") or payload.get("id"))
        path = _text_list(payload.get("path"))
        _require(block_id, "block ref requires block_id")
        _require(path, "block ref requires path")
        has_rich_text = bool(payload.get("has_non_plain_text_elements")) or _has_non_plain_text_elements(
            payload.get("text_elements") or payload.get("elements")
        )
        has_style_run_proof = bool(payload.get("has_style_run_proof") or payload.get("style_run_proof"))
        protected = bool(payload.get("protected"))
        protection_reason = _text(payload.get("protection_reason"))
        if has_rich_text and not has_style_run_proof:
            protected = True
            protection_reason = protection_reason or "rich_text_elements_without_style_run_proof"
        table_shape = payload.get("table_shape") if isinstance(payload.get("table_shape"), dict) else {}
        return cls(
            block_id=block_id,
            path=path,
            block_type=_text(payload.get("block_type") or payload.get("type") or "text"),
            text=str(payload.get("text") or ""),
            table_shape=dict(table_shape),
            protected=protected,
            protection_reason=protection_reason,
            has_non_plain_text_elements=has_rich_text,
            has_style_run_proof=has_style_run_proof,
        )

    def to_mapping(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DocumentEditWorkingBlock:
    block_id: str
    path: list[str]
    block_type: str = "text"
    text: str = ""
    heading_path: list[str] = field(default_factory=list)
    protected: bool = False
    protection_reason: str = ""
    table_shape: dict[str, Any] = field(default_factory=dict)
    has_non_plain_text_elements: bool = False
    has_style_run_proof: bool = False

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any], *, protected: bool = False, reason: str = "") -> "DocumentEditWorkingBlock":
        block_id = _text(payload.get("block_id") or payload.get("id"))
        path = _text_list(payload.get("path"))
        if not path and _text(payload.get("path")):
            path = [_text(payload.get("path"))]
        _require(block_id, "working block requires block_id")
        _require(path, "working block requires path")
        has_rich_text = bool(payload.get("has_non_plain_text_elements")) or bool(payload.get("non_plain_text_element_kinds"))
        table_shape = payload.get("table_shape") if isinstance(payload.get("table_shape"), dict) else {}
        return cls(
            block_id=block_id,
            path=path,
            block_type=_text(payload.get("block_type") or payload.get("type") or payload.get("kind") or "text"),
            text=str(payload.get("text") or ""),
            heading_path=_text_list(payload.get("heading_path")),
            protected=bool(protected or payload.get("protected")),
            protection_reason=_text(reason or payload.get("protection_reason") or payload.get("reason")),
            table_shape=dict(table_shape),
            has_non_plain_text_elements=has_rich_text,
            has_style_run_proof=bool(payload.get("has_style_run_proof") or payload.get("style_run_proof")),
        )

    def to_block_ref(self) -> dict[str, Any]:
        return {
            "block_id": self.block_id,
            "path": list(self.path),
            "block_type": self.block_type,
            "text": self.text,
            "table_shape": dict(self.table_shape),
            "heading_path": list(self.heading_path),
            "protected": self.protected,
            "protection_reason": self.protection_reason,
            "has_non_plain_text_elements": self.has_non_plain_text_elements,
            "has_style_run_proof": self.has_style_run_proof,
        }

    def compact_line(self) -> str:
        attrs = [self.block_id]
        if self.protected:
            attrs.append("PROTECTED")
        if self.table_shape:
            attrs.append("table")
            if self.table_shape.get("row_size"):
                attrs.append(f"rows={self.table_shape.get('row_size')}")
            if self.table_shape.get("column_size"):
                attrs.append(f"cols={self.table_shape.get('column_size')}")
        elif self.has_non_plain_text_elements and not self.has_style_run_proof:
            attrs.append("styled")
        heading = " > ".join(self.heading_path)
        prefix = f"[h={heading}]" if heading else ""
        text = self.text.strip() or self.protection_reason or self.block_type
        return f"{prefix}[{'|'.join(attrs)}] {text}".strip()

    def to_mapping(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DocumentEditIntentOperation:
    op: str
    old_text: str
    new_text: str
    operation_id: str = ""
    scope_block_ids: list[str] = field(default_factory=list)
    source_evidence: list[str] = field(default_factory=list)
    product_facts_checked: list[str] = field(default_factory=list)

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "DocumentEditIntentOperation":
        op = _text(payload.get("op") or payload.get("intent") or payload.get("operation"))
        _require(op == "replace_terms", "intent operation must be replace_terms")
        match_mode = _text(payload.get("match_mode") or payload.get("mode") or "exact")
        _require(match_mode == "exact", "replace_terms intent supports only exact match_mode")
        _require(not bool(payload.get("regex")), "replace_terms intent cannot use regex")
        _require(not bool(payload.get("case_insensitive")), "replace_terms intent cannot use case_insensitive matching")
        _require(not bool(payload.get("semantic_match")), "replace_terms intent cannot use semantic_match")
        old_text = _text(payload.get("old_text") or payload.get("find") or payload.get("term"))
        _require(old_text, "replace_terms intent requires old_text")
        _require(
            _has_key(payload, "new_text") or _has_key(payload, "replacement") or _has_key(payload, "replace_with"),
            "replace_terms intent requires new_text",
        )
        new_text_value = payload.get("new_text")
        if not _has_key(payload, "new_text"):
            new_text_value = payload.get("replacement") if _has_key(payload, "replacement") else payload.get("replace_with")
        return cls(
            op=op,
            old_text=old_text,
            new_text=str(new_text_value),
            operation_id=_text(payload.get("operation_id") or payload.get("id")),
            scope_block_ids=_text_list(payload.get("scope_block_ids") or payload.get("block_ids") or payload.get("target_block_ids")),
            source_evidence=_text_list(payload.get("source_evidence")),
            product_facts_checked=_text_list(payload.get("product_facts_checked")),
        )

    def to_mapping(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["contract_id"] = DOCUMENT_EDIT_INTENT_OP_CONTRACT_ID
        return payload


@dataclass(frozen=True)
class DocumentEditWorkingCopy:
    url: str
    document_id: str
    source_hash: str
    revision_token: str
    snapshot_path: str
    text: str = ""
    snapshot_depth: int = 1
    snapshot_max_blocks: int = 500
    blocks: list[DocumentEditWorkingBlock] = field(default_factory=list)
    protected_table_shapes: list[Any] = field(default_factory=list)
    truncated: bool = False

    @classmethod
    def from_patch_source(cls, payload: Mapping[str, Any], *, target_doc_url: str = "") -> "DocumentEditWorkingCopy":
        _require(bool(payload.get("ok")), "working copy source must be ok")
        url = _text(payload.get("url") or payload.get("doc_url") or target_doc_url)
        document_id = _text(payload.get("document_id"))
        source_hash = _text(payload.get("source_hash") or payload.get("source_block_hash"))
        revision_token = _text(payload.get("revision_token"))
        snapshot_path = _text(payload.get("snapshot_path"))
        _require(url, "working copy requires url")
        _require(document_id, "working copy requires document_id")
        _require(source_hash, "working copy requires source_hash")
        _require(revision_token, "working copy requires revision_token")
        _require(snapshot_path, "working copy requires snapshot_path")
        blocks_by_id: dict[str, DocumentEditWorkingBlock] = {}
        for item in _list(payload.get("patchable_blocks")):
            if isinstance(item, Mapping):
                block = DocumentEditWorkingBlock.from_mapping(item)
                blocks_by_id[block.block_id] = block
        for item in _list(payload.get("protected_blocks")):
            if isinstance(item, Mapping):
                block = DocumentEditWorkingBlock.from_mapping(
                    item,
                    protected=True,
                    reason=_text(item.get("reason") or "protected_block"),
                )
                blocks_by_id[block.block_id] = block
        truncated = bool(payload.get("truncated") or payload.get("tree_truncated"))
        if _tree_has_executable_truncation(payload.get("root_blocks")):
            truncated = True
        return cls(
            url=url,
            document_id=document_id,
            source_hash=source_hash,
            revision_token=revision_token,
            snapshot_path=snapshot_path,
            text=str(payload.get("text") or ""),
            snapshot_depth=int(payload.get("snapshot_depth") or 1),
            snapshot_max_blocks=int(payload.get("snapshot_max_blocks") or 500),
            blocks=list(blocks_by_id.values()),
            protected_table_shapes=_list(payload.get("protected_table_shapes")),
            truncated=truncated,
        )

    def patch_source(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "document_id": self.document_id,
            "source_hash": self.source_hash,
            "revision_token": self.revision_token,
            "snapshot_path": self.snapshot_path,
            "snapshot_depth": self.snapshot_depth,
            "snapshot_max_blocks": self.snapshot_max_blocks,
            "text": self.text,
            "protected_block_ids": [block.block_id for block in self.blocks if block.protected],
            "protected_table_shapes": list(self.protected_table_shapes),
            "product_facts_checked": [],
        }

    def block_map(self) -> list[dict[str, Any]]:
        return [block.to_block_ref() for block in self.blocks if not block.protected]

    def block_by_id(self) -> dict[str, DocumentEditWorkingBlock]:
        return {block.block_id: block for block in self.blocks}

    def fanout_intent_operations(self, intent_operations: list[DocumentEditIntentOperation]) -> dict[str, list[dict[str, Any]]]:
        operations: list[dict[str, Any]] = []
        manual_actions: list[dict[str, Any]] = []
        block_by_id = self.block_by_id()
        for intent_index, intent in enumerate(intent_operations, start=1):
            target_blocks = self.blocks
            if intent.scope_block_ids:
                target_blocks = []
                for block_id in intent.scope_block_ids:
                    block = block_by_id.get(block_id)
                    if block is None:
                        manual_actions.append(
                            {
                                "reason": "intent_target_block_not_found",
                                "instructions": f"Review replace_terms manually because target block is absent: {block_id}",
                                "requested_op": intent.op,
                                "block_id": block_id,
                            }
                        )
                    else:
                        target_blocks.append(block)
            matched = 0
            for block in target_blocks:
                if intent.old_text not in block.text:
                    continue
                matched += 1
                if block.protected:
                    manual_actions.append(
                        {
                            "reason": block.protection_reason or "protected_block",
                            "instructions": "Review replace_terms manually because the matched block is protected.",
                            "requested_op": intent.op,
                            "block_id": block.block_id,
                            "path": list(block.path),
                        }
                    )
                    continue
                if block.has_non_plain_text_elements and not block.has_style_run_proof:
                    manual_actions.append(
                        {
                            "reason": "rich_text_elements_without_style_run_proof",
                            "instructions": "Review replace_terms manually because the matched block contains rich text without style-run proof.",
                            "requested_op": intent.op,
                            "block_id": block.block_id,
                            "path": list(block.path),
                        }
                    )
                    continue
                operation_root = intent.operation_id or f"replace_terms_{intent_index}"
                operations.append(
                    {
                        "op": "replace_text",
                        "operation_id": f"{operation_root}_{len(operations) + 1}",
                        "block_id": block.block_id,
                        "path": list(block.path),
                        "block_type": block.block_type,
                        "expected_old_text": block.text,
                        "new_text": block.text.replace(intent.old_text, intent.new_text),
                        "source_evidence": list(intent.source_evidence),
                        "product_facts_checked": list(intent.product_facts_checked),
                    }
                )
            if matched == 0:
                manual_actions.append(
                    {
                        "reason": "replace_terms_no_exact_match",
                        "instructions": f"Review replace_terms manually because no exact old_text match was found: {intent.old_text}",
                        "requested_op": intent.op,
                    }
                )
        return {"operations": operations, "manual_actions": manual_actions}

    def compact_view(self, *, max_lines: int = 500) -> str:
        lines = [block.compact_line() for block in self.blocks[:max_lines]]
        if self.truncated or len(self.blocks) > max_lines:
            lines.append("[TRUNCATED] document_edit working copy is incomplete; use chunked planning before executable patch.")
        return "\n".join(lines)

    def visible_heading_paths(self) -> list[list[str]]:
        seen: set[tuple[str, ...]] = set()
        paths: list[list[str]] = []
        for block in self.blocks:
            key = tuple(block.heading_path)
            if not key or key in seen:
                continue
            seen.add(key)
            paths.append(list(block.heading_path))
        return paths

    def compact_view_for_heading_paths(self, heading_paths: list[list[str]], *, max_lines: int = 500) -> str:
        wanted = {tuple(path) for path in heading_paths if path}
        lines = [
            block.compact_line()
            for block in self.blocks
            if tuple(block.heading_path) in wanted
        ][:max_lines]
        if self.truncated or len(lines) >= max_lines:
            lines.append("[TRUNCATED] visible heading chunk only; unread sections require manual review.")
        return "\n".join(lines)

    def summary(self) -> dict[str, Any]:
        protected_count = sum(1 for block in self.blocks if block.protected)
        return {
            "contract_id": DOCUMENT_EDIT_WORKING_COPY_CONTRACT_ID,
            "document_id": self.document_id,
            "block_count": len(self.blocks),
            "protected_block_count": protected_count,
            "patchable_block_count": len(self.blocks) - protected_count,
            "protected_table_count": len(self.protected_table_shapes),
            "truncated": self.truncated,
            "source_hash": self.source_hash,
            "revision_token": self.revision_token,
            "snapshot_path": self.snapshot_path,
        }

    def to_mapping(self) -> dict[str, Any]:
        return {
            **self.summary(),
            "url": self.url,
            "text": self.text,
            "snapshot_depth": self.snapshot_depth,
            "snapshot_max_blocks": self.snapshot_max_blocks,
            "blocks": [block.to_mapping() for block in self.blocks],
            "protected_table_shapes": list(self.protected_table_shapes),
        }


@dataclass(frozen=True)
class DocumentEditPatchOperation:
    op: str
    block: DocumentEditBlockRef
    expected_old_text: str
    new_text: str
    operation_id: str = ""
    parent_block_id: str = ""
    anchor_block_id: str = ""
    cell_block_id: str = ""
    table_block_id: str = ""
    row_index: int = -1
    cell_texts: list[str] = field(default_factory=list)
    minimum_rows: int = 0
    content_spec: str = ""
    product_facts_checked: list[str] = field(default_factory=list)
    source_evidence: list[str] = field(default_factory=list)

    @classmethod
    def from_mapping(
        cls,
        payload: Mapping[str, Any],
        *,
        block_refs: Mapping[str, DocumentEditBlockRef],
        executable_op_whitelist: Any,
    ) -> "DocumentEditPatchOperation":
        whitelist = _op_whitelist(executable_op_whitelist)
        _require(whitelist, "executable op whitelist is required")
        op = _text(payload.get("op") or payload.get("operation"))
        _require(op, "patch operation requires op")
        _require(op in whitelist, f"patch operation is not executable by whitelist: {op}")
        parent_block_id = _text(payload.get("parent_block_id"))
        anchor_block_id = _text(payload.get("anchor_block_id"))
        cell_block_id = _text(payload.get("cell_block_id"))
        table_block_id = _text(payload.get("table_block_id"))
        block_id = _text(payload.get("block_id") or payload.get("target_block_id") or table_block_id or anchor_block_id or cell_block_id)
        _require(block_id, "executable patch operation requires block_id")
        if op == "insert_text_after":
            _require(anchor_block_id, "insert_text_after requires anchor_block_id")
            _require(parent_block_id, "insert_text_after requires parent_block_id")
            _require("index" not in payload and "static_index" not in payload, "insert_text_after cannot use plan-time static index")
        if op == "delete_text_block":
            _require(parent_block_id, "delete_text_block requires parent_block_id")
        if op == "append_text_to_cell":
            _require(cell_block_id, "append_text_to_cell requires cell_block_id")
        row_index = -1
        cell_texts: list[str] = []
        minimum_rows = 0
        content_spec = _text(payload.get("content_spec"))
        if op == "insert_table_row":
            table_block_id = table_block_id or block_id
            _require(table_block_id, "insert_table_row requires table_block_id")
            _require(parent_block_id == "", "insert_table_row must not use parent_block_id")
            _require(anchor_block_id == "", "insert_table_row must not use anchor_block_id")
            _require(cell_block_id == "", "insert_table_row must not use cell_block_id")
            _require("index" not in payload and "static_index" not in payload, "insert_table_row cannot use plan-time static index")
            try:
                row_index = int(payload.get("row_index", -1))
            except (TypeError, ValueError):
                raise DocumentEditContractViolation("insert_table_row requires integer row_index") from None
            _require(row_index == -1, "insert_table_row currently supports only append row_index=-1")
            raw_cell_texts = payload.get("cell_texts") or payload.get("row_values") or payload.get("cells") or []
            _require(isinstance(raw_cell_texts, list), "insert_table_row requires cell_texts list")
            cell_texts = [str(item) for item in raw_cell_texts]
            _require(any(text.strip() for text in cell_texts), "insert_table_row requires at least one non-empty cell_text")
            try:
                minimum_rows = int(payload.get("minimum_rows") or 0)
            except (TypeError, ValueError):
                minimum_rows = 0
        block = block_refs.get(block_id)
        if block is None:
            block = DocumentEditBlockRef.from_mapping(
                {
                    "block_id": block_id,
                    "path": payload.get("path"),
                    "block_type": payload.get("block_type") or "text",
                    "text": payload.get("expected_old_text") or "",
                    "table_shape": payload.get("table_shape") or {},
                    "protected": payload.get("protected"),
                    "protection_reason": payload.get("protection_reason"),
                    "has_non_plain_text_elements": payload.get("has_non_plain_text_elements"),
                    "has_style_run_proof": payload.get("has_style_run_proof") or payload.get("style_run_proof"),
                    "text_elements": payload.get("text_elements") or payload.get("elements"),
                }
            )
        _require(block.path, "executable patch operation requires path")
        if block.has_non_plain_text_elements and not block.has_style_run_proof:
            raise DocumentEditContractViolation(
                "executable patch operation cannot target rich text block without style-run proof"
            )
        allowed_protected_table_insert = (
            op == "insert_table_row"
            and _text(block.block_type) in {"31", "table"}
            and bool(block.table_shape)
        )
        _require(not block.protected or allowed_protected_table_insert, "executable patch operation cannot target protected block")
        if op in {"replace_text", "delete_text_block"}:
            _require(_has_key(payload, "expected_old_text"), f"{op} requires expected_old_text")
        if op == "insert_table_row":
            if not _has_key(payload, "new_text"):
                payload = {**payload, "new_text": "\n".join(text for text in cell_texts if text.strip())}
        _require(_has_key(payload, "new_text"), "executable patch operation requires new_text")
        source_evidence = _text_list(payload.get("source_evidence"))
        if bool(payload.get("changes_product_facts")):
            _require(source_evidence, "product fact changes require source_evidence")
        return cls(
            op=op,
            block=block,
            expected_old_text=str(payload.get("expected_old_text") or ""),
            new_text=str(payload.get("new_text") or ""),
            operation_id=_text(payload.get("operation_id") or payload.get("id")),
            parent_block_id=parent_block_id,
            anchor_block_id=anchor_block_id,
            cell_block_id=cell_block_id,
            table_block_id=table_block_id,
            row_index=row_index,
            cell_texts=cell_texts,
            minimum_rows=minimum_rows,
            content_spec=content_spec,
            product_facts_checked=_text_list(payload.get("product_facts_checked")),
            source_evidence=source_evidence,
        )

    def to_mapping(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["block_id"] = self.block.block_id
        payload["path"] = list(self.block.path)
        payload["executable"] = True
        if self.parent_block_id:
            payload["parent_block_id"] = self.parent_block_id
        if self.anchor_block_id:
            payload["anchor_block_id"] = self.anchor_block_id
        if self.cell_block_id:
            payload["cell_block_id"] = self.cell_block_id
        if self.table_block_id:
            payload["table_block_id"] = self.table_block_id
            payload["row_index"] = self.row_index
            payload["cell_texts"] = list(self.cell_texts)
        if self.minimum_rows:
            payload["minimum_rows"] = self.minimum_rows
        if self.content_spec:
            payload["content_spec"] = self.content_spec
        if self.operation_id:
            payload["operation_id"] = self.operation_id
        return payload


@dataclass(frozen=True)
class DocumentEditManualAction:
    reason: str
    instructions: str
    requested_op: str = ""
    block_id: str = ""
    path: list[str] = field(default_factory=list)

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "DocumentEditManualAction":
        action = _text(payload.get("action"))
        reason = _text(payload.get("reason") or payload.get("manual_reason") or payload.get("protection_reason"))
        instructions = _text(payload.get("instructions") or payload.get("manual_action") or payload.get("description") or reason or action)
        reason = reason or instructions
        _require(reason, "manual action requires reason")
        _require(instructions, "manual action requires instructions")
        block_ids = _list(payload.get("block_ids"))
        return cls(
            reason=reason,
            instructions=instructions,
            requested_op=_text(payload.get("requested_op") or payload.get("op") or payload.get("operation") or action),
            block_id=_text(payload.get("block_id") or payload.get("target_block_id") or (block_ids[0] if block_ids else "")),
            path=_text_list(payload.get("path")),
        )

    @classmethod
    def from_blocked_operation(cls, payload: Mapping[str, Any], *, reason: str) -> "DocumentEditManualAction":
        return cls(
            reason=_text(reason) or "operation_not_executable",
            instructions=_text(payload.get("manual_action") or payload.get("instructions") or "Review and apply this edit manually."),
            requested_op=_text(payload.get("op") or payload.get("operation")),
            block_id=_text(payload.get("block_id") or payload.get("target_block_id")),
            path=_text_list(payload.get("path")),
        )

    def to_mapping(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["executable"] = False
        return payload


@dataclass(frozen=True)
class DocumentEditPatchPlan:
    source: DocumentEditPatchSource
    operations: list[DocumentEditPatchOperation]
    manual_actions: list[DocumentEditManualAction]
    block_refs: list[DocumentEditBlockRef] = field(default_factory=list)
    product_facts_checked: list[str] = field(default_factory=list)
    intent_operations: list[DocumentEditIntentOperation] = field(default_factory=list)

    contract: ClassVar[DocumentEditContractMetadata] = DocumentEditContractMetadata(
        protected_invariant=(
            "document_edit patch plans may contain only whitelisted executable block "
            "operations plus manual actions; full-document Markdown is not a patch plan."
        )
    )

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any], *, executable_op_whitelist: Any) -> "DocumentEditPatchPlan":
        _require(not _text(payload.get("content") or payload.get("markdown") or payload.get("full_markdown")), "patch plan cannot contain full-document Markdown output")
        _require(
            not _list(payload.get("intent_operations") or payload.get("intent_ops")),
            "replace_terms intent operations require WorkingCopy fanout before patch plan validation",
        )
        source_payload = payload.get("source")
        _require(isinstance(source_payload, Mapping), "patch plan requires source")
        source = DocumentEditPatchSource.from_mapping(source_payload)
        block_refs = [
            DocumentEditBlockRef.from_mapping(item)
            for item in _list(payload.get("block_refs") or payload.get("blocks") or payload.get("document_map"))
            if isinstance(item, Mapping)
        ]
        block_ref_by_id = {block.block_id: block for block in block_refs}
        operations: list[DocumentEditPatchOperation] = []
        manual_actions: list[DocumentEditManualAction] = []
        for item in _list(payload.get("operations")):
            _require(isinstance(item, Mapping), "patch operation must be an object")
            if item.get("executable") is False or _text(item.get("status")) in {"manual", "blocked"}:
                manual_actions.append(DocumentEditManualAction.from_blocked_operation(item, reason=_text(item.get("reason") or "operation_marked_manual")))
                continue
            operations.append(
                DocumentEditPatchOperation.from_mapping(
                    item,
                    block_refs=block_ref_by_id,
                    executable_op_whitelist=executable_op_whitelist,
                )
            )
        for item in _list(payload.get("manual_actions")):
            _require(isinstance(item, Mapping), "manual action must be an object")
            manual_actions.append(DocumentEditManualAction.from_mapping(item))
        _require(operations or manual_actions, "patch plan requires executable operations or manual actions")
        return cls(
            source=source,
            operations=operations,
            manual_actions=manual_actions,
            block_refs=block_refs,
            product_facts_checked=_text_list(payload.get("product_facts_checked") or source.product_facts_checked),
        )

    @classmethod
    def from_intent_mapping(
        cls,
        payload: Mapping[str, Any],
        *,
        working_copy: DocumentEditWorkingCopy,
        executable_op_whitelist: Any,
    ) -> "DocumentEditPatchPlan":
        _require(not _list(payload.get("operations")), "intent patch plan cannot mix LLM operations with intent_operations")
        intent_payloads = _list(payload.get("intent_operations") or payload.get("intent_ops"))
        _require(intent_payloads, "intent patch plan requires intent_operations")
        intent_operations = [
            DocumentEditIntentOperation.from_mapping(item)
            for item in intent_payloads
            if isinstance(item, Mapping)
        ]
        _require(len(intent_operations) == len(intent_payloads), "intent operation must be an object")
        fanout = working_copy.fanout_intent_operations(intent_operations)
        expanded_payload = {
            "source": working_copy.patch_source(),
            "block_refs": working_copy.block_map(),
            "operations": fanout["operations"],
            "manual_actions": [
                *fanout["manual_actions"],
                *[
                    item
                    for item in _list(payload.get("manual_actions"))
                    if isinstance(item, Mapping)
                ],
            ],
            "product_facts_checked": _text_list(payload.get("product_facts_checked")),
        }
        plan = cls.from_mapping(expanded_payload, executable_op_whitelist=executable_op_whitelist)
        return cls(
            source=plan.source,
            operations=plan.operations,
            manual_actions=plan.manual_actions,
            block_refs=plan.block_refs,
            product_facts_checked=plan.product_facts_checked,
            intent_operations=intent_operations,
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "ok": True,
            "contract_id": DOCUMENT_EDIT_PATCH_CONTRACT_ID,
            "concurrency_semantics": DOCUMENT_EDIT_PATCH_CONCURRENCY_SEMANTICS,
            "source": self.source.to_mapping(),
            "operations": [operation.to_mapping() for operation in self.operations],
            "manual_actions": [action.to_mapping() for action in self.manual_actions],
            "block_refs": [block.to_mapping() for block in self.block_refs],
            "product_facts_checked": list(self.product_facts_checked),
            "intent_trace": [operation.to_mapping() for operation in self.intent_operations],
        }


@dataclass(frozen=True)
class DocumentEditPatchApplyResult:
    document_id: str
    source_hash: str
    revision_token: str
    status: str
    applied_operations: list[Any] = field(default_factory=list)
    manual_actions: list[Any] = field(default_factory=list)
    errors: list[Any] = field(default_factory=list)

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "DocumentEditPatchApplyResult":
        status = _text(payload.get("status"))
        _require(status in {"patch_apply_ok", "patch_apply_partial", "patch_apply_manual", "patch_apply_failed"}, "patch apply result has invalid status")
        _require(_text(payload.get("document_id")), "patch apply result requires document_id")
        _require(_text(payload.get("source_hash")), "patch apply result requires source_hash")
        _require(_text(payload.get("revision_token")), "patch apply result requires revision_token")
        if status == "patch_apply_ok":
            _require(_list(payload.get("applied_operations")), "patch_apply_ok requires applied_operations")
            _require(not _list(payload.get("errors")), "patch_apply_ok cannot include errors")
        return cls(
            document_id=_text(payload.get("document_id")),
            source_hash=_text(payload.get("source_hash")),
            revision_token=_text(payload.get("revision_token")),
            status=status,
            applied_operations=_list(payload.get("applied_operations")),
            manual_actions=_list(payload.get("manual_actions")),
            errors=_list(payload.get("errors")),
        )

    def to_mapping(self) -> dict[str, Any]:
        payload = asdict(self)
        payload.update({"ok": self.status in {"patch_apply_ok", "patch_apply_partial"}, "contract_id": DOCUMENT_EDIT_PATCH_CONTRACT_ID})
        return payload


@dataclass(frozen=True)
class DocumentEditPatchReadbackResult:
    document_id: str
    source_hash: str
    revision_token: str
    changed_since_read: bool
    applied_operation_ids: list[str] = field(default_factory=list)
    protected_block_ids_missing: list[str] = field(default_factory=list)
    protected_table_shape_changes: list[Any] = field(default_factory=list)
    manual_actions: list[Any] = field(default_factory=list)

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "DocumentEditPatchReadbackResult":
        _require(bool(payload.get("ok")), "patch readback must be ok")
        _require(_text(payload.get("document_id")), "patch readback requires document_id")
        _require(_text(payload.get("source_hash")), "patch readback requires source_hash")
        _require(_text(payload.get("revision_token")), "patch readback requires revision_token")
        _require(not _list(payload.get("protected_block_ids_missing")), "patch readback cannot lose protected blocks")
        _require(not _list(payload.get("protected_table_shape_changes")), "patch readback cannot change protected table shapes")
        return cls(
            document_id=_text(payload.get("document_id")),
            source_hash=_text(payload.get("source_hash")),
            revision_token=_text(payload.get("revision_token")),
            changed_since_read=bool(payload.get("changed_since_read") or payload.get("document_changed_since_read")),
            applied_operation_ids=_text_list(payload.get("applied_operation_ids")),
            protected_block_ids_missing=_text_list(payload.get("protected_block_ids_missing")),
            protected_table_shape_changes=_list(payload.get("protected_table_shape_changes")),
            manual_actions=_list(payload.get("manual_actions")),
        )

    def to_mapping(self) -> dict[str, Any]:
        payload = asdict(self)
        payload.update(
            {
                "ok": True,
                "contract_id": DOCUMENT_EDIT_PATCH_CONTRACT_ID,
                "concurrency_semantics": DOCUMENT_EDIT_PATCH_CONCURRENCY_SEMANTICS,
                "document_changed_since_read": self.changed_since_read,
            }
        )
        return payload


@dataclass(frozen=True)
class DocumentEditLlmOutput:
    content: str
    changed_sections: list[Any]
    preserved_constraints_checked: list[Any]
    family_requirements_checked: list[Any]
    table_sections: list[Any]
    commercial_delivery_record_fields: dict[str, Any] = field(default_factory=dict)

    contract: ClassVar[DocumentEditContractMetadata] = DocumentEditContractMetadata()

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any], *, document_family: str) -> "DocumentEditLlmOutput":
        _require(str(payload.get("status") or "") == "done", "LLM output status must be done")
        content = _text(payload.get("content") or payload.get("markdown"))
        _require(content, "LLM output content is required")
        changed = _list(payload.get("changed_sections"))
        preserved = _list(payload.get("preserved_constraints_checked"))
        family = _list(payload.get("family_requirements_checked"))
        table_sections = _list(payload.get("table_sections"))
        _require(any(_text(item) for item in changed), "LLM output changed_sections is required")
        _require(isinstance(payload.get("preserved_constraints_checked"), list), "LLM output preserved_constraints_checked must be a list")
        _require(any(_text(item) for item in family), "LLM output family_requirements_checked is required")
        _require(isinstance(payload.get("table_sections"), list), "LLM output table_sections must be a list")
        record_fields = payload.get("commercial_delivery_record_fields")
        if document_family == "commercial_delivery":
            _require(isinstance(record_fields, dict), "commercial_delivery LLM output requires commercial_delivery_record_fields")
        return cls(
            content=content,
            changed_sections=changed,
            preserved_constraints_checked=preserved,
            family_requirements_checked=family,
            table_sections=table_sections,
            commercial_delivery_record_fields=record_fields if isinstance(record_fields, dict) else {},
        )

    def to_schema_status(self) -> dict[str, Any]:
        return {
            "ok": True,
            "status": "document_edit_schema_ok",
            "contract_id": DOCUMENT_EDIT_CONTRACT_ID,
            "changed_sections": list(self.changed_sections),
            "family_requirements_checked": list(self.family_requirements_checked),
            "table_sections": list(self.table_sections),
        }


@dataclass(frozen=True)
class DocumentEditReplaceRequest:
    doc_url: str
    content: str
    source_hash: str
    snapshot_path: str
    document_family: str

    contract: ClassVar[DocumentEditContractMetadata] = DocumentEditContractMetadata()

    @classmethod
    def from_source(
        cls,
        *,
        doc_url: str,
        content: str,
        source: Mapping[str, Any],
    ) -> "DocumentEditReplaceRequest":
        source_hash = _text(source.get("source_hash") or source.get("source_block_hash"))
        snapshot_path = _text(source.get("snapshot_path"))
        _require(_text(doc_url), "replace request requires doc_url")
        _require(_text(content), "replace request requires full content")
        _require(source_hash, "replace request requires source_hash")
        _require(snapshot_path, "replace request requires snapshot_path")
        _require(_text(source.get("preflight_status") or "passed") == "passed", "replace request requires passed preflight")
        _require(not _list(source.get("unsupported_blocks") or source.get("unsupported_document_blocks")), "replace request cannot include unsupported blocks")
        return cls(
            doc_url=_text(doc_url),
            content=str(content),
            source_hash=source_hash,
            snapshot_path=snapshot_path,
            document_family=_text(source.get("document_family") or "generic_docx"),
        )

    def kwargs(self) -> dict[str, Any]:
        return {
            "source_hash": self.source_hash,
            "snapshot_path": self.snapshot_path,
            "document_family": self.document_family,
            "contract_id": DOCUMENT_EDIT_CONTRACT_ID,
        }


@dataclass(frozen=True)
class DocumentEditReadbackResult:
    document_id: str
    native_table_count: int
    markdown_table_residue_found: bool
    family_requirements_checked: list[Any]
    root_block_count: int = 0

    contract: ClassVar[DocumentEditContractMetadata] = DocumentEditContractMetadata()

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "DocumentEditReadbackResult":
        _require(bool(payload.get("ok")), "readback must be ok")
        _require(_text(payload.get("status")) == "document_edit_readback_ok", "readback status must be document_edit_readback_ok")
        _require(not bool(payload.get("markdown_table_residue_found")), "readback must not contain Markdown table residue")
        checks = _list(payload.get("family_requirements_checked"))
        _require(any(_text(item) for item in checks), "readback family_requirements_checked is required")
        return cls(
            document_id=_text(payload.get("document_id")),
            native_table_count=int(payload.get("native_table_count") or 0),
            markdown_table_residue_found=False,
            family_requirements_checked=checks,
            root_block_count=int(payload.get("root_block_count") or 0),
        )

    def to_mapping(self) -> dict[str, Any]:
        payload = asdict(self)
        payload.update({"ok": True, "status": "document_edit_readback_ok", "contract_id": DOCUMENT_EDIT_CONTRACT_ID})
        return payload
