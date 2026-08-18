"""Typed, tenant-scoped projection of source assets into PostgreSQL.

The caller's authenticated tenant context is the only source of ``tenant_id``.
The input model deliberately has no tenant field so a source record cannot
redirect a write to another tenant.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
import uuid
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Callable, Literal, Mapping, Protocol, Sequence, TypeAlias
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from media_model.platform_hashtags import resolve_platform_hashtags

from ..resource_owner_registry import ResourceOwnerConflict


PROJECTION_SCHEMA_VERSION = "source_asset_projection_v1"
_PUBLIC_ID_PREFIX = "asset_"
_PUBLIC_ID = re.compile(r"asset_[A-Za-z0-9_-]{2,154}\Z")
_TENANT_KEYS = frozenset({"tenantid", "targettenantid"})
_RETIRED_PLATFORM_HASHTAG_KEYS = frozenset({"tags", "标签", "主题标签"})


class SourceAssetProjectionError(ValueError):
    """A source asset cannot be represented by the typed projection contract."""


class SourceAssetProjectionDatabaseError(RuntimeError):
    """A projection transaction failed and was rolled back."""


@dataclass(frozen=True)
class AuthenticatedTenantContext:
    """Minimal authentication context accepted by the projector."""

    tenant_id: str
    user_public_id: str = ""


class TenantContextLike(Protocol):
    tenant_id: str


@dataclass(frozen=True)
class SourceAttachment:
    """Provider-neutral attachment descriptor."""

    attachment_id: str
    name: str | None = None
    media_type: str | None = None
    object_ref: str | None = None
    checksum: str | None = None
    size_bytes: int | None = None


Attachment: TypeAlias = SourceAttachment


@dataclass(frozen=True)
class SourceAssetInput:
    """Typed source record accepted by :class:`SourceAssetProjection`."""

    source_identity: str
    title: str = ""
    media_type: str = "unknown"
    platform: str | None = None
    source_url: str | None = None
    captured_at: datetime | date | str | int | float | None = None
    original_title: str = ""
    source_kind: str = "unknown"
    account_ref: str | None = None
    track_refs: tuple[str, ...] = ()
    request_constraints: Mapping[str, Any] = field(default_factory=dict)
    canonical_data: Mapping[str, Any] = field(default_factory=dict)
    attachments: tuple[SourceAttachment, ...] = ()
    evidence: tuple[Mapping[str, Any], ...] = ()
    published_at: datetime | date | str | None = None
    source_version: str | None = None


SourceAssetRecord: TypeAlias = SourceAssetInput


@dataclass(frozen=True)
class ProjectionResult:
    tenant_id: str
    public_id: str
    revision: int
    status: Literal["inserted", "updated", "unchanged"]
    canonical_data: Mapping[str, Any]


def _key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def normalize_source_identity(value: str) -> str:
    """Return a stable identity for URL and opaque source identifiers."""

    if not isinstance(value, str):
        raise SourceAssetProjectionError("source_identity must be a string")
    value = unicodedata.normalize("NFKC", value).strip()
    if not value:
        raise SourceAssetProjectionError("source_identity is required")
    parsed = urlsplit(value)
    if parsed.scheme and parsed.netloc:
        if parsed.username or parsed.password:
            raise SourceAssetProjectionError("source_identity must not contain credentials")
        hostname = (parsed.hostname or "").encode("idna").decode("ascii").lower()
        if not hostname:
            raise SourceAssetProjectionError("source_identity has no host")
        try:
            port = parsed.port
        except ValueError as exc:
            raise SourceAssetProjectionError("source_identity has an invalid port") from exc
        netloc = hostname
        if port is not None and not ((parsed.scheme.lower() == "http" and port == 80) or (parsed.scheme.lower() == "https" and port == 443)):
            netloc = f"{hostname}:{port}"
        path = parsed.path or "/"
        if path != "/":
            path = path.rstrip("/") or "/"
        query = urlencode(sorted(parse_qsl(parsed.query, keep_blank_values=True)), doseq=True)
        return urlunsplit((parsed.scheme.lower(), netloc, path, query, ""))
    return " ".join(value.casefold().split())


def stable_public_id(tenant_id: str, normalized_source_identity: str) -> str:
    """Derive an opaque id from the authenticated tenant and source identity."""

    material = f"{tenant_id}\x00{normalized_source_identity}".encode("utf-8")
    return _PUBLIC_ID_PREFIX + hashlib.sha256(material).hexdigest()


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime, date)):
        return _timestamp(value)
    if isinstance(value, Mapping):
        output: dict[str, Any] = {}
        for name, item in value.items():
            if _key(name) in _TENANT_KEYS:
                continue
            output[str(name)] = _json_safe(item)
        return output
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    raise SourceAssetProjectionError(f"value of type {type(value).__name__} is not JSON-safe")


def _drop_retired_platform_hashtag_fields(value: Any) -> Any:
    """Remove retired Chinese label aliases before canonical persistence."""

    if isinstance(value, Mapping):
        return {
            str(name): _drop_retired_platform_hashtag_fields(item)
            for name, item in value.items()
            if str(name) not in _RETIRED_PLATFORM_HASHTAG_KEYS
        }
    if isinstance(value, list):
        return [_drop_retired_platform_hashtag_fields(item) for item in value]
    return value


def _timestamp(value: datetime | date | str | int | float | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        value = datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        seconds = float(value) / 1000 if abs(float(value)) >= 100_000_000_000 else float(value)
        value = datetime.fromtimestamp(seconds, tz=timezone.utc)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, str) and value.strip():
        try:
            instant = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError as exc:
            raise SourceAssetProjectionError("published_at is not an ISO timestamp") from exc
        if instant.tzinfo is None:
            instant = instant.replace(tzinfo=timezone.utc)
        return instant.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    raise SourceAssetProjectionError("published_at must be a timestamp")


def _attachment(value: SourceAttachment | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(value, SourceAttachment):
        output: dict[str, Any] = {"attachment_id": value.attachment_id}
        values = {
            "name": value.name,
            "media_type": value.media_type,
            "object_ref": value.object_ref,
            "checksum": value.checksum,
            "size_bytes": value.size_bytes,
        }
    elif isinstance(value, Mapping):
        if any(_key(name) in _TENANT_KEYS for name in value):
            raise SourceAssetProjectionError("attachment cannot contain tenant identity")
        values = {
            "name": value.get("name") or value.get("filename") or value.get("file_name"),
            "media_type": value.get("media_type") or value.get("mime_type") or value.get("type"),
            "object_ref": value.get("object_ref") or value.get("uri") or value.get("url"),
            "checksum": value.get("checksum") or value.get("sha256"),
            "size_bytes": value.get("size_bytes") or value.get("size"),
        }
        raw_id = value.get("attachment_id") or value.get("id") or values["name"]
        attachment_id = str(raw_id or "").strip()
        if not attachment_id:
            raise SourceAssetProjectionError("attachment_id is required")
        output = {"attachment_id": attachment_id}
    else:
        raise SourceAssetProjectionError("attachments must be typed descriptors or objects")
    if not output.get("attachment_id"):
        raise SourceAssetProjectionError("attachment_id is required")
    for name, item in values.items():
        if item is None or item == "":
            continue
        if name == "size_bytes":
            if isinstance(item, bool) or not isinstance(item, int) or item < 0:
                raise SourceAssetProjectionError("attachment size_bytes must be a non-negative integer")
            output[name] = item
        else:
            text = str(item).strip()
            if name == "object_ref" and not text.startswith("media://"):
                raise SourceAssetProjectionError("attachment object_ref must be a MediaVault URI")
            output[name] = text
    return output


def _evidence_items(value: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise SourceAssetProjectionError("evidence entries must be objects")
        cleaned = _json_safe(item)
        output.append(cleaned)
    return output


def _string_list(value: Any, *, field_name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        raise SourceAssetProjectionError(f"{field_name} must be a list")
    output: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if not text:
            raise SourceAssetProjectionError(f"{field_name} contains an empty value")
        if text not in output:
            output.append(text)
    return output


def _quality_status(evidence: Sequence[Mapping[str, Any]]) -> str:
    statuses = {
        str(item.get("quality_status") or item.get("qualityStatus") or item.get("quality") or "")
        .strip()
        .casefold()
        for item in evidence
    }
    if "verified" in statuses:
        return "verified"
    if statuses & {"partial", "screenshot_only"}:
        return "partial"
    if "unavailable" in statuses:
        return "unavailable"
    return "unverified"


def _evidence_refs(
    evidence: Sequence[Mapping[str, Any]],
    *,
    default_captured_at: str | None,
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for item in evidence:
        quality = str(
            item.get("quality_status") or item.get("qualityStatus") or item.get("quality") or "unverified"
        ).strip().casefold()
        if quality == "screenshot_only":
            quality = "partial"
        if quality not in {"verified", "partial", "unverified", "unavailable"}:
            quality = "unverified"
        public_url = item.get("public_url") or item.get("publicUrl") or item.get("url")
        if public_url:
            parsed = urlsplit(str(public_url).strip())
            if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
                public_url = None
        captured_at = item.get("captured_at") or item.get("capturedAt") or default_captured_at
        output.append(
            {
                "kind": str(item.get("kind") or item.get("type") or "source").strip() or "source",
                "label": str(item.get("label") or item.get("name") or "来源证据").strip() or "来源证据",
                "publicUrl": str(public_url).strip() if public_url else None,
                "capturedAt": _timestamp(captured_at) if captured_at else None,
                "qualityStatus": quality,
            }
        )
    return output


def _publication_is_evidenced(evidence: Sequence[Mapping[str, Any]]) -> bool:
    for item in evidence:
        kind = str(item.get("kind") or item.get("type") or "").casefold().replace("-", "_")
        quality = str(item.get("quality_status") or item.get("qualityStatus") or item.get("quality") or "").casefold()
        reference = item.get("public_url") or item.get("url") or item.get("ref") or item.get("source")
        if kind in {"publication", "published_at", "published"} and quality == "verified" and reference:
            return True
    return False


def _coerce_input(value: SourceAssetInput | Mapping[str, Any]) -> SourceAssetInput:
    if isinstance(value, SourceAssetInput):
        return value
    if not isinstance(value, Mapping):
        raise SourceAssetProjectionError("source asset must be a typed input or object")
    if any(_key(name) in _TENANT_KEYS for name in value):
        raise SourceAssetProjectionError("tenant_id must come from authenticated context")
    identity = value.get("source_identity") or value.get("sourceIdentity") or value.get("source_url") or value.get("sourceUrl") or value.get("url")
    attachments = value.get("attachments") or ()
    evidence = value.get("evidence") or value.get("evidence_refs") or value.get("evidenceRefs") or ()
    canonical = value.get("canonical_data") or value.get("canonicalData") or {}
    if isinstance(canonical, Mapping):
        canonical = dict(canonical)
        if "platform_hashtags" in value:
            canonical["platform_hashtags"] = value.get("platform_hashtags")
    return SourceAssetInput(
        source_identity=str(identity or ""),
        title=str(value.get("title") or ""),
        media_type=str(value.get("media_type") or value.get("mediaType") or "unknown"),
        platform=str(value["platform"]) if value.get("platform") is not None else None,
        source_url=str(value["source_url"] or value["sourceUrl"]) if value.get("source_url") or value.get("sourceUrl") else None,
        captured_at=value.get("captured_at") or value.get("capturedAt"),
        original_title=str(value.get("original_title") or value.get("originalTitle") or ""),
        source_kind=str(value.get("source_kind") or value.get("sourceKind") or "unknown"),
        account_ref=str(value.get("account_ref") or value.get("accountRef") or "") or None,
        track_refs=tuple(value.get("track_refs") or value.get("trackRefs") or ()),
        request_constraints=(
            value.get("request_constraints") or value.get("requestConstraints") or {}
        ),
        canonical_data=canonical if isinstance(canonical, Mapping) else {},
        attachments=tuple(attachments),
        evidence=tuple(evidence),
        published_at=value.get("published_at") or value.get("publishedAt"),
        source_version=str(value["source_version"] or value["sourceVersion"]) if value.get("source_version") or value.get("sourceVersion") else None,
    )


def canonicalize_source_asset(asset: SourceAssetInput | Mapping[str, Any], tenant_id: str) -> tuple[str, dict[str, Any], str]:
    """Return ``(public_id, canonical_data, source_version)`` for a source."""

    source = _coerce_input(asset)
    normalized_identity = normalize_source_identity(source.source_identity)
    public_id = stable_public_id(tenant_id, normalized_identity)
    evidence = _evidence_items(source.evidence)
    captured_at = _timestamp(source.captured_at)
    raw_canonical = _json_safe(dict(source.canonical_data))
    if not isinstance(raw_canonical, dict):
        raise SourceAssetProjectionError("canonical_data must be an object")
    if "tags" in raw_canonical:
        raise SourceAssetProjectionError("canonical_data.tags is retired; use platform_hashtags")
    canonical = _drop_retired_platform_hashtag_fields(raw_canonical)
    track_names = _string_list(
        source.track_refs or canonical.get("trackNames") or (),
        field_name="track_refs",
    )
    title = source.title.strip() or source.original_title.strip() or "未命名素材"
    platform_hashtags = resolve_platform_hashtags(
        canonical.get("platform_hashtags"),
        source.original_title,
        source.title,
    )
    media_type = source.media_type.strip() or "unknown"
    platform = source.platform.strip() if source.platform and source.platform.strip() else "未标注"
    source_label = str(canonical.get("sourceLabel") or source.account_ref or platform or "用户素材").strip()
    material_status = str(canonical.get("materialStatus") or canonical.get("status") or "captured").strip()
    quality_status = _quality_status(evidence)
    canonical.update(
        {
            "schema_version": PROJECTION_SCHEMA_VERSION,
            "source_identity": normalized_identity,
            "title": title,
            "original_title": source.original_title.strip() or None,
            "media_type": media_type,
            "mediaType": media_type,
            "platform": platform,
            "sourceLabel": source_label,
            "platform_hashtags": platform_hashtags,
            "trackNames": track_names,
            "qualityStatus": quality_status,
            "materialStatus": material_status,
            "source_url": normalize_source_identity(source.source_url) if source.source_url else None,
            "source_kind": source.source_kind.strip() or "unknown",
            "account_ref": source.account_ref.strip() if source.account_ref else None,
            "track_refs": track_names,
            "request_constraints": _json_safe(dict(source.request_constraints)),
            "captured_at": captured_at,
            "evidence": evidence,
            "evidenceRefs": _evidence_refs(evidence, default_captured_at=captured_at),
            "attachments": [_attachment(item) for item in source.attachments],
            "published_at": _timestamp(source.published_at) if _publication_is_evidenced(evidence) else None,
        }
    )
    canonical_json = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    source_version = source.source_version.strip() if source.source_version else "source-asset:" + hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()[:24]
    if not source_version:
        raise SourceAssetProjectionError("source_version must not be empty")
    return public_id, canonical, source_version


ConnectionFactory: TypeAlias = Callable[[], AbstractContextManager[Any]]


class SourceAssetProjection:
    """Write source assets to the canonical PostgreSQL read model."""

    def __init__(self, connection_factory: ConnectionFactory, *, owner_registry: Any | None = None):
        self.connection_factory = connection_factory
        self.owner_registry = owner_registry

    def project(self, context: TenantContextLike, asset: SourceAssetInput | Mapping[str, Any]) -> ProjectionResult:
        tenant_id = self._tenant_id(getattr(context, "tenant_id", ""))
        public_id, canonical, source_version = canonicalize_source_asset(asset, tenant_id)
        if self.owner_registry is not None:
            try:
                self.owner_registry.create(
                    "media.source_asset",
                    public_id,
                    session_tenant_id=tenant_id,
                )
            except ResourceOwnerConflict:
                self.owner_registry.assert_owner(
                    "media.source_asset",
                    public_id,
                    session_tenant_id=tenant_id,
                )
        encoded = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        with self.connection_factory() as connection:
            try:
                existing = connection.execute(
                    "SELECT revision, source_version, canonical_data FROM media_product.assets "
                    "WHERE tenant_id = %s AND public_id = %s FOR UPDATE",
                    (tenant_id, public_id),
                ).fetchone()
                if existing is not None:
                    old_revision, old_source_version, old_canonical = existing[:3]
                    same_canonical = _json_safe(old_canonical) == canonical
                    if same_canonical and str(old_source_version) == source_version:
                        connection.commit()
                        return ProjectionResult(tenant_id, public_id, int(old_revision), "unchanged", canonical)
                    if same_canonical:
                        row = connection.execute(
                            "UPDATE media_product.assets SET source_version = %s WHERE tenant_id = %s AND public_id = %s RETURNING revision",
                            (source_version, tenant_id, public_id),
                        ).fetchone()
                        revision = int(row[0]) if row else int(old_revision)
                        connection.commit()
                        return ProjectionResult(tenant_id, public_id, revision, "unchanged", canonical)
                    row = connection.execute(
                        "UPDATE media_product.assets SET source_version = %s, canonical_data = %s::jsonb, revision = revision + 1 "
                        "WHERE tenant_id = %s AND public_id = %s RETURNING revision",
                        (source_version, encoded, tenant_id, public_id),
                    ).fetchone()
                    revision = int(row[0]) if row else int(old_revision) + 1
                    connection.commit()
                    return ProjectionResult(tenant_id, public_id, revision, "updated", canonical)
                row = connection.execute(
                    "INSERT INTO media_product.assets "
                    "(tenant_id, public_id, source_version, revision, canonical_data) "
                    "VALUES (%s, %s, %s, 1, %s::jsonb) "
                    "ON CONFLICT (tenant_id, public_id) DO UPDATE SET "
                    "source_version = EXCLUDED.source_version, canonical_data = EXCLUDED.canonical_data, "
                    "revision = CASE WHEN media_product.assets.canonical_data IS DISTINCT FROM EXCLUDED.canonical_data "
                    "THEN media_product.assets.revision + 1 ELSE media_product.assets.revision END "
                    "RETURNING revision",
                    (tenant_id, public_id, source_version, encoded),
                ).fetchone()
                revision = int(row[0]) if row else 1
                connection.commit()
                return ProjectionResult(tenant_id, public_id, revision, "inserted", canonical)
            except Exception as exc:
                connection.rollback()
                raise SourceAssetProjectionDatabaseError("source asset projection transaction failed") from exc

    def exists(self, tenant_id: str, public_asset_id: str) -> bool:
        tenant_id = self._tenant_id(tenant_id)
        public_asset_id = self._public_asset_id(public_asset_id)
        with self.connection_factory() as connection:
            try:
                row = connection.execute(
                    "SELECT 1 FROM media_product.assets WHERE tenant_id = %s AND public_id = %s",
                    (tenant_id, public_asset_id),
                ).fetchone()
            except Exception as exc:
                connection.rollback()
                raise SourceAssetProjectionDatabaseError("source asset projection readback failed") from exc
        return row is not None

    def delete(self, tenant_id: str, public_asset_id: str) -> bool:
        tenant_id = self._tenant_id(tenant_id)
        public_asset_id = self._public_asset_id(public_asset_id)
        with self.connection_factory() as connection:
            try:
                deleted = connection.execute(
                    "DELETE FROM media_product.assets WHERE tenant_id = %s AND public_id = %s RETURNING public_id",
                    (tenant_id, public_asset_id),
                ).fetchone()
                readback = connection.execute(
                    "SELECT 1 FROM media_product.assets WHERE tenant_id = %s AND public_id = %s",
                    (tenant_id, public_asset_id),
                ).fetchone()
                if readback is not None:
                    raise RuntimeError("PostgreSQL 素材删除后读回仍存在")
                connection.commit()
            except Exception as exc:
                connection.rollback()
                raise SourceAssetProjectionDatabaseError("source asset projection delete failed") from exc
        return deleted is not None

    @staticmethod
    def _tenant_id(value: Any) -> str:
        tenant_id = str(value or "").strip()
        if not tenant_id:
            raise SourceAssetProjectionError("authenticated tenant context is required")
        try:
            canonical_tenant_id = str(uuid.UUID(tenant_id))
        except ValueError as exc:
            raise SourceAssetProjectionError("authenticated tenant_id must be a canonical UUID") from exc
        if canonical_tenant_id != tenant_id:
            raise SourceAssetProjectionError("authenticated tenant_id must be a canonical UUID")
        return tenant_id

    @staticmethod
    def _public_asset_id(value: Any) -> str:
        public_asset_id = str(value or "").strip()
        if _PUBLIC_ID.fullmatch(public_asset_id) is None:
            raise SourceAssetProjectionError("public_asset_id is invalid")
        return public_asset_id


def project_growth_source_asset(
    projector: SourceAssetProjection,
    *,
    tenant_id: str,
    artifact: Mapping[str, Any],
    uploads: Sequence[Mapping[str, Any]] = (),
) -> ProjectionResult:
    """Project an already-persisted Media Growth SourceAsset result."""

    if not isinstance(artifact, Mapping) or str(artifact.get("artifact_type") or "") != "SourceAsset":
        raise SourceAssetProjectionError("Media Growth result is not a SourceAsset")
    urls = [str(item).strip() for item in artifact.get("urls") or [] if str(item).strip()]
    artifact_uri = str(artifact.get("artifact_uri") or "").strip()
    artifact_id = str(artifact.get("artifact_id") or "").strip()
    source_identity = (urls[0] if urls else artifact_uri or artifact_id).strip()
    if not source_identity:
        raise SourceAssetProjectionError("Media Growth SourceAsset has no source identity")
    created_at = artifact.get("created_at") or artifact.get("updated_at")
    attachments: list[SourceAttachment] = []
    for item in uploads:
        if not isinstance(item, Mapping):
            continue
        attachment_id = str(item.get("upload_id") or item.get("sha256") or "").strip()
        if not attachment_id:
            continue
        attachments.append(
            SourceAttachment(
                attachment_id=attachment_id,
                name=str(item.get("filename") or "").strip() or None,
                media_type=str(item.get("mime_type") or "").strip() or None,
                checksum=str(item.get("sha256") or "").strip() or None,
            )
        )
    evidence: tuple[Mapping[str, Any], ...] = ()
    if artifact_uri.startswith("media://"):
        evidence = (
            {
                "kind": "media_vault_artifact",
                "label": "MediaVault SourceAsset",
                "quality_status": "verified",
                "captured_at": created_at,
                "ref": artifact_uri,
            },
        )
    source = SourceAssetInput(
        source_identity=source_identity,
        title=str(artifact.get("display_title") or ""),
        original_title=str(artifact.get("original_title") or artifact.get("display_title") or ""),
        media_type=str(artifact.get("media_type") or artifact.get("source_kind") or "unknown"),
        platform=str(artifact.get("platform") or "") or None,
        source_url=urls[0] if urls else None,
        captured_at=created_at,
        source_kind=str(artifact.get("source_kind") or "media_growth_intake"),
        account_ref=str(artifact.get("account_id") or "") or None,
        track_refs=(str(artifact.get("track_id")),) if str(artifact.get("track_id") or "").strip() else (),
        request_constraints=(
            artifact.get("request_constraints")
            if isinstance(artifact.get("request_constraints"), Mapping)
            else {}
        ),
        canonical_data={
            "artifact_id": artifact_id,
            "artifact_uri": artifact_uri,
            "display_summary": str(artifact.get("display_summary") or ""),
            "platform_hashtags": resolve_platform_hashtags(
                artifact.get("platform_hashtags"),
                artifact.get("original_title"),
                artifact.get("display_title"),
            ),
            "source_trace": _json_safe(artifact.get("source_trace") or []),
            "status": str(artifact.get("status") or "captured"),
        },
        attachments=tuple(attachments),
        evidence=evidence,
    )
    return projector.project(AuthenticatedTenantContext(tenant_id=tenant_id), source)


SourceAssetProjectionService: TypeAlias = SourceAssetProjection
SourceAsset: TypeAlias = SourceAssetInput


__all__ = [
    "Attachment",
    "AuthenticatedTenantContext",
    "PROJECTION_SCHEMA_VERSION",
    "ProjectionResult",
    "SourceAsset",
    "SourceAssetInput",
    "SourceAssetProjection",
    "SourceAssetProjectionDatabaseError",
    "SourceAssetProjectionError",
    "SourceAssetProjectionService",
    "SourceAssetRecord",
    "SourceAttachment",
    "canonicalize_source_asset",
    "normalize_source_identity",
    "stable_public_id",
    "project_growth_source_asset",
]
