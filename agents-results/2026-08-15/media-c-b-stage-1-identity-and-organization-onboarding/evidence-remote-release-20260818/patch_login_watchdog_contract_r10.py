#!/usr/bin/env python3
"""Add the exact Media auth module route to the remote watchdog allowlist."""

from __future__ import annotations

import json
import os
import pathlib
import stat
import sys


EXPECTED = "= /media.login.js"


def patch(path: pathlib.Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise SystemExit(f"contract is not a regular file: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    nginx = value.get("nginx")
    if not isinstance(nginx, dict):
        raise SystemExit("contract nginx object is missing")
    locations = nginx.get("allowedLoginLocations")
    if not isinstance(locations, list):
        raise SystemExit("contract allowlist is missing")
    if EXPECTED in locations:
        return
    if any(not isinstance(item, str) for item in locations):
        raise SystemExit("contract allowlist contains a non-string entry")
    if any(item == "= /media.auth.css" for item in locations):
        raise SystemExit("unexpected CSS route in login allowlist")
    insert_at = next((index for index, item in enumerate(locations) if item.startswith("~* ")), len(locations))
    locations.insert(insert_at, EXPECTED)
    encoded = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    mode = stat.S_IMODE(path.stat().st_mode)
    temporary = path.with_name(f".{path.name}.stage1-auth-r10.tmp")
    temporary.write_bytes(encoded)
    os.chmod(temporary, mode)
    os.replace(temporary, path)


if len(sys.argv) != 2:
    raise SystemExit("usage: patch_login_watchdog_contract_r10.py CONTRACT")
patch(pathlib.Path(sys.argv[1]))
