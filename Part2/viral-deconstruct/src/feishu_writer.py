from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

FEISHU_BASE = os.getenv("FEISHU_API_BASE_URL", "https://open.feishu.cn/open-apis").rstrip("/")
MAX_BITABLE_SUMMARY_CHARS = 500

ALLOWED_BITABLE_FIELDS = {
    "原标题",
    "参考链接",
    "平台",
    "赛道/标签",
    "封面图/前五秒",
    "原文件",
    "原音频",
    "作品截图",
    "热榜字段",
    "核心数据",
    "爆点拆解",
    "爆点迁移",
    "吸睛元素",
    "核心价值",
    "痛点/爽点",
    "发布时间",
    "高赞评论",
    "目标受众",
    "拆解文档链接",
    "拆解文档",
    "再创作文档链接",
    "再创作文档",
    "关联ID",
    "创建时间",
}

FIELD_ALIASES = {
    "拆解文档链接": ["拆解文档链接", "拆解文档"],
    "再创作文档链接": ["再创作文档链接", "再创作文档"],
}

FORBIDDEN_BITABLE_FIELDS = {
    "可复制发布稿",
    "分镜脚本",
    "图文脚本",
    "final_script",
    "video_storyboard",
    "image_post_script",
    "republish_copy",
}

ATTACHMENT_FIELD_KINDS = {
    "封面图/前五秒": {"cover", "preview", "first_frame", "five_second_preview"},
    "原文件": {"original_video", "original_image"},
    "原音频": {"original_audio"},
    "作品截图": {"interaction_screenshot"},
}


@dataclass(frozen=True)
class AttachmentItem:
    field_name: str
    path: str
    kind: str


def tenant_access_token() -> str:
    app_id = os.getenv("FEISHU_APP_ID", "")
    app_secret = os.getenv("FEISHU_APP_SECRET", "")
    if not app_id or not app_secret:
        raise RuntimeError("FEISHU_APP_ID / FEISHU_APP_SECRET 未配置")
    resp = requests.post(
        f"{FEISHU_BASE}/auth/v3/tenant_access_token/internal",
        json={"app_id": app_id, "app_secret": app_secret},
        timeout=10,
    )
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("code") != 0:
        raise RuntimeError(f"获取飞书 token 失败：{payload}")
    return payload["tenant_access_token"]


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"}


def resolve_wiki_bitable(wiki_token: str, token: str) -> str:
    resp = requests.get(f"{FEISHU_BASE}/wiki/v2/spaces/get_node", params={"token": wiki_token}, headers=_headers(token), timeout=10)
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("code") != 0:
        raise RuntimeError(f"解析飞书 wiki 节点失败：{payload}")
    node = payload.get("data", {}).get("node", {})
    if node.get("obj_type") != "bitable":
        raise RuntimeError(f"wiki 节点不是多维表格：{node.get('obj_type')}")
    return node["obj_token"]


def parse_feishu_bitable_url(url: str) -> tuple[str, str]:
    wiki_match = re.search(r"/wiki/([A-Za-z0-9]+)", url)
    table_match = re.search(r"[?&]table=([^&#]+)", url)
    if not wiki_match or not table_match:
        raise ValueError("飞书链接必须包含 /wiki/<token> 且带 table= 参数")
    token = tenant_access_token()
    app_token = resolve_wiki_bitable(wiki_match.group(1), token)
    return app_token, table_match.group(1)


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, indent=2)


def _summary_text(value: Any, limit: int = MAX_BITABLE_SUMMARY_CHARS) -> str:
    text = _normalize_text(value).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _core_stats_summary(stats: Any) -> str:
    if not isinstance(stats, dict):
        return _summary_text(stats)
    labels = [
        ("like_count", "点赞"),
        ("collect_count", "收藏"),
        ("comment_count", "评论"),
        ("share_count", "转发"),
        ("interaction_status", "互动状态"),
        ("stats_notice", "说明"),
        ("visible_interaction_text", "页面可见文本"),
        ("interaction_screenshot_status", "作品截图状态"),
        ("interaction_screenshot_path", "作品截图"),
    ]
    lines = []
    for key, label in labels:
        value = stats.get(key)
        if value not in (None, "", []):
            lines.append(f"{label}: {value}")
    missing = stats.get("missing_interaction_fields")
    if missing:
        lines.append("缺失字段: " + ", ".join(str(item) for item in missing))
    return _summary_text("\n".join(lines) if lines else stats)


def _top_comments_summary(stats: Any) -> str:
    if not isinstance(stats, dict):
        return ""
    comments = stats.get("top_comments")
    if not isinstance(comments, list):
        return ""
    lines = []
    for idx, comment in enumerate(comments[:5], 1):
        if not isinstance(comment, dict):
            continue
        author = comment.get("author") or "匿名"
        text = comment.get("text") or ""
        like_count = comment.get("like_count")
        suffix = f"（{like_count}赞）" if like_count is not None else ""
        lines.append(f"{idx}. {author}{suffix}: {text}")
    return _summary_text("\n".join(lines))


