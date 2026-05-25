from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from common.social_runtime import (  # noqa: E402
    INTERACTION_KEYS,
    count_value,
    detect_platform,
    ensure_paths,
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
DEPRECATED_SOCIAL_THEORY_TAGS = ("/风控量表",)
SLASH_THEORY_RE = re.compile(r"/([\w\u4e00-\u9fff-]+)")
THEORY_TAG_SUFFIXES = ("进行分析", "来分析", "分析一下", "分析")


def clean_slash_theory_tag(value: str) -> str:
    tag = value.strip().strip("/")
    for suffix in THEORY_TAG_SUFFIXES:
        if tag.endswith(suffix) and len(tag) > len(suffix):
            tag = tag[: -len(suffix)]
            break
    return f"/{tag.strip()}" if tag.strip() else ""


PART_DIRS = {
    "viral-radar": ROOT / "05-detect-viral-radar",
    "comment-topics": ROOT / "06-mine-comment-topics",
    "viral-structures": ROOT / "07-index-viral-structures",
    "account-competitors": ROOT / "08-report-account-competitors",
    "material-quality": ROOT / "09-score-material-quality",
    "field-health": ROOT / "10-diagnose-field-health",
}

PART_MODULE_NAMES = {
    "viral-radar": "05 爆款雷达",
    "comment-topics": "06 高赞评论选题池",
    "viral-structures": "07 爆款结构数据库",
    "account-competitors": "08 账号竞品周报",
    "material-quality": "09 素材入库质量评分",
    "field-health": "10 字段健康诊断",
    "creation": "11 创作 Agent",
}

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
    return [tag for tag in (*DEPRECATED_SOCIAL_THEORY_TAGS, *SOCIAL_THEORY_TAGS) if tag in slash_tags]


def reject_social_theory_tags(text: str) -> None:
    matched = social_theory_matches(text)
    if matched:
        if any(tag in DEPRECATED_SOCIAL_THEORY_TAGS for tag in matched):
            raise SystemExit(
                "社交理论旧入口已废弃，selfmedia/爆款入口拒绝执行，不做入口映射："
                + "、".join(tag for tag in matched if tag in DEPRECATED_SOCIAL_THEORY_TAGS)
            )
        raise SystemExit(
            "社交理论标签只能由 social bot 调用，selfmedia/爆款入口拒绝执行："
            + "、".join(matched)
        )


def run_command(command: list[str], cwd: Path, timeout: int = 1800) -> dict[str, Any]:
    completed = subprocess.run(command, cwd=str(cwd), text=True, capture_output=True, timeout=timeout, check=False)
    return {
        "ok": completed.returncode == 0,
        "returncode": completed.returncode,
        "command": command,
        "cwd": str(cwd),
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }


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
            ROOT / "04-manage-platform-cookies" / "private" / "douyin-cookies.json",
            ROOT / "01-ingest-content-flow" / "private" / "douyin-cookies.json",
            Path(os.getenv("DOUYIN_COOKIES_JSON_PATH", "")),
        ],
        "xiaohongshu": [
            ROOT / "04-manage-platform-cookies" / "private" / "xiaohongshu-cookies.json",
            ROOT / "01-ingest-content-flow" / "private" / "xiaohongshu-cookies.json",
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
    return {"ok": all(row.get("health_status") == "ok" for row in rows), "module": "01-ingest-content-flow", "mode": "stats", "rows": rows}


def run_viral_deconstruct(args: argparse.Namespace) -> dict[str, Any]:
    text = args.text or " ".join(args.urls or [])
    if args.stdin:
        stdin_text = sys.stdin.read().strip()
        if stdin_text:
            text = stdin_text
    reject_social_theory_tags(text)
    if not text:
        raise SystemExit("deconstruct requires --text or --urls text")
    python = ROOT / "03-deconstruct-viral-content" / ".venv" / "bin" / "python"
    if not python.exists():
        python = Path(sys.executable)
    command = [str(python), "-m", "src.cli", text]
    if args.feishu_url:
        command.extend(["--feishu-url", args.feishu_url])
    if args.no_write:
        command.append("--no-write")
    return run_command(command, ROOT / "03-deconstruct-viral-content", timeout=args.timeout)


def run_creation(args: argparse.Namespace) -> dict[str, Any]:
    from tools.creation.workflow import handle_creation_command

    text = args.text or " ".join(args.urls or [])
    if args.stdin:
        stdin_text = sys.stdin.read().strip()
        if stdin_text:
            text = stdin_text
    reject_social_theory_tags(text)
    if not text:
        raise SystemExit("creation requires --text")
    return handle_creation_command(
        text,
        dry_run=args.dry_run,
        no_write=args.no_write,
        viral_url=args.feishu_url,
        activity_url=args.activity_url,
        business_url=args.business_url,
        inspiration_url=args.inspiration_url,
        creation_record_url=args.creation_record_url,
        limit=args.limit,
        ensure_schema=args.ensure_schema,
        conversation_context=parse_json_arg(args.conversation_context_json, env_name="OPENCLAW_CONVERSATION_CONTEXT_JSON"),
    )


def run_creation_consultation(args: argparse.Namespace) -> dict[str, Any]:
    from tools.creation.consultation import handle_creation_consultation_command

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
        viral_url=args.feishu_url,
        activity_url=args.activity_url,
        business_url=args.business_url,
        inspiration_url=args.inspiration_url,
        limit=args.limit,
        conversation_context=parse_json_arg(args.conversation_context_json, env_name="OPENCLAW_CONVERSATION_CONTEXT_JSON"),
    )


