from __future__ import annotations

import argparse
import json
import logging
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = Path(__file__).resolve().parents[2]
try:
    sys.path.remove(str(SCRIPT_DIR))
except ValueError:
    pass
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from media_vault.vault import MediaVault, require_tenant_id  # noqa: E402

MEDIA_CREATION_RUNTIME_PYTHON = Path(os.getenv("SELFMEDIA_RUNTIME_PYTHON", sys.executable))
CREATION_RUNTIME_COMMANDS = {"consultation", "shooting-execution", "shooting-backwash"}
CREATION_RUNTIME_RUN_PARTS = {"creation", "创作", "deconstruct", "拆解"}

from common.social_runtime import (  # noqa: E402
    INTERACTION_KEYS,
    count_value,
    detect_platform,
    extract_urls,
    feishu_bitable_refs,
    feishu_bool,
    feishu_field_types,
    feishu_first_field,
    feishu_list_records,
    feishu_required_default,
    feishu_table_url_from_env,
    feishu_update_record,
    feishu_urls_from_fields,
    load_default_env_files,
    metric_summary,
    now_iso,
    quality_score,
    refresh_posts,
    row_to_feishu_fields,
    slug_time,
    total_interactions,
    write_feishu_records,
    write_json,
    write_markdown,
)

SOCIAL_THEORY_TAGS = ("/女性爱", "/性兴趣", "/风控", "/性资源", "/行动")
BLOCKED_SOCIAL_THEORY_TAGS = ("/风控量表",)
SLASH_THEORY_RE = re.compile(r"/([\w\u4e00-\u9fff-]+)")
THEORY_TAG_SUFFIXES = ("进行分析", "来分析", "分析一下", "分析")


def clean_slash_theory_tag(value: str) -> str:
    tag = value.strip().strip("/")
    for suffix in THEORY_TAG_SUFFIXES:
        if tag.endswith(suffix) and len(tag) > len(suffix):
            tag = tag[: -len(suffix)]
            break
    return f"/{tag.strip()}" if tag.strip() else ""


ACCOUNT_MONITOR_FIELD_SPECS = {
    "账号名称": 1,
    "平台": 1,
    "近期作品链接": 1,
    "启用": 7,
    "最近运行时间": 5,
    "最近状态": 1,
    "最近作品数": 2,
    "最近总互动": 2,
    "最近错误": 1,
    "最近日报摘要": 1,
}

ACCOUNT_MONITOR_LINK_FIELDS = frozenset(("近期作品链接", "作品链接", "监控链接", "链接", "URL", "urls"))
ACCOUNT_MONITOR_ENABLED_FIELDS = frozenset(("启用", "是否启用", "监控", "enabled"))
CREATOR_PROFILE_FIELD_MARKERS = frozenset(
    (
        "creator_profile_id",
        "profile_id",
        "author_id",
        "博主IP",
        "作者ID",
        "平台ID",
        "主页链接",
        "赛道",
        "粉丝数(k)",
    )
)
DAILY_POLL_STATUS_LABELS = {
    "ok": "正常",
    "ok_empty": "无可轮询账号",
    "partial": "部分成功",
    "missing": "未获取到作品",
    "missing_urls": "缺少作品链接",
    "error": "轮询失败",
}
DAILY_POLL_DECISION_LABELS = {
    "deconstruct": "建议拆解",
    "review": "继续观察",
    "skip": "暂不处理",
}
DAILY_POLL_DETAIL_COMMENT_KEYS = ("top_comments", "comments", "hot_comments", "high_like_comments")
LOGGER = logging.getLogger(__name__)


