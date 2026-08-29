#!/usr/bin/env python3
from __future__ import annotations

import os
import pathlib
import stat
import sys


ANCHOR = "    location = /openclaw/bots/ingest {\n"
BLOCK = """    # Unregistered legacy Media auth routes are closed at the transport boundary.
    # Exact OAuth routes above still win before this prefix location.
    location ^~ /openclaw/media/auth/ {
        return 404;
    }

"""


def patch(path: pathlib.Path) -> None:
    source = path.read_text(encoding="utf-8")
    if BLOCK in source:
        return
    if source.count(ANCHOR) != 1:
        raise SystemExit(f"expected one Nginx insertion anchor in {path}")
    updated = source.replace(ANCHOR, BLOCK + ANCHOR, 1)
    temporary = path.with_name(f".{path.name}.stage1-auth-media-oauth-r9.tmp")
    mode = stat.S_IMODE(path.stat().st_mode)
    temporary.write_text(updated, encoding="utf-8")
    os.chmod(temporary, mode)
    os.replace(temporary, path)


if len(sys.argv) < 2:
    raise SystemExit("usage: patch_nginx_media_auth_boundary.py PATH ...")
for argument in sys.argv[1:]:
    patch(pathlib.Path(argument))
