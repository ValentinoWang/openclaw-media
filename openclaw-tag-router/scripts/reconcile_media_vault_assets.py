#!/usr/bin/env python3
"""Backfill verified MediaVault source manifests into media_product.assets."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from media_model.platform_hashtags import (
    normalize_platform_hashtags,
    resolve_platform_hashtags,
)
from openclaw_app.account import AccountDatabase, AccountDatabaseSettings
from openclaw_app.services.media_business.source_asset_projection import (
    SourceAssetInput,
    canonicalize_source_asset,
)
from openclaw_app.services.resource_owner_registry import (
    ResourceOwnerConflict,
    ResourceOwnerRegistry,
)

ASSET_ID = re.compile(r"^[A-Za-z0-9_-]{8,160}$")
SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
SOURCE_FIELDS = (
    "source_record_id",
    "platform",
    "source_url",
    "title",
    "platform_hashtags",
    "captured_at",
    "deconstruct_doc_url",
    "source_asset_id",
    "qa",
)
URL_FIELDS = {"source_url", "deconstruct_doc_url"}
MAX_SOURCE_TEXT_BYTES = 2 * 1024 * 1024


class ReconciliationError(ValueError):
    """A source manifest cannot be safely projected."""


@dataclass(frozen=True)
class OperatorScope:
    operator_id: str
    scope: str
    audit_reason: str | None = None

    def validate(self) -> None:
        if not self.operator_id.strip() or len(self.operator_id.strip()) > 254:
            raise ReconciliationError("operator_id is required and must be <= 254 characters")
        if self.scope not in {"tenant", "admin"}:
            raise ReconciliationError("operator_scope must be tenant or admin")
        if self.scope == "admin" and not str(self.audit_reason or "").strip():
            raise ReconciliationError("admin scope requires an audit_reason")


@dataclass(frozen=True)
class AssetCandidate:
    public_id: str
    source_version: str
    canonical_data: dict[str, Any]
    path: str


def _tenant(value: str) -> str:
    text = str(value or "").strip()
    try:
        canonical = str(uuid.UUID(text))
    except ValueError as exc:
        raise ReconciliationError("tenant_id must be a canonical UUID") from exc
    if canonical != text:
        raise ReconciliationError("tenant_id must be a canonical UUID")
    return canonical


def _json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReconciliationError(f"{label} is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ReconciliationError(f"{label} must be a JSON object")
    return value


def _uri(tenant_id: str, tenant_root: Path, path: Path) -> str:
    relative = path.resolve().relative_to(tenant_root.resolve())
    return f"media://tenants/{tenant_id}/{'/'.join(quote(part, safe='') for part in relative.parts)}"


def _tenant_root(vault_root: Path, tenant_id: str) -> Path:
    root = vault_root.expanduser().resolve()
    tenant_root = (root / "tenants" / tenant_id).resolve()
    try:
        tenant_root.relative_to((root / "tenants").resolve())
    except ValueError as exc:
        raise ReconciliationError("tenant root escapes vault root") from exc
    manifest = _json(tenant_root / "manifest" / "media_vault_manifest.json", "MediaVault manifest")
    if manifest.get("version") != "media_vault_v2":
        raise ReconciliationError("MediaVault manifest must be media_vault_v2")
    if manifest.get("tenant_id") != tenant_id:
        raise ReconciliationError("MediaVault manifest tenant mismatch")
    if Path(str(manifest.get("root") or "")).expanduser().resolve() != tenant_root:
        raise ReconciliationError("MediaVault manifest root mismatch")
    return tenant_root


def _fields(manifest: dict[str, Any], asset_id: str) -> dict[str, Any]:
    projected: dict[str, Any] = {"asset_id": asset_id}
    for key in SOURCE_FIELDS:
        if key not in manifest or manifest[key] is None:
            continue
        value = manifest[key]
        if value in (None, ""):
            continue
        if key == "platform_hashtags":
            value = normalize_platform_hashtags(value)
            if not value:
                continue
        elif key == "qa":
            if not isinstance(value, bool):
                raise ReconciliationError("qa must be boolean")
        elif key in URL_FIELDS:
            if not isinstance(value, str) or not value.strip().startswith("https://"):
                raise ReconciliationError(f"{key} must be an HTTPS URL")
            value = value.strip()
        elif key == "captured_at":
            if not isinstance(value, (str, int, float)) or isinstance(value, bool):
                raise ReconciliationError("captured_at must be a scalar timestamp")
        else:
            if not isinstance(value, str) or not value.strip():
                raise ReconciliationError(f"{key} must be a non-empty string")
            value = value.strip()
        projected[key] = value
    return projected


def _captured_source_text(manifest_path: Path) -> str:
    source_text_path = manifest_path.parent / "original" / "source_text.md"
    if not source_text_path.exists():
        return ""
    if source_text_path.is_symlink() or not source_text_path.is_file():
        raise ReconciliationError("captured source text must be a regular file")
    if source_text_path.stat().st_size > MAX_SOURCE_TEXT_BYTES:
        raise ReconciliationError("captured source text exceeds the size limit")
    try:
        return source_text_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ReconciliationError("captured source text is not valid UTF-8") from exc


def _candidate(tenant_id: str, tenant_root: Path, path: Path) -> AssetCandidate:
    if path.is_symlink() or not path.is_file():
        raise ReconciliationError("manifest path must be a regular file")
    raw = path.read_bytes()
    manifest = _json(path, str(path))
    if manifest.get("qa") is True:
        raise ReconciliationError("QA manifest is excluded from production backwash")
    asset_id = manifest.get("asset_id")
    if not isinstance(asset_id, str) or not ASSET_ID.fullmatch(asset_id.strip()):
        raise ReconciliationError("manifest asset_id is invalid")
    asset_id = asset_id.strip()
    if path.parent.name != asset_id:
        raise ReconciliationError("manifest path asset directory does not match asset_id")
    sidecar = _json(path.with_name(path.name + ".manifest.json"), f"sidecar for {path}")
    if sidecar.get("artifact_type") != "source_asset_manifest":
        raise ReconciliationError("sidecar artifact_type is not source_asset_manifest")
    if sidecar.get("tenant_id") != tenant_id or sidecar.get("owner_type") != "SourceAsset":
        raise ReconciliationError("sidecar ownership does not match target tenant")
    if sidecar.get("owner_id") != asset_id:
        raise ReconciliationError("sidecar owner_id does not match asset_id")
    content_hash = str(sidecar.get("content_hash") or "")
    if not SHA256.fullmatch(content_hash) or content_hash != f"sha256:{hashlib.sha256(raw).hexdigest()}":
        raise ReconciliationError("sidecar content hash does not match manifest bytes")
    if sidecar.get("size_bytes") is not None and sidecar.get("size_bytes") != len(raw):
        raise ReconciliationError("sidecar size_bytes does not match manifest bytes")
    if sidecar.get("uri") != _uri(tenant_id, tenant_root, path):
        raise ReconciliationError("sidecar URI does not match the tenant-scoped path")
    fields = _fields(manifest, asset_id)
    captured_source_text = _captured_source_text(path)
    source = {
        "provider": "media_vault",
        "artifact_type": "source_asset_manifest",
        "artifact_id": str(sidecar.get("artifact_id") or ""),
        "uri": str(sidecar["uri"]),
        "content_hash": content_hash,
    }
    if not source["artifact_id"]:
        raise ReconciliationError("sidecar artifact_id is required")
    source_url = str(fields.get("source_url") or "").strip()
    evidence = (
        {
            "kind": "source",
            "label": "MediaVault source manifest",
            "quality_status": "partial",
            "public_url": source_url,
            "captured_at": fields.get("captured_at"),
        },
    ) if source_url else ()
    _, canonical, _ = canonicalize_source_asset(
        SourceAssetInput(
            source_identity=source_url or str(fields.get("source_asset_id") or asset_id),
            title=str(fields.get("title") or ""),
            original_title=str(fields.get("title") or ""),
            media_type="link",
            platform=str(fields.get("platform") or "") or None,
            source_url=source_url or None,
            captured_at=fields.get("captured_at"),
            source_kind="media_vault_manifest",
            canonical_data={
                "asset_id": asset_id,
                "platform_hashtags": resolve_platform_hashtags(
                    fields.get("platform_hashtags"),
                    captured_source_text,
                    fields.get("title"),
                ),
                "source": source,
                "fields": fields,
                "mediaVaultEvidence": source,
            },
            evidence=evidence,
        ),
        tenant_id,
    )
    return AssetCandidate(asset_id, f"media_vault:v2:{content_hash[7:]}", canonical, str(path))


def discover_candidates(vault_root: str | Path, tenant_id: str) -> tuple[list[AssetCandidate], list[dict[str, str]]]:
    """Return verified candidates and fail-closed per-file errors."""
    tenant_id = _tenant(tenant_id)
    tenant_root = _tenant_root(Path(vault_root), tenant_id)
    source_root = tenant_root / "source_assets"
    candidates: list[AssetCandidate] = []
    errors: list[dict[str, str]] = []
    paths = sorted(source_root.rglob("manifest.json")) if source_root.exists() else []
    for path in paths:
        try:
            path.resolve().relative_to(tenant_root)
            candidates.append(_candidate(tenant_id, tenant_root, path))
        except (OSError, ReconciliationError, ValueError) as exc:
            errors.append({"path": str(path), "error": str(exc)})
    grouped: dict[str, list[AssetCandidate]] = {}
    for item in candidates:
        grouped.setdefault(item.public_id, []).append(item)
    duplicate_ids = {key for key, values in grouped.items() if len(values) > 1}
    for public_id in sorted(duplicate_ids):
        for item in grouped[public_id]:
            errors.append({"path": item.path, "error": f"duplicate asset_id: {public_id}"})
    candidates = [item for item in candidates if item.public_id not in duplicate_ids]
    return candidates, errors


def repair_sidecar_sizes(vault_root: str | Path, tenant_id: str) -> list[str]:
    """Repair only redundant size metadata after full hash/owner/URI validation."""

    tenant_id = _tenant(tenant_id)
    tenant_root = _tenant_root(Path(vault_root), tenant_id)
    repaired: list[str] = []
    source_root = tenant_root / "source_assets"
    for path in sorted(source_root.rglob("manifest.json")) if source_root.exists() else []:
        if path.is_symlink() or not path.is_file():
            continue
        raw = path.read_bytes()
        manifest = _json(path, str(path))
        if manifest.get("qa") is True:
            continue
        asset_id = str(manifest.get("asset_id") or "").strip()
        if not ASSET_ID.fullmatch(asset_id) or path.parent.name != asset_id:
            continue
        sidecar_path = path.with_name(path.name + ".manifest.json")
        if sidecar_path.is_symlink() or not sidecar_path.is_file():
            continue
        sidecar = _json(sidecar_path, f"sidecar for {path}")
        expected_hash = f"sha256:{hashlib.sha256(raw).hexdigest()}"
        if (
            sidecar.get("artifact_type") != "source_asset_manifest"
            or sidecar.get("tenant_id") != tenant_id
            or sidecar.get("owner_type") != "SourceAsset"
            or sidecar.get("owner_id") != asset_id
            or sidecar.get("content_hash") != expected_hash
            or sidecar.get("uri") != _uri(tenant_id, tenant_root, path)
        ):
            continue
        if sidecar.get("size_bytes") == len(raw):
            continue
        sidecar["size_bytes"] = len(raw)
        temporary = sidecar_path.with_name(f".{sidecar_path.name}.{os.getpid()}.tmp")
        encoded = (json.dumps(sidecar, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
        try:
            with temporary.open("xb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            temporary.chmod(sidecar_path.stat().st_mode & 0o777)
            os.replace(temporary, sidecar_path)
            directory_fd = os.open(sidecar_path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            temporary.unlink(missing_ok=True)
        repaired.append(str(sidecar_path))
    return repaired


def _authorize(connection: Any, tenant_id: str, scope: OperatorScope) -> None:
    scope.validate()
    operator = scope.operator_id.strip()
    if scope.scope == "tenant":
        row = connection.execute(
            "SELECT 1 FROM openclaw_account.tenant_members tm "
            "JOIN openclaw_account.users u ON u.id = tm.user_id "
            "WHERE tm.tenant_id = %s AND tm.status = 'active' AND u.status = 'active' "
            "AND (u.id::text = %s OR u.username = %s)",
            (tenant_id, operator, operator),
        ).fetchone()
        if not row:
            raise ReconciliationError("operator is not an active member of the target tenant")
        return
    row = connection.execute(
        "SELECT 1 FROM openclaw_account.users "
        "WHERE status = 'active' AND role = 'admin' AND (id::text = %s OR username = %s)",
        (operator, operator),
    ).fetchone()
    if not row:
        raise ReconciliationError("operator is not an active admin")
    if not connection.execute(
        "SELECT 1 FROM openclaw_account.tenants WHERE id = %s AND status = 'active'",
        (tenant_id,),
    ).fetchone():
        raise ReconciliationError("target tenant is not active")


def _merge_canonical(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    merged = {key: value for key, value in existing.items() if key != "tags"}
    for key, value in incoming.items():
        if key == "source":
            continue
        if key == "fields":
            existing_fields = merged.get("fields") if isinstance(merged.get("fields"), dict) else {}
            incoming_fields = value if isinstance(value, dict) else {}
            merged["fields"] = {
                **incoming_fields,
                **existing_fields,
            }
            continue
        if key == "evidenceRefs" and isinstance(value, list):
            current = merged.get(key) if isinstance(merged.get(key), list) else []
            signatures = {json.dumps(item, ensure_ascii=False, sort_keys=True) for item in current}
            merged[key] = [*current, *[
                item for item in value
                if json.dumps(item, ensure_ascii=False, sort_keys=True) not in signatures
            ]]
            continue
        if key not in merged or merged[key] in (None, "", [], {}):
            merged[key] = value
    incoming_source = incoming.get("mediaVaultEvidence") or incoming.get("source")
    if isinstance(incoming_source, dict):
        merged["mediaVaultEvidence"] = incoming_source
    return merged


def reconcile(
    connection: Any,
    tenant_id: str,
    candidates: Iterable[AssetCandidate],
    operator_scope: OperatorScope,
    *,
    owner_registry: Any,
) -> dict[str, int]:
    """Idempotently upsert verified candidates after DB authorization."""
    tenant_id = _tenant(tenant_id)
    _authorize(connection, tenant_id, operator_scope)
    stats = {"inserted": 0, "updated": 0, "unchanged": 0}
    try:
        for item in candidates:
            try:
                owner_registry.create(
                    "media.source_asset",
                    item.public_id,
                    session_tenant_id=tenant_id,
                )
            except ResourceOwnerConflict:
                owner_registry.assert_owner(
                    "media.source_asset",
                    item.public_id,
                    session_tenant_id=tenant_id,
                )
            existing = connection.execute(
                "SELECT source_version, canonical_data FROM media_product.assets "
                "WHERE tenant_id = %s AND public_id = %s FOR UPDATE",
                (tenant_id, item.public_id),
            ).fetchone()
            existing_data = existing[1] if existing else None
            if isinstance(existing_data, str):
                existing_data = json.loads(existing_data)
            canonical_data = (
                _merge_canonical(existing_data, item.canonical_data)
                if isinstance(existing_data, dict)
                else item.canonical_data
            )
            if existing and existing_data == canonical_data:
                if str(existing[0]) != item.source_version:
                    connection.execute(
                        "UPDATE media_product.assets SET source_version = %s "
                        "WHERE tenant_id = %s AND public_id = %s",
                        (item.source_version, tenant_id, item.public_id),
                    )
                stats["unchanged"] += 1
                continue
            payload = json.dumps(canonical_data, ensure_ascii=False, sort_keys=True)
            if existing:
                connection.execute(
                    "UPDATE media_product.assets SET source_version = %s, canonical_data = %s::jsonb, "
                    "revision = revision + 1, updated_at = now() WHERE tenant_id = %s AND public_id = %s",
                    (item.source_version, payload, tenant_id, item.public_id),
                )
                stats["updated"] += 1
            else:
                connection.execute(
                    "INSERT INTO media_product.assets (tenant_id, public_id, source_version, revision, canonical_data) "
                    "VALUES (%s, %s, %s, 1, %s::jsonb)",
                    (tenant_id, item.public_id, item.source_version, payload),
                )
                stats["inserted"] += 1
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    return stats


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Reconcile verified MediaVault manifests into media_product.assets")
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--operator-id", required=True)
    parser.add_argument("--operator-scope", required=True, choices=("tenant", "admin"))
    parser.add_argument("--audit-reason", default="")
    parser.add_argument("--vault-root", default=os.getenv("OPENCLAW_MEDIA_VAULT_ROOT", "/home/ubuntu/selfmedia-tools/data/media_vault"))
    parser.add_argument("--execute", action="store_true", help="commit authorized PostgreSQL upserts; default is dry-run")
    parser.add_argument("--database-url", default="", help="PostgreSQL URL; otherwise OPENCLAW_ACCOUNT_DATABASE_URL")
    parser.add_argument(
        "--owner-db",
        default=os.getenv("OPENCLAW_RESOURCE_OWNER_DB", "/home/ubuntu/.openclaw/state/resource_owners.sqlite3"),
    )
    parser.add_argument(
        "--repair-sidecar-size",
        action="store_true",
        help="after database authorization, atomically repair hash-verified sidecar size metadata",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    tenant_id = _tenant(args.tenant_id)
    scope = OperatorScope(args.operator_id, args.operator_scope, args.audit_reason or None)
    scope.validate()
    if args.repair_sidecar_size and not args.execute:
        raise ReconciliationError("--repair-sidecar-size requires --execute")
    database_url = str(args.database_url or os.getenv("OPENCLAW_ACCOUNT_DATABASE_URL") or "").strip()
    repaired_sidecars: list[str] = []
    if args.repair_sidecar_size:
        if not database_url:
            raise ReconciliationError("--execute requires --database-url or OPENCLAW_ACCOUNT_DATABASE_URL")
        settings = AccountDatabaseSettings.from_environment({"OPENCLAW_ACCOUNT_DATABASE_URL": database_url})
        with AccountDatabase(settings).connect() as connection:
            _authorize(connection, tenant_id, scope)
        repaired_sidecars = repair_sidecar_sizes(args.vault_root, tenant_id)
    candidates, errors = discover_candidates(args.vault_root, tenant_id)
    result: dict[str, Any] = {
        "schemaVersion": "media_vault_assets_reconciliation_v1",
        "tenantId": tenant_id,
        "operatorScope": args.operator_scope,
        "dryRun": not args.execute,
        "discovered": len(candidates) + len({item["path"] for item in errors}),
        "candidateCount": len(candidates),
        "errors": errors,
        "repairedSidecars": repaired_sidecars,
        "items": [{"publicId": item.public_id, "sourceVersion": item.source_version, "path": item.path, "canonicalData": item.canonical_data} for item in candidates],
    }
    if not args.execute:
        result["wouldProject"] = len(candidates)
    else:
        if not database_url:
            raise ReconciliationError("--execute requires --database-url or OPENCLAW_ACCOUNT_DATABASE_URL")
        settings = AccountDatabaseSettings.from_environment({"OPENCLAW_ACCOUNT_DATABASE_URL": database_url})
        with AccountDatabase(settings).connect() as connection:
            result.update(
                reconcile(
                    connection,
                    tenant_id,
                    candidates,
                    scope,
                    owner_registry=ResourceOwnerRegistry(args.owner_db),
                )
            )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
