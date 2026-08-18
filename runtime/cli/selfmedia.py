from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = Path(__file__).resolve().parents[2]
try:
    sys.path.remove(str(SCRIPT_DIR))
except ValueError:
    pass
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

MEDIA_CREATION_RUNTIME_PYTHON = Path(os.getenv("SELFMEDIA_RUNTIME_PYTHON", sys.executable))
CREATION_RUNTIME_COMMANDS = {"consultation", "shooting-execution", "shooting-backwash"}
CREATION_RUNTIME_RUN_PARTS = {"creation", "创作", "deconstruct", "拆解"}

from common.social_runtime import (  # noqa: E402
    INTERACTION_KEYS,
    count_value,
    detect_platform,
    extract_urls,
    feishu_bool,
    feishu_first_field,
    feishu_list_records,
    feishu_status_message,
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
from common.bot_llm_config import bot_runtime

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
    if any(name in fields for name in ("启用", "是否启用", "监控", "enabled")):
        return any(feishu_bool(fields.get(name), default=True) for name in ("启用", "是否启用", "监控", "enabled") if name in fields)
    return True


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


def build_daily_report(accounts: list[dict[str, Any]], account_rows: dict[str, list[dict[str, Any]]], summaries: list[dict[str, Any]]) -> list[str]:
    lines = [
        "# 账号每日轮询",
        "",
        "| 账号 | 平台 | 作品数 | 状态 | 点赞 | 收藏 | 评论 | 分享 | 总互动 | 最佳作品 |",
        "| --- | --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for summary in sorted(summaries, key=lambda item: item["total_interactions"], reverse=True):
        lines.append(
            "| {account_name} | {platform} | {post_count} | {overall_status} | {like_count} | {collect_count} | {comment_count} | {share_count} | {total_interactions} | {best_post_url} |".format(
                **summary
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
            metrics = metric_summary(row)
            lines.append(
                "- {post_id} total={total} like={like} collect={collect} comment={comment} share={share} status={status} {url}".format(
                    post_id=row.get("post_id", ""),
                    total=metrics["total_interactions"],
                    like=row.get("like_count"),
                    collect=row.get("collect_count"),
                    comment=row.get("comment_count"),
                    share=row.get("share_count"),
                    status=row.get("health_status", ""),
                    url=row.get("cleaned_url") or row.get("url") or "",
                )
            )
    return lines


def daily_poll(args: argparse.Namespace) -> dict[str, Any]:
    load_default_env_files()
    monitor_url = args.monitor_url or feishu_table_url_from_env(
        "MEDIA_OS_CREATOR_PROFILES_V2_URL",
        "FEISHU_ACCOUNT_MONITOR_URL",
        "FEISHU_SELFMEDIA_ACCOUNT_MONITOR_URL",
    )
    report_url = args.report_url or ""
    if not monitor_url:
        raise SystemExit("missing MEDIA_OS_CREATOR_PROFILES_V2_URL or --monitor-url")

    records = feishu_list_records(monitor_url, view_id=args.view_id)
    accounts = [account_from_record(record) for record in records]
    if args.limit:
        accounts = accounts[: args.limit]

    output_dir = ROOT / "data" / "media_vault" / "account_daily_runs"
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
                feishu_update_record(
                    monitor_url,
                    account["record_id"],
                    {
                        "最近运行时间": now_iso(),
                        "最近状态": "missing_urls",
                        "最近错误": "账号监控表需要填写近期作品链接/作品链接",
                    },
                    specs=ACCOUNT_MONITOR_FIELD_SPECS,
                )
            continue
        try:
            rows = refresh_posts(account["urls"])
            account_rows[account["record_id"]] = rows
            summary = account_summary(account, rows)
            summaries.append(summary)
            if not args.dry_run:
                feishu_update_record(
                    monitor_url,
                    account["record_id"],
                    {
                        "最近运行时间": summary["captured_at"],
                        "最近状态": summary["overall_status"],
                        "最近作品数": summary["post_count"],
                        "最近总互动": summary["total_interactions"],
                        "最近错误": "",
                        "最近日报摘要": f"{summary['post_count']} 条作品，总互动 {summary['total_interactions']}，最佳作品 {summary['best_post_id']}",
                    },
                    specs=ACCOUNT_MONITOR_FIELD_SPECS,
                )
        except Exception as exc:
            message = str(exc)
            errors.append({"account_name": account["account_name"], "error": message})
            if not args.dry_run:
                feishu_update_record(
                    monitor_url,
                    account["record_id"],
                    {
                        "最近运行时间": now_iso(),
                        "最近状态": "error",
                        "最近错误": message[:500],
                    },
                    specs=ACCOUNT_MONITOR_FIELD_SPECS,
                )

    stamp = slug_time()
    json_path = output_dir / f"account_daily_{stamp}.json"
    md_path = output_dir / f"account_daily_{stamp}.md"
    payload = {
        "accounts": accounts,
        "summaries": summaries,
        "rows": account_rows,
        "errors": errors,
        "monitor_url": monitor_url,
        "report_url": report_url,
    }
    write_json(json_path, payload)
    write_markdown(md_path, build_daily_report(accounts, account_rows, summaries))

    feishu_records: list[dict[str, Any]] = []
    for account in accounts:
        rows = account_rows.get(account["record_id"], [])
        for row in rows:
            score = quality_score(row)
            fields = row_to_feishu_fields(
                "账号每日轮询",
                row,
                summary=f"{account['account_name']} daily; total={total_interactions(row)}; score={score['overall_score']}",
                report_path=str(md_path),
                score=score["overall_score"],
                decision=score["decision"],
            )
            fields["详情JSON"] = {"account": account, "row": row, "score": score}
            feishu_records.append(fields)
    record_ids: list[str] = []
    if not args.dry_run:
        record_ids = write_feishu_records(
            report_url,
            feishu_records,
            module="08 账号每日轮询",
            report_path=str(md_path),
            require=args.require_feishu,
        )

    return {
        "ok": not errors,
        "json_path": str(json_path),
        "report_path": str(md_path),
        "account_count": len(accounts),
        "polled_account_count": len(summaries),
        "record_ids": record_ids,
        "feishu": feishu_status_message(record_ids, report_url, len(feishu_records)),
        "errors": errors,
    }


def install_cron(args: argparse.Namespace) -> dict[str, Any]:
    command = "/home/ubuntu/openclaw-agents/media/scripts/selfmedia.py daily-poll --require-feishu"
    if args.monitor_url:
        command += f" --monitor-url {args.monitor_url!r}"
    if args.report_url:
        command += f" --report-url {args.report_url!r}"
    runtime = bot_runtime("media")
    cron_command = [
        runtime.bin,
        "cron",
        "add",
        "--name",
        args.name,
        "--agent",
        runtime.agent,
        "--cron",
        args.cron,
        "--tz",
        args.tz,
        "--session",
        "isolated",
        "--tools",
        "exec",
        "--timeout-seconds",
        str(args.timeout_seconds),
        "--expect-final",
        "--no-deliver",
        "--message",
        f"请执行这个本机自媒体每日轮询命令，并只返回飞书写入结果、失败账号和阻塞点：\n\n{command}",
        "--json",
    ]
    if args.disabled:
        cron_command.append("--disabled")
    return run_command(cron_command, ROOT, timeout=60)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="OpenClaw bridge for /home/ubuntu/selfmedia-tools readable modules.")
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
    poll.add_argument("--require-feishu", action="store_true")
    poll.add_argument("--dry-run", action="store_true")

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

    shooting = sub.add_parser("shooting-execution", help="Create an executable shooting plan from a concrete creation target.")
    shooting.add_argument("--text", default="")
    shooting.add_argument("--stdin", action="store_true")
    shooting.add_argument("--dry-run", action="store_true")
    shooting.add_argument("--no-write", action="store_true")
    shooting.add_argument("--conversation-context-json", default="")

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

    cron = sub.add_parser("install-cron", help="Register the daily Feishu account poll through OpenClaw cron.")
    cron.add_argument("--name", default="selfmedia-account-daily-poll")
    cron.add_argument("--cron", default="0 8 * * *")
    cron.add_argument("--tz", default="Asia/Shanghai")
    cron.add_argument("--timeout-seconds", type=int, default=10800)
    cron.add_argument("--monitor-url", default="")
    cron.add_argument("--report-url", default="")
    cron.add_argument("--disabled", action="store_true")
    return parser


def main() -> None:
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
    if args.command == "shooting-execution":
        print_json(run_shooting_execution(args))
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
