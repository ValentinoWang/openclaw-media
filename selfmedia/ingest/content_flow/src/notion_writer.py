from __future__ import annotations

import json
from typing import Optional

from notion_client import Client
import requests

from .config import Settings
from .semantic_persistence import analysis_user_field_contract_issue
from .utils import detect_platform, extract_douyin_id, extract_xhs_id, normalize_tags


def _find_title_property(properties: dict) -> Optional[str]:
    for name, prop in properties.items():
        if prop.get("type") == "title":
            return name
    if not properties:
        return "Name"
    return None


def _find_property(properties: dict, keywords: list[str], types: set[str]) -> Optional[str]:
    for name, prop in properties.items():
        if types and prop.get("type") not in types:
            continue
        lower = name.lower()
        if any(keyword in lower for keyword in keywords):
            return name
    return None


def _build_rich_text(value: str) -> list[dict]:
    chunks = [value[i : i + 1800] for i in range(0, len(value), 1800)]
    return [{"text": {"content": chunk}} for chunk in chunks if chunk]


def _normalize_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        parts = []
        for item in value:
            if item is None:
                continue
            if isinstance(item, (str, int, float, bool)):
                parts.append(str(item))
            elif isinstance(item, dict):
                parts.append(json.dumps(item, ensure_ascii=False))
            else:
                parts.append(str(item))
        return "\n".join([part for part in parts if part])
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _make_paragraph(text: str) -> dict:
    return {"object": "block", "type": "paragraph", "paragraph": {"rich_text": _build_rich_text(text)}}


def _make_heading(text: str) -> dict:
    return {
        "object": "block",
        "type": "heading_2",
        "heading_2": {"rich_text": [{"text": {"content": text}}]},
    }


def _build_children(analysis: dict, url: str) -> list[dict]:
    children: list[dict] = []
    if analysis:
        children.append(_make_heading("分析结果"))
        summary = _normalize_text(analysis.get("summary") or "")
        hooks = _normalize_text(analysis.get("hooks") or "")
        emotion = _normalize_text(analysis.get("emotion") or "")
        score = analysis.get("score")
        action_plan = _normalize_text(analysis.get("action_plan") or "")
        if summary:
            children.append(_make_paragraph(f"摘要：{summary}"))
        if hooks:
            children.append(_make_paragraph(f"钩子：{hooks}"))
        if emotion:
            children.append(_make_paragraph(f"情绪：{emotion}"))
        if score is not None:
            children.append(_make_paragraph(f"翻拍难度：{score}"))
        if action_plan:
            children.append(_make_paragraph(f"二创建议：\n{action_plan}"))

    if url:
        children.append(_make_heading("原链接"))
        children.append(_make_paragraph(url))

    work_copy = _normalize_text(analysis.get("work_copy") if analysis else "")
    if work_copy:
        children.append(_make_heading("平台文案"))
        for chunk in _build_rich_text(work_copy):
            children.append(
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {"rich_text": [chunk]},
                }
            )

    full_content = _normalize_text(analysis.get("full_content") if analysis else "")
    if full_content:
        children.append(_make_heading("全部内容"))
        for chunk in _build_rich_text(full_content):
            children.append(
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {"rich_text": [chunk]},
                }
            )

    return children


