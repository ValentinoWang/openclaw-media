from __future__ import annotations

import argparse
import re
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
            CREATE TABLE IF NOT EXISTS comments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                platform TEXT NOT NULL,
                post_id TEXT NOT NULL,
                comment_id TEXT,
                author_name TEXT,
                text TEXT NOT NULL,
                like_count INTEGER,
                captured_at TEXT NOT NULL,
                raw_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS comment_topics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic_type TEXT NOT NULL,
                title TEXT NOT NULL,
                summary TEXT NOT NULL,
                priority_score INTEGER NOT NULL,
                evidence_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )


def topic_type(text: str) -> str:
    if re.search(r"怎么|如何|为啥|为什么|吗|\?|？", text):
        return "question"
    if re.search(r"求|教程|链接|模板|在哪|哪里|想要", text):
        return "demand"
    if re.search(r"不对|不是|但是|凭什么|离谱|争议", text):
        return "controversy"
    if re.search(r"难|痛|累|焦虑|卡住|做不到", text):
        return "pain"
    return "identity"


def topic_title(kind: str) -> str:
    return {
        "question": "高频问题",
        "demand": "明确需求",
        "controversy": "争议观点",
        "pain": "痛点表达",
        "identity": "身份/共鸣表达",
    }.get(kind, "评论洞察")


def build_topics(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    comments: list[dict] = []
    buckets: dict[str, list[dict]] = {}
    for row in rows:
        for comment in row.get("top_comments") or []:
            text = str(comment.get("text") or "").strip()
            if not text:
                continue
            item = {
                "platform": row["platform"],
                "post_id": row["post_id"],
                "comment_id": str(comment.get("cid") or ""),
                "author_name": str(comment.get("author") or "匿名"),
                "text": text,
                "like_count": int(comment.get("like_count") or 0),
                "captured_at": row["captured_at"],
                "source_url": row["cleaned_url"],
            }
            comments.append(item)
            buckets.setdefault(topic_type(text), []).append(item)
    topics = []
    for kind, items in buckets.items():
        items.sort(key=lambda item: item["like_count"], reverse=True)
        top = items[:5]
        score = sum(item["like_count"] for item in top)
        topics.append(
            {
                "topic_type": kind,
                "title": topic_title(kind),
                "summary": " / ".join(item["text"] for item in top[:3]),
                "priority_score": score,
                "evidence_comments": top,
            }
        )
    topics.sort(key=lambda item: item["priority_score"], reverse=True)
    return comments, topics


def save(db_path: Path, comments: list[dict], topics: list[dict]) -> None:
    with connect(db_path) as conn:
        for item in comments:
            conn.execute(
                """
                INSERT INTO comments(platform, post_id, comment_id, author_name, text, like_count, captured_at, raw_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item["platform"],
                    item["post_id"],
                    item["comment_id"],
                    item["author_name"],
                    item["text"],
                    item["like_count"],
                    item["captured_at"],
                    json_dumps(item),
                ),
            )
        for topic in topics:
            conn.execute(
                """
                INSERT INTO comment_topics(topic_type, title, summary, priority_score, evidence_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    topic["topic_type"],
                    topic["title"],
                    topic["summary"],
                    topic["priority_score"],
                    json_dumps(topic["evidence_comments"]),
                    comments[0]["captured_at"] if comments else "",
                ),
            )


def report(topics: list[dict], comments: list[dict]) -> list[str]:
    lines = ["# 高赞评论选题池", "", f"评论数：{len(comments)}", f"选题数：{len(topics)}", ""]
    for idx, topic in enumerate(topics, 1):
        lines.append(f"## {idx}. {topic['title']} score={topic['priority_score']}")
        lines.append("")
        lines.append(topic["summary"] or "暂无摘要")
        lines.append("")
        for item in topic["evidence_comments"]:
            lines.append(f"- {item['author_name']}（{item['like_count']}赞）：{item['text']}")
        lines.append("")
    if not topics:
        lines.append("暂无高赞评论；可提高 TOP_COMMENTS_LIMIT 或更新 Cookie 后重试。")
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(description="06 高赞评论选题池：抓取高赞评论并生成选题卡。")
    add_url_arguments(parser)
    add_feishu_argument(parser)
    args = parser.parse_args()

    paths = ensure_paths(PART_DIR, "comments.sqlite")
    init_db(paths.db_path)
    rows = refresh_posts(read_urls_from_args(args))
    comments, topics = build_topics(rows)
    save(paths.db_path, comments, topics)
    stamp = slug_time()
    json_path = paths.output_dir / f"topic_cards_{stamp}.json"
    md_path = paths.output_dir / f"topic_pool_{stamp}.md"
    write_json(json_path, {"comments": comments, "topics": topics, "source_rows": rows})
    write_markdown(md_path, report(topics, comments))
    records = []
    source_by_post = {row["post_id"]: row for row in rows}
    for topic in topics:
        evidence = topic["evidence_comments"][0] if topic["evidence_comments"] else {}
        row = source_by_post.get(evidence.get("post_id"), rows[0] if rows else {})
        fields = row_to_feishu_fields(
            "06 高赞评论选题池",
            row,
            summary=f"{topic['title']}：{topic['summary']}",
            report_path=str(md_path),
            score=topic["priority_score"],
            decision=topic["topic_type"],
        )
        fields["详情JSON"] = topic
        records.append(fields)
    record_ids = write_feishu_records(
        args.feishu_url,
        records,
        module="06 高赞评论选题池",
        report_path=str(md_path),
        require=args.require_feishu,
    )
    print(f"wrote {json_path}")
    print(f"wrote {md_path}")
    print(feishu_status_message(record_ids, args.feishu_url, len(records)))


if __name__ == "__main__":
    main()
