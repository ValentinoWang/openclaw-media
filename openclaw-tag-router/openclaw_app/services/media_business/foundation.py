"""Provider-independent safety primitives for Media Web business pages."""

from __future__ import annotations

import base64
import copy
import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Mapping

from common.canonical_digest import digest_hex


class MediaBusinessError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


class EmptyState(MediaBusinessError):
    def __init__(self):
        super().__init__("empty", "no records")


class NotFound(MediaBusinessError):
    def __init__(self):
        super().__init__("resource_not_found", "resource not found")


class Forbidden(MediaBusinessError):
    def __init__(self, message: str = "not permitted"):
        super().__init__("forbidden", message)


class Conflict(MediaBusinessError):
    def __init__(self, message: str = "revision conflict"):
        super().__init__("revision_conflict", message)


class Validation(MediaBusinessError):
    def __init__(self, message: str = "invalid request", *, code: str = "validation_error"):
        super().__init__(code, message)


class ProtectedDocumentBlock(MediaBusinessError):
    def __init__(self, block_ids: set[str]):
        self.block_ids = tuple(sorted(block_ids))
        super().__init__(
            "unsupported_document_block",
            "protected document blocks cannot be changed or exported",
        )


class ResultKind(str, Enum):
    SUCCESS = "success"
    EMPTY = "empty"
    NOT_FOUND = "not_found"
    FORBIDDEN = "forbidden"
    CONFLICT = "conflict"
    VALIDATION = "validation"


@dataclass(frozen=True)
class ServiceResult:
    kind: ResultKind
    value: Any = None
    message: str | None = None

    @classmethod
    def empty(cls) -> "ServiceResult":
        return cls(ResultKind.EMPTY)

    @classmethod
    def not_found(cls) -> "ServiceResult":
        return cls(ResultKind.NOT_FOUND)

    @classmethod
    def forbidden(cls) -> "ServiceResult":
        return cls(ResultKind.FORBIDDEN)

    @classmethod
    def conflict(cls) -> "ServiceResult":
        return cls(ResultKind.CONFLICT)

    @classmethod
    def validation(cls, message: str) -> "ServiceResult":
        return cls(ResultKind.VALIDATION, message=message)


@dataclass(frozen=True)
class TenantContext:
    tenant_id: str
    user_public_id: str
    is_admin: bool = False
    audit_reason: str | None = None


def require_context(
    context: TenantContext | None,
    target_tenant: str | None = None,
) -> TenantContext:
    if context is None or not context.tenant_id.strip():
        raise Forbidden("tenant context is required")
    if target_tenant and target_tenant != context.tenant_id:
        if not context.is_admin:
            raise NotFound()
        if not context.audit_reason or not context.audit_reason.strip():
            raise Forbidden("admin cross-tenant access requires an audit reason")
    return context


_FORBIDDEN_PUBLIC_NAMES = {
    "accesstoken",
    "apptoken",
    "credential",
    "credentialvalue",
    "feishurecordid",
    "feishutableid",
    "larktableurl",
    "localpath",
    "rawmodelresponse",
    "rawprompt",
    "rawresponse",
    "recordid",
    "refreshtoken",
    "secret",
    "targettenantid",
    "tenantid",
    "token",
}


def _normalized_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def public_projection(value: Any) -> Any:
    """Return a detached public value or fail closed on private field names."""

    def walk(item: Any) -> Any:
        if isinstance(item, dict):
            projected: dict[str, Any] = {}
            for key, child in item.items():
                if not isinstance(key, str):
                    raise Validation("public response keys must be strings")
                normalized = _normalized_name(key)
                if normalized in _FORBIDDEN_PUBLIC_NAMES or any(
                    token in normalized
                    for token in ("credential", "localpath", "feishurecord", "rawprompt")
                ):
                    raise Validation(f"forbidden public field: {key}")
                projected[key] = walk(child)
            return projected
        if isinstance(item, list):
            return [walk(child) for child in item]
        return copy.deepcopy(item)

    return walk(value)


def body_checksum(body: dict[str, Any]) -> str:
    return digest_hex(body, allow_nan=True)


