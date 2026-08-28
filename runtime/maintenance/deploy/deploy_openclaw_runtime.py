#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from pathlib import Path


REPO_ROOT = Path(os.getenv("OPENCLAW_REPO_ROOT") or Path(__file__).resolve().parents[3])
OPENCLAW_RUNTIME_HOME = Path(os.getenv("OPENCLAW_RUNTIME_HOME") or Path.home() / ".openclaw")
NODE_RUNTIME_BIN = os.getenv("OPENCLAW_NODE_RUNTIME_BIN", "").strip()
TAG_ROUTER_SOURCE_DIR = REPO_ROOT / "openclaw-tag-router"
TAG_ROUTER_TARGET_DIR = Path(os.getenv("OPENCLAW_TAG_ROUTER_TARGET_DIR") or OPENCLAW_RUNTIME_HOME / "extensions/openclaw-tag-router")
TAG_ROUTER_SYSTEMD_SOURCE_DIR = TAG_ROUTER_SOURCE_DIR / "deploy/systemd/user"
USER_SYSTEMD_DIR = Path(os.getenv("OPENCLAW_USER_SYSTEMD_DIR") or Path.home() / ".config/systemd/user")
BOT_CENTER_ROOT = Path(os.getenv("OPENCLAW_BOT_CENTER_ROOT") or REPO_ROOT / "openclaw-bot-center")
BOT_CENTER_PUBLISH_DIR = Path(os.getenv("OPENCLAW_BOT_CENTER_PUBLISH_DIR") or "/var/www/openclaw/bots")
SYNC_MODELS_SCRIPT = REPO_ROOT / "runtime" / "maintenance" / "deploy" / "sync_openclaw_agent_models.py"
SYNC_BOT_CONFIG_SCRIPT = REPO_ROOT / "runtime" / "maintenance" / "deploy" / "sync_openclaw_bot_config.py"
OPENCLAW_QUALITY_ROOT = Path(os.getenv("OPENCLAW_QUALITY_ROOT") or REPO_ROOT / "scripts/quality")
OPENCLAW_QA_ROOT = Path(os.getenv("OPENCLAW_QA_ROOT") or REPO_ROOT / "scripts/qa")
SINGLE_SOURCE_GUARD = OPENCLAW_QUALITY_ROOT / "check_openclaw_single_source_contract.py"
MODEL_CONFIG_GUARD = OPENCLAW_QUALITY_ROOT / "check_openclaw_model_tiers_contract.py"
TAG_ROUTER_GUARD = OPENCLAW_QUALITY_ROOT / "check_feishu_tag_router_contract.py"
BOT_CENTER_CAPABILITY_GUARD = OPENCLAW_QUALITY_ROOT / "check_bot_center_capability_detail_contract.py"
BOT_CENTER_DELETION_GUARD = OPENCLAW_QUALITY_ROOT / "check_deletion_contract_coverage.py"
BOT_CENTER_PUBLISHED_DATA_GUARD = OPENCLAW_QUALITY_ROOT / "check_bot_center_published_data_sync.py"
SINGLE_SOURCE_RUNTIME_SMOKE = OPENCLAW_QA_ROOT / "openclaw_single_source_runtime_smoke.py"
FEISHU_TRANSPORT_GUARD = OPENCLAW_QUALITY_ROOT / "check_openclaw_feishu_transport_contract.py"
JOURNAL_TIMER_UNITS = (
    "openclaw-daily-journal-template.timer",
    "openclaw-weekly-self-model-summary.timer",
    "openclaw-feishu-transport-smoke.timer",
)
JOURNAL_SYSTEMD_FILES = (
    "openclaw-daily-journal-template.service",
    "openclaw-daily-journal-template.timer",
    "openclaw-weekly-self-model-summary.service",
    "openclaw-weekly-self-model-summary.timer",
    "openclaw-feishu-transport-smoke.service",
    "openclaw-feishu-transport-smoke.timer",
)
FORBIDDEN_CRON_JOB_NAMES = (
    "daily-weekly-self-model-review",
)


