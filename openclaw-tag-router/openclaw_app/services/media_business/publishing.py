"""Tenant-scoped PostgreSQL projections for the B06 publishing page."""

from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import json
import re
import secrets
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit

from media_vault import MediaVault, MediaVaultError

from . import foundation, sql_pagination
from .foundation import (
    MediaBusinessError,
    TenantContext,
    _fetchall,
    _fetchone,
    body_checksum,
    public_projection,
    validate_body,
)


SCHEMA_VERSION = "media_web_business_pages_v2"
SOURCE_VERSION = "b06.publishing.v1"
DEFAULT_PAGE_SIZE = 30
MAX_PAGE_SIZE = 100
PUBLIC_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{8,160}$")
CHECK_KEYS = ("content", "publication")
PACKAGE_STATUSES = {"draft", "checking", "ready", "published"}
_CURSOR_VERSION = 1
_CURSOR_SCOPE = "publishing"
_CURSOR_AAD = b"media-web-b06-publishing-v1"
_CREATION_PROJECTION_SOURCE = "creation_run_projection.v1"


PublishingError = MediaBusinessError


class PublishingInvalidRequest(PublishingError):
    def __init__(self, message: str, *, field: str | None = None) -> None:
        super().__init__(foundation.INVALID_REQUEST, message, status=400, field=field)


class PublishingForbidden(foundation.Forbidden):
    def __init__(self, message: str = "publishing data is not available for this session") -> None:
        super().__init__(message)


class PublishingNotFound(foundation.NotFound):
    def __init__(self, message: str = "publishing resource was not found") -> None:
        super().__init__(message)


class PublishingConflict(foundation.Conflict):
    def __init__(self, message: str = "publishing revision conflict") -> None:
        super().__init__(message)


class PublishingUnprocessable(foundation.Unprocessable):
    def __init__(self, message: str) -> None:
        super().__init__(message)


class PublishingFieldUnavailable(PublishingError):
    def __init__(self, message: str = "controlled document link is unavailable") -> None:
        super().__init__("field_unavailable", message, status=500)


class PublishingInternalError(foundation.InternalError):
    def __init__(self, message: str = "publishing data is unavailable") -> None:
        super().__init__(message)


class DatabaseConnection(Protocol):
    def execute(self, query: str, params: tuple[Any, ...] = ()) -> Any: ...


ConnectionFactory = Callable[[], AbstractContextManager[DatabaseConnection]]


@dataclass(frozen=True)
class _CursorPosition:
    updated_at: str
    public_id: str


@dataclass(frozen=True)
class _PackageRow:
    public_id: str
    revision: int
    canonical_data: dict[str, Any]
    updated_at: Any
    artifact_public_id: str
    artifact_project_id: str
    artifact_kind: str
    body_authority: str
    artifact_revision: int
    artifact_updated_at: Any


def _json_object(value: Any, label: str) -> dict[str, Any]:
    return foundation.json_object(value, label, error=PublishingInternalError)


def _as_json(value: Any) -> str:
    return foundation.canonical_json(value)


def _public_id(value: Any, field: str = "public id") -> str:
    if not isinstance(value, str) or not PUBLIC_ID_PATTERN.fullmatch(value):
        raise PublishingInternalError(f"{field} is invalid")
    return value


def _request_public_id(value: Any, field: str) -> str:
    if not isinstance(value, str) or not PUBLIC_ID_PATTERN.fullmatch(value):
        raise PublishingInvalidRequest(f"{field} is invalid", field=field)
    return value


