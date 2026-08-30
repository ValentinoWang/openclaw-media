"""Shared Markdown ``---`` YAML frontmatter parsing.

SV-04 found seven independent regex-and-``yaml.safe_load`` frontmatter
parsers scattered across the router and service layers, three distinct
failure semantics among them:

* **strict** -- a missing file, a missing/malformed frontmatter block, a
  YAML error, or a non-mapping document is a caller-supplied error.  Used
  where frontmatter *is* the writable state record and a malformed record
  must stop the write, not paper over it.  Seed:
  ``content_os_project_lifecycle._read_frontmatter``.
* **tolerant** -- the same failures silently collapse to ``({}, body)``
  (or ``({}, "")`` for a missing file) and are never raised.  Used by
  read-only consumers that must not fail a whole listing/discovery pass
  over one malformed record.  Seed: ``content_os_utils._read_markdown_frontmatter``.
* **placeholder** -- like tolerant, but collapses failure to a single
  fixed display value instead of an empty dict, for read-only surfaces
  that only ever show a placeholder string on failure.  Seed:
  ``content_os_feishu_projection._evidence_summary``'s pre-refactor
  "未记录" fallback.

This module exists to hold that parsing logic exactly once.  It has no
opinion on *when* a caller should be strict vs. tolerant vs.
placeholder-returning, on what a caller does with the body afterwards
(cleanup, section extraction, spec_version checks, ...), or on how a
caller renders/writes frontmatter back out -- all of that stays in each
call site.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable

import yaml


_FRONTMATTER_RE = re.compile(r"\A---\n(?P<frontmatter>.*?)\n---\n?(?P<body>.*)\Z", flags=re.S)


def _read_text_or_missing(path: Path) -> str | None:
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8", errors="replace")


def read_frontmatter_strict(
    path: Path,
    *,
    error: Callable[[str], Exception],
) -> tuple[dict[str, Any], str]:
    """Parse ``path``'s frontmatter, raising ``error(message)`` on any failure.

    ``error`` is an exception factory (e.g. ``ContentOSContractError``) so
    this module stays agnostic of any one caller's domain error type. Raises
    for: a missing file, a missing/malformed ``---`` block, a YAML parse
    error, or a document whose frontmatter is not a mapping.
    """

    text = _read_text_or_missing(path)
    if text is None:
        raise error(f"frontmatter 文件不存在：{path}")
    match = _FRONTMATTER_RE.match(text)
    if not match:
        raise error(f"frontmatter 缺失：{path}")
    try:
        frontmatter = yaml.safe_load(match.group("frontmatter")) or {}
    except yaml.YAMLError as exc:
        raise error(f"frontmatter 无法读取：{path}") from exc
    if not isinstance(frontmatter, dict):
        raise error(f"frontmatter 必须是对象：{path}")
    return frontmatter, match.group("body")


def read_frontmatter_tolerant(text_or_path: str | Path) -> tuple[dict[str, Any], str]:
    """Best-effort frontmatter parse that never raises.

    Accepts either markdown text already read by the caller, or a ``Path``
    to read (missing file -> ``({}, "")``). Any failure to find or parse a
    ``---\\n...\\n---\\n`` block -- no match, a YAML error, or a non-mapping
    document -- collapses to ``({}, original_text)``.
    """

    if isinstance(text_or_path, Path):
        text = _read_text_or_missing(text_or_path)
        if text is None:
            return {}, ""
    else:
        text = text_or_path
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    try:
        frontmatter = yaml.safe_load(match.group("frontmatter")) or {}
    except yaml.YAMLError:
        frontmatter = {}
    return (frontmatter if isinstance(frontmatter, dict) else {}), match.group("body")


def read_frontmatter_or_default(
    text_or_path: str | Path,
    *,
    default: str = "未记录",
) -> dict[str, Any] | str:
    """Best-effort frontmatter parse collapsing failure to one placeholder value.

    Same parsing rules as :func:`read_frontmatter_tolerant`, but returns a
    single fixed ``default`` (rather than ``{}`` plus the raw body) when
    the file is missing, has no frontmatter block, fails to parse, or is
    not a mapping. This is the third failure semantic SV-04 flagged --
    distinct from the strict (raises) and tolerant (silent ``{}``)
    variants -- for read-only display surfaces that only ever show a
    placeholder on failure and have no separate use for the raw body.
    """

    frontmatter, _ = read_frontmatter_tolerant(text_or_path)
    return frontmatter if frontmatter else default


__all__ = [
    "read_frontmatter_strict",
    "read_frontmatter_tolerant",
    "read_frontmatter_or_default",
]
