from __future__ import annotations

import ast
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import requests

from common.social_runtime import load_default_env_files

from .config import load_config
from .feishu_writer import FEISHU_BASE, _headers, resolve_wiki_bitable, tenant_access_token
from .storyboard_images import generate_and_upload_storyboard_images, upload_feishu_doc_image

MAX_SOURCE_TEXT_CHARS_IN_DOC = 300
DOCX_WRITE_SLEEP_SEC = float(os.getenv("FEISHU_DOCX_WRITE_SLEEP_SEC", "0.35"))
SKIP_STORYBOARD_IMAGE_GENERATION = os.getenv("FEISHU_SKIP_STORYBOARD_IMAGE_GENERATION", "0").lower() in ("1", "true", "yes")
GENERATE_STORYBOARD_IMAGES = os.getenv("FEISHU_GENERATE_STORYBOARD_IMAGES", "0").lower() in ("1", "true", "yes")
DEFAULT_DECONSTRUCT_SOURCE_TABLE_URL = ""


@dataclass(frozen=True)
class DocRef:
    document_id: str
    url: str
    wiki_url: str = ""


def _get_parent_space(parent_node_token: str, token: str) -> str:
    resp = requests.get(f"{FEISHU_BASE}/wiki/v2/spaces/get_node", params={"token": parent_node_token}, headers=_headers(token), timeout=10)
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("code") != 0:
        raise RuntimeError(f"解析父级知识库节点失败：{payload}")
    return payload["data"]["node"]["space_id"]


def _find_child_doc(space_id: str, parent_node_token: str, title: str, token: str) -> tuple[str, str] | None:
    clean_title = (title or "").strip()
    page_token = ""
    while True:
        params = {"parent_node_token": parent_node_token, "page_size": 50}
        if page_token:
            params["page_token"] = page_token
        resp = requests.get(f"{FEISHU_BASE}/wiki/v2/spaces/{space_id}/nodes", params=params, headers=_headers(token), timeout=10)
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("code") != 0:
            raise RuntimeError(f"查询知识库子文档失败：{payload}")
        data = payload.get("data", {}) or {}
        for item in data.get("items", []) or []:
            if str(item.get("title") or "").strip() != clean_title:
                continue
            if str(item.get("obj_type") or "").lower() not in {"docx", "doc"}:
                continue
            document_id = str(item.get("obj_token") or "")
            node_token = str(item.get("node_token") or "")
            if document_id and node_token:
                return document_id, node_token
        if not data.get("has_more"):
            break
        page_token = str(data.get("page_token") or "")
        if not page_token:
            break
    return None


