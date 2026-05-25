#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


REPO_ROOT = Path("/home/ubuntu/selfmedia-tools")
SOURCE_DIR = REPO_ROOT / "openclaw-tag-router"
TARGET_DIR = Path("/home/ubuntu/.openclaw/extensions/openclaw-tag-router")


def deploy(*, restart_gateway: bool) -> None:
    if not SOURCE_DIR.is_dir():
        raise SystemExit(f"missing source dir: {SOURCE_DIR}")
    TARGET_DIR.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "rsync",
            "-a",
            "--delete",
            "--exclude",
            "__pycache__/",
            "--exclude",
            ".pytest_cache/",
            "--exclude",
            "*.pyc",
            f"{SOURCE_DIR}/",
            f"{TARGET_DIR}/",
        ],
        check=True,
    )
    if restart_gateway:
        subprocess.run(["systemctl", "--user", "restart", "openclaw-feishu-gateway.service"], check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Deploy repo-managed openclaw-tag-router to runtime extension dir.")
    parser.add_argument("--no-restart", action="store_true", help="Do not restart openclaw-feishu-gateway.service after deploy.")
    args = parser.parse_args()
    deploy(restart_gateway=not args.no_restart)
    print(
        {
            "ok": True,
            "source": str(SOURCE_DIR),
            "target": str(TARGET_DIR),
            "restarted_gateway": not args.no_restart,
        }
    )


if __name__ == "__main__":
    main()
