from __future__ import annotations

import base64
import binascii
import re


AUDIT_REASON_HEADER = "X-Audit-Reason"
AUDIT_REASON_WIRE_PREFIX = "utf8-base64url-v1."
MAX_AUDIT_REASON_UTF8_BYTES = 1024
_WIRE_VALUE = re.compile(r"utf8-base64url-v1\.([A-Za-z0-9_-]+)\Z", re.ASCII)


class AuditReasonHeaderError(ValueError):
    """The audit reason header is absent or is not canonical wire data."""


def decode_audit_reason_header(value: str | None) -> str:
    if value is None:
        raise AuditReasonHeaderError("audit reason header is required")
    match = _WIRE_VALUE.fullmatch(value)
    if match is None:
        raise AuditReasonHeaderError("audit reason header uses an invalid wire format")

    payload = match.group(1)
    padding = "=" * (-len(payload) % 4)
    try:
        raw = base64.b64decode(payload + padding, altchars=b"-_", validate=True)
    except (binascii.Error, ValueError) as exc:
        raise AuditReasonHeaderError("audit reason header contains invalid base64url") from exc

    canonical_payload = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    if canonical_payload != payload:
        raise AuditReasonHeaderError("audit reason header is not canonical base64url")
    if not raw:
        raise AuditReasonHeaderError("audit reason must not be empty")
    if len(raw) > MAX_AUDIT_REASON_UTF8_BYTES:
        raise AuditReasonHeaderError("audit reason exceeds 1024 UTF-8 bytes")
    try:
        return raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise AuditReasonHeaderError("audit reason header is not valid UTF-8") from exc
