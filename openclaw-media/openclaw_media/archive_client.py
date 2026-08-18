"""Client-side ArchiveManifest construction and owner-confirmed operations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import base64
import binascii
import json
import mimetypes
from pathlib import Path, PurePosixPath
import re
from typing import Any, Mapping, Sequence

from .remote_client import RemoteClient, RemoteError
from .workspace import LocalWorkspace, WorkspaceGcOutcome


class ArchiveClientError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


_CONTENT_MIME = {"application/json", "text/plain", "text/markdown"}
_MEDIA_PREFIX = ("video/", "audio/", "image/")
_MAX_CONTENT = 1_048_576
_SHA256 = re.compile(r"\A[0-9a-f]{64}\Z")
_SAFE_REF = re.compile(r"\A[A-Za-z0-9_:/?.=-]{1,500}\Z")
_MEDIA_MAGIC = (
    b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff", b"GIF8", b"RIFF", b"ID3",
    b"OggS", b"fLaC", b"\x1a\x45\xdf\xa3", b"%PDF", b"PK\x03\x04",
)


@dataclass(frozen=True, slots=True)
class ArtifactSelection:
    ref: str
    local_path: Path
    mime_type: str | None = None
    mode: str | None = None
    description: str | None = None


def _ref(value: str) -> str:
    if not isinstance(value, str) or not _SAFE_REF.fullmatch(value) or "\\" in value or "\x00" in value:
        raise ArchiveClientError("unsafe_ref")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ArchiveClientError("unsafe_ref")
    return path.as_posix()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _extension_mime(name: str) -> str | None:
    return mimetypes.guess_type(name)[0]


def _is_media_mime(mime: str) -> bool:
    return mime.lower().startswith(_MEDIA_PREFIX)


def _looks_like_media(value: bytes) -> bool:
    return value.startswith(_MEDIA_MAGIC) or (len(value) >= 12 and value[4:8] == b"ftyp")


def _decode_content(content: Mapping[str, Any]) -> bytes:
    if set(content) != {"encoding", "value"}:
        raise ArchiveClientError("invalid_content")
    encoding = content.get("encoding")
    encoded = content.get("value")
    if encoding not in {"utf8", "base64"} or not isinstance(encoded, str):
        raise ArchiveClientError("invalid_content")
    if "\x00" in encoded:
        raise ArchiveClientError("invalid_content")
    if encoding == "utf8":
        try:
            decoded = encoded.encode("utf-8")
        except UnicodeError as exc:  # pragma: no cover - str.encode is total for valid Python str
            raise ArchiveClientError("invalid_content") from exc
    else:
        try:
            decoded = base64.b64decode(encoded.encode("ascii"), validate=True)
        except (UnicodeEncodeError, binascii.Error, ValueError) as exc:
            raise ArchiveClientError("invalid_content") from exc
    if b"\x00" in decoded or _looks_like_media(decoded):
        raise ArchiveClientError("content_forbidden")
    try:
        text = decoded.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ArchiveClientError("content_forbidden") from exc
    if "\x00" in text:
        raise ArchiveClientError("content_forbidden")
    return decoded


def _validate_mime_extension(name: str, mime: str, *, content: bool) -> None:
    guessed = _extension_mime(name)
    if guessed is not None and guessed.lower() != mime:
        raise ArchiveClientError("invalid_mime")
    if content and (guessed is None or guessed.lower() != mime or mime not in _CONTENT_MIME):
        raise ArchiveClientError("content_forbidden")


def _validate_artifact(item: Mapping[str, Any]) -> dict[str, Any]:
    required = {"ref", "mode", "mime_type", "sha256", "size_bytes", "descriptor", "metadata", "content"}
    if set(item) != required:
        raise ArchiveClientError("invalid_item")
    try:
        ref = _ref(item["ref"])
    except (ArchiveClientError, TypeError) as exc:
        raise ArchiveClientError("invalid_ref") from exc
    mode = item["mode"]
    if mode not in {"content", "descriptor_only", "forbidden"}:
        raise ArchiveClientError("invalid_mode")
    mime = item["mime_type"]
    if not isinstance(mime, str) or not mime or mime != mime.strip() or len(mime) > 128:
        raise ArchiveClientError("invalid_mime")
    mime = mime.lower()
    digest = item["sha256"]
    size = item["size_bytes"]
    descriptor = item["descriptor"]
    if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
        raise ArchiveClientError("invalid_sha256")
    if isinstance(size, bool) or not isinstance(size, int) or not 0 <= size <= _MAX_CONTENT:
        raise ArchiveClientError("invalid_size")
    if not isinstance(descriptor, bool) or descriptor != (mode != "content"):
        raise ArchiveClientError("invalid_descriptor")
    metadata = item["metadata"]
    if not isinstance(metadata, Mapping) or set(metadata) != {"name", "description", "source_ref"}:
        raise ArchiveClientError("invalid_metadata")
    name = metadata["name"]
    description = metadata["description"]
    source_ref = metadata["source_ref"]
    if (
        not isinstance(name, str) or not name or name != Path(name).name or "\\" in name or "\x00" in name
        or not isinstance(description, (str, type(None)))
    ):
        raise ArchiveClientError("invalid_metadata")
    if source_ref is not None:
        try:
            source_ref = _ref(source_ref)
        except (ArchiveClientError, TypeError) as exc:
            raise ArchiveClientError("invalid_metadata") from exc
    _validate_mime_extension(name, mime, content=mode == "content")
    is_media = _is_media_mime(mime)
    content_value = item["content"]
    if mode == "content":
        if is_media or not isinstance(content_value, Mapping) or mime not in _CONTENT_MIME:
            raise ArchiveClientError("content_forbidden")
        decoded = _decode_content(content_value)
        if len(decoded) != size or sha256(decoded).hexdigest() != digest:
            raise ArchiveClientError("content_mismatch")
        if mime == "application/json":
            try:
                json.loads(decoded.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ArchiveClientError("content_mismatch") from exc
    elif content_value is not None:
        raise ArchiveClientError("descriptor_content_forbidden")
    return {
        "ref": ref,
        "mode": mode,
        "mime_type": mime,
        "sha256": digest,
        "size_bytes": size,
        "descriptor": descriptor,
        "metadata": {"name": name, "description": description, "source_ref": source_ref},
        "content": dict(content_value) if isinstance(content_value, Mapping) else None,
    }


class ArchiveClient:
    def __init__(self, remote: RemoteClient, *, workspace: Path | str | None = None) -> None:
        self.remote = remote
        self.workspace = None if workspace is None else Path(workspace).resolve()

    def _selection(self, selection: ArtifactSelection) -> dict[str, Any]:
        ref = _ref(selection.ref)
        path = Path(selection.local_path).resolve()
        if self.workspace is not None:
            try:
                path.relative_to(self.workspace)
            except ValueError as exc:
                raise ArchiveClientError("artifact_outside_workspace") from exc
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise ArchiveClientError("artifact_unavailable") from exc
        size = len(raw)
        extension_mime = _extension_mime(path.name)
        mime = extension_mime or "application/octet-stream"
        if selection.mime_type is not None:
            if not isinstance(selection.mime_type, str) or not selection.mime_type.strip():
                raise ArchiveClientError("invalid_mime")
            if selection.mime_type.strip().lower() != mime.lower():
                raise ArchiveClientError("invalid_mime")
        mime = mime.lower()
        digest = sha256(raw).hexdigest()
        is_media = _is_media_mime(mime)
        mode = selection.mode or ("descriptor_only" if is_media else "content")
        if mode not in {"content", "descriptor_only", "forbidden"}:
            raise ArchiveClientError("invalid_mode")
        if mime in _CONTENT_MIME:
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ArchiveClientError("content_forbidden") from exc
            if "\x00" in text or _looks_like_media(raw):
                raise ArchiveClientError("content_forbidden")
        content: dict[str, str] | None = None
        if mode == "content":
            if mime not in _CONTENT_MIME or is_media or size > _MAX_CONTENT:
                raise ArchiveClientError("content_forbidden")
            if mime == "application/json":
                try:
                    json.loads(text)
                except json.JSONDecodeError as exc:
                    raise ArchiveClientError("content_mismatch") from exc
            content = {"encoding": "utf8", "value": text}
        return _validate_artifact({
            "ref": ref,
            "mode": mode,
            "mime_type": mime,
            "sha256": digest,
            "size_bytes": size,
            "descriptor": mode != "content",
            "metadata": {"name": path.name, "description": selection.description, "source_ref": ref},
            "content": content,
        })

    def build_manifest(
        self,
        *,
        manifest_id: str,
        run_id: str,
        confirmation_ref: str,
        selections: Sequence[ArtifactSelection],
        created_at: str | None = None,
    ) -> dict[str, Any]:
        if not selections or len(selections) > 32:
            raise ArchiveClientError("invalid_items")
        if not all(isinstance(value, str) and value.strip() for value in (manifest_id, run_id, confirmation_ref)):
            raise ArchiveClientError("invalid_confirmation")
        return {
            "manifest_id": manifest_id,
            "run_id": run_id,
            "confirmation_ref": confirmation_ref,
            "items": [self._selection(item) for item in selections],
            "created_at": created_at or _now(),
        }

    def confirm(self, manifest: Mapping[str, Any], *, confirmation_ref: str) -> dict[str, Any]:
        try:
            confirmation_ref = _ref(confirmation_ref)
        except (ArchiveClientError, TypeError) as exc:
            raise ArchiveClientError("invalid_confirmation")
        if not isinstance(manifest, Mapping) or set(manifest) != {"manifest_id", "run_id", "confirmation_ref", "items", "created_at"}:
            raise ArchiveClientError("invalid_manifest")
        value = dict(manifest)
        for key in ("manifest_id", "run_id"):
            if not isinstance(value[key], str) or not value[key].strip() or "\x00" in value[key]:
                raise ArchiveClientError("invalid_manifest")
            try:
                value[key] = _ref(value[key])
            except (ArchiveClientError, TypeError) as exc:
                raise ArchiveClientError("invalid_manifest") from exc
        if not isinstance(value["created_at"], str) or not value["created_at"].strip() or "\x00" in value["created_at"]:
            raise ArchiveClientError("invalid_manifest")
        try:
            _ref(value["confirmation_ref"])
        except (ArchiveClientError, TypeError) as exc:
            raise ArchiveClientError("invalid_manifest") from exc
        value["confirmation_ref"] = confirmation_ref
        items = value.get("items")
        if not isinstance(items, list) or not 1 <= len(items) <= 32:
            raise ArchiveClientError("invalid_items")
        normalized = []
        refs = set()
        for item in items:
            if not isinstance(item, Mapping):
                raise ArchiveClientError("invalid_item")
            normalized_item = _validate_artifact(item)
            if normalized_item["ref"] in refs:
                raise ArchiveClientError("duplicate_ref")
            refs.add(normalized_item["ref"])
            normalized.append(normalized_item)
        value["items"] = normalized
        return value

    def commit(self, *, run_id: str, manifest: Mapping[str, Any], confirmation_ref: str) -> Mapping[str, Any]:
        confirmed = self.confirm(manifest, confirmation_ref=confirmation_ref)
        return self.remote.archive_commit({"run_id": run_id, "manifest": confirmed, "confirmation_ref": confirmation_ref})

    def readback(self, archive_id: str, *, receipt_ref: str, observed_refs: Sequence[str] = ()) -> Mapping[str, Any]:
        if not receipt_ref:
            raise ArchiveClientError("invalid_readback_receipt")
        return self.remote.archive_readback(archive_id, readback_receipt_ref=receipt_ref, observed_refs=list(observed_refs))

    def delete(
        self,
        archive_id: str,
        *,
        confirmation_ref: str,
        expected_revision: int,
        readback_receipt_ref: str | None = None,
    ) -> Mapping[str, Any]:
        if expected_revision < 1 or not confirmation_ref:
            raise ArchiveClientError("invalid_delete_confirmation")
        plan = self.remote.archive_delete_plan(archive_id)
        plan_id = plan.get("delete_plan_id")
        if not isinstance(plan_id, str) or not plan_id:
            raise RemoteError("invalid_delete_plan")
        result = self.remote.archive_delete(
            archive_id,
            delete_plan_id=plan_id,
            confirmation_ref=confirmation_ref,
            expected_revision=expected_revision,
        )
        if readback_receipt_ref:
            return {"delete": result, "readback": self.readback(archive_id, receipt_ref=readback_receipt_ref)}
        return result

    def gc(self, *, dry_run: bool = True, now: float | None = None, min_age_seconds: float = 14 * 86400) -> WorkspaceGcOutcome:
        if self.workspace is None:
            raise ArchiveClientError("workspace_not_configured")
        return LocalWorkspace(self.workspace).collect_garbage(
            dry_run=dry_run, now=now, min_age_seconds=min_age_seconds
        )


__all__ = ["ArchiveClient", "ArchiveClientError", "ArtifactSelection"]