def _build_properties(
    properties: dict,
    title: str,
    url: str,
    analysis: dict,
) -> dict:
    notion_props: dict = {}
    title_key = _find_title_property(properties)
    if not title_key:
        return {}
    title_value = title
    title_key_lower = title_key.lower()
    video_id = analysis.get("video_id") if analysis else None
    if not video_id:
        _kind, extracted_id = extract_douyin_id(url)
        if extracted_id:
            video_id = extracted_id
        else:
            video_id = extract_xhs_id(url)
    if ("视频id" in title_key_lower) or ("video id" in title_key_lower) or ("videoid" in title_key_lower):
        if video_id:
            title_value = str(video_id)
    notion_props[title_key] = {"title": [{"text": {"content": title_value}}]}

    url_key = _find_property(properties, ["url", "链接", "link", "地址"], {"url"})
    if url_key and url:
        notion_props[url_key] = {"url": url}

    cover_key = _find_property(properties, ["封面", "cover", "thumbnail"], {"files", "url", "rich_text"})
    cover_url = _normalize_text(analysis.get("cover_url") if analysis else "")
    if cover_key and cover_url:
        prop_type = properties[cover_key]["type"]
        if prop_type == "files":
            notion_props[cover_key] = {
                "files": [
                    {
                        "name": "cover",
                        "type": "external",
                        "external": {"url": cover_url},
                    }
                ]
            }
        elif prop_type == "url":
            notion_props[cover_key] = {"url": cover_url}
        else:
            notion_props[cover_key] = {"rich_text": _build_rich_text(cover_url)}

    summary_key = _find_property(
        properties,
        ["summary", "摘要", "总结", "概述", "黄金三句总结", "爆款", "特点"],
        {"rich_text"},
    )
    summary = _normalize_text(analysis.get("summary") if analysis else "")
    if summary_key and summary:
        notion_props[summary_key] = {"rich_text": _build_rich_text(summary)}

    hooks_key = _find_property(properties, ["hooks", "钩子", "开头"], {"rich_text"})
    hooks = _normalize_text(analysis.get("hooks") if analysis else "")
    if hooks_key and hooks:
        notion_props[hooks_key] = {"rich_text": _build_rich_text(hooks)}

    emotion_key = _find_property(properties, ["emotion", "情绪"], {"rich_text", "select"})
    emotion = _normalize_text(analysis.get("emotion") if analysis else "")
    if emotion_key and emotion:
        prop_type = properties[emotion_key]["type"]
        if prop_type == "select":
            notion_props[emotion_key] = {"select": {"name": emotion}}
        else:
            notion_props[emotion_key] = {"rich_text": _build_rich_text(str(emotion))}

    score_key = _find_property(
        properties,
        ["score", "评分", "难度", "分数"],
        {"number", "rich_text"},
    )
    score = analysis.get("score") if analysis else None
    if score_key and score is not None:
        prop_type = properties[score_key]["type"]
        if prop_type == "number":
            try:
                notion_props[score_key] = {"number": float(score)}
            except (TypeError, ValueError):
                pass
        else:
            notion_props[score_key] = {"rich_text": _build_rich_text(str(score))}

    action_key = _find_property(
        properties,
        ["action", "plan", "建议", "二创", "翻拍"],
        {"rich_text"},
    )
    action_plan = _normalize_text(analysis.get("action_plan") if analysis else "")
    if action_key and action_plan:
        notion_props[action_key] = {"rich_text": _build_rich_text(action_plan)}

    transcript_key = _find_property(
        properties,
        ["full script", "script", "文案", "逐字稿", "transcript"],
        {"rich_text"},
    )
    script_text = _normalize_text(analysis.get("full_content") if analysis else "")
    if transcript_key and script_text:
        notion_props[transcript_key] = {"rich_text": _build_rich_text(script_text)}

    platform_key = _find_property(properties, ["platform", "平台"], {"select", "multi_select", "rich_text"})
    platform = analysis.get("platform") if analysis else ""
    if not platform:
        platform = detect_platform(url)
    if platform_key and platform:
        prop_type = properties[platform_key]["type"]
        if prop_type == "select":
            notion_props[platform_key] = {"select": {"name": platform}}
        elif prop_type == "multi_select":
            notion_props[platform_key] = {"multi_select": [{"name": platform}]}
        else:
            notion_props[platform_key] = {"rich_text": _build_rich_text(platform)}

    like_key = _find_property(properties, ["点赞", "like", "digg"], {"number", "rich_text"})
    collect_key = _find_property(properties, ["收藏", "collect", "favorite"], {"number", "rich_text"})
    comment_key = _find_property(properties, ["评论", "comment"], {"number", "rich_text"})
    share_key = _find_property(properties, ["转发", "分享", "share"], {"number", "rich_text"})
    like_count = analysis.get("like_count") if analysis else None
    collect_count = analysis.get("collect_count") if analysis else None
    comment_count = analysis.get("comment_count") if analysis else None
    share_count = analysis.get("share_count") if analysis else None

    for key_name, value in (
        (like_key, like_count),
        (collect_key, collect_count),
        (comment_key, comment_count),
        (share_key, share_count),
    ):
        if not key_name:
            continue
        prop_type = properties[key_name]["type"]
        if value is None:
            if prop_type == "rich_text":
                notion_props[key_name] = {"rich_text": _build_rich_text("未取到/待复核")}
            continue
        if prop_type == "number":
            try:
                notion_props[key_name] = {"number": float(value)}
            except (TypeError, ValueError):
                pass
        else:
            notion_props[key_name] = {"rich_text": _build_rich_text(str(value))}

    stats_notice_key = _find_property(
        properties,
        ["互动状态", "互动数据状态", "stats notice", "interaction status", "数据状态"],
        {"rich_text"},
    )
    stats_notice_parts = []
    interaction_status = analysis.get("interaction_status") if analysis else None
    stats_notice = analysis.get("stats_notice") if analysis else None
    missing_fields = analysis.get("missing_interaction_fields") if analysis else None
    screenshot_path = analysis.get("interaction_screenshot_path") if analysis else None
    screenshot_status = analysis.get("interaction_screenshot_status") if analysis else None
    screenshot_error = analysis.get("interaction_screenshot_error") if analysis else None
    if interaction_status:
        stats_notice_parts.append(str(interaction_status))
    if stats_notice:
        stats_notice_parts.append(str(stats_notice))
    if missing_fields:
        stats_notice_parts.append("缺失字段：" + ", ".join(str(item) for item in missing_fields))
    if screenshot_path:
        stats_notice_parts.append(f"作品截图：{screenshot_path}")
    elif screenshot_status:
        stats_notice_parts.append(f"作品截图状态：{screenshot_status}")
    if screenshot_error:
        stats_notice_parts.append(f"作品截图错误：{screenshot_error}")
    if stats_notice_key and stats_notice_parts:
        notion_props[stats_notice_key] = {"rich_text": _build_rich_text("\n".join(stats_notice_parts))}

    top_comment_key = _find_property(
        properties,
        ["top comment", "热评", "高赞评论", "置顶评论"],
        {"rich_text"},
    )
    top_comments = analysis.get("top_comments") if analysis else None
    if top_comment_key and top_comments:
        lines = []
        for idx, comment in enumerate(top_comments, start=1):
            author = comment.get("author") or "匿名"
            text = comment.get("text") or ""
            like_count = comment.get("like_count")
            if like_count is not None:
                line = f"{idx}. {author}（{like_count}赞）：{text}"
            else:
                line = f"{idx}. {author}：{text}"
            lines.append(line)
        notion_props[top_comment_key] = {"rich_text": _build_rich_text("\n".join(lines))}

    video_id_key = _find_property(
        properties,
        ["video id", "视频id", "视频ID", "视频Id"],
        {"rich_text", "number"},
    )
    video_id = analysis.get("video_id") if analysis else None
    if not video_id:
        _kind, extracted_id = extract_douyin_id(url)
        if extracted_id:
            video_id = extracted_id
        else:
            video_id = extract_xhs_id(url)
    if video_id_key and video_id:
        prop_type = properties[video_id_key]["type"]
        if prop_type == "number":
            try:
                notion_props[video_id_key] = {"number": float(video_id)}
            except (TypeError, ValueError):
                notion_props[video_id_key] = {"rich_text": _build_rich_text(str(video_id))}
        else:
            notion_props[video_id_key] = {"rich_text": _build_rich_text(str(video_id))}

    tags_key = _find_property(
        properties,
        ["tags", "标签", "tag"],
        {"multi_select", "select", "rich_text"},
    )
    tags = normalize_tags(analysis.get("tags") if analysis else None)
    if tags_key and tags:
        prop_type = properties[tags_key]["type"]
        if prop_type == "multi_select":
            notion_props[tags_key] = {"multi_select": [{"name": tag} for tag in tags]}
        elif prop_type == "select":
            notion_props[tags_key] = {"select": {"name": tags[0]}}
        else:
            notion_props[tags_key] = {"rich_text": _build_rich_text(", ".join(tags))}

    return notion_props


