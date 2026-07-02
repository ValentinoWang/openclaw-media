#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any


REPO_CONFIG = Path("/home/ubuntu/selfmedia-tools/config/openclaw_bots.json")
OBSIDIAN_DIR = Path("/home/ubuntu/obsidian-日记/openclaw配置")
OBSIDIAN_CONFIG = OBSIDIAN_DIR / "openclaw_bots.json"
OBSIDIAN_NOTE = OBSIDIAN_DIR / "OpenClaw Bot LLM 配置.md"
PUBLIC_KNOWLEDGE_DIR = Path("/home/ubuntu/obsidian-日记/公共知识库")
LLM_USAGE_SSOT_NOTE = PUBLIC_KNOWLEDGE_DIR / "OpenClaw Bot LLM 使用矩阵 SSOT.md"
SYNC_STATE = OBSIDIAN_DIR / ".openclaw_bots_sync_state.json"
MAC_OBSIDIAN_DIR = "/Users/vsiyo/Library/Mobile Documents/iCloud~md~obsidian/Documents/日记/openclaw配置"
MAC_PUBLIC_KNOWLEDGE_DIR = "/Users/vsiyo/Library/Mobile Documents/iCloud~md~obsidian/Documents/日记/公共知识库"
SYNC_AGENT_MODELS = Path("/home/ubuntu/selfmedia-tools/runtime/maintenance/deploy/sync_openclaw_agent_models.py")
DUPLICATE_NOTE_PATTERNS = (
    "OpenClaw Bot LLM 配置 [0-9]*.md",
    "OpenClaw Bot LLM 配置.sync-conflict-*.md",
)

PROFILE_USAGE_ROWS = (
    {
        "profile": "system_guide",
        "usage": "OpenClaw 能力说明、空业务标签填写模板",
        "callers": "openclaw-tag-router/openclaw_app/router/media_intake_guides.py; openclaw-agents/media/AGENTS.md; openclaw-agents/media/TOOLS.md",
        "surface": "profile_runtime('system_guide') -> openclaw agent",
        "state": "当前只用于说明/模板，不执行归档、创作、入库或同步。",
    },
    {
        "profile": "knowledge_delegate",
        "usage": "【归档】【补全】【认知】【学习】【学习-整理】普通知识委托",
        "callers": "openclaw-tag-router/openclaw_app/router/knowledge_delegate.py",
        "surface": "profile_config/profile_runtime('knowledge_delegate') -> openclaw agent",
        "state": "provider 为 openclaw_codex 时转交 feishu-knowledge；非 openclaw_codex 时有 chat-completions 直连分支。",
    },
    {
        "profile": "knowledge_research",
        "usage": "Knowledge 深度研究/高思考委托",
        "callers": "openclaw-tag-router/openclaw_app/router/knowledge_delegate.py; tag_router_common.py",
        "surface": "profile_runtime('knowledge_research') -> openclaw agent",
        "state": "thinking_level 为 research 时使用。",
    },
    {
        "profile": "transcription_postprocess",
        "usage": "录音/访谈逐字稿整理、分块摘要、附件合并、全局纪要、一致性检查和修订",
        "callers": "openclaw-tag-router/openclaw_app/services/content_flow_client.py; router/transcription.py",
        "surface": "_call_profile_provider_json('transcription_postprocess') -> common.generate_json_from_parts",
        "state": "统一走 direct Codex Responses；不再调用 OpenClaw agent 后处理。",
    },
    {
        "profile": "media_analysis",
        "usage": "内容采集结构化分析、数据截图复盘、Media 数据审计",
        "callers": "selfmedia/ingest/content_flow/src/config.py; selfmedia/ingest/content_flow/src/analyzer.py; selfmedia/review/data_review.py",
        "surface": "load_profile_llm_settings('media_analysis') -> common.generate_json_from_parts",
        "state": "01 ingest analyzer 和数据复盘统一走 direct Codex Responses。",
    },
    {
        "profile": "media_creation",
        "usage": "爆款拆解、创作稿、脚本、分镜、素材创作、创作简报回填",
        "callers": "selfmedia/deconstruct/viral_content/src/config.py; selfmedia/creation/llm_generator.py",
        "surface": "load_profile_llm_settings('media_creation') -> common.generate_json_from_parts",
        "state": "拆解、创作稿、创作简报回填统一走 direct Codex Responses；关键帧/图文图片直接作为 Responses parts 输入。",
    },
    {
        "profile": "activity_cleaning",
        "usage": "活动 Brief AI 清洗、活动链接/字段结构化",
        "callers": "openclaw-tag-router/openclaw_app/services/content_flow_client.py; router/activity_daily.py",
        "surface": "_call_profile_provider_json('activity_cleaning') -> common.generate_json_from_parts",
        "state": "统一走 direct Codex Responses。",
    },
    {
        "profile": "daily_task_extraction",
        "usage": "Daily 日程、待办、提醒自然语言抽取与分流",
        "callers": "openclaw-tag-router/openclaw_app/router/activity_daily.py",
        "surface": "_call_profile_provider_json('daily_task_extraction')",
        "state": "用于 _extract_daily_task_with_llm() 和 _extract_todo_intake_with_llm()。",
    },
    {
        "profile": "daily_hierarchy_records_extraction",
        "usage": "Daily 父子层级事项拆分",
        "callers": "openclaw-tag-router/openclaw_app/router/activity_daily.py",
        "surface": "_call_profile_provider_json('daily_hierarchy_records_extraction')",
        "state": "用于 _extract_hierarchy_records_with_llm()。",
    },
    {
        "profile": "social_vision",
        "usage": "Social 人物档案图片视觉读取",
        "callers": "openclaw-agents/social/person-profile-skill/tools/person_archive.py",
        "surface": "load_profile_llm_settings('social_vision') -> common.generate_json_from_parts",
        "state": "人物档案图片可见事实、外观呈现和截图文字统一走 direct Codex Responses。",
    },
    {
        "profile": "content_cleaner",
        "usage": "OCR、transcript、采集正文清洗；商务 ID 语义抽取；再创任务卡；社交档案元数据抽取",
        "callers": "common/content_cleaner.py; selfmedia/business/id_business.py; openclaw-tag-router/openclaw_app/router/recreation.py; router/social_archive.py",
        "surface": "load_content_cleaner_llm_settings(); _call_profile_provider_json('content_cleaner')",
        "state": "统一走 direct Codex Responses。",
    },
)