def run_creation_inspiration(args: argparse.Namespace) -> dict[str, Any]:
    text = args.text or ""
    if args.stdin:
        stdin_text = sys.stdin.read().strip()
        if stdin_text:
            text = stdin_text
    reject_social_theory_tags(text)
    if not text and not args.attachments:
        raise SystemExit("creation-inspiration requires --text or --attachment")
    python = ROOT / "03-deconstruct-viral-content" / ".venv" / "bin" / "python"
    if not python.exists():
        python = Path(sys.executable)
    command = [
        str(python),
        "-m",
        "tools.creation_inspiration",
        "--text",
        text,
    ]
    for path in args.attachments or []:
        command.extend(["--attachment", path])
    if args.feishu_url:
        command.extend(["--feishu-url", args.feishu_url])
    if args.no_write:
        command.append("--no-write")
    if conversation_context_json := conversation_context_json_arg(args.conversation_context_json):
        command.extend(["--conversation-context-json", conversation_context_json])
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{ROOT}:{env.get('PYTHONPATH', '')}".rstrip(":")
    completed = subprocess.run(command, cwd=str(ROOT), text=True, capture_output=True, timeout=1860, check=False, env=env)
    if completed.returncode != 0:
        return {
            "ok": False,
            "returncode": completed.returncode,
            "command": command,
            "stdout": completed.stdout.strip(),
            "stderr": completed.stderr.strip(),
            "reply": (completed.stderr.strip() or completed.stdout.strip() or "【创作-灵感】执行失败")[-3000:],
        }
    try:
        return json.loads(completed.stdout.strip() or "{}")
    except json.JSONDecodeError:
        return {"ok": False, "stdout": completed.stdout.strip(), "stderr": completed.stderr.strip(), "reply": "【创作-灵感】返回了非 JSON 输出"}


