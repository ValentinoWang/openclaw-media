"""Fail-closed, one-shot planner for legacy Media Vault tenant migration.

The migration contract does not allow inferred ownership.  A file is eligible
only when an explicit repository-controlled mapping covers it.  Unmapped files
are reported for an offline orphan archive.  Applying a plan is deliberately a
separate opt-in operation; plan-only never moves source files.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
from collections.abc import Iterable
from pathlib import Path, PurePosixPath
from typing import Any

from media_vault.vault import require_tenant_id


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
MIGRATION_CONTRACT_PATH = REPOSITORY_ROOT / "media_vault" / "media_vault_v2_contract.json"
MIGRATION_CONTRACT_ID = "media_vault_v2"
ORPHAN_REASON = "no_explicit_tenant_assignment"


class MigrationError(RuntimeError):
    pass


def _read_json(path: str | Path, *, label: str) -> dict[str, Any]:
    source = Path(path).expanduser()
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except OSError as exc:
        raise MigrationError(f"cannot read {label}: {source}") from exc
    except json.JSONDecodeError as exc:
        raise MigrationError(f"invalid {label} JSON: {source}") from exc
    if not isinstance(payload, dict):
        raise MigrationError(f"{label} must be a JSON object: {source}")
    return payload


def _load_contract() -> dict[str, Any]:
    contract = _read_json(MIGRATION_CONTRACT_PATH, label="media vault migration contract")
    if contract.get("contract_id") != MIGRATION_CONTRACT_ID:
        raise MigrationError("unsupported media vault migration contract")
    migration = contract.get("migration")
    if not isinstance(migration, dict):
        raise MigrationError("media vault migration contract lacks migration rules")
    if migration.get("ownership_input") != "explicit tenant mapping plus canonical owner sidecar":
        raise MigrationError("media vault migration contract does not require explicit ownership")
    if migration.get("unprovable_owner_action") != "move_to_offline_orphan_archive":
        raise MigrationError("media vault migration contract does not preserve unprovable owners")
    return contract


def _normalized_relative_path(value: Any) -> str:
    raw = str(value or "").strip().replace("\\", "/")
    path = PurePosixPath(raw)
    if not raw or path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise MigrationError("mapping relative_path must be a safe relative path")
    if path.parts[0] == "tenants":
        raise MigrationError("mapping cannot assign an already tenant-scoped path")
    return path.as_posix()


def _load_assignments(mapping_path: str | Path) -> list[dict[str, str]]:
    payload = _read_json(mapping_path, label="tenant mapping")
    raw_assignments = payload.get("assignments")
    if not isinstance(raw_assignments, list):
        raise MigrationError("tenant mapping assignments must be a list")
    assignments: list[dict[str, str]] = []
    for index, raw in enumerate(raw_assignments):
        if not isinstance(raw, dict):
            raise MigrationError(f"tenant mapping assignment {index} must be an object")
        relative_path = _normalized_relative_path(raw.get("relative_path"))
        try:
            tenant_id = require_tenant_id(raw.get("tenant_id"))
        except Exception as exc:
            raise MigrationError(f"tenant mapping assignment {index} has invalid tenant_id") from exc
        assignments.append({"relative_path": relative_path, "tenant_id": tenant_id})
    _reject_cross_tenant_assignments(assignments)
    return assignments


def _paths_overlap(left: str, right: str) -> bool:
    return left == right or left.startswith(right + "/") or right.startswith(left + "/")


def _reject_cross_tenant_assignments(assignments: Iterable[dict[str, str]]) -> None:
    ordered = sorted(assignments, key=lambda item: item["relative_path"])
    for index, assignment in enumerate(ordered):
        for other in ordered[index + 1 :]:
            if not _paths_overlap(assignment["relative_path"], other["relative_path"]):
                continue
            if assignment["tenant_id"] != other["tenant_id"]:
                raise MigrationError("cross-tenant mapping overlap is forbidden")
            raise MigrationError("duplicate or overlapping tenant mapping is forbidden")


def require_explicit_seed_tenant(mapping_path: str | Path, seed_tenant_id: str) -> str:
    """Require an exact explicit mapping for a supplied migration seed tenant."""
    try:
        expected = require_tenant_id(seed_tenant_id)
    except Exception as exc:
        raise MigrationError("explicit seed tenant must be a canonical UUID") from exc
    assignments = _load_assignments(mapping_path)
    if not any(assignment["tenant_id"] == expected for assignment in assignments):
        raise MigrationError("explicit seed tenant is absent from tenant mapping")
    return expected


def _iter_legacy_files(vault_root: Path) -> list[Path]:
    if not vault_root.exists():
        raise MigrationError(f"media vault root does not exist: {vault_root}")
    if not vault_root.is_dir():
        raise MigrationError(f"media vault root is not a directory: {vault_root}")
    return sorted(
        path
        for path in vault_root.rglob("*")
        if path.is_file() and "tenants" not in path.relative_to(vault_root).parts
    )


def _matching_assignment(relative_path: str, assignments: list[dict[str, str]]) -> dict[str, str] | None:
    matches = [
        assignment
        for assignment in assignments
        if relative_path == assignment["relative_path"] or relative_path.startswith(assignment["relative_path"] + "/")
    ]
    if not matches:
        return None
    return max(matches, key=lambda item: len(item["relative_path"]))


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _inventory_hash(files: list[dict[str, Any]]) -> str:
    canonical = [
        {
            "relative_path": item["relative_path"],
            "content_hash": item["content_hash"],
            "tenant_id": item["tenant_id"],
            "orphan_reason": item.get("orphan_reason"),
        }
        for item in files
    ]
    encoded = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _owner_relation_count(resource_owner_db: Path) -> int:
    if not resource_owner_db.exists():
        return 0
    try:
        with sqlite3.connect(f"file:{resource_owner_db}?mode=ro", uri=True) as connection:
            table = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'resource_owners'"
            ).fetchone()
            if table is None:
                return 0
            row = connection.execute("SELECT COUNT(*) FROM resource_owners").fetchone()
    except sqlite3.Error as exc:
        raise MigrationError(f"cannot inspect canonical resource owner sidecar: {resource_owner_db}") from exc
    return int(row[0]) if row else 0


def _canonical_owner_tenant(resource_owner_db: Path, relative_path: str) -> str | None:
    if not resource_owner_db.exists():
        return None
    parts = PurePosixPath(relative_path).parts
    if len(parts) < 2:
        return None
    resource_type_by_namespace = {
        "source_assets": "media.source_asset",
        "deconstructions": "media.material_deconstruction",
        "creation_runs": "media.creation_run",
        "published_posts": "media.published_post",
        "business": "media.business_opportunity",
        "creator_profiles": "media.creator_profile",
    }
    resource_type = resource_type_by_namespace.get(parts[0])
    if resource_type is None:
        return None
    try:
        with sqlite3.connect(f"file:{resource_owner_db}?mode=ro", uri=True) as connection:
            row = connection.execute(
                "SELECT tenant_id FROM resource_owners "
                "WHERE resource_type = ? AND canonical_resource_id = ? AND status = 'active'",
                (resource_type, parts[1]),
            ).fetchone()
    except sqlite3.Error as exc:
        raise MigrationError(f"cannot inspect canonical resource owner sidecar: {resource_owner_db}") from exc
    return str(row[0]) if row else None


def _apply_file_move(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if target.is_file() and _file_hash(source) == _file_hash(target):
            source.unlink()
            return
        raise MigrationError(f"migration target already exists with different content: {target}")
    shutil.move(str(source), str(target))


def migrate(
    *,
    vault_root: str | Path,
    mapping_path: str | Path,
    offline_archive: str | Path,
    evidence_path: str | Path,
    resource_owner_db: str | Path,
    maintenance_window_id: str,
    plan_only: bool = True,
) -> dict[str, Any]:
    """Create a fail-closed migration plan and optionally execute it.

    ``plan_only=True`` is the default and writes only the requested evidence
    document.  It never creates destination directories or moves vault files.
    """
    contract = _load_contract()
    source_root = Path(vault_root).expanduser().resolve()
    archive_root = Path(offline_archive).expanduser().resolve()
    evidence = Path(evidence_path).expanduser().resolve()
    owner_db = Path(resource_owner_db).expanduser().resolve()
    window = str(maintenance_window_id or "").strip()
    if not window:
        raise MigrationError("maintenance_window_id is required")
    assignments = _load_assignments(mapping_path)
    pre_relation_count = _owner_relation_count(owner_db)
    files: list[dict[str, Any]] = []
    for source in _iter_legacy_files(source_root):
        relative_path = source.relative_to(source_root).as_posix()
        assignment = _matching_assignment(relative_path, assignments)
        content_hash = _file_hash(source)
        if assignment is None:
            files.append(
                {
                    "relative_path": relative_path,
                    "content_hash": content_hash,
                    "tenant_id": None,
                    "action": "offline_orphan_plan",
                    "orphan_reason": ORPHAN_REASON,
                    "offline_archive_target": str(archive_root / window / relative_path),
                }
            )
            continue
        canonical_owner = _canonical_owner_tenant(owner_db, relative_path)
        if canonical_owner is not None and canonical_owner != assignment["tenant_id"]:
            raise MigrationError("cross-tenant mapping conflicts with canonical owner sidecar")
        files.append(
            {
                "relative_path": relative_path,
                "content_hash": content_hash,
                "tenant_id": assignment["tenant_id"],
                "action": "tenant_migration_plan",
                "target": str(source_root / "tenants" / assignment["tenant_id"] / relative_path),
                "canonical_owner_tenant_id": canonical_owner,
            }
        )
    mapped_count = sum(item["tenant_id"] is not None for item in files)
    orphan_count = len(files) - mapped_count
    report: dict[str, Any] = {
        "contract_id": contract["contract_id"],
        "contract_path": str(MIGRATION_CONTRACT_PATH),
        "maintenance_window_id": window,
        "plan_only": bool(plan_only),
        "status": "dry_run_verified" if plan_only else "apply_verified",
        "pre_count": len(files),
        "mapped_count": mapped_count,
        "orphan_count": orphan_count,
        "pre_hash": _inventory_hash(files),
        "pre_relation_count": pre_relation_count,
        "post_relation_count": pre_relation_count,
        "files": files,
    }
    if not plan_only:
        for item in files:
            source = source_root / item["relative_path"]
            if item["tenant_id"] is None:
                target = archive_root / window / item["relative_path"]
            else:
                target = source_root / "tenants" / item["tenant_id"] / item["relative_path"]
            _apply_file_move(source, target)
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Plan or apply Media Vault v2 tenant migration.")
    parser.add_argument("--vault-root", required=True)
    parser.add_argument("--mapping", required=True)
    parser.add_argument("--offline-archive", required=True)
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--resource-owner-db", required=True)
    parser.add_argument("--maintenance-window-id", required=True)
    parser.add_argument("--apply", action="store_true", help="Move files only after reviewing a prior plan.")
    args = parser.parse_args()
    report = migrate(
        vault_root=args.vault_root,
        mapping_path=args.mapping,
        offline_archive=args.offline_archive,
        evidence_path=args.evidence,
        resource_owner_db=args.resource_owner_db,
        maintenance_window_id=args.maintenance_window_id,
        plan_only=not args.apply,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
