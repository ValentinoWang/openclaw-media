from __future__ import annotations

import base64

import pytest

from openclaw_app.adapters.audit_reason_header import (
    AuditReasonHeaderError,
    decode_audit_reason_header,
)


def _encode(value: str) -> str:
    payload = base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii").rstrip("=")
    return "utf8-base64url-v1." + payload


@pytest.mark.parametrize(
    "reason",
    ["中文审计原因：逐字回读", "foundation test", "  保留首尾空格  "],
)
def test_decodes_exact_utf8_reason(reason: str) -> None:
    assert decode_audit_reason_header(_encode(reason)) == reason


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        "中文审计原因",
        "%E4%B8%AD%E6%96%87",
        "utf8-base64url-v1.",
        "utf8-base64url-v1.Zg==",
        "utf8-base64url-v1.Zg+",
        "utf8-base64url-v2.Zg",
        "utf8-base64url-v1._w",
    ],
)
def test_rejects_noncanonical_wire_values(value: str | None) -> None:
    with pytest.raises(AuditReasonHeaderError):
        decode_audit_reason_header(value)


def test_rejects_oversized_decoded_value() -> None:
    with pytest.raises(AuditReasonHeaderError):
        decode_audit_reason_header(_encode("a" * 1025))