def print_json(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def parse_json_arg(value: str, *, env_name: str = "") -> dict[str, Any] | None:
    text = (value or "").strip()
    if not text and env_name:
        text = os.environ.get(env_name, "").strip()
    if not text:
        return None
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise SystemExit("conversation context must be a JSON object")
    return parsed


def conversation_context_json_arg(value: str) -> str:
    return (value or "").strip() or os.environ.get("OPENCLAW_CONVERSATION_CONTEXT_JSON", "").strip()


def social_theory_matches(text: str) -> list[str]:
    normalized = re.sub(r"https?://\S+", " ", text or "")
    slash_tags = {clean_slash_theory_tag(match) for match in SLASH_THEORY_RE.findall(normalized)}
    return [tag for tag in (*BLOCKED_SOCIAL_THEORY_TAGS, *SOCIAL_THEORY_TAGS) if tag in slash_tags]


def reject_social_theory_tags(text: str) -> None:
    matched = social_theory_matches(text)
    if matched:
        if any(tag in BLOCKED_SOCIAL_THEORY_TAGS for tag in matched):
            raise SystemExit(
                "社交理论标签未在 selfmedia 注册，selfmedia/爆款入口拒绝执行："
                + "、".join(tag for tag in matched if tag in BLOCKED_SOCIAL_THEORY_TAGS)
            )
        raise SystemExit(
            "社交理论标签只能由 social bot 调用，selfmedia/爆款入口拒绝执行："
            + "、".join(matched)
        )


def canonical_creation_python() -> Path:
    if not MEDIA_CREATION_RUNTIME_PYTHON.exists():
        raise SystemExit(f"缺少 Media 创作运行时 Python：{MEDIA_CREATION_RUNTIME_PYTHON}")
    return MEDIA_CREATION_RUNTIME_PYTHON


def _same_python(left: Path, right: Path) -> bool:
    try:
        return left.resolve() == right.resolve()
    except OSError:
        return str(left) == str(right)


def _requires_creation_runtime(args: argparse.Namespace) -> bool:
    if args.command in CREATION_RUNTIME_COMMANDS:
        return True
    if args.command == "run":
        return str(getattr(args, "part", "")).strip() in CREATION_RUNTIME_RUN_PARTS
    return False


def ensure_creation_runtime(args: argparse.Namespace) -> None:
    if not _requires_creation_runtime(args):
        return
    python = canonical_creation_python()
    if _same_python(Path(sys.executable), python):
        return
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{ROOT}:{env.get('PYTHONPATH', '')}".rstrip(":")
    completed = run_command_with_watchdog(
        [str(python), str(Path(__file__).resolve()), *sys.argv[1:]],
        ROOT,
        timeout=int(float(os.getenv("SELFMEDIA_OPENCLAW_REEXEC_TIMEOUT_SECONDS", "10800"))),
        env=env,
    )
    if completed.stdout:
        print(completed.stdout, end="")
    if completed.stderr:
        print(completed.stderr, end="", file=sys.stderr)
    raise SystemExit(completed.returncode)


def repo_subprocess_env() -> dict[str, str]:
    env = os.environ.copy()
    paths = [str(ROOT)]
    existing = env.get("PYTHONPATH", "").strip()
    if existing:
        paths.append(existing)
    env["PYTHONPATH"] = ":".join(paths)
    return env


def run_command(command: list[str], cwd: Path, timeout: int = 10800) -> dict[str, Any]:
    completed = run_command_with_watchdog(command, cwd, timeout=timeout)
    return {
        "ok": completed.returncode == 0,
        "returncode": completed.returncode,
        "command": command,
        "cwd": str(cwd),
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }


def run_command_with_watchdog(command: list[str], cwd: Path, timeout: int = 10800, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    heartbeat_seconds = max(10, int(float(os.getenv("SELFMEDIA_OPENCLAW_SUBPROCESS_WATCHDOG_HEARTBEAT_SECONDS", "60"))))
    started_at = time.monotonic()
    process = subprocess.Popen(
        command,
        cwd=str(cwd),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env or repo_subprocess_env(),
    )
    watchdog_lines: list[str] = []
    while True:
        elapsed = time.monotonic() - started_at
        remaining = max(0.1, float(timeout) - elapsed)
        wait_for = min(float(heartbeat_seconds), remaining)
        try:
            stdout, stderr = process.communicate(timeout=wait_for)
            if watchdog_lines:
                stderr = "\n".join([*(line for line in watchdog_lines if line), stderr or ""]).strip()
            return subprocess.CompletedProcess(command, process.returncode, stdout or "", stderr or "")
        except subprocess.TimeoutExpired:
            elapsed = time.monotonic() - started_at
            if elapsed >= timeout:
                process.kill()
                stdout, stderr = process.communicate()
                watchdog_lines.append(f"[watchdog] timeout_after={int(elapsed)}s limit={timeout}s command={command[0]}")
                stderr = "\n".join([*(line for line in watchdog_lines if line), stderr or ""]).strip()
                return subprocess.CompletedProcess(command, -9, stdout or "", stderr)
            watchdog_lines.append(f"[watchdog] still_running elapsed={int(elapsed)}s command={command[0]}")


def collect_urls(args: argparse.Namespace) -> list[str]:
    values: list[str] = []
    values.extend(args.urls or [])
    if args.text:
        values.append(args.text)
    if args.stdin:
        values.append(sys.stdin.read())
    urls = extract_urls(values)
    if not urls:
        raise SystemExit("no URLs found")
    return urls


def cookie_status() -> dict[str, Any]:
    candidates = {
        "douyin": [
            ROOT / "integrations" / "platform_auth" / "cookies" / "private" / "douyin-cookies.json",
            ROOT / "selfmedia" / "ingest" / "content_flow" / "private" / "douyin-cookies.json",
            Path(os.getenv("DOUYIN_COOKIES_JSON_PATH", "")),
        ],
        "xiaohongshu": [
            ROOT / "integrations" / "platform_auth" / "cookies" / "private" / "xiaohongshu-cookies.json",
            ROOT / "selfmedia" / "ingest" / "content_flow" / "private" / "xiaohongshu-cookies.json",
            Path(os.getenv("XIAOHONGSHU_COOKIES_JSON_PATH", "")),
        ],
    }
    result: dict[str, Any] = {"ok": True, "platforms": {}}
    for platform, paths in candidates.items():
        existing = []
        seen_paths: set[str] = set()
        for path in paths:
            if not str(path):
                continue
            expanded = path.expanduser()
            path_key = str(expanded)
            if path_key in seen_paths:
                continue
            seen_paths.add(path_key)
            if expanded.exists() and expanded.is_file():
                existing.append({"path": str(expanded), "size": expanded.stat().st_size})
        result["platforms"][platform] = {"ok": bool(existing), "files": existing}
        if not existing:
            result["ok"] = False
    return result


def run_content_ingest(args: argparse.Namespace) -> dict[str, Any]:
    urls = collect_urls(args)
    rows = refresh_posts(urls)
    return {"ok": all(row.get("health_status") == "ok" for row in rows), "module": "selfmedia.ingest.content_flow", "mode": "stats", "rows": rows}


def run_viral_deconstruct(args: argparse.Namespace) -> dict[str, Any]:
    text = args.text or " ".join(args.urls or [])
    if args.stdin:
        stdin_text = sys.stdin.read().strip()
        if stdin_text:
            text = stdin_text
    reject_social_theory_tags(text)
    if not text:
        raise SystemExit("deconstruct requires --text or --urls text")
    if args.smoke:
        from selfmedia.deconstruct.viral_content.src.trigger import extract_url, route_mode

        workflow_mode = route_mode(text)
        source_url = extract_url(text)
        return {
            "ok": bool(source_url),
            "mode": "smoke",
            "module": "selfmedia.deconstruct.viral_content",
            "workflow_mode": str(workflow_mode.value),
            "source_url": source_url,
            "write_policy": "no_feishu_write_no_llm_generation",
        }
    python = canonical_creation_python()
    command = [str(python), "-m", "selfmedia.deconstruct.viral_content.src.cli", text]
    if args.feishu_url:
        raise SystemExit("--feishu-url 已退役；拆解写入固定使用 Media Model v2 02A/02B")
    if args.partial:
        command.append("--partial")
        command.append("--no-write")
    elif args.no_write:
        command.append("--no-write")
    if not args.no_write and not args.partial:
        if not args.tenant_id:
            raise SystemExit("deconstruct write requires --tenant-id")
        command.extend(["--tenant-id", args.tenant_id])
    return run_command(command, ROOT, timeout=args.timeout)


def run_creation(args: argparse.Namespace) -> dict[str, Any]:
    from selfmedia.creation.workflow import handle_creation_command, smoke_creation_command

    if args.feishu_url:
        raise SystemExit("--feishu-url 已退役；创作素材候选固定从 Media Model v2 02A/02B 读取")
    text = args.text or " ".join(args.urls or [])
    if args.stdin:
        stdin_text = sys.stdin.read().strip()
        if stdin_text:
            text = stdin_text
    reject_social_theory_tags(text)
    if not text:
        raise SystemExit("creation requires --text")
    if args.smoke:
        return smoke_creation_command(
            text,
            tenant_id=args.tenant_id,
            conversation_context=parse_json_arg(args.conversation_context_json, env_name="OPENCLAW_CONVERSATION_CONTEXT_JSON"),
        )
    return handle_creation_command(
        text,
        tenant_id=args.tenant_id,
        dry_run=args.dry_run,
        no_write=args.no_write,
        viral_url="",
        activity_url=args.activity_url,
        business_url=args.business_url,
        inspiration_url=args.inspiration_url,
        creation_record_url=args.creation_record_url,
        limit=args.limit,
        ensure_schema=args.ensure_schema,
        conversation_context=parse_json_arg(args.conversation_context_json, env_name="OPENCLAW_CONVERSATION_CONTEXT_JSON"),
    )


def run_creation_consultation(args: argparse.Namespace) -> dict[str, Any]:
    from selfmedia.creation.consultation import handle_creation_consultation_command

    if args.feishu_url:
        raise SystemExit("--feishu-url 已退役；创作咨询素材候选固定从 Media Model v2 02A/02B 读取")
    text = args.text or ""
    if args.stdin:
        stdin_text = sys.stdin.read().strip()
        if stdin_text:
            text = stdin_text
    reject_social_theory_tags(text)
    if not text:
        raise SystemExit("consultation requires --text")
    return handle_creation_consultation_command(
        text,
        tenant_id=args.tenant_id,
        viral_url="",
        activity_url=args.activity_url,
        business_url=args.business_url,
        inspiration_url=args.inspiration_url,
        limit=args.limit,
        conversation_context=parse_json_arg(args.conversation_context_json, env_name="OPENCLAW_CONVERSATION_CONTEXT_JSON"),
    )


def run_shooting_execution(args: argparse.Namespace) -> dict[str, Any]:
    from selfmedia.creation.shooting_execution import handle_shooting_execution_command

    text = args.text or ""
    if args.stdin:
        stdin_text = sys.stdin.read().strip()
        if stdin_text:
            text = stdin_text
    reject_social_theory_tags(text)
    if not text:
        raise SystemExit("shooting-execution requires --text")
    return handle_shooting_execution_command(
        text,
        tenant_id=args.tenant_id,
        dry_run=args.dry_run,
        no_write=args.no_write,
        conversation_context=parse_json_arg(args.conversation_context_json, env_name="OPENCLAW_CONVERSATION_CONTEXT_JSON"),
    )


def run_shooting_backwash(args: argparse.Namespace) -> dict[str, Any]:
    from selfmedia.creation.backwash import handle_shooting_execution_backwash

    requirements = args.requirements or ""
    if args.stdin:
        stdin_text = sys.stdin.read().strip()
        if stdin_text:
            requirements = stdin_text
    if not args.doc_url or not requirements.strip():
        raise SystemExit("shooting-backwash requires --doc-url and --requirements")
    return handle_shooting_execution_backwash(
        args.doc_url,
        requirements,
        tenant_id=args.tenant_id,
    )


def run_media_review(args: argparse.Namespace) -> dict[str, Any]:
    from selfmedia.context import record_review_memory

    text = args.text or ""
    if args.stdin:
        stdin_text = sys.stdin.read().strip()
        if stdin_text:
            text = stdin_text
    reject_social_theory_tags(text)
    if not text:
        raise SystemExit("review requires --text or --stdin")
    result = record_review_memory(
        text,
        tenant_id=args.tenant_id,
        source=args.source or "selfmedia-cli",
    )
    result["ok"] = True
    return result


def run_data_review(args: argparse.Namespace) -> dict[str, Any]:
    from selfmedia.review import handle_data_review_command

    text = args.text or ""
    if args.stdin:
        stdin_text = sys.stdin.read().strip()
        if stdin_text:
            text = stdin_text
    reject_social_theory_tags(text)
    if not text:
        raise SystemExit("data-review requires --text or --stdin")
    return handle_data_review_command(
        text,
        tenant_id=args.tenant_id,
        attachment_paths=args.attachments or [],
        no_write=args.no_write,
        table_url=args.feishu_url,
        output_parent_node_token=args.parent_node_token,
        guide_url=args.guide_url,
        conversation_context=parse_json_arg(args.conversation_context_json, env_name="OPENCLAW_CONVERSATION_CONTEXT_JSON"),
    )


def run_media_context(args: argparse.Namespace) -> dict[str, Any]:
    from selfmedia.creation.field_contract import split_tags
    from selfmedia.context import build_media_context, format_media_context_reply

    context = build_media_context(
        tenant_id=args.tenant_id,
        platform=args.platform,
        account=args.account,
        track=args.track,
        topic=args.topic,
        keywords=split_tags(args.keywords or ""),
        limit=args.limit,
    )
    return {"ok": True, "context": context, "reply": format_media_context_reply(context)}


def run_part(args: argparse.Namespace) -> dict[str, Any]:
    load_default_env_files()
    module = args.part.lower().strip().replace("_", "-")
    module_aliases = {
        "content-ingest": "ingest",
        "ingest-content": "ingest",
        "viral-deconstruct": "deconstruct",
        "cookie": "cookies",
        "创作": "creation",
    }
    module = module_aliases.get(module, module)
    if module == "ingest":
        return run_content_ingest(args)
    if module == "deconstruct":
        return run_viral_deconstruct(args)
    if module == "cookies":
        return cookie_status()
    if module == "creation":
        return run_creation(args)
    raise SystemExit(f"unknown selfmedia module: {args.part}")


def account_enabled(fields: dict[str, Any]) -> bool:
    return any(
        feishu_bool(fields.get(name), default=False)
        for name in ACCOUNT_MONITOR_ENABLED_FIELDS
        if name in fields
    )


def account_from_record(record: dict[str, Any]) -> dict[str, Any]:
    fields = record.get("fields") or {}
    name = feishu_first_field(fields, ("账号名称", "账号", "名称", "account_name", "account", "博主"), default=record.get("record_id", ""))
    platform = feishu_first_field(fields, ("平台", "platform"), default="")
    urls = feishu_urls_from_fields(fields, ("近期作品链接", "作品链接", "监控链接", "链接", "URL", "urls", "主页链接", "首页链接"))
    if not platform and urls:
        platform = detect_platform(urls[0])
    return {
        "record_id": record.get("record_id", ""),
        "account_name": name,
        "platform": platform or "unknown",
        "enabled": account_enabled(fields),
        "urls": urls,
        "raw_fields": fields,
    }


def account_record_kind(record: dict[str, Any]) -> str:
    fields = record.get("fields") or {}
    if not isinstance(fields, dict):
        return "unknown"
    field_names = set(fields)
    if field_names & CREATOR_PROFILE_FIELD_MARKERS:
        return "creator_profile_v2"
    if field_names & ACCOUNT_MONITOR_LINK_FIELDS:
        return "account_monitor_v1"
    return "unknown"


def validate_account_monitor_records(records: list[dict[str, Any]]) -> None:
    profile_record_ids = [
        str(record.get("record_id") or "<unknown>")
        for record in records
        if account_record_kind(record) == "creator_profile_v2"
    ]
    if profile_record_ids:
        raise SystemExit(
            "daily-poll 仅支持 v1 账号监控表；检测到 v2 CreatorProfile 行，"
            "已拒绝写入，避免向画像表添加监控字段："
            + "、".join(profile_record_ids[:3])
        )
    if records and not any(account_record_kind(record) == "account_monitor_v1" for record in records):
        raise SystemExit(
            "daily-poll 无法确认这是 v1 账号监控表；至少一行需要包含近期作品链接、作品链接或监控链接字段。"
        )
    missing_enabled_record_ids = [
        str(record.get("record_id") or "<unknown>")
        for record in records
        if account_record_kind(record) == "account_monitor_v1"
        and not (set((record.get("fields") or {})) & ACCOUNT_MONITOR_ENABLED_FIELDS)
    ]
    if missing_enabled_record_ids:
        raise SystemExit(
            "daily-poll 账号监控表需要每行显式包含启用字段，已拒绝轮询："
            + "、".join(missing_enabled_record_ids[:3])
        )


def verify_schema(
    bitable_url: str,
    *,
    specs: dict[str, int] | None = None,
    token: str | None = None,
) -> dict[str, Any]:
    """Verify the account-monitor table fields before reading or writing records."""
    if not bitable_url.strip():
        raise ValueError("账号监控表 URL 不能为空")
    expected = specs or ACCOUNT_MONITOR_FIELD_SPECS
    app_token, table_id, access_token = feishu_bitable_refs(bitable_url, token)
    actual = feishu_field_types(app_token, table_id, access_token)
    missing = [name for name in expected if name not in actual]
    mismatched = [
        {"field": name, "expected_type": field_type, "actual_type": actual[name]}
        for name, field_type in expected.items()
        if name in actual and actual[name] != field_type
    ]
    return {
        "ok": not missing and not mismatched,
        "app_token": app_token,
        "table_id": table_id,
        "required_fields": len(expected),
        "actual_fields": len(actual),
        "missing_fields": missing,
        "mismatched_fields": mismatched,
    }


def require_valid_schema(monitor_url: str) -> dict[str, Any]:
    result = verify_schema(monitor_url)
    if result["ok"]:
        return result
    problems: list[str] = []
    if result["missing_fields"]:
        problems.append("缺少字段：" + "、".join(result["missing_fields"]))
    if result["mismatched_fields"]:
        problems.append(
            "类型不匹配："
            + "、".join(
                f"{item['field']}({item['actual_type']} != {item['expected_type']})"
                for item in result["mismatched_fields"]
            )
        )
    raise SystemExit("账号监控表 schema 校验失败；" + "；".join(problems))


def daily_poll_status_label(status: object) -> str:
    value = str(status or "").strip()
    return DAILY_POLL_STATUS_LABELS.get(value, "状态未知")


def daily_poll_decision_label(decision: object) -> str:
    return DAILY_POLL_DECISION_LABELS.get(str(decision or "").strip(), "待人工判断")


def user_visible_poll_error(exc: Exception) -> str:
    message = str(exc).lower()
    if "timeout" in message or "timed out" in message:
        return "轮询超时，请检查网络或平台登录状态。"
    if "cookie" in message or "login" in message or "登录" in message:
        return "平台登录状态异常，请更新登录凭据后重试。"
    return "轮询失败，请检查运行日志。"


def account_monitor_url(value: str) -> str:
    monitor_url = value or feishu_table_url_from_env(
        "FEISHU_ACCOUNT_MONITOR_URL",
        "FEISHU_SELFMEDIA_ACCOUNT_MONITOR_URL",
    )
    if not monitor_url:
        raise SystemExit("missing FEISHU_ACCOUNT_MONITOR_URL or --monitor-url")
    return monitor_url


def list_account_monitor_records(monitor_url: str, *, view_id: str) -> list[dict[str, Any]]:
    try:
        return feishu_list_records(monitor_url, view_id=view_id)
    except Exception as exc:
        LOGGER.warning("daily-poll could not read account monitor table", exc_info=True)
        raise SystemExit(f"无法读取账号监控表：{user_visible_poll_error(exc)}") from None


def update_account_monitor_record(monitor_url: str, record_id: str, fields: dict[str, Any]) -> None:
    try:
        feishu_update_record(
            monitor_url,
            record_id,
            fields,
            specs=ACCOUNT_MONITOR_FIELD_SPECS,
        )
    except Exception as exc:
        LOGGER.warning("daily-poll could not update account monitor record %s", record_id, exc_info=True)
        raise SystemExit(f"账号监控表状态写入失败：{user_visible_poll_error(exc)}") from None


def redacted_report_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): user_visible_poll_error(RuntimeError(str(item)))
            if str(key).lower() in {"error", "exception", "failure_reason", "stderr", "stdout", "traceback"}
            else redacted_report_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redacted_report_value(item) for item in value]
    if isinstance(value, str):
        return re.sub(r"(?<![\w.-])/(?:Users|home|private|tmp|var|opt)(?:/[^\s`'\"|<>()\[\]{}]*)?", "[本机路径已隐藏]", value)
    return value


