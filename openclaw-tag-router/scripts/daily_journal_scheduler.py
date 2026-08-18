#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SETTINGS_PATH = PLUGIN_ROOT / "config/settings.yaml"
DEFAULT_BRIDGE_PATH = PLUGIN_ROOT / "bridge.py"
DEFAULT_SESSIONS_PATH = Path("/home/ubuntu/.openclaw/agents/feishu-daily/sessions/sessions.json")
DEFAULT_OPENCLAW_BIN_CANDIDATES = (
    "/home/ubuntu/.nvm/versions/node/v22.22.2/bin/openclaw",
    "/home/ubuntu/.local/bin/openclaw",
    "/usr/local/bin/openclaw",
    "/usr/bin/openclaw",
)

if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from openclaw_app.router.daily_journal_contract import (  # noqa: E402
    DAILY_JOURNAL_TEMPLATE,
    week_bounds_for,
    week_key,
)


def load_settings(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def json_result(**fields: Any) -> dict[str, Any]:
    return {key: value for key, value in fields.items() if value is not None}


def latest_daily_delivery_target(sessions_path: Path = DEFAULT_SESSIONS_PATH) -> str:
    if not sessions_path.exists():
        return ""
    try:
        data = json.loads(sessions_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return ""
    candidates: list[tuple[int, str]] = []
    for value in data.values() if isinstance(data, dict) else []:
        if not isinstance(value, dict):
            continue
        delivery = value.get("deliveryContext") or {}
        if delivery.get("channel") != "feishu" or delivery.get("accountId") != "daily":
            continue
        target = str(delivery.get("to") or "").strip()
        if not target:
            continue
        updated = int(value.get("updatedAt") or value.get("lastInteractionAt") or 0)
        candidates.append((updated, target))
    if not candidates:
        return ""
    return sorted(candidates)[-1][1]


def resolve_delivery_target(settings: dict[str, Any]) -> str:
    journal = settings.get("daily_journal") or {}
    configured = str(os.environ.get("OPENCLAW_DAILY_JOURNAL_TARGET") or journal.get("notification_target") or "").strip()
    if configured:
        return configured
    sessions_path = Path(str(journal.get("notification_sessions_path") or DEFAULT_SESSIONS_PATH))
    return latest_daily_delivery_target(sessions_path)


def resolve_openclaw_binary(settings: dict[str, Any]) -> str:
    journal = settings.get("daily_journal") or {}
    candidates = [
        str(os.environ.get("OPENCLAW_BIN") or "").strip(),
        str(journal.get("openclaw_bin") or "").strip(),
        shutil.which("openclaw") or "",
        *DEFAULT_OPENCLAW_BIN_CANDIDATES,
    ]
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate).expanduser()
        if path.is_file():
            return str(path)
    return "openclaw"


def openclaw_command_env(openclaw_bin: str) -> dict[str, str]:
    env = dict(os.environ)
    path_parts = [str(Path(openclaw_bin).parent)] if "/" in openclaw_bin else []
    configured_path = env.get("PATH") or ""
    if configured_path:
        path_parts.append(configured_path)
    env["PATH"] = os.pathsep.join(path_parts)
    return env


def state_path(settings: dict[str, Any]) -> Path:
    journal = settings.get("daily_journal") or {}
    configured = str(journal.get("scheduler_state_path") or "").strip()
    if configured:
        return Path(configured)
    workspace_root = Path(str(settings.get("workspace_root") or "/home/ubuntu/.openclaw/workspace/openclaw-tag-router"))
    return workspace_root / "daily_journal_scheduler" / "state.json"


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"runs": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"runs": {}}
    if not isinstance(data, dict):
        return {"runs": {}}
    if not isinstance(data.get("runs"), dict):
        data["runs"] = {}
    return data


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def send_feishu_message(settings: dict[str, Any], target: str, text: str, *, dry_run: bool) -> dict[str, Any]:
    journal = settings.get("daily_journal") or {}
    account = str(journal.get("notification_account") or "daily")
    channel = str(journal.get("notification_channel") or "feishu")
    openclaw_bin = resolve_openclaw_binary(settings)
    cmd = [
        openclaw_bin,
        "message",
        "send",
        "--channel",
        channel,
        "--account",
        account,
        "--target",
        target,
        "--message",
        text,
        "--json",
    ]
    if dry_run:
        cmd.append("--dry-run")
    try:
        proc = subprocess.run(cmd, text=True, capture_output=True, timeout=60, env=openclaw_command_env(openclaw_bin))
    except FileNotFoundError as exc:
        return {"ok": False, "returncode": 127, "stdout": "", "stderr": str(exc), "command": openclaw_bin}
    output = (proc.stdout or "").strip()
    parsed: Any = {}
    if output:
        try:
            parsed = json.loads(output)
        except json.JSONDecodeError:
            parsed = {"raw": output}
    if proc.returncode != 0:
        return {"ok": False, "returncode": proc.returncode, "stdout": output, "stderr": (proc.stderr or "").strip()}
    return {"ok": True, "returncode": 0, "result": parsed}


