#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any


REPO_CONFIG = Path("/home/ubuntu/selfmedia-tools/config/openclaw_bots.json")
OBSIDIAN_DIR = Path("/home/ubuntu/obsidian-diary/openclaw配置")
OBSIDIAN_CONFIG = OBSIDIAN_DIR / "openclaw_bots.json"
OBSIDIAN_NOTE = OBSIDIAN_DIR / "OpenClaw Bot LLM 配置.md"
SYNC_STATE = OBSIDIAN_DIR / ".openclaw_bots_sync_state.json"
MAC_OBSIDIAN_DIR = "/Users/vsiyo/Library/Mobile Documents/iCloud~md~obsidian/Documents/日记/openclaw配置"


def canonical_payload(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit(f"config is not a JSON object: {path}")
    for key in ("defaults", "bots", "profiles", "providers", "content_cleaner"):
        if not isinstance(payload.get(key), dict):
            raise SystemExit(f"config missing object field {key}: {path}")
    return payload


def canonical_text(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def canonical_hash(payload: dict[str, Any]) -> str:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def file_hash(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        return canonical_hash(canonical_payload(path))
    except SystemExit:
        return ""


def load_state() -> dict[str, Any]:
    if not SYNC_STATE.exists():
        return {}
    try:
        parsed = json.loads(SYNC_STATE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(tmp_name, path)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


def write_json_config(path: Path, payload: dict[str, Any], *, dry_run: bool) -> None:
    if dry_run:
        return
    atomic_write(path, canonical_text(payload))


def render_note(payload: dict[str, Any], repo_hash: str, obsidian_hash: str) -> str:
    now = datetime.now().isoformat(timespec="seconds")
    lines = [
        "# OpenClaw Bot LLM 配置",
        "",
        "> 自动生成说明文件；可读来源是同目录 `openclaw_bots.json`。不要手工改这份 Markdown。",
        "",
        f"- 服务器 Obsidian 路径：`{OBSIDIAN_DIR}`",
        f"- Mac Obsidian 目标路径：`{MAC_OBSIDIAN_DIR}`",
        f"- 仓库配置：`{REPO_CONFIG}`",
        f"- 最近同步：`{now}`",
        f"- repo sha256：`{repo_hash}`",
        f"- obsidian sha256：`{obsidian_hash}`",
        "",
        "## Bots",
        "",
        "| bot | provider | agent | model | thinking | timeout | cwd |",
        "|---|---|---|---|---|---:|---|",
    ]
    defaults = payload.get("defaults") or {}
    default_provider = (payload.get("providers") or {}).get(defaults.get("provider") or "") or {}
    for name, bot in sorted((payload.get("bots") or {}).items()):
        provider = (payload.get("providers") or {}).get((bot or {}).get("provider") or defaults.get("provider") or "") or default_provider
        merged = {**provider, **defaults, **(bot or {})}
        lines.append(
            "| "
            + " | ".join(
                [
                    str(name),
                    str(merged.get("provider") or ""),
                    str(merged.get("agent") or ""),
                    str(merged.get("model") or ""),
                    str(merged.get("thinking") or ""),
                    str(merged.get("timeout") or ""),
                    str(merged.get("cwd") or ""),
                ]
            )
            + " |"
        )
    lines.extend(["", "## Profiles", "", "| profile | provider | bot | model | thinking | timeout |", "|---|---|---|---|---|---:|"])
    for name, profile in sorted((payload.get("profiles") or {}).items()):
        bot_name = str((profile or {}).get("bot") or "")
        bot = (payload.get("bots") or {}).get(bot_name) or {}
        provider = (payload.get("providers") or {}).get((profile or {}).get("provider") or bot.get("provider") or defaults.get("provider") or "") or default_provider
        merged = {**provider, **defaults, **bot, **(profile or {})}
        lines.append(
            "| "
            + " | ".join(
                [
                    str(name),
                    str(merged.get("provider") or ""),
                    bot_name,
                    str(merged.get("model") or ""),
                    str(merged.get("thinking") or ""),
                    str(merged.get("timeout") or ""),
                ]
            )
            + " |"
        )
    lines.extend(["", "## Providers", "", "| provider | model | base_url | api_type | timeout | api_key |", "|---|---|---|---|---:|---|"])
    for name, provider in sorted((payload.get("providers") or {}).items()):
        api_key = str((provider or {}).get("api_key") or "")
        lines.append(
            "| "
            + " | ".join(
                [
                    str(name),
                    str((provider or {}).get("model") or ""),
                    str((provider or {}).get("base_url") or ""),
                    str((provider or {}).get("api_type") or ""),
                    str((provider or {}).get("timeout") or ""),
                    "已配置" if api_key else "未配置",
                ]
            )
            + " |"
        )
    cleaner = payload.get("content_cleaner") or {}
    lines.extend(
        [
            "",
            "## Content Cleaner",
            "",
            f"- provider: `{cleaner.get('provider') or ''}`",
            f"- enabled: `{cleaner.get('enabled')}`",
            f"- max_chars: `{cleaner.get('max_chars')}`",
            f"- max_tokens: `{cleaner.get('max_tokens')}`",
        ]
    )
    lines.extend(
        [
            "",
            "## Sync",
            "",
            "```bash",
            "python3 /home/ubuntu/selfmedia-tools/tools/sync_openclaw_bot_config.py",
            "python3 /home/ubuntu/selfmedia-tools/tools/sync_openclaw_bot_config.py --direction obsidian-to-repo",
            "python3 /home/ubuntu/selfmedia-tools/tools/sync_openclaw_bot_config.py --direction repo-to-obsidian",
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def write_state(repo_hash: str, obsidian_hash: str, direction: str, *, dry_run: bool) -> None:
    if dry_run:
        return
    state = {
        "last_synced_at": datetime.now().isoformat(timespec="seconds"),
        "repo_config": str(REPO_CONFIG),
        "obsidian_config": str(OBSIDIAN_CONFIG),
        "mac_obsidian_dir": MAC_OBSIDIAN_DIR,
        "repo_hash": repo_hash,
        "obsidian_hash": obsidian_hash,
        "direction": direction,
    }
    atomic_write(SYNC_STATE, json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def choose_direction(requested: str, repo_hash: str, obsidian_hash: str) -> str:
    if requested != "auto":
        return requested
    if not OBSIDIAN_CONFIG.exists():
        return "repo-to-obsidian"
    if repo_hash == obsidian_hash:
        return "none"
    state = load_state()
    repo_changed = bool(state.get("repo_hash")) and state.get("repo_hash") != repo_hash
    obsidian_changed = bool(state.get("obsidian_hash")) and state.get("obsidian_hash") != obsidian_hash
    if repo_changed and not obsidian_changed:
        return "repo-to-obsidian"
    if obsidian_changed and not repo_changed:
        return "obsidian-to-repo"
    repo_mtime = REPO_CONFIG.stat().st_mtime
    obsidian_mtime = OBSIDIAN_CONFIG.stat().st_mtime
    return "repo-to-obsidian" if repo_mtime >= obsidian_mtime else "obsidian-to-repo"


def main() -> None:
    parser = argparse.ArgumentParser(description="Bidirectionally sync OpenClaw Bot LLM config with Obsidian.")
    parser.add_argument(
        "--direction",
        choices=("auto", "repo-to-obsidian", "obsidian-to-repo"),
        default="auto",
        help="Sync direction. auto chooses the changed/newer side.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Show the action without writing files.")
    parser.add_argument("--restart-services", action="store_true", help="Restart runtime services when config changed.")
    args = parser.parse_args()

    repo_payload = canonical_payload(REPO_CONFIG)
    repo_hash = canonical_hash(repo_payload)
    obsidian_hash = file_hash(OBSIDIAN_CONFIG)
    direction = choose_direction(args.direction, repo_hash, obsidian_hash)

    if direction == "repo-to-obsidian":
        payload = repo_payload
        write_json_config(OBSIDIAN_CONFIG, payload, dry_run=args.dry_run)
        obsidian_hash = canonical_hash(payload)
        action = f"repo -> obsidian: {OBSIDIAN_CONFIG}"
    elif direction == "obsidian-to-repo":
        payload = canonical_payload(OBSIDIAN_CONFIG)
        write_json_config(REPO_CONFIG, payload, dry_run=args.dry_run)
        repo_hash = canonical_hash(payload)
        obsidian_hash = canonical_hash(payload)
        action = f"obsidian -> repo: {REPO_CONFIG}"
    else:
        payload = repo_payload
        obsidian_hash = repo_hash
        action = "already in sync"

    note = render_note(payload, repo_hash, obsidian_hash)
    if not args.dry_run:
        atomic_write(OBSIDIAN_NOTE, note)
    write_state(repo_hash, obsidian_hash, direction, dry_run=args.dry_run)
    if args.restart_services and direction != "none" and not args.dry_run:
        subprocess.run(
            ["systemctl", "--user", "restart", "content-flow.service", "openclaw-feishu-gateway.service"],
            check=True,
        )

    print(json.dumps({"ok": True, "action": action, "direction": direction, "obsidian_config": str(OBSIDIAN_CONFIG)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
