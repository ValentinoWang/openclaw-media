from __future__ import annotations

import json
from pathlib import Path

from ..adapters.mac_agent_client import MacAgentClient, SchedulePayload


class MacQueueWorker:
    def __init__(self, queue_dir: str, local_obsidian_root: str):
        self.queue_dir = Path(queue_dir)
        self.client = MacAgentClient("local", queue_dir, local_obsidian_root, local_obsidian_root)

    def process_once(self) -> list[str]:
        processed: list[str] = []
        for file in sorted(self.queue_dir.glob("*.json")):
            data = json.loads(file.read_text(encoding="utf-8"))
            payload = SchedulePayload(
                title=data["title"],
                due_at=self._parse_dt(data["due_at"]),
                note_path=data.get("note_path", ""),
                reminder_text=data.get("reminder_text", ""),
            )
            self.client.create_schedule(payload)
            done = file.with_suffix(".done.json")
            file.rename(done)
            processed.append(str(done))
        return processed

    @staticmethod
    def _parse_dt(value: str):
        from datetime import datetime
        return datetime.fromisoformat(value)
