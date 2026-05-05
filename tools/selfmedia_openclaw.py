from __future__ import annotations

import argparse
import json
import os
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


PART_DIRS = {
    "part4": ROOT / "Part4" / "viral-radar",
    "part5": ROOT / "Part5" / "comment-topic-pool",
    "part6": ROOT / "Part6" / "viral-structure-db",
    "part7": ROOT / "Part7" / "account-competitor-weekly",
    "part8": ROOT / "Part8" / "material-quality-score",
    "part9": ROOT / "Part9" / "field-health-diagnostics",
}

PART_MODULE_NAMES = {
    "part4": "Part4 爆款雷达",
    "part5": "Part5 高赞评论选题池",
    "part6": "Part6 爆款结构数据库",
    "part7": "Part7 账号竞品周报",
    "part8": "Part8 素材入库质量评分",
    "part9": "Part9 字段健康诊断",
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


def part3_status() -> dict[str, Any]:
    candidates = {
        "douyin": [
            ROOT / "part3" / "private" / "douyin-cookies.json",
            ROOT / "Part1" / "content-flow" / "private" / "douyin-cookies.json",
            Path(os.getenv("DOUYIN_COOKIES_JSON_PATH", "")),
        ],
        "xiaohongshu": [
            ROOT / "part3" / "private" / "xiaohongshu-cookies.json",
            ROOT / "Part1" / "content-flow" / "private" / "xiaohongshu-cookies.json",
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


def run_part1(args: argparse.Namespace) -> dict[str, Any]:
    urls = collect_urls(args)
    rows = refresh_posts(urls)
    return {"ok": all(row.get("health_status") == "ok" for row in rows), "part": "part1", "mode": "stats", "rows": rows}


def run_part2(args: argparse.Namespace) -> dict[str, Any]:
    text = args.text or " ".join(args.urls or [])
    if args.stdin:
        stdin_text = sys.stdin.read().strip()
        if stdin_text:
            text = stdin_text
    if not text:
        raise SystemExit("part2 requires --text or --urls text")
    python = ROOT / "Part2" / "viral-deconstruct" / ".venv" / "bin" / "python"
    if not python.exists():
        python = Path(sys.executable)
    command = [str(python), "-m", "src.cli", text]
    if args.feishu_url:
        command.extend(["--feishu-url", args.feishu_url])
    if args.no_write:
        command.append("--no-write")
    return run_command(command, ROOT / "Part2" / "viral-deconstruct", timeout=args.timeout)


def run_cli_part(part: str, args: argparse.Namespace) -> dict[str, Any]:
    urls = collect_urls(args)
    part_dir = PART_DIRS[part]
    command = [sys.executable, "cli.py", "--urls", *urls]
    if part == "part7":
        command.extend(["--account", args.account or "openclaw"])
    if args.feishu_url:
        command.extend(["--feishu-url", args.feishu_url])
    if args.require_feishu:
        command.append("--require-feishu")
    return run_command(command, part_dir, timeout=args.timeout)


def run_part(args: argparse.Namespace) -> dict[str, Any]:
    load_default_env_files()
    part = args.part.lower().replace("-", "")
    if part in {"part1", "p1"}:
        return run_part1(args)
    if part in {"part2", "p2"}:
        return run_part2(args)
    if part in {"part3", "p3"}:
        return part3_status()
    if part in {"part4", "p4"}:
        return run_cli_part("part4", args)
    if part in {"part5", "p5"}:
        return run_cli_part("part5", args)
    if part in {"part6", "p6"}:
        return run_cli_part("part6", args)
    if part in {"part7", "p7"}:
        return run_cli_part("part7", args)
    if part in {"part8", "p8"}:
        return run_cli_part("part8", args)
    if part in {"part9", "p9"}:
        return run_cli_part("part9", args)
    raise SystemExit(f"unknown part: {args.part}")


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
        "FEISHU_ACCOUNT_MONITOR_URL",
        "FEISHU_SELFMEDIA_ACCOUNT_MONITOR_URL",
    )
    report_url = args.report_url or feishu_table_url_from_env(
        "FEISHU_ACCOUNT_REPORT_URL",
        "FEISHU_SELFMEDIA_ACCOUNT_REPORT_URL",
        "FEISHU_BITABLE_URL",
    )
    if not monitor_url:
        raise SystemExit("missing FEISHU_ACCOUNT_MONITOR_URL or --monitor-url")

    records = feishu_list_records(monitor_url, view_id=args.view_id)
    accounts = [account_from_record(record) for record in records]
    if args.limit:
        accounts = accounts[: args.limit]

    paths = ensure_paths(ROOT / "Part7" / "account-competitor-weekly", "account_weekly.sqlite")
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
                "Part7 账号每日轮询",
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
            module="Part7 账号每日轮询",
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
    cron_command = [
        "openclaw",
        "cron",
        "add",
        "--name",
        args.name,
        "--agent",
        "feishu-media",
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
    parser = argparse.ArgumentParser(description="OpenClaw bridge for /home/ubuntu/selfmedia-tools Part1-Part9.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="List routable selfmedia parts.")

    run = sub.add_parser("run", help="Run one Part1-Part9 module.")
    run.add_argument("part", help="part1 ... part9")
    run.add_argument("--urls", nargs="*", default=[])
    run.add_argument("--text", default="")
    run.add_argument("--stdin", action="store_true")
    run.add_argument("--feishu-url", default="")
    run.add_argument("--require-feishu", action="store_true")
    run.add_argument("--no-write", action="store_true", help="Part2 only: do not write Feishu.")
    run.add_argument("--account", default="", help="Part7 account label.")
    run.add_argument("--timeout", type=int, default=1800)

    poll = sub.add_parser("daily-poll", help="Read Feishu account monitor table, refresh recent post stats, write daily report.")
    poll.add_argument("--monitor-url", default="")
    poll.add_argument("--report-url", default="")
    poll.add_argument("--view-id", default="")
    poll.add_argument("--limit", type=int, default=0)
    poll.add_argument("--require-feishu", action="store_true")
    poll.add_argument("--dry-run", action="store_true")

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
    if args.command == "list":
        print_json(
            {
                "parts": {
                    "part1": "字段刷新/素材入口",
                    "part2": "拆解/再创作，写飞书文档和多维表格",
                    "part3": "Cookie 状态检查",
                    **PART_MODULE_NAMES,
                },
                "daily_poll": "Feishu 账号监控表 -> 每日作品互动刷新 -> Part7 日报",
            }
        )
        return
    if args.command == "run":
        print_json(run_part(args))
        return
    if args.command == "daily-poll":
        print_json(daily_poll(args))
        return
    if args.command == "install-cron":
        print_json(install_cron(args))
        return


if __name__ == "__main__":
    main()
