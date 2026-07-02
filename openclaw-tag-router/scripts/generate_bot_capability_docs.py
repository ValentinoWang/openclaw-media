#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
ROOT = Path("/home/ubuntu")
DOC_DIR = ROOT / "docs/说明书"
MAIN_SYNC_CONFIG = PLUGIN_ROOT / "config/docs_sync.json"
DOC_SYNC_CONFIG_DIR = PLUGIN_ROOT / "config/capability_docs_sync"
RUNTIME_LINK_CONFIG = PLUGIN_ROOT / "config/capability_docs.json"
sys.path.insert(0, str(PLUGIN_ROOT))

from openclaw_app.router.system_routes import SystemRoutesMixin  # noqa: E402
from openclaw_app.router.tag_capabilities import TAG_CAPABILITIES  # noqa: E402


class CapabilityDocHarness(SystemRoutesMixin):
    pass


DOC_SPECS = {
    "total": {
        "title": "OpenClaw 全部 Bot 能力说明",
        "bot_label": "OpenClaw bot",
        "mode": "total",
        "filename": "OpenClaw 全部 Bot 能力说明.md",
    },
    "main": {
        "title": "OpenClaw Main bot 能力说明",
        "bot_label": "OpenClaw bot",
        "mode": "bot",
        "filename": "OpenClaw Main bot 能力说明.md",
    },
    "daily": {
        "title": "OpenClaw Daily bot 能力说明",
        "bot_label": "Daily bot",
        "mode": "bot",
        "filename": "OpenClaw Daily bot 能力说明.md",
    },
    "media": {
        "title": "OpenClaw Media bot 能力说明",
        "bot_label": "Media bot",
        "mode": "bot",
        "filename": "OpenClaw Media bot 能力说明.md",
    },
    "knowledge": {
        "title": "OpenClaw Knowledge bot 能力说明",
        "bot_label": "Knowledge bot",
        "mode": "bot",
        "filename": "OpenClaw Knowledge bot 能力说明.md",
    },
    "social": {
        "title": "OpenClaw Social bot 能力说明",
        "bot_label": "Social bot",
        "mode": "bot",
        "filename": "OpenClaw Social bot 能力说明.md",
    },
}


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def doc_url_from_config(config: dict[str, Any]) -> str:
    return str(config.get("wiki_url") or config.get("doc_url") or "").strip()


def sync_config_path(key: str) -> Path:
    return DOC_SYNC_CONFIG_DIR / f"{key}.json"


def ensure_sync_config(key: str, spec: dict[str, str]) -> dict[str, Any]:
    config_path = sync_config_path(key)
    existing = load_json(config_path)
    main_config = load_json(MAIN_SYNC_CONFIG)
    config = dict(existing)
    config["doc_title"] = spec["title"]
    if not config.get("wiki_parent_node_token") and main_config.get("wiki_parent_node_token"):
        config["wiki_parent_node_token"] = main_config["wiki_parent_node_token"]
    write_json(config_path, config)
    return config


def capabilities_for_spec(harness: CapabilityDocHarness, spec: dict[str, str]) -> list[Any]:
    if spec.get("mode") == "total":
        return list(TAG_CAPABILITIES)
    return harness._bot_capabilities(spec["bot_label"])


def capability_heading(group: list[Any]) -> str:
    return " / ".join(f"【{capability.label}】" for capability in group)


def render_capability_detail(harness: CapabilityDocHarness, bot_label: str, capability: Any) -> list[str]:
    lines = [
        f"### 【{capability.label}】",
        "",
        f"- 归属：{capability.bot}",
        f"- 用途：{capability.purpose}",
        f"- 产出：{capability.result}",
        f"- 输入格式：{harness._format_capability_usage(capability.label)}",
    ]
    details = harness._bot_capability_details(bot_label, capability.label)
    for detail in details:
        cleaned = str(detail or "").strip()
        if cleaned.startswith("- "):
            lines.append(cleaned)
        elif cleaned:
            lines.append(f"- {cleaned}")
    lines.append("")
    return lines


def render_doc(key: str, spec: dict[str, str], sync_config: dict[str, Any]) -> str:
    harness = CapabilityDocHarness()
    bot_label = spec["bot_label"]
    capabilities = capabilities_for_spec(harness, spec)
    groups = harness._group_capabilities(capabilities)
    now = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S %z")
    doc_url = doc_url_from_config(sync_config)
    lines = [
        f"# {spec['title']}",
        "",
        f"更新时间：{now}",
        "",
        f"飞书云文档：{doc_url or '首次同步后自动写入'}",
        "",
        "## 入口事实",
        "",
        "- `【说明】` 是所有 Bot 的唯一能力说明入口。",
        "- `【说明】` 只返回能力说明和文档链接，不执行归档、创作、入库或同步。",
        "- 聊天回复只保留短入口；完整能力详情以本文档为准。",
        "- 标签格式固定为：`【标签】正文内容`。",
        "",
        "## 当前范围",
        "",
        f"- 当前文档：{spec['title']}",
        f"- 当前 Bot：{bot_label}",
        f"- 覆盖能力数：{len(capabilities)}",
        "",
        "## 标签索引",
        "",
    ]
    lines.extend(harness._format_capability_label_list(capabilities))
    lines.extend(["", "## 能力详情", ""])
    for _, group in groups:
        lines.append(f"## {capability_heading(group)}")
        lines.append("")
        for capability in group:
            lines.extend(render_capability_detail(harness, bot_label, capability))
    lines.extend(
        [
            "<!-- CAPABILITY_DOC_SYNC_START",
            *[capability.label for capability in capabilities],
            "CAPABILITY_DOC_SYNC_END -->",
            "",
        ]
    )
    return "\n".join(lines)


def write_runtime_link_config() -> None:
    total_config = load_json(sync_config_path("total"))
    bots: dict[str, dict[str, str]] = {}
    for key, spec in DOC_SPECS.items():
        config = load_json(sync_config_path(key))
        entry = {
            "key": key,
            "title": spec["title"],
            "url": doc_url_from_config(config),
            "local_path": str(DOC_DIR / spec["filename"]),
        }
        if key == "total":
            continue
        bots[spec["bot_label"]] = entry
    payload = {
        "updated_at": datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds"),
        "total": {
            "key": "total",
            "title": DOC_SPECS["total"]["title"],
            "url": doc_url_from_config(total_config),
            "local_path": str(DOC_DIR / DOC_SPECS["total"]["filename"]),
        },
        "bots": bots,
    }
    write_json(RUNTIME_LINK_CONFIG, payload)


def main() -> int:
    DOC_DIR.mkdir(parents=True, exist_ok=True)
    for key, spec in DOC_SPECS.items():
        sync_config = ensure_sync_config(key, spec)
        path = DOC_DIR / spec["filename"]
        path.write_text(render_doc(key, spec, sync_config), encoding="utf-8")
        print(path)
    write_runtime_link_config()
    print(RUNTIME_LINK_CONFIG)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
