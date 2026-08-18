"""Owner-authenticated, atomic commits for small descriptor/text artifacts."""
from __future__ import annotations

from hashlib import sha256
import json
from threading import RLock
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


_FORBIDDEN_MIME_PREFIXES = ("video/", "audio/")
_ALLOWED_MIME = {"application/json", "text/plain", "text/markdown"}
_MAGIC = (b"\x00\x00\x00\x18ftyp", b"ID3", b"\x1aE\xdf\xa3", b"RIFF")


class ArchiveItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)
    ref: str = Field(min_length=1, max_length=256)
    mime_type: str = Field(min_length=1, max_length=96)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0, le=1_048_576)
    content: bytes | None = None
    descriptor_only: bool = False


class ArchiveManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)
    manifest_id: str = Field(min_length=8, max_length=128)
    tenant_id: str = Field(min_length=1, max_length=128)
    owner_id: str = Field(min_length=1, max_length=128)
    items: tuple[ArchiveItem, ...] = Field(min_length=1, max_length=32)
    quota_bytes: int = Field(gt=0, le=1_048_576)


class ArchiveReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    commit_id: str
    manifest_id: str
    tenant_id: str
    owner_id: str
    item_refs: tuple[str, ...]
    total_bytes: int
    cloud_bytes: Literal[0] = 0


class ArchiveOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    status: Literal["archived", "manual"]
    code: str
    receipt: ArchiveReceipt | None = None


def _manual(code: str) -> ArchiveOutcome:
    return ArchiveOutcome(status="manual", code=code)


def _safe_ref(ref: object) -> bool:
    if not isinstance(ref, str) or not ref or "\\" in ref or "\x00" in ref:
        return False
    parts = ref.split("/")
    return not ref.startswith("/") and ".." not in parts and not (len(ref) >= 2 and ref[1] == ":")


class ArchiveRegistry:
    """In-process canonical archive boundary; persistence is supplied by the next unit."""

    def __init__(self, *, max_item_bytes: int = 1_048_576):
        self.max_item_bytes = max_item_bytes
        self._manifests: dict[tuple[str, str], ArchiveManifest] = {}
        self._receipts: dict[tuple[str, str], ArchiveOutcome] = {}
        self._lock = RLock()

    def create_manifest(self, manifest: ArchiveManifest) -> ArchiveOutcome:
        with self._lock:
            key = (manifest.tenant_id, manifest.manifest_id)
            if key in self._manifests:
                return _manual("manifest_exists")
            if any(not _safe_ref(item.ref) for item in manifest.items):
                return _manual("unsafe_ref")
            if any(item.mime_type.lower().startswith(_FORBIDDEN_MIME_PREFIXES) for item in manifest.items):
                return _manual("media_bytes_forbidden")
            if any(item.mime_type not in _ALLOWED_MIME for item in manifest.items):
                return _manual("mime_forbidden")
            total = sum(item.size_bytes for item in manifest.items)
            if total > manifest.quota_bytes or any(item.size_bytes > self.max_item_bytes for item in manifest.items):
                return _manual("quota_exceeded")
            if len({item.ref for item in manifest.items}) != len(manifest.items):
                return _manual("duplicate_ref")
            for item in manifest.items:
                if item.content is not None:
                    if len(item.content) != item.size_bytes or sha256(item.content).hexdigest() != item.sha256:
                        return _manual("content_mismatch")
                    if item.content.startswith(_MAGIC):
                        return _manual("magic_forbidden")
                elif not item.descriptor_only:
                    return _manual("content_missing")
            self._manifests[key] = manifest
            return ArchiveOutcome(status="archived", code="manifest_accepted")

    def commit(self, tenant_id: str, owner_id: str, manifest_id: str) -> ArchiveOutcome:
        with self._lock:
            key = (tenant_id, manifest_id)
            existing = self._receipts.get(key)
            if existing is not None:
                return existing
            manifest = self._manifests.get(key)
            if manifest is None:
                return _manual("manifest_missing")
            if manifest.owner_id != owner_id:
                return _manual("owner_forbidden")
            total = sum(item.size_bytes for item in manifest.items)
            receipt = ArchiveReceipt(
                commit_id="commit_" + uuid4().hex,
                manifest_id=manifest.manifest_id,
                tenant_id=tenant_id,
                owner_id=owner_id,
                item_refs=tuple(item.ref for item in manifest.items),
                total_bytes=total,
            )
            outcome = ArchiveOutcome(status="archived", code="committed", receipt=receipt)
            self._receipts[key] = outcome
            return outcome


__all__ = ["ArchiveItem", "ArchiveManifest", "ArchiveOutcome", "ArchiveReceipt", "ArchiveRegistry"]