def _required_text(data: Mapping[str, Any], key: str, label: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise PublishingInternalError(f"{label} is missing")
    return value.strip()


def _object_field(data: Mapping[str, Any], key: str, label: str) -> dict[str, Any]:
    value = data.get(key)
    if not isinstance(value, Mapping):
        raise PublishingInternalError(f"{label} is invalid")
    return dict(value)


def _map_list(value: Any, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise PublishingInternalError(f"{label} is invalid")
    result: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise PublishingInternalError(f"{label} contains an invalid item")
        result.append(dict(item))
    return result


def _timestamp_error(label: str, reason: str) -> Exception:
    if reason == "missing":
        return PublishingInternalError(f"{label} is missing")
    return PublishingInternalError(f"{label} is invalid")


def _timestamp(value: Any, label: str = "timestamp") -> str:
    return foundation.coerce_utc(value, label, error=_timestamp_error, allow_naive=True).isoformat()


def _request_timestamp_error(field: str, reason: str) -> Exception:
    if reason == "naive":
        return PublishingInvalidRequest(f"{field} must include a timezone", field=field)
    return PublishingInvalidRequest(f"{field} must be an ISO timestamp", field=field)


def _request_timestamp(value: Any, field: str) -> tuple[datetime, str]:
    if not isinstance(value, str) or not value.strip():
        raise PublishingInvalidRequest(f"{field} must be an ISO timestamp", field=field)
    parsed = foundation.coerce_utc(value, field, error=_request_timestamp_error, allow_naive=False)
    return parsed, parsed.isoformat()


def _revision(value: Any, *, request: bool = False, field: str = "revision") -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        if request:
            raise PublishingInvalidRequest(f"{field} must be a non-negative integer", field=field)
        raise PublishingInternalError(f"{field} is invalid")
    return value


def _page_size(value: Any) -> int:
    return foundation.page_size(value, error=lambda m: PublishingInvalidRequest(m, field="pageSize"))


def _public_response(value: dict[str, Any]) -> dict[str, Any]:
    try:
        return public_projection(value)
    except Exception as exc:
        raise PublishingInternalError("publishing response contains a forbidden field") from exc


def _normalize_checks(value: Any, *, request: bool) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) != len(CHECK_KEYS):
        if request:
            raise PublishingInvalidRequest(
                "checks must contain content and publication",
                field="checks",
            )
        raise PublishingInternalError("stored publishing checks are invalid")
    by_key: dict[str, dict[str, Any]] = {}
    for item in value:
        if not isinstance(item, Mapping):
            if request:
                raise PublishingInvalidRequest("checks contain an invalid item", field="checks")
            raise PublishingInternalError("stored publishing checks are invalid")
        key = item.get("key")
        checked = item.get("checked")
        if key not in CHECK_KEYS or key in by_key or not isinstance(checked, bool):
            if request:
                raise PublishingInvalidRequest(
                    "checks must contain unique content and publication keys",
                    field="checks",
                )
            raise PublishingInternalError("stored publishing checks are invalid")
        status = item.get("status")
        expected_status = "complete" if checked else "pending"
        if status is not None and status != expected_status:
            if request:
                raise PublishingInvalidRequest(
                    "check status does not match checked value",
                    field="checks",
                )
            raise PublishingInternalError("stored publishing check status is invalid")
        by_key[str(key)] = {
            "key": str(key),
            "checked": checked,
            "status": expected_status,
        }
    if set(by_key) != set(CHECK_KEYS):
        if request:
            raise PublishingInvalidRequest(
                "checks must contain content and publication keys",
                field="checks",
            )
        raise PublishingInternalError("stored publishing checks are invalid")
    return [by_key[key] for key in CHECK_KEYS]


def _safe_public_url(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 2048:
        raise PublishingInvalidRequest(f"{field} must be a public URL", field=field)
    url = value.strip()
    if any(character.isspace() or ord(character) < 32 for character in url):
        raise PublishingInvalidRequest(f"{field} must be a public URL", field=field)
    try:
        parts = urlsplit(url)
        hostname = parts.hostname
    except ValueError as exc:
        raise PublishingInvalidRequest(f"{field} must be a public URL", field=field) from exc
    if parts.scheme.lower() not in {"http", "https"} or not hostname:
        raise PublishingInvalidRequest(f"{field} must be a public URL", field=field)
    if parts.username is not None or parts.password is not None or parts.fragment:
        raise PublishingInvalidRequest(f"{field} must be a public URL", field=field)
    hostname = hostname.rstrip(".").lower()
    if hostname in {"localhost", "localhost.localdomain"} or hostname.endswith(".localhost") or hostname.endswith(".local"):
        raise PublishingInvalidRequest(f"{field} must be a public URL", field=field)
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address is not None and (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    ):
        raise PublishingInvalidRequest(f"{field} must be a public URL", field=field)
    return url


def _cursor_key(secret: bytes) -> bytes:
    return hashlib.sha256(bytes(secret)).digest()


def _encode_cursor(secret: bytes, context: TenantContext, updated_at: Any, public_id: str) -> str:
    payload = _as_json(
        {
            "v": _CURSOR_VERSION,
            "scope": _CURSOR_SCOPE,
            "tenantTag": hmac.new(
                secret,
                (str(context.tenant_id) + "|" + _CURSOR_SCOPE).encode(),
                hashlib.sha256,
            ).hexdigest()[:32],
            "updatedAt": _timestamp(updated_at),
            "publicId": public_id,
        }
    ).encode()
    signature = hmac.new(_cursor_key(secret), _CURSOR_AAD + payload, hashlib.sha256).digest()
    raw = base64.urlsafe_b64encode(payload).decode().rstrip("=")
    sig = base64.urlsafe_b64encode(signature).decode().rstrip("=")
    return f"{raw}.{sig}"


def _decode_cursor(secret: bytes, context: TenantContext, token: str) -> _CursorPosition:
    if not isinstance(token, str) or token.count(".") != 1:
        raise PublishingInvalidRequest("cursor is invalid", field="cursor")
    encoded_payload, encoded_signature = token.split(".", 1)
    try:
        payload_bytes = base64.urlsafe_b64decode(encoded_payload + "=" * (-len(encoded_payload) % 4))
        signature = base64.urlsafe_b64decode(encoded_signature + "=" * (-len(encoded_signature) % 4))
        expected = hmac.new(_cursor_key(secret), _CURSOR_AAD + payload_bytes, hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError("signature mismatch")
        payload = json.loads(payload_bytes.decode())
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PublishingInvalidRequest("cursor is invalid", field="cursor") from exc
    if payload.get("v") != _CURSOR_VERSION or payload.get("scope") != _CURSOR_SCOPE:
        raise PublishingInvalidRequest("cursor is invalid", field="cursor")
    expected_tag = hmac.new(
        secret,
        (str(context.tenant_id) + "|" + _CURSOR_SCOPE).encode(),
        hashlib.sha256,
    ).hexdigest()[:32]
    if not hmac.compare_digest(str(payload.get("tenantTag", "")), expected_tag):
        raise PublishingInvalidRequest("cursor is invalid", field="cursor")
    public_id = _public_id(payload.get("publicId"), "cursor public id")
    updated_at = _timestamp(payload.get("updatedAt"), "cursor updatedAt")
    return _CursorPosition(updated_at, public_id)


class PublishingService:
    """Read and write B06 publishing facts in the authenticated tenant."""

    _PACKAGE_LIST_QUERY = f"""
        SELECT p.public_id AS package_public_id,
               p.revision AS package_revision,
               p.canonical_data AS package_data,
               p.updated_at AS package_updated_at,
               a.public_id AS artifact_public_id,
               a.public_project_id AS artifact_project_id,
               a.artifact_kind AS artifact_kind,
               a.body_authority AS body_authority,
               a.current_revision AS artifact_revision,
               a.updated_at AS artifact_updated_at
        FROM media_product.publishing_packages AS p
        LEFT JOIN media_product.document_artifacts AS a
          ON a.tenant_id = p.tenant_id
         AND a.public_id = p.canonical_data->>'public_artifact_id'
        WHERE p.tenant_id = %s
{sql_pagination.keyset_window("p.", "updated_at", "public_id")}"""
    _PACKAGE_DETAIL_QUERY = """
        SELECT p.public_id AS package_public_id,
               p.revision AS package_revision,
               p.canonical_data AS package_data,
               p.updated_at AS package_updated_at,
               a.public_id AS artifact_public_id,
               a.public_project_id AS artifact_project_id,
               a.artifact_kind AS artifact_kind,
               a.body_authority AS body_authority,
               a.current_revision AS artifact_revision,
               a.updated_at AS artifact_updated_at
        FROM media_product.publishing_packages AS p
        LEFT JOIN media_product.document_artifacts AS a
          ON a.tenant_id = p.tenant_id
         AND a.public_id = p.canonical_data->>'public_artifact_id'
        WHERE p.tenant_id = %s
          AND p.public_id = %s
    """
    _CHECK_QUERY = """
        SELECT public_id, revision, canonical_data, updated_at
        FROM media_product.publishing_checks
        WHERE tenant_id = %s
          AND canonical_data->>'public_package_id' = %s
        ORDER BY revision DESC, updated_at DESC, public_id ASC
        LIMIT 1
    """
    _POST_BY_ID_QUERY = """
        SELECT public_id, revision, canonical_data, updated_at
        FROM media_product.published_posts
        WHERE tenant_id = %s
          AND public_id = %s
    """
    _POST_BY_PACKAGE_QUERY = """
        SELECT public_id, revision, canonical_data, updated_at
        FROM media_product.published_posts
        WHERE tenant_id = %s
          AND canonical_data->>'public_package_id' = %s
        ORDER BY created_at ASC, public_id ASC
    """
    _POST_BY_PUBLIC_URL_QUERY = """
        SELECT public_id, revision, canonical_data, updated_at
        FROM media_product.published_posts
        WHERE tenant_id = %s
          AND canonical_data->>'public_package_id' = %s
          AND canonical_data->>'platform' = %s
          AND canonical_data->>'published_url' = %s
        LIMIT 1
    """
    _ARTIFACT_QUERY = """
        SELECT public_id, public_project_id, artifact_kind, body_authority,
               current_revision, docx_url, docx_url_expires_at, updated_at
        FROM media_product.document_artifacts
        WHERE tenant_id = %s
          AND public_id = %s
    """
    _CREATION_PACKAGE_QUERY = """
        SELECT public_id
        FROM media_product.publishing_packages
        WHERE tenant_id = %s
          AND canonical_data->>'public_run_id' = %s
        LIMIT 1
    """

    def __init__(
        self,
        connection_factory: ConnectionFactory,
        *,
        cursor_secret: bytes = b"",
        public_id_secret: bytes = b"",
        id_factory: Callable[[str], str] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not cursor_secret:
            cursor_secret = secrets.token_bytes(32)
        if not public_id_secret:
            public_id_secret = cursor_secret
        if len(cursor_secret) < 16 or len(public_id_secret) < 16:
            raise ValueError("B06 secrets must be at least 16 bytes")
        self._connection_factory = connection_factory
        self._cursor_secret = bytes(cursor_secret)
        self._public_id_secret = bytes(public_id_secret)
        self._id_factory = id_factory or self._new_public_id
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def _new_public_id(self, prefix: str) -> str:
        digest = hmac.new(
            self._public_id_secret,
            (prefix + "|" + secrets.token_urlsafe(18)).encode(),
            hashlib.sha256,
        ).hexdigest()[:24]
        return f"{prefix}_{digest}"

    @staticmethod
    def error_response(error: BaseException) -> dict[str, Any]:
        if isinstance(error, PublishingError):
            return {
                "error": {
                    "code": error.code,
                    "message": error.message,
                    "field": error.field,
                }
            }
        return {
            "error": {
                "code": "internal_error",
                "message": "publishing data is unavailable",
                "field": None,
            }
        }

    def _context(self, context: TenantContext | None) -> TenantContext:
        return foundation.require_context_branded(context, PublishingForbidden)

    def _now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime):
            raise PublishingInternalError("publishing clock returned an invalid value")
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)

    @staticmethod
    def _creation_text(value: Any, field: str) -> str:
        if not isinstance(value, str) or not value.strip() or len(value.strip()) > 20_000:
            raise PublishingUnprocessable(f"creation run {field} is missing or invalid")
        return value.strip()

    @classmethod
    def _creation_tags(cls, value: Any) -> list[str]:
        if not isinstance(value, list) or not value:
            raise PublishingUnprocessable("creation run publishing_pack.hashtags is missing or invalid")
        tags = [cls._creation_text(item, "publishing_pack.hashtags") for item in value]
        if len(tags) != len(set(tags)) or len(tags) > 30:
            raise PublishingUnprocessable("creation run publishing_pack.hashtags is invalid")
        return tags

    @classmethod
    def _creation_projection_input(cls, draft: Mapping[str, Any]) -> tuple[str, str, dict[str, Any]]:
        report = draft.get("creator_report")
        if not isinstance(report, Mapping):
            raise PublishingUnprocessable("creation run creator_report is missing")
        overview = report.get("overview")
        if not isinstance(overview, Mapping):
            raise PublishingUnprocessable("creation run creator_report.overview is missing")
        pack = report.get("publishing_pack")
        if not isinstance(pack, Mapping):
            pack = draft.get("publishing_pack")
        if not isinstance(pack, Mapping):
            raise PublishingUnprocessable("creation run publishing_pack is missing")
        platform = cls._creation_text(overview.get("platform"), "creator_report.overview.platform")
        title = cls._creation_text(overview.get("recommended_topic"), "creator_report.overview.recommended_topic")
        fields = {
            "title": cls._creation_text(pack.get("title_1"), "publishing_pack.title_1"),
            "alternate_title": cls._creation_text(pack.get("title_2"), "publishing_pack.title_2"),
            "cover_text": cls._creation_text(pack.get("cover_text"), "publishing_pack.cover_text"),
            "body": cls._creation_text(pack.get("body_copy"), "publishing_pack.body_copy"),
            "hashtags": cls._creation_tags(pack.get("hashtags")),
            "pinned_comment": cls._creation_text(pack.get("pinned_comment"), "publishing_pack.pinned_comment"),
            "comment_prompt": cls._creation_text(pack.get("comment_prompt"), "publishing_pack.comment_prompt"),
            "first_hour_action": cls._creation_text(pack.get("first_hour_action"), "publishing_pack.first_hour_action"),
        }
        return title, platform, fields

    @staticmethod
    def _creation_document_body(title: str, platform: str, fields: Mapping[str, Any]) -> dict[str, Any]:
        body = {
            "schemaVersion": "media.document.body.v1",
            "blocks": [
                {
                    "id": "creation_publishing_heading",
                    "type": "heading_1",
                    "attrs": {},
                    "content": [{"type": "text", "text": title, "marks": []}],
                },
                {
                    "id": "creation_publishing_platform",
                    "type": "paragraph",
                    "attrs": {},
                    "content": [{"type": "text", "text": f"发布平台：{platform}", "marks": []}],
                },
                {
                    "id": "creation_publishing_first_hour",
                    "type": "paragraph",
                    "attrs": {},
                    "content": [{"type": "text", "text": f"发布后 1 小时动作：{fields['first_hour_action']}", "marks": []}],
                },
            ],
        }
        return validate_body(body)

    def project_creation_run(
        self,
        tenant_id: str,
        public_run_id: str,
        *,
        vault_root: str | Path | None = None,
    ) -> dict[str, str | bool]:
        """Project a trusted CreationRun publishing pack into the B06 tables."""

        if not isinstance(tenant_id, str) or not tenant_id.strip():
            raise PublishingUnprocessable("creation run tenant is invalid")
        run_id = _request_public_id(public_run_id, "publicRunId")
        try:
            draft_path = MediaVault(tenant_id=tenant_id.strip(), root=vault_root).creation_run_dir(run_id) / "draft_output.json"
            draft = _json_object(json.loads(draft_path.read_text(encoding="utf-8")), "creation run draft")
        except (OSError, json.JSONDecodeError, MediaVaultError) as exc:
            raise PublishingUnprocessable("creation run draft is unavailable") from exc
        title, platform, content_fields = self._creation_projection_input(draft)
        validation_path = draft_path.with_name("validation_report.json")
        try:
            validation = _json_object(json.loads(validation_path.read_text(encoding="utf-8")), "creation run validation")
        except (OSError, json.JSONDecodeError) as exc:
            raise PublishingUnprocessable("creation run validation is unavailable") from exc
        if validation.get("ok") is not True:
            raise PublishingUnprocessable("creation run validation did not pass")
        body = self._creation_document_body(title, platform, content_fields)
        checksum = body_checksum(body)
        try:
            with self._connection_factory() as connection:
                connection.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    (f"creation-publishing:{tenant_id}:{run_id}",),
                )
                existing = _fetchone(connection.execute(self._CREATION_PACKAGE_QUERY, (tenant_id, run_id)))
                if existing is not None:
                    package_id = existing.get("public_id") if isinstance(existing, Mapping) else existing[0]
                    return {
                        "public_package_id": _public_id(package_id, "existing publishing package id"),
                        "public_run_id": run_id,
                        "created": False,
                    }
                project_id = _public_id(self._id_factory("project"), "project public id")
                artifact_id = _public_id(self._id_factory("artifact"), "artifact public id")
                package_id = _public_id(self._id_factory("package"), "publishing package id")
                project_data = {"public_run_id": run_id, "platform": platform, "source": _CREATION_PROJECTION_SOURCE}
                package_data = {
                    "public_run_id": run_id,
                    "platform": platform,
                    "content_fields": content_fields,
                    "first_hour_action": content_fields["first_hour_action"],
                    "rule_checks": [{"key": "creation_validation", "status": "pass", "source": "creation_run"}],
                    "public_artifact_id": artifact_id,
                    "status": "draft",
                }
                connection.execute(
                    """
                    INSERT INTO media_product.content_projects
                        (tenant_id, public_id, title, stage, revision, canonical_data)
                    VALUES (%s, %s, %s, 'creation_ready', 1, CAST(%s AS jsonb))
                    """,
                    (tenant_id, project_id, title, _as_json(project_data)),
                )
                connection.execute(
                    """
                    INSERT INTO media_product.document_artifacts
                        (tenant_id, public_id, public_project_id, artifact_kind,
                         workspace_mode, body_authority, current_revision)
                    VALUES (%s, %s, %s, 'publishing_package', 'personal_web', 'internal', 1)
                    """,
                    (tenant_id, artifact_id, project_id),
                )
                connection.execute(
                    """
                    INSERT INTO media_product.document_revisions
                        (tenant_id, public_artifact_id, revision, state, base_revision,
                         body_checksum, actor_public_id, generation_source)
                    VALUES (%s, %s, 1, 'ready', NULL, %s, 'system_creation_projection', %s)
                    """,
                    (tenant_id, artifact_id, checksum, _CREATION_PROJECTION_SOURCE),
                )
                connection.execute(
                    """
                    INSERT INTO media_document.revision_bodies
                        (tenant_id, public_artifact_id, revision, schema_version, body_json, body_checksum)
                    VALUES (%s, %s, 1, 'media.document.body.v1', CAST(%s AS jsonb), %s)
                    """,
                    (tenant_id, artifact_id, _as_json(body), checksum),
                )
                connection.execute(
                    """
                    INSERT INTO media_product.publishing_packages
                        (tenant_id, public_id, revision, canonical_data)
                    VALUES (%s, %s, 1, CAST(%s AS jsonb))
                    """,
                    (tenant_id, package_id, _as_json(package_data)),
                )
                self._commit(connection)
                return {"public_package_id": package_id, "public_run_id": run_id, "created": True}
        except PublishingError:
            raise
        except Exception as exc:
            raise PublishingInternalError("creation publishing projection failed") from exc

    def _load_package(self, connection: DatabaseConnection, context: TenantContext, public_id: str) -> _PackageRow:
        row = _fetchone(connection.execute(self._PACKAGE_DETAIL_QUERY, (context.tenant_id, public_id)))
        if row is None:
            raise PublishingNotFound()
        return self._package_row(row)

    @staticmethod
    def _package_row(row: Any) -> _PackageRow:
        if isinstance(row, Mapping):
            values = (
                row.get("package_public_id"),
                row.get("package_revision"),
                row.get("package_data"),
                row.get("package_updated_at"),
                row.get("artifact_public_id"),
                row.get("artifact_project_id"),
                row.get("artifact_kind"),
                row.get("body_authority"),
                row.get("artifact_revision"),
                row.get("artifact_updated_at"),
            )
        else:
            if not isinstance(row, (tuple, list)) or len(row) < 10:
                raise PublishingInternalError("publishing package row shape is invalid")
            values = tuple(row[:10])
        public_id, revision, data, updated_at, artifact_id, project_id, kind, authority, artifact_revision, artifact_updated_at = values
        if artifact_id is None or project_id is None or kind is None or authority is None:
            raise PublishingInternalError("publishing package is not linked to a document artifact")
        return _PackageRow(
            public_id=_public_id(public_id, "package public id"),
            revision=_revision(revision),
            canonical_data=_json_object(data, "publishing package canonical data"),
            updated_at=updated_at,
            artifact_public_id=_public_id(artifact_id, "artifact public id"),
            artifact_project_id=_public_id(project_id, "project public id"),
            artifact_kind=str(kind),
            body_authority=str(authority),
            artifact_revision=_revision(artifact_revision, field="artifact revision"),
            artifact_updated_at=artifact_updated_at,
        )

    def _human_checks(
        self,
        connection: DatabaseConnection,
        context: TenantContext,
        public_package_id: str,
    ) -> list[dict[str, Any]]:
        row = _fetchone(connection.execute(self._CHECK_QUERY, (context.tenant_id, public_package_id)))
        if row is None:
            return [
                {"key": key, "checked": False, "status": "pending"}
                for key in CHECK_KEYS
            ]
        if isinstance(row, Mapping):
            canonical_data = row.get("canonical_data")
        elif isinstance(row, (tuple, list)) and len(row) >= 3:
            canonical_data = row[2]
        else:
            raise PublishingInternalError("publishing check row shape is invalid")
        data = _json_object(canonical_data, "publishing check canonical data")
        return _normalize_checks(data.get("checks"), request=False)

    @staticmethod
    def _artifact_descriptor(package: _PackageRow) -> dict[str, Any]:
        if package.artifact_kind != "publishing_package":
            raise PublishingInternalError("publishing package artifact kind is invalid")
        if package.body_authority != "internal":
            raise PublishingInternalError("publishing package body authority is invalid")
        return {
            "publicArtifactId": package.artifact_public_id,
            "publicProjectId": package.artifact_project_id,
            "artifactType": package.artifact_kind,
            "bodyAuthority": package.body_authority,
            "currentRevision": package.artifact_revision,
            "syncStatus": "not_applicable",
            "updatedAt": _timestamp(package.artifact_updated_at, "artifact updatedAt"),
            "allowedActions": ["read", "export"],
        }

    def _package_projection(
        self,
        connection: DatabaseConnection,
        context: TenantContext,
        package: _PackageRow,
    ) -> dict[str, Any]:
        data = package.canonical_data
        status = _required_text(data, "status", "publishing package status")
        if status not in PACKAGE_STATUSES:
            raise PublishingInternalError("publishing package status is invalid")
        projection = {
            "publicPackageId": package.public_id,
            "publicRunId": _public_id(data.get("public_run_id"), "run public id"),
            "platform": _required_text(data, "platform", "publishing package platform"),
            "contentFields": _object_field(data, "content_fields", "publishing package content fields"),
            "ruleChecks": _map_list(data.get("rule_checks"), "publishing package rule checks"),
            "artifactDescriptor": self._artifact_descriptor(package),
            "humanChecks": self._human_checks(connection, context, package.public_id),
            "status": status,
            "revision": package.revision,
        }
        return projection

    def _package_response(
        self,
        connection: DatabaseConnection,
        context: TenantContext,
        package: _PackageRow,
    ) -> dict[str, Any]:
        return _public_response(
            {
                "schemaVersion": SCHEMA_VERSION,
                "revision": package.revision,
                "package": self._package_projection(connection, context, package),
            }
        )

    def list_publishing_packages(
        self,
        context: TenantContext,
        *,
        cursor: str | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> dict[str, Any]:
        context = self._context(context)
        size = _page_size(page_size)
        position = _decode_cursor(self._cursor_secret, context, cursor) if cursor else None
        ts = position.updated_at if position is not None else None
        public_id = position.public_id if position is not None else None
        params: tuple[Any, ...] = (
            context.tenant_id,
            *sql_pagination.keyset_params(ts, public_id),
            size + 1,
        )
        try:
            with self._connection_factory() as connection:
                rows = _fetchall(connection.execute(self._PACKAGE_LIST_QUERY, params))
                packages = [self._package_row(row) for row in rows]
                has_next = len(packages) > size
                visible = packages[:size]
                items = [
                    self._package_projection(connection, context, package)
                    for package in visible
                ]
                next_cursor = None
                if has_next:
                    last = visible[-1]
                    next_cursor = _encode_cursor(
                        self._cursor_secret,
                        context,
                        last.updated_at,
                        last.public_id,
                    )
        except PublishingError:
            raise
        except Exception as exc:
            raise PublishingInternalError() from exc
        response = {
            "schemaVersion": SCHEMA_VERSION,
            "revision": max((item["revision"] for item in items), default=0),
            "items": items,
            "nextCursor": next_cursor,
        }
        return _public_response(response)

    def get_publishing_package(
        self,
        context: TenantContext,
        public_package_id: str,
    ) -> dict[str, Any]:
        context = self._context(context)
        package_id = _request_public_id(public_package_id, "publicPackageId")
        try:
            with self._connection_factory() as connection:
                package = self._load_package(connection, context, package_id)
                return self._package_response(connection, context, package)
        except PublishingError:
            raise
        except Exception as exc:
            raise PublishingInternalError() from exc

    def _load_idempotent(
        self,
        connection: DatabaseConnection,
        context: TenantContext,
        operation: str,
        idempotency_key: str,
        request: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        if not isinstance(idempotency_key, str) or not idempotency_key.strip() or len(idempotency_key) > 200:
            raise PublishingInvalidRequest("Idempotency-Key is required", field="Idempotency-Key")
        row = _fetchone(
            connection.execute(
                """
                SELECT request_checksum, response_json
                FROM media_product.b06_idempotency_keys
                WHERE tenant_id = %s AND operation = %s AND idempotency_key = %s
                """,
                (context.tenant_id, operation, idempotency_key),
            )
        )
        if row is None:
            return None
        if isinstance(row, Mapping):
            checksum = row.get("request_checksum")
            response_json = row.get("response_json")
        elif isinstance(row, (tuple, list)) and len(row) >= 2:
            checksum, response_json = row[:2]
        else:
            raise PublishingInternalError("idempotency row shape is invalid")
        request_checksum = hashlib.sha256(_as_json(request).encode()).hexdigest()
        if checksum != request_checksum:
            raise PublishingConflict("Idempotency-Key was reused with a different request")
        return _json_object(response_json, "idempotent response")

    @staticmethod
    def _store_idempotent(
        connection: DatabaseConnection,
        context: TenantContext,
        operation: str,
        idempotency_key: str,
        request: Mapping[str, Any],
        response: Mapping[str, Any],
    ) -> None:
        checksum = hashlib.sha256(_as_json(request).encode()).hexdigest()
        connection.execute(
            """
            INSERT INTO media_product.b06_idempotency_keys
                (tenant_id, operation, idempotency_key, request_checksum, response_json)
            VALUES (%s, %s, %s, %s, CAST(%s AS jsonb))
            ON CONFLICT (tenant_id, operation, idempotency_key) DO NOTHING
            """,
            (
                context.tenant_id,
                operation,
                idempotency_key,
                checksum,
                _as_json(response),
            ),
        )

    @staticmethod
    def _commit(connection: Any) -> None:
        commit = getattr(connection, "commit", None)
        if callable(commit):
            commit()

    @staticmethod
    def _check_request(request: Any) -> dict[str, Any]:
        if not isinstance(request, Mapping):
            raise PublishingInvalidRequest("request body is invalid")
        unexpected = set(request) - {"expectedRevision", "checks", "reason"}
        if unexpected:
            raise PublishingInvalidRequest(f"unexpected field: {sorted(unexpected)[0]}")
        expected = _revision(request.get("expectedRevision"), request=True, field="expectedRevision")
        checks = _normalize_checks(request.get("checks"), request=True)
        reason = request.get("reason")
        if not isinstance(reason, str) or not reason.strip() or len(reason.strip()) > 2000:
            raise PublishingInvalidRequest("reason is required", field="reason")
        return {
            "expectedRevision": expected,
            "checks": checks,
            "reason": reason.strip(),
        }

    def update_publishing_checks(
        self,
        context: TenantContext,
        public_package_id: str,
        request: Mapping[str, Any],
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        context = self._context(context)
        package_id = _request_public_id(public_package_id, "publicPackageId")
        normalized = self._check_request(request)
        operation = "updatePublishingChecks"
        try:
            with self._connection_factory() as connection:
                replay = self._load_idempotent(connection, context, operation, idempotency_key, normalized)
                if replay is not None:
                    return replay
                package = self._load_package(connection, context, package_id)
                if package.canonical_data.get("status") == "published":
                    raise PublishingConflict("published package checks are immutable")
                if normalized["expectedRevision"] != package.revision:
                    raise PublishingConflict()
                next_revision = package.revision + 1
                check_id = _public_id(self._id_factory("check"), "check public id")
                check_data = {
                    "public_package_id": package.public_id,
                    "checks": normalized["checks"],
                    "reason": normalized["reason"],
                    "recorded_by": "admin" if context.is_admin else "user",
                    "recorded_at": _timestamp(self._now()),
                }
                connection.execute(
                    """
                    INSERT INTO media_product.publishing_checks
                        (tenant_id, public_id, source_version, revision, canonical_data)
                    VALUES (%s, %s, %s, %s, CAST(%s AS jsonb))
                    """,
                    (
                        context.tenant_id,
                        check_id,
                        SOURCE_VERSION,
                        next_revision,
                        _as_json(check_data),
                    ),
                )
                new_data = dict(package.canonical_data)
                new_data["status"] = (
                    "ready"
                    if all(item["checked"] for item in normalized["checks"])
                    else "checking"
                )
                updated = _fetchone(
                    connection.execute(
                        """
                        UPDATE media_product.publishing_packages
                        SET revision = %s,
                            canonical_data = CAST(%s AS jsonb),
                            updated_at = %s
                        WHERE tenant_id = %s
                          AND public_id = %s
                          AND revision = %s
                        RETURNING public_id, revision, canonical_data, updated_at
                        """,
                        (
                            next_revision,
                            _as_json(new_data),
                            _timestamp(self._now()),
                            context.tenant_id,
                            package.public_id,
                            package.revision,
                        ),
                    )
                )
                if updated is None:
                    raise PublishingConflict()
                readback = self._load_package(connection, context, package.public_id)
                response = self._package_response(connection, context, readback)
                self._store_idempotent(connection, context, operation, idempotency_key, normalized, response)
                self._commit(connection)
                return response
        except PublishingError:
            raise
        except Exception as exc:
            raise PublishingInternalError() from exc

    @staticmethod
    def _publication_request(request: Any) -> tuple[dict[str, Any], datetime]:
        if not isinstance(request, Mapping):
            raise PublishingInvalidRequest("request body is invalid")
        unexpected = set(request) - {
            "publicPackageId",
            "expectedRevision",
            "platform",
            "publishedUrl",
            "publishedAt",
        }
        if unexpected:
            raise PublishingInvalidRequest(f"unexpected field: {sorted(unexpected)[0]}")
        package_id = _request_public_id(request.get("publicPackageId"), "publicPackageId")
        expected = _revision(request.get("expectedRevision"), request=True, field="expectedRevision")
        platform = request.get("platform")
        if not isinstance(platform, str) or not platform.strip():
            raise PublishingInvalidRequest("platform is required", field="platform")
        published_url = _safe_public_url(request.get("publishedUrl"), "publishedUrl")
        published_at, published_at_text = _request_timestamp(request.get("publishedAt"), "publishedAt")
        return (
            {
                "publicPackageId": package_id,
                "expectedRevision": expected,
                "platform": platform.strip(),
                "publishedUrl": published_url,
                "publishedAt": published_at_text,
            },
            published_at,
        )

    def _published_post_projection(self, row: Any) -> dict[str, Any]:
        if isinstance(row, Mapping):
            public_id, revision, data, _updated_at = (
                row.get("public_id"),
                row.get("revision"),
                row.get("canonical_data"),
                row.get("updated_at"),
            )
        elif isinstance(row, (tuple, list)) and len(row) >= 4:
            public_id, revision, data, _updated_at = row[:4]
        else:
            raise PublishingInternalError("published post row shape is invalid")
        body = _json_object(data, "published post canonical data")
        evidence_quality = _required_text(body, "evidence_quality", "published post evidence quality")
        recorded_by = body.get("recorded_by")
        if recorded_by not in {"user", "admin"}:
            raise PublishingInternalError("published post recordedBy is invalid")
        return {
            "publicPostId": _public_id(public_id, "post public id"),
            "publicPackageId": _public_id(body.get("public_package_id"), "package public id"),
            "platform": _required_text(body, "platform", "published post platform"),
            "publishedUrl": _safe_public_url(body.get("published_url"), "publishedUrl"),
            "publishedAt": _timestamp(body.get("published_at"), "publishedAt"),
            "recordedBy": recorded_by,
            "evidenceQuality": evidence_quality,
            "_revision": _revision(revision),
        }

    def _publication_response(self, row: Any) -> dict[str, Any]:
        receipt = self._published_post_projection(row)
        revision = receipt.pop("_revision")
        return _public_response(
            {
                "schemaVersion": SCHEMA_VERSION,
                "revision": revision,
                "publishedPost": receipt,
            }
        )

    def create_published_post(
        self,
        context: TenantContext,
        request: Mapping[str, Any],
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        context = self._context(context)
        normalized, published_at = self._publication_request(request)
        operation = "createPublishedPost"
        try:
            with self._connection_factory() as connection:
                replay = self._load_idempotent(connection, context, operation, idempotency_key, normalized)
                if replay is not None:
                    return replay
                package = self._load_package(connection, context, normalized["publicPackageId"])
                package_platform = _required_text(
                    package.canonical_data,
                    "platform",
                    "publishing package platform",
                )
                if normalized["platform"] != package_platform:
                    raise PublishingInvalidRequest("platform does not match package", field="platform")
                same_url = _fetchone(
                    connection.execute(
                        self._POST_BY_PUBLIC_URL_QUERY,
                        (
                            context.tenant_id,
                            package.public_id,
                            normalized["platform"],
                            normalized["publishedUrl"],
                        ),
                    )
                )
                if same_url is not None:
                    response = self._publication_response(same_url)
                    self._store_idempotent(connection, context, operation, idempotency_key, normalized, response)
                    self._commit(connection)
                    return response
                existing_posts = _fetchall(
                    connection.execute(self._POST_BY_PACKAGE_QUERY, (context.tenant_id, package.public_id))
                )
                if existing_posts:
                    raise PublishingConflict("a different publication already exists for this package")
                if package.canonical_data.get("status") != "ready":
                    raise PublishingUnprocessable("publishing package is not ready")
                if normalized["expectedRevision"] != package.revision:
                    raise PublishingConflict()
                post_id = _public_id(self._id_factory("post"), "post public id")
                recorded_by = "admin" if context.is_admin else "user"
                published_at_text = published_at.isoformat()
                post_data = {
                    "public_package_id": package.public_id,
                    "platform": normalized["platform"],
                    "published_url": normalized["publishedUrl"],
                    "published_at": published_at_text,
                    "recorded_by": recorded_by,
                    "evidence_quality": "unverified",
                    "retrieval_status": "pending",
                    "review_windows": [
                        {
                            "window": "24h",
                            "status": "scheduled",
                            "scheduled_at": (published_at + timedelta(hours=24)).isoformat(),
                        },
                        {
                            "window": "7d",
                            "status": "scheduled",
                            "scheduled_at": (published_at + timedelta(days=7)).isoformat(),
                        },
                    ],
                }
                connection.execute(
                    """
                    INSERT INTO media_product.published_posts
                        (tenant_id, public_id, source_version, revision, canonical_data)
                    VALUES (%s, %s, %s, %s, CAST(%s AS jsonb))
                    """,
                    (
                        context.tenant_id,
                        post_id,
                        SOURCE_VERSION,
                        1,
                        _as_json(post_data),
                    ),
                )
                post_readback = _fetchone(
                    connection.execute(self._POST_BY_ID_QUERY, (context.tenant_id, post_id))
                )
                if post_readback is None:
                    raise PublishingInternalError("published post write could not be read back")
                next_revision = package.revision + 1
                package_data = dict(package.canonical_data)
                package_data["status"] = "published"
                package_data["published_post_id"] = post_id
                updated = _fetchone(
                    connection.execute(
                        """
                        UPDATE media_product.publishing_packages
                        SET revision = %s,
                            canonical_data = CAST(%s AS jsonb),
                            updated_at = %s
                        WHERE tenant_id = %s
                          AND public_id = %s
                          AND revision = %s
                        RETURNING public_id, revision, canonical_data, updated_at
                        """,
                        (
                            next_revision,
                            _as_json(package_data),
                            _timestamp(self._now()),
                            context.tenant_id,
                            package.public_id,
                            package.revision,
                        ),
                    )
                )
                if updated is None:
                    raise PublishingConflict()
                response = self._publication_response(post_readback)
                self._store_idempotent(connection, context, operation, idempotency_key, normalized, response)
                self._commit(connection)
                return response
        except PublishingError:
            raise
        except Exception as exc:
            raise PublishingInternalError() from exc

    def get_published_post(
        self,
        context: TenantContext,
        public_post_id: str,
    ) -> dict[str, Any]:
        context = self._context(context)
        post_id = _request_public_id(public_post_id, "publicPostId")
        try:
            with self._connection_factory() as connection:
                row = _fetchone(connection.execute(self._POST_BY_ID_QUERY, (context.tenant_id, post_id)))
                if row is None:
                    raise PublishingNotFound()
                return self._publication_response(row)
        except PublishingError:
            raise
        except Exception as exc:
            raise PublishingInternalError() from exc

    def get_resource_docx_link(
        self,
        context: TenantContext,
        public_artifact_id: str,
    ) -> dict[str, Any]:
        context = self._context(context)
        artifact_id = _request_public_id(public_artifact_id, "publicArtifactId")
        try:
            with self._connection_factory() as connection:
                row = _fetchone(connection.execute(self._ARTIFACT_QUERY, (context.tenant_id, artifact_id)))
                if row is None:
                    raise PublishingNotFound()
                if isinstance(row, Mapping):
                    kind = row.get("artifact_kind")
                    url = row.get("docx_url")
                    expires_at = row.get("docx_url_expires_at")
                    revision = row.get("current_revision")
                elif isinstance(row, (tuple, list)) and len(row) >= 8:
                    kind, revision, url, expires_at = row[2], row[4], row[5], row[6]
                else:
                    raise PublishingInternalError("document artifact row shape is invalid")
                if kind != "publishing_package":
                    raise PublishingNotFound()
                if not isinstance(url, str) or not url.strip() or expires_at is None:
                    raise PublishingFieldUnavailable()
                safe_url = _safe_public_url(url, "docxUrl")
                expires_text = _timestamp(expires_at, "docx URL expiresAt")
                expires = datetime.fromisoformat(expires_text)
                if expires <= self._now():
                    raise PublishingFieldUnavailable("controlled document link has expired")
                response = {
                    "schemaVersion": SCHEMA_VERSION,
                    "revision": _revision(revision, field="artifact revision"),
                    "document": {
                        "publicArtifactId": artifact_id,
                        "url": safe_url,
                        "expiresAt": expires_text,
                    },
                }
                return _public_response(response)
        except PublishingError:
            raise
        except Exception as exc:
            raise PublishingInternalError() from exc


__all__ = [
    "PublishingConflict",
    "PublishingError",
    "PublishingFieldUnavailable",
    "PublishingForbidden",
    "PublishingInternalError",
    "PublishingInvalidRequest",
    "PublishingNotFound",
    "PublishingService",
    "PublishingUnprocessable",
]