NON_PROFILE_MODEL_ROWS = (
    {
        "name": "01 ingest 原始音频转写",
        "provider": "codex_responses",
        "model": "media_analysis resolved model",
        "code": "selfmedia/ingest/content_flow/src/transcriber.py; src/pipeline.py; content_flow_client.py transcribe_file()",
        "state": "audio_part_from_path() 把本地音频作为 Responses input_audio；转写 JSON 由 direct Codex Responses 返回。",
    },
    {
        "name": "03 拆解关键帧/图文图片理解",
        "provider": "codex_responses",
        "model": "media_creation resolved model",
        "code": "selfmedia/deconstruct/viral_content/src/runner.py; common/llm_client.py",
        "state": "prepare_media_evidence() 生成的全部关键帧/图文图片 parts 直接进入 Codex Responses。",
    },
    {
        "name": "Social 人物档案音频转写",
        "provider": "social_vision",
        "model": "social_vision resolved model",
        "code": "openclaw-agents/social/person-profile-skill/tools/person_archive.py",
        "state": "audio_part_from_path() 把本地音频作为 Responses input_audio；转写 JSON 由 direct Codex Responses 返回。",
    },
    {
        "name": "Social 人物档案图片读取",
        "provider": "social_vision",
        "model": "social_vision resolved model",
        "code": "openclaw-agents/social/person-profile-skill/tools/person_archive.py",
        "state": "describe_image_with_llm() 把图片作为 Responses input_image 直接交给 Codex Responses。",
    },
)