def compact_daily_poll_comments(row: dict[str, Any]) -> list[str]:
    comments: list[str] = []
    for key in DAILY_POLL_DETAIL_COMMENT_KEYS:
        value = row.get(key)
        for item in value if isinstance(value, list) else [value]:
            if isinstance(item, dict):
                item = item.get("text") or item.get("comment") or item.get("content")
            text = str(item or "").strip()
            if text:
                comments.append(text[:240])
    return list(dict.fromkeys(comments))[:5]


def compact_daily_poll_detail(row: dict[str, Any], score: dict[str, Any]) -> dict[str, Any]:
    return {
        "互动数据": {
            "点赞": count_value(row, "like_count"),
            "收藏": count_value(row, "collect_count"),
            "评论": count_value(row, "comment_count"),
            "分享": count_value(row, "share_count"),
            "总互动": total_interactions(row),
        },
        "采集状态": daily_poll_status_label(row.get("health_status")),
        "建议": daily_poll_decision_label(score.get("decision")),
        "高价值评论原话": compact_daily_poll_comments(row),
    }


def account_summary(account: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    totals = {key: sum(count_value(row, key) for row in rows) for key in INTERACTION_KEYS}
    total = sum(totals.values())
    ok_count = sum(1 for row in rows if row.get("health_status") == "ok")
    status = "ok" if rows and ok_count == len(rows) else ("partial" if rows and ok_count else "missing")
    best = max(rows, key=total_interactions) if rows else {}
    return {
        "account_name": account["account_name"],
        "platform": account["platform"],
        "record_id": account["record_id"],
        "post_count": len(rows),
        "ok_count": ok_count,
        "overall_status": status,
        "total_interactions": total,
        "like_count": totals["like_count"],
        "collect_count": totals["collect_count"],
        "comment_count": totals["comment_count"],
        "share_count": totals["share_count"],
        "best_post_id": best.get("post_id", ""),
        "best_post_url": best.get("cleaned_url") or best.get("url") or "",
        "captured_at": now_iso(),
    }


def build_daily_report(
    accounts: list[dict[str, Any]],
    account_rows: dict[str, list[dict[str, Any]]],
    summaries: list[dict[str, Any]],
    errors: list[dict[str, str]],
) -> list[str]:
    lines = [
        "# 账号每日轮询",
        "",
        "| 账号 | 平台 | 作品数 | 状态 | 点赞 | 收藏 | 评论 | 分享 | 总互动 | 最佳作品链接 |",
        "| --- | --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for summary in sorted(summaries, key=lambda item: item["total_interactions"], reverse=True):
        lines.append(
            "| {account_name} | {platform} | {post_count} | {status} | {like_count} | {collect_count} | {comment_count} | {share_count} | {total_interactions} | {best_post_url} |".format(
                **redacted_report_value(summary),
                status=daily_poll_status_label(summary["overall_status"]),
            )
        )
    missing = [item for item in accounts if item["enabled"] and not item["urls"]]
    if missing:
        lines.extend(["", "## 缺少作品链接的账号", ""])
        for item in missing:
            lines.append(f"- {item['account_name']}：账号监控表需要填写 `近期作品链接` 或 `作品链接`")
    for account in accounts:
        rows = account_rows.get(account["record_id"], [])
        if not rows:
            continue
        lines.extend(["", f"## {account['account_name']}", ""])
        for row in sorted(rows, key=total_interactions, reverse=True):
            report_row = redacted_report_value(row)
            metrics = metric_summary(report_row)
            lines.append(
                "- 作品 {post_id}：总互动 {total}，点赞 {like}，收藏 {collect}，评论 {comment}，分享 {share}，状态 {status}，链接 {url}".format(
                    post_id=report_row.get("post_id", ""),
                    total=metrics["total_interactions"],
                    like=report_row.get("like_count"),
                    collect=report_row.get("collect_count"),
                    comment=report_row.get("comment_count"),
                    share=report_row.get("share_count"),
                    status=daily_poll_status_label(report_row.get("health_status", "")),
                    url=report_row.get("cleaned_url") or report_row.get("url") or "",
                )
            )
    if errors:
        lines.extend(["", "## 轮询失败", ""])
        for error in errors:
            lines.append(f"- {error['account_name']}：{error['error']}")
    return lines


def daily_poll(args: argparse.Namespace) -> dict[str, Any]:
    load_default_env_files()
    tenant_id = require_tenant_id(args.tenant_id)
    monitor_url = account_monitor_url(args.monitor_url)
    report_url = args.report_url or os.getenv("FEISHU_ACCOUNT_REPORT_URL", "").strip()
    require_feishu = bool(args.require_feishu or feishu_required_default())
    if require_feishu and not args.dry_run and not report_url:
        raise SystemExit("missing FEISHU_ACCOUNT_REPORT_URL or --report-url when --require-feishu is set")

    schema = require_valid_schema(monitor_url) if getattr(args, "verify_schema", False) else None
    records = list_account_monitor_records(monitor_url, view_id=args.view_id)
    validate_account_monitor_records(records)
    accounts = [account_from_record(record) for record in records]
    if args.limit:
        accounts = accounts[: args.limit]

    output_dir = MediaVault(tenant_id=tenant_id).root / "account_daily_runs"
    output_dir.mkdir(parents=True, exist_ok=True)
    account_rows: dict[str, list[dict[str, Any]]] = {}
    summaries: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for account in accounts:
        if not account["enabled"]:
            continue
        if not account["urls"]:
            errors.append({"account_name": account["account_name"], "error": "missing_urls"})
            if not args.dry_run:
                update_account_monitor_record(
                    monitor_url,
                    account["record_id"],
                    {
                        "最近运行时间": now_iso(),
                        "最近状态": daily_poll_status_label("missing_urls"),
                        "最近错误": "账号监控表需要填写近期作品链接/作品链接",
                    },
                )
            continue
        try:
            rows = refresh_posts(account["urls"])
            account_rows[account["record_id"]] = rows
            summary = account_summary(account, rows)
            summaries.append(summary)
            if not args.dry_run:
                _record_daily_poll_reviews(account, rows, tenant_id=tenant_id)
            if not args.dry_run:
                update_account_monitor_record(
                    monitor_url,
                    account["record_id"],
                    {
                        "最近运行时间": summary["captured_at"],
                        "最近状态": daily_poll_status_label(summary["overall_status"]),
                        "最近作品数": summary["post_count"],
                        "最近总互动": summary["total_interactions"],
                        "最近错误": "",
                        "最近日报摘要": f"{summary['post_count']} 条作品，总互动 {summary['total_interactions']}，最佳作品 {summary['best_post_id']}",
                    },
                )
        except Exception as exc:
            LOGGER.warning("daily-poll failed for account %s", account["record_id"], exc_info=True)
            message = user_visible_poll_error(exc)
            errors.append({"account_name": account["account_name"], "error": message})
            if not args.dry_run:
                update_account_monitor_record(
                    monitor_url,
                    account["record_id"],
                    {
                        "最近运行时间": now_iso(),
                        "最近状态": "error",
                        "最近错误": message[:500],
                    },
                )

    stamp = slug_time()
    json_path = output_dir / f"account_daily_{stamp}.json"
    md_path = output_dir / f"account_daily_{stamp}.md"
    payload = redacted_report_value({
        "tenant_id": tenant_id,
        "accounts": accounts,
        "summaries": summaries,
        "rows": account_rows,
        "errors": errors,
        "monitor_url": monitor_url,
        "report_url": report_url,
        "schema": schema,
    })
    write_json(json_path, payload)
    write_markdown(md_path, build_daily_report(accounts, account_rows, summaries, errors))

    feishu_records: list[dict[str, Any]] = []
    for account in accounts:
        rows = account_rows.get(account["record_id"], [])
        for row in rows:
            score = quality_score(row)
            fields = row_to_feishu_fields(
                "账号每日轮询",
                row,
                summary=f"{account['account_name']} 每日轮询；总互动 {total_interactions(row)}；评分 {score['overall_score']}",
                report_path=md_path.name,
                score=score["overall_score"],
                decision=score["decision"],
            )
            fields["状态"] = daily_poll_status_label(row.get("health_status"))
            if row.get("failure_reason"):
                fields["失败原因"] = user_visible_poll_error(RuntimeError(str(row["failure_reason"])))
            fields["决策"] = daily_poll_decision_label(score["decision"])
            fields["详情JSON"] = compact_daily_poll_detail(row, score)
            feishu_records.append(redacted_report_value(fields))
    record_ids: list[str] = []
    if not args.dry_run:
        try:
            record_ids = write_feishu_records(
                report_url,
                feishu_records,
                module="08 账号每日轮询",
                report_path=str(md_path),
                require=require_feishu,
            )
        except Exception as exc:
            LOGGER.warning("daily-poll could not write report records", exc_info=True)
            raise SystemExit(f"日报飞书写入失败：{user_visible_poll_error(exc)}") from None

    feishu_report_skipped = bool(not args.dry_run and feishu_records and not report_url)
    enabled_account_count = sum(1 for account in accounts if account["enabled"])
    polled_account_count = len(summaries)
    successful_summary_count = sum(1 for summary in summaries if summary["overall_status"] == "ok")
    summary_failure = successful_summary_count < polled_account_count
    if polled_account_count == 0:
        status = "ok_empty" if enabled_account_count == 0 and not errors else "error"
    elif errors or summary_failure or feishu_report_skipped:
        status = "partial" if successful_summary_count else "error"
    else:
        status = "ok"
    return {
        "ok": status == "ok",
        "json_path": str(json_path),
        "report_path": str(md_path),
        "account_count": len(accounts),
        "enabled_account_count": enabled_account_count,
        "polled_account_count": polled_account_count,
        "status": status,
        "completion_status": status,
        "record_ids": record_ids,
        "feishu": {
            "已写入": f"已写入 {len(record_ids)} 条飞书记录",
            "无记录": "无需写入飞书记录",
            "未配置": "未配置飞书日报表，未写入跨平台记录",
            "未写入": "已配置飞书日报表，但没有写入记录",
        }.get(
            "已写入"
            if record_ids
            else "无记录"
            if not feishu_records
            else "未配置"
            if not report_url
            else "未写入"
        ),
        "errors": errors,
    }


def _record_daily_poll_reviews(
    account: dict[str, Any],
    rows: list[dict[str, Any]],
    *,
    tenant_id: str,
) -> list[str]:
    """Persist bounded, successful polling evidence into the review memory."""
    from selfmedia.context import record_review_memory

    recorded: list[str] = []
    platform = str(account.get("platform") or "").strip()
    account_name = str(account.get("account_name") or "").strip()
    for row in rows:
        if str(row.get("health_status") or "").strip() not in {"ok", "partial"}:
            continue
        publish_url = str(row.get("url") or row.get("cleaned_url") or "").strip()
        if not publish_url:
            continue
        metric_labels = (
            ("点赞", "like_count"),
            ("收藏", "collect_count"),
            ("评论", "comment_count"),
            ("分享", "share_count"),
        )
        metrics = [
            f"{label}={row[key]}"
            for label, key in metric_labels
            if row.get(key) is not None
        ]
        comments = compact_daily_poll_comments(row)[:5]
        if not metrics and not comments:
            continue
        review_text = (
            f"【数据复盘】平台={platform} 账号={account_name} 主体=账号每日轮询 "
            f"发布链接={publish_url} 数据={' '.join(metrics)} "
            "结论=日报已采集作品互动数据，供后续复盘与创作参考"
        ).strip()
        result = record_review_memory(
            review_text,
            tenant_id=tenant_id,
            source="selfmedia:daily-poll",
            analysis={
                "top_comments": comments,
                "data_source": "account_daily_poll",
                "captured_at": row.get("captured_at") or "",
            },
        )
        recorded.append(str(result.get("review_id") or ""))
    return recorded


def _systemd_calendar(cron: str, *, timezone: str = "") -> str:
    """Translate the supported five-field daily cron form to OnCalendar."""
    fields = str(cron or "").split()
    if len(fields) != 5 or fields[2:] != ["*", "*", "*"]:
        raise SystemExit("--cron must use daily five-field form: '<minute> <hour> * * *'")
    minute, hour = fields[:2]
    if not (minute.isdigit() and hour.isdigit() and 0 <= int(minute) <= 59 and 0 <= int(hour) <= 23):
        raise SystemExit("--cron minute/hour must be numeric and within valid ranges")
    if timezone:
        try:
            ZoneInfo(timezone)
        except ZoneInfoNotFoundError as exc:
            raise SystemExit(f"--tz must be a valid IANA timezone: {timezone}") from exc
    return f"*-*-* {int(hour):02d}:{int(minute):02d}:00"


def install_cron(args: argparse.Namespace) -> dict[str, Any]:
    load_default_env_files()
    tenant_id = require_tenant_id(args.tenant_id)
    monitor_url = account_monitor_url(args.monitor_url)
    report_url = args.report_url or os.getenv("FEISHU_ACCOUNT_REPORT_URL", "").strip()
    if not report_url:
        raise SystemExit("missing FEISHU_ACCOUNT_REPORT_URL or --report-url; refusing to register an unreported daily poll")
    on_calendar = _systemd_calendar(args.cron, timezone=args.tz)
    command_args = [
        sys.executable,
        str(Path(__file__).resolve()),
        "daily-poll",
        "--tenant-id",
        tenant_id,
        "--require-feishu",
        "--report-url",
        report_url,
        "--monitor-url",
        monitor_url,
    ]
    unit_name = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(args.name or "selfmedia-account-daily-poll")).strip("-")
    if not unit_name:
        raise SystemExit("--name must contain at least one usable unit-name character")
    systemd_dir = Path(os.getenv("OPENCLAW_USER_SYSTEMD_DIR") or Path.home() / ".config/systemd/user")
    service_path = systemd_dir / f"{unit_name}.service"
    timer_path = systemd_dir / f"{unit_name}.timer"
    service_path.parent.mkdir(parents=True, exist_ok=True)
    service_path.write_text(
        "[Unit]\nDescription=SelfMedia tenant account daily poll\n\n[Service]\n"
        f"Type=oneshot\nWorkingDirectory={ROOT}\nExecStart={shlex.join(command_args)}\n",
        encoding="utf-8",
    )
    timer_path.write_text(
        "[Unit]\nDescription=SelfMedia tenant account daily poll timer\n\n[Timer]\n"
        f"OnCalendar={on_calendar} {args.tz}\nPersistent=true\nUnit={unit_name}.service\n\n[Install]\nWantedBy=timers.target\n",
        encoding="utf-8",
    )
    reload_result = run_command(["systemctl", "--user", "daemon-reload"], ROOT, timeout=60)
    if not reload_result["ok"]:
        return {**reload_result, "service_path": str(service_path), "timer_path": str(timer_path)}
    action = "disable --now" if args.disabled else "enable --now"
    action_args = ["systemctl", "--user", *action.split(), timer_path.name]
    result = run_command(action_args, ROOT, timeout=60)
    return {**result, "service_path": str(service_path), "timer_path": str(timer_path), "calendar": on_calendar}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Selfmedia module unified entrypoint.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="List routable selfmedia parts.")

    run = sub.add_parser("run", help="Run one selfmedia module.")
    run.add_argument("part", help="ingest | deconstruct | cookies | creation")
    run.add_argument("--urls", nargs="*", default=[])
    run.add_argument("--text", default="")
    run.add_argument("--stdin", action="store_true")
    run.add_argument("--feishu-url", default="")
    run.add_argument("--require-feishu", action="store_true")
    run.add_argument("--no-write", action="store_true", help="deconstruct/creation only: do not write Feishu.")
    run.add_argument("--partial", action="store_true", help="deconstruct only: run partial evidence extraction and force --no-write.")
    run.add_argument("--smoke", action="store_true", help="creation/deconstruct only: validate entrypoint parsing and no-write boundaries without LLM generation.")
    run.add_argument("--dry-run", action="store_true", help="creation only: read and match without creating Feishu docs/records.")
    run.add_argument("--activity-url", default="", help="creation only: activity bitable URL override.")
    run.add_argument("--business-url", default="", help="creation only: ID+Business bitable URL override.")
    run.add_argument("--inspiration-url", default="", help="creation only: creation inspiration bitable URL override.")
    run.add_argument("--creation-record-url", default="", help="creation only: creation record bitable URL override.")
    run.add_argument("--limit", type=int, default=300, help="creation only: max rows per source table.")
    run.add_argument("--ensure-schema", action="store_true", help="creation only: create missing v1 source-table fields before reading.")
    run.add_argument("--conversation-context-json", default="", help="creation only: recent Feishu/OpenClaw conversation context JSON.")
    run.add_argument("--timeout", type=int, default=10800)
    run.add_argument("--tenant-id", default="", help="Required Sub2API tenant id for private Media reads/writes.")

    poll = sub.add_parser("daily-poll", help="Read Feishu account monitor table, refresh recent post stats, write daily report.")
    poll.add_argument("--monitor-url", default="")
    poll.add_argument("--report-url", default="")
    poll.add_argument("--view-id", default="")
    poll.add_argument("--limit", type=int, default=0)
    poll.add_argument("--require-feishu", action="store_true", default=feishu_required_default())
    poll.add_argument("--dry-run", action="store_true")
    poll.add_argument("--verify-schema", action="store_true", help="校验账号监控表字段和类型后再轮询。")
    poll.add_argument("--tenant-id", required=True)

    shooting = sub.add_parser("shooting-execution", help="Create an executable shooting plan from a concrete creation target.")
    shooting.add_argument("--text", default="")
    shooting.add_argument("--stdin", action="store_true")
    shooting.add_argument("--dry-run", action="store_true")
    shooting.add_argument("--no-write", action="store_true")
    shooting.add_argument("--conversation-context-json", default="")
    shooting.add_argument("--tenant-id", required=True)

    backwash = sub.add_parser("shooting-backwash", help="Rewrite an existing shooting plan through its CreationRun and canonical renderer.")
    backwash.add_argument("--doc-url", required=True)
    backwash.add_argument("--requirements", default="")
    backwash.add_argument("--stdin", action="store_true")
    backwash.add_argument("--tenant-id", required=True)

    consultation = sub.add_parser("consultation", help="Answer creation strategy questions from Feishu tables and media memory.")
    consultation.add_argument("--text", default="")
    consultation.add_argument("--stdin", action="store_true")
    consultation.add_argument("--feishu-url", default="", help="已退役：素材候选固定从 Media Model v2 02A/02B 读取。")
    consultation.add_argument("--activity-url", default="")
    consultation.add_argument("--business-url", default="")
    consultation.add_argument("--inspiration-url", default="")
    consultation.add_argument("--limit", type=int, default=300)
    consultation.add_argument("--conversation-context-json", default="")
    consultation.add_argument("--tenant-id", required=True)

    review = sub.add_parser("review", help="Record a media post review into local account memory.")
    review.add_argument("--text", default="")
    review.add_argument("--stdin", action="store_true")
    review.add_argument("--source", default="")
    review.add_argument("--tenant-id", required=True)

    data_review = sub.add_parser("data-review", help="Analyze uploaded platform data screenshots and write Feishu data review outputs.")
    data_review.add_argument("--text", default="")
    data_review.add_argument("--stdin", action="store_true")
    data_review.add_argument("--attachment", dest="attachments", action="append", default=[])
    data_review.add_argument("--feishu-url", default="", help="Data review bitable URL override.")
    data_review.add_argument("--parent-node-token", default="", help="Review output wiki parent node token override.")
    data_review.add_argument("--guide-url", default="", help="Review guide/template document URL override.")
    data_review.add_argument("--conversation-context-json", default="")
    data_review.add_argument("--no-write", action="store_true")
    data_review.add_argument("--tenant-id", required=True)

    context = sub.add_parser("context", help="Load media account context that creation workflows will inject.")
    context.add_argument("--platform", default="")
    context.add_argument("--account", default="")
    context.add_argument("--track", default="")
    context.add_argument("--topic", default="")
    context.add_argument("--keywords", default="")
    context.add_argument("--limit", type=int, default=5)
    context.add_argument("--tenant-id", required=True)

    cron = sub.add_parser("install-cron", help="Register the daily Feishu account poll as a systemd user timer.")
    cron.add_argument("--name", default="selfmedia-account-daily-poll")
    cron.add_argument("--cron", default="0 8 * * *")
    cron.add_argument("--tz", default="Asia/Shanghai")
    cron.add_argument("--monitor-url", default="")
    cron.add_argument("--report-url", default="")
    cron.add_argument("--disabled", action="store_true")
    cron.add_argument("--tenant-id", required=True)
    return parser


