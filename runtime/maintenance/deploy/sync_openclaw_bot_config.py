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
        "usage": "OpenClaw 【说明】能力介绍与自然语言推荐",
        "callers": "openclaw-tag-router/openclaw_app/services/capability_matcher.py; openclaw-tag-router/openclaw_app/router/system_routes.py",
        "surface": "load_profile_llm_settings('system_guide') -> OpenClaw Gateway structured JSON",
        "state": "只读取公开能力目录并返回介绍或推荐；不调用工具，不执行归档、创作、入库或同步。",
    },
    {
        "profile": "knowledge_delegate",
        "usage": "【归档】【补全】【认知】【学习】【学习-整理】普通知识委托",
        "callers": "openclaw-tag-router/openclaw_app/router/knowledge_delegate.py",
        "surface": "profile_config/profile_runtime('knowledge_delegate') -> openclaw agent",
        "state": "唯一转交 feishu-knowledge；认证来自 OpenClaw 对 /home/ubuntu/.codex/auth.json 的 OAuth 投影。",
    },
    {
        "profile": "transcription_postprocess",
        "usage": "录音/访谈逐字稿整理、分块摘要、附件合并、全局纪要、一致性检查和修订",
        "callers": "openclaw-tag-router/openclaw_app/services/content_flow_client.py; router/transcription.py",
        "surface": "_call_profile_provider_json('transcription_postprocess') -> common.generate_json_from_parts",
        "state": "统一走 OpenClaw Gateway structured JSON；不读取 OPENAI_API_KEY。",
    },
    {
        "profile": "media_analysis",
        "usage": "内容采集结构化分析、爆款关键帧/图文理解、数据截图复盘、Media 数据审计",
        "callers": "selfmedia/ingest/content_flow/src/config.py; selfmedia/ingest/content_flow/src/analyzer.py; selfmedia/deconstruct/viral_content/src/runner.py; selfmedia/review/data_review.py",
        "surface": "load_profile_llm_settings('media_analysis') -> common.generate_json_from_parts",
        "state": "01 ingest analyzer 和数据复盘统一走 OpenClaw Gateway structured JSON。",
    },
    {
        "profile": "media_creation",
        "usage": "创作稿、脚本、分镜、SourceAsset 创作交接、创作简报回填",
        "callers": "selfmedia/deconstruct/viral_content/src/config.py; selfmedia/creation/llm_generator.py",
        "surface": "load_profile_llm_settings('media_creation') -> common.generate_json_from_parts",
        "state": "所有正式创作和创作简报回填统一走 OpenClaw Gateway structured JSON；不承载拆解或证据分析。",
    },
    {
        "profile": "activity_cleaning",
        "usage": "活动 Brief AI 清洗、活动链接/字段结构化",
        "callers": "openclaw-tag-router/openclaw_app/services/content_flow_client.py; router/activity_daily.py",
        "surface": "_call_profile_provider_json('activity_cleaning') -> common.generate_json_from_parts",
        "state": "统一走 OpenClaw Gateway structured JSON。",
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
        "state": "人物档案图片可见事实、外观呈现和截图文字作为 Gateway attachment 进入 OpenClaw OAuth 模型。",
    },
    {
        "profile": "content_cleaner",
        "usage": "OCR、transcript、采集正文清洗；商务 ID 语义抽取；创作交接素材摘要；社交档案元数据抽取",
        "callers": "common/content_cleaner.py; selfmedia/business/id_business.py; selfmedia/creation/llm_generator.py; router/social_archive.py",
        "surface": "load_content_cleaner_llm_settings(); _call_profile_provider_json('content_cleaner')",
        "state": "统一走 OpenClaw Gateway structured JSON。",
    },
)

