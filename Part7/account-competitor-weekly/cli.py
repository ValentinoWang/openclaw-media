from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from common.social_runtime import (  # noqa: E402
    add_url_arguments,
    add_feishu_argument,
    connect,
    ensure_paths,
    feishu_status_message,
    json_dumps,
    metric_summary,
    read_urls_from_args,
    refresh_posts,
    row_to_feishu_fields,
    slug_time,
    write_feishu_records,
    write_json,
    write_markdown,
)


PART_DIR = Path(__file__).resolve().parent


def init_db(db_path: Path) -> None:
    with connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS accounts (
                account_key TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                platform TEXT,
                tags_json TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS account_posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_key TEXT NOT NULL,
                platform TEXT NOT NULL,
                post_id TEXT NOT NULL,
                url TEXT NOT NULL,
                captured_at TEXT NOT NULL,
                metrics_json TEXT NOT NULL,
                raw_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS weekly_insights (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_key TEXT NOT NULL,
                week_key TEXT NOT NULL,
                summary TEXT NOT NULL,
                payload_json TEXT NOT NULL
            );
            """
        )


def save(db_path: Path, account_key: str, rows: list[dict]) -> dict:
    posts = []
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO accounts(account_key, name, platform, tags_json, enabled)
            VALUES (?, ?, ?, ?, 1)
            ON CONFLICT(account_key) DO UPDATE SET name = excluded.name, platform = excluded.platform
            """,
            (account_key, account_key, rows[0]["platform"] if rows else "", json_dumps([])),
        )
        for row in rows:
            metrics = metric_summary(row)
            payload = {**row, **metrics}
            posts.append(payload)
            conn.execute(
                """
                INSERT INTO account_posts(account_key, platform, post_id, url, captured_at, metrics_json, raw_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    account_key,
                    row["platform"],
                    row["post_id"],
                    row["cleaned_url"],
                    row["captured_at"],
                    json_dumps(metrics),
                    json_dumps(row),
                ),
            )
        week_key = slug_time()[:8]
        top = sorted(posts, key=lambda item: item["total_interactions"], reverse=True)
        summary = f"{account_key}: tracked {len(posts)} posts; top total={top[0]['total_interactions'] if top else 0}"
        conn.execute(
            "INSERT INTO weekly_insights(account_key, week_key, summary, payload_json) VALUES (?, ?, ?, ?)",
            (account_key, week_key, summary, json_dumps({"posts": top})),
        )
    return {"account_key": account_key, "posts": posts, "summary": summary}


def report(result: dict) -> list[str]:
    lines = ["# 账号竞品周报", "", result["summary"], "", "## 作品表现", ""]
    for idx, item in enumerate(sorted(result["posts"], key=lambda row: row["total_interactions"], reverse=True), 1):
        lines.append(
            f"{idx}. {item['platform']} {item['post_id']} total={item['total_interactions']} "
            f"赞={item.get('like_count')} 藏={item.get('collect_count')} 评={item.get('comment_count')} 分享={item.get('share_count')}"
        )
    lines.extend(["", "## 下周建议", "", "- 优先拆解总互动和收藏率靠前的作品。", "- 将高赞评论送入 Part5 生成选题卡。"])
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(description="Part7 账号竞品周报：跟踪一组作品并生成周报。")
    add_url_arguments(parser)
    add_feishu_argument(parser)
    parser.add_argument("--account", default="manual", help="Account or competitor label for this run.")
    args = parser.parse_args()

    paths = ensure_paths(PART_DIR, "account_weekly.sqlite")
    init_db(paths.db_path)
    rows = refresh_posts(read_urls_from_args(args))
    result = save(paths.db_path, args.account, rows)
    stamp = slug_time()
    json_path = paths.output_dir / f"account_scores_{stamp}.json"
    md_path = paths.output_dir / f"weekly_report_{stamp}.md"
    write_json(json_path, result)
    write_markdown(md_path, report(result))
    records = []
    for item in result["posts"]:
        fields = row_to_feishu_fields(
            "Part7 账号竞品周报",
            item,
            summary=f"{args.account} total={item['total_interactions']}",
            report_path=str(md_path),
            score=item["total_interactions"],
            decision="weekly_tracking",
        )
        fields["详情JSON"] = item
        records.append(fields)
    record_ids = write_feishu_records(
        args.feishu_url,
        records,
        module="Part7 账号竞品周报",
        report_path=str(md_path),
        require=args.require_feishu,
    )
    print(f"wrote {json_path}")
    print(f"wrote {md_path}")
    print(feishu_status_message(record_ids, args.feishu_url, len(records)))


if __name__ == "__main__":
    main()