# --- Signed opaque-token codec (HIGH-28 c4) ---------------------------------
#
# admin_access.py, admin_tenants.py, and admin_billing.py each independently
# implemented the exact same HMAC-signed opaque-token codec: JSON-encode a
# mapping with sorted keys and compact separators, HMAC-SHA256 it, keep the
# first 18 signature bytes, and base64url-encode body + b"." + signature
# with the trailing "=" padding stripped. admin_tenants.py's version is the
# most complete of the three -- it is the only one that accepts a `pattern`
# override, needed for its 8-512 char cursor tokens (longer than an 8-160
# char public id) -- so this is that implementation, moved here verbatim
# except for parameterizing the "invalid token" exception via an `error`
# factory in place of the hard-coded AdminTenantsNotFound.
#
# admin_tenants.py and admin_billing.py already derive their HMAC key from
# the configured secret identically (sha256(label + b":" + secret)) and had
# already converged on that shared shape independently of this pass (TI-10);
# derive_namespace_secret below is that shape, moved verbatim (guard +
# hashing) from admin_tenants.py's former `_secret` helper -- only the
# ValueError text lost its hard-coded page prefix ("B12 ...") since the
# function is now shared. `label` is folded into the digest, so callers must
# keep passing the exact label text they always have ("public-id-secret",
# "cursor-secret", ...); changing it would silently invalidate every public
# ID or cursor already issued under the old label.
#
# admin_access.py derives its public-id/cursor secrets a different,
# unlabeled way (see its own module for that derivation) and is NOT moved
# onto this shape: doing so would change every public ID it has ever issued
# -- a breaking key-rotation change, not a refactor -- so admin_access.py
# keeps deriving its own secret and only delegates the encode/decode
# algorithm below.

PUBLIC_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{8,160}$")

SIGNATURE_BYTES = 18


def derive_namespace_secret(secret: bytes, label: str) -> bytes:
    if not isinstance(secret, bytes) or len(secret) < 16:
        raise ValueError(f"{label} must be at least 16 bytes")
    return hashlib.sha256(label.encode("ascii") + b":" + secret).digest()