NON_PROFILE_MODEL_ROWS = (
    {
        "name": "01 ingest 原始音频转写",
        "provider": "dashscope",
        "model": "DASHSCOPE_ASR_MODEL",
        "code": "selfmedia/ingest/content_flow/src/transcriber.py; src/pipeline.py; content_flow_client.py transcribe_file()",
        "state": "统一走 DashScope/阿里非实时 ASR；content-flow 不再把原始音频交给 Codex Responses。",
    },
    {
        "name": "03 拆解关键帧/图文图片理解",
        "provider": "openclaw_codex",
        "model": "media_analysis resolved model",
        "code": "selfmedia/deconstruct/viral_content/src/runner.py; common/llm_client.py",
        "state": "prepare_media_evidence() 生成的关键帧/图文图片作为 Gateway attachment 进入 media_analysis。",
    },
    {
        "name": "Social 人物档案音频转写",
        "provider": "social_vision",
        "model": "social_vision resolved model",
        "code": "openclaw-agents/social/person-profile-skill/tools/person_archive.py",
        "state": "audio_part_from_path() 把本地音频作为 Gateway attachment；结构化 JSON 由 OpenClaw OAuth 模型返回。",
    },
    {
        "name": "Social 人物档案图片读取",
        "provider": "social_vision",
        "model": "social_vision resolved model",
        "code": "openclaw-agents/social/person-profile-skill/tools/person_archive.py",
        "state": "describe_image_with_llm() 把图片作为 Gateway attachment 交给 OpenClaw OAuth 模型。",
    },
)


