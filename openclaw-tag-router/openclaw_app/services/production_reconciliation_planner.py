"""Pure, source-only planning for Production Reconciliation.

The planner accepts a complete in-memory observation and returns a redacted
declarative plan. It deliberately has no filesystem, process, network, or
runtime-state dependency.
"""

from __future__ import annotations

import hashlib
import json
import posixpath
import re
from collections.abc import Mapping
from typing import Any, NoReturn


PLAN_SCHEMA_VERSION = "production-reconciliation-plan.v1"
MANIFEST_SCHEMA_VERSION = "production-release-manifest.v1"
RELEASE_ID_PREFIX = "openclaw-stage2-"

_SHA_RE = re.compile(r"[0-9a-f]{40}\Z")
_DIGEST_RE = re.compile(r"[0-9a-f]{64}\Z")
_DRIVE_RE = re.compile(r"[A-Za-z]:")
_GLOB_CHARS = frozenset("*?[]{}")
_SECRET_KEY_RE = re.compile(
    r"(?:access[_-]?token|api[_-]?key|credential|cookie|password|passwd|private[_-]?key|secret|token)",
    re.IGNORECASE,
)
_SAFE_SYSTEMD_UNIT_RE = re.compile(r"[A-Za-z0-9_.@:%+-]+\Z")
_SAFE_SYSTEMD_ACTION_RE = re.compile(r"[a-z][a-z0-9_-]{0,63}\Z")
_SAFE_SIGNAL_RE = re.compile(r"[a-z][a-z0-9_-]{0,63}\Z")

_REQUEST_KEYS = frozenset(
    {
        "operation",
        "source",
        "layout",
        "target_release",
        "pointer",
        "previous_release",
        "known_releases",
        "user_systemd",
        "observation",
    }
)
_MANIFEST_KEYS = frozenset(
    {
        "schema_version",
        "source",
        "target",
        "previous_release_identity",
        "manifest_sha256",
    }
)
_MANIFEST_SOURCE_KEYS = frozenset({"git_sha", "git_clean"})
_MANIFEST_TARGET_KEYS = frozenset({"root", "files"})
_MANIFEST_FILE_KEYS = frozenset({"path", "sha256", "mode"})
_RELEASE_IDENTITY_KEYS = frozenset(
    {"release_id", "git_sha", "root", "manifest_sha256"}
)
_PREVIOUS_RELEASE_KEYS = frozenset(
    {
        "release_id",
        "git_sha",
        "root",
        "manifest_sha256",
        "manifest_schema",
        "rollback_compatible",
    }
)
_LAYOUT_KEYS = frozenset({"release_base", "current_pointer"})
_POINTER_KEYS = frozenset({"expected", "observed"})
_SYSTEMD_KEYS = frozenset({"enabled", "units", "actions"})
_OBSERVATION_KEYS = frozenset({"window_seconds", "signals"})
_KNOWN_RELEASE_KEYS = frozenset({"release_id", "git_sha", "root"})

_BROAD_RELEASE_BASES = frozenset(
    {"/", "/home", "/var", "/tmp", "/etc", "/usr", "/opt", "/srv"}
)
_RUNTIME_PREFIXES = ("runtime", "run")
_MUTABLE_PREFIXES = (
    "state",
    "var",
    "cache",
    "logs",
    "tmp",
    "uploads",
)
_MUTABLE_SUFFIXES = (
    ".db",
    ".sqlite",
    ".sqlite3",
    ".log",
    ".pid",
    ".sock",
    ".lock",
    ".jsonl",
)
_SECRET_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".jks")
_SECRET_SEGMENTS = frozenset(
    {"secret", "secrets", "credential", "credentials", "token", "tokens", "password"}
)


class PlannerValidationError(ValueError):
    """A stable, redacted validation failure from the pure planner."""

    def __init__(self, code: str, detail: str = "invalid production reconciliation request") -> None:
        self.code = code
        super().__init__(f"{code}: {detail}")


def _fail(code: str, detail: str = "invalid production reconciliation request") -> NoReturn:
    raise PlannerValidationError(code, detail)


def _is_secret_key(key: str) -> bool:
    return bool(_SECRET_KEY_RE.search(key))


def _require_mapping(value: object, code: str = "SCHEMA_INVALID") -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        _fail(code)
    return value


