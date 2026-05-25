from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TaskResult:
    ok: bool
    status: str
    reply: str
    task_id: str
    local_path: str = ""
    feishu_doc: str = ""
    extra: dict[str, Any] = field(default_factory=dict)
