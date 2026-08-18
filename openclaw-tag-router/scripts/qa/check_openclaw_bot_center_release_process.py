#!/usr/bin/env python3
"""Verify the Bot Center user service owns an explicit release process."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
from typing import Mapping, Sequence

DEFAULT_SERVICE = "openclaw-bot-center-api.service"


class ReleaseProcessGuardError(RuntimeError):
    pass


def parse_systemctl_properties(output: str) -> dict[str, str]:
    properties: dict[str, str] = {}
    for line in output.splitlines():
        key, separator, value = line.partition("=")
        if separator:
            properties[key] = value
    return properties


def read_service_properties(service: str) -> dict[str, str]:
    command = [
        "systemctl", "--user", "show", service,
        "--property=MainPID", "--property=ActiveState", "--property=SubState",
        "--property=ExecStart",
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode:
        raise ReleaseProcessGuardError(
            f"cannot read user service {service}: systemctl exited {completed.returncode}"
        )
    return parse_systemctl_properties(completed.stdout)


def read_process_cmdline(pid: int) -> list[str]:
    return [
        part.decode("utf-8", errors="surrogateescape")
        for part in Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
        if part
    ]


def required_option(tokens: Sequence[str], option: str) -> str:
    values = [tokens[index + 1] for index, token in enumerate(tokens[:-1]) if token == option]
    if len(values) != 1:
        raise ReleaseProcessGuardError(f"service process must contain exactly one {option}")
    return values[0]


def validate_release_process(
    properties: Mapping[str, str], cmdline: Sequence[str], cwd: str, release_root: Path
) -> int:
    if properties.get("ActiveState") != "active" or properties.get("SubState") != "running":
        raise ReleaseProcessGuardError("user service is not active and running")
    try:
        pid = int(properties.get("MainPID", ""))
    except ValueError as error:
        raise ReleaseProcessGuardError("user service has no numeric MainPID") from error
    if pid <= 0:
        raise ReleaseProcessGuardError("user service has no running MainPID")

    expected_root = str(release_root)
    expected_settings = str(release_root / "config" / "settings.yaml")
    exec_start = properties.get("ExecStart", "")
    if "openclaw_app.server_cli" not in exec_start or expected_settings not in exec_start:
        raise ReleaseProcessGuardError("service manager ExecStart does not identify the requested release")
    if len(cmdline) < 3 or cmdline[1:3] != ["-m", "openclaw_app.server_cli"]:
        raise ReleaseProcessGuardError("service MainPID is not openclaw_app.server_cli")
    if required_option(cmdline, "--settings") != expected_settings:
        raise ReleaseProcessGuardError("service MainPID settings do not identify the requested release")
    if cwd != expected_root:
        raise ReleaseProcessGuardError("service MainPID cwd does not identify the requested release")
    return pid


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-root", type=Path, required=True)
    parser.add_argument("--service", default=DEFAULT_SERVICE)
    args = parser.parse_args()
    release_root = args.release_root.expanduser()
    if not release_root.is_absolute():
        raise ReleaseProcessGuardError("--release-root must be absolute")

    properties = read_service_properties(args.service)
    try:
        pid = int(properties.get("MainPID", ""))
    except ValueError as error:
        raise ReleaseProcessGuardError("user service has no numeric MainPID") from error
    validated_pid = validate_release_process(
        properties, read_process_cmdline(pid), os.readlink(f"/proc/{pid}/cwd"), release_root
    )
    print(
        f"release process guard passed: service={args.service} pid={validated_pid} "
        f"release_root={release_root}"
    )


if __name__ == "__main__":
    main()