def write_to_notion(
    url: str,
    transcript: str,
    caption: str,
    analysis: dict,
    settings: Settings,
) -> Optional[str]:
    contract_issue = analysis_user_field_contract_issue(analysis, require_work_copy=bool(str(caption or "").strip()))
    if contract_issue:
        print(f"LLM 清洗用户字段契约未满足，停止 Notion 写入：{contract_issue}", flush=True)
        return None
    if not settings.notion_token or not settings.notion_database_id:
        print("Notion 配置缺失，跳过写入。", flush=True)
        return None

    client = Client(auth=settings.notion_token)
    try:
        database = client.databases.retrieve(database_id=settings.notion_database_id)
    except Exception as exc:
        print(f"获取 Notion 数据库失败: {exc}", flush=True)
        return None

    properties = database.get("properties", {}) or {}
    if not properties:
        try:
            response = requests.get(
                f"https://api.notion.com/v1/databases/{settings.notion_database_id}",
                headers={
                    "Authorization": f"Bearer {settings.notion_token}",
                    "Notion-Version": "2022-06-28",
                },
                timeout=10,
            )
            response.raise_for_status()
            properties = response.json().get("properties", {}) or {}
        except requests.RequestException as exc:
            print(f"获取 Notion 字段失败: {exc}", flush=True)
            properties = {}
    title = _normalize_text(analysis.get("title") if analysis else "")

    notion_props = _build_properties(properties, title, url, analysis)
    if not notion_props:
        print("Notion 数据库缺少标题字段，无法写入。", flush=True)
        return None
    children = _build_children(analysis, url)

    try:
        response = client.pages.create(
            parent={"database_id": settings.notion_database_id},
            properties=notion_props,
            children=children,
        )
    except Exception as exc:
        print(f"写入 Notion 失败: {exc}", flush=True)
        return None

    return response.get("id")
