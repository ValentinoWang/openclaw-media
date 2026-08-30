"""Provider-independent safety primitives for Media Web business pages."""

from __future__ import annotations

import base64
import copy
import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Mapping
from uuid import UUID

from common.canonical_digest import canonical_json as _canonical_json


class MediaBusinessError(Exception):
    status = 500
    field: str | None = None

    def __init__(self, code: str, message: str, *, status: int = 500, field: str | None = None):
        self.code = code
        self.message = message
        self.status = status
        self.field = field
        super().__init__(message)


# --- Error-code literals and semantic base classes (exc-2) ------------------
#
# These eight codes were previously re-declared as string literals by every
# one of the 16 media_business services' own semantic exception subclasses
# (e.g. `super().__init__("invalid_request", message, status=400, ...)`).
# They are a frozen wire contract -- asserted in tests/ and rendered by the
# frontend's publicErrorMessages table -- so this pass only centralizes the
# literals and the five/nine matching base classes; it does not rename any
# of them. Four call sites are deliberately NOT normalized onto these codes
# because they are live, distinct contract values: admin_billing's 403 code
# "admin_required" (not "forbidden"), documents' 409 code
# "document_revision_conflict" (frozen by openapi.yaml's errorCodes list,
# not the generic "revision_conflict"), publishing's "field_unavailable" at
# status 500 (not the 503 "*_unavailable" codes used elsewhere), and
# usage_billing's UsageBillingConflict, whose code is "idempotency_conflict"
# despite the class being named "Conflict".

INVALID_REQUEST = "invalid_request"
FORBIDDEN = "forbidden"
RESOURCE_NOT_FOUND = "resource_not_found"
REVISION_CONFLICT = "revision_conflict"
IDEMPOTENCY_CONFLICT = "idempotency_conflict"
UNPROCESSABLE_ENTITY = "unprocessable_entity"
AUTHENTICATION_REQUIRED = "authentication_required"
INTERNAL_ERROR = "internal_error"


class EmptyState(MediaBusinessError):
    def __init__(self):
        super().__init__("empty", "no records")


class NotFound(MediaBusinessError):
    def __init__(self, message: str = "resource not found", *, status: int = 404):
        super().__init__(RESOURCE_NOT_FOUND, message, status=status)


class Forbidden(MediaBusinessError):
    def __init__(self, message: str = "not permitted", *, status: int = 403):
        super().__init__(FORBIDDEN, message, status=status)


class Conflict(MediaBusinessError):
    def __init__(self, message: str = "revision conflict", *, status: int = 409):
        super().__init__(REVISION_CONFLICT, message, status=status)


class IdempotencyConflict(MediaBusinessError):
    def __init__(
        self,
        message: str = "idempotency key was already used for another request",
        *,
        status: int = 409,
    ):
        super().__init__(IDEMPOTENCY_CONFLICT, message, status=status)


class Unprocessable(MediaBusinessError):
    def __init__(self, message: str = "unprocessable entity", *, status: int = 422):
        super().__init__(UNPROCESSABLE_ENTITY, message, status=status)


class Unauthorized(MediaBusinessError):
    def __init__(self, message: str = "authentication is required", *, status: int = 401):
        super().__init__(AUTHENTICATION_REQUIRED, message, status=status)


class InternalError(MediaBusinessError):
    def __init__(self, message: str = "internal error", *, status: int = 500):
        super().__init__(INTERNAL_ERROR, message, status=status)


class Validation(MediaBusinessError):
    def __init__(
        self,
        message: str = "invalid request",
        *,
        code: str = "validation_error",
        status: int = 400,
    ):
        super().__init__(code, message, status=status)


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


def error_status(error: BaseException) -> int:
    """Map any raised error to the HTTP status it should carry.

    Every media_business service used to re-implement this as a static
    method gated on its own local ``isinstance(error, XxxError)`` check
    (exc-3 audit). This single implementation duck-types instead of
    checking ``isinstance(error, MediaBusinessError)`` because four
    services (admin_upstreams/admin_billing/admin_tenants/admin_overview)
    still derive their own error classes from RuntimeError, not
    MediaBusinessError (exc-1 step 4 was deliberately skipped) -- so a
    class check here would wrongly fall back to 500 for those.
    """
    status = getattr(error, "status", None)
    return status if isinstance(status, int) else 500


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