def _list_child_docs(space_id: str, parent_node_token: str, token: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    page_token = ""
    while True:
        params = {"parent_node_token": parent_node_token, "page_size": 50}
        if page_token:
            params["page_token"] = page_token
        resp = requests.get(f"{FEISHU_BASE}/wiki/v2/spaces/{space_id}/nodes", params=params, headers=_headers(token), timeout=10)
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("code") != 0:
            raise RuntimeError(f"查询知识库子文档失败：{payload}")
        data = payload.get("data", {}) or {}
        for item in data.get("items", []) or []:
            if str(item.get("obj_type") or "").lower() in {"docx", "doc"}:
                items.append(item)
        if not data.get("has_more"):
            break
        page_token = str(data.get("page_token") or "")
        if not page_token:
            break
    return items


def _parent_node_for_doc_kind(config: Any, doc_kind: str) -> str:
    if doc_kind == "deconstruct":
        return str(getattr(config, "feishu_deconstruct_parent_node_token", "") or config.feishu_wiki_parent_node_token or "").strip()
    if doc_kind == "recreate":
        return str(getattr(config, "feishu_recreate_parent_node_token", "") or config.feishu_wiki_parent_node_token or "").strip()
    return str(config.feishu_wiki_parent_node_token or "").strip()


def create_doc(title: str, content: dict[str, Any], folder_token: str | None = None, doc_kind: str = "deconstruct") -> str:
    load_default_env_files()
    token = tenant_access_token()
    config = load_config()
    parent_node = _parent_node_for_doc_kind(config, doc_kind)
    reused_existing = False
    if parent_node:
        space_id = _get_parent_space(parent_node, token)
        existing = _find_child_doc(space_id, parent_node, title or "拆解-再创执行单", token)
        if existing:
            document_id, node_token = existing
            reused_existing = True
        else:
            resp = requests.post(
                f"{FEISHU_BASE}/wiki/v2/spaces/{space_id}/nodes",
                headers=_headers(token),
                json={"obj_type": "docx", "parent_node_token": parent_node, "node_type": "origin", "title": title or "拆解-再创执行单"},
                timeout=15,
            )
            resp.raise_for_status()
            payload = resp.json()
            if payload.get("code") != 0:
                raise RuntimeError(f"在知识库下创建飞书文档失败：{payload}")
            node = payload["data"]["node"]
            document_id = node["obj_token"]
            node_token = node["node_token"]
    else:
        folder_token = folder_token or config.feishu_doc_folder_token
        body: dict[str, Any] = {"title": title or "拆解-再创执行单"}
        if folder_token:
            body["folder_token"] = folder_token
        resp = requests.post(f"{FEISHU_BASE}/docx/v1/documents", headers=_headers(token), json=body, timeout=15)
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("code") != 0:
            raise RuntimeError(f"创建飞书文档失败：{payload}")
        document_id = payload.get("data", {}).get("document", {}).get("document_id") or payload.get("data", {}).get("document_id")
        node_token = ""
    storyboard = content.get("video_storyboard")
    image_post_script = content.get("image_post_script")
    media_type = _content_media_type(content)
    is_video = media_type == "video"
    is_image_post = media_type == "image_post"
    strict_storyboard_images = False
    if doc_kind == "recreate" and is_video and storyboard:
        content.setdefault("storyboard_image_assets", [])
    should_generate_storyboard_images = (bool(content.get("generate_storyboard_images")) or GENERATE_STORYBOARD_IMAGES) and not SKIP_STORYBOARD_IMAGE_GENERATION
    if doc_kind == "recreate" and isinstance(storyboard, list) and storyboard and should_generate_storyboard_images:
        source = content.get("source_url") or content.get("user_input") or "recreate"
        work_dir = Path("/tmp") / "selfmedia_storyboard_images" / str(abs(hash(str(source))))
        assets = generate_and_upload_storyboard_images(
            storyboard,
            str(work_dir),
            document_id,
            token,
            feishu_base=FEISHU_BASE,
        )
        content["storyboard_image_assets"] = assets
        strict_storyboard_images = len([item for item in assets if item.get("path")]) >= len(storyboard)
    if reused_existing:
        _clear_document_blocks(document_id, token)
    append_blocks(document_id, content, token, doc_kind=doc_kind, include_evidence_appendix=False)
    if doc_kind == "recreate" and is_video and isinstance(storyboard, list) and storyboard:
        append_storyboard_table(
            document_id,
            storyboard,
            token,
            content.get("storyboard_image_assets") or content.get("evidence_assets") or [],
            strict_images=strict_storyboard_images if doc_kind == "recreate" else False,
        )
    if doc_kind == "recreate" and is_image_post and isinstance(image_post_script, list) and image_post_script:
        append_image_post_table(
            document_id,
            image_post_script,
            token,
            content.get("evidence_assets") or [],
        )
    append_evidence_appendix(document_id, content, token)
    content["feishu_docx_url"] = f"https://tcnwueberajc.feishu.cn/docx/{document_id}"
    content["feishu_doc_url"] = content["feishu_docx_url"]
    if node_token:
        content["feishu_wiki_url"] = f"https://tcnwueberajc.feishu.cn/wiki/{node_token}"
        content["feishu_doc_url"] = content["feishu_wiki_url"]
    return document_id


def sync_deconstruct_parent_index(source_records: dict[str, str] | None = None) -> None:
    token = tenant_access_token()
    config = load_config()
    parent_node = str(getattr(config, "feishu_deconstruct_parent_node_token", "") or "").strip()
    if not parent_node:
        return
    parent_payload = _wiki_node(parent_node, token)
    parent_doc = str(parent_payload.get("obj_token") or "")
    space_id = str(parent_payload.get("space_id") or "")
    if not parent_doc or not space_id:
        raise RuntimeError("拆解文档池缺少 document_id 或 space_id")
    existing_records = _parse_index_source_records(_read_docx_raw_content(parent_doc, token))
    existing_records.update({k: v for k, v in (source_records or {}).items() if k and v})
    child_docs = _list_child_docs(space_id, parent_node, token)
    child_docs.sort(key=_node_sort_timestamp, reverse=True)
    source_table_url = str(getattr(config, "material_deconstructions_url", "") or DEFAULT_DECONSTRUCT_SOURCE_TABLE_URL).strip()
    children = _deconstruct_index_blocks(child_docs, existing_records, source_table_url)
    _replace_document_blocks(parent_doc, children, token)


def _wiki_node(node_token: str, token: str) -> dict[str, Any]:
    resp = requests.get(f"{FEISHU_BASE}/wiki/v2/spaces/get_node", params={"token": node_token}, headers=_headers(token), timeout=10)
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("code") != 0:
        raise RuntimeError(f"解析知识库节点失败：{payload}")
    return payload.get("data", {}).get("node") or {}


def _node_sort_timestamp(node: dict[str, Any]) -> int:
    for key in ("obj_edit_time", "node_create_time", "obj_create_time"):
        try:
            return int(node.get(key) or 0)
        except (TypeError, ValueError):
            continue
    return 0


def _format_node_time(value: Any) -> str:
    try:
        timestamp = int(value or 0)
    except (TypeError, ValueError):
        return "待补"
    if timestamp <= 0:
        return "待补"
    if timestamp > 10**12:
        timestamp //= 1000
    tz = timezone(timedelta(hours=8))
    return datetime.fromtimestamp(timestamp, tz).strftime("%Y-%m-%d %H:%M:%S")


def _parse_index_source_records(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    current_title = ""
    for raw in str(text or "").splitlines():
        line = raw.strip()
        if line.startswith("爆款拆解文档｜"):
            current_title = line
            continue
        if current_title and line.startswith("来源记录："):
            value = line.split("：", 1)[1].strip()
            if value:
                result[current_title] = value
            current_title = ""
    return result


def _deconstruct_index_blocks(child_docs: list[dict[str, Any]], source_records: dict[str, str], source_table_url: str) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = [
        _heading("拆解文档池"),
        _paragraph("这里是 Media Model v2 素材拆解文档索引；每条拆解文档已作为本页下的独立子文档存放，标题按“爆款拆解文档｜主旨”命名。"),
        _paragraph("排序规则：按分析时间倒叙排列，最新分析在最上面。"),
    ]
    if source_table_url:
        blocks.append(_paragraph(f"来源表格：{source_table_url}"))
    for node in child_docs:
        title = str(node.get("title") or "未命名拆解文档").strip()
        node_token = str(node.get("node_token") or "").strip()
        blocks.extend(
            [
                _heading3(title),
                _paragraph(f"分析时间：{_format_node_time(node.get('obj_edit_time') or node.get('node_create_time') or node.get('obj_create_time'))}"),
                _paragraph(f"子文档：https://tcnwueberajc.feishu.cn/wiki/{node_token}" if node_token else "子文档：待补"),
                _paragraph(f"来源记录：{source_records.get(title) or '待补'}"),
            ]
        )
    return blocks


def _read_docx_raw_content(document_id: str, token: str) -> str:
    resp = requests.get(f"{FEISHU_BASE}/docx/v1/documents/{document_id}/raw_content", headers=_headers(token), timeout=15)
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("code") != 0:
        raise RuntimeError(f"读取飞书文档正文失败：{payload}")
    data = payload.get("data") or {}
    return str(data.get("content") or data.get("raw_content") or data.get("text") or "")


def _document_child_count(document_id: str, token: str) -> int:
    total = 0
    page_token = ""
    while True:
        params = {"document_revision_id": -1, "page_size": 500}
        if page_token:
            params["page_token"] = page_token
        resp = requests.get(f"{FEISHU_BASE}/docx/v1/documents/{document_id}/blocks/{document_id}/children", params=params, headers=_headers(token), timeout=15)
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("code") != 0:
            raise RuntimeError(f"读取飞书文档块失败：{payload}")
        data = payload.get("data") or {}
        total += len(data.get("items") or [])
        if not data.get("has_more"):
            return total
        page_token = str(data.get("page_token") or "")
        if not page_token:
            return total


def _replace_document_blocks(document_id: str, children: list[dict[str, Any]], token: str) -> None:
    child_count = _document_child_count(document_id, token)
    append_blocks_raw(document_id, children, token)
    if child_count:
        _delete_document_child_range(document_id, token, start_index=0, end_index=child_count, error_label="清理飞书文档原索引失败")


def _clear_document_blocks(document_id: str, token: str) -> None:
    child_count = _document_child_count(document_id, token)
    if child_count:
        _delete_document_child_range(document_id, token, start_index=0, end_index=child_count, error_label="清理飞书文档原内容失败")


def _delete_document_child_range(document_id: str, token: str, *, start_index: int, end_index: int, error_label: str) -> None:
    resp = requests.delete(
        f"{FEISHU_BASE}/docx/v1/documents/{document_id}/blocks/{document_id}/children/batch_delete",
        params={"document_revision_id": -1},
        headers=_headers(token),
        json={"start_index": start_index, "end_index": end_index},
        timeout=20,
    )
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("code") != 0:
        raise RuntimeError(f"{error_label}：{payload}")


def append_blocks_raw(document_id: str, children: list[dict[str, Any]], token: str) -> None:
    for index in range(0, len(children), 20):
        _post_docx_children(
            document_id,
            document_id,
            children[index:index + 20],
            token,
            "写入拆解文档池索引失败",
        )


def _content_media_type(content: dict[str, Any]) -> str:
    raw = str(content.get("media_type") or content.get("part1_media_type") or "").strip().lower()
    if raw in {"video", "image_post"}:
        return raw
    if content.get("source_video_path"):
        return "video"
    image_paths = content.get("source_image_paths")
    if isinstance(image_paths, list) and image_paths:
        return "image_post"
    return raw


def prepare_evidence_assets(evidence_assets: list[dict[str, Any]]) -> list[dict[str, str]]:
    prepared: list[dict[str, str]] = []
    if not evidence_assets:
        raise RuntimeError("拆解文档缺少视觉证据资产，不能创建画面图表格")
    for item in evidence_assets:
        asset_id = str(item.get("asset_id") or "").strip()
        path = str(item.get("path") or "").strip()
        if not asset_id or not path:
            raise RuntimeError(f"视觉证据资产缺少 asset_id/path：{item}")
        prepared.append({"asset_id": asset_id, "path": path, "file_token": str(item.get("file_token") or ""), "kind": str(item.get("kind") or "")})
    return prepared


def upload_evidence_assets(document_id: str, evidence_assets: list[dict[str, Any]], token: str) -> list[dict[str, str]]:
    """Upload evidence images into the current document scope."""
    uploaded: list[dict[str, str]] = []
    for item in prepare_evidence_assets(evidence_assets):
        file_token = upload_feishu_doc_image(document_id, item["path"], token, feishu_base=FEISHU_BASE)
        uploaded.append({**item, "file_token": file_token})
    return uploaded


def create_checked_doc(title: str, content: dict[str, Any], folder_token: str | None = None, doc_kind: str = "deconstruct") -> DocRef:
    document_id = create_doc(title, content, folder_token=folder_token, doc_kind=doc_kind)
    ref = assert_doc_accessible(document_id)
    wiki_url = str(content.get("feishu_wiki_url") or "")
    content["feishu_doc_id"] = ref.document_id
    content["feishu_docx_url"] = ref.url
    content["feishu_doc_url"] = wiki_url or ref.url
    if wiki_url:
        content["feishu_wiki_url"] = wiki_url
    return DocRef(document_id=ref.document_id, url=wiki_url or ref.url, wiki_url=wiki_url)


def assert_doc_accessible(document_id: str, token: str | None = None) -> DocRef:
    if not document_id:
        raise RuntimeError("飞书文档 token 为空")
    token = token or tenant_access_token()
    resp = requests.get(f"{FEISHU_BASE}/docx/v1/documents/{document_id}", headers=_headers(token), timeout=10)
    try:
        payload = resp.json()
    except ValueError:
        payload = {"raw": resp.text}
    if resp.status_code >= 400 or payload.get("code") != 0:
        raise RuntimeError(f"飞书文档不可访问：HTTP {resp.status_code} {payload}")
    document = payload.get("data", {}).get("document") or payload.get("data", {})
    checked_id = document.get("document_id") or document_id
    url = f"https://tcnwueberajc.feishu.cn/docx/{checked_id}"
    return DocRef(document_id=checked_id, url=url)


def append_blocks(
    document_id: str,
    content: dict[str, Any],
    token: str,
    doc_kind: str = "deconstruct",
    *,
    include_evidence_appendix: bool = True,
) -> None:
    blocks: list[dict[str, Any]] = []
    if doc_kind == "deconstruct":
        blocks = _deconstruct_doc_blocks(content, include_evidence_appendix=include_evidence_appendix)
    else:
        blocks = _recreate_doc_blocks(content)
    if not blocks:
        raise RuntimeError("飞书文档内容为空或不在白名单字段内")
    # Append in small batches to avoid API block count limits.
    for i in range(0, len(blocks), 20):
        resp = requests.post(
            f"{FEISHU_BASE}/docx/v1/documents/{document_id}/blocks/{document_id}/children",
            headers=_headers(token),
            json={"children": blocks[i:i+20]},
            timeout=20,
        )
        try:
            payload = resp.json()
        except ValueError:
            payload = {"raw": resp.text}
        if resp.status_code >= 400 or payload.get("code") != 0:
            raise RuntimeError(f"写入飞书文档失败 HTTP {resp.status_code}：{payload}")


def append_evidence_appendix(document_id: str, content: dict[str, Any], token: str) -> None:
    blocks = _deconstruct_evidence_blocks(content)
    if not blocks:
        return
    for i in range(0, len(blocks), 20):
        _post_docx_children(
            document_id,
            document_id,
            blocks[i:i + 20],
            token,
            "写入飞书证据附录失败",
        )


def _recreate_doc_blocks(content: dict[str, Any]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    media_type = _content_media_type(content)
    blocks.extend(_recreate_editorial_plan_blocks(_required_mapping(content, "editorial_plan")))
    blocks.extend(_recreate_production_route_blocks(_required_mapping(content, "production_route_plan")))
    blocks.append(_heading("发布脚本与分镜"))
    blocks.extend(_value_blocks(_required_text(content, "creative_positioning", "创作定位")))
    blocks.extend(_value_blocks(_required_text(content, "final_script", "可直接发布脚本")))
    if media_type == "video":
        storyboard = content.get("video_storyboard")
        if not isinstance(storyboard, list) or not storyboard:
            raise RuntimeError("拆解-再创文档缺少 video_storyboard")
        blocks.append(_heading3("视频分镜"))
        blocks.append(_paragraph("视频分镜见下方原生表格。"))
    elif media_type == "image_post":
        image_script = content.get("image_post_script")
        if not isinstance(image_script, list) or not image_script:
            raise RuntimeError("拆解-再创文档缺少 image_post_script")
        blocks.append(_heading3("图文脚本"))
        blocks.extend(_value_blocks(image_script))
    else:
        raise RuntimeError(f"拆解-再创文档 media_type 非法: {media_type}")
    blocks.extend(_recreate_comment_blocks(_required_mapping(content, "reusable_high_like_comment")))
    blocks.extend(_recreate_operation_blocks(_required_mapping(content, "operation_plan")))
    blocks.extend(_recreate_material_blocks(_required_mapping(content, "material_checklist")))
    blocks.extend(_recreate_risk_blocks(_required_list(content, "risk_controls")))
    blocks.append(_heading("标题与标签"))
    blocks.extend(_value_blocks(_required_list(content, "titles")))
    blocks.extend(_value_blocks(_required_list(content, "hashtags")))
    blocks.append(_heading("制作注意与避重说明"))
    blocks.extend(_value_blocks(_required_value(content, "production_notes")))
    blocks.extend(_value_blocks(_required_text(content, "anti_copy_notes", "避重说明")))
    return blocks


def _required_value(content: dict[str, Any], key: str) -> Any:
    value = content.get(key)
    if value in (None, "", [], {}):
        raise RuntimeError(f"拆解-再创文档缺少 {key}")
    return value


def _required_text(content: dict[str, Any], key: str, label: str) -> str:
    value = _required_value(content, key)
    text = str(value).strip()
    if not text:
        raise RuntimeError(f"拆解-再创文档缺少 {label}")
    return f"{label}：{text}"


def _required_mapping(content: dict[str, Any], key: str) -> dict[str, Any]:
    value = _required_value(content, key)
    if not isinstance(value, dict):
        raise RuntimeError(f"拆解-再创文档 {key} 必须是 object")
    return value


def _required_list(content: dict[str, Any], key: str) -> list[Any]:
    value = _required_value(content, key)
    if not isinstance(value, list):
        raise RuntimeError(f"拆解-再创文档 {key} 必须是 array")
    return value


def _recreate_editorial_plan_blocks(plan: dict[str, Any]) -> list[dict[str, Any]]:
    primary = plan.get("primary_plan")
    backups = plan.get("backup_variants")
    if not isinstance(primary, dict) or not isinstance(backups, list) or len(backups) != 2:
        raise RuntimeError("拆解-再创文档 editorial_plan 必须包含 1 个主方案 + 2 个备选改法")
    blocks = [_heading("千万年薪编导会怎么把这条改出彩？")]
    blocks.append(_heading3("主方案"))
    blocks.extend(
        _value_blocks(
            [
                f"标题：{_summary_value(primary.get('title'))}",
                f"为什么更出彩：{_summary_value(primary.get('why_better'))}",
                f"借什么：{_summary_value(primary.get('learn_from_reference'))}",
                f"必须改什么：{_summary_value(primary.get('must_transform'))}",
                f"执行角度：{_summary_value(primary.get('execution_angle'))}",
            ]
        )
    )
    blocks.append(_heading3("两个备选改法"))
    backup_lines = []
    for idx, item in enumerate(backups, 1):
        if not isinstance(item, dict):
            raise RuntimeError("拆解-再创文档 backup_variants 必须是 object 数组")
        backup_lines.append(
            f"{idx}. {_summary_value(item.get('title'))}；差异：{_summary_value(item.get('difference'))}；适合：{_summary_value(item.get('best_for'))}；风险：{_summary_value(item.get('risk'))}"
        )
    blocks.extend(_value_blocks(backup_lines))
    return blocks


def _recreate_production_route_blocks(plan: dict[str, Any]) -> list[dict[str, Any]]:
    rows = plan.get("shot_route_table")
    final_assembly = plan.get("final_assembly")
    if not isinstance(rows, list) or not rows or not isinstance(final_assembly, dict):
        raise RuntimeError("拆解-再创文档 production_route_plan 结构不完整")
    blocks = [_heading("这条内容怎么生产出来")]
    blocks.extend(_value_blocks([f"路线原则：{_summary_value(plan.get('route_policy'))}"]))
    route_lines = []
    for item in rows:
        if not isinstance(item, dict):
            raise RuntimeError("拆解-再创文档 shot_route_table 必须是 object 数组")
        route_lines.append(
            f"{_summary_value(item.get('segment_id'))}：{_summary_value(item.get('story_purpose'))}；路线={_summary_value(item.get('route'))}；素材={_summary_value(item.get('needed_material'))}；执行={_summary_value(item.get('execution_note'))}；检查={_summary_value(item.get('risk_or_manual_check'))}"
        )
    blocks.append(_heading3("分段路线"))
    blocks.extend(_value_blocks(route_lines))
    blocks.append(_heading3("合成交付"))
    blocks.extend(
        _value_blocks(
            [
                f"Remotion：{_summary_value(final_assembly.get('remotion_usage'))}",
                f"FFmpeg：{_summary_value(final_assembly.get('ffmpeg_usage'))}",
                f"交付说明：{_summary_value(final_assembly.get('delivery_note'))}",
            ]
        )
    )
    return blocks


def _recreate_comment_blocks(comment: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        _heading("可复用高赞评论"),
        *_value_blocks(
            [
                f"评论：{_summary_value(comment.get('comment_text'))}",
                f"刁钻角度：{_summary_value(comment.get('sharp_angle'))}",
                f"为什么可能获赞：{_summary_value(comment.get('why_it_can_get_likes'))}",
                f"复用方式：{_summary_value(comment.get('reuse_instruction'))}",
                f"风险边界：{_summary_value(comment.get('risk_boundary'))}",
            ]
        ),
    ]


def _recreate_operation_blocks(plan: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        _heading("这条内容怎么发"),
        *_value_blocks(
            [
                f"平台适配：{_summary_value(plan.get('platform_fit'))}",
                f"首 3 秒钩子：{_summary_value(plan.get('opening_3s_hook'))}",
                f"人群触发：{_summary_value(plan.get('audience_trigger'))}",
                f"评论区设计：{_summary_value(plan.get('comment_area_design'))}",
                f"发布时间：{_summary_value(plan.get('publish_timing'))}",
                f"观察指标：{_summary_value(plan.get('success_metric'))}",
                f"复投/迭代：{_summary_value(plan.get('republish_or_iteration'))}",
            ]
        ),
    ]


def _recreate_material_blocks(checklist: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        _heading("素材检查清单"),
        *_value_blocks(
            [
                f"必须有：{_summary_value(checklist.get('must_have'))}",
                f"最好有：{_summary_value(checklist.get('better_to_have'))}",
                f"没有也能救：{_summary_value(checklist.get('can_rescue_without'))}",
                f"禁止编造：{_summary_value(checklist.get('must_not_fabricate'))}",
            ]
        ),
    ]


def _recreate_risk_blocks(risks: list[Any]) -> list[dict[str, Any]]:
    lines = []
    for item in risks:
        if not isinstance(item, dict):
            raise RuntimeError("拆解-再创文档 risk_controls 必须是 object 数组")
        applies_to = _summary_value(item.get("applies_to"))
        suffix = f"；适用：{applies_to}" if applies_to else ""
        lines.append(f"风险：{_summary_value(item.get('risk'))}；控制：{_summary_value(item.get('control'))}{suffix}")
    return [_heading("风险控制"), *_value_blocks(lines)]


def _deconstruct_doc_blocks(content: dict[str, Any], *, include_evidence_appendix: bool = True) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for title, key in [
        ("总结", "content_summary"),
        ("原作品总结", "source_summary"),
        ("爆点机制", "viral_mechanism"),
    ]:
        value = content.get(key)
        if value in (None, "", []):
            continue
        blocks.append(_heading(title))
        blocks.extend(_value_blocks(value))
    assessment_lines = _assessment_summary_lines(content.get("viral_reuse_assessment") or {})
    if assessment_lines:
        blocks.append(_heading("爆款复用价值摘要"))
        blocks.extend(_value_blocks(assessment_lines))
    pacing_lines = _pacing_summary_lines(content.get("pacing_profile") or {})
    if pacing_lines:
        blocks.append(_heading("节奏复用摘要"))
        blocks.extend(_value_blocks(pacing_lines))
    guardrail_blocks = _guardrail_summary_blocks(content.get("reuse_guardrails") or {})
    if guardrail_blocks:
        blocks.append(_heading("复用护栏"))
        blocks.extend(guardrail_blocks)
    brief_lines = _compact_brief_lines(content.get("human_readable_brief") or {})
    if brief_lines:
        blocks.append(_heading("拆解-再创提示"))
        blocks.extend(_value_blocks(brief_lines))
    for title, key in [
        ("避重/改写建议", "avoid_plagiarism_notes"),
        ("后续复用检查清单", "production_checklist"),
    ]:
        value = content.get(key)
        if value in (None, "", []):
            continue
        blocks.append(_heading(title))
        blocks.extend(_value_blocks(value))
    if include_evidence_appendix:
        blocks.extend(_deconstruct_evidence_blocks(content))
    return blocks


def _post_docx_children(
    document_id: str,
    parent_block_id: str,
    children: list[dict[str, Any]],
    token: str,
    error_label: str,
    timeout: int = 20,
) -> dict[str, Any]:
    resp = requests.post(
        f"{FEISHU_BASE}/docx/v1/documents/{document_id}/blocks/{parent_block_id}/children?document_revision_id=-1",
        headers=_headers(token),
        json={"children": children, "index": -1},
        timeout=timeout,
    )
    try:
        payload = resp.json()
    except ValueError:
        payload = {"raw": resp.text}
    if resp.status_code >= 400 or payload.get("code") != 0:
        raise RuntimeError(f"{error_label} HTTP {resp.status_code}：{payload}")
    return payload


def _get_docx_block(document_id: str, block_id: str, token: str, error_label: str) -> dict[str, Any]:
    resp = requests.get(f"{FEISHU_BASE}/docx/v1/documents/{document_id}/blocks/{block_id}", headers=_headers(token), timeout=10)
    try:
        payload = resp.json()
    except ValueError:
        payload = {"raw": resp.text}
    if resp.status_code >= 400 or payload.get("code") != 0:
        raise RuntimeError(f"{error_label} HTTP {resp.status_code}：{payload}")
    return payload.get("data", {}).get("block") or payload.get("data", {})


def _get_docx_children(document_id: str, block_id: str, token: str, error_label: str) -> list[dict[str, Any]]:
    resp = requests.get(f"{FEISHU_BASE}/docx/v1/documents/{document_id}/blocks/{block_id}/children", headers=_headers(token), timeout=10)
    try:
        payload = resp.json()
    except ValueError:
        payload = {"raw": resp.text}
    if resp.status_code >= 400 or payload.get("code") != 0:
        raise RuntimeError(f"{error_label} HTTP {resp.status_code}：{payload}")
    return payload.get("data", {}).get("items") or payload.get("data", {}).get("children") or []


def _extract_block_id(item: Any) -> str:
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        return str(item.get("block_id") or item.get("id") or "")
    return ""


def _extract_table_cell_ids(table_block: dict[str, Any], expected: int) -> list[str]:
    table = table_block.get("table") if isinstance(table_block, dict) else {}
    candidates = []
    if isinstance(table, dict):
        candidates.extend(table.get("cells") or [])
    candidates.extend(table_block.get("children") or [])
    ids = [_extract_block_id(item) for item in candidates]
    ids = [item for item in ids if item]
    return ids[:expected] if len(ids) >= expected else ids


def _find_created_table(payload: dict[str, Any]) -> dict[str, Any]:
    children = payload.get("data", {}).get("children") or payload.get("data", {}).get("items") or []
    for child in children:
        if isinstance(child, dict) and child.get("block_type") == 31:
            return child
    return {}


def _find_created_block(payload: dict[str, Any], block_type: int) -> dict[str, Any]:
    children = payload.get("data", {}).get("children") or payload.get("data", {}).get("items") or []
    for child in children:
        if isinstance(child, dict) and child.get("block_type") == block_type:
            return child
    return {}


def _create_docx_table(
    document_id: str,
    token: str,
    heading: str,
    rows: int,
    cols: int,
    error_label: str,
) -> list[str]:
    payload = _post_docx_children(
        document_id,
        document_id,
        [
            _heading(heading),
            {"block_type": 31, "table": {"property": {"row_size": rows, "column_size": cols}}},
        ],
        token,
        error_label,
        timeout=30,
    )
    table_block = _find_created_table(payload)
    table_id = str(table_block.get("block_id") or "")
    expected = rows * cols
    cell_ids = _extract_table_cell_ids(table_block, expected)
    if len(cell_ids) < expected and table_id:
        hydrated = _get_docx_block(document_id, table_id, token, f"{error_label}：读取表格块失败")
        cell_ids = _extract_table_cell_ids(hydrated, expected)
    if len(cell_ids) < expected and table_id:
        children = _get_docx_children(document_id, table_id, token, f"{error_label}：读取表格单元格失败")
        cell_ids = [_extract_block_id(item) for item in children]
        cell_ids = [item for item in cell_ids if item]
    if len(cell_ids) < expected:
        raise RuntimeError(f"{error_label}：飞书未返回完整表格单元格 id，expected={expected} got={len(cell_ids)} table_id={table_id}")
    return cell_ids[:expected]


def _append_cell_blocks(document_id: str, cell_id: str, blocks: list[dict[str, Any]], token: str, error_label: str) -> None:
    if not blocks:
        return
    _post_docx_children(document_id, cell_id, blocks, token, error_label, timeout=20)
    if DOCX_WRITE_SLEEP_SEC > 0:
        time.sleep(DOCX_WRITE_SLEEP_SEC)


def _try_append_cell_blocks(document_id: str, cell_id: str, blocks: list[dict[str, Any]], token: str, error_label: str) -> bool:
    try:
        _append_cell_blocks(document_id, cell_id, blocks, token, error_label)
        return True
    except RuntimeError:
        return False


def _patch_docx_image(document_id: str, image_block_id: str, file_token: str, token: str, error_label: str) -> None:
    resp = requests.patch(
        f"{FEISHU_BASE}/docx/v1/documents/{document_id}/blocks/{image_block_id}",
        headers=_headers(token),
        json={"replace_image": {"token": file_token}},
        timeout=20,
    )
    try:
        payload = resp.json()
    except ValueError:
        payload = {"raw": resp.text}
    if resp.status_code >= 400 or payload.get("code") != 0:
        raise RuntimeError(f"{error_label} HTTP {resp.status_code}：{payload}")


def _append_image_file_to_cell(document_id: str, cell_id: str, file_path: str, token: str, error_label: str) -> None:
    payload = _post_docx_children(
        document_id,
        cell_id,
        [{"block_type": 27, "image": {}}],
        token,
        f"{error_label}：创建空图片块失败",
        timeout=20,
    )
    image_block = _find_created_block(payload, 27)
    image_block_id = str(image_block.get("block_id") or "")
    if not image_block_id:
        children = _get_docx_children(document_id, cell_id, token, f"{error_label}：读取图片块失败")
        for child in reversed(children):
            if isinstance(child, dict) and child.get("block_type") == 27:
                image_block_id = _extract_block_id(child)
                break
    if not image_block_id:
        raise RuntimeError(f"{error_label}：飞书未返回 Image Block id")
    file_token = upload_feishu_doc_image(document_id, file_path, token, feishu_base=FEISHU_BASE, parent_node=image_block_id)
    _patch_docx_image(document_id, image_block_id, file_token, token, f"{error_label}：绑定图片 token 失败")


def _heading(text: str) -> dict[str, Any]:
    return {"block_type": 4, "heading2": {"elements": [{"text_run": {"content": text}}]}}


def _paragraph(text: str) -> dict[str, Any]:
    return {"block_type": 2, "text": {"elements": [{"text_run": {"content": text[:1800]}}]}}


def _value_blocks(value: Any) -> list[dict[str, Any]]:
    value = _coerce_list_like_text(value)
    if isinstance(value, str):
        return [_paragraph(chunk) for chunk in _chunks(value)]
    if isinstance(value, dict):
        return [_paragraph(f"{k}：{v}") for k, v in value.items()]
    if isinstance(value, list):
        if value and all(isinstance(item, dict) for item in value):
            return _card_blocks(value)
        return [_paragraph(f"{idx}. {item}") for idx, item in enumerate(value, 1)]
    return [_paragraph(str(value))]


def _evidence_manifest_summary(evidence_manifest: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for evidence_id, item in list(evidence_manifest.items())[:120]:
        if not isinstance(item, dict):
            continue
        evidence_type = str(item.get("type") or "")
        if evidence_type == "visual":
            lines.append(f"{evidence_id}｜视觉｜{item.get('kind') or ''}｜{item.get('phase') or ''}")
        elif evidence_type == "speech":
            text = str(item.get("text") or "")
            lines.append(f"{evidence_id}｜口播｜{item.get('start')}s-{item.get('end')}s｜{text[:80]}")
        elif evidence_type == "ocr":
            text = _safe_ocr_text(item)
            if text:
                lines.append(f"{evidence_id}｜屏幕文字｜{item.get('asset_id') or ''}｜{text[:80]}")
            else:
                lines.append(f"{evidence_id}｜屏幕文字｜{item.get('asset_id') or ''}｜低置信或不可读，原文不进入正文")
        elif evidence_type == "scene":
            lines.append(f"{evidence_id}｜场景段｜{item.get('start_sec')}s-{item.get('end_sec')}s｜{item.get('reason') or ''}")
        elif evidence_type == "visual_observation":
            lines.append(f"{evidence_id}｜关键帧观察｜{item.get('asset_id') or ''}")
    return lines


def _assessment_summary_lines(assessment: dict[str, Any]) -> list[str]:
    if not isinstance(assessment, dict):
        return []
    lines: list[str] = []
    label = assessment.get("final_label")
    confidence = assessment.get("confidence")
    if label not in (None, ""):
        lines.append(f"复用结论：{label}" + (f"；confidence={confidence}" if confidence not in (None, "") else ""))
    for key, label_text in [
        ("observed_virality", "可见热度"),
        ("mechanism_strength", "机制强度"),
        ("account_fit", "账号适配"),
        ("production_feasibility", "生产可行性"),
        ("reuse_risk", "复用风险"),
    ]:
        value = _summary_value(assessment.get(key))
        if value:
            lines.append(f"{label_text}：{value}")
    if assessment.get("human_review_required") not in (None, ""):
        lines.append(f"人工复核：{assessment.get('human_review_required')}")
    return lines


def _pacing_summary_lines(pacing_profile: dict[str, Any]) -> list[str]:
    if not isinstance(pacing_profile, dict):
        return []
    interpretation = pacing_profile.get("llm_interpretation")
    if isinstance(interpretation, dict):
        lines: list[str] = []
        for key in ("summary", "rhythm_pattern", "edit_recommendations", "reuse_notes"):
            value = _summary_value(interpretation.get(key))
            if value:
                lines.append(f"{key}：{value}")
        if lines:
            return lines
    value = _summary_value(interpretation)
    return [value] if value else []


def _guardrail_summary_blocks(guardrails: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(guardrails, dict):
        return []
    blocks: list[dict[str, Any]] = []
    section_index = 1
    for key, label in [
        ("allowed_reuse", "可以学"),
        ("required_transformations", "必须改"),
        ("prohibited_reuse", "禁止碰"),
        ("own_account_mapping", "账号迁移"),
        ("similarity_risk", "相似风险"),
        ("originality_requirements", "原创要求"),
        ("sensitive_reuse_flags", "敏感复用标记"),
    ]:
        value = _summary_value(guardrails.get(key))
        if value:
            blocks.append(_heading3(f"{section_index}. {label}"))
            blocks.extend(_value_blocks(value))
            section_index += 1
    if guardrails.get("human_review_required") not in (None, ""):
        blocks.append(_heading3(f"{section_index}. 人工复核"))
        blocks.extend(_value_blocks(str(guardrails.get("human_review_required"))))
    return blocks


def _summary_value(value: Any, *, limit: int = 320) -> str:
    if value in (None, "", [], {}):
        return ""
    if isinstance(value, dict):
        preferred: list[str] = []
        for key in ("level", "overall", "label", "summary", "reason", "item", "element", "required_change"):
            item = value.get(key)
            if item not in (None, "", [], {}):
                preferred.append(str(item))
        if preferred:
            return "；".join(preferred)[:limit]
        compact = [f"{key}={_summary_value(item, limit=120)}" for key, item in value.items() if item not in (None, "", [], {}) and key != "python_facts"]
        return "；".join(item for item in compact if item)[:limit]
    if isinstance(value, list):
        items = [_summary_value(item, limit=120) for item in value if item not in (None, "", [], {})]
        return "；".join(item for item in items if item)[:limit]
    return str(value).strip()[:limit]


def _deconstruct_evidence_blocks(content: dict[str, Any]) -> list[dict[str, Any]]:
    evidence_manifest = content.get("evidence_manifest") if isinstance(content.get("evidence_manifest"), dict) else {}
    speech_transcript = content.get("speech_transcript") if isinstance(content.get("speech_transcript"), dict) else {}
    speech_timeline = content.get("speech_timeline") if isinstance(content.get("speech_timeline"), list) else []
    visible_text_segments = content.get("visible_text_segments") if isinstance(content.get("visible_text_segments"), list) else []
    has_deconstruct_evidence = bool(evidence_manifest or speech_timeline or visible_text_segments or speech_transcript)
    if not has_deconstruct_evidence:
        return []
    blocks: list[dict[str, Any]] = []

    blocks.append(_heading("证据附录"))
    if speech_timeline:
        blocks.append(_heading3("ASR 摘要"))
        blocks.extend(_value_blocks([_format_speech_timeline_item(item) for item in speech_timeline[:20] if isinstance(item, dict)]))
    else:
        status = str(speech_transcript.get("status") or "unknown")
        reason = str(speech_transcript.get("reason") or "")
        blocks.append(_paragraph(f"ASR：无可靠时间线证据。status={status}" + (f"；{reason}" if reason else "")))

    if visible_text_segments:
        blocks.append(_heading3("OCR 摘要"))
        formatted = [_format_visible_text_item(item) for item in visible_text_segments[:30] if isinstance(item, dict)]
        blocks.extend(_value_blocks([item for item in formatted if item]))
    else:
        blocks.append(_paragraph("OCR：无可靠屏幕文字证据。"))

    evidence_lines = _evidence_manifest_summary(evidence_manifest)
    if evidence_lines:
        blocks.append(_heading3("证据索引"))
        blocks.extend(_value_blocks(evidence_lines))
    return blocks


def _format_speech_timeline_item(item: dict[str, Any]) -> str:
    return f"{item.get('segment_id') or item.get('evidence_id') or ''} [{item.get('start', '')}-{item.get('end', '')}]：{item.get('text', '')}"


def _format_visible_text_item(item: dict[str, Any]) -> str:
    text = _safe_ocr_text(item)
    if not text:
        return f"{item.get('text_segment_id') or item.get('evidence_id') or ''}｜{item.get('asset_id', '')}：低置信或不可读，原文不进入正文"
    return f"{item.get('text_segment_id') or item.get('evidence_id') or ''}｜{item.get('asset_id', '')}：{text}"


def _safe_ocr_text(item: dict[str, Any]) -> str:
    try:
        confidence = float(item.get("confidence"))
    except (TypeError, ValueError):
        confidence = 0.0
    text = str(item.get("text") or "").strip()
    if confidence < 0.5:
        return ""
    if _looks_like_ocr_noise(text):
        return ""
    return text


def _looks_like_ocr_noise(text: str) -> bool:
    compact = "".join(str(text or "").split())
    if not compact:
        return True
    if len(compact) <= 3:
        return True
    alnum = sum(ch.isalnum() for ch in compact)
    if alnum / max(len(compact), 1) < 0.45:
        return True
    return False


def _compact_brief_lines(brief: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for key in ("source_summary", "why_it_may_work", "account_fit_reason"):
        value = brief.get(key)
        if value:
            lines.append(f"{key}：{value}")
    for key in ("usable_patterns", "recommended_script_directions", "must_transform", "must_not_copy", "human_review_flags"):
        value = brief.get(key)
        if isinstance(value, list):
            lines.append(f"{key}：" + "；".join(str(item).strip() for item in value if str(item).strip()))
        elif value:
            lines.append(f"{key}：{value}")
    return lines


def _coerce_list_like_text(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not (text.startswith("[") and text.endswith("]")):
        return value
    try:
        parsed = ast.literal_eval(text)
    except (SyntaxError, ValueError):
        return value
    if isinstance(parsed, list) and all(not isinstance(item, (dict, list, tuple, set)) for item in parsed):
        return [str(item).strip() for item in parsed if str(item).strip()]
    return value


def _card_blocks(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for idx, item in enumerate(items, 1):
        if "shot_no" in item:
            title = f"镜头 {item.get('shot_no') or idx}｜{item.get('duration', '')}"
            field_order = [
                ("visual", "画面"),
                ("subtitle_or_voiceover", "字幕/口播"),
                ("camera_movement", "运镜"),
                ("props", "道具"),
                ("edit_notes", "剪辑要点"),
            ]
        elif "page_no" in item:
            title = f"第 {item.get('page_no') or idx} 页｜{item.get('overlay_text', '')}"
            field_order = [
                ("image_prompt", "图片提示词"),
                ("overlay_text", "图上文字"),
                ("caption_note", "配文要点"),
            ]
        else:
            title = f"条目 {idx}"
            field_order = []
        blocks.append(_heading3(title))
        used = set()
        for key, label in field_order:
            value = item.get(key)
            used.add(key)
            if value not in (None, ""):
                blocks.append(_paragraph(f"{label}：{value}"))
        for key, value in item.items():
            if key in used or key in {"shot_no", "page_no", "duration", "evidence_asset_id"}:
                continue
            if value not in (None, ""):
                blocks.append(_paragraph(f"{key}：{value}"))
    return blocks


def _heading3(text: str) -> dict[str, Any]:
    return {"block_type": 5, "heading3": {"elements": [{"text_run": {"content": text}}]}}


def _chunks(text: str, size: int = 1700):
    text = str(text)
    return [text[i:i+size] for i in range(0, len(text), size)] or [""]


def append_storyboard_table(
    document_id: str,
    storyboard: list[dict[str, Any]],
    token: str,
    storyboard_image_assets: list[dict[str, Any]] | None = None,
    strict_images: bool = False,
) -> None:
    """Append a real Feishu Docx table for storyboard.

    Columns: 时间 / 画面 / 字幕/口播 / 声音/拍摄注意 / 画面图
    """
    if not storyboard:
        return
    cols = ["时间", "画面", "字幕/口播", "声音/拍摄注意", "画面图"]
    max_items_per_table = min(8, max(1, 50 // len(cols) - 1))
    image_paths_by_shot = {str(item.get("shot_no")): str(item.get("path") or "") for item in (storyboard_image_assets or []) if item.get("path")}
    image_paths_by_asset = {str(item.get("asset_id")): str(item.get("path") or "") for item in (storyboard_image_assets or []) if item.get("path")}
    for chunk_index, start in enumerate(range(0, len(storyboard), max_items_per_table), 1):
        chunk = storyboard[start:start + max_items_per_table]
        heading = "视频分镜表" if chunk_index == 1 else f"视频分镜表（续 {chunk_index}）"
        rows = len(chunk) + 1
        cell_ids = _create_docx_table(document_id, token, heading, rows, len(cols), "创建飞书视频分镜真表格失败")
        _fill_storyboard_table_cells(
            document_id,
            token,
            cell_ids,
            cols,
            chunk,
            image_paths_by_shot,
            image_paths_by_asset,
            strict_images,
            bool(storyboard_image_assets),
        )


def _fill_storyboard_table_cells(
    document_id: str,
    token: str,
    cell_ids: list[str],
    cols: list[str],
    storyboard: list[dict[str, Any]],
    image_paths_by_shot: dict[str, str],
    image_paths_by_asset: dict[str, str],
    strict_images: bool,
    has_storyboard_image_assets: bool,
) -> None:
    rows = len(storyboard) + 1
    for r in range(rows):
        for c in range(len(cols)):
            cell_id = cell_ids[r * len(cols) + c]
            if r == 0:
                content = cols[c]
            else:
                item = storyboard[r - 1]
                if c == 0:
                    content = str(item.get("duration") or item.get("time") or item.get("shot_no") or r)
                elif c == 1:
                    content = str(item.get("visual") or item.get("description") or "")
                elif c == 2:
                    content = str(item.get("subtitle") or item.get("voiceover") or item.get("subtitle_or_voiceover") or "")
                elif c == 3:
                    content = "；".join(
                        str(value).strip()
                        for value in (
                            item.get("camera_movement") or item.get("运镜") or "",
                            item.get("props") or "",
                            item.get("edit_notes") or "",
                        )
                        if str(value).strip()
                    )
                else:
                    content = ""
            if r > 0 and c == 4:
                row_item = storyboard[r - 1]
                shot_no = str(row_item.get("shot_no") or r)
                evidence_asset_id = str(row_item.get("evidence_asset_id") or "")
                image_path = image_paths_by_asset.get(evidence_asset_id) or image_paths_by_shot.get(shot_no, "")
                if image_path:
                    try:
                        _append_image_file_to_cell(document_id, cell_id, image_path, token, f"写入视频分镜画面图失败 row={r} col={c}")
                    except RuntimeError:
                        if strict_images:
                            raise
                        _append_cell_blocks(document_id, cell_id, [_paragraph("图片上传失败，保留文字分镜")], token, f"写入视频分镜图片失败占位 row={r} col={c}")
                else:
                    if strict_images:
                        raise RuntimeError(f"分镜表画面图缺少可插入图片路径：row={r} evidence_asset_id={evidence_asset_id}")
                    placeholder_text = "图片生成失败" if has_storyboard_image_assets else ""
                    if placeholder_text:
                        _append_cell_blocks(document_id, cell_id, [_paragraph(placeholder_text)], token, f"写入视频分镜图片占位失败 row={r} col={c}")
            else:
                if content:
                    _append_cell_blocks(document_id, cell_id, [_paragraph(content)], token, f"写入视频分镜文本失败 row={r} col={c}")


def append_image_post_table(
    document_id: str,
    image_post_script: list[dict[str, Any]],
    token: str,
    image_assets: list[dict[str, Any]],
    strict_images: bool = False,
) -> None:
    if not image_post_script:
        return
    image_paths_by_asset = {str(item.get("asset_id")): str(item.get("path") or "") for item in image_assets if item.get("path")}
    cols = ["时间", "画面", "字幕/口播", "声音/拍摄注意", "画面图"]
    rows = len(image_post_script) + 1
    cell_ids = _create_docx_table(document_id, token, "图文画面表", rows, len(cols), "创建飞书图文真表格失败")
    for r in range(rows):
        for c in range(len(cols)):
            cell_id = cell_ids[r * len(cols) + c]
            if r == 0:
                content = cols[c]
            else:
                item = image_post_script[r - 1]
                if c == 0:
                    content = str(item.get("duration") or item.get("page_no") or r)
                elif c == 1:
                    content = str(item.get("image_prompt") or "")
                elif c == 2:
                    content = str(item.get("overlay_text") or "")
                elif c == 3:
                    content = str(item.get("caption_note") or "")
                else:
                    content = ""
            if r > 0 and c == 4:
                item = image_post_script[r - 1]
                evidence_asset_id = str(item.get("evidence_asset_id") or "")
                image_path = image_paths_by_asset.get(evidence_asset_id, "")
                if not image_path:
                    if strict_images:
                        raise RuntimeError(f"图文表画面图缺少可插入图片路径：row={r} evidence_asset_id={evidence_asset_id}")
                else:
                    try:
                        _append_image_file_to_cell(document_id, cell_id, image_path, token, f"写入图文画面图失败 row={r} col={c}")
                    except RuntimeError:
                        if strict_images:
                            raise
                        _append_cell_blocks(document_id, cell_id, [_paragraph("图片上传失败，保留文字分镜")], token, f"写入图文表图片失败占位 row={r} col={c}")
            else:
                if content:
                    _append_cell_blocks(document_id, cell_id, [_paragraph(content)], token, f"写入图文表文本失败 row={r} col={c}")
