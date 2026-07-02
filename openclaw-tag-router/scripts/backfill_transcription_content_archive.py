#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from openclaw_app.router.tag_router_common import MEETING_MINUTES_DIR
from openclaw_app.services.knowledge_archive_bridge import archive_meeting_content_section


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill meeting-note ## 内容整理 sections into Knowledge 【归档】 weekly notes.")
    parser.add_argument("--meeting-dir", default=str(MEETING_MINUTES_DIR), help="整理版会议纪要目录")
    parser.add_argument("--apply", action="store_true", help="实际写入 Obsidian 周记；默认只 dry-run")
    parser.add_argument("--refresh", action="store_true", help="先删除同一来源会议纪要的既有周记条目，再重新写入")
    parser.add_argument("--limit", type=int, default=0, help="最多处理多少个文件；0 表示不限制")
    parser.add_argument("--output", default="", help="可选 JSON 结果输出路径")
    args = parser.parse_args()

    meeting_dir = Path(args.meeting_dir)
    paths = sorted(meeting_dir.glob("*.md"))
    if args.limit > 0:
        paths = paths[: args.limit]

    rows = []
    counts: dict[str, int] = {}
    for path in paths:
        result = archive_meeting_content_section(path, dry_run=not args.apply, refresh=args.refresh)
        row = {"meeting_note": str(path), **result.to_dict()}
        rows.append(row)
        counts[result.status] = counts.get(result.status, 0) + 1

    payload = {
        "ok": True,
        "apply": args.apply,
        "refresh": args.refresh,
        "meeting_dir": str(meeting_dir),
        "total": len(paths),
        "counts": counts,
        "results": rows,
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
