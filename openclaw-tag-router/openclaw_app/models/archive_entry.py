from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ArchiveEntry:
    frontmatter: dict[str, Any]
    title: str
    sections: list[tuple[str, str]]
    local_path: str = ""
    extra: dict[str, Any] = field(default_factory=dict)