def main() -> None:
    load_default_env_files()
    args = build_parser().parse_args()
    ensure_creation_runtime(args)
    reject_social_theory_tags(" ".join(sys.argv[1:]))
    if args.command == "list":
        print_json(
            {
                "parts": {
                    "ingest": "字段刷新/素材入口",
                    "deconstruct": "拆解素材，写飞书文档和多维表格；脚本/分镜交接创作或拍摄链路",
                    "cookies": "Cookie 状态检查",
                    "creation": "创作 Agent",
                },
                "daily_poll": "Feishu 账号监控表 -> 每日作品互动刷新 -> 账号日报",
                "shooting_execution": "【创作-拍摄执行】明确主题/场地/人物/参考 -> 现场拍摄执行单 -> 创作文档/CreationRun",
                "consultation": "基于爆款/活动/商务表和账号记忆回答创作咨询",
                "review": "发布后复盘 -> 本地账号画像/复盘记忆 -> 下次创作自动加载",
                "data_review": "【数据复盘】上传后台截图 -> 视觉识别数据 -> 写数据复盘表/复盘文档/账号记忆",
                "context": "查看某个平台/账号/主题会被注入的长期上下文",
            }
        )
        return
    if args.command == "run":
        print_json(run_part(args))
        return
    if args.command == "daily-poll":
        print_json(daily_poll(args))
        return
    if args.command == "shooting-execution":
        print_json(run_shooting_execution(args))
        return
    if args.command == "shooting-backwash":
        print_json(run_shooting_backwash(args))
        return
    if args.command == "consultation":
        print_json(run_creation_consultation(args))
        return
    if args.command == "review":
        print_json(run_media_review(args))
        return
    if args.command == "data-review":
        print_json(run_data_review(args))
        return
    if args.command == "context":
        print_json(run_media_context(args))
        return
    if args.command == "install-cron":
        print_json(install_cron(args))
        return


if __name__ == "__main__":
    main()