def canonical_payload(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit(f"config is not a JSON object: {path}")
    for key in ("defaults", "model_tiers", "bots", "profiles", "providers"):
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


def resolved_model_tier(payload: dict[str, Any], scope: dict[str, Any], bot: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    providers = payload.get("providers") or {}
    provider_name = str(scope.get("provider") or bot.get("provider") or "")
    provider = (providers.get(provider_name) or scope) if scope.get("default_model_tier") else providers.get(provider_name) or {}
    tier_name = str(scope.get("model_tier") or bot.get("model_tier") or provider.get("default_model_tier") or "")
    tier = (payload.get("model_tiers") or {}).get(tier_name) or {}
    if not isinstance(tier, dict) or not tier.get("model") or not tier.get("reasoning"):
        raise SystemExit(f"invalid model tier {tier_name!r} for provider {provider_name!r}")
    return tier_name, tier


def merged_bot_runtime(payload: dict[str, Any], bot_name: str) -> dict[str, Any]:
    defaults = payload.get("defaults") or {}
    bot = (payload.get("bots") or {}).get(bot_name) or {}
    provider_name = str(bot.get("provider") or "")
    provider = (payload.get("providers") or {}).get(provider_name) or {}
    tier_name, tier = resolved_model_tier(payload, bot, {})
    return {
        **provider,
        **defaults,
        **bot,
        "_bot": bot_name,
        "_provider": provider_name,
        "_model_tier": tier_name,
        "model": tier["model"],
        "reasoning": tier["reasoning"],
    }


def merged_profile_runtime(payload: dict[str, Any], profile_name: str) -> dict[str, Any]:
    profile = (payload.get("profiles") or {}).get(profile_name) or {}
    bot_name = str(profile.get("bot") or "")
    bot = (payload.get("bots") or {}).get(bot_name) or {}
    provider_name = str(profile.get("provider") or bot.get("provider") or "")
    provider = (payload.get("providers") or {}).get(provider_name) or {}
    tier_name, tier = resolved_model_tier(payload, profile, bot)
    return {
        **provider,
        **(payload.get("defaults") or {}),
        **bot,
        **profile,
        "_profile": profile_name,
        "_bot": bot_name,
        "_provider": provider_name,
        "_model_tier": tier_name,
        "model": tier["model"],
        "reasoning": tier["reasoning"],
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
        "| bot | provider | agent | model | reasoning | timeout | cwd |",
        "|---|---|---|---|---|---:|---|",
    ]
    for name, bot in sorted((payload.get("bots") or {}).items()):
        merged = merged_bot_runtime(payload, str(name))
        lines.append(
            "| "
            + " | ".join(
                [
                    str(name),
                    str(merged.get("provider") or ""),
                    str(merged.get("agent") or ""),
                    str(merged.get("model") or ""),
                    str(merged.get("reasoning") or ""),
                    str(merged.get("timeout") or ""),
                    str(merged.get("cwd") or ""),
                ]
            )
            + " |"
        )
    lines.extend(["", "## Profiles", "", "| profile | provider | bot | model | reasoning | timeout |", "|---|---|---|---|---|---:|"])
    for name, profile in sorted((payload.get("profiles") or {}).items()):
        bot_name = str((profile or {}).get("bot") or "")
        merged = merged_profile_runtime(payload, str(name))
        lines.append(
            "| "
            + " | ".join(
                [
                    str(name),
                    str(merged.get("provider") or ""),
                    bot_name,
                    str(merged.get("model") or ""),
                    str(merged.get("reasoning") or ""),
                    str(merged.get("timeout") or ""),
                ]
            )
            + " |"
        )
    lines.extend(["", "## Providers", "", "| provider | model | base_url | api_type | timeout | api_key |", "|---|---|---|---|---:|---|"])
    for name, provider in sorted((payload.get("providers") or {}).items()):
        _, tier = resolved_model_tier(payload, provider, {})
        api_key = str((provider or {}).get("api_key") or "")
        lines.append(
            "| "
            + " | ".join(
                [
                    str(name),
                    str(tier.get("model") or ""),
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
        _, tier = resolved_model_tier(payload, provider, {})
        provider_rows.append(
            [
                name,
                tier.get("model") or "",
                provider.get("api_type") or "",
                provider.get("base_url") or "",
                provider.get("timeout") or "",
                tier.get("reasoning") or "",
                provider_key_status(provider),
            ]
        )
    lines.extend(
        markdown_table(
            ["provider", "model", "api_type", "base_url", "timeout", "reasoning", "api_key"],
            provider_rows,
        )
    )
    lines.extend(["", "## 3. Bot 默认运行时", ""])
    bot_rows: list[list[Any]] = []
    for name, bot in sorted((payload.get("bots") or {}).items()):
        merged = merged_bot_runtime(payload, str(name))
        bot_rows.append(
            [
                name,
                merged.get("provider") or "",
                merged.get("agent") or "",
                merged.get("model") or "",
                merged.get("reasoning") or "",
                merged.get("timeout") or "",
                merged.get("cwd") or "",
            ]
        )
    lines.extend(markdown_table(["bot", "provider", "agent", "model", "reasoning", "timeout", "cwd"], bot_rows))
    lines.extend(["", "## 4. Profile 使用矩阵", ""])
    profile_rows: list[list[Any]] = []
    for row in PROFILE_USAGE_ROWS:
        profile_name = row["profile"]
        if profile_name not in (payload.get("profiles") or {}):
            continue
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
                runtime.get("reasoning") or "",
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
                "reasoning",
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
    profiles = payload.get("profiles") or {}
    for row in NON_PROFILE_MODEL_ROWS:
        model = row["model"]
        if model == "media_creation resolved model" and "media_creation" in profiles:
            model = merged_profile_runtime(payload, "media_creation").get("model") or model
        elif model == "media_analysis resolved model" and "media_analysis" in profiles:
            model = merged_profile_runtime(payload, "media_analysis").get("model") or model
        elif model == "social_vision resolved model" and "social_vision" in profiles:
            model = merged_profile_runtime(payload, "social_vision").get("model") or model
        non_profile_rows.append([row["name"], row["provider"], model, row["code"], row["state"]])
    lines.extend(markdown_table(["使用点", "provider / 执行层", "模型", "代码位置", "当前状态说明"], non_profile_rows))
    lines.extend(
        [
            "",
            "## 6. 当前代码中需要特别留意的多路径",
            "",
            "- `common.llm_client` 的生产 JSON 生成入口统一使用 `openclaw_agent`，每次调用带独立 sessionKey 和 idempotencyKey。",
            "- `ContentFlowClient._call_profile_provider_json()` 统一接入 `common.generate_json_from_parts()`；模型失败返回 pending/manual。",
            "- `selfmedia/ingest/content_flow/src/analyzer.py` 通过 Gateway 使用 canonical OpenClaw OAuth，不读取 direct provider key。",
            "- `selfmedia/ingest/content_flow/src/transcriber.py` 仍走 DashScope/阿里非实时 ASR，结构化文本分析走 OpenClaw OAuth。",
            "- `selfmedia/deconstruct/viral_content` 的关键帧/图文图片 parts 复用公共 Gateway attachment 适配。",
            "- Social 人物档案图片读取和音频结构化复用公共 Gateway attachment 适配。",
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
            ["systemctl", "--user", "restart", "content-flow.service", "openclaw-gateway.service"],
            check=True,
            timeout=int(os.getenv("OPENCLAW_RESTART_SERVICES_TIMEOUT_SECONDS", "60")),
        )
        subprocess.run(
            ["sudo", "-n", "systemctl", "restart", "openclaw-feishu-gateway.service"],
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