def encode_signed(value: Mapping[str, Any], secret: bytes) -> str:
    body = json.dumps(dict(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    signature = hmac.new(secret, body, hashlib.sha256).digest()[:SIGNATURE_BYTES]
    return base64.urlsafe_b64encode(body + b"." + signature).decode("ascii").rstrip("=")


def decode_signed(
    token: Any,
    secret: bytes,
    *,
    error: Callable[[], Exception],
    pattern: "re.Pattern[str]" = PUBLIC_ID_PATTERN,
) -> dict[str, Any]:
    """Verify and decode one ``encode_signed()`` token, or raise ``error()``.

    ``error()`` is invoked -- never a caught-and-reraised prior exception --
    for every failure mode: pattern mismatch, malformed base64, a missing or
    wrong signature, malformed JSON, or a non-object payload. Callers pass
    their own not-found/invalid-request exception factory so each service
    keeps its existing exception type, HTTP status, and field name.
    """
    if not isinstance(token, str) or pattern.fullmatch(token) is None:
        raise error()
    try:
        padded = token + "=" * (-len(token) % 4)
        raw = base64.urlsafe_b64decode(padded.encode("ascii"))
        body, signature = raw.rsplit(b".", 1)
    except ValueError as exc:
        # binascii.Error (malformed base64) is itself a ValueError subclass;
        # a token with no "." separator raises ValueError from rsplit too.
        raise error() from exc
    expected = hmac.new(secret, body, hashlib.sha256).digest()[:SIGNATURE_BYTES]
    if not hmac.compare_digest(signature, expected):
        raise error()
    try:
        decoded = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise error() from exc
    if not isinstance(decoded, dict):
        raise error()
    return decoded


# --- Signed cursor codec (HIGH-29 c2) ---------------------------------------
#
# decisions.py, runs.py, and reviews.py each independently implemented the
# same signed-cursor wire format: HMAC-SHA256(key, aad + raw_json_body) as a
# full 32-byte digest, base64url(raw_json_body + b"." + signature) with
# padding stripped. This is a DIFFERENT format from the admin_* signed
# opaque-token codec above (encode_signed/decode_signed): that one truncates
# its signature to 18 bytes and rsplits on the last b"."; this one keeps the
# full 32-byte signature and slices the last 33 bytes positionally, so a
# token from one codec is not decodable by the other. publishing.py's cursor
# format is a further, incompatible third shape (a two-segment encoding with
# two separate keys) and is explicitly out of scope here -- per the HIGH-29
# audit, it belongs to a later, versioned-release pass, not this pure
# refactor. overview.py and usage_billing.py carry the same c2 shape too but
# were flagged as "missed implementations" to fold in during that next
# pass -- also not touched here.
#
# `aad` has no default here, deliberately. All of these services share one
# HMAC secret injected by server_cli.py; today the only thing stopping a
# cursor issued by one service from being replayed against another is each
# service's own distinct `_CURSOR_AAD` constant, folded into the signed
# bytes. Giving `aad` a default would make it easy for a future call site to
# accidentally drop that isolation. This pass does not rename, share, or
# otherwise touch any service's `_CURSOR_AAD` value, and does not touch how
# any of the three derives its `_cursor_secret` (runs.py hashes its input
# secret with sha256 before use; decisions.py and reviews.py do not -- both
# left exactly as they were).
#
# Also NOT consolidated here: the payload-semantics checks each service's
# own _decode_cursor performs after calling verify_cursor() -- the
# {"v", "scope"} version/scope match and the tenantTag re-derivation check
# that binds a cursor to the tenant that requested it. Those depend on each
# resource's own cursor payload shape and error type, not the wire codec.


def sign_cursor(payload: Mapping[str, Any], *, key: bytes, aad: bytes) -> str:
    raw = json.dumps(dict(payload), ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    signature = hmac.new(key, aad + raw, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(raw + b"." + signature).decode("ascii").rstrip("=")


def verify_cursor(
    token: Any,
    *,
    key: bytes,
    aad: bytes,
    error: Callable[[], Exception],
) -> dict[str, Any]:
    """Verify and decode one ``sign_cursor()`` token, or raise ``error()``.

    Only unwraps the wire format (base64url of the JSON body plus a
    trailing 32-byte HMAC signature) and returns the decoded JSON body --
    callers remain responsible for validating the payload's own fields
    (version, scope, tenant binding, ...) exactly as they did before this
    codec was extracted.
    """
    if not isinstance(token, str) or not token:
        raise error()
    try:
        padded = token + "=" * (-len(token) % 4)
        signed = base64.urlsafe_b64decode(padded.encode("ascii"))
        if len(signed) < 33 or signed[-33] != ord("."):
            raise ValueError("cursor separator is missing")
        raw, signature = signed[:-33], signed[-32:]
        expected = hmac.new(key, aad + raw, hashlib.sha256).digest()
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise error() from exc
    if not hmac.compare_digest(signature, expected):
        raise error()
    return payload


# --- Idempotency-key format policies (TI-04) -------------------------------
#
# Every IF2 write endpoint (documents, admin_access, admin_billing,
# admin_upstreams, runs, tracks) and the IF2 projection layer in
# stage1_organization_provisioning.py independently re-implement the exact
# same 8-128 character alphanumeric+"_-" regex fullmatch, with no stripping
# or other normalization -- differing only in which exception class and
# field name they raise. IF2_KEY captures that.
#
# The device/Mac transport protocol (device_job_service.py,
# cloud_media_task_receiver.py) uses the same alphabet but a 1-128 length
# floor, since a device-generated key can be shorter than IF2's 8-char
# minimum. DEVICE_KEY captures that.
#
# stage1_organization_provisioning._resource_run_key is NOT the same
# contract, despite validating "an idempotency key": its own docstring says
# it deliberately does not apply IF2's alphabet, because orchestrator child
# keys are built as f"{parent_key}:{step}". Reading its actual
# implementation (_text() + a length check) shows it does not restrict the
# character set at all beyond rejecting control characters and untrimmed
# input -- it is not simply "IF2_KEY plus a colon". Imposing an
# alphanumeric+"_-:" regex here would be a real tightening this pass has no
# way to verify against whatever resource-run keys already exist in
# production, so RESOURCE_RUN_KEY reproduces the actual current algorithm
# (trim-mismatch rejection + control-character rejection + length bounds,
# no character-class restriction) rather than the narrower shape a name like
# "allows colon" might suggest.

IDEMPOTENCY_KEY_CHARSET = "A-Za-z0-9_-"


@dataclass(frozen=True)
class IdempotencyKeyPolicy:
    """A named idempotency-key format contract.

    ``pattern`` set: fullmatch the original (unstripped) value against it --
    the IF2_KEY / DEVICE_KEY shape, where the alphabet already excludes
    whitespace and control characters so no separate stripping is needed.

    ``pattern`` is ``None``: fall back to the RESOURCE_RUN_KEY shape --
    accept any non-control character, but reject the value outright if it
    is not already trimmed, and enforce ``minimum``/``maximum`` length.
    """

    pattern: "re.Pattern[str] | None"
    minimum: int
    maximum: int


IF2_KEY = IdempotencyKeyPolicy(
    pattern=re.compile(rf"^[{IDEMPOTENCY_KEY_CHARSET}]{{8,128}}$"), minimum=8, maximum=128
)
DEVICE_KEY = IdempotencyKeyPolicy(
    pattern=re.compile(rf"^[{IDEMPOTENCY_KEY_CHARSET}]{{1,128}}$"), minimum=1, maximum=128
)
# stage1_organization_provisioning._resource_run_key is NOT IF2_KEY's
# contract, despite validating "an idempotency key": its own docstring says
# it deliberately does not apply IF2's alphabet, because orchestrator child
# keys are built as f"{parent_key}:{step}". Reading its actual
# implementation (_text() + a length check) shows it does not restrict the
# character set at all beyond rejecting control characters and untrimmed
# input -- it is not simply "IF2_KEY plus a colon". Imposing an
# alphanumeric+"_-:" regex here would be a real tightening this pass has no
# way to verify against whatever resource-run keys already exist in
# production, so RESOURCE_RUN_KEY reproduces the actual current algorithm
# (pattern=None) rather than the narrower shape a name like "allows colon"
# might suggest.
RESOURCE_RUN_KEY = IdempotencyKeyPolicy(pattern=None, minimum=8, maximum=160)


def idempotency_key(
    value: Any,
    *,
    error: Callable[[], Exception],
    policy: IdempotencyKeyPolicy = IF2_KEY,
) -> str:
    """Validate ``value`` against ``policy`` and return its canonical form.

    Every IF2 write endpoint (documents, admin_access, admin_billing,
    admin_upstreams, runs, tracks) and the IF2 projection layer in
    stage1_organization_provisioning.py independently re-implemented this
    exact 8-128 character alphanumeric+"_-" regex fullmatch with no
    stripping, differing only in which exception class and field name they
    raise on failure -- that is IF2_KEY, the default. The device/Mac
    transport protocol (device_job_service.py, cloud_media_task_receiver.py)
    uses the same alphabet with a 1-128 length floor since a device-
    generated key can be shorter than IF2's 8-char minimum -- DEVICE_KEY.
    """
    if not isinstance(value, str):
        raise error()
    if policy.pattern is not None:
        if policy.pattern.fullmatch(value) is None:
            raise error()
        return value
    normalized = value.strip()
    if (
        value != normalized
        or not normalized
        or not (policy.minimum <= len(normalized) <= policy.maximum)
        or any(ord(character) < 32 for character in normalized)
    ):
        raise error()
    return normalized


_RICH_TEXT_TYPES = {"paragraph", "quote", *(f"heading_{level}" for level in range(1, 10))}
_LIST_TYPES = {"bullet_list", "ordered_list"}
_MARKS = {"bold", "italic", "underline", "strike", "inline_code"}
_BLOCK_TYPES = _RICH_TEXT_TYPES | _LIST_TYPES | {
    "todo_item",
    "code_block",
    "divider",
    "callout",
    "image",
    "attachment",
    "table",
    "data_snapshot",
}


def _require_keys(value: dict[str, Any], required: set[str], label: str) -> None:
    if set(value) != required:
        raise Validation(f"{label} contains undeclared or missing fields")


def _validate_inline_nodes(value: Any, label: str) -> None:
    if not isinstance(value, list):
        raise Validation(f"{label} must be a list")
    for node in value:
        if not isinstance(node, dict):
            raise Validation(f"{label} contains an invalid inline node")
        _require_keys(node, {"type", "text", "marks"}, label)
        if node["type"] != "text" or not isinstance(node["text"], str):
            raise Validation(f"{label} contains invalid text")
        marks = node["marks"]
        if not isinstance(marks, list) or len(marks) != len({json.dumps(mark, sort_keys=True) for mark in marks}):
            raise Validation(f"{label} contains duplicate or invalid marks")
        for mark in marks:
            if isinstance(mark, str):
                if mark not in _MARKS:
                    raise Validation(f"{label} contains an unknown mark")
            elif isinstance(mark, dict):
                _require_keys(mark, {"type", "href", "title"}, label)
                if mark["type"] != "link" or not isinstance(mark["href"], str):
                    raise Validation(f"{label} contains an invalid link mark")
            else:
                raise Validation(f"{label} contains an invalid mark")


def _validate_list(block: dict[str, Any]) -> None:
    _require_keys(block, {"id", "type", "attrs", "items"}, "document list block")
    if block["attrs"] != {} or not isinstance(block["items"], list) or not block["items"]:
        raise Validation("invalid document list block")
    for item in block["items"]:
        if not isinstance(item, dict):
            raise Validation("invalid document list item")
        _require_keys(item, {"id", "content", "children"}, "document list item")
        _validate_inline_nodes(item["content"], "document list item")
        if not isinstance(item["children"], list):
            raise Validation("document list children must be a list")
        for child in item["children"]:
            _validate_block(child)
            if child["type"] not in _LIST_TYPES:
                raise Validation("document list children must be lists")


def _validate_table(block: dict[str, Any]) -> None:
    _require_keys(block, {"id", "type", "attrs", "rows"}, "document table")
    attrs = block["attrs"]
    if not isinstance(attrs, dict):
        raise Validation("invalid table attributes")
    _require_keys(attrs, {"semanticPurpose", "headerRowCount"}, "document table attributes")
    if attrs["semanticPurpose"] not in {
        "general",
        "storyboard",
        "publishing_checklist",
        "metric_snapshot",
        "evidence_index",
    } or attrs["headerRowCount"] != 1:
        raise Validation("invalid table attributes")
    rows = block["rows"]
    if not isinstance(rows, list) or not 1 <= len(rows) <= 9:
        raise Validation("lark table shape is unsupported", code="lark_table_shape_unsupported")
    cell_count = 0
    for row in rows:
        if not isinstance(row, dict):
            raise Validation("invalid document table row")
        _require_keys(row, {"id", "cells"}, "document table row")
        cells = row["cells"]
        if not isinstance(cells, list) or not 1 <= len(cells) <= 9:
            raise Validation("lark table shape is unsupported", code="lark_table_shape_unsupported")
        cell_count += len(cells)
        for cell in cells:
            if not isinstance(cell, dict):
                raise Validation("invalid document table cell")
            _require_keys(cell, {"id", "content"}, "document table cell")
            _validate_inline_nodes(cell["content"], "document table cell")
    if cell_count > 81:
        raise Validation("lark table shape is unsupported", code="lark_table_shape_unsupported")


def _validate_block(block: Any) -> None:
    if not isinstance(block, dict) or block.get("type") not in _BLOCK_TYPES:
        raise Validation("invalid document block")
    if not isinstance(block.get("id"), str) or not block["id"]:
        raise Validation("document block id is required")
    block_type = block["type"]
    if block_type in _RICH_TEXT_TYPES:
        _require_keys(block, {"id", "type", "attrs", "content"}, "rich text block")
        if block["attrs"] != {}:
            raise Validation("rich text attrs must be empty")
        if not block["content"]:
            raise Validation("rich text content must not be empty")
        _validate_inline_nodes(block["content"], "rich text block")
    elif block_type in _LIST_TYPES:
        _validate_list(block)
    elif block_type == "table":
        _validate_table(block)
    else:
        required = {
            "todo_item": {"id", "type", "attrs", "content"},
            "code_block": {"id", "type", "attrs", "text"},
            "divider": {"id", "type", "attrs"},
            "callout": {"id", "type", "attrs", "content"},
            "image": {"id", "type", "attrs"},
            "attachment": {"id", "type", "attrs"},
            "data_snapshot": {"id", "type", "attrs"},
        }[block_type]
        _require_keys(block, required, f"{block_type} block")


def validate_body(body: Any) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise Validation("invalid media.document.body.v1")
    _require_keys(body, {"schemaVersion", "blocks"}, "document body")
    if body["schemaVersion"] != "media.document.body.v1":
        raise Validation("invalid media.document.body.v1")
    blocks = body["blocks"]
    if not isinstance(blocks, list) or len(blocks) > 5000:
        raise Validation("invalid document blocks")
    seen: set[str] = set()
    for block in blocks:
        _validate_block(block)
        if block["id"] in seen:
            raise Validation("document block ids must be unique")
        seen.add(block["id"])
    return copy.deepcopy(body)


def assert_autosave_state(state: str) -> None:
    if state != "draft":
        raise Conflict("autosave only accepts draft revisions")


def assert_export_state(state: str) -> None:
    if state != "ready":
        raise Conflict("exports require a ready revision")


def preserve_protected_blocks(
    existing: dict[str, Any],
    incoming: dict[str, Any],
    protected_block_ids: set[str],
    targeted_block_ids: set[str] | None = None,
) -> dict[str, Any]:
    current = validate_body(existing)
    proposed = validate_body(incoming)
    if targeted_block_ids and protected_block_ids & targeted_block_ids:
        raise ProtectedDocumentBlock(protected_block_ids & targeted_block_ids)
    current_by_id = {block["id"]: block for block in current["blocks"]}
    proposed_by_id = {block["id"]: block for block in proposed["blocks"]}
    changed = {
        block_id
        for block_id in protected_block_ids
        if current_by_id.get(block_id) != proposed_by_id.get(block_id)
    }
    if changed:
        raise ProtectedDocumentBlock(changed)
    return proposed
