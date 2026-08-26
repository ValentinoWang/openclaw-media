#!/usr/bin/env python3
"""One-shot bootstrap for the single main-reconciliation branch."""
from __future__ import annotations
import base64
import json
from pathlib import Path
import subprocess
import sys
import zlib

EXECUTABLES = {
    "scripts/reconcile_main_source.py",
    "openclaw-tag-router/scripts/run_stage2_authenticated_acceptance.py",
}


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    chunks = sorted((root / "scripts/reconcile_payload").glob("*.txt"))
    if not chunks:
        raise RuntimeError("reconciliation payload chunks are missing")
    payload = "".join(path.read_text(encoding="ascii") for path in chunks)
    files = json.loads(zlib.decompress(base64.b64decode(payload)).decode("utf-8"))
    if not isinstance(files, dict):
        raise RuntimeError("reconciliation payload is invalid")
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(content), encoding="utf-8")
        if relative in EXECUTABLES:
            path.chmod(0o755)
    subprocess.run([sys.executable, str(root / "scripts/reconcile_main_source.py")], check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
