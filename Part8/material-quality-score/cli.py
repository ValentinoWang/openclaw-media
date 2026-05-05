from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from common.social_runtime import (  # noqa: E402
    add_feishu_argument,
    add_url_arguments,
    connect,
    ensure_paths,
    feishu_status_message,
    json_dumps,
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
            CREATE TABLE IF NOT EXISTS material_scores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                platform TEXT NOT NULL,
                post_id TEXT NOT NULL,
                url TEXT NOT NULL,
                captured_at TEXT NOT NULL,
                overall_score INTEGER NOT NULL,
                decision TEXT NOT NULL,
                field_completeness_score INTEGER NOT NULL,
                interaction_quality_score INTEGER NOT NULL,
                recreate_value_score INTEGER NOT NULL,
                health_status TEXT NOT NULL,
                raw_json TEXT NOT NULL
            );
            """
        )


def save(db_path: Path, rows: list[dict]) -> list[dict]:
    scored = []
    with connect(db_path) as conn:
        for row in rows:
            score = quality_score(row)
            item = {**row, **score}
            scored.append(item)
            conn.execute(
                """
                INSERT INTO material_scores(
                    platform, post_id, url, captured_at, overall_score, decision,
                    field_completeness_score, interaction_quality_score, recreate_value_score,
                    health_status, raw_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["platform"],
                    row["post_id"],
                    row["cleaned_url"],
                    row["captured_at"],
                    score["overall_score"],
                    score["decision"],
                    score["field_completeness_score"],
                    score["interaction_quality_score"],
                    score["recreate_value_score"],
                    row["health_status"],
                    json_dumps(item),
                ),
            )
    scored.sort(key=lambda item: item["overall_score"], reverse=True)
    return scored


def report(scored: list[dict]) -> list[str]:
    lines = ["# 素材入库质量评分", "", "| 平台 | 作品ID | 总分 | 决策 | 字段完整 | 互动质量 | 复刻价值 | 链接 |", "| --- | --- | ---: | --- | ---: | ---: | ---: | --- |"]
    for item in scored:
        lines.append(
            f"| {item['platform']} | {item['post_id']} | {item['overall_score']} | {item['decision']} | "
            f"{item['field_completeness_score']} | {item['interaction_quality_score']} | {item['recreate_value_score']} | {item['cleaned_url']} |"
        )
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(description="Part8 素材入库质量评分：下载/拆解前评估素材价值。")
    add_url_arguments(parser)
    add_feishu_argument(parser)
    args = parser.parse_args()

    paths = ensure_paths(PART_DIR, "material_quality.sqlite")
    init_db(paths.db_path)
    rows = refresh_posts(read_urls_from_args(args))
    scored = save(paths.db_path, rows)
    stamp = slug_time()
    json_path = paths.output_dir / f"quality_scores_{stamp}.json"
    md_path = paths.output_dir / f"review_queue_{stamp}.md"
    write_json(json_path, {"items": scored})
    write_markdown(md_path, report(scored))
    records = []
    for item in scored:
        fields = row_to_feishu_fields(
            "Part8 素材入库质量评分",
            item,
            summary=f"总分 {item['overall_score']}；字段完整 {item['field_completeness_score']}；互动质量 {item['interaction_quality_score']}",
            report_path=str(md_path),
            score=item["overall_score"],
            decision=item["decision"],
        )
        fields["详情JSON"] = item
        records.append(fields)
    record_ids = write_feishu_records(
        args.feishu_url,
        records,
        module="Part8 素材入库质量评分",
        report_path=str(md_path),
        require=args.require_feishu,
    )
    print(f"wrote {json_path}")
    print(f"wrote {md_path}")
    print(feishu_status_message(record_ids, args.feishu_url, len(records)))


if __name__ == "__main__":
    main()
