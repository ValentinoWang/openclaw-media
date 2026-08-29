#!/usr/bin/env python3
from __future__ import annotations

import os
import pathlib
import re
import stat
import sys


CONTRACT_OLD = '''      "id": "retired_media_oauth_callback",
      "path": "/openclaw/media/oauth/callback",
      "expectedStatus": 404,
      "scopes": ["public", "loopback"],
      "contentTypePrefix": "application/json",'''
CONTRACT_NEW = '''      "id": "media_oauth_callback_without_query",
      "path": "/openclaw/media/oauth/callback",
      "expectedStatus": 400,
      "scopes": ["public", "loopback"],
      "contentTypePrefix": "text/html",'''

WATCHDOG_OLD = '''    positive_session = run(
        [
            sys.executable,
            str(MEDIA_SESSION_COMPOSITION_GUARD),
            "--session-composition-root",
            "/home/ubuntu/selfmedia-tools/openclaw-tag-router",
        ]
    )'''
WATCHDOG_NEW = '''    positive_listener = run(["ss", "-H", "-ltnp", "sport", "=", ":8787"])
    positive_pids = {int(value) for value in re.findall(r"pid=(\\d+)", positive_listener.stdout)}
    if positive_listener.returncode != 0 or len(positive_pids) != 1:
        raise AssertionError("canonical Media backend listener is unavailable")
    positive_release = Path(f"/proc/{next(iter(positive_pids))}/cwd").resolve(strict=True)
    positive_session = run(
        [
            sys.executable,
            str(MEDIA_SESSION_COMPOSITION_GUARD),
            "--session-composition-root",
            str(positive_release),
        ]
    )'''


def replace_once(path: pathlib.Path, old: str, new: str) -> None:
    source = path.read_text(encoding="utf-8")
    if new in source:
        return
    if source.count(old) != 1:
        raise SystemExit(f"expected one patch target in {path}")
    updated = source.replace(old, new, 1)
    mode = stat.S_IMODE(path.stat().st_mode)
    temporary = path.with_name(f".{path.name}.stage1-auth-media-oauth-r9.tmp")
    temporary.write_text(updated, encoding="utf-8")
    os.chmod(temporary, mode)
    os.replace(temporary, path)


if len(sys.argv) != 3:
    raise SystemExit("usage: patch_login_watchdog_r9.py CONTRACT WATCHDOG")
replace_once(pathlib.Path(sys.argv[1]), CONTRACT_OLD, CONTRACT_NEW)
replace_once(pathlib.Path(sys.argv[2]), WATCHDOG_OLD, WATCHDOG_NEW)
