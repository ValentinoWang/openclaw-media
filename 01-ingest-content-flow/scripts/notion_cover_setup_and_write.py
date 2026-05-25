#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys

from dotenv import load_dotenv
from notion_client import Client

from src.config import load_settings
from src.downloader import clean_douyin_url, resolve_media
from src.notion_writer import write_to_notion
from src.storage import ensure_media_paths, load_json, load_text, save_json
from src.utils import detect_platform, extract_douyin_id, extract_xhs_id


def _load_env() -> None:
    env_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env"))
    if os.path.exists(env_path):
        load_dotenv(env_path)


def _ensure_cover_property(client: Client, database_id: str, property_name: str) -> str:
    database = client.databases.retrieve(database_id=database_id)
    properties = database.get("properties", {}) or {}
    if property_name in properties:
        return str(properties[property_name].get("type") or "")

    client.databases.update(
        database_id=database_id,
        properties={
            property_name: {
                "files": {},
            }
        },
    )
    database = client.databases.retrieve(database_id=database_id)
    properties = database.get("properties", {}) or {}
    if property_name not in properties:
        raise RuntimeError(f"failed_to_create_property:{property_name}")
    return str(properties[property_name].get("type") or "")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="为 Notion 数据库创建“封面图”列并用指定链接写入一条实验数据。",
    )
    parser.add_argument(
        "--url",
        required=True,
        help="分享链接（建议为包含 xsec_token 的分享链接）",
    )
    parser.add_argument(
        "--expected-dir",
        default="",
        help="期望的本地下载目录（用于校验写入时对应的素材目录）",
    )
    parser.add_argument(
        "--property-name",
        default="封面图",
        help="Notion 数据库列名（Files & media 类型）",
    )
    parser.add_argument(
        "--no-ensure",
        action="store_true",
        help="不自动创建封面列（仅写入页面）。",
    )
    parser.add_argument(
        "--save-analysis",
        action="store_true",
        help="将本次补全的 cover_url 等信息写回 analysis.json。",
    )
    args = parser.parse_args(argv)

    _load_env()

    notion_token = os.getenv("NOTION_TOKEN", "").strip()
    database_id = os.getenv("NOTION_DATABASE_ID", "").strip()
    if not notion_token or not database_id:
        print("缺少 NOTION_TOKEN 或 NOTION_DATABASE_ID，无法操作 Notion。", file=sys.stderr)
        return 1

    cleaned_url = clean_douyin_url(args.url)
    downloads_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "downloads"))
    paths = ensure_media_paths(cleaned_url, base_dir=downloads_dir)
    if args.expected_dir:
        expected = os.path.abspath(os.path.expanduser(args.expected_dir))
        actual = os.path.abspath(paths.item_dir)
        if expected != actual:
            print("素材目录校验失败：", file=sys.stderr)
            print(f"- expected: {expected}", file=sys.stderr)
            print(f"- actual:   {actual}", file=sys.stderr)
            return 2

    client = Client(auth=notion_token)
    if not args.no_ensure:
        prop_type = _ensure_cover_property(client, database_id, args.property_name)
        if prop_type and prop_type != "files":
            print(
                f"警告：数据库已存在同名列，但类型为 {prop_type}（推荐为 files）。",
                file=sys.stderr,
            )

    settings = load_settings()
    media = resolve_media(cleaned_url, settings)
    stats = media.stats or {}

    caption = load_text(paths.caption_path) or (media.caption or "")
    transcript = load_text(paths.transcript_path) or ""

    analysis = load_json(paths.analysis_path)
    if not isinstance(analysis, dict):
        analysis = {}

    if not analysis.get("platform"):
        analysis["platform"] = detect_platform(cleaned_url)
    if not analysis.get("video_id"):
        video_id = extract_xhs_id(cleaned_url)
        if not video_id:
            _kind, extracted = extract_douyin_id(cleaned_url)
            video_id = extracted
        if video_id:
            analysis["video_id"] = video_id

    if caption and not analysis.get("caption"):
        analysis["caption"] = caption
    if media.media_type and not analysis.get("media_type"):
        analysis["media_type"] = media.media_type

    for key in (
        "like_count",
        "collect_count",
        "comment_count",
        "share_count",
        "cover_url",
        "stats_sources",
        "interaction_status",
        "stats_notice",
        "missing_interaction_fields",
        "interaction_screenshot_path",
        "interaction_screenshot_status",
        "interaction_screenshot_error",
    ):
        if analysis.get(key) is None and stats.get(key) is not None:
            analysis[key] = stats[key]

    if args.save_analysis:
        save_json(paths.analysis_path, analysis)

    page_id = write_to_notion(cleaned_url, transcript, caption, analysis, settings)
    if not page_id:
        print("Notion 写入失败。", file=sys.stderr)
        return 3

    print(page_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