def canonical_payload(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit(f"config is not a JSON object: {path}")
    for key in ("defaults", "bots", "profiles", "providers"):
        if not isinstance(payload.get(key), dict):
            raise SystemExit(f"config missing object field {key}: {path}")
    return payload


def canonical_text(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def canonical_hash(payload: dict[str, Any]) -> str:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def file_hash(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        return canonical_hash(canonical_payload(path))
    except SystemExit:
        return ""


def load_state() -> dict[str, Any]:
    if not SYNC_STATE.exists():
        return {}
    try:
        parsed = json.loads(SYNC_STATE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(tmp_name, path)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


def write_json_config(path: Path, payload: dict[str, Any], *, dry_run: bool) -> None:
    if dry_run:
        return
    atomic_write(path, canonical_text(payload))


def cleanup_duplicate_notes(*, dry_run: bool) -> list[str]:
    removed: list[str] = []
    for pattern in DUPLICATE_NOTE_PATTERNS:
        for path in OBSIDIAN_DIR.glob(pattern):
            if path == OBSIDIAN_NOTE or not path.is_file():
                continue
            removed.append(str(path))
            if not dry_run:
                path.unlink()
    return sorted(removed)


def markdown_cell(value: Any) -> str:
    text = str(value if value is not None else "")
    return text.replace("|", "\\|").replace("\n", "<br>")


def markdown_table(headers: list[str], rows: list[list[Any]]) -> list[str]:
    lines = [
        "| " + " | ".join(markdown_cell(header) for header in headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(markdown_cell(value) for value in row) + " |")
    return lines


def merged_profile_runtime(payload: dict[str, Any], profile_name: str) -> dict[str, Any]:
    defaults = payload.get("defaults") or {}
    profile = (payload.get("profiles") or {}).get(profile_name) or {}
    bot_name = str(profile.get("bot") or "")
    bot = (payload.get("bots") or {}).get(bot_name) or {}
    provider_name = str(profile.get("provider") or bot.get("provider") or "")
    provider = (payload.get("providers") or {}).get(provider_name) or {}
    return {
        **provider,
        **defaults,
        **bot,
        **profile,
        "_profile": profile_name,
        "_bot": bot_name,
        "_provider": provider_name,
    }


def provider_key_status(provider: dict[str, Any]) -> str:
    return "已配置" if str(provider.get("api_key") or "").strip() else "未配置"


def render_note(payload: dict[str, Any], repo_hash: str, obsidian_hash: str) -> str:
    now = datetime.now().isoformat(timespec="seconds")
    lines = [
        "# OpenClaw Bot LLM 配置",
        "",
        "> 自动生成说明文件；可读来源是同目录 `openclaw_bots.json`。不要手工改这份 Markdown。",
        "",
        f"- 服务器 Obsidian 路径：`{OBSIDIAN_DIR}`",
        f"- Mac Obsidian 目标路径：`{MAC_OBSIDIAN_DIR}`",
        f"- 仓库配置：`{REPO_CONFIG}`",
        f"- 最近同步：`{now}`",
        f"- repo sha256：`{repo_hash}`",
        f"- obsidian sha256：`{obsidian_hash}`",
        "",
        "## Bots",
        "",
        "| bot | provider | agent | model | thinking | timeout | cwd |",
        "|---|---|---|---|---|---:|---|",
    ]
    defaults = payload.get("defaults") or {}
    for name, bot in sorted((payload.get("bots") or {}).items()):
        provider = (payload.get("providers") or {}).get((bot or {}).get("provider") or "") or {}
        merged = {**provider, **defaults, **(bot or {})}
        lines.append(
            "| "
            + " | ".join(
                [
                    str(name),
                    str(merged.get("provider") or ""),
                    str(merged.get("agent") or ""),
                    str(merged.get("model") or ""),
                    str(merged.get("thinking") or ""),
                    str(merged.get("timeout") or ""),
                    str(merged.get("cwd") or ""),
                ]
            )
            + " |"
        )
    lines.extend(["", "## Profiles", "", "| profile | provider | bot | model | thinking | timeout |", "|---|---|---|---|---|---:|"])
    for name, profile in sorted((payload.get("profiles") or {}).items()):
        bot_name = str((profile or {}).get("bot") or "")
        bot = (payload.get("bots") or {}).get(bot_name) or {}
        provider = (payload.get("providers") or {}).get((profile or {}).get("provider") or bot.get("provider") or "") or {}
        merged = {**provider, **defaults, **bot, **(profile or {})}
        lines.append(
            "| "
            + " | ".join(
                [
                    str(name),
                    str(merged.get("provider") or ""),
                    bot_name,
                    str(merged.get("model") or ""),
                    str(merged.get("thinking") or ""),
                    str(merged.get("timeout") or ""),
                ]
            )
            + " |"
        )
    lines.extend(["", "## Providers", "", "| provider | model | base_url | api_type | timeout | api_key |", "|---|---|---|---|---:|---|"])
    for name, provider in sorted((payload.get("providers") or {}).items()):
        api_key = str((provider or {}).get("api_key") or "")
        lines.append(
            "| "
            + " | ".join(
                [
                    str(name),
                    str((provider or {}).get("model") or ""),
                    str((provider or {}).get("base_url") or ""),
                    str((provider or {}).get("api_type") or ""),
                    str((provider or {}).get("timeout") or ""),
                    "已配置" if api_key else "未配置",
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Sync",
            "",
            "```bash",
            "python3 /home/ubuntu/selfmedia-tools/runtime/maintenance/deploy/sync_openclaw_bot_config.py",
            "python3 /home/ubuntu/selfmedia-tools/runtime/maintenance/deploy/sync_openclaw_bot_config.py --direction obsidian-to-repo",
            "python3 /home/ubuntu/selfmedia-tools/runtime/maintenance/deploy/sync_openclaw_bot_config.py --direction repo-to-obsidian",
            "python3 /home/ubuntu/selfmedia-tools/runtime/maintenance/deploy/sync_openclaw_agent_models.py",
            "python3 /home/ubuntu/selfmedia-tools/runtime/maintenance/deploy/deploy_openclaw_runtime.py",
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def render_llm_usage_ssot(payload: dict[str, Any], repo_hash: str) -> str:
    now = datetime.now().isoformat(timespec="seconds")
    providers = payload.get("providers") or {}
    lines = [
        "# OpenClaw Bot LLM 使用矩阵 SSOT",
        "",
        "> 自动生成公共知识库文件；描述当前真实代码状态，不描述目标改造状态。不要手工改这份 Markdown。",
        "",
        f"- 服务器公共知识库路径：`{PUBLIC_KNOWLEDGE_DIR}`",
        f"- Mac 公共知识库目标路径：`{MAC_PUBLIC_KNOWLEDGE_DIR}`",
        f"- 仓库配置事实源：`{REPO_CONFIG}`",
        f"- 配置 sha256：`{repo_hash}`",
        f"- 最近生成：`{now}`",
        "",
        "## 1. 事实源边界",
        "",
        "- Bot / profile / provider 的可编辑事实源是 `/home/ubuntu/selfmedia-tools/config/openclaw_bots.json`。",
        "- `openclaw配置/OpenClaw Bot LLM 配置.md` 是配置镜像说明，由 `runtime/maintenance/deploy/sync_openclaw_bot_config.py` 生成。",
        "- 本文件是 LLM 使用矩阵 SSOT，由同一个脚本生成，覆盖 profile 路径和非 profile 模型理解路径。",
        "- 本文件不输出真实 API key，只输出配置状态。",
        "",
        "## 2. Provider 当前状态",
        "",
    ]
    provider_rows: list[list[Any]] = []
    for name, provider in sorted(providers.items()):
        provider_rows.append(
            [
                name,
                provider.get("model") or "",
                provider.get("api_type") or "",
                provider.get("base_url") or "",
                provider.get("timeout") or "",
                provider.get("thinking") or "",
                provider_key_status(provider),
            ]
        )
    lines.extend(
        markdown_table(
            ["provider", "model", "api_type", "base_url", "timeout", "thinking", "api_key"],
            provider_rows,
        )
    )
    lines.extend(["", "## 3. Bot 默认运行时", ""])
    bot_rows: list[list[Any]] = []
    defaults = payload.get("defaults") or {}
    for name, bot in sorted((payload.get("bots") or {}).items()):
        provider = providers.get((bot or {}).get("provider") or "") or {}
        merged = {**provider, **defaults, **(bot or {})}
        bot_rows.append(
            [
                name,
                merged.get("provider") or "",
                merged.get("agent") or "",
                merged.get("model") or "",
                merged.get("thinking") or "",
                merged.get("timeout") or "",
                merged.get("cwd") or "",
            ]
        )
    lines.extend(markdown_table(["bot", "provider", "agent", "model", "thinking", "timeout", "cwd"], bot_rows))
    lines.extend(["", "## 4. Profile 使用矩阵", ""])
    profile_rows: list[list[Any]] = []
    for row in PROFILE_USAGE_ROWS:
        profile_name = row["profile"]
        runtime = merged_profile_runtime(payload, profile_name)
        profile_rows.append(
            [
                profile_name,
                row["usage"],
                runtime.get("_provider") or "",
                runtime.get("_bot") or "",
                runtime.get("agent") or "",
                runtime.get("model") or "",
                runtime.get("api_type") or "",
                runtime.get("thinking") or "",
                runtime.get("timeout") or "",
                row["surface"],
                row["callers"],
                row["state"],
            ]
        )
    lines.extend(
        markdown_table(
            [
                "profile",
                "当前用途",
                "provider",
                "bot",
                "agent",
                "model",
                "api_type",
                "thinking",
                "timeout",
                "调用面",
                "代码位置",
                "当前状态说明",
            ],
            profile_rows,
        )
    )
    lines.extend(["", "## 5. 非 profile / 特殊模型理解路径", ""])
    non_profile_rows: list[list[Any]] = []
    for row in NON_PROFILE_MODEL_ROWS:
        model = row["model"]
        if model == "media_creation resolved model":
            model = merged_profile_runtime(payload, "media_creation").get("model") or model
        elif model == "media_analysis resolved model":
            model = merged_profile_runtime(payload, "media_analysis").get("model") or model
        elif model == "social_vision resolved model":
            model = merged_profile_runtime(payload, "social_vision").get("model") or model
        non_profile_rows.append([row["name"], row["provider"], model, row["code"], row["state"]])
    lines.extend(markdown_table(["使用点", "provider / 执行层", "模型", "代码位置", "当前状态说明"], non_profile_rows))
    lines.extend(
        [
            "",
            "## 6. 当前代码中需要特别留意的多路径",
            "",
            "- `common.llm_client` 的 JSON 生成入口只支持 `openai_codex_responses` 和 `openai_chat_completions`；生产理解 profile 统一使用 `openai_codex_responses`。",
            "- `ContentFlowClient._call_profile_provider_json()` 已统一接入 `common.generate_json_from_parts()`，OpenClaw agent 配置会返回 pending/manual。",
            "- `selfmedia/ingest/content_flow/src/analyzer.py` 当前直接调用 Codex Responses，不走 Codex CLI 或 OpenClaw agent。",
            "- `selfmedia/ingest/content_flow/src/transcriber.py` 当前把原始音频作为 Responses `input_audio` 交给 Codex Responses。",
            "- `selfmedia/deconstruct/viral_content` 当前把关键帧/图文图片 parts 直接交给 Codex Responses。",
            "- Social 人物档案图片读取和音频转写当前直接走 Codex Responses。",
            "",
            "## 7. 生成与验证",
            "",
            "```bash",
            "python3 /home/ubuntu/selfmedia-tools/runtime/maintenance/deploy/sync_openclaw_bot_config.py",
            "PYTHONPATH=/home/ubuntu/selfmedia-tools pytest -q /home/ubuntu/selfmedia-tools/tests/test_sync_openclaw_bot_config.py",
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def write_state(repo_hash: str, obsidian_hash: str, direction: str, *, dry_run: bool) -> None:
    if dry_run:
        return
    state = {
        "last_synced_at": datetime.now().isoformat(timespec="seconds"),
        "repo_config": str(REPO_CONFIG),
        "obsidian_config": str(OBSIDIAN_CONFIG),
        "mac_obsidian_dir": MAC_OBSIDIAN_DIR,
        "repo_hash": repo_hash,
        "obsidian_hash": obsidian_hash,
        "direction": direction,
    }
    atomic_write(SYNC_STATE, json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def choose_direction(requested: str, repo_hash: str, obsidian_hash: str) -> str:
    if requested != "auto":
        return requested
    if not OBSIDIAN_CONFIG.exists():
        return "repo-to-obsidian"
    if repo_hash == obsidian_hash:
        return "none"
    state = load_state()
    repo_changed = bool(state.get("repo_hash")) and state.get("repo_hash") != repo_hash
    obsidian_changed = bool(state.get("obsidian_hash")) and state.get("obsidian_hash") != obsidian_hash
    if repo_changed and not obsidian_changed:
        return "repo-to-obsidian"
    if obsidian_changed and not repo_changed:
        return "obsidian-to-repo"
    repo_mtime = REPO_CONFIG.stat().st_mtime
    obsidian_mtime = OBSIDIAN_CONFIG.stat().st_mtime
    return "repo-to-obsidian" if repo_mtime >= obsidian_mtime else "obsidian-to-repo"


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync OpenClaw Bot LLM config from the repo source to the Obsidian mirror.")
    parser.add_argument(
        "--direction",
        choices=("auto", "repo-to-obsidian", "obsidian-to-repo"),
        default="repo-to-obsidian",
        help="Sync direction. obsidian-to-repo is an explicit manual recovery path; timer/default use repo-to-obsidian.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Show the action without writing files.")
    parser.add_argument("--restart-services", action="store_true", help="Restart runtime services when config changed.")
    args = parser.parse_args()

    repo_payload = canonical_payload(REPO_CONFIG)
    repo_hash = canonical_hash(repo_payload)
    obsidian_hash = file_hash(OBSIDIAN_CONFIG)
    runtime_config_changed = repo_hash != obsidian_hash
    direction = choose_direction(args.direction, repo_hash, obsidian_hash)

    if direction == "repo-to-obsidian":
        payload = repo_payload
        write_json_config(OBSIDIAN_CONFIG, payload, dry_run=args.dry_run)
        obsidian_hash = canonical_hash(payload)
        action = f"repo -> obsidian: {OBSIDIAN_CONFIG}"
    elif direction == "obsidian-to-repo":
        payload = canonical_payload(OBSIDIAN_CONFIG)
        write_json_config(REPO_CONFIG, payload, dry_run=args.dry_run)
        repo_hash = canonical_hash(payload)
        obsidian_hash = canonical_hash(payload)
        action = f"obsidian -> repo: {REPO_CONFIG}"
    else:
        payload = repo_payload
        obsidian_hash = repo_hash
        action = "already in sync"

    note = render_note(payload, repo_hash, obsidian_hash)
    llm_usage_ssot = render_llm_usage_ssot(payload, repo_hash)
    if not args.dry_run:
        atomic_write(OBSIDIAN_NOTE, note)
        atomic_write(LLM_USAGE_SSOT_NOTE, llm_usage_ssot)
    removed_duplicate_notes = cleanup_duplicate_notes(dry_run=args.dry_run)
    write_state(repo_hash, obsidian_hash, direction, dry_run=args.dry_run)
    restarted_services = False
    if args.restart_services and runtime_config_changed and direction != "none" and not args.dry_run:
        subprocess.run(
            ["python3", str(SYNC_AGENT_MODELS)],
            check=True,
            timeout=int(os.getenv("OPENCLAW_SYNC_AGENT_MODELS_TIMEOUT_SECONDS", "120")),
        )
        subprocess.run(
            ["systemctl", "--user", "restart", "content-flow.service", "openclaw-gateway.service", "openclaw-feishu-gateway.service"],
            check=True,
            timeout=int(os.getenv("OPENCLAW_RESTART_SERVICES_TIMEOUT_SECONDS", "60")),
        )
        restarted_services = True

    print(
        json.dumps(
            {
                "ok": True,
                "action": action,
                "direction": direction,
                "config_changed": runtime_config_changed,
                "obsidian_config": str(OBSIDIAN_CONFIG),
                "obsidian_note": str(OBSIDIAN_NOTE),
                "llm_usage_ssot_note": str(LLM_USAGE_SSOT_NOTE),
                "removed_duplicate_notes": removed_duplicate_notes,
                "restarted_services": restarted_services,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
