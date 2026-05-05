from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

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
    quality_score,
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
            CREATE TABLE IF NOT EXISTS cases (
                case_id TEXT PRIMARY KEY,
                platform TEXT NOT NULL,
                source_url TEXT NOT NULL,
                post_id TEXT NOT NULL,
                media_type TEXT,
                caption TEXT,
                cover_url TEXT,
                created_at TEXT NOT NULL,
                raw_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS metrics (
                case_id TEXT PRIMARY KEY,
                like_count INTEGER,
                collect_count INTEGER,
                comment_count INTEGER,
                share_count INTEGER,
                total_interactions INTEGER,
                collect_ratio REAL,
                comment_ratio REAL,
                share_ratio REAL
            );
            CREATE TABLE IF NOT EXISTS structures (
                case_id TEXT PRIMARY KEY,
                hook_type TEXT,
                opening_pattern TEXT,
                visual_pattern TEXT,
                topic_tags_json TEXT,
                audience_json TEXT,
                raw_json TEXT NOT NULL
            );
            """
        )


def structure_from_row(row: dict[str, Any]) -> dict[str, Any]:
    metrics = metric_summary(row)
    if metrics["collect_ratio"] >= 0.08:
        hook = "高收藏实用型"
    elif metrics["comment_ratio"] >= 0.03:
        hook = "高讨论争议型"
    elif metrics["share_ratio"] >= 0.03:
        hook = "高传播共鸣型"
    else:
        hook = "基础热度型"
    return {
        "hook_type": hook,
        "opening_pattern": "待从 Part2 拆解结果补齐",
        "visual_pattern": "待从素材证据补齐",
        "topic_tags": [],
        "audience": [],
        "metrics": metrics,
    }


def load_deconstruct_json(paths: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in paths:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        source = payload.get("deconstruct") if isinstance(payload, dict) else None
        if not isinstance(source, dict):
            source = payload if isinstance(payload, dict) else {}
        stats = source.get("stats") if isinstance(source.get("stats"), dict) else {}
        rows.append(
            {
                "url": source.get("source_url") or "",
                "cleaned_url": source.get("source_url") or "",
                "platform": source.get("platform") or "",
                "post_id": str(stats.get("video_id") or source.get("source_id") or ""),
                "captured_at": source.get("created_at") or "",
                "like_count": stats.get("like_count"),
                "collect_count": stats.get("collect_count"),
                "comment_count": stats.get("comment_count"),
                "share_count": stats.get("share_count"),
                "cover_url": source.get("cover_url") or "",
                "caption": source.get("source_caption") or "",
                "media_type": source.get("media_type") or source.get("part1_media_type") or "",
                "health_status": stats.get("interaction_status") or "",
                "raw_stats": stats,
                "raw_case": source,
            }
        )
    return rows


def save(db_path: Path, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    index: list[dict[str, Any]] = []
    with connect(db_path) as conn:
        for row in rows:
            post_id = row.get("post_id") or "unknown"
            case_id = f"{row.get('platform') or 'unknown'}:{post_id}"
            metrics = metric_summary(row)
            structure = structure_from_row(row)
            conn.execute(
                """
                INSERT OR REPLACE INTO cases(case_id, platform, source_url, post_id, media_type, caption, cover_url, created_at, raw_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    case_id,
                    row.get("platform", ""),
                    row.get("cleaned_url") or row.get("url", ""),
                    post_id,
                    row.get("media_type", ""),
                    row.get("caption", ""),
                    row.get("cover_url", ""),
                    row.get("captured_at", ""),
                    json_dumps(row),
                ),
            )
            conn.execute(
                """
                INSERT OR REPLACE INTO metrics(case_id, like_count, collect_count, comment_count, share_count, total_interactions, collect_ratio, comment_ratio, share_ratio)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    case_id,
                    row.get("like_count"),
                    row.get("collect_count"),
                    row.get("comment_count"),
                    row.get("share_count"),
                    metrics["total_interactions"],
                    metrics["collect_ratio"],
                    metrics["comment_ratio"],
                    metrics["share_ratio"],
                ),
            )
            conn.execute(
                """
                INSERT OR REPLACE INTO structures(case_id, hook_type, opening_pattern, visual_pattern, topic_tags_json, audience_json, raw_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    case_id,
                    structure["hook_type"],
                    structure["opening_pattern"],
                    structure["visual_pattern"],
                    json_dumps(structure["topic_tags"]),
                    json_dumps(structure["audience"]),
                    json_dumps(structure),
                ),
            )
            index.append({"case_id": case_id, **row, **metrics, "structure": structure, "quality": quality_score(row)})
    index.sort(key=lambda item: item["total_interactions"], reverse=True)
    return index


def report(index: list[dict[str, Any]]) -> list[str]:
    lines = ["# 爆款结构数据库索引", ""]
    for idx, item in enumerate(index, 1):
        lines.append(
            f"{idx}. {item['case_id']} total={item['total_interactions']} "
            f"hook={item['structure']['hook_type']} score={item['quality']['overall_score']}"
        )
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(description="Part6 爆款结构数据库：导入作品字段和拆解结果。")
    add_url_arguments(parser)
    add_feishu_argument(parser)
    parser.add_argument("--json-input", nargs="*", default=[], help="Part2 deconstruct JSON files to import.")
    args = parser.parse_args()

    paths = ensure_paths(PART_DIR, "viral_structure.sqlite")
    init_db(paths.db_path)
    rows: list[dict[str, Any]] = []
    if args.urls or args.input or args.stdin:
        rows.extend(refresh_posts(read_urls_from_args(args)))
    if args.json_input:
        rows.extend(load_deconstruct_json(args.json_input))
    if not rows:
        raise SystemExit("no input rows; pass URLs or --json-input")
    index = save(paths.db_path, rows)
    stamp = slug_time()
    json_path = paths.output_dir / f"case_index_{stamp}.json"
    md_path = paths.output_dir / f"structure_digest_{stamp}.md"
    write_json(json_path, {"cases": index})
    write_markdown(md_path, report(index))
    records = []
    for item in index:
        q = item["quality"]
        fields = row_to_feishu_fields(
            "Part6 爆款结构数据库",
            item,
            summary=f"{item['structure']['hook_type']} total={item['total_interactions']}",
            report_path=str(md_path),
            score=q["overall_score"],
            decision=q["decision"],
        )
        fields["详情JSON"] = item
        records.append(fields)
    record_ids = write_feishu_records(
        args.feishu_url,
        records,
        module="Part6 爆款结构数据库",
        report_path=str(md_path),
        require=args.require_feishu,
    )
    print(f"wrote {json_path}")
    print(f"wrote {md_path}")
    print(feishu_status_message(record_ids, args.feishu_url, len(records)))


if __name__ == "__main__":
    main()
