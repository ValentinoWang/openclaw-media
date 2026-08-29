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