def run_material_creation(args: argparse.Namespace) -> dict[str, Any]:
    python = ROOT / "03-deconstruct-viral-content" / ".venv" / "bin" / "python"
    if not python.exists():
        python = Path(sys.executable)
    command = [
        str(python),
        "-m",
        "tools.material_creation.cli",
        "--text",
        args.text,
    ]
    for path in args.attachments or []:
        command.extend(["--attachment", path])
    if args.dry_run:
        command.append("--dry-run")
    if args.no_write:
        command.append("--no-write")
    if args.creation_record_url:
        command.extend(["--creation-record-url", args.creation_record_url])
    if conversation_context_json := conversation_context_json_arg(args.conversation_context_json):
        command.extend(["--conversation-context-json", conversation_context_json])
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{ROOT}:{env.get('PYTHONPATH', '')}".rstrip(":")
    completed = subprocess.run(command, cwd=str(ROOT), text=True, capture_output=True, timeout=1860, check=False, env=env)
    if completed.returncode != 0:
        return {
            "ok": False,
            "returncode": completed.returncode,
            "command": command,
            "stdout": completed.stdout.strip(),
            "stderr": completed.stderr.strip(),
            "reply": (completed.stderr.strip() or completed.stdout.strip() or "【素材创作】执行失败")[-3000:],
        }
    try:
        return json.loads(completed.stdout.strip() or "{}")
    except json.JSONDecodeError:
        return {"ok": False, "stdout": completed.stdout.strip(), "stderr": completed.stderr.strip(), "reply": "【素材创作】返回了非 JSON 输出"}


def run_media_review(args: argparse.Namespace) -> dict[str, Any]:
    from tools.media_context import record_review_memory

    text = args.text or ""
    if args.stdin:
        stdin_text = sys.stdin.read().strip()
        if stdin_text:
            text = stdin_text
    reject_social_theory_tags(text)
    if not text:
        raise SystemExit("review requires --text or --stdin")
    result = record_review_memory(text, source=args.source or "selfmedia-cli")
    result["ok"] = True
    return result


def run_data_review(args: argparse.Namespace) -> dict[str, Any]:
    from tools.data_review import handle_data_review_command

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
        attachment_paths=args.attachments or [],
        no_write=args.no_write,
        table_url=args.feishu_url,
        output_parent_node_token=args.parent_node_token,
        guide_url=args.guide_url,
        conversation_context=parse_json_arg(args.conversation_context_json, env_name="OPENCLAW_CONVERSATION_CONTEXT_JSON"),
    )


def run_media_context(args: argparse.Namespace) -> dict[str, Any]:
    from tools.creation.field_contract import split_tags
    from tools.media_context import build_media_context, format_media_context_reply

    context = build_media_context(
        platform=args.platform,
        account=args.account,
        track=args.track,
        topic=args.topic,
        keywords=split_tags(args.keywords or ""),
        limit=args.limit,
    )
    return {"ok": True, "context": context, "reply": format_media_context_reply(context)}


def run_cli_module(module: str, args: argparse.Namespace) -> dict[str, Any]:
    urls = collect_urls(args)
    part_dir = PART_DIRS[module]
    command = [sys.executable, "cli.py", "--urls", *urls]
    if module == "account-competitors":
        command.extend(["--account", args.account or "openclaw"])
    if args.feishu_url:
        command.extend(["--feishu-url", args.feishu_url])
    if args.require_feishu:
        command.append("--require-feishu")
    return run_command(command, part_dir, timeout=args.timeout)


