from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path

from ..services.utils import ensure_dir


@dataclass
class SchedulePayload:
    title: str
    due_at: datetime
    note_path: str
    reminder_text: str


class MacAgentClient:
    def __init__(self, mode: str, queue_dir: str, obsidian_root: str, local_obsidian_root: str):
        self.mode = mode
        self.queue_dir = Path(queue_dir)
        self.obsidian_root = Path(obsidian_root)
        self.local_obsidian_root = Path(local_obsidian_root)
        ensure_dir(self.queue_dir)
        ensure_dir(self.local_obsidian_root)

    def create_schedule(self, payload: SchedulePayload) -> dict[str, str]:
        if self.mode == "local":
            note_path = self.local_obsidian_root / f"{payload.due_at.strftime('%Y%m%d')}.md"
            self._append_obsidian_todo(note_path, payload.due_at, payload.title)
            calendar_path = self.local_obsidian_root / f"calendar-{payload.due_at.strftime('%Y%m%d')}.json"
            events = []
            if calendar_path.exists():
                events = json.loads(calendar_path.read_text(encoding="utf-8"))
            events.append(
                {
                    "title": payload.title,
                    "start": payload.due_at.isoformat(),
                    "end": (payload.due_at + timedelta(minutes=30)).isoformat(),
                    "reminder": "at_time",
                }
            )
            calendar_path.write_text(json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8")
            self._trigger_syncthing_scan(self.local_obsidian_root)
            return {"status": "synced", "note_path": str(note_path), "calendar": "已创建提醒"}

        task_path = self.queue_dir / f"{payload.due_at.strftime('%Y%m%d-%H%M%S')}-{payload.title[:12]}.json"
        task_path.write_text(json.dumps(asdict(payload), ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        return {"status": "pending_manual", "note_path": payload.note_path, "calendar": "待 Mac 执行代理处理", "task_path": str(task_path)}

    @staticmethod
    def _append_obsidian_todo(path: Path, due_at: datetime, title: str) -> None:
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        todo_line = f"- [ ] {due_at.strftime('%y%m%d %H:%M')} {title}"
        if "# 待办" not in existing:
            existing = (existing.rstrip() + "\n\n# 待办\n").lstrip("\n")
        lines = existing.splitlines()
        output: list[str] = []
        inserted = False
        for idx, line in enumerate(lines):
            output.append(line)
            if line.strip() == "# 待办" and not inserted:
                next_line = lines[idx + 1] if idx + 1 < len(lines) else ""
                if next_line.strip() != todo_line:
                    output.append(todo_line)
                inserted = True
        if not inserted:
            output.extend(["# 待办", todo_line])
        path.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")

    @staticmethod
    def _trigger_syncthing_scan(path: Path) -> None:
        config_path = Path(os.environ.get("OPENCLAW_SYNCTHING_CONFIG", "/home/ubuntu/.local/state/syncthing/config.xml"))
        vault_root = Path(os.environ.get("OPENCLAW_OBSIDIAN_VAULT_ROOT", "/home/ubuntu/obsidian-diary")).resolve()
        folder_id = os.environ.get("OPENCLAW_SYNCTHING_FOLDER_ID", "obsidian-diary")
        api_url = os.environ.get("OPENCLAW_SYNCTHING_API_URL", "http://127.0.0.1:8384").rstrip("/")
        try:
            api_key = ET.parse(config_path).getroot().findtext("./gui/apikey")
            if not api_key:
                return
            sub_path = path.resolve().relative_to(vault_root).as_posix()
            query = urllib.parse.urlencode({"folder": folder_id, "sub": sub_path})
            request = urllib.request.Request(
                f"{api_url}/rest/db/scan?{query}",
                headers={"X-API-Key": api_key},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=5) as response:
                response.read()
        except Exception:
            return
