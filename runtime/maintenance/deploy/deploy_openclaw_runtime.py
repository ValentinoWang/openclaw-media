#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path


REPO_ROOT = Path("/home/ubuntu/selfmedia-tools")
TAG_ROUTER_SOURCE_DIR = REPO_ROOT / "openclaw-tag-router"
TAG_ROUTER_TARGET_DIR = Path("/home/ubuntu/.openclaw/extensions/openclaw-tag-router")
SYNC_MODELS_SCRIPT = REPO_ROOT / "runtime" / "maintenance" / "deploy" / "sync_openclaw_agent_models.py"
SYNC_BOT_CONFIG_SCRIPT = REPO_ROOT / "runtime" / "maintenance" / "deploy" / "sync_openclaw_bot_config.py"
SINGLE_SOURCE_GUARD = Path("/home/ubuntu/scripts/quality/check_openclaw_single_source_contract.py")
MODEL_CONFIG_GUARD = Path("/home/ubuntu/scripts/quality/check_openclaw_model_config_contract.py")
TAG_ROUTER_GUARD = Path("/home/ubuntu/scripts/quality/check_feishu_tag_router_contract.py")
SINGLE_SOURCE_RUNTIME_SMOKE = Path("/home/ubuntu/scripts/qa/openclaw_single_source_runtime_smoke.py")


def run(command: list[str]) -> None:
    subprocess.run(command, check=True, timeout=int(os.getenv("OPENCLAW_DEPLOY_COMMAND_TIMEOUT_SECONDS", "300")))


def deploy(*, restart_gateway: bool, skip_guards: bool = False) -> dict[str, object]:
    if not TAG_ROUTER_SOURCE_DIR.is_dir():
        raise SystemExit(f"missing source dir: {TAG_ROUTER_SOURCE_DIR}")
    run(["python3", str(SYNC_BOT_CONFIG_SCRIPT), "--direction", "repo-to-obsidian"])
    TAG_ROUTER_TARGET_DIR.parent.mkdir(parents=True, exist_ok=True)
    run(
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
    )
    run(["python3", str(SYNC_MODELS_SCRIPT)])
    if not skip_guards:
        run(["python3", str(MODEL_CONFIG_GUARD)])
        run(["python3", str(TAG_ROUTER_GUARD)])
        run(["python3", str(SINGLE_SOURCE_GUARD)])
    if restart_gateway:
        run(["systemctl", "--user", "restart", "openclaw-gateway.service", "openclaw-feishu-gateway.service"])
        if not skip_guards:
            run(["python3", str(SINGLE_SOURCE_RUNTIME_SMOKE)])
    return {
        "ok": True,
        "tag_router_source": str(TAG_ROUTER_SOURCE_DIR),
        "tag_router_target": str(TAG_ROUTER_TARGET_DIR),
        "synced_config": str(SYNC_BOT_CONFIG_SCRIPT),
        "synced_models": str(SYNC_MODELS_SCRIPT),
        "ran_guards": not skip_guards,
        "ran_runtime_smoke": restart_gateway and not skip_guards,
        "restarted_gateway": restart_gateway,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Deploy repo-managed OpenClaw runtime artifacts.")
    parser.add_argument("--no-restart", action="store_true", help="Do not restart OpenClaw gateway services after deploy.")
    parser.add_argument("--skip-guards", action="store_true", help="Skip quality guards after generating runtime artifacts.")
    args = parser.parse_args()
    result = deploy(restart_gateway=not args.no_restart, skip_guards=args.skip_guards)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
