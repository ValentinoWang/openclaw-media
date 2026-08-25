"""Build and validate a source-only production release manifest.

The module deliberately has no network, service, database, or environment
inputs.  A manifest is useful only when its source identity and target
inventory are both explicit and independently checkable.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
import subprocess
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "production-release-manifest.v1"

_TOP_LEVEL_KEYS = {
    "schema_version",
    "source",
    "target",
    "previous_release_identity",
    "manifest_sha256",
}
_TOP_LEVEL_KEYS_WITHOUT_DIGEST = _TOP_LEVEL_KEYS - {"manifest_sha256"}
_SOURCE_KEYS = {"git_sha", "git_clean"}
_TARGET_KEYS = {"root", "files"}
_FILE_KEYS = {"path", "sha256", "mode"}
_PREVIOUS_IDENTITY_KEYS = {"git_sha", "manifest_sha256"}
_ALLOWED_MODES = {"100644", "100755"}
_SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA64_RE = re.compile(r"^[0-9a-f]{64}$")
_DRIVE_PREFIX_RE = re.compile(r"^[A-Za-z]:")
_SECRET_KEY_WORDS = {
    "secret",
    "secrets",
    "credential",
    "credentials",
    "token",
    "tokens",
    "password",
    "passwords",
    "passwd",
    "api_key",
    "apikey",
    "private_key",
}
_MUTABLE_PREFIXES = ("state", "var", "cache", "logs", "tmp", "uploads")
_MUTABLE_SUFFIXES = (".db", ".sqlite", ".sqlite3", ".log", ".pid", ".sock", ".lock", ".jsonl")
_RUNTIME_PREFIXES = ("runtime", "run")
_SECRET_SEGMENTS = {
    "secret",
    "secrets",
    "credential",
    "credentials",
    "token",
    "tokens",
    "password",
}
_SECRET_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".jks")
_MISSING = object()


class ManifestValidationError(ValueError):
    """A stable, non-secret failure from manifest construction or validation."""

    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code
        self.message = message or code
        super().__init__(self.message)


def _raise(code: str) -> None:
    raise ManifestValidationError(code)


def _is_secret_key(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", "_", key.casefold()).strip("_")
    if not normalized:
        return False
    parts = set(normalized.split("_"))
    return bool(parts & _SECRET_KEY_WORDS) or any(
        marker in normalized for marker in ("secret", "credential", "password", "token")
    )


def _json_copy(value: Any) -> Any:
    """Copy JSON-compatible data while rejecting secret-bearing field names."""

    if isinstance(value, Mapping):
        copied: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                _raise("SCHEMA_INVALID")
            if _is_secret_key(key):
                _raise("SECRET_DISCLOSURE")
            copied[key] = _json_copy(item)
        return copied
    if isinstance(value, list):
        return [_json_copy(item) for item in value]
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    _raise("SCHEMA_INVALID")


def _ensure_known_keys(value: Any, allowed: set[str]) -> None:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        _raise("SCHEMA_INVALID")
    if set(value) - allowed:
        _raise("SCHEMA_INVALID")


def _canonical_payload(manifest: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(manifest, Mapping):
        _raise("SCHEMA_INVALID")

    payload = dict(manifest)
    payload.pop("manifest_sha256", None)
    copied = _json_copy(payload)

    if set(copied) != _TOP_LEVEL_KEYS_WITHOUT_DIGEST:
        _raise("SCHEMA_INVALID")
    _ensure_known_keys(copied["source"], _SOURCE_KEYS)
    _ensure_known_keys(copied["target"], _TARGET_KEYS)
    files = copied["target"].get("files")
    if not isinstance(files, list):
        _raise("SCHEMA_INVALID")
    for entry in files:
        _ensure_known_keys(entry, _FILE_KEYS)
    previous = copied["previous_release_identity"]
    if previous is not None:
        _ensure_known_keys(previous, _PREVIOUS_IDENTITY_KEYS)
    return copied


def canonical_manifest_json(manifest: Mapping[str, Any]) -> str:
    """Return the compact canonical payload used to calculate the manifest digest."""

    payload = _canonical_payload(manifest)
    try:
        return json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError, UnicodeError):
        _raise("SCHEMA_INVALID")
    raise AssertionError("canonical serialization did not return")


def _valid_sha(value: Any, pattern: re.Pattern[str]) -> bool:
    return isinstance(value, str) and pattern.fullmatch(value) is not None


def _normalize_relative_path(raw_path: Any) -> str:
    try:
        path = os.fspath(raw_path)
    except TypeError:
        _raise("PATH_TRAVERSAL")
    if not isinstance(path, str) or not path or "\x00" in path:
        _raise("PATH_TRAVERSAL")
    if path.startswith("/") or path.startswith("\\\\") or _DRIVE_PREFIX_RE.match(path):
        _raise("ABSOLUTE_PATH")
    if "\\" in path:
        _raise("PATH_TRAVERSAL")

    parts = path.split("/")
    if any(part == ".." for part in parts):
        _raise("PATH_TRAVERSAL")
    normalized_parts = [part for part in parts if part not in {"", "."}]
    if not normalized_parts:
        _raise("PATH_TRAVERSAL")
    return "/".join(normalized_parts)


def _path_policy_error(path: str) -> str | None:
    lowered = path.casefold()
    if any(lowered == prefix or lowered.startswith(prefix + "/") for prefix in _RUNTIME_PREFIXES):
        return "RUNTIME_PATH"
    if any(lowered == prefix or lowered.startswith(prefix + "/") for prefix in _MUTABLE_PREFIXES):
        return "MUTABLE_PATH"
    if any(lowered.endswith(suffix) for suffix in _MUTABLE_SUFFIXES):
        return "MUTABLE_PATH"

    segments = lowered.split("/")
    basename = segments[-1]
    if any(segment in _SECRET_SEGMENTS for segment in segments):
        return "SECRET_PATH"
    if basename == ".env" or basename.startswith(".env."):
        return "SECRET_PATH"
    if basename in {"stage2.env", "session-material.env"}:
        return "SECRET_PATH"
    if any(lowered.endswith(suffix) for suffix in _SECRET_SUFFIXES):
        return "SECRET_PATH"
    return None


def _checked_manifest_path(raw_path: Any) -> str:
    path = _normalize_relative_path(raw_path)
    policy_error = _path_policy_error(path)
    if policy_error:
        _raise(policy_error)
    return path


def _target_root_path(target_root: str | os.PathLike[str]) -> Path:
    try:
        root = Path(target_root)
    except (TypeError, ValueError):
        _raise("SOURCE_UNAVAILABLE")
    try:
        root_stat = os.lstat(root)
    except FileNotFoundError:
        _raise("FILE_MISSING")
    except OSError:
        _raise("SOURCE_UNAVAILABLE")
    if stat.S_ISLNK(root_stat.st_mode):
        _raise("UNSUPPORTED_SYMLINK")
    if not stat.S_ISDIR(root_stat.st_mode):
        _raise("UNSUPPORTED_FILE_TYPE")
    return root


def _lstat_regular_target(root: Path, path: str) -> tuple[Path, os.stat_result]:
    current = root
    try:
        root_stat = os.lstat(root)
    except FileNotFoundError:
        _raise("FILE_MISSING")
    except OSError:
        _raise("SOURCE_UNAVAILABLE")
    if stat.S_ISLNK(root_stat.st_mode):
        _raise("UNSUPPORTED_SYMLINK")
    if not stat.S_ISDIR(root_stat.st_mode):
        _raise("UNSUPPORTED_FILE_TYPE")

    parts = path.split("/")
    for index, part in enumerate(parts):
        current = current / part
        try:
            entry_stat = os.lstat(current)
        except FileNotFoundError:
            _raise("FILE_MISSING")
        except OSError:
            _raise("SOURCE_UNAVAILABLE")
        if stat.S_ISLNK(entry_stat.st_mode):
            _raise("UNSUPPORTED_SYMLINK")
        if index < len(parts) - 1 and not stat.S_ISDIR(entry_stat.st_mode):
            _raise("UNSUPPORTED_FILE_TYPE")
        if index == len(parts) - 1:
            if not stat.S_ISREG(entry_stat.st_mode):
                _raise("UNSUPPORTED_FILE_TYPE")
            return current, entry_stat
    raise AssertionError("target path had no components")


def _read_regular_target(root: Path, path: str) -> bytes:
    target, expected_stat = _lstat_regular_target(root, path)
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(os.fspath(target), flags)
    except FileNotFoundError:
        _raise("FILE_MISSING")
    except OSError:
        _raise("SOURCE_UNAVAILABLE")
    try:
        opened_stat = os.fstat(descriptor)
        if not stat.S_ISREG(opened_stat.st_mode):
            _raise("UNSUPPORTED_FILE_TYPE")
        if (opened_stat.st_dev, opened_stat.st_ino) != (expected_stat.st_dev, expected_stat.st_ino):
            _raise("UNSUPPORTED_SYMLINK")
        with os.fdopen(descriptor, "rb") as handle:
            descriptor = -1
            return handle.read()
    except ManifestValidationError:
        raise
    except FileNotFoundError:
        _raise("FILE_MISSING")
    except OSError:
        _raise("SOURCE_UNAVAILABLE")
    finally:
        if descriptor != -1:
            os.close(descriptor)


def _git_run(root: Path, *arguments: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", os.fspath(root), *arguments],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError:
        _raise("SOURCE_UNAVAILABLE")
    if result.returncode != 0:
        _raise("SOURCE_UNAVAILABLE")
    return result.stdout


def _git_source_sha(root: Path) -> str:
    status = _git_run(root, "status", "--porcelain=v1", "--untracked-files=all")
    if status:
        _raise("SOURCE_NOT_CLEAN")
    source_sha = _git_run(root, "rev-parse", "--verify", "HEAD^{commit}").strip()
    if not _SHA40_RE.fullmatch(source_sha):
        _raise("SOURCE_UNAVAILABLE")
    return source_sha


def _git_mode(root: Path, path: str) -> str:
    output = _git_run(root, "ls-tree", "-z", "--full-tree", "HEAD", "--", f":(literal){path}")
    for record in output.split("\x00"):
        if not record:
            continue
        header, separator, record_path = record.partition("\t")
        if not separator or record_path != path:
            continue
        fields = header.split(" ", 2)
        if len(fields) != 3 or fields[1] != "blob":
            _raise("UNSUPPORTED_FILE_TYPE")
        mode = fields[0]
        if mode not in _ALLOWED_MODES:
            _raise("MALFORMED_MODE")
        return mode
    _raise("FILE_MISSING")


def _normalize_previous_identity(value: Any, *, error_code: str = "SCHEMA_INVALID") -> dict[str, str] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping) or set(value) != _PREVIOUS_IDENTITY_KEYS:
        _raise(error_code)
    git_sha = value.get("git_sha")
    manifest_sha = value.get("manifest_sha256")
    if not _valid_sha(git_sha, _SHA40_RE) or not _valid_sha(manifest_sha, _SHA64_RE):
        _raise(error_code)
    return {"git_sha": git_sha, "manifest_sha256": manifest_sha}


def build_manifest(
    target_root: str | os.PathLike[str],
    *,
    file_paths: Iterable[str | os.PathLike[str]],
    previous_release_identity: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Build a sealed manifest from an explicitly selected clean Git tree."""

    if isinstance(file_paths, (str, bytes)):
        _raise("SCHEMA_INVALID")
    try:
        raw_paths = list(file_paths)
    except TypeError:
        _raise("SCHEMA_INVALID")
    if not raw_paths:
        _raise("SCHEMA_INVALID")

    normalized_paths: list[str] = []
    seen_paths: set[str] = set()
    for raw_path in raw_paths:
        path = _checked_manifest_path(raw_path)
        if path in seen_paths:
            _raise("DUPLICATE_PATH")
        seen_paths.add(path)
        normalized_paths.append(path)

    root = _target_root_path(target_root)
    source_sha = _git_source_sha(root)
    previous = _normalize_previous_identity(previous_release_identity)

    entries: list[dict[str, str]] = []
    for path in sorted(normalized_paths):
        content = _read_regular_target(root, path)
        entries.append(
            {
                "path": path,
                "sha256": hashlib.sha256(content).hexdigest(),
                "mode": _git_mode(root, path),
            }
        )

    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "source": {"git_sha": source_sha, "git_clean": True},
        "target": {"root": ".", "files": entries},
        "previous_release_identity": previous,
    }
    manifest["manifest_sha256"] = hashlib.sha256(
        canonical_manifest_json(manifest).encode("utf-8")
    ).hexdigest()
    return manifest


