#!/usr/bin/env python3
from __future__ import annotations

import argparse
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
sys.path.insert(0, str(PLUGIN_ROOT.parent))
sys.path.insert(0, str(PLUGIN_ROOT))

from openclaw_app.router.system_routes import SystemRoutesMixin  # noqa: E402
from openclaw_app.router.tag_capabilities import MEDIA_GROWTH_LABEL_CAPABILITIES, MEDIA_GROWTH_MAIN_LABELS, TAG_CAPABILITIES  # noqa: E402


MEDIA_GROWTH_DOC_LABELS = set(MEDIA_GROWTH_LABEL_CAPABILITIES) | set(MEDIA_GROWTH_MAIN_LABELS)
RESEARCH_LABELS = {"调研"}


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
    "deepmath": {
        "title": "OpenClaw DeepMath bot 能力说明",
        "bot_label": "DeepMath bot",
        "mode": "bot",
        "filename": "OpenClaw DeepMath bot 能力说明.md",
        "credential_profile": "deepmath",
        "env_file": "/home/ubuntu/.openclaw-deepmath/openclaw.env",
        "app_id_env": "OPENCLAW_DEEPMATH_APP_ID",
        "app_secret_env": "OPENCLAW_DEEPMATH_APP_SECRET",
        "api_base_env": "OPENCLAW_DEEPMATH_FEISHU_API_BASE_URL",
        "tenant_host_env": "OPENCLAW_DEEPMATH_TENANT_HOST",
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
    for field_name in ("credential_profile", "env_file", "app_id_env", "app_secret_env", "api_base_env", "tenant_host_env"):
        if spec.get(field_name) and not config.get(field_name):
            config[field_name] = spec[field_name]
    if key != "deepmath" and not config.get("wiki_parent_node_token") and main_config.get("wiki_parent_node_token"):
        config["wiki_parent_node_token"] = main_config["wiki_parent_node_token"]
    write_json(config_path, config)
    return config


def capabilities_for_spec(harness: CapabilityDocHarness, spec: dict[str, str]) -> list[Any]:
    if spec.get("mode") == "total":
        return list(TAG_CAPABILITIES)
    return harness._bot_capabilities(spec["bot_label"])


def implementation_status_text(capability: Any) -> str:
    status = str(capability.implementation_status or "").strip()
    if status == "implemented":
        if capability.label == "思考":
            return "当前已实现收件、恰好一次 LLM 分析、不可变版本提案、私聊审批卡、唯一审批人校验和原子 claim；字段完整的任务创建在批准后写入唯一 Tasks 清单并精确读回，Calendar 与通知执行器尚未接入。"
        return "可用：本地 runner 或复核入口已接入；新 artifact 默认 pending_review，需复核后进入 dashboard 可见集合。"
    if status == "external":
        return "既有链路：由现有 Media/Knowledge handler 执行，不是 Media Growth 本地 runner。"
    if status == "not_implemented":
        return "规划中：只接收输入并返回待人工处理，不生成完整产物，不伪造 Feishu 写入。"
    return f"状态未定义：{status or 'unknown'}。"


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
    if capability.label in MEDIA_GROWTH_DOC_LABELS or bot_label == "DeepMath bot":
        status_text = implementation_status_text(capability)
        if capability.label in RESEARCH_LABELS and capability.implementation_status == "implemented":
            status_text = "可用（证据登记级）：本地 runner 已接入；无外部取证证据时返回 pending_manual。"
        lines.append(f"- 实装状态：{status_text}")
    details = harness._bot_capability_details(bot_label, capability.label)
    for detail in details:
        cleaned = str(detail or "").strip()
        if cleaned.startswith("- "):
            lines.append(cleaned)
        elif cleaned:
            lines.append(f"- {cleaned}")
    lines.append("")
    return lines


def render_deepmath_policy_section(capabilities: list[Any]) -> list[str]:
    thinking = next((item for item in capabilities if item.label == "思考"), None)
    if thinking is None:
        return []
    status = str(thinking.implementation_status or "").strip()
    if status == "implemented":
        current_lines = [
            "- 当前已实现收件、恰好一次 LLM 分析、不可变版本提案与私聊审批卡。",
            "- 批准表示对当前提案版本的执行授权；唯一审批人、签名、版本、参数指纹和原子 claim 均已实现。",
            "- 修改、拒绝、仅保存、取消、过期、陈旧授权或非审批人操作均零执行。",
        ]
    elif status == "external":
        current_lines = ["- 当前由既有外部链路承接，不把外部链路误报为 DeepMath U4 本地实现。"]
    elif status == "not_implemented":
        current_lines = ["- 当前尚未实现，只接收输入并返回待人工处理，不生成完整产物。"]
    else:
        current_lines = [f"- 当前状态未定义（{status or 'unknown'}），不得据此声称已执行。"]
    return [
        "## DeepMath U5 运行边界",
        "",
        *current_lines,
        "- 已实现不可变版本提案、私聊审批卡、唯一审批人校验和原子 claim；批准表示对当前版本的执行授权。",
        "- 已批准且字段完整的任务创建会写入唯一 DeepMath Tasks 清单并设置一个任务提醒；只有精确读回后才可称为成功。",
        "- Calendar 与通知执行器尚未接入；结果未知时禁止盲重试，也不得把原子 claim 本身说成外部动作已执行。",
        "",
    ]


def render_media_growth_status_section(capabilities: list[Any]) -> list[str]:
    growth_capabilities = [capability for capability in capabilities if capability.label in MEDIA_GROWTH_DOC_LABELS]
    if not growth_capabilities:
        return []
    grouped: dict[str, list[str]] = {"implemented": [], "external": [], "not_implemented": []}
    for capability in growth_capabilities:
        status = str(capability.implementation_status or "external")
        label_text = f"`【{capability.label}】`"
        if capability.label in RESEARCH_LABELS and status == "implemented":
            label_text = f"{label_text}（证据登记级，深度取证待接入）"
        grouped.setdefault(status, []).append(label_text)
    lines = [
        "## Media Growth v2 状态与复核规则",
        "",
        "- 状态口径：可用=本地 runner/复核入口已接；既有链路=由老 handler 执行；规划中=只返回待人工处理，不伪造产物。",
    ]
    for status, label in (("implemented", "可用"), ("external", "既有链路"), ("not_implemented", "规划中")):
        if grouped.get(status):
            lines.append(f"- {label}：{'、'.join(grouped[status])}")
    lines.extend(
        [
            "- 新生成 artifact 默认 `quality_status=pending_review`，dashboard 不展示；用 `【复核】artifact_id=<id> 动作=通过/废弃` 或飞书卡片按钮晋升。",
            "- `来源=`、`source=`、`artifact_id=`、`artifact_ref=` 均可引用 Growth artifact；引用失败会报错，不静默降级。",
            "- `【调研】` 在 Media 语境没有外部取证证据时返回 `pending_manual`，不会把空壳 brief 当成真实调研结论。",
            "",
        ]
    )
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
        "## 当前范围",
        "",
        f"- 当前文档：{spec['title']}",
        f"- 当前 Bot：{bot_label}",
        f"- 覆盖能力数：{len(capabilities)}",
        "",
    ]
    if bot_label == "DeepMath bot":
        lines[6:6] = [
            "## DeepMath 入口事实",
            "",
            "- `【说明】` 只返回 DeepMath 专属能力说明和文档链接。",
            "- 空 `【说明】` 不调用 matcher；非空 `【说明】问题` 只在 DeepMath 能力目录内做一次 LLM 匹配。",
            "- 说明路径全程只读，不写 Base，不创建 Tasks/Calendar，不发送通知。",
            "- DeepMath 只放行 `【思考】` 和 `【说明】`；其他全角标签在入口拒绝。",
            "",
        ]
    else:
        lines[6:6] = [
            "## 入口事实",
            "",
            "- `【说明】` 是所有 Bot 的唯一能力说明入口。",
            "- `【说明】` 只返回能力说明和文档链接，不执行归档、创作、入库或同步。",
            "- 聊天回复只保留短入口；完整能力详情以本文档为准。",
            "- 标签格式固定为：`【标签】正文内容`。",
            "",
            "## Codex 后台维护任务",
            "",
            "- 消息中包含 `【codex】` 时，任务会写入唯一 v2 队列，由独立 worker 使用 Codex CLI full access、`gpt-5.6-sol` 和 `high` 执行，并快速返回 `task_id`。DeepMath 账号会冻结 `tenantProfile=deepmath`；修改飞书 Wiki/Docx 必须包含本轮显式 URL，只使用 DeepMath 专用应用身份进行同文档结构化修改与写后回读。",
            "- 入队回执作为第 0 次状态；运行满 120 秒后每 120 秒主动私信发起人最新进度，完成或失败时立即主动通知。",
            "- 使用 `【codex】状态 task_id` 可随时查询同一 v2 状态和最终文本；Gateway 重启不会中断或恢复该任务。",
            "- 状态回复不公开请求正文、完整执行命令、本机路径或受控日志；具体维护动作仍以用户原始授权范围为边界。",
            "",
        ]
    if bot_label == "DeepMath bot":
        lines.extend(render_deepmath_policy_section(capabilities))
    lines.extend(render_media_growth_status_section(capabilities))
    lines.extend(["## 标签索引", ""])
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
        local_path = str(DOC_DIR / spec["filename"])
        url = doc_url_from_config(config)
        if key == "deepmath" and not url:
            url = local_path
        entry = {
            "key": key,
            "title": spec["title"],
            "url": url,
            "local_path": local_path,
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
    parser = argparse.ArgumentParser(description="Generate local tag-router capability documents and runtime links.")
    parser.add_argument(
        "--only",
        choices=tuple(DOC_SPECS),
        action="append",
        default=None,
        help="generate only the selected document(s); runtime link config is always refreshed",
    )
    args = parser.parse_args()
    DOC_DIR.mkdir(parents=True, exist_ok=True)
    selected = set(args.only or DOC_SPECS)
    for key, spec in DOC_SPECS.items():
        if key not in selected:
            continue
        sync_config = ensure_sync_config(key, spec)
        path = DOC_DIR / spec["filename"]
        path.write_text(render_doc(key, spec, sync_config), encoding="utf-8")
        print(path)
    write_runtime_link_config()
    print(RUNTIME_LINK_CONFIG)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
