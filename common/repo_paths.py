"""Locate the openclaw-media repository root and make it importable.

Dedup audit cluster pe-04: ten-plus call sites across this repo (and a
sibling, openclaw-bot-center) each re-derive "where is the openclaw-media
checkout" with a different, incompatible recipe -- five of them a literal
``Path("/home/ubuntu/selfmedia-tools")`` that silently shadows the actual
checkout on any other host, the rest a ``Path(__file__).resolve().parents[N]``
whose ``N`` silently goes stale the moment a file moves. This module is the
single, portable replacement for all of them.

The algorithm is lifted from the one genuinely well-engineered instance of
this pattern already in the repo --
``media-agent-cli/generate_product_clients.py:25 resolve_repository_root``
(env override validated by a marker check, else walk ``__file__.parents``
for the first directory that satisfies the marker, else a ``RuntimeError``
naming the env var) -- adapted to the marker this repo already standardized
on: ``OPENCLAW_SELFMEDIA_ROOT``, honored today by
``selfmedia/business/id_business.py`` and
``openclaw_app/services/media_business/admin_platform_cookies.py``, and
pinned by ``tests/test_portable_media_paths.py``.

This change only introduces the shared helper. Migrating the many existing
call sites onto it (see the audit's pe-04 entry for the full list and a
four-wave rollout plan) touches files outside this change's scope and is
tracked separately -- do not assume every bootstrap in the repo has been
switched over yet.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path

REPOSITORY_ROOT_ENV = "OPENCLAW_SELFMEDIA_ROOT"

# A checkout of this repository always has both of these as top-level
# directories; requiring both (rather than either alone) avoids matching an
# unrelated ancestor directory that happens to contain just one.
_MARKER_DIRS = ("common", "selfmedia")


def _is_repository_root(path: Path) -> bool:
    return path.is_dir() and all((path / marker).is_dir() for marker in _MARKER_DIRS)


def _search_candidates(origin: Path) -> Iterable[Path]:
    """Yield `origin` (if it's a directory) then its ancestors, nearest first."""
    if origin.is_dir():
        yield origin
    yield from origin.parents


def repository_root(
    *,
    environment: Mapping[str, str] | None = None,
    start: Path | None = None,
) -> Path:
    """Resolve the openclaw-media repository root.

    ``OPENCLAW_SELFMEDIA_ROOT``, if set, is used verbatim once validated
    (must resolve to a directory containing both ``common/`` and
    ``selfmedia/``); this matches ``id_business.py`` and
    ``admin_platform_cookies.py``, the two existing call sites that already
    honor an override, and is validated the same way
    ``generate_product_clients.py`` validates
    ``OPENCLAW_MEDIA_PRODUCT_CLIENTS_ROOT`` -- fail closed on a
    misconfigured override rather than silently falling through to a
    guessed path.

    Otherwise, walk upward from ``start`` (default: this file's own
    location, which is always inside the checkout) for the first ancestor
    directory containing both markers. Raises ``RuntimeError`` naming
    ``OPENCLAW_SELFMEDIA_ROOT`` if the override is invalid, or if no
    ancestor matches (e.g. this file was copied outside a full checkout).
    """
    environment = os.environ if environment is None else environment
    override = (environment.get(REPOSITORY_ROOT_ENV) or "").strip()
    if override:
        root = Path(override).expanduser().resolve()
        if not _is_repository_root(root):
            markers = " and ".join(f"{marker}/" for marker in _MARKER_DIRS)
            raise RuntimeError(f"{REPOSITORY_ROOT_ENV} must name a checkout containing {markers}")
        return root

    origin = (start or Path(__file__)).resolve()
    for candidate in _search_candidates(origin):
        if _is_repository_root(candidate):
            return candidate
    raise RuntimeError(
        f"unable to locate the openclaw-media repository root from {origin}; "
        f"set {REPOSITORY_ROOT_ENV}"
    )


def ensure_repository_on_sys_path(
    *,
    environment: Mapping[str, str] | None = None,
    start: Path | None = None,
) -> Path:
    """Resolve the repository root and make sure it is importable.

    Idempotent: inserts at ``sys.path[0]`` only if the root is not already
    present somewhere in ``sys.path``, so repeated calls (or calls from
    several modules during one process's startup) never reorder or
    duplicate entries. Returns the resolved root either way.
    """
    root = repository_root(environment=environment, start=start)
    root_str = str(root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)
    return root


__all__ = [
    "REPOSITORY_ROOT_ENV",
    "ensure_repository_on_sys_path",
    "repository_root",
]
