from __future__ import annotations

import hashlib
from pathlib import Path

from common.file_hash import sha256_file


def test_sha256_file_matches_hashlib_reference(tmp_path: Path) -> None:
    content = b"hello world" * 1000
    path = tmp_path / "data.bin"
    path.write_bytes(content)

    assert sha256_file(path) == hashlib.sha256(content).hexdigest()


def test_sha256_file_accepts_str_path(tmp_path: Path) -> None:
    content = b"abc"
    path = tmp_path / "data.bin"
    path.write_bytes(content)

    assert sha256_file(str(path)) == hashlib.sha256(content).hexdigest()


def test_sha256_file_handles_empty_file(tmp_path: Path) -> None:
    path = tmp_path / "empty.bin"
    path.write_bytes(b"")

    assert sha256_file(path) == hashlib.sha256(b"").hexdigest()


def test_sha256_file_result_independent_of_chunk_size(tmp_path: Path) -> None:
    content = bytes(range(256)) * 50
    path = tmp_path / "chunked.bin"
    path.write_bytes(content)

    assert sha256_file(path, chunk_size=17) == sha256_file(path, chunk_size=1024 * 1024)
