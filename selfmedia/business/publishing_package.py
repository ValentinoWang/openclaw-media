"""Tenant-local publishing package producer.

The package is an execution artifact, not prose copied into a delivery
document.  It can be projected into the web publishing tables by an owning
adapter, while this producer remains useful when external systems are absent.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

from media_vault import MediaVault, require_tenant_id

from .commercial_loop import has_external_evidence


PUBLISHING_PACKAGE_SCHEMA_VERSION = "publishing_package_v1"
PACKAGE_FILENAME = "publishing_package.json"
REQUIRED_CONTENT_FIELDS = (
    "title_1",
    "title_2",
    "cover_text",
    "body_copy",
    "hashtags",
    "pinned_comment",
    "comment_prompt",
    "first_hour_action",
)


class PublishingPackageError(ValueError):
    """Invalid package input or an unsafe package replay."""


def build_publishing_package_payload(
    *,
    opportunity_id: str,
    creation_run_id: str,
    platform: str,
    content_fields: Mapping[str, Any],
    published_url: str = "",
    external_evidence_uri: str = "",
    external_verified: bool = False,
    version: str = "1",
    idempotency_identity: str = "",
    tenant_id: str = "",
) -> dict[str, Any]:
    """Build the canonical structured payload used by local and DB producers."""
    opportunity = str(opportunity_id or "").strip()
    run_id = str(creation_run_id or "").strip()
    platform_name = str(platform or "").strip()
    if not opportunity or not run_id or not platform_name:
        raise PublishingPackageError("opportunity_id, creation_run_id and platform are required")
    if not isinstance(content_fields, Mapping):
        raise PublishingPackageError("content_fields must be an object")
    fields = dict(content_fields)
    missing = [key for key in REQUIRED_CONTENT_FIELDS if key not in fields or fields[key] in (None, "", [])]
    if missing:
        raise PublishingPackageError(f"publishing package fields missing: {', '.join(missing)}")
    if not isinstance(fields["hashtags"], list) or not all(str(item).strip() for item in fields["hashtags"]):
        raise PublishingPackageError("hashtags must be a non-empty list")
    url = _public_url(published_url)
    identity = str(idempotency_identity or "").strip() or "creation_run:" + hashlib.sha256(
        f"{tenant_id}|{opportunity}|{run_id}".encode("utf-8")
    ).hexdigest()
    evidence = str(external_evidence_uri or "").strip()
    return {
        "schema_version": PUBLISHING_PACKAGE_SCHEMA_VERSION,
        "package_id": f"package_{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:24]}",
        "version": str(version or "1").strip() or "1",
        "idempotency_identity": identity,
        "tenant_id": str(tenant_id or "").strip(),
        "opportunity_id": opportunity,
        "creation_run_id": run_id,
        "platform": platform_name,
        "content_fields": fields,
        "first_hour_action": str(fields["first_hour_action"]).strip(),
        "published_url": url,
        "external_evidence_uri": evidence,
        "status": "published" if url and _external_evidence(evidence) and external_verified else ("pending_manual" if url else "draft"),
    }


def _public_url(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        parts = urlsplit(text)
    except ValueError as exc:
        raise PublishingPackageError("published_url must be a public URL") from exc
    if parts.scheme not in {"http", "https"} or not parts.netloc or parts.username or parts.password or parts.fragment:
        raise PublishingPackageError("published_url must be a public URL")
    host = (parts.hostname or "").lower().rstrip(".")
    try:
        host_ip = ipaddress.ip_address(host)
    except ValueError:
        host_ip = None
    if (
        host in {"localhost", "localhost.localdomain"}
        or host.endswith(".localhost")
        or host.endswith(".local")
        or (
            host_ip is not None
            and (
                host_ip.is_private
                or host_ip.is_loopback
                or host_ip.is_link_local
                or host_ip.is_reserved
                or host_ip.is_multicast
                or host_ip.is_unspecified
            )
        )
    ):
        raise PublishingPackageError("published_url must be a public URL")
    return text


def _external_evidence(value: str) -> bool:
    return has_external_evidence(value)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class PublishingPackageProducer:
    """Produce and read an idempotent, structured package for one run."""

    def __init__(self, *, tenant_id: str, opportunity_id: str, root: str | None = None) -> None:
        self.tenant_id = require_tenant_id(tenant_id)
        self.opportunity_id = str(opportunity_id or "").strip()
        if not self.opportunity_id:
            raise PublishingPackageError("opportunity_id is required")
        self.vault = MediaVault(tenant_id=self.tenant_id, root=root)
        self.path = self.vault.business_dir(self.opportunity_id) / PACKAGE_FILENAME

    def produce(
        self,
        *,
        creation_run_id: str,
        platform: str,
        content_fields: Mapping[str, Any],
        published_url: str = "",
        external_evidence_uri: str = "",
        external_verified: bool = False,
        version: str = "1",
        idempotency_identity: str = "",
    ) -> dict[str, Any]:
        run_id = str(creation_run_id or "").strip()
        platform_name = str(platform or "").strip()
        payload = build_publishing_package_payload(
            opportunity_id=self.opportunity_id,
            creation_run_id=run_id,
            platform=platform_name,
            content_fields=content_fields,
            published_url=published_url,
            external_evidence_uri=external_evidence_uri,
            external_verified=external_verified,
            version=version,
            idempotency_identity=idempotency_identity,
            tenant_id=self.tenant_id,
        )
        if self.path.exists():
            existing = self.read()
            if existing.get("idempotency_identity") != payload["idempotency_identity"]:
                raise PublishingPackageError("publishing package identity was reused with different content")
            if _canonical_json(existing) != _canonical_json(payload):
                raise PublishingPackageError("publishing package replay payload differs")
            return {**existing, "replayed": True}
        artifact = self.vault.write_json_artifact(
            self.path.parent,
            PACKAGE_FILENAME,
            payload,
            owner_type="BusinessOpportunity",
            owner_id=self.opportunity_id,
            artifact_type="publishing_package",
            artifact_id=payload["package_id"],
        )
        return {**payload, "artifact_uri": artifact["uri"], "artifact_hash": artifact["content_hash"], "replayed": False}

    def read(self) -> dict[str, Any]:
        if not self.path.is_file():
            raise PublishingPackageError("publishing package is not available")
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PublishingPackageError("publishing package is unreadable") from exc
        if not isinstance(payload, dict) or payload.get("schema_version") != PUBLISHING_PACKAGE_SCHEMA_VERSION:
            raise PublishingPackageError("publishing package schema is unsupported")
        if payload.get("tenant_id") != self.tenant_id or payload.get("opportunity_id") != self.opportunity_id:
            raise PublishingPackageError("publishing package ownership mismatch")
        return payload
