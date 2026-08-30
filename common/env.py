"""Shared, host-portable defaults for external tool roots.

Split out from ``common/social_runtime.py`` (rather than added there)
because that module had a concurrent in-flight edit from another agent at
the time this was written -- see the pe-06/pe-01 audit notes. Nothing here
depends on social_runtime; feel free to fold it back in once that file is
free, but it works standalone.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

_ENV_KEY_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def parse_env_file(path: str | Path, *, require: bool = False) -> dict[str, str]:
    """Parse a ``KEY=VALUE`` env file into a dict, without touching ``os.environ``.

    The canonical .env reader for this repository (dedup audit pe-01, which
    counted 12+ hand-rolled copies with mutually inconsistent rules).
    Canonical semantics:

    - ``path`` accepts ``str | Path`` and is ``expanduser``-ed.
    - A missing (or otherwise unreadable) file returns ``{}``, unless
      ``require=True``, in which case the underlying ``OSError`` (e.g.
      ``FileNotFoundError``) propagates — for callers whose env file is a
      hard requirement.
    - Blank lines and ``#`` comment lines are skipped; a line-level
      ``export `` prefix is stripped, so ``export KEY=V`` parses as ``KEY``.
    - Keys must be shell-style identifiers (``[A-Za-z_][A-Za-z0-9_]*``
      after stripping surrounding whitespace); other lines are dropped.
    - Values are whitespace-stripped, then unwrapped exactly ONCE when
      wrapped in a matched pair of quotes (``X="v"`` / ``X='v'`` → ``v``).
      An unbalanced quote is preserved verbatim (``X="ab'`` → ``"ab'``) —
      deliberately NOT the legacy ``.strip("'").strip('"')``, which also
      ate unpaired quotes.
    - On a duplicate key, the last assignment wins.

    Two hardened parsers in openclaw-tag-router deliberately do NOT
    delegate here: ``openclaw_app/adapters/http_api.py``'s
    ``load_auth_environment`` (an allowlist-enforcing security boundary
    that must keep rejecting unknown keys) and
    ``openclaw_app/services/deepmath_runtime_config.py``'s ``_read_env``
    (a fail-closed required-file contract raising its own domain error).
    """
    env_path = Path(path).expanduser()
    try:
        raw_text = env_path.read_text(encoding="utf-8")
    except OSError:
        if require:
            raise
        return {}
    return parse_env_text(raw_text)


def parse_env_text(text: str) -> dict[str, str]:
    """Parse already-decoded ``KEY=VALUE`` text using the canonical line rules.

    :func:`parse_env_file` is `Path.read_text(encoding="utf-8") -> parse_env_text`;
    split out for the one caller in this repo that must control the *decode*
    step itself (``openclaw-tag-router/scripts/sync_tag_router_docs_to_feishu.py``
    reads with ``errors="replace"`` so a stray non-UTF-8 byte in a synced doc
    env file can't crash the sync) while still sharing every line-parsing rule
    -- comments, ``export `` prefix, matched-pair quote slicing, identifier-key
    validation, last-assignment-wins -- with the canonical reader instead of
    re-deriving them.
    """
    values: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        key, separator, value = line.partition("=")
        if not separator:
            continue
        key = key.strip()
        if not _ENV_KEY_RE.fullmatch(key):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


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