# --- Tenant-id extraction wrapper (exc-4 Shape B, generalized by TI-02) -----
#
# tracks.py, assets.py (both AssetsService and AssetPreviewService), and
# document_resources.py each independently wrapped require_context() with
# the exact same four lines: call it, catch every exception (bare `except
# Exception`, swallowing require_context's own Forbidden/NotFound along with
# anything else) and re-raise the caller's own branded Forbidden, then strip
# the returned tenant_id and raise the same Forbidden again if it is empty.
# This is "Shape B" in the exc-4 audit -- distinct from "Shape A" (a plain
# `return require_context(context)` passthrough used by publishing/reviews/
# decisions/runs, left as inline require_context() calls) and "Shape C"
# (usage_billing/invites/overview, which carry real additional business
# logic and were left alone by exc-4).
#
# TI-02 folds usage_billing.py's Shape-C _tenant_id in too, via the
# ``canonical``/``deny_admin`` flags: it additionally rejects an admin
# session (``deny_admin``) and normalizes the tenant id through
# ``UUID(...)`` (``canonical``) before returning it. Every exception --
# including require_context's own Forbidden/NotFound, and even after
# exc-1 made every service's XxxError family an alias for
# MediaBusinessError -- becomes ``error()``; that matters because
# usage_billing's prior copy had a
#   except UsageBillingError: raise
#   except Exception as exc: raise UsageBillingForbidden() from exc
# double-except that, since exc-1, started silently bare-re-raising
# require_context's raw foundation.Forbidden/NotFound instead of wrapping
# it (UsageBillingError now matches everything MediaBusinessError does).
# No test exercised that path, so it shipped unnoticed; tenant_id_of's
# single bare ``except Exception`` fixes it for every caller by
# construction, not just usage_billing.


def tenant_id_of(
    context: "TenantContext | None",
    *,
    error: Callable[[], Exception],
    canonical: bool = False,
    deny_admin: bool = False,
) -> str:
    """require_context() plus tenant-id extraction and normalization.

    ``deny_admin=True`` additionally rejects an admin session outright
    (only usage_billing denies tenant-scoped reads to admins).
    ``canonical=True`` additionally normalizes the tenant id through
    ``UUID(...)`` instead of the plain strip-and-reject-empty check the
    other callers use (only usage_billing needs this). Every exception --
    from require_context, the admin check, or UUID coercion -- becomes
    ``error()``.
    """
    try:
        checked = require_context(context)
    except Exception as exc:
        raise error() from exc
    if deny_admin and checked.is_admin:
        raise error()
    if canonical:
        try:
            return str(UUID(checked.tenant_id))
        except Exception as exc:
            raise error() from exc
    tenant_id = str(checked.tenant_id).strip()
    if not tenant_id:
        raise error()
    return tenant_id


def require_context_branded(
    context: "TenantContext | None",
    forbidden: Callable[[], Exception],
) -> "TenantContext":
    """require_context() with the exception rebranded to the caller's own
    Forbidden subclass ("Shape A" in the exc-4 audit -- publishing, reviews,
    decisions, and runs each wrapped `try: return require_context(...)
    except Exception: raise XxxForbidden()` verbatim).

    Deliberately calls ``forbidden()`` with no arguments so it falls back to
    its own branded default message rather than foundation's generic
    "tenant context is required" -- at least one caller's tests assert the
    branded exception *type* via ``pytest.raises(RunsForbidden)`` (not just
    status), which a bare `require_context()` call would fail since
    ``foundation.Forbidden`` is not a subclass of ``RunsForbidden``. This is
    the explicit message-preservation choice the exc-4 audit asked for.
    """
    try:
        return require_context(context)
    except Exception as exc:
        raise forbidden() from exc


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