def _check_keys(
    value: Mapping[str, object],
    allowed: frozenset[str],
    *,
    code: str = "SCHEMA_INVALID",
) -> None:
    for key in value:
        if not isinstance(key, str):
            _fail(code)
        if key not in allowed:
            if _is_secret_key(key):
                _fail("SECRET_DISCLOSURE", "secret-bearing fields are not accepted")
            _fail(code)


def _require_string(value: object, code: str = "SCHEMA_INVALID") -> str:
    if not isinstance(value, str) or not value or any(ord(char) < 32 for char in value):
        _fail(code)
    return value


def _require_sha(value: object, code: str = "SOURCE_SHA_INVALID") -> str:
    if not isinstance(value, str) or _SHA_RE.fullmatch(value) is None:
        _fail(code)
    return value


def _require_digest(value: object, code: str = "SCHEMA_INVALID") -> str:
    if not isinstance(value, str) or _DIGEST_RE.fullmatch(value) is None:
        _fail(code)
    return value


def _require_bool(value: object, code: str = "SCHEMA_INVALID") -> bool:
    if type(value) is not bool:
        _fail(code)
    return value


def _require_list(value: object, code: str = "SCHEMA_INVALID") -> list[object]:
    if type(value) is not list:
        _fail(code)
    return value


def _plain_json(value: object) -> object:
    """Convert accepted JSON-shaped mappings without touching their inputs."""

    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        for key, child in value.items():
            if not isinstance(key, str):
                _fail("SCHEMA_INVALID")
            result[key] = _plain_json(child)
        return result
    if type(value) is list:
        return [_plain_json(child) for child in value]
    if value is None or type(value) is bool or type(value) is int or isinstance(value, str):
        return value
    _fail("SCHEMA_INVALID")


