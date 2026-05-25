from __future__ import annotations

from pathlib import Path
from typing import Any

from .utils import dump_yaml, load_yaml


class RuleService:
    def __init__(self, rules_path: str | Path):
        self.rules_path = Path(rules_path)
        self.data = load_yaml(self.rules_path)
        self.data.setdefault("entry_tag_rules", {})
        self.data.setdefault("display_time_format", "yymmdd hh:mm")

    def get_tag_rule(self, tag: str) -> dict[str, Any]:
        return self.data.get("entry_tag_rules", {}).get(tag, {})

    def update_rule_from_text(self, text: str) -> dict[str, Any]:
        rule = {"raw": text}
        entry_rules = self.data.setdefault("entry_tag_rules", {})
        if "链接" in text and "内容素材" in text:
            target = entry_rules.setdefault("内容素材", {})
            target["detect_links"] = True
            rule["applied"] = "内容素材.detect_links=true"
        elif "灵感" in text and "标签" in text:
            target = entry_rules.setdefault("灵感", {})
            target.setdefault("default_tags", [])
            after = text.split("标签", 1)[-1].replace("：", "").replace(":", "").strip()
            if after:
                normalized = after.replace("，", ",").replace("、", ",")
                target["default_tags"] = [part.strip() for part in normalized.split(",") if part.strip()]
                rule["applied"] = f"灵感.default_tags={target['default_tags']}"
        else:
            target = self.data.setdefault("custom_rules", [])
            target.append(text)
            rule["applied"] = "custom_rules.append"
        dump_yaml(self.rules_path, self.data)
        return rule