def canonical_json(value: Any) -> str:
    """Canonical JSON text for cursor/checksum bodies (c6 audit).

    Sorted keys, compact separators, non-ASCII kept literal
    (``ensure_ascii=False``), NaN/Infinity allowed through rather than
    rejected (``allow_nan=True``) -- matching what every media_business
    call site of this shape already did via a bare, unguarded
    ``json.dumps(value, ensure_ascii=False, sort_keys=True,
    separators=(",", ":"))`` call. Thin wrapper over
    ``common.canonical_digest.canonical_json``, whose own default is the
    stricter ``allow_nan=False``.
    """
    return _canonical_json(value, allow_nan=True)


def canonical_json_bytes(value: Any) -> bytes:
    return canonical_json(value).encode("utf-8")


def body_checksum(body: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(body)).hexdigest()


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


# --- public_id validation (TI-03) --------------------------------------------
#
# 13+ media_business modules each independently re-compiled this exact
# regex; most also wrote a matching validator that raises one of two
# exceptions depending on whether the id came from a request (400) or a
# database read (500). runs.py's `_public_id(value, label, error_type)`
# is the most parameterized of them (the others hardcode one exception
# type per function, needing two functions for the 400-vs-500 split) --
# this is that shape, generalized.


def public_id(value: Any, label: str, error_type: Callable[[str], Exception]) -> str:
    if not isinstance(value, str) or PUBLIC_ID_PATTERN.fullmatch(value) is None:
        raise error_type(f"{label} is invalid")
    return value


def prefixed_public_id(
    value: Any,
    label: str,
    prefix: str,
    error_type: Callable[[str], Exception],
) -> str:
    """A public id with a required literal prefix, consuming part of the
    same 8-160 total-length budget PUBLIC_ID_PATTERN uses (e.g.
    ``prefix="asset_"`` reproduces source_asset_projection.py's own
    ``asset_[A-Za-z0-9_-]{2,154}`` pattern exactly: 6-char prefix + 2..154
    = 8..160 total, same as the unprefixed pattern). NOT used against
    source_asset_projection.py itself in this pass -- that module's
    pattern is deliberately left untouched (see TI-03 audit); this
    exists for the next caller that needs a prefixed variant.
    """
    suffix_min, suffix_max = 8 - len(prefix), 160 - len(prefix)
    pattern = re.compile(rf"^{re.escape(prefix)}[A-Za-z0-9_-]{{{suffix_min},{suffix_max}}}$")
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise error_type(f"{label} is invalid")
    return value


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


# --- UTC timestamp coercion (TF-04, step 1 of 2) ----------------------------
#
# runs.py, assets.py, tracks.py, invites.py, usage_billing.py, decisions.py,
# reviews.py, publishing.py, and overview.py each independently re-implement
# the same core steps: accept either a datetime or an ISO-8601 string
# (treating a trailing "Z" as "+00:00"), reject anything else, and either
# require a timezone or (for the "lenient" callers) silently assume UTC on a
# naive value, before normalizing the result to UTC. coerce_utc is that core,
# extracted from runs.py's former _timestamp_value.
#
# Every call site keeps its own _timestamp_value / _timestamp /
# _require_timestamp shell -- same function name, same signature, same
# exception type(s), same message text, same allow-naive policy -- and only
# its body now delegates here through an `error(label, reason)` factory it
# supplies. `reason` is one of:
#   "missing" -- value is None, an empty/whitespace-only string, or not a
#                str/datetime at all
#   "invalid" -- a non-empty string that fails datetime.fromisoformat
#   "naive"   -- parsed successfully but carries no tzinfo/utcoffset and
#                allow_naive is False
# Some callers use one message for every reason (runs.py, assets.py,
# tracks.py, invites.py, usage_billing.py all use one text for
# "missing"/"invalid" and a second, distinct text for "naive"); others
# (decisions.py's and reviews.py's lenient _timestamp) use a third, distinct
# "missing" message. Preserving each module's own reason-to-message mapping
# -- not merging them into one shared message -- is the point of this pass;
# only the parsing/validation mechanics are shared. allow_none exists for
# callers that treat a bare ``None`` as a valid "not set" value rather than
# an error.
#
# This is step 1 of 2 (TF-04 audit). Output-format unification (the "Z"
# suffix some callers produce vs the "+00:00" offset datetime.isoformat()
# naturally produces -- several of these strings are compared byte-for-byte
# as pagination cursors or revision digests) is explicitly out of scope for
# this pass and is deliberately not attempted here.