def run_part(args: argparse.Namespace) -> dict[str, Any]:
    load_default_env_files()
    module = args.part.lower().strip().replace("_", "-")
    module_aliases = {
        "01-ingest-content-flow": "ingest",
        "content-ingest": "ingest",
        "ingest-content": "ingest",
        "02-extract-music-media": "music-media",
        "03-deconstruct-viral-content": "deconstruct",
        "viral-deconstruct": "deconstruct",
        "04-manage-platform-cookies": "cookies",
        "cookie": "cookies",
        "05-detect-viral-radar": "viral-radar",
        "radar": "viral-radar",
        "06-mine-comment-topics": "comment-topics",
        "comments": "comment-topics",
        "07-index-viral-structures": "viral-structures",
        "structures": "viral-structures",
        "08-report-account-competitors": "account-competitors",
        "competitors": "account-competitors",
        "09-score-material-quality": "material-quality",
        "quality": "material-quality",
        "10-diagnose-field-health": "field-health",
        "health": "field-health",
        "11-create-content": "creation",
        "创作": "creation",
    }
    module = module_aliases.get(module, module)
    if module == "ingest":
        return run_content_ingest(args)
    if module == "deconstruct":
        return run_viral_deconstruct(args)
    if module == "cookies":
        return cookie_status()
    if module in PART_DIRS:
        return run_cli_module(module, args)
    if module == "music-media":
        raise SystemExit("music-media has its own UI/CLI and is not exposed through this OpenClaw run bridge")
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
        "MEDIA_OS_CREATOR_PROFILES_URL",
        "FEISHU_ACCOUNT_MONITOR_URL",
        "FEISHU_SELFMEDIA_ACCOUNT_MONITOR_URL",
    )
    report_url = args.report_url or feishu_table_url_from_env(
        "MEDIA_OS_VIRAL_URL",
        "FEISHU_ACCOUNT_REPORT_URL",
        "FEISHU_SELFMEDIA_ACCOUNT_REPORT_URL",
        "FEISHU_BITABLE_URL",
    )
    if not monitor_url:
        raise SystemExit("missing MEDIA_OS_CREATOR_PROFILES_URL or --monitor-url")

    records = feishu_list_records(monitor_url, view_id=args.view_id)
    accounts = [account_from_record(record) for record in records]
    if args.limit:
        accounts = accounts[: args.limit]

    paths = ensure_paths(ROOT / "08-report-account-competitors", "account_weekly.sqlite")
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
    json_path = paths.output_dir / f"account_daily_{stamp}.json"
    md_path = paths.output_dir / f"account_daily_{stamp}.md"
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
                "08 账号每日轮询",
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
    run.add_argument("part", help="ingest | deconstruct | cookies | viral-radar | comment-topics | viral-structures | account-competitors | material-quality | field-health | creation")
    run.add_argument("--urls", nargs="*", default=[])
    run.add_argument("--text", default="")
    run.add_argument("--stdin", action="store_true")
    run.add_argument("--feishu-url", default="")
    run.add_argument("--require-feishu", action="store_true")
    run.add_argument("--no-write", action="store_true", help="deconstruct/creation only: do not write Feishu.")
    run.add_argument("--dry-run", action="store_true", help="creation only: read and match without creating Feishu docs/records.")
    run.add_argument("--activity-url", default="", help="creation only: activity bitable URL override.")
    run.add_argument("--business-url", default="", help="creation only: ID+Business bitable URL override.")
    run.add_argument("--inspiration-url", default="", help="creation only: creation inspiration bitable URL override.")
    run.add_argument("--creation-record-url", default="", help="creation only: creation record bitable URL override.")
    run.add_argument("--limit", type=int, default=300, help="creation only: max rows per source table.")
    run.add_argument("--ensure-schema", action="store_true", help="creation only: create missing v1 source-table fields before reading.")
    run.add_argument("--conversation-context-json", default="", help="creation only: recent Feishu/OpenClaw conversation context JSON.")
    run.add_argument("--account", default="", help="account-competitors account label.")
    run.add_argument("--timeout", type=int, default=1800)

    poll = sub.add_parser("daily-poll", help="Read Feishu account monitor table, refresh recent post stats, write daily report.")
    poll.add_argument("--monitor-url", default="")
    poll.add_argument("--report-url", default="")
    poll.add_argument("--view-id", default="")
    poll.add_argument("--limit", type=int, default=0)
    poll.add_argument("--require-feishu", action="store_true")
    poll.add_argument("--dry-run", action="store_true")

    material = sub.add_parser("material-creation", help="Create positioning analysis and draft from uploaded video/image attachments.")
    material.add_argument("--text", required=True)
    material.add_argument("--attachment", dest="attachments", action="append", default=[])
    material.add_argument("--dry-run", action="store_true")
    material.add_argument("--no-write", action="store_true")
    material.add_argument("--creation-record-url", default="")
    material.add_argument("--conversation-context-json", default="")

    consultation = sub.add_parser("consultation", help="Answer creation strategy questions from Feishu tables and media memory.")
    consultation.add_argument("--text", default="")
    consultation.add_argument("--stdin", action="store_true")
    consultation.add_argument("--feishu-url", default="", help="viral/content bitable URL override.")
    consultation.add_argument("--activity-url", default="")
    consultation.add_argument("--business-url", default="")
    consultation.add_argument("--inspiration-url", default="")
    consultation.add_argument("--limit", type=int, default=300)
    consultation.add_argument("--conversation-context-json", default="")

    creation_inspiration = sub.add_parser("creation-inspiration", help="Analyze creative inspiration from text/images and write the inspiration table.")
    creation_inspiration.add_argument("--text", default="")
    creation_inspiration.add_argument("--stdin", action="store_true")
    creation_inspiration.add_argument("--attachment", dest="attachments", action="append", default=[])
    creation_inspiration.add_argument("--feishu-url", default="")
    creation_inspiration.add_argument("--conversation-context-json", default="")
    creation_inspiration.add_argument("--no-write", action="store_true")

    review = sub.add_parser("review", help="Record a media post review into local account memory.")
    review.add_argument("--text", default="")
    review.add_argument("--stdin", action="store_true")
    review.add_argument("--source", default="")

    data_review = sub.add_parser("data-review", help="Analyze uploaded platform data screenshots and write Feishu data review outputs.")
    data_review.add_argument("--text", default="")
    data_review.add_argument("--stdin", action="store_true")
    data_review.add_argument("--attachment", dest="attachments", action="append", default=[])
    data_review.add_argument("--feishu-url", default="", help="Data review bitable URL override.")
    data_review.add_argument("--parent-node-token", default="", help="Review output wiki parent node token override.")
    data_review.add_argument("--guide-url", default="", help="Review guide/template document URL override.")
    data_review.add_argument("--conversation-context-json", default="")
    data_review.add_argument("--no-write", action="store_true")

    context = sub.add_parser("context", help="Load media account context that creation workflows will inject.")
    context.add_argument("--platform", default="")
    context.add_argument("--account", default="")
    context.add_argument("--track", default="")
    context.add_argument("--topic", default="")
    context.add_argument("--keywords", default="")
    context.add_argument("--limit", type=int, default=5)

    cron = sub.add_parser("install-cron", help="Register the daily Feishu account poll through OpenClaw cron.")
    cron.add_argument("--name", default="selfmedia-account-daily-poll")
    cron.add_argument("--cron", default="0 8 * * *")
    cron.add_argument("--tz", default="Asia/Shanghai")
    cron.add_argument("--timeout-seconds", type=int, default=1800)
    cron.add_argument("--monitor-url", default="")
    cron.add_argument("--report-url", default="")
    cron.add_argument("--disabled", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    reject_social_theory_tags(" ".join(sys.argv[1:]))
    if args.command == "list":
        print_json(
            {
                "parts": {
                    "ingest": "01 字段刷新/素材入口",
                    "deconstruct": "03 拆解/创作-再创，写飞书文档和多维表格",
                    "cookies": "04 Cookie 状态检查",
                    **PART_MODULE_NAMES,
                },
                "daily_poll": "Feishu 账号监控表 -> 每日作品互动刷新 -> 08 账号日报",
                "material_creation": "上传视频/图文附件 -> 定位分析 -> 创作初稿 -> 创作文档/作品档案/账号监控",
                "consultation": "基于爆款/活动/商务表和账号记忆回答创作咨询",
                "creation_inspiration": "【创作-灵感】文本/照片/视频 -> 灵感落盘 -> 创作-再创方向 -> 评分 -> 写指定灵感表",
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
    if args.command == "material-creation":
        print_json(run_material_creation(args))
        return
    if args.command == "consultation":
        print_json(run_creation_consultation(args))
        return
    if args.command == "creation-inspiration":
        print_json(run_creation_inspiration(args))
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
