"""Shared, host-portable defaults for external tool roots.

Split out from ``common/social_runtime.py`` (rather than added there)
because that module had a concurrent in-flight edit from another agent at
the time this was written -- see the pe-06/pe-01 audit notes. Nothing here
depends on social_runtime; feel free to fold it back in once that file is
free, but it works standalone.
"""

from __future__ import annotations

import os
from pathlib import Path


def env_bool(name: str, default: bool = False) -> bool:
    """Parse a boolean-ish environment variable.

    Accepts (case-insensitively, after stripping whitespace) ``"1"``,
    ``"true"``, ``"yes"``, ``"on"`` as true; an unset variable, or any other
    value, falls back to ``default``.
    """
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def env_float(name: str, default: float, *, strict: bool = False) -> float:
    """Parse a float-valued environment variable.

    An unset variable falls back to ``default``. A malformed value also
    falls back to ``default`` unless ``strict=True``, in which case it
    raises ``ValueError`` -- tolerant-by-default matches the majority of
    this repo's existing ad hoc env-int/env-float readers, so a stray
    misconfiguration silently keeps the default instead of crashing at
    import/call time.
    """
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        if strict:
            raise
        return default


def env_int(name: str, default: int, *, strict: bool = False) -> int:
    """Parse an int-valued environment variable. See :func:`env_float`."""
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(float(raw))
    except ValueError:
        if strict:
            raise
        return default


def feishu_reminder_root() -> Path:
    """Resolve the openclaw-feishu-reminder checkout root.

    ``OPENCLAW_FEISHU_REMINDER_ROOT`` overrides the default of
    ``~/openclaw-feishu-reminder``. Several call sites re-derived this same
    fallback independently (and some hardcoded ``/home/ubuntu`` instead of
    resolving the home directory), so this is the one place that should own
    it going forward.
    """
    return Path(os.getenv("OPENCLAW_FEISHU_REMINDER_ROOT") or Path.home() / "openclaw-feishu-reminder").expanduser()