def coerce_utc(
    value: Any,
    label: str,
    *,
    error: Callable[[str, str], Exception],
    allow_naive: bool = False,
    allow_none: bool = False,
) -> datetime | None:
    """Parse ``value`` into a UTC-normalized ``datetime``, or raise ``error(label, reason)``."""
    if allow_none and value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError as exc:
            raise error(label, "invalid") from exc
    else:
        raise error(label, "missing")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        if allow_naive:
            parsed = parsed.replace(tzinfo=timezone.utc)
        else:
            raise error(label, "naive")
    return parsed.astimezone(timezone.utc)


def utc_z_text(
    value: Any,
    label: str,
    *,
    error: Callable[[str, str], Exception],
    allow_naive: bool = False,
    allow_none: bool = False,
) -> str | None:
    """``coerce_utc`` plus the "Z"-suffixed text form some callers store/return."""
    parsed = coerce_utc(value, label, error=error, allow_naive=allow_naive, allow_none=allow_none)
    if parsed is None:
        return None
    return parsed.isoformat().replace("+00:00", "Z")


# --- Admin-audit idempotency-key lookup (gap1 audit) -------------------------
#
# admin_access.py, admin_upstreams.py, and admin_billing.py's Postgres
# storage classes each independently wrote the same admin_audit
# idempotency-key SELECT. Canonical is admin_billing's prior copy: the
# only one (tied with admin_upstreams) whose ORDER BY carries an `id DESC`
# tiebreak -- admin_access's former copy sorted by `created_at DESC` alone,
# and since admin_audit.created_at defaults to now(), several rows written
# in the same transaction can share an identical timestamp, making which
# row it read back nondeterministic. Folding admin_access onto this shared
# implementation is a real determinism fix, not just deduplication.
#
# Deliberately NOT unified: the three services raise three different
# exception types at three different HTTP statuses for corrupt metadata
# (AdminAccessInternalError=500, AdminUpstreamsUnavailable=503,
# AdminBillingInternalError=500) -- ``on_invalid`` is a zero-argument
# factory each caller supplies so its own exception type and status survive
# unchanged. Each storage class keeps its own one-line delegating
# find_idempotency method; only the query/parsing body moved here.


def find_admin_audit_idempotency(
    connection: Any,
    actor_user_id: Any,
    operation: str,
    key: str,
    *,
    on_invalid: Callable[[], Exception],
) -> dict[str, Any] | None:
    """Look up a previously-recorded admin_audit row by idempotency key.

    Returns the decoded ``metadata`` mapping, or ``None`` if no matching
    audit row exists. Raises ``on_invalid()`` if the stored metadata is
    present but is not valid JSON or does not decode to an object --
    always a genuine data-corruption case, never a not-found case.
    """
    row = connection.execute(
        """
        SELECT metadata
        FROM openclaw_account.admin_audit
        WHERE actor_user_id = %s
          AND action = %s
          AND metadata ->> 'idempotencyKey' = %s
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        FOR UPDATE
        """,
        (actor_user_id, operation, key),
    ).fetchone()
    if row is None:
        return None
    metadata = row[0]
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except json.JSONDecodeError as exc:
            raise on_invalid() from exc
    if not isinstance(metadata, dict):
        raise on_invalid()
    return metadata


