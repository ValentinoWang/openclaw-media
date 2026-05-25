#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


REPO_ROOT = Path("/home/ubuntu/selfmedia-tools")
TAG_ROUTER_SOURCE_DIR = REPO_ROOT / "openclaw-tag-router"
TAG_ROUTER_TARGET_DIR = Path("/home/ubuntu/.openclaw/extensions/openclaw-tag-router")
SYNC_MODELS_SCRIPT = REPO_ROOT / "tools" / "sync_openclaw_agent_models.py"


def deploy(*, restart_gateway: bool) -> None:
    if not TAG_ROUTER_SOURCE_DIR.is_dir():
        raise SystemExit(f"missing source dir: {TAG_ROUTER_SOURCE_DIR}")
    TAG_ROUTER_TARGET_DIR.parent.mkdir(parents=True, exist_ok=True)
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
            f"{TAG_ROUTER_SOURCE_DIR}/",
            f"{TAG_ROUTER_TARGET_DIR}/",
        ],
        check=True,
    )
    subprocess.run(["python3", str(SYNC_MODELS_SCRIPT)], check=True)
    if restart_gateway:
        subprocess.run(["systemctl", "--user", "restart", "openclaw-feishu-gateway.service"], check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Deploy repo-managed OpenClaw runtime artifacts.")
    parser.add_argument("--no-restart", action="store_true", help="Do not restart openclaw-feishu-gateway.service after deploy.")
    args = parser.parse_args()
    deploy(restart_gateway=not args.no_restart)
    print(
        {
            "ok": True,
            "tag_router_source": str(TAG_ROUTER_SOURCE_DIR),
            "tag_router_target": str(TAG_ROUTER_TARGET_DIR),
            "restarted_gateway": not args.no_restart,
        }
    )


if __name__ == "__main__":
    main()
