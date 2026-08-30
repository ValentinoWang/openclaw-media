"""Canonical JSON serialization and SHA-256 fingerprint primitives.

This module consolidates the "pure copy" canonical-JSON-then-sha256
fingerprint implementations that existed independently across the
codebase: every parameter here (``ensure_ascii=False``, ``sort_keys=True``,
``separators=(",", ":")``) matches the literal defaults each of those call
sites already used, so switching a call site to these helpers changes no
digest value for any input already representable by that call site.

This module intentionally has no opinion about *what* goes into ``value``
(no UUID/datetime normalization, no dataclass/set/bytes coercion, no
strict-JSON-only validation). Callers with that kind of domain-specific
normalization keep it themselves and pass the already-normalized value in
— folding that logic in here would silently change behavior for every
caller, which is exactly what this consolidation must not do.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any


def canonical_json(value: Any, *, ensure_ascii: bool = False, allow_nan: bool = False) -> str:
    """Serialize ``value`` with sorted keys and compact separators.

    ``allow_nan`` defaults to ``False`` here (stricter than ``json.dumps``'s
    own default of ``True``) for new callers that want to fail closed on a
    non-finite float rather than silently emit invalid JSON (``NaN`` /
    ``Infinity`` are not valid JSON tokens). Callers migrating an existing
    call site that never set ``allow_nan`` must pass ``allow_nan=True``
    explicitly to preserve their prior behavior exactly.
    """
    return json.dumps(value, ensure_ascii=ensure_ascii, sort_keys=True, separators=(",", ":"), allow_nan=allow_nan)


def digest_hex(value: Any, **kwargs: Any) -> str:
    """SHA-256 hex digest of ``canonical_json(value, **kwargs)``."""
    return hashlib.sha256(canonical_json(value, **kwargs).encode("utf-8")).hexdigest()


def digest_bytes(value: Any, **kwargs: Any) -> bytes:
    """SHA-256 raw digest of ``canonical_json(value, **kwargs)``."""
    return hashlib.sha256(canonical_json(value, **kwargs).encode("utf-8")).digest()


def prefixed_digest(value: Any, **kwargs: Any) -> str:
    """``"sha256:" + digest_hex(value, **kwargs)``."""
    return "sha256:" + digest_hex(value, **kwargs)


# dedup(r2): shared format for the "sha256:<64 hex>" digest strings produced
# by prefixed_digest() above and validated at the six Stage-2 fail-closed
# boundaries (stage2_candidate_assembly / stage2_external_document /
# stage2_artifact_state / stage2_release_gate / stage2_organization_pipeline
# / stage2_personal_store). Each of those sites keeps its own exception type
# and error code -- only the regex literal and the strip/length-guard/
# fullmatch logic are deduplicated here.
#
# Deliberately excludes the *bare* 64-hex form (no "sha256:" prefix) used by
# production_reconciliation_planner.py / media_archive_service.py /
# retail_billing.py / production_release_manifest.py -- that is a different
# wire contract, out of scope for this helper.
SHA256_PREFIXED_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


def normalize_prefixed_digest(value: Any) -> str | None:
    """Return the trimmed ``sha256:<64 hex>`` string, or ``None`` if invalid."""
    text = str(value or "").strip()
    if len(text) > 80:
        return None
    return text if SHA256_PREFIXED_RE.fullmatch(text) else None
