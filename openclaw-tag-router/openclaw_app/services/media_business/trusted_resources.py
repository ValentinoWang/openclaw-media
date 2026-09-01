"""Strict projection for persisted Feishu resource pointers.

The URL checks in this module establish only a canonical Feishu URL shape.
They do not prove that a URL belongs to the authenticated organization's
tenant; that remains a separate identity and ownership acceptance gate.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit


_RESOURCE_ID = re.compile(r"^[A-Za-z0-9_-]{8,160}$")
_RESOURCE_TYPES = {"wiki": "wiki", "docx": "docx", "base": "bitable"}
_LARK_DOCUMENT_PATH = re.compile(r"^/(wiki|docx)/([A-Za-z0-9_-]{8,160})$")
_LARK_DOCUMENT_ROOT_HOSTS = ("feishu.cn", "larksuite.com", "larkoffice.com")
_HOST_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")
_FEISHU_HOST_SUFFIX = ("feishu", "cn")


class TrustedOrganizationResourceError(ValueError):
    pass


def public_lark_document_url(value: Any) -> str | None:
    """Project a stored Lark document URL only when its public shape is safe."""

    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = urlsplit(value.strip())
        host = str(parsed.hostname or "").lower()
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
        or parsed.query
        or parsed.fragment
    ):
        return None
    if not any(host == root or host.endswith(f".{root}") for root in _LARK_DOCUMENT_ROOT_HOSTS):
        return None
    path_match = _LARK_DOCUMENT_PATH.fullmatch(parsed.path)
    if path_match is None:
        return None
    document_type, token = path_match.groups()
    return f"https://{host}/{document_type}/{token}"


def _tenant_feishu_host(parsed: Any) -> str:
    host = str(parsed.hostname or "").lower()
    labels = host.split(".")
    if (
        len(labels) < 3
        or tuple(labels[-2:]) != _FEISHU_HOST_SUFFIX
        or any(_HOST_LABEL.fullmatch(label) is None for label in labels[:-2])
    ):
        raise TrustedOrganizationResourceError("trusted organization resource URL host is invalid")
    return host


def _split_url(value: Any) -> Any:
    if not isinstance(value, str) or value != value.strip():
        raise TrustedOrganizationResourceError("trusted organization resource URL is invalid")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise TrustedOrganizationResourceError(
            "trusted organization resource URL is invalid"
        ) from exc
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
        or parsed.query
        or parsed.fragment
    ):
        raise TrustedOrganizationResourceError("trusted organization resource URL is invalid")
    _tenant_feishu_host(parsed)
    return parsed


def canonical_feishu_web_base_url(value: Any) -> str:
    """Return a tenant-scoped HTTPS Feishu web origin.

    This is configuration validation only; it does not establish organization
    membership or resource ownership.
    """

    parsed = _split_url(value)
    if parsed.path not in {"", "/"}:
        raise TrustedOrganizationResourceError("trusted Feishu web base URL path is invalid")
    return f"https://{_tenant_feishu_host(parsed)}"


def feishu_wiki_url(web_base_url: Any, node_token: Any) -> str:
    """Build a canonical Wiki URL from explicitly configured host and token."""

    if not isinstance(node_token, str) or node_token != node_token.strip():
        raise TrustedOrganizationResourceError("trusted Feishu Wiki node token is invalid")
    token = node_token.strip()
    if _RESOURCE_ID.fullmatch(token) is None:
        raise TrustedOrganizationResourceError("trusted Feishu Wiki node token is invalid")
    return f"{canonical_feishu_web_base_url(web_base_url)}/wiki/{token}"


def trusted_organization_resource(
    url: Any,
    expires_at: Any,
    *,
    retired: bool = False,
    now: datetime | None = None,
) -> dict[str, str | None] | None:
    if url is None or url == "":
        return None
    if not isinstance(retired, bool):
        raise TrustedOrganizationResourceError(
            "trusted organization resource retirement state is invalid"
        )
    if retired:
        raise TrustedOrganizationResourceError("trusted organization resource is retired")
    expires_text, expires_value = _timestamp_value(expires_at)
    if expires_value is not None:
        _, current_value = _timestamp_value(datetime.now(timezone.utc) if now is None else now)
        if current_value is None or expires_value <= current_value:
            raise TrustedOrganizationResourceError("trusted organization resource URL has expired")
    parsed = _split_url(url)
    parts = parsed.path.split("/")
    if (
        len(parts) != 3
        or parts[0] != ""
        or parts[1].lower() not in _RESOURCE_TYPES
        or _RESOURCE_ID.fullmatch(parts[2] or "") is None
        or parsed.path != f"/{parts[1].lower()}/{parts[2]}"
    ):
        raise TrustedOrganizationResourceError("trusted organization resource URL is invalid")
    return {
        "resourceType": _RESOURCE_TYPES[parts[1].lower()],
        "url": f"https://{_tenant_feishu_host(parsed)}/{parts[1].lower()}/{parts[2]}",
        "expiresAt": expires_text,
    }


def _timestamp_value(value: Any) -> tuple[str | None, datetime | None]:
    if value is None:
        return None, None
    if isinstance(value, datetime):
        current = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return current.isoformat(), current
    if not isinstance(value, str) or not value.strip():
        raise TrustedOrganizationResourceError(
            "trusted organization resource expiry is invalid"
        )
    text = value.strip()
    try:
        current = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise TrustedOrganizationResourceError(
            "trusted organization resource expiry is invalid"
        ) from exc
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return text, current


def _nullable_timestamp(value: Any) -> str | None:
    return _timestamp_value(value)[0]