def validate_bitable_record(fields: dict[str, Any]) -> None:
    forbidden = set(fields) & FORBIDDEN_BITABLE_FIELDS
    if forbidden:
        raise ValueError(f"禁止写入多维表格的长脚本字段: {sorted(forbidden)}")
    unexpected = set(fields) - ALLOWED_BITABLE_FIELDS
    if unexpected:
        raise ValueError(f"多维表格字段不在白名单内: {sorted(unexpected)}")
    for name in ("爆点拆解", "爆点迁移", "吸睛元素", "核心价值", "痛点/爽点", "目标受众", "高赞评论"):
        value = fields.get(name)
        if isinstance(value, str) and len(value) > MAX_BITABLE_SUMMARY_CHARS:
            raise ValueError(f"多维表格摘要字段过长: {name}")


def resolve_field_name(canonical: str, existing: set[str]) -> str:
    for candidate in FIELD_ALIASES.get(canonical, [canonical]):
        if candidate in existing:
            return candidate
    return canonical


def remap_alias_fields(fields: dict[str, Any], existing: set[str]) -> dict[str, Any]:
    remapped: dict[str, Any] = {}
    for name, value in fields.items():
        target = resolve_field_name(name, existing)
        remapped[target] = value
    return remapped


def validate_attachment_item(item: AttachmentItem) -> None:
    allowed = ATTACHMENT_FIELD_KINDS.get(item.field_name)
    if not allowed:
        raise ValueError(f"未知附件字段: {item.field_name}")
    if item.kind not in allowed:
        raise ValueError(f"附件字段归类错误: {item.field_name} 不能放 {item.kind}")
    path = Path(item.path)
    if not path.exists() or not path.is_file() or path.stat().st_size <= 0:
        raise ValueError(f"附件文件不存在或为空: {item.path}")


def build_attachment_plan(result: dict[str, Any]) -> list[AttachmentItem]:
    plan: list[AttachmentItem] = []
    cover = result.get("cover_path") or result.get("source_preview_path")
    if isinstance(cover, str) and cover:
        plan.append(AttachmentItem("封面图/前五秒", cover, "first_frame"))
    elif isinstance(result.get("source_image_paths"), list) and result.get("source_image_paths"):
        plan.append(AttachmentItem("封面图/前五秒", str(result["source_image_paths"][0]), "cover"))

    video = result.get("source_video_path")
    if isinstance(video, str) and video:
        plan.append(AttachmentItem("原文件", video, "original_video"))
    images = result.get("source_image_paths")
    if isinstance(images, list):
        for image in images:
            if image:
                plan.append(AttachmentItem("原文件", str(image), "original_image"))

    audio = result.get("source_audio_path")
    if isinstance(audio, str) and audio:
        plan.append(AttachmentItem("原音频", audio, "original_audio"))

    interaction_screenshot = result.get("interaction_screenshot_path") or (result.get("stats") or {}).get("interaction_screenshot_path")
    if isinstance(interaction_screenshot, str) and interaction_screenshot:
        plan.append(AttachmentItem("作品截图", interaction_screenshot, "interaction_screenshot"))

    for item in plan:
        validate_attachment_item(item)
    return plan


def upload_attachment(app_token: str, table_id: str, field_name: str, file_path: str, token: str) -> str:
    path = Path(file_path)
    if not path.exists() or not path.is_file():
        return ""
    size = path.stat().st_size
    # 飞书 upload_all 单文件上限 20MB；更大的视频后续再接分片上传。
    if size > 20 * 1024 * 1024:
        return ""
    image_exts = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
    parent_type = "bitable_image" if path.suffix.lower() in image_exts else "bitable_file"
    with path.open("rb") as handle:
        resp = requests.post(
            f"{FEISHU_BASE}/drive/v1/medias/upload_all",
            headers={"Authorization": f"Bearer {token}"},
            data={
                "file_name": path.name,
                "parent_type": parent_type,
                "parent_node": app_token,
                "size": str(size),
            },
            files={"file": (path.name, handle)},
            timeout=60,
        )
    try:
        payload = resp.json()
    except ValueError:
        return ""
    if resp.status_code >= 400 or payload.get("code") != 0:
        return ""
    return payload.get("data", {}).get("file_token") or payload.get("data", {}).get("file_token") or ""


