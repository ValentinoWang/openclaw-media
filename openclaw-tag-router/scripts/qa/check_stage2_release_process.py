#!/usr/bin/env python3
"""Evaluate an injected, read-only Stage-2 release observation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import shlex
from typing import Any


CHECK_ID = "stage2_release_readback"
SERVER_MODULE = "openclaw_app.server_cli"
MANIFEST_FIELDS = ("release_id", "commit_sha", "manifest_sha256")
EXPECTED_FIELDS = (
    "service_name",
    "release_root",
    "settings_path",
    "port",
    "pointer_path",
    "manifest_identity",
    "http_statuses",
)
OBSERVED_FIELDS = ("systemd", "process", "pointer", "manifest", "http_probes")

FAILURE_CODES = frozenset(
    {
        "SERVICE_INACTIVE",
        "MAIN_PID_MISSING_OR_INVALID",
        "PID_CWD_DRIFT",
        "EXECSTART_MODULE_MISMATCH",
        "SETTINGS_OR_PORT_MISMATCH",
        "POINTER_RELEASE_ROOT_DRIFT",
        "MANIFEST_IDENTITY_MISMATCH",
        "REQUIRED_PROPERTY_MISSING",
        "HTTP_STATUS_MISMATCH",
    }
)


def _pass() -> dict[str, str]:
    return {"status": "PASS", "code": "OK", "check": CHECK_ID}


def _fail(code: str) -> dict[str, str]:
    if code not in FAILURE_CODES:
        raise ValueError("unsupported readback failure code")
    return {"status": "FAIL", "code": code, "check": CHECK_ID}


def _is_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value)


def _is_status(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _parse_pid(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if not isinstance(value, str):
        return None
    token = value.strip()
    if not token or not token.isascii() or not token.isdecimal():
        return None
    pid = int(token, 10)
    return pid if pid > 0 else None


def _mapping(value: Any) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _has_fields(value: Mapping[str, Any], fields: Sequence[str]) -> bool:
    return all(field in value for field in fields)


def _option_values(tokens: Sequence[Any], option: str) -> list[str] | None:
    values: list[str] = []
    for index, token in enumerate(tokens):
        if token != option:
            continue
        if index + 1 >= len(tokens) or not isinstance(tokens[index + 1], str):
            return None
        values.append(tokens[index + 1])
    return values


def _command_module(tokens: Sequence[Any]) -> bool:
    modules = [
        tokens[index + 1]
        for index, token in enumerate(tokens[:-1])
        if token == "-m"
    ]
    return len(modules) == 1 and modules[0] == SERVER_MODULE


def _command_tokens(value: Any) -> list[str] | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        tokens = shlex.split(value, posix=True)
    except ValueError:
        return None
    return tokens if tokens else None


def _argv_tokens(value: Any) -> Sequence[Any] | None:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        return None
    return value


def _expected_http_statuses(value: Any) -> dict[tuple[str, str], int] | None:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        return None
    statuses: dict[tuple[str, str], int] = {}
    for probe in value:
        entry = _mapping(probe)
        if entry is None or not _has_fields(entry, ("surface", "path", "status")):
            return None
        surface = entry["surface"]
        path = entry["path"]
        status = entry["status"]
        if not _is_text(surface) or not _is_text(path) or not _is_status(status):
            return None
        key = (surface, path)
        if key in statuses:
            return None
        statuses[key] = status
    return statuses


def _observed_http_statuses(value: Any) -> dict[tuple[str, str], int] | None:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        return None
    statuses: dict[tuple[str, str], int] = {}
    for probe in value:
        entry = _mapping(probe)
        if entry is None or not _has_fields(entry, ("surface", "path", "status")):
            return None
        surface = entry["surface"]
        path = entry["path"]
        status = entry["status"]
        if not _is_text(surface) or not _is_text(path) or not _is_status(status):
            return None
        key = (surface, path)
        if key in statuses:
            return None
        statuses[key] = status
    return statuses


def _validate_expected(expected: Any) -> tuple[Mapping[str, Any], dict[tuple[str, str], int]] | None:
    expected_map = _mapping(expected)
    if expected_map is None or not _has_fields(expected_map, EXPECTED_FIELDS):
        return None
    for field in ("service_name", "release_root", "settings_path", "pointer_path"):
        if not _is_text(expected_map[field]):
            return None
    if not _is_status(expected_map["port"]) or expected_map["port"] <= 0:
        return None

    expected_manifest = _mapping(expected_map["manifest_identity"])
    if expected_manifest is None or not _has_fields(expected_manifest, MANIFEST_FIELDS):
        return None
    if not all(_is_text(expected_manifest[field]) for field in MANIFEST_FIELDS):
        return None

    statuses = _expected_http_statuses(expected_map["http_statuses"])
    if statuses is None or not statuses:
        return None
    return expected_map, statuses


def _evaluate(observed: Any, expected: Any) -> dict[str, str]:
    expected_data = _validate_expected(expected)
    if expected_data is None:
        return _fail("REQUIRED_PROPERTY_MISSING")
    expected_map, expected_statuses = expected_data

    observed_map = _mapping(observed)
    if observed_map is None or not _has_fields(observed_map, OBSERVED_FIELDS):
        return _fail("REQUIRED_PROPERTY_MISSING")

    systemd = _mapping(observed_map["systemd"])
    if systemd is None or not _has_fields(systemd, ("ActiveState", "SubState", "ExecStart")):
        return _fail("REQUIRED_PROPERTY_MISSING")
    if systemd["ActiveState"] != "active" or systemd["SubState"] != "running":
        return _fail("SERVICE_INACTIVE")

    if "MainPID" not in systemd:
        return _fail("MAIN_PID_MISSING_OR_INVALID")
    main_pid = _parse_pid(systemd["MainPID"])
    if main_pid is None:
        return _fail("MAIN_PID_MISSING_OR_INVALID")

    process = _mapping(observed_map["process"])
    if process is None or not _has_fields(process, ("pid", "cwd", "argv")):
        return _fail("REQUIRED_PROPERTY_MISSING")
    process_pid = _parse_pid(process["pid"])
    if process_pid is None or process_pid != main_pid:
        return _fail("MAIN_PID_MISSING_OR_INVALID")
    if process["cwd"] != expected_map["release_root"]:
        return _fail("PID_CWD_DRIFT")

    exec_start = _command_tokens(systemd["ExecStart"])
    process_argv = _argv_tokens(process["argv"])
    if exec_start is None or not _command_module(exec_start):
        return _fail("EXECSTART_MODULE_MISMATCH")
    if process_argv is None or not _command_module(process_argv):
        return _fail("EXECSTART_MODULE_MISMATCH")

    expected_settings = expected_map["settings_path"]
    expected_port = str(expected_map["port"])
    for tokens in (exec_start, process_argv):
        settings = _option_values(tokens, "--settings")
        ports = _option_values(tokens, "--port")
        if settings != [expected_settings] or ports != [expected_port]:
            return _fail("SETTINGS_OR_PORT_MISMATCH")

    pointer = _mapping(observed_map["pointer"])
    if pointer is None or not _has_fields(pointer, ("path", "target")):
        return _fail("REQUIRED_PROPERTY_MISSING")
    if pointer["path"] != expected_map["pointer_path"]:
        return _fail("POINTER_RELEASE_ROOT_DRIFT")
    if pointer["target"] != expected_map["release_root"]:
        return _fail("POINTER_RELEASE_ROOT_DRIFT")

    manifest = _mapping(observed_map["manifest"])
    expected_manifest = expected_map["manifest_identity"]
    if manifest is None or not _has_fields(manifest, MANIFEST_FIELDS):
        return _fail("REQUIRED_PROPERTY_MISSING")
    if any(manifest[field] != expected_manifest[field] for field in MANIFEST_FIELDS):
        return _fail("MANIFEST_IDENTITY_MISMATCH")

    observed_statuses = _observed_http_statuses(observed_map["http_probes"])
    if observed_statuses is None or observed_statuses != expected_statuses:
        return _fail("HTTP_STATUS_MISMATCH")
    return _pass()


def evaluate_readback(observed: Mapping[str, Any], expected: Mapping[str, Any]) -> dict[str, str]:
    """Return a stable, redacted decision for caller-supplied observations only."""

    try:
        return _evaluate(observed, expected)
    except Exception:
        # Malformed injected mappings must fail closed without serializing input.
        return _fail("REQUIRED_PROPERTY_MISSING")
