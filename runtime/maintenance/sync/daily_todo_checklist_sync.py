#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from common.env import feishu_reminder_root  # noqa: E402
from runtime.maintenance.reminder_runtime import reminder_script_path  # noqa: E402

OPENCLAW_RUNTIME_HOME = Path(os.getenv("OPENCLAW_RUNTIME_HOME") or Path.home() / ".openclaw")
DEFAULT_ARCHIVE_ROOT = Path(os.getenv("OPENCLAW_DAILY_TODO_ARCHIVE_ROOT") or Path.home() / "obsidian-日记/Archieve")
DEFAULT_DEVELOPMENT_ARCHIVE_ROOT = Path(
    os.getenv("OPENCLAW_DEVELOPMENT_WEEKLY_ROOT") or DEFAULT_ARCHIVE_ROOT
)
DEFAULT_STATE_PATH = Path(
    os.getenv("OPENCLAW_DAILY_TODO_SYNC_STATE") or REPO_ROOT / "data/daily_todo_sync_state.json"
)
DEFAULT_REMINDER_ROOT = feishu_reminder_root()
DEFAULT_REMINDER_SCRIPT = reminder_script_path()
DEFAULT_ENV_FILES = [
    str(OPENCLAW_RUNTIME_HOME / "openclaw-feishu-env.conf"),
    str(DEFAULT_REMINDER_ROOT / "reminder.env"),
]


CHECKED_FEISHU_RE = re.compile(
    r"^\s*-\s*\[[xX]\]\s*(?P<title>.*?)\s*<!--\s*openclaw:feishu_record=(?P<record>rec[A-Za-z0-9_-]+);sync=todo_complete_v1\s*-->\s*$"
)


def default_command() -> str:
    return sys.executable


@dataclass(frozen=True)
class SyncCandidate:
    record_id: str
    title: str
    source_file: str
    line_hash: str


def weekly_archive_path(root: Path, target: date) -> Path:
    start = target - timedelta(days=target.weekday())
    end = start + timedelta(days=6)
    return root / f"{start:%Y%m%d}-{end:%Y%m%d}.md"


def recent_weekly_files(root: Path, today: date, days: int) -> list[Path]:
    files: dict[Path, None] = {}
    for offset in range(max(1, days)):
        target = today - timedelta(days=offset)
        files[weekly_archive_path(root, target)] = None
    return [path for path in files if path.exists()]


def recent_weekly_files_for_roots(roots: list[Path], today: date, days: int) -> list[Path]:
    files: dict[Path, None] = {}
    for root in roots:
        for path in recent_weekly_files(root, today, days):
            files[path] = None
    return list(files)


def find_checked_feishu_items(paths: list[Path]) -> list[SyncCandidate]:
    candidates: list[SyncCandidate] = []
    for path in paths:
        for line in path.read_text(encoding="utf-8").splitlines():
            match = CHECKED_FEISHU_RE.match(line)
            if not match:
                continue
            line_hash = hashlib.sha256(line.strip().encode("utf-8")).hexdigest()
            candidates.append(
                SyncCandidate(
                    record_id=match.group("record"),
                    title=match.group("title").strip(),
                    source_file=str(path),
                    line_hash=line_hash,
                )
            )
    return candidates


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def sync_candidates(
    candidates: list[SyncCandidate],
    state: dict[str, Any],
    complete_record: Callable[[str], None],
) -> list[dict[str, str]]:
    synced: list[dict[str, str]] = []
    for candidate in candidates:
        current = state.get(candidate.record_id) or {}
        if current.get("synced_completed") and current.get("line_hash") == candidate.line_hash:
            continue
        complete_record(candidate.record_id)
        state[candidate.record_id] = {
            "synced_completed": True,
            "line_hash": candidate.line_hash,
            "source_file": candidate.source_file,
            "title": candidate.title,
        }
        synced.append({"record_id": candidate.record_id, "source_file": candidate.source_file, "title": candidate.title})
    return synced


def load_env_files(paths: list[str]) -> dict[str, str]:
    env = os.environ.copy()
    for raw_path in paths:
        path = Path(str(raw_path or "").strip()).expanduser()
        if not path.exists() or not path.is_file():
            continue
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def reminder_complete_runner(command: str, script: str, env: dict[str, str]) -> Callable[[str], None]:
    def _run(record_id: str) -> None:
        subprocess.run(
            [command, script, "complete-record", "--record-id", record_id],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
            timeout=int(os.getenv("DAILY_TODO_COMPLETE_RECORD_TIMEOUT_SECONDS", "120")),
        )

    return _run


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync checked Obsidian weekly todo checkboxes to Feishu completion status.")
    parser.add_argument("--weekly-root", default=str(DEFAULT_ARCHIVE_ROOT))
    parser.add_argument("--development-weekly-root", default=str(DEFAULT_DEVELOPMENT_ARCHIVE_ROOT))
    parser.add_argument("--state", default=str(DEFAULT_STATE_PATH))
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--today", default="")
    # Use the interpreter running this entrypoint so virtualenvs and relocated hosts work.
    parser.add_argument("--command", default=default_command())
    parser.add_argument("--reminder-script", default=str(DEFAULT_REMINDER_SCRIPT))
    parser.add_argument(
        "--env-file",
        action="append",
        default=DEFAULT_ENV_FILES,
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.dry_run and not Path(args.reminder_script).is_file():
        parser.error("--reminder-script must name an existing reminder.py; set OPENCLAW_FEISHU_REMINDER_SCRIPT or pass the flag")

    today = date.fromisoformat(args.today) if args.today else date.today()
    files = recent_weekly_files_for_roots([Path(args.weekly_root), Path(args.development_weekly_root)], today, args.days)
    candidates = find_checked_feishu_items(files)
    state_path = Path(args.state)
    state = load_state(state_path)
    env = load_env_files(args.env_file)
    runner = (lambda _record_id: None) if args.dry_run else reminder_complete_runner(args.command, args.reminder_script, env)
    synced = sync_candidates(candidates, state, runner)
    if not args.dry_run:
        save_state(state_path, state)
    print(json.dumps({"ok": True, "scanned_files": len(files), "candidates": len(candidates), "synced": synced}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