def _validate_manifest_shape(manifest: Mapping[str, Any]) -> None:
    if set(manifest) != _TOP_LEVEL_KEYS:
        _raise("SCHEMA_INVALID")
    if manifest.get("schema_version") != SCHEMA_VERSION:
        _raise("SCHEMA_INVALID")

    source = manifest.get("source")
    if not isinstance(source, Mapping) or set(source) != _SOURCE_KEYS:
        _raise("SCHEMA_INVALID")
    if not _valid_sha(source.get("git_sha"), _SHA40_RE):
        _raise("SCHEMA_INVALID")
    if not isinstance(source.get("git_clean"), bool):
        _raise("SCHEMA_INVALID")

    target = manifest.get("target")
    if not isinstance(target, Mapping) or set(target) != _TARGET_KEYS:
        _raise("SCHEMA_INVALID")
    if target.get("root") != "." or not isinstance(target.get("files"), list):
        _raise("SCHEMA_INVALID")
    for entry in target["files"]:
        if not isinstance(entry, Mapping) or set(entry) - _FILE_KEYS:
            _raise("SCHEMA_INVALID")

    _normalize_previous_identity(manifest.get("previous_release_identity"))


def validate_manifest(
    manifest: Mapping[str, Any],
    target_root: str | os.PathLike[str],
    *,
    expected_source_sha: str,
    expected_previous_release_identity: Mapping[str, str] | None = None,
) -> None:
    """Validate a manifest against a local target tree without mutating either input."""

    if not isinstance(manifest, Mapping):
        _raise("SCHEMA_INVALID")
    supplied_digest = manifest.get("manifest_sha256", _MISSING)
    if not _valid_sha(supplied_digest, _SHA64_RE):
        _raise("MANIFEST_DIGEST_MISMATCH")
    canonical = canonical_manifest_json(manifest)
    expected_digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    if supplied_digest != expected_digest:
        _raise("MANIFEST_DIGEST_MISMATCH")

    _validate_manifest_shape(manifest)
    source = manifest["source"]
    if source["git_clean"] is not True:
        if source["git_clean"] is False:
            _raise("SOURCE_NOT_CLEAN")
        _raise("SCHEMA_INVALID")
    if not _valid_sha(expected_source_sha, _SHA40_RE) or source["git_sha"] != expected_source_sha:
        _raise("SOURCE_SHA_MISMATCH")

    expected_previous = _normalize_previous_identity(
        expected_previous_release_identity,
        error_code="PREVIOUS_RELEASE_IDENTITY_MISMATCH",
    )
    actual_previous = _normalize_previous_identity(
        manifest["previous_release_identity"],
        error_code="PREVIOUS_RELEASE_IDENTITY_MISMATCH",
    )
    if actual_previous != expected_previous:
        _raise("PREVIOUS_RELEASE_IDENTITY_MISMATCH")

    files = manifest["target"]["files"]
    if not files:
        _raise("SCHEMA_INVALID")
    normalized_paths: list[str] = []
    seen_paths: set[str] = set()
    for entry in files:
        if "path" not in entry:
            _raise("SCHEMA_INVALID")
        path = _checked_manifest_path(entry["path"])
        if path in seen_paths:
            _raise("DUPLICATE_PATH")
        seen_paths.add(path)
        normalized_paths.append(path)

        if "sha256" not in entry:
            _raise("MISSING_DIGEST")
        if not _valid_sha(entry["sha256"], _SHA64_RE):
            _raise("MALFORMED_DIGEST")
        if "mode" not in entry or not isinstance(entry["mode"], str) or entry["mode"] not in _ALLOWED_MODES:
            _raise("MALFORMED_MODE")

        content = _read_regular_target(_target_root_path(target_root), path)
        if hashlib.sha256(content).hexdigest() != entry["sha256"]:
            _raise("DIGEST_MISMATCH")

    if normalized_paths != sorted(normalized_paths):
        _raise("SCHEMA_INVALID")


__all__ = [
    "ManifestValidationError",
    "build_manifest",
    "canonical_manifest_json",
    "validate_manifest",
]