def _record_fields(result: dict[str, Any], source_text: str) -> dict[str, Any]:
    url = result.get("source_url") or ""
    title = result.get("source_title") or "未抓取"
    return {
        "原标题": str(title)[:500],
        "参考链接": {"text": "原作品", "link": url} if url else "",
        "平台": str(result.get("platform") or ("抖音" if "douyin" in url else ("小红书" if "xiaohongshu" in url or "xhs" in url else ""))),
        "爆点拆解": _summary_text(result.get("viral_mechanism")),
        "爆点迁移": _summary_text(result.get("production_checklist")),
        "核心价值": _summary_text(result.get("source_summary")),
        "吸睛元素": _summary_text(result.get("hook_elements") or result.get("viral_mechanism")),
        "痛点/爽点": _summary_text(result.get("pain_or_pleasure_points") or ""),
        "目标受众": _summary_text(result.get("target_audience") or ""),
        "发布时间": str(result.get("published_at") or ""),
        # 长脚本只进入飞书云文档，不写多维表格。
        "核心数据": _core_stats_summary(result.get("stats")),
        "高赞评论": _top_comments_summary(result.get("stats")),
        "拆解文档链接": {"text": "拆解文档", "link": result.get("deconstruct_doc_url", "")} if result.get("deconstruct_doc_url") else "",
        "再创作文档链接": {"text": "再创作文档", "link": result.get("recreate_doc_url", "")} if result.get("recreate_doc_url") else "",
        "关联ID": str(result.get("source_url") or source_text)[:1000],
        "创建时间": int(time.time() * 1000),
    }


def list_fields(app_token: str, table_id: str, token: str) -> list[dict[str, Any]]:
    resp = requests.get(f"{FEISHU_BASE}/bitable/v1/apps/{app_token}/tables/{table_id}/fields", headers=_headers(token), timeout=10)
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("code") != 0:
        raise RuntimeError(f"读取字段失败：{payload}")
    return payload.get("data", {}).get("items", [])


def ensure_text_fields(app_token: str, table_id: str, wanted: list[str], token: str) -> None:
    existing = {item.get("field_name") for item in list_fields(app_token, table_id, token)}
    for name in wanted:
        if name in existing:
            continue
        resp = requests.post(
            f"{FEISHU_BASE}/bitable/v1/apps/{app_token}/tables/{table_id}/fields",
            headers=_headers(token),
            json={"field_name": name, "type": 1},
            timeout=10,
        )
        payload = resp.json()
        if resp.status_code >= 400 or payload.get("code") != 0:
            # 字段创建失败不阻塞；后面会只写已有字段，避免整条记录失败。
            continue



def ensure_fields(app_token: str, table_id: str, specs: dict[str, int], token: str) -> None:
    existing = {item.get("field_name") for item in list_fields(app_token, table_id, token)}
    for name, field_type in specs.items():
        if resolve_field_name(name, existing) in existing:
            continue
        resp = requests.post(
            f"{FEISHU_BASE}/bitable/v1/apps/{app_token}/tables/{table_id}/fields",
            headers=_headers(token),
            json={"field_name": name, "type": field_type},
            timeout=10,
        )
        try:
            payload = resp.json()
        except ValueError:
            payload = {}
        if resp.status_code >= 400 or payload.get("code") != 0:
            continue

def write_deconstruction(result: dict[str, Any], source_text: str, bitable_url: str | None = None) -> str:
    bitable_url = bitable_url or os.getenv("FEISHU_BITABLE_URL", "")
    if not bitable_url:
        raise RuntimeError("缺少 FEISHU_BITABLE_URL 或 --feishu-url")
    token = tenant_access_token()
    app_token, table_id = parse_feishu_bitable_url(bitable_url)
    ensure_fields(
        app_token,
        table_id,
        {
            "封面图/前五秒": 17,
            "原文件": 17,
            "原音频": 17,
            "作品截图": 17,
            "拆解文档链接": 15,
            "再创作文档链接": 15,
        },
        token,
    )
    fields = _record_fields(result, source_text)
    validate_bitable_record({k: v for k, v in fields.items() if v not in (None, "", [])})
    field_items = list_fields(app_token, table_id, token)
    existing = {item.get("field_name") for item in field_items}
    fields = remap_alias_fields(fields, existing)
    attachment_values: dict[str, list[dict[str, str]]] = {}
    for item in build_attachment_plan(result):
        if item.field_name not in existing:
            continue
        token_val = upload_attachment(app_token, table_id, item.field_name, item.path, token)
        if not token_val:
            raise RuntimeError(f"附件上传失败，停止写入多维表格: {item.field_name} {item.path}")
        attachment_values.setdefault(item.field_name, []).append({"file_token": token_val})
    fields.update(attachment_values)
    fields = {k: v for k, v in fields.items() if k in existing and v not in (None, "", [])}
    validate_bitable_record(fields)
    resp = requests.post(
        f"{FEISHU_BASE}/bitable/v1/apps/{app_token}/tables/{table_id}/records",
        headers=_headers(token),
        json={"fields": fields},
        timeout=15,
    )
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("code") != 0:
        raise RuntimeError(f"写入飞书多维表格失败：{payload}")
    return payload.get("data", {}).get("record", {}).get("record_id", "")
