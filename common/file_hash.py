"""Streaming SHA-256 for on-disk files (r9).

selfmedia's viral_content evidence pipeline (a speech-evidence cache key)
and openclaw-tag-router's vlog storage service (a material dedup key) each
carried a byte-for-byte identical 1 MiB-chunked streaming SHA-256 reader.
Both are content fingerprints over the same kind of input (a file on disk),
so the chunk size and hex-digest format must stay in lockstep between them
-- keeping two copies is a drift risk, not just duplication.

A third, near-identical copy (openclaw_app/router/transcription_storage.py
_file_sha256) wraps the read in try/except OSError and returns "" on
failure instead of propagating -- that swallow may be load-bearing at its
call site, so it is deliberately not folded in here; a caller that wants
that behavior should catch OSError around sha256_file() itself.
"""

from __future__ import annotations

import hashlib
from pathlib import Path


def sha256_file(path: str | Path, *, chunk_size: int = 1024 * 1024) -> str:
    """Hex SHA-256 digest of the file at ``path``, read in ``chunk_size`` chunks."""
    hasher = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            hasher.update(chunk)
    return hasher.hexdigest()
