from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping


def _tenant_dir(root: Path, category: str, tenant_id: str) -> Path:
    return root / category / hashlib.sha256(tenant_id.encode("utf-8")).hexdigest()


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
        temporary_path = Path(handle.name)
    os.replace(temporary_path, path)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    _atomic_write(path, json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")


def _write_jsonl(path: Path, entries: list[Mapping[str, Any]]) -> None:
    _atomic_write(
        path,
        "".join(json.dumps(entry, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n" for entry in entries),
    )


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"invalid migration source: {path}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"migration source must be an object: {path}")
    return payload


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"invalid migration source: {path}") from exc
        if not isinstance(entry, dict):
            raise RuntimeError(f"migration source must contain objects: {path}")
        entries.append(entry)
    return entries


def _owner(payload: Mapping[str, Any]) -> str:
    return str(payload.get("principal") or payload.get("actor") or "").strip()


def _tenant_payload(payload: Mapping[str, Any], tenant_id: str, *, strip_actor: bool = False) -> dict[str, Any]:
    migrated = dict(payload)
    migrated.pop("principal", None)
    if strip_actor:
        migrated.pop("actor", None)
    migrated["tenant_id"] = tenant_id
    return migrated


def _same_identity(existing: Mapping[str, Any], candidate: Mapping[str, Any], identity: str) -> bool:
    return existing.get("tenant_id") == candidate.get("tenant_id") and existing.get(identity) == candidate.get(identity)


def _move_json(source: Path, target: Path, payload: Mapping[str, Any], identity: str) -> bool:
    if target.exists():
        if not _same_identity(_read_json(target), payload, identity):
            raise RuntimeError(f"migration target conflict: {target}")
        source.unlink(missing_ok=True)
        return False
    _write_json(target, payload)
    source.unlink()
    return True


def _move_jsonl(source: Path, target: Path, entries: list[Mapping[str, Any]]) -> None:
    if target.exists():
        existing = _read_jsonl(target)
        if existing != entries:
            raise RuntimeError(f"migration target conflict: {target}")
        source.unlink(missing_ok=True)
        return
    _write_jsonl(target, entries)
    source.unlink()


def _archive(root: Path, category: str, source: Path) -> None:
    target = root / "migration_archive" / "orphaned" / category / source.name
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if target.read_bytes() != source.read_bytes():
            raise RuntimeError(f"migration archive conflict: {target}")
        source.unlink(missing_ok=True)
        return
    os.replace(source, target)


def _move_upload_binary(source: Path, target: Path) -> None:
    if target.exists():
        if source.exists() and source.read_bytes() != target.read_bytes():
            raise RuntimeError(f"migration upload conflict: {target}")
        source.unlink(missing_ok=True)
        return
    if not source.exists():
        raise RuntimeError(f"missing legacy upload binary: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    os.replace(source, target)


def migrate(root: Path, principal_to_tenant: Mapping[str, str]) -> dict[str, int]:
    root = Path(root).resolve()
    owners = {
        str(principal).strip(): str(tenant_id).strip()
        for principal, tenant_id in principal_to_tenant.items()
        if str(principal).strip() and str(tenant_id).strip()
    }
    counts = {"tasks": 0, "uploads": 0, "audit": 0, "orphaned": 0}
    tasks_dir = root / "tasks"
    events_dir = root / "events"
    uploads_dir = root / "uploads"

    for source in sorted(tasks_dir.glob("*.json")):
        task = _read_json(source)
        task_id = str(task.get("task_id") or source.stem)
        tenant_id = owners.get(_owner(task))
        event_source = events_dir / f"{task_id}.jsonl"
        if not tenant_id:
            _archive(root, "tasks", source)
            if event_source.exists():
                _archive(root, "events", event_source)
            counts["orphaned"] += 1
            continue
        migrated = _tenant_payload(task, tenant_id)
        migrated["task_id"] = task_id
        target = _tenant_dir(root, "tasks", tenant_id) / f"{task_id}.json"
        if _move_json(source, target, migrated, "task_id"):
            counts["tasks"] += 1
        if event_source.exists():
            migrated_events = [_tenant_payload(event, tenant_id) for event in _read_jsonl(event_source)]
            _move_jsonl(event_source, _tenant_dir(root, "events", tenant_id) / f"{task_id}.jsonl", migrated_events)

    for source in sorted(events_dir.glob("*.jsonl")):
        _archive(root, "events", source)
        counts["orphaned"] += 1

    for source in sorted(uploads_dir.glob("*.json")):
        upload = _read_json(source)
        upload_id = str(upload.get("upload_id") or source.stem)
        tenant_id = owners.get(_owner(upload))
        if not tenant_id:
            storage_path = str(upload.get("storage_path") or "")
            if storage_path:
                binary = Path(storage_path)
                if not binary.is_absolute():
                    binary = root / binary
                binary = binary.resolve()
                if binary.exists():
                    _archive(root, "uploads", binary)
            _archive(root, "uploads", source)
            counts["orphaned"] += 1
            continue
        storage_path = str(upload.get("storage_path") or "")
        migrated = _tenant_payload(upload, tenant_id)
        target_dir = _tenant_dir(root, "uploads", tenant_id)
        if storage_path:
            binary = Path(storage_path)
            if not binary.is_absolute():
                binary = root / binary
            binary = binary.resolve()
            try:
                binary.relative_to(uploads_dir)
            except ValueError as exc:
                raise RuntimeError(f"legacy upload path escapes uploads directory: {binary}") from exc
            target_binary = target_dir / f"{upload_id}{binary.suffix or '.bin'}"
            _move_upload_binary(binary, target_binary)
            migrated["storage_path"] = str(target_binary)
        else:
            migrated["storage_path"] = ""
        migrated["upload_id"] = upload_id
        target = target_dir / f"{upload_id}.json"
        if _move_json(source, target, migrated, "upload_id"):
            counts["uploads"] += 1

    audit_source = root / "audit.jsonl"
    if audit_source.exists():
        grouped: dict[str, list[dict[str, Any]]] = {}
        orphaned: list[dict[str, Any]] = []
        for entry in _read_jsonl(audit_source):
            tenant_id = owners.get(_owner(entry))
            if tenant_id:
                grouped.setdefault(tenant_id, []).append(_tenant_payload(entry, tenant_id, strip_actor=True))
            else:
                orphaned.append(entry)
        for tenant_id, entries in grouped.items():
            target = root / "audit" / f"{hashlib.sha256(tenant_id.encode('utf-8')).hexdigest()}.jsonl"
            existing = _read_jsonl(target) if target.exists() else []
            existing_signatures = {json.dumps(entry, ensure_ascii=False, sort_keys=True) for entry in existing}
            additions = [entry for entry in entries if json.dumps(entry, ensure_ascii=False, sort_keys=True) not in existing_signatures]
            if additions:
                _write_jsonl(target, [*existing, *additions])
                counts["audit"] += len(additions)
        if orphaned:
            _write_jsonl(root / "migration_archive" / "orphaned" / "audit.jsonl", orphaned)
            counts["orphaned"] += len(orphaned)
        audit_source.unlink()

    return counts