def _canonical_json(value: object) -> str:
    try:
        return json.dumps(
            _plain_json(value),
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise PlannerValidationError("SCHEMA_INVALID") from exc


def canonical_plan_json(plan: Mapping[str, object]) -> str:
    """Return compact, recursively key-sorted, ASCII-safe plan JSON."""

    if not isinstance(plan, Mapping):
        _fail("SCHEMA_INVALID")
    return _canonical_json(plan)


def _validate_absolute_path(value: object, *, broad_base: bool = False) -> str:
    path = _require_string(value, "PATH_UNSAFE")
    if (
        not path.startswith("/")
        or path.startswith("//")
        or "\\" in path
        or "\x00" in path
        or path.startswith("~")
        or _DRIVE_RE.match(path) is not None
        or any(char in _GLOB_CHARS for char in path)
    ):
        _fail("PATH_UNSAFE")
    parts = path.split("/")
    if any(part in {"", ".", ".."} for part in parts[1:]):
        _fail("PATH_UNSAFE")
    if posixpath.normpath(path) != path:
        _fail("PATH_UNSAFE")
    components = [part for part in parts if part]
    if not components or len(components) < 2:
        _fail("PATH_UNSAFE")
    if broad_base and path in _BROAD_RELEASE_BASES:
        _fail("PATH_UNSAFE")
    return path


def _validate_layout(value: object) -> tuple[str, str]:
    layout = _require_mapping(value, "PATH_UNSAFE")
    _check_keys(layout, _LAYOUT_KEYS, code="PATH_UNSAFE")
    if "release_base" not in layout or "current_pointer" not in layout:
        _fail("PATH_UNSAFE")
    release_base = _validate_absolute_path(layout["release_base"], broad_base=True)
    current_pointer = _validate_absolute_path(layout["current_pointer"])
    if posixpath.dirname(current_pointer) != posixpath.dirname(release_base):
        _fail("PATH_UNSAFE")
    if current_pointer == release_base:
        _fail("PATH_UNSAFE")
    return release_base, current_pointer


def _release_id_for_sha(git_sha: str) -> str:
    return RELEASE_ID_PREFIX + git_sha


def _release_root_for_sha(release_base: str, git_sha: str) -> str:
    return posixpath.join(release_base, _release_id_for_sha(git_sha))


def _validate_target_identity(
    value: object,
    *,
    source_sha: str,
    release_base: str,
) -> tuple[str, str, str]:
    target = _require_mapping(value, "SOURCE_ROOT_MISMATCH")
    _check_keys(target, frozenset({"release_id", "git_sha", "root", "manifest"}))
    for key in ("release_id", "git_sha", "root"):
        if key not in target:
            _fail("SOURCE_ROOT_MISMATCH")
    target_sha = _require_sha(target["git_sha"], "SOURCE_ROOT_MISMATCH")
    expected_release_id = _release_id_for_sha(source_sha)
    expected_root = _release_root_for_sha(release_base, source_sha)
    release_id = _require_string(target["release_id"], "SOURCE_ROOT_MISMATCH")
    root = _validate_absolute_path(target["root"])
    if target_sha != source_sha or release_id != expected_release_id or root != expected_root:
        _fail("SOURCE_ROOT_MISMATCH")
    if "manifest" not in target:
        _fail("MANIFEST_INVALID")
    return release_id, target_sha, root


def _validate_manifest_path(value: object) -> str:
    path = _require_string(value, "MANIFEST_INVALID")
    if (
        path.startswith("/")
        or path.startswith("~")
        or _DRIVE_RE.match(path) is not None
        or "\\" in path
        or "\x00" in path
        or any(char in _GLOB_CHARS for char in path)
    ):
        _fail("MANIFEST_INVALID")
    parts = path.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        _fail("MANIFEST_INVALID")
    if posixpath.normpath(path) != path:
        _fail("MANIFEST_INVALID")
    lowered = path.lower()
    segments = {part.lower() for part in parts}
    basename = parts[-1].lower()
    if any(
        lowered == prefix or lowered.startswith(f"{prefix}/")
        for prefix in (*_RUNTIME_PREFIXES, *_MUTABLE_PREFIXES)
    ):
        _fail("MANIFEST_INVALID")
    if lowered.endswith(_MUTABLE_SUFFIXES):
        _fail("MANIFEST_INVALID")
    if (
        basename == ".env"
        or basename.startswith(".env.")
        or basename in {"stage2.env", "session-material.env"}
        or segments & _SECRET_SEGMENTS
        or lowered.endswith(_SECRET_SUFFIXES)
    ):
        _fail("MANIFEST_INVALID")
    return path


def _validate_manifest(
    value: object,
    *,
    source_sha: str,
) -> tuple[str, tuple[str, str]]:
    manifest = _require_mapping(value, "MANIFEST_INVALID")
    _check_keys(manifest, _MANIFEST_KEYS, code="SCHEMA_INVALID")
    for key in _MANIFEST_KEYS:
        if key not in manifest:
            _fail("MANIFEST_INVALID")
    if manifest["schema_version"] != MANIFEST_SCHEMA_VERSION:
        _fail("MANIFEST_INVALID")

    manifest_digest = _require_digest(manifest["manifest_sha256"], "MANIFEST_INVALID")
    without_digest = dict(manifest)
    without_digest.pop("manifest_sha256", None)
    try:
        expected_digest = hashlib.sha256(
            _canonical_json(without_digest).encode("utf-8")
        ).hexdigest()
    except PlannerValidationError as exc:
        if exc.code == "SECRET_DISCLOSURE":
            raise
        _fail("MANIFEST_INVALID")
    if manifest_digest != expected_digest:
        _fail("MANIFEST_INVALID")

    source = _require_mapping(manifest["source"], "MANIFEST_INVALID")
    _check_keys(source, _MANIFEST_SOURCE_KEYS, code="MANIFEST_INVALID")
    if set(source) != _MANIFEST_SOURCE_KEYS:
        _fail("MANIFEST_INVALID")
    if _require_sha(source["git_sha"], "MANIFEST_INVALID") != source_sha:
        _fail("MANIFEST_INVALID")
    if _require_bool(source["git_clean"], "MANIFEST_INVALID") is not True:
        _fail("MANIFEST_INVALID")

    target = _require_mapping(manifest["target"], "MANIFEST_INVALID")
    _check_keys(target, _MANIFEST_TARGET_KEYS, code="MANIFEST_INVALID")
    if set(target) != _MANIFEST_TARGET_KEYS or target["root"] != ".":
        _fail("MANIFEST_INVALID")
    files = _require_list(target["files"], "MANIFEST_INVALID")
    if not files:
        _fail("MANIFEST_INVALID")
    paths: list[str] = []
    for entry_value in files:
        entry = _require_mapping(entry_value, "MANIFEST_INVALID")
        _check_keys(entry, _MANIFEST_FILE_KEYS, code="MANIFEST_INVALID")
        if set(entry) != _MANIFEST_FILE_KEYS:
            _fail("MANIFEST_INVALID")
        path = _validate_manifest_path(entry["path"])
        _require_digest(entry["sha256"], "MANIFEST_INVALID")
        mode = _require_string(entry["mode"], "MANIFEST_INVALID")
        if mode not in {"100644", "100755"}:
            _fail("MANIFEST_INVALID")
        paths.append(path)
    if len(paths) != len(set(paths)):
        _fail("MANIFEST_INVALID")

    previous_identity = manifest["previous_release_identity"]
    previous_identity = _require_mapping(previous_identity, "MANIFEST_INVALID")
    expected_previous_keys = frozenset({"git_sha", "manifest_sha256"})
    _check_keys(previous_identity, expected_previous_keys, code="MANIFEST_INVALID")
    if set(previous_identity) != expected_previous_keys:
        _fail("MANIFEST_INVALID")
    previous_sha = _require_sha(previous_identity["git_sha"], "MANIFEST_INVALID")
    previous_digest = _require_digest(
        previous_identity["manifest_sha256"], "MANIFEST_INVALID"
    )
    return manifest_digest, (previous_sha, previous_digest)


def _validate_release_identity(
    value: object,
    *,
    release_base: str,
    code: str,
) -> dict[str, str]:
    identity = _require_mapping(value, code)
    _check_keys(identity, _RELEASE_IDENTITY_KEYS, code=code)
    if set(identity) != _RELEASE_IDENTITY_KEYS:
        _fail(code)
    git_sha = _require_sha(identity["git_sha"], code)
    release_id = _require_string(identity["release_id"], code)
    root = _validate_absolute_path(identity["root"])
    manifest_sha256 = _require_digest(identity["manifest_sha256"], code)
    if release_id != _release_id_for_sha(git_sha):
        _fail(code)
    if root != _release_root_for_sha(release_base, git_sha):
        _fail(code)
    return {
        "release_id": release_id,
        "git_sha": git_sha,
        "root": root,
        "manifest_sha256": manifest_sha256,
    }


def _validate_previous_release(
    value: object,
    *,
    release_base: str,
) -> tuple[dict[str, str], bool]:
    previous = _require_mapping(value, "PREVIOUS_RELEASE_INVALID")
    _check_keys(previous, _PREVIOUS_RELEASE_KEYS, code="PREVIOUS_RELEASE_INVALID")
    identity_keys = _RELEASE_IDENTITY_KEYS
    if not identity_keys.issubset(previous):
        _fail("PREVIOUS_RELEASE_INVALID")
    identity = _validate_release_identity(
        {key: previous[key] for key in identity_keys},
        release_base=release_base,
        code="PREVIOUS_RELEASE_INVALID",
    )
    if "manifest_schema" not in previous or "rollback_compatible" not in previous:
        _fail("ROLLBACK_INCOMPATIBLE")
    manifest_schema = previous["manifest_schema"]
    rollback_compatible = previous["rollback_compatible"]
    if manifest_schema != MANIFEST_SCHEMA_VERSION or type(rollback_compatible) is not bool:
        _fail("ROLLBACK_INCOMPATIBLE")
    return identity, rollback_compatible


def _validate_pointer(
    value: object,
    *,
    release_base: str,
) -> dict[str, str]:
    pointer = _require_mapping(value, "POINTER_CAS_CONFLICT")
    _check_keys(pointer, _POINTER_KEYS, code="POINTER_CAS_CONFLICT")
    if "expected" not in pointer or "observed" not in pointer:
        _fail("POINTER_CAS_CONFLICT")
    expected = _validate_release_identity(
        pointer["expected"], release_base=release_base, code="POINTER_CAS_CONFLICT"
    )
    observed = _validate_release_identity(
        pointer["observed"], release_base=release_base, code="POINTER_CAS_CONFLICT"
    )
    if expected != observed:
        _fail("POINTER_CAS_CONFLICT")
    return expected


def _validate_known_releases(
    value: object,
    *,
    release_base: str,
    target: Mapping[str, object],
) -> None:
    records = _require_list(value)
    target_release_id = str(target["release_id"])
    target_sha = str(target["git_sha"])
    target_root = str(target["root"])
    seen: dict[str, tuple[str, str]] = {}
    for record_value in records:
        record = _require_mapping(record_value)
        _check_keys(record, _KNOWN_RELEASE_KEYS)
        if set(record) != _KNOWN_RELEASE_KEYS:
            _fail("SCHEMA_INVALID")
        release_id = _require_string(record["release_id"])
        git_sha = _require_sha(record["git_sha"])
        root = _validate_absolute_path(record["root"])
        if release_id != _release_id_for_sha(release_id.removeprefix(RELEASE_ID_PREFIX)):
            _fail("IDENTITY_COLLISION")
        embedded_sha = release_id.removeprefix(RELEASE_ID_PREFIX)
        if git_sha != embedded_sha or root != _release_root_for_sha(release_base, embedded_sha):
            _fail("IDENTITY_COLLISION")
        pair = (git_sha, root)
        prior = seen.get(release_id)
        if prior is not None and prior != pair:
            _fail("IDENTITY_COLLISION")
        seen[release_id] = pair
        if release_id == target_release_id and (git_sha != target_sha or root != target_root):
            _fail("IDENTITY_COLLISION")
        if root == target_root and git_sha != target_sha:
            _fail("IDENTITY_COLLISION")


def _validate_user_systemd(value: object) -> tuple[bool, list[str], list[str]]:
    systemd = _require_mapping(value)
    _check_keys(systemd, _SYSTEMD_KEYS)
    if set(systemd) != _SYSTEMD_KEYS:
        _fail("SCHEMA_INVALID")
    enabled = _require_bool(systemd["enabled"])
    units = _require_list(systemd["units"])
    actions = _require_list(systemd["actions"])
    normalized_units: list[str] = []
    normalized_actions: list[str] = []
    for unit in units:
        unit_name = _require_string(unit)
        if _SAFE_SYSTEMD_UNIT_RE.fullmatch(unit_name) is None or unit_name.startswith("-"):
            _fail("SCHEMA_INVALID")
        normalized_units.append(unit_name)
    for action in actions:
        action_name = _require_string(action)
        if _SAFE_SYSTEMD_ACTION_RE.fullmatch(action_name) is None:
            _fail("SCHEMA_INVALID")
        normalized_actions.append(action_name)
    if len(set(normalized_units)) != len(normalized_units) or len(set(normalized_actions)) != len(
        normalized_actions
    ):
        _fail("SCHEMA_INVALID")
    if enabled != bool(normalized_units or normalized_actions):
        _fail("SCHEMA_INVALID")
    if enabled and (not normalized_units or not normalized_actions):
        _fail("SCHEMA_INVALID")
    return enabled, normalized_units, normalized_actions


def _validate_observation(value: object) -> tuple[int, list[str]]:
    observation = _require_mapping(value)
    _check_keys(observation, _OBSERVATION_KEYS)
    if set(observation) != _OBSERVATION_KEYS:
        _fail("OBSERVATION_INVALID")
    window_seconds = observation["window_seconds"]
    if type(window_seconds) is not int or not 1 <= window_seconds <= 86400:
        _fail("OBSERVATION_INVALID")
    signals = _require_list(observation["signals"], "OBSERVATION_INVALID")
    if not signals:
        _fail("OBSERVATION_INVALID")
    normalized_signals: list[str] = []
    for signal in signals:
        signal_name = _require_string(signal, "OBSERVATION_INVALID")
        if _SAFE_SIGNAL_RE.fullmatch(signal_name) is None:
            _fail("OBSERVATION_INVALID")
        normalized_signals.append(signal_name)
    if len(set(normalized_signals)) != len(normalized_signals):
        _fail("OBSERVATION_INVALID")
    return window_seconds, normalized_signals


def _normalized_request_for_id(request: Mapping[str, object]) -> object:
    normalized = _plain_json(request)
    if not isinstance(normalized, dict):
        _fail("SCHEMA_INVALID")
    return normalized


def plan_production_reconciliation(request: Mapping[str, object]) -> dict[str, object]:
    """Validate an in-memory v1 request and return a deterministic dry-run plan."""

    request_mapping = _require_mapping(request)
    _check_keys(request_mapping, _REQUEST_KEYS)

    source = _require_mapping(request_mapping.get("source"), "SOURCE_SHA_INVALID")
    _check_keys(source, frozenset({"git_sha"}), code="SCHEMA_INVALID")
    if "git_sha" not in source:
        _fail("SOURCE_SHA_INVALID")
    source_sha = _require_sha(source["git_sha"])

    operation = request_mapping.get("operation")
    if operation not in {"activate", "rollback"}:
        _fail("SCHEMA_INVALID")

    release_base, _current_pointer = _validate_layout(request_mapping.get("layout"))
    target = _require_mapping(request_mapping.get("target_release"), "SOURCE_ROOT_MISMATCH")
    _check_keys(target, frozenset({"release_id", "git_sha", "root", "manifest"}))
    target_release_id, target_git_sha, target_root = _validate_target_identity(
        target, source_sha=source_sha, release_base=release_base
    )
    target_manifest_digest, manifest_previous = _validate_manifest(
        target["manifest"], source_sha=source_sha
    )

    previous_identity, rollback_compatible = _validate_previous_release(
        request_mapping.get("previous_release"), release_base=release_base
    )
    if manifest_previous != (
        previous_identity["git_sha"],
        previous_identity["manifest_sha256"],
    ):
        _fail("MANIFEST_INVALID")
    if rollback_compatible is not True:
        _fail("ROLLBACK_INCOMPATIBLE")

    expected_current = _validate_pointer(
        request_mapping.get("pointer"), release_base=release_base
    )
    _validate_known_releases(
        request_mapping.get("known_releases"),
        release_base=release_base,
        target={
            "release_id": target_release_id,
            "git_sha": target_git_sha,
            "root": target_root,
        },
    )
    systemd_enabled, systemd_units, systemd_actions = _validate_user_systemd(
        request_mapping.get("user_systemd")
    )
    observation_window, observation_signals = _validate_observation(
        request_mapping.get("observation")
    )

    plan_identity = hashlib.sha256(
        _canonical_json(_normalized_request_for_id(request_mapping)).encode("utf-8")
    ).hexdigest()
    plan: dict[str, object] = {
        "schema_version": PLAN_SCHEMA_VERSION,
        "plan_id": plan_identity,
        "operation": operation,
        "source": {"git_sha": source_sha},
        "target_release": {
            "release_id": target_release_id,
            "git_sha": target_git_sha,
            "root": target_root,
            "manifest_sha256": target_manifest_digest,
        },
        "expected_current": expected_current,
        "preflight": [
            {"id": "source_identity", "result": "pass"},
            {"id": "release_identity", "result": "pass"},
            {"id": "manifest", "result": "pass"},
            {"id": "pointer_cas", "result": "pass"},
            {"id": "rollback_compatibility", "result": "pass"},
            {"id": "identity_collision", "result": "pass"},
        ],
        "steps": [
            {"id": "manifest_preflight", "kind": "manifest_preflight", "effect": "none"},
            {
                "id": "pointer_cas",
                "kind": "expected_current_pointer_cas",
                "effect": "planned_only",
            },
            {
                "id": "atomic_switch",
                "kind": "planned_atomic_switch",
                "effect": "planned_only",
            },
            {
                "id": "user_systemd",
                "kind": "optional_user_systemd",
                "effect": "planned_only",
                "enabled": systemd_enabled,
                "units": systemd_units,
                "actions": systemd_actions,
            },
            {
                "id": "same_round_readback",
                "kind": "same_round_readback",
                "effect": "planned_only",
            },
            {
                "id": "observation",
                "kind": "observation",
                "effect": "planned_only",
                "window_seconds": observation_window,
                "signals": observation_signals,
            },
            {"id": "rollback", "kind": "rollback", "effect": "planned_only"},
        ],
        "external_actions": [],
        "redaction": {
            "secret_values_emitted": False,
            "manifest_file_bytes_emitted": False,
            "volatile_values_emitted": False,
        },
    }
    return plan


__all__ = [
    "PlannerValidationError",
    "canonical_plan_json",
    "plan_production_reconciliation",
]
