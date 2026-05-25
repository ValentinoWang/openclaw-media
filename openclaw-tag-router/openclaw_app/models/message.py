from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class Message:
    entry_tag: str
    raw_text: str
    body: str
    source: str = "qq"
    chat_type: str = "private"
    created_at: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_tag": self.entry_tag,
            "raw_text": self.raw_text,
            "body": self.body,
            "source": self.source,
            "chat_type": self.chat_type,
            "created_at": self.created_at.isoformat(timespec="seconds"),
            "metadata": self.metadata,
        }
