from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from common.social_runtime import (  # noqa: E402
    INTERACTION_KEYS,
    add_feishu_argument,
    add_url_arguments,
    connect,
    feishu_status_message,
    json_dumps,
    read_urls_from_args,
    refresh_posts,
    row_to_feishu_fields,
    slug_time,
    write_feishu_records,
    write_json,
    write_markdown,
)


OUTPUT_DIR = ROOT / "data" / "media_vault" / "field_health_runs"
DB_PATH = OUTPUT_DIR / "field_health.sqlite"


def init_db(db_path: Path) -> None:
    with connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS field_runs (
                run_id TEXT PRIMARY KEY,
                platform TEXT NOT NULL,
                url TEXT NOT NULL,
                post_id TEXT NOT NULL,
                started_at TEXT NOT NULL,
                overall_status TEXT NOT NULL,
                failure_reason TEXT
            );
            CREATE TABLE IF NOT EXISTS field_values (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                field_name TEXT NOT NULL,
                field_value TEXT,
                source TEXT,
                status TEXT NOT NULL,
                error TEXT
            );
            """
        )


def diagnose(rows: list[dict]) -> list[dict]:
    diagnostics = []
    for row in rows:
        run_id = f"{row['platform']}:{row['post_id']}:{slug_time()}"
        fields = []
        sources = row.get("stats_sources") or {}
        missing = set(row.get("missing_interaction_fields") or [])
        for key in INTERACTION_KEYS:
            value = row.get(key)
            fields.append(
                {
                    "field_name": key,
                    "field_value": value,
                    "source": sources.get(key, ""),
                    "status": "ok" if value is not None else "missing",
                    "error": "missing" if key in missing or value is None else "",
                }
            )
        diagnostics.append(
            {
                "run_id": run_id,
                "platform": row["platform"],
                "url": row["cleaned_url"],
                "post_id": row["post_id"],
                "started_at": row["captured_at"],
                "overall_status": row["health_status"],
                "failure_reason": row.get("failure_reason") or "",
                "fields": fields,
                "source_row": row,
            }
        )
    return diagnostics


def save(db_path: Path, diagnostics: list[dict]) -> None:
    with connect(db_path) as conn:
        for item in diagnostics:
            conn.execute(
                """
                INSERT OR REPLACE INTO field_runs(run_id, platform, url, post_id, started_at, overall_status, failure_reason)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item["run_id"],
                    item["platform"],
                    item["url"],
                    item["post_id"],
                    item["started_at"],
                    item["overall_status"],
                    item["failure_reason"],
                ),
            )
            for field in item["fields"]:
                conn.execute(
                    """
                    INSERT INTO field_values(run_id, field_name, field_value, source, status, error)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item["run_id"],
                        field["field_name"],
                        "" if field["field_value"] is None else str(field["field_value"]),
                        field["source"],
                        field["status"],
                        field["error"],
                    ),
                )


def report(diagnostics: list[dict]) -> list[str]:
    lines = ["# 字段健康诊断", ""]
    for item in diagnostics:
        lines.append(f"## {item['platform']} {item['post_id']}")
        lines.append("")
        lines.append(f"- 状态：{item['overall_status']}")
        lines.append(f"- 失败原因：{item['failure_reason'] or '无'}")
        lines.append(f"- 链接：{item['url']}")
        lines.append("")
        for field in item["fields"]:
            lines.append(f"- {field['field_name']}: {field['status']} value={field['field_value']} source={field['source']}")
        lines.append("")
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(description="字段健康诊断：记录字段来源和失败原因。")
    add_url_arguments(parser)
    add_feishu_argument(parser)
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    init_db(DB_PATH)
    rows = refresh_posts(read_urls_from_args(args))
    diagnostics = diagnose(rows)
    save(DB_PATH, diagnostics)
    stamp = slug_time()
    json_path = OUTPUT_DIR / f"field_health_{stamp}.json"
    md_path = OUTPUT_DIR / f"failure_report_{stamp}.md"
    write_json(json_path, {"diagnostics": diagnostics})
    write_markdown(md_path, report(diagnostics))
    records = []
    for item in diagnostics:
        row = item["source_row"]
        fields = row_to_feishu_fields(
            "字段健康诊断",
            row,
            summary=f"状态 {item['overall_status']}；失败原因 {item['failure_reason'] or '无'}",
            report_path=str(md_path),
            score=100 if item["overall_status"] == "ok" else 50,
            decision=item["overall_status"],
        )
        fields["详情JSON"] = item
        records.append(fields)
    record_ids = write_feishu_records(
        args.feishu_url,
        records,
        module="字段健康诊断",
        report_path=str(md_path),
        require=args.require_feishu,
    )
    print(f"wrote {json_path}")
    print(f"wrote {md_path}")
    print(feishu_status_message(record_ids, args.feishu_url, len(records)))


if __name__ == "__main__":
    main()
