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
    slug_time,
    table_lines,
    total_interactions,
    row_to_feishu_fields,
    write_feishu_records,
    write_json,
    write_markdown,
)


PART_DIR = Path(__file__).resolve().parent


def init_db(db_path: Path) -> None:
    with connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS posts (
                platform TEXT NOT NULL,
                post_id TEXT NOT NULL,
                url TEXT NOT NULL,
                cleaned_url TEXT NOT NULL,
                cover_url TEXT,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                PRIMARY KEY (platform, post_id)
            );
            CREATE TABLE IF NOT EXISTS post_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                platform TEXT NOT NULL,
                post_id TEXT NOT NULL,
                captured_at TEXT NOT NULL,
                like_count INTEGER,
                collect_count INTEGER,
                comment_count INTEGER,
                share_count INTEGER,
                total_interactions INTEGER NOT NULL,
                collect_ratio REAL NOT NULL,
                comment_ratio REAL NOT NULL,
                share_ratio REAL NOT NULL,
                health_status TEXT NOT NULL,
                stats_sources_json TEXT NOT NULL,
                raw_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS radar_signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                platform TEXT NOT NULL,
                post_id TEXT NOT NULL,
                captured_at TEXT NOT NULL,
                signal_type TEXT NOT NULL,
                score REAL NOT NULL,
                reason TEXT NOT NULL,
                previous_total INTEGER,
                current_total INTEGER NOT NULL
            );
            """
        )


def previous_total(db_path: Path, platform: str, post_id: str) -> int | None:
    if not db_path.exists():
        return None
    with connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT total_interactions
            FROM post_snapshots
            WHERE platform = ? AND post_id = ?
            ORDER BY captured_at DESC, id DESC
            LIMIT 1
            """,
            (platform, post_id),
        ).fetchone()
    return int(row["total_interactions"]) if row else None


def save_rows(db_path: Path, rows: list[dict]) -> list[dict]:
    signals: list[dict] = []
    with connect(db_path) as conn:
        for row in rows:
            metrics = metric_summary(row)
            current_total = metrics["total_interactions"]
            prev_total = previous_total(db_path, row["platform"], row["post_id"])
            growth = current_total if prev_total is None else current_total - prev_total
            score = growth if growth > 0 else current_total * 0.05
            reason = "first_snapshot" if prev_total is None else f"interaction_growth={growth}"
            signal_type = "rising" if growth > 0 else "baseline"

            conn.execute(
                """
                INSERT INTO posts(platform, post_id, url, cleaned_url, cover_url, first_seen_at, last_seen_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(platform, post_id) DO UPDATE SET
                    cleaned_url = excluded.cleaned_url,
                    cover_url = excluded.cover_url,
                    last_seen_at = excluded.last_seen_at
                """,
                (
                    row["platform"],
                    row["post_id"],
                    row["url"],
                    row["cleaned_url"],
                    row.get("cover_url", ""),
                    row["captured_at"],
                    row["captured_at"],
                ),
            )
            conn.execute(
                """
                INSERT INTO post_snapshots(
                    platform, post_id, captured_at,
                    like_count, collect_count, comment_count, share_count,
                    total_interactions, collect_ratio, comment_ratio, share_ratio,
                    health_status, stats_sources_json, raw_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["platform"],
                    row["post_id"],
                    row["captured_at"],
                    row.get("like_count"),
                    row.get("collect_count"),
                    row.get("comment_count"),
                    row.get("share_count"),
                    current_total,
                    metrics["collect_ratio"],
                    metrics["comment_ratio"],
                    metrics["share_ratio"],
                    row["health_status"],
                    json_dumps(row.get("stats_sources") or {}),
                    json_dumps(row),
                ),
            )
            conn.execute(
                """
                INSERT INTO radar_signals(platform, post_id, captured_at, signal_type, score, reason, previous_total, current_total)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (row["platform"], row["post_id"], row["captured_at"], signal_type, score, reason, prev_total, current_total),
            )
            enriched = {**row, **metrics, "signal_type": signal_type, "score": score, "reason": reason, "previous_total": prev_total}
            signals.append(enriched)
    signals.sort(key=lambda item: item["score"], reverse=True)
    return signals


def build_report(rows: list[dict], signals: list[dict]) -> list[str]:
    lines = ["# 爆款雷达", "", "## 采集结果", ""]
    lines.extend(table_lines(rows))
    lines.extend(["", "## 起量信号", ""])
    for idx, item in enumerate(signals, 1):
        lines.append(
            f"{idx}. {item['platform']} {item['post_id']} score={item['score']:.1f} "
            f"total={item['total_interactions']} reason={item['reason']}"
        )
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(description="05 爆款雷达：刷新作品互动数并输出起量信号。")
    add_url_arguments(parser)
    add_feishu_argument(parser)
    parser.add_argument("--top", type=int, default=20, help="How many signals to keep in JSON output.")
    args = parser.parse_args()

    paths = ensure_paths(PART_DIR, "viral_radar.sqlite")
    init_db(paths.db_path)
    urls = read_urls_from_args(args)
    rows = refresh_posts(urls)
    signals = save_rows(paths.db_path, rows)

    stamp = slug_time()
    json_path = paths.output_dir / f"rising_posts_{stamp}.json"
    md_path = paths.output_dir / f"radar_report_{stamp}.md"
    write_json(json_path, {"rows": rows, "signals": signals[: args.top]})
    write_markdown(md_path, build_report(rows, signals[: args.top]))
    feishu_records = [
        row_to_feishu_fields(
            "05 爆款雷达",
            item,
            summary=f"{item['signal_type']} score={item['score']:.1f}; {item['reason']}",
            report_path=str(md_path),
            score=f"{item['score']:.1f}",
            decision=item["signal_type"],
        )
        for item in signals[: args.top]
    ]
    record_ids = write_feishu_records(
        args.feishu_url,
        feishu_records,
        module="05 爆款雷达",
        report_path=str(md_path),
        require=args.require_feishu,
    )
    print(f"wrote {json_path}")
    print(f"wrote {md_path}")
    print(feishu_status_message(record_ids, args.feishu_url, len(feishu_records)))


if __name__ == "__main__":
    main()