# --- Cursor result normalization (gap1 audit) --------------------------------
#
# runs.py, publishing.py, reviews.py, decisions.py, and documents.py (the
# last for _fetchone only) each independently wrote the same normalization
# over whatever a fake/real DB cursor's fetchone()/fetchall() -- or a bare
# list/tuple test stub standing in for one -- returns. Moved verbatim from
# runs.py, the majority form (5 modules, 52 call sites). NOT the same
# family as stage1_postgres_provisioning._one/_all or
# stage1_administrator_authorization._rows, which use a getattr+callable
# check instead of hasattr and return None/[] rather than falling back to
# a list/tuple's first element -- those live outside media_business and
# are explicitly out of scope for this pass.


def _fetchone(cursor: Any) -> Any:
    if hasattr(cursor, "fetchone"):
        return cursor.fetchone()
    if isinstance(cursor, (list, tuple)):
        return cursor[0] if cursor else None
    return None


def _fetchall(cursor: Any) -> list[Any]:
    if hasattr(cursor, "fetchall"):
        return list(cursor.fetchall())
    if isinstance(cursor, (list, tuple)):
        return list(cursor)
    return []


# --- jsonb column -> dict Row mapping (gap1 audit) ---------------------------
#
# publishing.py, reviews.py, runs.py, and decisions.py each independently
# wrote the same jsonb-decode: accept either an already-decoded Mapping or
# a JSON string, decode it (raising a controlled business error rather
# than letting json.JSONDecodeError escape uncaught), reject anything that
# isn't an object, and return a *copy* (dict(value)) so callers mutating
# the result never alias a cursor row or cached object. Moved verbatim
# from publishing.py's former _json_object, the majority form (4 modules,
# 21 call sites). ``error`` is a caller-supplied ``(message) -> Exception``
# factory so each service keeps its own exception type.
#
# tracks.py, usage_billing.py, admin_tenants.py, documents.py, and
# overview.py have their own, behaviorally-divergent versions of this
# (uncopied returns, dict-only isinstance checks, missing try/except,
# hardcoded messages, or an extra indirection) -- deliberately NOT touched
# here; see the gap1 audit for what would have to change at each of their
# call sites before it would be safe to converge them too.


def json_object(value: Any, label: str, *, error: Callable[[str], Exception]) -> dict[str, Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise error(f"{label} is not valid JSON") from exc
    if not isinstance(value, Mapping):
        raise error(f"{label} is not an object")
    return dict(value)


# --- pageSize validation (c1 audit) ------------------------------------------
#
# Eleven media_business modules each independently wrote the same pageSize
# guard: reject anything that isn't a plain int (explicitly rejecting
# bool, since bool is an int subclass in Python) outside 1..100, using one
# of two competing type-check spellings (`type(value) is not int` vs
# `isinstance(value, bool) or not isinstance(value, int)` -- equivalent
# for bool, but the isinstance form is the one that also correctly
# rejects other bool-like int subclasses, hence "bool-rejecting isinstance
# form"). DEFAULT_PAGE_SIZE is a live per-page 20-vs-30 contract and stays
# per-module; only the validator and the MAX_PAGE_SIZE=100 ceiling (which
# is identical everywhere) are centralized here.

MAX_PAGE_SIZE = 100


def page_size(value: Any, *, maximum: int = MAX_PAGE_SIZE, error: Callable[[str], Exception]) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
        raise error(f"pageSize must be between 1 and {maximum}")
    return value


# --- base64url encode/decode (c6 audit) --------------------------------------
#
# tracks.py, assets.py, and invites.py each independently wrote the same
# unpadded-base64url codec for cursor/checksum bytes; overview.py's
# _safe_base64_decode is a fourth spelling that additionally translates
# straight to a domain exception. This is invites.py's spelling verbatim
# (assets.py's is character-identical; tracks.py's differs only in
# `.decode()` vs `.decode("ascii")` and `not re.fullmatch(...)` vs
# `re.fullmatch(...) is None`, semantically identical either way).

_B64URL_PATTERN = re.compile(r"[A-Za-z0-9_-]+")


def b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def b64url_decode(value: str) -> bytes:
    if not value or _B64URL_PATTERN.fullmatch(value) is None:
        raise ValueError("invalid base64url")
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