def run_bridge(settings: dict[str, Any], settings_path: Path, text: str, now: datetime) -> dict[str, Any]:
    workspace_root = str(settings.get("workspace_root") or "/home/ubuntu/.openclaw/workspace/openclaw-tag-router")
    payload = {
        "text": text,
        "source": "scheduler",
        "chat_type": "private",
        "created_at": now.isoformat(),
        "metadata": {
            "account_id": "daily",
            "scheduler": "daily_journal",
            "scheduled_text": text,
        },
    }
    cmd = ["python3", str(DEFAULT_BRIDGE_PATH), "ingest", workspace_root, str(settings_path)]
    env = dict(os.environ)
    env["PYTHONPATH"] = f"{PLUGIN_ROOT}:{env.get('PYTHONPATH', '')}".rstrip(":")
    proc = subprocess.run(cmd, input=json.dumps(payload, ensure_ascii=False), text=True, capture_output=True, timeout=1800, env=env)
    output = (proc.stdout or "").strip()
    parsed: Any = {}
    if output:
        try:
            parsed = json.loads(output)
        except json.JSONDecodeError:
            parsed = {"raw": output}
    if proc.returncode != 0:
        return {"ok": False, "returncode": proc.returncode, "stdout": output, "stderr": (proc.stderr or "").strip()}
    return {"ok": True, "returncode": 0, "result": parsed, "stderr": (proc.stderr or "").strip()}


def should_skip(state: dict[str, Any], run_key: str, force: bool) -> bool:
    return not force and run_key in (state.get("runs") or {})


def record_run(state_file: Path, state: dict[str, Any], run_key: str, payload: dict[str, Any]) -> None:
    runs = state.setdefault("runs", {})
    runs[run_key] = payload
    save_state(state_file, state)


def daily_prompt(settings: dict[str, Any], *, now: datetime, dry_run: bool, force: bool) -> dict[str, Any]:
    run_key = f"daily-template:{now.date().isoformat()}"
    state_file = state_path(settings)
    state = load_state(state_file)
    target = resolve_delivery_target(settings)
    if not target:
        return json_result(ok=False, status="missing_target", action="daily-template", runKey=run_key, statePath=str(state_file))
    if should_skip(state, run_key, force):
        return json_result(ok=True, status="skipped_already_sent", action="daily-template", runKey=run_key, statePath=str(state_file), target=target)
    delivery = send_feishu_message(settings, target, DAILY_JOURNAL_TEMPLATE, dry_run=dry_run)
    status = "dry_run" if dry_run else ("sent" if delivery.get("ok") else "send_failed")
    result = json_result(ok=bool(delivery.get("ok")), status=status, action="daily-template", runKey=run_key, target=target, delivery=delivery, template=DAILY_JOURNAL_TEMPLATE)
    if delivery.get("ok") and not dry_run:
        record_run(state_file, state, run_key, {"sentAt": now.isoformat(), "target": target, "delivery": delivery})
    result["statePath"] = str(state_file)
    return result


def weekly_summary(settings: dict[str, Any], settings_path: Path, *, now: datetime, dry_run: bool, force: bool) -> dict[str, Any]:
    timezone = str(settings.get("timezone") or "Asia/Shanghai")
    start, end = week_bounds_for(now, timezone)
    week = week_key(start, end)
    text = f"【周记】{week}"
    run_key = f"weekly-summary:{week}"
    state_file = state_path(settings)
    state = load_state(state_file)
    target = resolve_delivery_target(settings)
    if not target:
        return json_result(ok=False, status="missing_target", action="weekly-summary", runKey=run_key, week=week, statePath=str(state_file))
    if should_skip(state, run_key, force):
        return json_result(ok=True, status="skipped_already_run", action="weekly-summary", runKey=run_key, week=week, statePath=str(state_file), target=target)
    if dry_run:
        delivery = send_feishu_message(settings, target, f"周记定时提取 dry-run：{text}", dry_run=True)
        return json_result(ok=bool(delivery.get("ok")), status="dry_run", action="weekly-summary", runKey=run_key, week=week, target=target, scheduledText=text, delivery=delivery, statePath=str(state_file))
    bridge = run_bridge(settings, settings_path, text, now)
    if not bridge.get("ok"):
        return json_result(ok=False, status="bridge_failed", action="weekly-summary", runKey=run_key, week=week, target=target, bridge=bridge, statePath=str(state_file))
    bridge_result = bridge.get("result") if isinstance(bridge.get("result"), dict) else {}
    reply = str(bridge_result.get("reply") or bridge_result.get("message") or json.dumps(bridge_result, ensure_ascii=False))
    delivery = send_feishu_message(settings, target, reply, dry_run=False)
    status = "written_and_sent" if delivery.get("ok") else "written_send_failed"
    result = json_result(ok=bool(delivery.get("ok")), status=status, action="weekly-summary", runKey=run_key, week=week, target=target, bridge=bridge, delivery=delivery, statePath=str(state_file))
    if bridge.get("ok") and delivery.get("ok"):
        record_run(state_file, state, run_key, {"ranAt": now.isoformat(), "target": target, "bridge": bridge, "delivery": delivery})
    return result


def parse_now(value: str, timezone: str) -> datetime:
    if value:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(ZoneInfo(timezone))
    return datetime.now(ZoneInfo(timezone))


def main() -> int:
    parser = argparse.ArgumentParser(description="Daily journal scheduled prompt and weekly summary runner.")
    parser.add_argument("action", choices=["daily-template", "weekly-summary"])
    parser.add_argument("--settings", default=str(DEFAULT_SETTINGS_PATH))
    parser.add_argument("--now", default="")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    settings_path = Path(args.settings)
    settings = load_settings(settings_path)
    now = parse_now(args.now, str(settings.get("timezone") or "Asia/Shanghai"))
    if args.action == "daily-template":
        result = daily_prompt(settings, now=now, dry_run=args.dry_run, force=args.force)
    else:
        result = weekly_summary(settings, settings_path, now=now, dry_run=args.dry_run, force=args.force)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
