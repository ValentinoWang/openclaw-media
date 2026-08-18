"""Fail-closed Lark document gateway for canonical media document revisions."""

from __future__ import annotations

import copy
import hashlib
import json
import re
import time
from collections.abc import Mapping as MappingABC
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol

import requests

from openclaw_app.services.media_business.documents import (
    DocumentConflict,
    DocumentUnavailable,
    LarkBlockSnapshot,
    LarkRevisionSnapshot,
    UnsupportedDocumentBlock,
)
from openclaw_app.services.media_business.foundation import (
    body_checksum,
    preserve_protected_blocks,
    validate_body,
)


class LarkDocumentClient(Protocol):
    """Transport boundary implemented by the production authenticated Lark client."""

    def current_version(self, document_id: str) -> str:
        ...

    def read_canonical_revision(
        self, document_id: str, remote_document_version: str
    ) -> Mapping[str, Any]:
        ...

    def write_canonical_revision(
        self,
        document_id: str,
        body: dict[str, Any],
        *,
        expected_remote_version: str,
        idempotency_key: str,
    ) -> Mapping[str, Any]:
        ...

    def get_write_receipt(
        self, document_id: str, idempotency_key: str
    ) -> Mapping[str, Any] | None:
        ...


DocumentResolver = Callable[[str, str], str]


@dataclass(frozen=True)
class LarkDocumentResource:
    """Controlled bytes and metadata resolved from one public resource identity."""

    content: bytes
    file_name: str
    content_type: str
    width: int | None = None
    height: int | None = None


class LarkDocumentResourceResolver(Protocol):
    """Resolve canonical public resource identities without exposing storage refs."""

    def resolve(self, public_resource_id: str) -> LarkDocumentResource:
        ...


LarkMediaUpload = Callable[[str, str, LarkDocumentResource, str], str]


class LarkWriteReceiptStore(Protocol):
    """Durable store for receipts used when a remote write outcome is unknown."""

    def get(self, document_id: str, idempotency_key: str) -> Mapping[str, Any] | None:
        ...

    def put(
        self, document_id: str, idempotency_key: str, receipt: Mapping[str, Any]
    ) -> None:
        ...


class InMemoryLarkWriteReceiptStore:
    """Test-only receipt store; production composition uses the SQL implementation."""

    def __init__(self) -> None:
        self._receipts: dict[tuple[str, str], dict[str, Any]] = {}

    def get(self, document_id: str, idempotency_key: str) -> Mapping[str, Any] | None:
        value = self._receipts.get((document_id, idempotency_key))
        return copy.deepcopy(value) if value is not None else None

    def put(
        self, document_id: str, idempotency_key: str, receipt: Mapping[str, Any]
    ) -> None:
        self._receipts[(document_id, idempotency_key)] = copy.deepcopy(dict(receipt))

    def find_by_version(
        self, document_id: str, version: str
    ) -> Mapping[str, Any] | None:
        for (stored_document, _), receipt in self._receipts.items():
            if (
                stored_document == document_id
                and receipt.get("remoteDocumentVersion") == version
            ):
                return copy.deepcopy(receipt)
        return None


class SqlLarkWriteReceiptStore:
    """Persist receipts in the existing sync batch's JSON error detail column."""

    def __init__(self, connection_factory: Callable[[], Any]) -> None:
        self._connection_factory = connection_factory

    def get(self, document_id: str, idempotency_key: str) -> Mapping[str, Any] | None:
        with self._connection_factory() as connection:
            cursor = connection.execute(
                """SELECT error_detail
                     FROM media_product.sync_batches
                    WHERE public_sync_id=%s AND operation='save'
                    ORDER BY tenant_id
                    LIMIT 2""",
                (idempotency_key,),
            )
            rows = self._fetch_at_most_two(cursor)
        if not rows:
            return None
        if len(rows) != 1:
            raise DocumentUnavailable("Lark sync identity is ambiguous across tenants")
        return self._receipt_from_error_detail(rows[0][0], document_id=document_id)

    def put(
        self, document_id: str, idempotency_key: str, receipt: Mapping[str, Any]
    ) -> None:
        stored = {**dict(receipt), "documentId": document_id}
        with self._connection_factory() as connection:
            cursor = connection.execute(
                """UPDATE media_product.sync_batches
                      SET error_detail=jsonb_set(
                            COALESCE(error_detail, '{}'::jsonb),
                            '{larkWriteReceipt}', %s::jsonb, true),
                          updated_at=now()
                    WHERE public_sync_id=%s AND operation='save' AND state='running'
                RETURNING tenant_id""",
                (json.dumps(stored, ensure_ascii=False), idempotency_key),
            )
            rows = self._fetch_at_most_two(cursor)
            if len(rows) != 1:
                raise DocumentUnavailable(
                    "Lark receipt requires exactly one running sync batch"
                )

    def find_by_version(
        self, document_id: str, version: str
    ) -> Mapping[str, Any] | None:
        with self._connection_factory() as connection:
            cursor = connection.execute(
                """SELECT error_detail
                     FROM media_product.sync_batches
                    WHERE error_detail->'larkWriteReceipt'->>'documentId'=%s
                      AND error_detail->'larkWriteReceipt'->>'remoteDocumentVersion'=%s
                      AND operation='save'
                    ORDER BY updated_at DESC
                    LIMIT 2""",
                (document_id, version),
            )
            rows = self._fetch_at_most_two(cursor)
        if not rows:
            return None
        if len(rows) != 1:
            raise DocumentUnavailable("Lark document version receipt is ambiguous")
        return self._receipt_from_error_detail(rows[0][0], document_id=document_id)

    @staticmethod
    def _fetch_at_most_two(cursor: Any) -> list[Any]:
        if not hasattr(cursor, "fetchmany"):
            raise DocumentUnavailable("Lark receipt query returned an invalid cursor")
        return list(cursor.fetchmany(2))

    @staticmethod
    def _receipt_from_error_detail(
        value: Any,
        *,
        document_id: str,
    ) -> Mapping[str, Any] | None:
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError as exc:
                raise DocumentUnavailable(
                    "stored Lark receipt JSON is invalid"
                ) from exc
        if not isinstance(value, MappingABC):
            raise DocumentUnavailable("stored Lark receipt JSON is invalid")
        receipt = value.get("larkWriteReceipt")
        if receipt is None:
            return None
        if not isinstance(receipt, MappingABC):
            raise DocumentUnavailable("stored Lark receipt JSON is invalid")
        if receipt.get("documentId") != document_id:
            raise DocumentConflict("stored Lark receipt belongs to another document")
        return {
            key: copy.deepcopy(child)
            for key, child in receipt.items()
            if key != "documentId"
        }


