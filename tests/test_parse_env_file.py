"""Pinning tests for the canonical .env parser (dedup audit pe-01).

``common.env.parse_env_file`` replaces 12+ hand-rolled ``.env`` readers.
These tests pin the line shapes whose behavior is IDENTICAL to the legacy
``common.social_runtime.load_env_file`` implementation (proving the swap is
invisible for every ordinary line), and document the three deliberate
corrections the canonical parser makes:

1. Matched-pair quote slicing. The legacy ``.strip("'").strip('"')`` also
   mangled UNBALANCED quotes (``X="ab'`` used to yield ``ab``); the
   canonical parser only unwraps a value wrapped in one matched pair and
   preserves an unbalanced quote verbatim.
2. Shell-identifier key validation (``[A-Za-z_][A-Za-z0-9_]*``). Legacy
   accepted any non-empty key text; degenerate keys are now dropped.
3. ``expanduser`` on the path, previously done only by social_runtime.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest import mock

import pytest

from common import social_runtime
from common.env import parse_env_file


REPRESENTATIVE_ENV = """\
# full-line comment
   # indented comment

PLAIN=value
SPACED_KEY  =  spaced value\t
DOUBLE_QUOTED="quoted value"
SINGLE_QUOTED='single value'
QUOTED_PRESERVES_INNER="  padded  "
EMPTY=
EMPTY_QUOTED=""
export EXPORTED=exported-value
URL=https://example.com/path?a=1&b=2
CONTAINS_EQUALS=a=b=c
INNER_QUOTE=va"lue
MIXED_WRAP="'wrapped'"
not a key value line
UNBALANCED="ab'
LONE_QUOTE="
"""


#: Line shapes on which the canonical parser and the legacy
#: ``.strip("'").strip('"')`` implementations agree byte-for-byte.
UNCHANGED_EXPECTED = {
    "PLAIN": "value",
    "SPACED_KEY": "spaced value",
    "DOUBLE_QUOTED": "quoted value",
    "SINGLE_QUOTED": "single value",
    # Whitespace INSIDE a matched quote pair survives; only the outer
    # whitespace and the one quote pair are removed.
    "QUOTED_PRESERVES_INNER": "  padded  ",
    "EMPTY": "",
    "EMPTY_QUOTED": "",
    "EXPORTED": "exported-value",
    "URL": "https://example.com/path?a=1&b=2",
    # Split on the FIRST '=' only.
    "CONTAINS_EQUALS": "a=b=c",
    # A quote character that is not at both ends is data, not wrapping.
    "INNER_QUOTE": 'va"lue',
    # A matched OUTER pair is removed exactly once; the inner pair stays.
    "MIXED_WRAP": "'wrapped'",
}


def _write_env(tmp_path: Path, content: str = REPRESENTATIVE_ENV) -> Path:
    env_path = tmp_path / "pinned.env"
    env_path.write_text(content, encoding="utf-8")
    return env_path


def test_parse_env_file_unchanged_line_shapes(tmp_path: Path) -> None:
    parsed = parse_env_file(_write_env(tmp_path))
    for key, expected in UNCHANGED_EXPECTED.items():
        assert parsed[key] == expected, key


def test_parse_env_file_documents_matched_pair_quote_correction(tmp_path: Path) -> None:
    """The one behavior change the pe-01 audit warns about, pinned.

    Legacy ``.strip("'").strip('"')`` turned ``UNBALANCED="ab'`` into
    ``ab`` (both stray quotes silently eaten). Matched-pair slicing keeps
    the unbalanced quotes verbatim -- the value was never actually wrapped.
    """
    parsed = parse_env_file(_write_env(tmp_path))
    assert parsed["UNBALANCED"] == "\"ab'"
    # A single quote character is likewise no longer eaten to "".
    assert parsed["LONE_QUOTE"] == '"'


def test_parse_env_file_drops_non_identifier_keys(tmp_path: Path) -> None:
    env_path = _write_env(
        tmp_path,
        "GOOD=1\nBAD-KEY=2\n9LEADS=3\nSPACED KEY=4\ndotted.key=5\n=6\n_UNDER=7\n",
    )
    assert parse_env_file(env_path) == {"GOOD": "1", "_UNDER": "7"}


def test_parse_env_file_duplicate_keys_last_wins(tmp_path: Path) -> None:
    env_path = _write_env(tmp_path, "K=first\nK=second\n")
    assert parse_env_file(env_path) == {"K": "second"}


def test_parse_env_file_missing_file_and_require(tmp_path: Path) -> None:
    missing = tmp_path / "absent.env"
    assert parse_env_file(missing) == {}
    with pytest.raises(FileNotFoundError):
        parse_env_file(missing, require=True)
    # A directory behaves like an unreadable optional file.
    assert parse_env_file(tmp_path) == {}


def test_parse_env_file_expands_user(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "home.env").write_text("FROM_HOME=1\n", encoding="utf-8")
    assert parse_env_file("~/home.env") == {"FROM_HOME": "1"}


def test_load_env_file_precedence_pinned(tmp_path: Path) -> None:
    """social_runtime.load_env_file keeps its exact os.environ semantics."""
    env_path = _write_env(tmp_path, "PE01_KEEP=from-file\nPE01_NEW=fresh\n")
    with mock.patch.dict(os.environ):
        os.environ["PE01_KEEP"] = "from-process"
        os.environ.pop("PE01_NEW", None)

        social_runtime.load_env_file(env_path)
        assert os.environ["PE01_KEEP"] == "from-process"  # default: process wins
        assert os.environ["PE01_NEW"] == "fresh"

        social_runtime.load_env_file(str(env_path), override=True)
        assert os.environ["PE01_KEEP"] == "from-file"  # override: file wins


def test_load_env_file_missing_file_is_a_noop(tmp_path: Path) -> None:
    social_runtime.load_env_file(tmp_path / "absent.env")  # must not raise


def test_load_env_file_parses_with_canonical_rules(tmp_path: Path) -> None:
    env_path = _write_env(tmp_path)
    with mock.patch.dict(os.environ):
        for key in (*UNCHANGED_EXPECTED, "UNBALANCED", "LONE_QUOTE"):
            os.environ.pop(key, None)
        social_runtime.load_env_file(env_path)
        for key, expected in UNCHANGED_EXPECTED.items():
            assert os.environ[key] == expected, key
        assert os.environ["UNBALANCED"] == "\"ab'"
        assert os.environ["LONE_QUOTE"] == '"'