def run(command: list[str], *, cwd: Path | None = None, timeout: int | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    if NODE_RUNTIME_BIN:
        env["PATH"] = f"{NODE_RUNTIME_BIN}:{env.get('PATH', '')}"
    proc = subprocess.run(
        command,
        cwd=str(cwd) if cwd else None,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        timeout=timeout or int(os.getenv("OPENCLAW_DEPLOY_COMMAND_TIMEOUT_SECONDS", "300")),
    )
    if proc.returncode != 0:
        command_text = " ".join(command)
        stdout_tail = (proc.stdout or "")[-2000:]
        stderr_tail = (proc.stderr or "")[-2000:]
        raise RuntimeError(
            f"command failed ({proc.returncode}): {command_text}\n"
            f"--- stdout tail ---\n{stdout_tail}\n"
            f"--- stderr tail ---\n{stderr_tail}"
        )
    return proc


def run_with_retries(
    command: list[str],
    *,
    attempts: int,
    wait_seconds: int,
    cwd: Path | None = None,
    timeout: int | None = None,
) -> subprocess.CompletedProcess[str]:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return run(command, cwd=cwd, timeout=timeout)
        except Exception as exc:  # noqa: PERF203 - deployment readiness retry keeps the error context.
            last_error = exc
            if attempt < attempts:
                time.sleep(wait_seconds)
    if last_error is None:
        raise RuntimeError("run_with_retries failed without an error")
    raise last_error


def sync_tag_router_source_to_active() -> None:
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


def install_journal_systemd_units() -> None:
    missing = [name for name in JOURNAL_SYSTEMD_FILES if not (TAG_ROUTER_SYSTEMD_SOURCE_DIR / name).is_file()]
    if missing:
        raise SystemExit(f"missing tag-router systemd source units: {missing}")
    USER_SYSTEMD_DIR.mkdir(parents=True, exist_ok=True)
    for name in JOURNAL_SYSTEMD_FILES:
        run(["install", "-m", "0644", str(TAG_ROUTER_SYSTEMD_SOURCE_DIR / name), str(USER_SYSTEMD_DIR / name)])
    run(["systemctl", "--user", "daemon-reload"])
    run(["systemctl", "--user", "enable", "--now", *JOURNAL_TIMER_UNITS])


def assert_no_forbidden_openclaw_cron_jobs() -> None:
    proc = run(["openclaw", "cron", "list", "--json"], timeout=60)
    payload = json.loads(proc.stdout)
    jobs = payload.get("jobs") if isinstance(payload, dict) else None
    if not isinstance(jobs, list):
        raise SystemExit("openclaw cron list --json did not return a jobs list")
    offenders: list[str] = []
    for job in jobs:
        if not isinstance(job, dict):
            continue
        searchable = json.dumps(job, ensure_ascii=False, sort_keys=True)
        if any(token in searchable for token in FORBIDDEN_CRON_JOB_NAMES):
            offenders.append(str(job.get("id") or job.get("name") or "<unknown>"))
    if offenders:
        raise SystemExit(f"remove journal/self-model OpenClaw cron jobs before deploy: {offenders}")


def build_and_publish_bot_center() -> None:
    if not BOT_CENTER_ROOT.is_dir():
        raise SystemExit(f"missing Bot Center root: {BOT_CENTER_ROOT}")
    run(["npm", "run", "generate:data"], cwd=BOT_CENTER_ROOT, timeout=600)
    run(["npm", "run", "validate:data"], cwd=BOT_CENTER_ROOT, timeout=600)
    run(["npm", "run", "build"], cwd=BOT_CENTER_ROOT, timeout=900)
    run(["python3", str(BOT_CENTER_CAPABILITY_GUARD)], timeout=300)
    run(["python3", str(BOT_CENTER_DELETION_GUARD)], timeout=300)
    BOT_CENTER_PUBLISH_DIR.mkdir(parents=True, exist_ok=True)
    run(
        [
            "rsync",
            "-a",
            "--delete",
            f"{BOT_CENTER_ROOT / 'dist'}/",
            f"{BOT_CENTER_PUBLISH_DIR}/",
        ],
        timeout=300,
    )
    run(["python3", str(BOT_CENTER_PUBLISHED_DATA_GUARD)], timeout=120)


def deploy(*, restart_gateway: bool, skip_guards: bool = False) -> dict[str, object]:
    sync_tag_router_source_to_active()
    install_journal_systemd_units()
    build_and_publish_bot_center()
    assert_no_forbidden_openclaw_cron_jobs()
    if not skip_guards:
        run(["python3", str(MODEL_CONFIG_GUARD)])
        run(["python3", str(TAG_ROUTER_GUARD)])
        run(["python3", str(SINGLE_SOURCE_GUARD)])
        run(["python3", str(FEISHU_TRANSPORT_GUARD)])
    if restart_gateway:
        run(["systemctl", "--user", "restart", "openclaw-gateway.service"])
        run(["sudo", "-n", "systemctl", "restart", "openclaw-feishu-gateway.service"])
        if not skip_guards:
            run_with_retries(["python3", str(SINGLE_SOURCE_RUNTIME_SMOKE)], attempts=3, wait_seconds=10)
    return {
        "ok": True,
        "tag_router_source": str(TAG_ROUTER_SOURCE_DIR),
        "tag_router_target": str(TAG_ROUTER_TARGET_DIR),
        "tag_router_workspace": str(OPENCLAW_RUNTIME_HOME / "workspace/openclaw-tag-router"),
        "synced_config": str(SYNC_BOT_CONFIG_SCRIPT),
        "synced_models": str(SYNC_MODELS_SCRIPT),
        "installed_systemd_units": [str(USER_SYSTEMD_DIR / name) for name in JOURNAL_SYSTEMD_FILES],
        "bot_center_root": str(BOT_CENTER_ROOT),
        "bot_center_published": str(BOT_CENTER_PUBLISH_DIR),
        "checked_cron_forbidden_jobs": list(FORBIDDEN_CRON_JOB_NAMES),
        "ran_guards": not skip_guards,
        "ran_runtime_smoke": restart_gateway and not skip_guards,
        "restarted_gateway": restart_gateway,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Deploy repo-managed OpenClaw runtime artifacts.")
    parser.add_argument("--no-restart", action="store_true", help="Do not restart OpenClaw gateway services after deploy.")
    parser.add_argument("--skip-guards", action="store_true", help="Skip quality guards after generating runtime artifacts.")
    args = parser.parse_args()
    try:
        result = deploy(restart_gateway=not args.no_restart, skip_guards=args.skip_guards)
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        raise SystemExit(1) from exc
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