class AuthenticatedLarkDocumentClient:
    """Authenticated Docx transport backed by FeishuService's official request helper.

    The client deliberately exposes only canonical revision operations. Credentials
    remain inside FeishuService and are never copied into receipts or error values.
    """

    _NATIVE_TYPES = {
        "paragraph": (2, "text"),
        **{
            f"heading_{level}": (level + 2, f"heading{level}") for level in range(1, 10)
        },
        "bullet_list": (12, "bullet"),
        "ordered_list": (13, "ordered"),
        "todo_item": (17, "todo"),
        "quote": (15, "quote"),
        "code_block": (14, "code"),
        "callout": (19, "callout"),
        "divider": (22, "divider"),
    }
    _PROTECTED_TYPES = {
        18,
        21,
        26,
        28,
        29,
        30,
        35,
        36,
        37,
        38,
        39,
        40,
        43,
        44,
        45,
        46,
        47,
        49,
        50,
    }
    _PROTECTED_KEYS = {
        "agenda",
        "bitable",
        "diagram",
        "embed",
        "flowchart",
        "iframe",
        "isv",
        "lark_task",
        "mind_note",
        "mindnote",
        "okr",
        "sheet",
        "synced_block",
        "synced_source",
        "task",
        "third_party_widget",
        "whiteboard",
    }
    _COMPLEX_NATIVE_TYPES = {12, 13, 23, 27, 31, 32}
    _FIXED_READ_RETRY_ATTEMPTS = 3
    _FIXED_READ_RETRY_BASE_DELAY = 0.2
    _CODE_LANGUAGES = {
        "plaintext": 1,
        "bash": 7,
        "csharp": 8,
        "cpp": 9,
        "c": 10,
        "css": 12,
        "dart": 15,
        "dockerfile": 18,
        "go": 22,
        "html": 24,
        "json": 28,
        "java": 29,
        "javascript": 30,
        "kotlin": 32,
        "latex": 33,
        "lua": 36,
        "markdown": 39,
        "php": 43,
        "powershell": 46,
        "python": 49,
        "ruby": 52,
        "rust": 53,
        "sql": 56,
        "shell": 60,
        "swift": 61,
        "typescript": 63,
        "xml": 66,
        "yaml": 67,
        "toml": 75,
    }

    def __init__(
        self,
        feishu_service: Any,
        *,
        receipt_store: LarkWriteReceiptStore | None = None,
        resource_resolver: LarkDocumentResourceResolver | None = None,
        media_upload: LarkMediaUpload | None = None,
    ) -> None:
        request = getattr(feishu_service, "_request", None)
        if not callable(request):
            raise ValueError(
                "an authenticated FeishuService request helper is required"
            )
        self._feishu = feishu_service
        self._request = request
        self._receipts = receipt_store or InMemoryLarkWriteReceiptStore()
        self._resource_resolver = resource_resolver
        self._media_upload = media_upload or self._upload_media

    def current_version(self, document_id: str) -> str:
        payload = self._request("GET", f"/docx/v1/documents/{document_id}")
        version = self._value(
            payload, "revision_id", "document_revision_id", "revisionId", "version"
        )
        if version is None:
            document = self._value(payload, "document")
            if isinstance(document, MappingABC):
                version = self._value(
                    document,
                    "revision_id",
                    "document_revision_id",
                    "revisionId",
                    "version",
                )
        if not isinstance(version, (str, int)) or not str(version).strip():
            raise DocumentUnavailable("Lark document version is missing")
        return str(version).strip()

    def read_canonical_revision(
        self, document_id: str, remote_document_version: str
    ) -> Mapping[str, Any]:
        version = self._required_version(remote_document_version)
        items = self._list_blocks(document_id, version)
        receipt = self._find_receipt_for_version(document_id, version)
        body, mappings = self._decode_blocks(items, receipt)
        checksum = body_checksum(body)
        expected_checksum = (
            receipt.get("bodyChecksum") if isinstance(receipt, MappingABC) else None
        )
        if expected_checksum is not None and checksum != expected_checksum:
            raise DocumentConflict("Lark canonical body checksum differs from receipt")
        protected = sum(1 for item in mappings if item["isProtected"])
        return {
            "remoteDocumentVersion": version,
            "complete": True,
            "body": body,
            "bodyChecksum": checksum,
            "blockCount": len(mappings),
            "protectedBlockCount": protected,
            "blocks": mappings,
        }

    def write_canonical_revision(
        self,
        document_id: str,
        body: dict[str, Any],
        *,
        expected_remote_version: str,
        idempotency_key: str,
    ) -> Mapping[str, Any]:
        desired = validate_body(body)
        expected = self._required_version(expected_remote_version)
        key = self._required_value(idempotency_key, "Lark idempotency key is required")
        prior = self._receipts.get(document_id, key)
        if prior is not None:
            if prior.get("bodyChecksum") != body_checksum(desired):
                raise DocumentConflict(
                    "Lark idempotency key is already bound to another body"
                )
            return copy.deepcopy(dict(prior))
        if self.current_version(document_id) != expected:
            raise DocumentConflict("Lark document version is stale")
        existing = self._list_blocks(document_id, expected)
        protected = [
            item for item in self._walk_native(existing) if self._is_protected(item)
        ]
        if protected:
            ids = [self._block_id(item) for item in protected if self._block_id(item)]
            raise UnsupportedDocumentBlock(set(ids))
        resources = self._resolve_resources(desired["blocks"])
        self._validate_native_shapes(desired["blocks"])
        self._delete_children(document_id, len(existing), expected)
        block_map: list[dict[str, Any]] = []
        for block in desired["blocks"]:
            remote_ids = self._write_block(
                document_id,
                document_id,
                block,
                resources,
            )
            if not remote_ids:
                raise DocumentUnavailable(
                    "Lark write returned no remote block identity"
                )
            block_map.append(
                {
                    "publicBlockId": block["id"],
                    "remoteBlockId": remote_ids[0],
                    "remoteBlockIds": remote_ids,
                    "blockChecksum": body_checksum(block),
                    "isProtected": False,
                    "protectionReason": None,
                }
            )
        remote = self.current_version(document_id)
        if remote == expected:
            raise DocumentConflict("Lark write did not advance the document version")
        written = self._list_blocks(document_id, remote)
        written_ids = {
            self._block_id(item)
            for item in self._walk_native(written)
            if self._block_id(item)
        }
        for mapping in block_map:
            if not set(mapping["remoteBlockIds"]).issubset(written_ids):
                raise DocumentConflict("Lark block mapping readback is incomplete")
        receipt = {
            "idempotencyKey": key,
            "baseRemoteDocumentVersion": expected,
            "remoteDocumentVersion": remote,
            "bodyChecksum": body_checksum(desired),
            "body": desired,
            "blockMap": block_map,
            "nativeBlockChecksums": [self._native_checksum(item) for item in written],
        }
        self._receipts.put(document_id, key, receipt)
        return receipt

    def get_write_receipt(
        self, document_id: str, idempotency_key: str
    ) -> Mapping[str, Any] | None:
        return self._receipts.get(
            document_id,
            self._required_value(idempotency_key, "Lark idempotency key is required"),
        )

    def _find_receipt_for_version(
        self, document_id: str, version: str
    ) -> Mapping[str, Any] | None:
        finder = getattr(self._receipts, "find_by_version", None)
        return finder(document_id, version) if callable(finder) else None

    def _list_blocks(self, document_id: str, version: str) -> list[dict[str, Any]]:
        return self._list_children(document_id, document_id, version)

    def _list_children(
        self, document_id: str, parent_id: str, version: str
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        page_token = ""
        while True:
            params: dict[str, Any] = {"document_revision_id": version, "page_size": 500}
            if page_token:
                params["page_token"] = page_token
            attempts = 0
            while True:
                try:
                    payload = self._request(
                        "GET",
                        f"/docx/v1/documents/{document_id}/blocks/{parent_id}/children",
                        params=params,
                    )
                    break
                except RuntimeError as exc:
                    attempts += 1
                    retryable = (
                        re.search(r"(?<!\d)99991400(?!\d)", str(exc)) is not None
                    )
                    if not retryable or attempts >= self._FIXED_READ_RETRY_ATTEMPTS:
                        raise
                    time.sleep(
                        self._FIXED_READ_RETRY_BASE_DELAY * (2 ** (attempts - 1))
                    )
            data = payload.get("data", {}) if isinstance(payload, MappingABC) else {}
            actual = self._value(
                payload, "document_revision_id", "revision_id", "revisionId"
            )
            if actual is not None and str(actual) != version:
                raise DocumentConflict(
                    "Lark returned a different fixed document revision"
                )
            batch = (
                data.get("items") or data.get("children") or []
                if isinstance(data, MappingABC)
                else []
            )
            if not isinstance(batch, list):
                raise DocumentUnavailable("Lark block inventory is invalid")
            for raw_item in batch:
                if not isinstance(raw_item, dict):
                    continue
                item = copy.deepcopy(raw_item)
                child_ids = self._declared_child_ids(item)
                if child_ids:
                    child_id = self._block_id(item)
                    if not child_id:
                        raise DocumentUnavailable(
                            "Lark child-bearing block identity is missing"
                        )
                    item["_hydrated_children"] = self._list_children(
                        document_id, child_id, version
                    )
                items.append(item)
            if not data.get("has_more"):
                return items
            next_token = str(data.get("page_token") or "").strip()
            if not next_token or next_token == page_token:
                raise DocumentUnavailable("Lark block pagination did not advance")
            page_token = next_token

    @staticmethod
    def _declared_child_ids(item: Mapping[str, Any]) -> list[str]:
        candidates: list[Any] = []
        children = item.get("children")
        if isinstance(children, list):
            candidates.extend(children)
        table = item.get("table")
        if isinstance(table, MappingABC) and isinstance(table.get("cells"), list):
            candidates.extend(table["cells"])
        result: list[str] = []
        for value in candidates:
            if isinstance(value, MappingABC):
                value = value.get("block_id") or value.get("id")
            child_id = str(value).strip() if value is not None else ""
            if child_id and child_id not in result:
                result.append(child_id)
        return result

    def _delete_children(self, document_id: str, count: int, version: str) -> None:
        if count <= 0:
            return
        self._request(
            "DELETE",
            f"/docx/v1/documents/{document_id}/blocks/{document_id}/children/batch_delete",
            json_body={"start_index": 0, "end_index": count},
            params={"document_revision_id": version},
        )

    def _create_children(
        self,
        document_id: str,
        parent_id: str,
        children: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        created: list[dict[str, Any]] = []
        for start in range(0, len(children), 20):
            version = self.current_version(document_id)
            payload = self._request(
                "POST",
                f"/docx/v1/documents/{document_id}/blocks/{parent_id}/children",
                json_body={"children": children[start : start + 20], "index": -1},
                params={"document_revision_id": version},
            )
            batch = self._value(payload, "children", "items")
            if not isinstance(batch, list) or len(batch) != len(
                children[start : start + 20]
            ):
                raise DocumentUnavailable("Lark child creation readback is incomplete")
            created.extend(item for item in batch if isinstance(item, dict))
        if len(created) != len(children):
            raise DocumentUnavailable("Lark child creation readback is incomplete")
        return created

    def _resolve_resources(
        self, blocks: list[dict[str, Any]]
    ) -> dict[str, LarkDocumentResource]:
        resolved: dict[str, LarkDocumentResource] = {}
        resource_blocks = [
            block
            for block in self._walk_canonical(blocks)
            if block.get("type") in {"image", "attachment"}
        ]
        if resource_blocks and self._resource_resolver is None:
            raise DocumentUnavailable("Lark document resource resolver is unavailable")
        for block in resource_blocks:
            attrs = block.get("attrs")
            public_id = (
                attrs.get("publicResourceId") if isinstance(attrs, MappingABC) else None
            )
            if not isinstance(public_id, str) or not public_id.strip():
                raise DocumentUnavailable("Lark public resource identity is missing")
            try:
                resource = self._resource_resolver.resolve(public_id.strip())
            except (DocumentConflict, DocumentUnavailable):
                raise
            except Exception as exc:
                raise DocumentUnavailable(
                    "Lark document resource resolution failed"
                ) from exc
            if not isinstance(resource, LarkDocumentResource):
                raise DocumentUnavailable("Lark document resource is invalid")
            self._validate_resource(block, resource)
            resolved[str(block["id"])] = resource
        return resolved

    @staticmethod
    def _validate_resource(
        block: Mapping[str, Any], resource: LarkDocumentResource
    ) -> None:
        attrs = block.get("attrs")
        if not isinstance(attrs, MappingABC):
            raise DocumentUnavailable("Lark document resource metadata is invalid")
        if not isinstance(resource.content, bytes) or not resource.content:
            raise DocumentUnavailable("Lark document resource content is invalid")
        actual_checksum = hashlib.sha256(resource.content).hexdigest()
        if actual_checksum != attrs.get("contentChecksum"):
            raise DocumentConflict("Lark resource checksum does not match")
        if (
            not isinstance(resource.file_name, str)
            or not resource.file_name.strip()
            or resource.file_name != resource.file_name.rsplit("/", 1)[-1]
            or "\\" in resource.file_name
        ):
            raise DocumentUnavailable("Lark document resource filename is invalid")
        if not isinstance(resource.content_type, str) or not resource.content_type:
            raise DocumentUnavailable("Lark document resource content type is invalid")
        if block.get("type") == "image":
            if not resource.content_type.lower().startswith("image/"):
                raise DocumentConflict("Lark image resource content type differs")
            if resource.width != attrs.get("width") or resource.height != attrs.get(
                "height"
            ):
                raise DocumentConflict("Lark image resource dimensions differ")
        else:
            if resource.file_name != attrs.get("fileName"):
                raise DocumentConflict("Lark attachment filename differs")
            if resource.content_type != attrs.get("contentType"):
                raise DocumentConflict("Lark attachment content type differs")

    @classmethod
    def _validate_native_shapes(cls, blocks: list[dict[str, Any]]) -> None:
        for block in cls._walk_canonical(blocks):
            if block.get("type") != "table":
                continue
            rows = block.get("rows") or []
            widths = {
                len(row.get("cells") or [])
                for row in rows
                if isinstance(row, MappingABC)
            }
            if len(widths) != 1:
                raise UnsupportedDocumentBlock({str(block.get("id") or "table")})

    def _write_block(
        self,
        document_id: str,
        parent_id: str,
        block: dict[str, Any],
        resources: Mapping[str, LarkDocumentResource],
    ) -> list[str]:
        block_type = block["type"]
        if block_type in {"bullet_list", "ordered_list"}:
            return self._write_list(document_id, parent_id, block, resources)
        if block_type == "table":
            return self._write_table(document_id, parent_id, block["rows"])
        if block_type == "data_snapshot":
            remote_ids: list[str] = []
            for rows in self._snapshot_tables(block):
                remote_ids.extend(self._write_table(document_id, parent_id, rows))
            return remote_ids
        if block_type == "callout":
            callout = self._create_children(
                document_id,
                parent_id,
                [{"block_type": 19, "callout": {}}],
            )[0]
            callout_id = self._required_value(
                self._block_id(callout), "Lark callout identity is missing"
            )
            child_ids = self._declared_child_ids(callout)
            if len(child_ids) != 1:
                raise DocumentUnavailable(
                    "Lark callout did not return exactly one text block"
                )
            text_id = child_ids[0]
            version = self.current_version(document_id)
            self._request(
                "PATCH",
                f"/docx/v1/documents/{document_id}/blocks/{text_id}",
                json_body={
                    "update_text_elements": {
                        "elements": self._encode_inline(block.get("content") or [])
                    }
                },
                params={"document_revision_id": version},
            )
            return [callout_id, text_id]
        if block_type in {"image", "attachment"}:
            kind = block_type
            key = "image" if kind == "image" else "file"
            native_type = 27 if kind == "image" else 23
            empty_media = {} if kind == "image" else {"token": ""}
            created = self._create_children(
                document_id,
                parent_id,
                [{"block_type": native_type, key: empty_media}],
            )[0]
            created_id = self._required_value(
                self._block_id(created), "Lark media block identity is missing"
            )
            remote_ids = [created_id]
            block_id = created_id
            if kind == "attachment":
                file_ids = self._declared_child_ids(created)
                if len(file_ids) != 1:
                    raise DocumentUnavailable(
                        "Lark file view did not return exactly one file block"
                    )
                block_id = file_ids[0]
                remote_ids.append(block_id)
            resource = resources.get(str(block["id"]))
            if resource is None:
                raise DocumentUnavailable("Lark document resource was not preflighted")
            token = self._media_upload(document_id, block_id, resource, kind)
            token = self._required_value(token, "Lark media upload token is missing")
            version = self.current_version(document_id)
            self._request(
                "PATCH",
                f"/docx/v1/documents/{document_id}/blocks/{block_id}",
                json_body={f"replace_{key}": {"token": token}},
                params={"document_revision_id": version},
            )
            return remote_ids
        payload = self._encode_block(block)
        created = self._create_children(document_id, parent_id, [payload])[0]
        block_id = self._block_id(created)
        if not block_id:
            raise DocumentUnavailable("Lark created block identity is missing")
        return [block_id]

    def _write_list(
        self,
        document_id: str,
        parent_id: str,
        block: Mapping[str, Any],
        resources: Mapping[str, LarkDocumentResource],
    ) -> list[str]:
        native_type, key = self._NATIVE_TYPES[str(block["type"])]
        remote_ids: list[str] = []
        for item in block["items"]:
            created = self._create_children(
                document_id,
                parent_id,
                [
                    {
                        "block_type": native_type,
                        key: {"elements": self._encode_inline(item["content"])},
                    }
                ],
            )[0]
            item_id = self._block_id(created)
            if not item_id:
                raise DocumentUnavailable("Lark list item identity is missing")
            remote_ids.append(item_id)
            for child in item["children"]:
                remote_ids.extend(
                    self._write_block(document_id, item_id, child, resources)
                )
        return remote_ids

    def _write_table(
        self,
        document_id: str,
        parent_id: str,
        rows: list[dict[str, Any]],
    ) -> list[str]:
        column_count = len(rows[0]["cells"])
        created = self._create_children(
            document_id,
            parent_id,
            [
                {
                    "block_type": 31,
                    "table": {
                        "property": {
                            "row_size": len(rows),
                            "column_size": column_count,
                        }
                    },
                }
            ],
        )[0]
        table_id = self._block_id(created)
        expected_cells = len(rows) * column_count
        cell_ids = self._table_cell_ids(created, expected_cells)
        if table_id and len(cell_ids) != expected_cells:
            version = self.current_version(document_id)
            payload = self._request(
                "GET",
                f"/docx/v1/documents/{document_id}/blocks/{table_id}",
                params={"document_revision_id": version},
            )
            actual = self._value(
                payload, "document_revision_id", "revision_id", "revisionId"
            )
            if actual is not None and str(actual) != version:
                raise DocumentConflict(
                    "Lark returned a different fixed document revision"
                )
            hydrated = self._value(payload, "block")
            if not isinstance(hydrated, MappingABC):
                data = payload.get("data") if isinstance(payload, MappingABC) else None
                hydrated = data if isinstance(data, MappingABC) else payload
            cell_ids = self._table_cell_ids(hydrated, expected_cells)
        if table_id and len(cell_ids) != expected_cells:
            version = self.current_version(document_id)
            cell_ids = [
                self._block_id(item)
                for item in self._list_children(document_id, table_id, version)
            ][:expected_cells]
        if (
            not table_id
            or len(cell_ids) != expected_cells
            or any(not cell_id for cell_id in cell_ids)
        ):
            raise DocumentUnavailable("Lark table cell readback is incomplete")
        remote_ids = [table_id, *cell_ids]
        for cell_id, cell in zip(
            cell_ids,
            [cell for row in rows for cell in row["cells"]],
        ):
            version = self.current_version(document_id)
            text_blocks = self._list_children(document_id, cell_id, version)
            if len(text_blocks) != 1 or self._native_type(text_blocks[0]) != 2:
                raise DocumentUnavailable(
                    "Lark table cell did not return exactly one text block"
                )
            text_id = self._required_value(
                self._block_id(text_blocks[0]),
                "Lark table text block identity is missing",
            )
            self._request(
                "PATCH",
                f"/docx/v1/documents/{document_id}/blocks/{text_id}",
                json_body={
                    "update_text_elements": {
                        "elements": self._encode_inline(cell["content"])
                    }
                },
                params={"document_revision_id": version},
            )
            remote_ids.append(text_id)
        return remote_ids

    @classmethod
    def _table_cell_ids(cls, value: Any, expected: int) -> list[str]:
        if not isinstance(value, MappingABC):
            return []
        candidates = cls._declared_child_ids(value)
        return candidates[:expected] if len(candidates) >= expected else candidates

    @classmethod
    def _snapshot_tables(cls, block: Mapping[str, Any]) -> list[list[dict[str, Any]]]:
        attrs = block.get("attrs")
        if not isinstance(attrs, MappingABC):
            raise DocumentUnavailable("Lark data snapshot metadata is invalid")
        pairs: list[tuple[str, Any]] = [
            (name, attrs.get(name))
            for name in (
                "semanticPurpose",
                "publicObjectId",
                "sourceRevision",
                "capturedAt",
            )
        ]
        display = attrs.get("displayFields")
        if not isinstance(display, MappingABC):
            raise DocumentUnavailable("Lark data snapshot fields are invalid")
        pairs.extend(
            (f"displayFields.{name}", display[name]) for name in sorted(display)
        )
        result: list[list[dict[str, Any]]] = []
        for offset in range(0, len(pairs), 8):
            rows = [cls._projection_row("Field", "Value")]
            rows.extend(
                cls._projection_row(name, cls._snapshot_value(value))
                for name, value in pairs[offset : offset + 8]
            )
            result.append(rows)
        return result

    @staticmethod
    def _projection_row(name: str, value: str) -> dict[str, Any]:
        def cell(text: str) -> dict[str, Any]:
            return {
                "content": [{"type": "text", "text": text, "marks": []}],
            }

        return {"cells": [cell(name), cell(value)]}

    @staticmethod
    def _snapshot_value(value: Any) -> str:
        if isinstance(value, str):
            return value
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )

    def _upload_media(
        self,
        document_id: str,
        block_id: str,
        resource: LarkDocumentResource,
        kind: str,
    ) -> str:
        token_getter = getattr(self._feishu, "_get_tenant_access_token", None)
        api_base = str(getattr(self._feishu, "api_base_url", "") or "").rstrip("/")
        if not callable(token_getter) or not api_base:
            raise DocumentUnavailable("authenticated Lark media upload is unavailable")
        try:
            access_token = token_getter()
        except Exception as exc:
            raise DocumentUnavailable("Lark media authentication failed") from exc
        if not isinstance(access_token, str) or not access_token:
            raise DocumentUnavailable("Lark media authentication failed")
        parent_type = "docx_image" if kind == "image" else "docx_file"
        for attempt in range(3):
            try:
                response = requests.post(
                    f"{api_base}/drive/v1/medias/upload_all",
                    headers={"Authorization": f"Bearer {access_token}"},
                    data={
                        "file_name": resource.file_name,
                        "parent_type": parent_type,
                        "parent_node": block_id or document_id,
                        "size": str(len(resource.content)),
                        "mime_type": resource.content_type,
                    },
                    files={
                        "file": (
                            resource.file_name,
                            resource.content,
                            resource.content_type,
                        )
                    },
                    timeout=60,
                )
            except requests.RequestException as exc:
                if attempt < 2:
                    time.sleep(0.5 * (attempt + 1))
                    continue
                raise DocumentUnavailable("Lark media upload failed") from exc
            if response.status_code in {429, 500, 502, 503, 504} and attempt < 2:
                time.sleep(0.5 * (attempt + 1))
                continue
            try:
                payload = response.json()
            except ValueError as exc:
                raise DocumentUnavailable(
                    "Lark media upload returned invalid JSON"
                ) from exc
            file_token = self._value(payload, "file_token")
            if (
                response.status_code >= 400
                or payload.get("code") not in {None, 0}
                or not isinstance(file_token, str)
                or not file_token.strip()
            ):
                raise DocumentUnavailable("Lark media upload failed")
            return file_token.strip()
        raise DocumentUnavailable("Lark media upload failed")

    @classmethod
    def _decode_blocks(
        cls, items: list[dict[str, Any]], receipt: Mapping[str, Any] | None
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        stored_body = receipt.get("body") if isinstance(receipt, MappingABC) else None
        stored_map = (
            receipt.get("blockMap") if isinstance(receipt, MappingABC) else None
        )
        if isinstance(stored_body, MappingABC) and isinstance(stored_map, list):
            body = validate_body(dict(stored_body))
            expected_native = receipt.get("nativeBlockChecksums")
            if not isinstance(expected_native, list) or expected_native != [
                cls._native_checksum(item) for item in items
            ]:
                raise DocumentConflict(
                    "Lark fixed-revision native block readback differs from receipt"
                )
            remote_ids = {
                cls._block_id(item)
                for item in cls._walk_native(items)
                if cls._block_id(item)
            }
            mappings: list[dict[str, Any]] = []
            by_public = {
                str(item.get("publicBlockId")): item
                for item in stored_map
                if isinstance(item, MappingABC)
                and isinstance(item.get("publicBlockId"), str)
            }
            if len(by_public) != len(body["blocks"]):
                raise DocumentConflict("Lark block mapping readback is incomplete")
            for block in body["blocks"]:
                mapped = by_public.get(str(block["id"]))
                if not isinstance(mapped, MappingABC):
                    raise DocumentConflict("Lark block mapping readback is incomplete")
                raw_remote_id = mapped.get("remoteBlockId")
                remote_id = (
                    str(raw_remote_id).strip() if raw_remote_id is not None else ""
                )
                grouped = mapped.get("remoteBlockIds", [remote_id])
                if (
                    not remote_id
                    or not isinstance(grouped, list)
                    or not grouped
                    or any(not isinstance(value, str) or not value for value in grouped)
                    or remote_id not in grouped
                    or not set(grouped).issubset(remote_ids)
                ):
                    raise DocumentConflict("Lark block mapping readback is incomplete")
                mappings.append(
                    {
                        "publicBlockId": block["id"],
                        "remoteBlockId": remote_id,
                        "blockChecksum": mapped["blockChecksum"],
                        "isProtected": bool(mapped["isProtected"]),
                        "protectionReason": mapped.get("protectionReason"),
                    }
                )
            return body, mappings
        blocks: list[dict[str, Any]] = []
        mappings = []
        for index, item in enumerate(items):
            if cls._native_type(item) in cls._COMPLEX_NATIVE_TYPES:
                raise UnsupportedDocumentBlock(
                    {cls._block_id(item) or f"remote_{index}"}
                )
            block = cls._decode_native(item, index)
            blocks.append(block)
            mappings.append(
                {
                    "publicBlockId": block["id"],
                    "remoteBlockId": cls._block_id(item) or block["id"],
                    "blockChecksum": body_checksum(block),
                    "isProtected": cls._is_protected(item),
                    "protectionReason": cls._protection_reason(item),
                }
            )
        body = validate_body(
            {"schemaVersion": "media.document.body.v1", "blocks": blocks}
        )
        return body, mappings

    @classmethod
    def _decode_native(cls, item: Mapping[str, Any], index: int) -> dict[str, Any]:
        block_type = cls._native_type(item)
        block_id = cls._block_id(item) or f"remote_{index}"
        if block_type in cls._PROTECTED_TYPES or cls._is_protected(item):
            raise UnsupportedDocumentBlock({block_id})
        if block_type == 31:
            raise UnsupportedDocumentBlock({block_id})
        type_name = next(
            (
                name
                for name, (native, _) in cls._NATIVE_TYPES.items()
                if native == block_type
            ),
            None,
        )
        if type_name is None:
            raise DocumentUnavailable(f"unsupported Lark block type {block_type}")
        key = cls._NATIVE_TYPES[type_name][1]
        container = item.get(key) if isinstance(item.get(key), MappingABC) else {}
        elements = (
            container.get("elements") if isinstance(container, MappingABC) else []
        )
        content = cls._decode_inline(elements)
        if type_name == "callout" and not content:
            for child in item.get("_hydrated_children") or []:
                if not isinstance(child, MappingABC) or cls._native_type(child) != 2:
                    continue
                text = child.get("text")
                if isinstance(text, MappingABC):
                    content.extend(cls._decode_inline(text.get("elements")))
        attrs: dict[str, Any] = {}
        if type_name == "todo_item":
            style = container.get("style") if isinstance(container, MappingABC) else None
            attrs["checked"] = bool(
                style.get("done") if isinstance(style, MappingABC) else False
            )
        if type_name == "code_block":
            style = container.get("style") if isinstance(container, MappingABC) else None
            language_code = style.get("language") if isinstance(style, MappingABC) else None
            attrs["language"] = next(
                (
                    name
                    for name, code in cls._CODE_LANGUAGES.items()
                    if code == language_code
                ),
                "plaintext",
            )
            return {
                "id": block_id,
                "type": type_name,
                "attrs": attrs,
                "text": "".join(run["text"] for run in content),
            }
        if type_name == "divider":
            return {"id": block_id, "type": type_name, "attrs": attrs}
        return {
            "id": block_id,
            "type": type_name,
            "attrs": attrs,
            "content": content or [{"type": "text", "text": " ", "marks": []}],
        }

    @staticmethod
    def _decode_inline(elements: Any) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for element in elements if isinstance(elements, list) else []:
            run = element.get("text_run") if isinstance(element, MappingABC) else None
            if not isinstance(run, MappingABC):
                continue
            style = run.get("text_element_style") or {}
            marks: list[Any] = []
            for name in ("bold", "italic", "underline", "strikethrough", "inline_code"):
                if style.get(name):
                    marks.append("strike" if name == "strikethrough" else name)
            link = style.get("link")
            if isinstance(link, MappingABC) and link.get("url"):
                marks.append(
                    {
                        "type": "link",
                        "href": str(link["url"]),
                        "title": str(link.get("title") or ""),
                    }
                )
            result.append(
                {"type": "text", "text": str(run.get("content") or ""), "marks": marks}
            )
        return result

    @classmethod
    def _encode_block(cls, block: Mapping[str, Any]) -> dict[str, Any]:
        block_type = str(block["type"])
        native = cls._NATIVE_TYPES.get(block_type)
        if native is None:
            raise DocumentUnavailable(f"Lark block type {block_type} has no writer")
        native_type, key = native
        if block_type == "divider":
            return {"block_type": native_type, "divider": {}}
        if block_type == "code_block":
            text = block.get("text")
            if not isinstance(text, str):
                raise DocumentUnavailable("Lark code text is invalid")
            elements = [
                {
                    "text_run": {
                        "content": text,
                        "text_element_style": {},
                    }
                }
            ]
        else:
            elements = cls._encode_inline(block.get("content") or [])
        container: dict[str, Any] = {"elements": elements}
        payload: dict[str, Any] = {"block_type": native_type, key: container}
        if block_type == "code_block":
            attrs = block.get("attrs")
            language = attrs.get("language") if isinstance(attrs, MappingABC) else None
            if language not in cls._CODE_LANGUAGES:
                raise DocumentUnavailable("Lark code language is unsupported")
            container["style"] = {
                "language": cls._CODE_LANGUAGES[str(language)],
                "wrap": bool(attrs.get("wrap", True)),
            }
        if block_type == "todo_item":
            container["style"] = {
                "done": bool(block.get("attrs", {}).get("checked", False))
            }
        return payload

    @staticmethod
    def _encode_inline(content: Any) -> list[dict[str, Any]]:
        elements: list[dict[str, Any]] = []
        for run in content if isinstance(content, list) else []:
            style: dict[str, Any] = {}
            for mark in run.get("marks", []) if isinstance(run, MappingABC) else []:
                if isinstance(mark, str):
                    style["strikethrough" if mark == "strike" else mark] = True
                elif isinstance(mark, MappingABC) and mark.get("type") == "link":
                    style["link"] = {
                        "url": mark.get("href"),
                        "title": mark.get("title", ""),
                    }
            elements.append(
                {
                    "text_run": {
                        "content": str(run.get("text") or ""),
                        "text_element_style": style,
                    }
                }
            )
        return elements

    @classmethod
    def _walk_native(cls, items: Any) -> list[Mapping[str, Any]]:
        result: list[Mapping[str, Any]] = []
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, MappingABC):
                continue
            result.append(item)
            result.extend(cls._walk_native(item.get("_hydrated_children")))
        return result

    @classmethod
    def _walk_canonical(cls, blocks: Any) -> list[Mapping[str, Any]]:
        result: list[Mapping[str, Any]] = []
        for block in blocks if isinstance(blocks, list) else []:
            if not isinstance(block, MappingABC):
                continue
            result.append(block)
            if block.get("type") in {"bullet_list", "ordered_list"}:
                for item in block.get("items") or []:
                    if isinstance(item, MappingABC):
                        result.extend(cls._walk_canonical(item.get("children")))
        return result

    @classmethod
    def _is_protected(cls, item: Mapping[str, Any]) -> bool:
        raw_type = item.get("block_type")
        try:
            if int(raw_type) in cls._PROTECTED_TYPES:
                return True
        except (TypeError, ValueError):
            pass
        return any(key in item for key in cls._PROTECTED_KEYS)

    @classmethod
    def _protection_reason(cls, item: Mapping[str, Any]) -> str | None:
        if cls._is_protected(item):
            raw_type = item.get("block_type")
            return (
                f"protected_lark_block_{raw_type}"
                if raw_type is not None
                else "protected_lark_block"
            )
        return None

    @staticmethod
    def _block_id(item: Mapping[str, Any]) -> str:
        value = item.get("block_id") or item.get("id")
        return str(value).strip() if value is not None else ""

    @staticmethod
    def _native_type(item: Mapping[str, Any]) -> int:
        value = item.get("block_type")
        try:
            return int(value)
        except (TypeError, ValueError):
            return -1

    @staticmethod
    def _native_checksum(item: Mapping[str, Any]) -> str:
        def stable(value: Any) -> Any:
            if isinstance(value, MappingABC):
                return {
                    key: stable(child)
                    for key, child in value.items()
                    if key
                    not in {
                        "block_id",
                        "id",
                        "parent_id",
                        "document_revision_id",
                        "revision_id",
                    }
                }
            if isinstance(value, list):
                return [stable(child) for child in value]
            return value

        canonical = json.dumps(
            stable(item), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        return body_checksum({"native": canonical})

    @staticmethod
    def _value(value: Any, *names: str) -> Any:
        if not isinstance(value, MappingABC):
            return None
        for name in names:
            if name in value:
                return value[name]
        data = value.get("data")
        if isinstance(data, MappingABC):
            for name in names:
                if name in data:
                    return data[name]
        return None

    @staticmethod
    def _required_value(value: Any, message: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise DocumentUnavailable(message)
        return value.strip()

    @classmethod
    def _required_version(cls, value: Any) -> str:
        return cls._required_value(
            str(value) if isinstance(value, int) else value,
            "Lark document version is required",
        )


class ConfiguredLarkDocumentResolver:
    """Resolve tenant/artifact bindings from the controlled runtime settings file."""

    def __init__(self, bindings: Any) -> None:
        self._bindings: dict[tuple[str, str], str] = {}
        if bindings in (None, {}, []):
            return
        if isinstance(bindings, list):
            for item in bindings:
                if not isinstance(item, MappingABC):
                    raise ValueError("feishu.document_bindings entries must be objects")
                self._add(
                    item.get("tenant_id"),
                    item.get("public_artifact_id"),
                    item.get("document_id"),
                )
            return
        if not isinstance(bindings, MappingABC):
            raise ValueError("feishu.document_bindings must be an object or list")
        for tenant_id, artifacts in bindings.items():
            if not isinstance(artifacts, MappingABC):
                raise ValueError(
                    "feishu.document_bindings tenant values must be objects"
                )
            for artifact_id, document_id in artifacts.items():
                self._add(tenant_id, artifact_id, document_id)

    def _add(self, tenant_id: Any, artifact_id: Any, document_id: Any) -> None:
        values = (tenant_id, artifact_id, document_id)
        if any(not isinstance(value, str) or not value.strip() for value in values):
            raise ValueError("feishu.document_bindings contains an empty identity")
        key = (tenant_id.strip(), artifact_id.strip())
        if key in self._bindings:
            raise ValueError("feishu.document_bindings contains a duplicate identity")
        self._bindings[key] = document_id.strip()

    def __call__(self, tenant_id: str, public_artifact_id: str) -> str:
        document_id = self._bindings.get((tenant_id, public_artifact_id))
        if document_id is None:
            raise DocumentUnavailable("Lark document binding is missing")
        return document_id


class ConfiguredLarkDocumentResourceResolver:
    """Resolve only checksum-pinned local resources declared by runtime settings."""

    def __init__(self, resources: Any) -> None:
        self._resources: dict[str, LarkDocumentResource] = {}
        if resources in (None, {}):
            return
        if not isinstance(resources, MappingABC):
            raise ValueError("feishu.document_resources must be an object")
        for public_id, raw in resources.items():
            if not isinstance(public_id, str) or not public_id.strip():
                raise ValueError("feishu.document_resources contains an empty identity")
            if not isinstance(raw, MappingABC):
                raise ValueError("feishu.document_resources entries must be objects")
            path_value = raw.get("path")
            file_name = raw.get("file_name")
            content_type = raw.get("content_type")
            checksum = raw.get("sha256")
            if any(
                not isinstance(value, str) or not value.strip()
                for value in (path_value, file_name, content_type, checksum)
            ):
                raise ValueError("feishu.document_resources metadata is incomplete")
            if len(checksum) != 64 or any(char not in "0123456789abcdef" for char in checksum):
                raise ValueError("feishu.document_resources sha256 is invalid")
            path = Path(path_value)
            if not path.is_file():
                raise ValueError("feishu.document_resources path is not a file")
            content = path.read_bytes()
            if hashlib.sha256(content).hexdigest() != checksum:
                raise ValueError("feishu.document_resources checksum differs from the file")
            width = self._dimension(raw.get("width"), "width")
            height = self._dimension(raw.get("height"), "height")
            self._resources[public_id.strip()] = LarkDocumentResource(
                content=content,
                file_name=file_name.strip(),
                content_type=content_type.strip(),
                width=width,
                height=height,
            )

    @staticmethod
    def _dimension(value: Any, name: str) -> int | None:
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"feishu.document_resources {name} is invalid")
        return value

    def resolve(self, public_resource_id: str) -> LarkDocumentResource:
        resource = self._resources.get(public_resource_id)
        if resource is None:
            raise DocumentUnavailable("Lark document resource binding is missing")
        return resource


def build_production_lark_document_gateway(
    feishu_service: Any,
    connection_factory: Callable[[], Any],
    bindings: Any,
    *,
    resource_resolver: LarkDocumentResourceResolver | None = None,
    resources: Any = None,
) -> "ProductionLarkDocumentGateway":
    """Build the only production Lark gateway used by the Media API runtime."""

    resolver = ConfiguredLarkDocumentResolver(bindings)
    if resource_resolver is not None and resources not in (None, {}):
        raise ValueError("provide either a resource resolver or configured resources")
    configured_resources = (
        resource_resolver
        if resource_resolver is not None
        else ConfiguredLarkDocumentResourceResolver(resources)
    )
    client = AuthenticatedLarkDocumentClient(
        feishu_service,
        receipt_store=SqlLarkWriteReceiptStore(connection_factory),
        resource_resolver=configured_resources,
    )
    return ProductionLarkDocumentGateway(client, resolver)


@dataclass(frozen=True)
class _ValidatedRevision:
    snapshot: LarkRevisionSnapshot
    body_checksum: str


class ProductionLarkDocumentGateway:
    """Pins reads and proves every external mutation by exact-version readback."""

    def __init__(
        self, client: LarkDocumentClient, resolve_document: DocumentResolver
    ) -> None:
        self._client = client
        self._resolve_document = resolve_document

    def read_revision(
        self,
        tenant_id: str,
        public_artifact_id: str,
        remote_document_version: str | None,
    ) -> LarkRevisionSnapshot:
        document_id = self._document_id(tenant_id, public_artifact_id)
        version = self._required_version(
            remote_document_version or self._client.current_version(document_id),
            "Lark did not return a document version",
        )
        return self._read_exact(document_id, version).snapshot

    def save_draft(
        self,
        tenant_id: str,
        public_artifact_id: str,
        body: dict[str, Any],
        expected_remote_version: str,
        public_sync_id: str,
    ) -> LarkRevisionSnapshot:
        document_id = self._document_id(tenant_id, public_artifact_id)
        expected = self._required_version(
            expected_remote_version, "expected Lark document version is required"
        )
        sync_id = self._required_value(public_sync_id, "Lark sync identity is required")
        desired = validate_body(body)
        baseline = self._read_exact(document_id, expected).snapshot
        protected = {
            block.public_block_id for block in baseline.blocks if block.is_protected
        }
        preserve_protected_blocks(baseline.body, desired, protected)

        try:
            receipt = self._client.write_canonical_revision(
                document_id,
                copy.deepcopy(desired),
                expected_remote_version=expected,
                idempotency_key=sync_id,
            )
        except (DocumentConflict, UnsupportedDocumentBlock):
            raise
        except Exception as exc:
            raise DocumentUnavailable(
                "Lark write outcome is unknown and requires reconciliation"
            ) from exc

        return self._prove_write(
            document_id,
            sync_id,
            expected,
            body_checksum(desired),
            receipt,
        )

    def reconcile_save(
        self,
        tenant_id: str,
        public_artifact_id: str,
        public_sync_id: str,
        expected_remote_version: str,
    ) -> LarkRevisionSnapshot:
        document_id = self._document_id(tenant_id, public_artifact_id)
        sync_id = self._required_value(public_sync_id, "Lark sync identity is required")
        expected = self._required_version(
            expected_remote_version, "expected Lark document version is required"
        )
        receipt = self._client.get_write_receipt(document_id, sync_id)
        if receipt is None:
            current = self._required_version(
                self._client.current_version(document_id),
                "Lark did not return a document version during reconciliation",
            )
            if current == expected:
                raise DocumentUnavailable("Lark write has no durable external receipt")
            raise DocumentConflict(
                "Lark document advanced without a matching external write receipt"
            )
        checksum = self._required_checksum(receipt.get("bodyChecksum"))
        return self._prove_write(document_id, sync_id, expected, checksum, receipt)

    def _prove_write(
        self,
        document_id: str,
        sync_id: str,
        expected_version: str,
        expected_checksum: str,
        receipt: Mapping[str, Any],
    ) -> LarkRevisionSnapshot:
        if not isinstance(receipt, Mapping):
            raise DocumentUnavailable("Lark write returned an invalid receipt")
        if receipt.get("idempotencyKey") != sync_id:
            raise DocumentConflict(
                "Lark write receipt identity does not match the sync batch"
            )
        if receipt.get("baseRemoteDocumentVersion") != expected_version:
            raise DocumentConflict("Lark write receipt baseline does not match")
        if self._required_checksum(receipt.get("bodyChecksum")) != expected_checksum:
            raise DocumentConflict("Lark write receipt body checksum does not match")
        version = self._required_version(
            receipt.get("remoteDocumentVersion"),
            "Lark write receipt has no document version",
        )
        if version == expected_version:
            raise DocumentConflict("Lark write did not advance the document version")
        readback = self._read_exact(document_id, version)
        if readback.body_checksum != expected_checksum:
            raise DocumentConflict("Lark write readback body checksum does not match")
        return readback.snapshot

    def _read_exact(self, document_id: str, version: str) -> _ValidatedRevision:
        try:
            payload = self._client.read_canonical_revision(document_id, version)
        except (DocumentConflict, UnsupportedDocumentBlock):
            raise
        except Exception as exc:
            raise DocumentUnavailable("Lark fixed-revision read failed") from exc
        if not isinstance(payload, Mapping):
            raise DocumentUnavailable("Lark revision payload is invalid")
        if payload.get("complete") is not True:
            raise DocumentUnavailable("Lark block inventory is incomplete")
        actual_version = self._required_version(
            payload.get("remoteDocumentVersion"), "Lark revision version is missing"
        )
        if actual_version != version:
            raise DocumentConflict("Lark returned a different document version")

        body = validate_body(payload.get("body"))
        checksum = body_checksum(body)
        if self._required_checksum(payload.get("bodyChecksum")) != checksum:
            raise DocumentConflict("Lark revision body checksum does not match")
        raw_blocks = payload.get("blocks")
        if not isinstance(raw_blocks, list):
            raise DocumentUnavailable("Lark block inventory is invalid")
        blocks = tuple(self._block_snapshot(item) for item in raw_blocks)
        declared_count = payload.get("blockCount")
        declared_protected = payload.get("protectedBlockCount")
        if declared_count != len(blocks):
            raise DocumentUnavailable("Lark block inventory count does not match")
        if declared_protected != sum(item.is_protected for item in blocks):
            raise DocumentUnavailable("Lark protected block count does not match")
        public_ids = [item.public_block_id for item in blocks]
        remote_ids = [item.remote_block_id for item in blocks]
        if len(public_ids) != len(set(public_ids)) or len(remote_ids) != len(
            set(remote_ids)
        ):
            raise DocumentUnavailable(
                "Lark block inventory contains duplicate identities"
            )
        body_by_id = {str(block["id"]): block for block in body["blocks"]}
        if set(public_ids) != set(body_by_id):
            raise DocumentConflict(
                "Lark block inventory does not cover the canonical body"
            )
        for block in blocks:
            if block.block_checksum != body_checksum(body_by_id[block.public_block_id]):
                raise DocumentConflict(
                    "Lark block checksum does not match the canonical block"
                )
        return _ValidatedRevision(
            LarkRevisionSnapshot(body, actual_version, blocks), checksum
        )

    @classmethod
    def _block_snapshot(cls, value: Any) -> LarkBlockSnapshot:
        if not isinstance(value, Mapping):
            raise DocumentUnavailable("Lark block mapping is invalid")
        public_id = cls._required_value(
            value.get("publicBlockId"), "public block id is missing"
        )
        remote_id = cls._required_value(
            value.get("remoteBlockId"), "remote block id is missing"
        )
        checksum = cls._required_checksum(value.get("blockChecksum"))
        protected = value.get("isProtected")
        reason = value.get("protectionReason")
        if not isinstance(protected, bool):
            raise DocumentUnavailable("Lark block protection flag is invalid")
        if protected:
            reason = cls._required_value(
                reason, "protected Lark block reason is missing"
            )
        elif reason is not None:
            raise DocumentUnavailable("unprotected Lark block has a protection reason")
        return LarkBlockSnapshot(public_id, remote_id, checksum, protected, reason)

    def _document_id(self, tenant_id: str, public_artifact_id: str) -> str:
        tenant = self._required_value(tenant_id, "tenant identity is required")
        artifact = self._required_value(
            public_artifact_id, "artifact identity is required"
        )
        return self._required_value(
            self._resolve_document(tenant, artifact), "Lark document binding is missing"
        )

    @staticmethod
    def _required_value(value: Any, message: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise DocumentUnavailable(message)
        return value.strip()

    @classmethod
    def _required_version(cls, value: Any, message: str) -> str:
        return cls._required_value(value, message)

    @staticmethod
    def _required_checksum(value: Any) -> str:
        if (
            not isinstance(value, str)
            or len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)
        ):
            raise DocumentUnavailable("Lark checksum is invalid")
        return value
