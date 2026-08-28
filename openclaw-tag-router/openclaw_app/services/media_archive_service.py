from __future__ import annotations

import base64
import binascii
import hashlib
import importlib.util
import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any, Mapping

from .media_archive_store import MediaArchiveStore
from .media_device_job_contract import validate_r1_response


# `parents[3]` is the repository root: <repo>/openclaw-tag-router/openclaw_app/services/...
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
ARCHIVE_CONTRACT_PATH_ENV = "OPENCLAW_MEDIA_GENERATED_CONTRACT"
REPOSITORY_GENERATED_CONTRACT = REPOSITORY_ROOT / "media-agent-cli/generated_product_contract.py"
_KEY = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
_REF = re.compile(r"[A-Za-z0-9_:/?.=-]{1,500}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_CONTENT_MIMES = frozenset({"application/json", "text/plain", "text/markdown"})
_MODES = frozenset({"content", "descriptor_only", "forbidden"})
_MAX_ITEMS = 32
_MAX_ITEM_BYTES = 1024 * 1024
_MAX_CONTENT_VALUE_CHARS = 1024 * 1024
_MAX_METADATA_TEXT_CHARS = 500
_MAX_DATETIME_CHARS = 64
_MAX_BASE64_WIRE_BYTES = 4 * ((_MAX_ITEM_BYTES + 2) // 3)
_MAX_UTF8_JSON_WIRE_BYTES = 2 * _MAX_ITEM_BYTES
_ARCHIVE_ITEM_JSON_OVERHEAD_BYTES = 4096
_ARCHIVE_MANIFEST_JSON_OVERHEAD_BYTES = 64 * 1024
# A full manifest is bounded by the larger of base64 expansion and canonical JSON
# escaping of UTF-8 text, plus bounded metadata/manifest framing overhead.
ARCHIVE_HTTP_BODY_MAXIMUM_BYTES = (
    _MAX_ITEMS * max(_MAX_BASE64_WIRE_BYTES, _MAX_UTF8_JSON_WIRE_BYTES)
    + _MAX_ITEMS * _ARCHIVE_ITEM_JSON_OVERHEAD_BYTES
    + _ARCHIVE_MANIFEST_JSON_OVERHEAD_BYTES
)
_MEDIA_MARKER = re.compile(r"(?:^|[:/_.-])(raw|proxy|final|audio|video|media)(?:$|[:/_.-])", re.IGNORECASE)


def resolve_archive_contract_path() -> Path:
    override = os.getenv(ARCHIVE_CONTRACT_PATH_ENV, "").strip()
    candidates = (Path(override).expanduser(),) if override else (REPOSITORY_GENERATED_CONTRACT,)
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return candidates[0]


CANONICAL_GENERATED_CONTRACT = resolve_archive_contract_path()


def _load_contract() -> ModuleType:
    spec = importlib.util.spec_from_file_location("openclaw_media_generated_archive_contract", CANONICAL_GENERATED_CONTRACT)
    if spec is None or spec.loader is None:
        raise RuntimeError("canonical generated media contract cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_CONTRACT = _load_contract()
ARCHIVE_OPERATION_IDS = (
    "archive_commit",
    "archive_list",
    "archive_detail",
    "archive_delete_plan",
    "archive_delete",
    "archive_readback",
)


class MediaArchiveError(Exception):
    def __init__(self, code: str, detail: str, *, status: int = 400) -> None:
        super().__init__(detail)
        self.code, self.detail, self.status = code, detail, status


def resolve_archive_operation(relative_path: str, method: str) -> tuple[str, dict[str, str]] | None:
    for operation_id in ARCHIVE_OPERATION_IDS:
        operation = _CONTRACT.OPERATIONS[operation_id]
        if str(operation["method"]).upper() != method.upper():
            continue
        path = str(operation["relative_path"])
        cursor = 0
        pieces: list[str] = []
        for match in re.finditer(r"\{([a-z_]+)\}", path):
            pieces.append(re.escape(path[cursor : match.start()]))
            pieces.append(r"(?P<" + match.group(1) + r">[A-Za-z0-9_-]+)")
            cursor = match.end()
        pieces.append(re.escape(path[cursor:]))
        match = re.fullmatch("".join(pieces), relative_path)
        if match:
            return operation_id, match.groupdict()
    return None


class MediaArchiveService:
    """Tenant-owned R2 archive API with text-only cloud content."""

    def __init__(self, store: MediaArchiveStore, *, quota_bytes: int = 256 * 1024) -> None:
        if isinstance(quota_bytes, bool) or not isinstance(quota_bytes, int) or quota_bytes <= 0:
            raise ValueError("archive quota must be positive")
        self.store = store
        self.quota_bytes = quota_bytes

    def commit(self, tenant_id: str, payload: Mapping[str, Any], *, idempotency_key: str) -> dict[str, Any]:
        tenant = self._tenant(tenant_id)
        key = self._key(idempotency_key)
        self._fields(payload, {"run_id", "manifest", "confirmation_ref"}, {"run_id", "manifest", "confirmation_ref"})
        manifest = self._manifest(payload["manifest"])
        run_id = self._ref(payload["run_id"], "run_id")
        confirmation = self._ref(payload["confirmation_ref"], "confirmation_ref")
        if run_id != manifest["run_id"] or confirmation != manifest["confirmation_ref"]:
            raise MediaArchiveError("commit_rejected", "archive ownership confirmation is invalid")
        artifacts, refs, total_bytes, cloud_bytes = self._artifacts(manifest["items"])
        if total_bytes > self.quota_bytes:
            raise MediaArchiveError("commit_rejected", "archive quota exceeded")
        fingerprint = self._fingerprint({"run_id": run_id, "manifest": manifest, "confirmation_ref": confirmation})
        now = self.store._clock()
        with self.store.write_transaction() as connection:
            existing = self._idempotency_get(connection, tenant, "archive_commit", key, fingerprint)
            if existing is not None:
                return self._validated("archive_commit", self._replay_commit(connection, tenant, existing))
            archive_id = self.store.new_id("arc")
            commit_id = self.store.new_id("acm")
            connection.execute(
                "INSERT INTO archive_records(archive_id, tenant_id, commit_id, manifest_id, run_id, pipeline_id, pipeline_version, device_id, artifacts_json, cloud_bytes, media_cloud_bytes, state, revision, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 'active', 1, ?, ?)",
                (archive_id, tenant, commit_id, manifest["manifest_id"], run_id, None, None, None, self.store.json(artifacts), cloud_bytes, now, now),
            )
            connection.execute(
                "INSERT INTO archive_commits(commit_id, tenant_id, archive_id, manifest_id, run_id, state, artifact_refs_json, total_bytes, cloud_bytes, media_cloud_bytes, committed_at, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 'draft', ?, ?, ?, 0, NULL, ?, ?)",
                (commit_id, tenant, archive_id, manifest["manifest_id"], run_id, self.store.json(refs), total_bytes, cloud_bytes, now, now),
            )
            connection.execute("UPDATE archive_commits SET state = 'committing', updated_at = ? WHERE commit_id = ?", (now, commit_id))
            for index, artifact in enumerate(artifacts):
                content = artifact["content"]
                decoded = self._decoded_content(content) if artifact["mode"] == "content" else None
                connection.execute(
                    "INSERT INTO archive_attachments(attachment_id, archive_id, artifact_ref, mode, mime_type, sha256, size_bytes, encoding, metadata_json, content) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        f"{archive_id}_att_{index}",
                        archive_id,
                        artifact["ref"],
                        artifact["mode"],
                        artifact["mime_type"],
                        artifact["sha256"],
                        artifact["size_bytes"],
                        content["encoding"] if content else None,
                        self.store.json(artifact["metadata"]),
                        decoded,
                    ),
                )
            projection_refs = self._insert_projections(connection, archive_id, refs)
            connection.execute("UPDATE archive_commits SET state = 'verifying', updated_at = ? WHERE commit_id = ?", (now, commit_id))
            receipt_ref = f"rb_{archive_id}"
            connection.execute(
                "INSERT INTO archive_readback_receipts(readback_receipt_ref, archive_id, tenant_id, kind, artifact_refs_json, projection_refs_json, verified, db_present, attachments_present, projections_present, checked_at, created_at) VALUES (?, ?, ?, 'commit', ?, ?, 1, 1, 1, 1, ?, ?)",
                (receipt_ref, archive_id, tenant, self.store.json(refs), self.store.json(projection_refs), now, now),
            )
            connection.execute("UPDATE archive_commits SET state = 'archived', committed_at = ?, updated_at = ? WHERE commit_id = ?", (now, now, commit_id))
            response = self._commit_response(connection, tenant, archive_id, receipt_ref)
            self._idempotency_put(
                connection,
                tenant,
                "archive_commit",
                key,
                fingerprint,
                response,
                201,
                now,
                archive_id=archive_id,
            )
            return self._validated("archive_commit", response)

    def list(self, tenant_id: str, *, limit: int = 30, state: str | None = None) -> dict[str, Any]:
        tenant = self._tenant(tenant_id)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise MediaArchiveError("invalid_request", "limit is invalid")
        if state is not None and state not in {"active", "deleting", "delete_failed"}:
            raise MediaArchiveError("invalid_request", "state is invalid")
        query = "SELECT * FROM archive_records WHERE tenant_id = ?"
        args: list[Any] = [tenant]
        if state is not None:
            query += " AND state = ?"
            args.append(state)
        query += " ORDER BY created_at DESC, archive_id DESC LIMIT ?"
        args.append(limit)
        with self.store.connect() as connection:
            rows = connection.execute(query, args).fetchall()
            response = {"archives": [self._project_row(connection, row) for row in rows], "next_cursor": None}
        return self._validated("archive_list", response)

    def detail(self, tenant_id: str, archive_id: str) -> dict[str, Any]:
        tenant = self._tenant(tenant_id)
        with self.store.connect() as connection:
            row = self._owned_row(connection, tenant, archive_id)
            response = {"archive": self._project_row(connection, row)}
        return self._validated("archive_detail", response)

    def delete_plan(self, tenant_id: str, archive_id: str, *, idempotency_key: str) -> dict[str, Any]:
        tenant = self._tenant(tenant_id)
        key = self._key(idempotency_key)
        now = self.store._clock()
        fingerprint = self._fingerprint({"archive_id": archive_id})
        with self.store.write_transaction() as connection:
            existing = self._idempotency_get(connection, tenant, "archive_delete_plan", key, fingerprint)
            if existing is not None:
                response = self._replay_response("archive_delete_plan", existing)
                plan = connection.execute(
                    "SELECT expires_at FROM archive_delete_plans WHERE delete_plan_id = ? AND archive_id = ? AND tenant_id = ?",
                    (response.get("delete_plan_id"), archive_id, tenant),
                ).fetchone()
                if plan is not None and float(plan["expires_at"]) > now:
                    return self._validated("archive_delete_plan", response)
                connection.execute(
                    "DELETE FROM archive_idempotency WHERE scope = ? AND operation_id = 'archive_delete_plan' AND idempotency_key = ?",
                    (f"tenant:{tenant}", key),
                )
                connection.execute(
                    "DELETE FROM archive_delete_plans WHERE delete_plan_id = ? AND archive_id = ? AND tenant_id = ?",
                    (response.get("delete_plan_id"), archive_id, tenant),
                )
            row = self._owned_row(connection, tenant, archive_id)
            if row["state"] != "active":
                raise MediaArchiveError("delete_not_allowed", "archive cannot be deleted in its current state", status=409)
            plan_id = self.store.new_id("adp")
            expires_at = now + 600
            connection.execute(
                "INSERT INTO archive_delete_plans(delete_plan_id, archive_id, tenant_id, expires_at, created_at) VALUES (?, ?, ?, ?, ?)",
                (plan_id, archive_id, tenant, expires_at, now),
            )
            response = {"delete_plan_id": plan_id, "archive_id": archive_id, "expires_at": self._iso(expires_at)}
            self._idempotency_put(
                connection,
                tenant,
                "archive_delete_plan",
                key,
                fingerprint,
                response,
                200,
                now,
                archive_id=archive_id,
            )
            return self._validated("archive_delete_plan", response)

    def delete(self, tenant_id: str, archive_id: str, payload: Mapping[str, Any], *, idempotency_key: str) -> dict[str, Any]:
        tenant = self._tenant(tenant_id)
        key = self._key(idempotency_key)
        self._fields(payload, {"delete_plan_id", "confirmation_ref", "expected_revision"}, {"delete_plan_id", "confirmation_ref", "expected_revision"})
        plan_id = self._ref(payload["delete_plan_id"], "delete_plan_id")
        confirmation = self._ref(payload["confirmation_ref"], "confirmation_ref")
        expected_revision = self._revision(payload["expected_revision"])
        fingerprint = self._fingerprint({"archive_id": archive_id, "delete_plan_id": plan_id, "confirmation_ref": confirmation, "expected_revision": expected_revision})
        now = self.store._clock()
        with self.store.write_transaction() as connection:
            existing = self._idempotency_get(connection, tenant, "archive_delete", key, fingerprint)
            if existing is not None:
                return self._validated("archive_delete", self._replay_response("archive_delete", existing))
            row = self._owned_row(connection, tenant, archive_id)
            if int(row["revision"]) != expected_revision:
                raise MediaArchiveError("invalid_state", "archive revision is stale", status=409)
            plan = connection.execute(
                "SELECT * FROM archive_delete_plans WHERE delete_plan_id = ? AND archive_id = ? AND tenant_id = ?",
                (plan_id, archive_id, tenant),
            ).fetchone()
            if plan is None or float(plan["expires_at"]) <= now or not confirmation:
                raise MediaArchiveError("invalid_delete_plan", "delete plan is invalid")
            refs = json.loads(str(row["artifacts_json"]))
            artifact_refs = [str(item["ref"]) for item in refs]
            projection_rows = connection.execute(
                "SELECT projection_id FROM archive_projections WHERE archive_id = ? ORDER BY projection_id", (archive_id,)
            ).fetchall()
            projection_refs = [str(item["projection_id"]) for item in projection_rows]
            connection.execute(
                "UPDATE archive_records SET state = 'deleting', revision = revision + 1, updated_at = ? WHERE archive_id = ? AND tenant_id = ? AND revision = ? AND state = 'active'",
                (now, archive_id, tenant, expected_revision),
            )
            receipt_ref = f"del_{archive_id}_{uuid.uuid4().hex}"
            connection.execute("DELETE FROM archive_records WHERE archive_id = ? AND tenant_id = ?", (archive_id, tenant))
            connection.execute("DELETE FROM archive_delete_plans WHERE archive_id = ? AND tenant_id = ?", (archive_id, tenant))
            connection.execute(
                "INSERT INTO archive_readback_receipts(readback_receipt_ref, archive_id, tenant_id, kind, artifact_refs_json, projection_refs_json, verified, db_present, attachments_present, projections_present, checked_at, created_at) VALUES (?, ?, ?, 'delete', ?, ?, 1, 0, 0, 0, ?, ?)",
                (receipt_ref, archive_id, tenant, self.store.json(artifact_refs), self.store.json(projection_refs), now, now),
            )
            response = {
                "archive_id": archive_id,
                "state": "deleted",
                "delete_receipt": {
                    "receipt_ref": receipt_ref,
                    "archive_id": archive_id,
                    "deleted_artifact_refs": artifact_refs,
                    "deleted_projection_refs": projection_refs,
                    "verified": True,
                    "hard_deleted": True,
                    "deleted_at": self._iso(now),
                },
                "hard_deleted": True,
            }
            self._idempotency_put(
                connection,
                tenant,
                "archive_delete",
                key,
                fingerprint,
                response,
                200,
                now,
                archive_id=archive_id,
            )
            return self._validated("archive_delete", response)

    def readback(self, tenant_id: str, archive_id: str, payload: Mapping[str, Any], *, idempotency_key: str) -> dict[str, Any]:
        tenant = self._tenant(tenant_id)
        key = self._key(idempotency_key)
        self._fields(payload, {"readback_receipt_ref", "observed_refs"}, {"readback_receipt_ref"})
        receipt_ref = self._ref(payload["readback_receipt_ref"], "readback_receipt_ref")
        observed = payload.get("observed_refs", [])
        if not isinstance(observed, list) or any(not isinstance(item, str) for item in observed):
            raise MediaArchiveError("readback_failed", "readback references are invalid")
        fingerprint = self._fingerprint({"archive_id": archive_id, "readback_receipt_ref": receipt_ref, "observed_refs": observed})
        now = self.store._clock()
        with self.store.write_transaction() as connection:
            existing = self._idempotency_get(connection, tenant, "archive_readback", key, fingerprint)
            if existing is not None:
                return self._validated("archive_readback", self._replay_readback(connection, tenant, existing))
            response = self._readback_response(connection, tenant, archive_id, receipt_ref, observed=observed)
            self._idempotency_put(
                connection,
                tenant,
                "archive_readback",
                key,
                fingerprint,
                response,
                200,
                now,
                archive_id=archive_id,
            )
            return self._validated("archive_readback", response)

    def delete_receipts(self, tenant_id: str, archive_id: str) -> list[dict[str, Any]]:
        tenant = self._tenant(tenant_id)
        with self.store.connect() as connection:
            rows = connection.execute(
                "SELECT readback_receipt_ref, archive_id, kind, verified FROM archive_readback_receipts WHERE tenant_id = ? AND archive_id = ? ORDER BY created_at, readback_receipt_ref",
                (tenant, archive_id),
            ).fetchall()
        return [dict(row) for row in rows]

    def _manifest(self, value: Any) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            raise MediaArchiveError("commit_rejected", "archive manifest is invalid")
        self._fields(value, {"manifest_id", "run_id", "confirmation_ref", "items", "created_at"}, {"manifest_id", "run_id", "confirmation_ref", "items", "created_at"})
        manifest = dict(value)
        manifest["manifest_id"] = self._ref(manifest["manifest_id"], "manifest_id")
        manifest["run_id"] = self._ref(manifest["run_id"], "run_id")
        manifest["confirmation_ref"] = self._ref(manifest["confirmation_ref"], "confirmation_ref")
        self._datetime(manifest["created_at"], "created_at")
        if not isinstance(manifest["items"], list) or not 1 <= len(manifest["items"]) <= _MAX_ITEMS:
            raise MediaArchiveError("commit_rejected", "archive manifest item count is invalid")
        return manifest

    def _artifacts(self, items: list[Any]) -> tuple[list[dict[str, Any]], list[str], int, int]:
        artifacts: list[dict[str, Any]] = []
        refs: list[str] = []
        total_bytes = 0
        cloud_bytes = 0
        for item in items:
            if not isinstance(item, Mapping):
                raise MediaArchiveError("commit_rejected", "archive artifact is invalid")
            self._fields(item, {"ref", "mode", "mime_type", "sha256", "size_bytes", "descriptor", "metadata", "content"}, {"ref", "mode", "mime_type", "sha256", "size_bytes", "descriptor", "metadata", "content"})
            artifact = dict(item)
            ref = self._ref(artifact["ref"], "artifact_ref")
            if ref in refs:
                raise MediaArchiveError("commit_rejected", "archive artifact references must be unique")
            refs.append(ref)
            mode = artifact["mode"]
            if not isinstance(mode, str) or mode not in _MODES:
                raise MediaArchiveError("invalid_mode", "archive mode is invalid")
            if not isinstance(artifact["mime_type"], str) or not artifact["mime_type"] or len(artifact["mime_type"]) > 128:
                raise MediaArchiveError("commit_rejected", "archive MIME type is invalid")
            if not _SHA256.fullmatch(artifact["sha256"] if isinstance(artifact["sha256"], str) else ""):
                raise MediaArchiveError("commit_rejected", "archive digest is invalid")
            if isinstance(artifact["size_bytes"], bool) or not isinstance(artifact["size_bytes"], int) or artifact["size_bytes"] < 0:
                raise MediaArchiveError("commit_rejected", "archive size is invalid")
            if not isinstance(artifact["descriptor"], bool):
                raise MediaArchiveError("commit_rejected", "archive descriptor flag is invalid")
            metadata = artifact["metadata"]
            if not isinstance(metadata, Mapping) or set(metadata) != {"name", "description", "source_ref"}:
                raise MediaArchiveError("commit_rejected", "archive metadata is invalid")
            if not isinstance(metadata["name"], str) or not isinstance(metadata["description"], (str, type(None))) or not isinstance(metadata["source_ref"], (str, type(None))):
                raise MediaArchiveError("commit_rejected", "archive metadata is invalid")
            if (
                len(metadata["name"]) > _MAX_METADATA_TEXT_CHARS
                or (
                    metadata["description"] is not None
                    and len(metadata["description"]) > _MAX_METADATA_TEXT_CHARS
                )
            ):
                raise MediaArchiveError("commit_rejected", "archive metadata is too long")
            if metadata["source_ref"] is not None:
                self._safe_local_ref(metadata["source_ref"], "source_ref")
            if mode == "content":
                if artifact["mime_type"] not in _CONTENT_MIMES or self._media_marker(ref, metadata):
                    raise MediaArchiveError("forbidden_media", "media content is not permitted")
                content = self._content(artifact["content"])
                decoded = self._decoded_content(content)
                self._verify_content(artifact, decoded)
                if len(decoded) > _MAX_ITEM_BYTES:
                    raise MediaArchiveError("commit_rejected", "archive item exceeds size limit")
                cloud_bytes += len(decoded)
            elif artifact["content"] is not None:
                raise MediaArchiveError("invalid_mode", f"{mode} archive items cannot carry content")
            else:
                artifact["content"] = None
            total_bytes += int(artifact["size_bytes"])
            artifact["metadata"] = dict(metadata)
            artifacts.append(artifact)
        return artifacts, refs, total_bytes, cloud_bytes

    @staticmethod
    def _content(value: Any) -> dict[str, str]:
        if not isinstance(value, Mapping) or set(value) != {"encoding", "value"}:
            raise MediaArchiveError("commit_rejected", "archive content is invalid")
        if value["encoding"] not in {"utf8", "base64"} or not isinstance(value["value"], str):
            raise MediaArchiveError("commit_rejected", "archive content is invalid")
        if len(value["value"]) > _MAX_CONTENT_VALUE_CHARS:
            raise MediaArchiveError("commit_rejected", "archive content is too long")
        return {"encoding": value["encoding"], "value": value["value"]}

    @staticmethod
    def _decoded_content(content: Mapping[str, str]) -> bytes:
        if len(content["value"]) > _MAX_CONTENT_VALUE_CHARS:
            raise MediaArchiveError("commit_rejected", "archive content is too long")
        if content["encoding"] == "utf8":
            try:
                return content["value"].encode("utf-8")
            except UnicodeError as exc:
                raise MediaArchiveError("content_decode_failed", "archive content could not be decoded") from exc
        try:
            return base64.b64decode(content["value"].encode("ascii"), validate=True)
        except (UnicodeEncodeError, binascii.Error, ValueError) as exc:
            raise MediaArchiveError("content_decode_failed", "archive content could not be decoded") from exc

    def _verify_content(self, artifact: Mapping[str, Any], decoded: bytes) -> None:
        if int(artifact["size_bytes"]) != len(decoded):
            raise MediaArchiveError("content_size_mismatch", "archive content size does not match")
        if hashlib.sha256(decoded).hexdigest() != artifact["sha256"]:
            raise MediaArchiveError("content_hash_mismatch", "archive content digest does not match")
        if self._looks_like_media(decoded):
            raise MediaArchiveError("forbidden_media", "media content is not permitted")
        try:
            text = decoded.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise MediaArchiveError("content_magic_mismatch", "archive content MIME does not match") from exc
        if any(ord(character) == 0 for character in text):
            raise MediaArchiveError("forbidden_media", "media content is not permitted")
        if artifact["mime_type"] == "application/json":
            try:
                json.loads(text)
            except json.JSONDecodeError as exc:
                raise MediaArchiveError("content_magic_mismatch", "archive content MIME does not match") from exc

    @staticmethod
    def _looks_like_media(value: bytes) -> bool:
        signatures = (b"\x89PNG", b"\xff\xd8\xff", b"GIF8", b"RIFF", b"ID3", b"OggS", b"fLaC", b"%PDF", b"PK\x03\x04")
        return value.startswith(signatures) or (len(value) >= 12 and value[4:8] == b"ftyp")

    @staticmethod
    def _media_marker(ref: str, metadata: Mapping[str, Any]) -> bool:
        values = [ref, str(metadata["name"])]
        if metadata["source_ref"] is not None:
            values.append(str(metadata["source_ref"]))
        return any(_MEDIA_MARKER.search(value) is not None for value in values)

    @staticmethod
    def _safe_local_ref(value: str, field: str) -> None:
        if not value or len(value) > 500 or "\x00" in value or value.startswith(("/", "\\", "~", "file:")) or re.match(r"^[A-Za-z]:[\\/]", value):
            raise MediaArchiveError("commit_rejected", f"{field} is invalid")

    @classmethod
    def _ref(cls, value: Any, field: str) -> str:
        if not isinstance(value, str) or not _REF.fullmatch(value):
            raise MediaArchiveError("commit_rejected", f"{field} is invalid")
        cls._safe_local_ref(value, field)
        return value

    @staticmethod
    def _revision(value: Any) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise MediaArchiveError("invalid_request", "revision is invalid")
        return value

    @staticmethod
    def _datetime(value: Any, field: str) -> None:
        if not isinstance(value, str) or len(value) > _MAX_DATETIME_CHARS:
            raise MediaArchiveError("commit_rejected", f"{field} is invalid")
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise MediaArchiveError("commit_rejected", f"{field} is invalid") from exc
        if parsed.tzinfo is None:
            raise MediaArchiveError("commit_rejected", f"{field} is invalid")

    @staticmethod
    def _tenant(value: Any) -> str:
        if not isinstance(value, str):
            raise MediaArchiveError("forbidden", "tenant is invalid", status=403)
        try:
            normalized = str(uuid.UUID(value))
        except ValueError as exc:
            raise MediaArchiveError("forbidden", "tenant is invalid", status=403) from exc
        if normalized != value:
            raise MediaArchiveError("forbidden", "tenant is invalid", status=403)
        return normalized

    @staticmethod
    def _key(value: Any) -> str:
        if not isinstance(value, str) or not _KEY.fullmatch(value):
            raise MediaArchiveError("invalid_request", "idempotency key is invalid")
        return value

    @staticmethod
    def _fields(payload: Mapping[str, Any], allowed: set[str], required: set[str]) -> None:
        if not isinstance(payload, Mapping) or set(payload) - allowed or not required.issubset(payload):
            raise MediaArchiveError("commit_rejected", "archive request fields are invalid")

    def _owned_row(self, connection: Any, tenant: str, archive_id: str) -> Any:
        row = connection.execute(
            "SELECT * FROM archive_records WHERE tenant_id = ? AND archive_id = ?", (tenant, archive_id)
        ).fetchone()
        if row is None:
            raise MediaArchiveError("not_found", "archive was not found", status=404)
        return row

    def _project_row(self, connection: Any, row: Any) -> dict[str, Any]:
        projection_rows = connection.execute(
            "SELECT projection_id, kind, ref, artifact_refs_json, consistent FROM archive_projections WHERE archive_id = ? ORDER BY projection_id",
            (row["archive_id"],),
        ).fetchall()
        projections = [
            {
                "projection_id": str(item["projection_id"]),
                "kind": str(item["kind"]),
                "ref": str(item["ref"]),
                "artifact_refs": json.loads(str(item["artifact_refs_json"])),
                "consistent": bool(item["consistent"]),
            }
            for item in projection_rows
        ]
        return self.store.row_projection(row, projections=projections, iso=self._iso)

    def _commit_response(self, connection: Any, tenant: str, archive_id: str, receipt_ref: str) -> dict[str, Any]:
        row = self._owned_row(connection, tenant, archive_id)
        commit = connection.execute(
            "SELECT * FROM archive_commits WHERE archive_id = ? AND tenant_id = ? AND commit_id = ?",
            (archive_id, tenant, row["commit_id"]),
        ).fetchone()
        receipt = connection.execute(
            "SELECT * FROM archive_readback_receipts WHERE readback_receipt_ref = ? AND archive_id = ? AND tenant_id = ? AND kind = 'commit'",
            (receipt_ref, archive_id, tenant),
        ).fetchone()
        if commit is None or receipt is None or commit["committed_at"] is None:
            raise MediaArchiveError("internal_error", "archive commit replay metadata is invalid", status=500)
        return {
            "archive": self._project_row(connection, row),
            "commit_receipt": {
                "commit_id": str(commit["commit_id"]),
                "manifest_id": str(commit["manifest_id"]),
                "archive_id": archive_id,
                "artifact_refs": json.loads(str(commit["artifact_refs_json"])),
                "total_bytes": int(commit["total_bytes"]),
                "cloud_bytes": int(commit["cloud_bytes"]),
                "media_cloud_bytes": int(commit["media_cloud_bytes"]),
                "committed_at": self._iso(float(commit["committed_at"])),
            },
            "readback_receipt": self._readback_receipt(
                str(receipt["readback_receipt_ref"]),
                archive_id,
                bool(receipt["verified"]),
                bool(receipt["db_present"]),
                bool(receipt["attachments_present"]),
                bool(receipt["projections_present"]),
                float(receipt["checked_at"]),
            ),
        }

    def _readback_response(
        self,
        connection: Any,
        tenant: str,
        archive_id: str,
        receipt_ref: str,
        *,
        observed: list[str] | None = None,
    ) -> dict[str, Any]:
        receipt = connection.execute(
            "SELECT * FROM archive_readback_receipts WHERE readback_receipt_ref = ? AND archive_id = ? AND tenant_id = ?",
            (receipt_ref, archive_id, tenant),
        ).fetchone()
        if receipt is None:
            raise MediaArchiveError("not_found", "archive readback was not found", status=404)
        expected_refs = json.loads(str(receipt["artifact_refs_json"]))
        if observed and sorted(observed) != sorted(expected_refs):
            raise MediaArchiveError("readback_failed", "archive readback did not verify")
        row = connection.execute(
            "SELECT * FROM archive_records WHERE archive_id = ? AND tenant_id = ?", (archive_id, tenant)
        ).fetchone()
        if row is None:
            return {
                "archive": None,
                "verified": True,
                "readback_receipt": self._readback_receipt(
                    receipt_ref,
                    archive_id,
                    True,
                    False,
                    False,
                    False,
                    float(receipt["checked_at"]),
                ),
                "hard_deleted": True,
            }
        attachment_count = connection.execute(
            "SELECT COUNT(*) FROM archive_attachments WHERE archive_id = ?", (archive_id,)
        ).fetchone()[0]
        projection_count = connection.execute(
            "SELECT COUNT(*) FROM archive_projections WHERE archive_id = ?", (archive_id,)
        ).fetchone()[0]
        expected_projections = json.loads(str(receipt["projection_refs_json"]))
        verified = (
            receipt["kind"] == "commit"
            and int(receipt["verified"]) == 1
            and int(attachment_count) == len(expected_refs)
            and int(projection_count) == len(expected_projections)
        )
        if not verified:
            raise MediaArchiveError("readback_failed", "archive readback did not verify")
        return {
            "archive": self._project_row(connection, row),
            "verified": True,
            "readback_receipt": self._readback_receipt(
                receipt_ref,
                archive_id,
                True,
                True,
                True,
                True,
                float(receipt["checked_at"]),
            ),
            "hard_deleted": False,
        }

    def _insert_projections(self, connection: Any, archive_id: str, refs: list[str]) -> list[str]:
        projection_refs: list[str] = []
        db_id = f"prj_{archive_id}_db"
        connection.execute(
            "INSERT INTO archive_projections(projection_id, archive_id, kind, ref, artifact_refs_json, consistent) VALUES (?, ?, 'db', ?, ?, 1)",
            (db_id, archive_id, f"archive:{archive_id}", self.store.json(refs)),
        )
        projection_refs.append(db_id)
        for index, ref in enumerate(refs):
            projection_id = f"prj_{archive_id}_att_{index}"
            connection.execute(
                "INSERT INTO archive_projections(projection_id, archive_id, kind, ref, artifact_refs_json, consistent) VALUES (?, ?, 'attachment', ?, ?, 1)",
                (projection_id, archive_id, f"attachment:{archive_id}:{index}", self.store.json([ref])),
            )
            projection_refs.append(projection_id)
        return projection_refs

    @staticmethod
    def _readback_receipt(receipt_ref: str, archive_id: str, verified: bool, db: bool, attachments: bool, projections: bool, now: float) -> dict[str, Any]:
        return {
            "receipt_ref": receipt_ref,
            "archive_id": archive_id,
            "verified": verified,
            "db_present": db,
            "attachments_present": attachments,
            "projections_present": projections,
            "checked_at": datetime.fromtimestamp(now, timezone.utc).isoformat().replace("+00:00", "Z"),
        }

    def _validated(self, operation_id: str, response: dict[str, Any]) -> dict[str, Any]:
        validate_r1_response(operation_id, response)
        return response

    @staticmethod
    def _fingerprint(payload: Mapping[str, Any]) -> str:
        return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()

    @staticmethod
    def _iso(value: float) -> str:
        return datetime.fromtimestamp(value, timezone.utc).isoformat().replace("+00:00", "Z")

    def _replay_response(self, operation: str, row: Mapping[str, Any]) -> dict[str, Any]:
        if row["replay_kind"] != "response":
            raise MediaArchiveError("internal_error", f"{operation} idempotency metadata is invalid", status=500)
        try:
            response = json.loads(str(row["response_json"]))
        except (TypeError, json.JSONDecodeError) as exc:
            raise MediaArchiveError("internal_error", f"{operation} idempotency metadata is invalid", status=500) from exc
        if not isinstance(response, dict):
            raise MediaArchiveError("internal_error", f"{operation} idempotency metadata is invalid", status=500)
        return response

    def _replay_reference(self, operation: str, row: Mapping[str, Any]) -> tuple[str, str]:
        if row["replay_kind"] != operation:
            raise MediaArchiveError("internal_error", f"{operation} idempotency metadata is invalid", status=500)
        try:
            metadata = json.loads(str(row["response_json"]))
        except (TypeError, json.JSONDecodeError) as exc:
            raise MediaArchiveError("internal_error", f"{operation} idempotency metadata is invalid", status=500) from exc
        if not isinstance(metadata, dict) or set(metadata) != {"archive_id", "receipt_ref"}:
            raise MediaArchiveError("internal_error", f"{operation} idempotency metadata is invalid", status=500)
        archive_id = row["archive_id"]
        if not isinstance(archive_id, str) or archive_id != metadata["archive_id"]:
            raise MediaArchiveError("internal_error", f"{operation} idempotency metadata is invalid", status=500)
        receipt_ref = metadata["receipt_ref"]
        if not isinstance(receipt_ref, str):
            raise MediaArchiveError("internal_error", f"{operation} idempotency metadata is invalid", status=500)
        return archive_id, receipt_ref

    def _replay_commit(self, connection: Any, tenant: str, row: Mapping[str, Any]) -> dict[str, Any]:
        archive_id, receipt_ref = self._replay_reference("archive_commit", row)
        return self._commit_response(connection, tenant, archive_id, receipt_ref)

    def _replay_readback(self, connection: Any, tenant: str, row: Mapping[str, Any]) -> dict[str, Any]:
        archive_id, receipt_ref = self._replay_reference("archive_readback", row)
        return self._readback_response(connection, tenant, archive_id, receipt_ref)

    @staticmethod
    def _idempotency_get(connection: Any, tenant: str, operation: str, key: str, fingerprint: str) -> Any:
        row = connection.execute(
            "SELECT * FROM archive_idempotency WHERE scope = ? AND operation_id = ? AND idempotency_key = ?",
            (f"tenant:{tenant}", operation, key),
        ).fetchone()
        if row is None:
            return None
        if row["request_fingerprint"] != fingerprint:
            raise MediaArchiveError("idempotency_conflict", "idempotency key is bound to another request", status=409)
        return row

    @staticmethod
    def _idempotency_put(
        connection: Any,
        tenant: str,
        operation: str,
        key: str,
        fingerprint: str,
        response: Mapping[str, Any],
        status: int,
        now: float,
        *,
        archive_id: str | None = None,
    ) -> None:
        if operation in {"archive_commit", "archive_readback"}:
            if archive_id is None:
                raise RuntimeError("archive idempotency references require an archive id")
            receipt = response.get("readback_receipt")
            if not isinstance(receipt, Mapping) or not isinstance(receipt.get("receipt_ref"), str):
                raise RuntimeError("archive idempotency references require a receipt")
            replay_kind = operation
            stored_response: Mapping[str, Any] = {
                "archive_id": archive_id,
                "receipt_ref": receipt["receipt_ref"],
            }
        else:
            replay_kind = "response"
            stored_response = response
        connection.execute(
            "INSERT INTO archive_idempotency(scope, operation_id, idempotency_key, request_fingerprint, archive_id, replay_kind, response_json, status_code, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                f"tenant:{tenant}",
                operation,
                key,
                fingerprint,
                archive_id,
                replay_kind,
                json.dumps(stored_response, ensure_ascii=False, separators=(",", ":")),
                status,
                now,
            ),
        )


__all__ = [
    "ARCHIVE_HTTP_BODY_MAXIMUM_BYTES",
    "ARCHIVE_OPERATION_IDS",
    "MediaArchiveError",
    "MediaArchiveService",
    "MediaArchiveStore",
    "resolve_archive_operation",
]
