from __future__ import annotations

from pathlib import Path
from typing import Any

from .utils import load_yaml


class RuleService:
    def __init__(self, rules_path: str | Path):
        self.rules_path = Path(rules_path)
        self.data = load_yaml(self.rules_path)
        self.data.setdefault("entry_tag_rules", {})
        self.data.setdefault("display_time_format", "yymmdd hh:mm")

    def get_tag_rule(self, tag: str) -> dict[str, Any]:
        return self.data.get("entry_tag_rules", {}).get(tag, {})
