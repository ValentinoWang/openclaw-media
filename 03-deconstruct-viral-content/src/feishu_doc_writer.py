from __future__ import annotations

import ast
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import requests

from .config import load_config
from .feishu_writer import FEISHU_BASE, _headers, resolve_wiki_bitable, tenant_access_token
from .storyboard_images import generate_and_upload_storyboard_images, upload_feishu_doc_image

MAX_SOURCE_TEXT_CHARS_IN_DOC = 300
DOCX_WRITE_SLEEP_SEC = float(os.getenv("FEISHU_DOCX_WRITE_SLEEP_SEC", "0.35"))
SKIP_STORYBOARD_IMAGE_GENERATION = os.getenv("FEISHU_SKIP_STORYBOARD_IMAGE_GENERATION", "0").lower() in ("1", "true", "yes")
GENERATE_STORYBOARD_IMAGES = os.getenv("FEISHU_GENERATE_STORYBOARD_IMAGES", "0").lower() in ("1", "true", "yes")
DEFAULT_DECONSTRUCT_SOURCE_TABLE_URL = "https://tcnwueberajc.feishu.cn/wiki/GgOewSQVziIEaIkYoZYcs1c7nTh?table=tblk0OepolGAdDI8&view=vew8tLq1Yl"


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
    token = tenant_access_token()
    config = load_config()
    parent_node = _parent_node_for_doc_kind(config, doc_kind)
    reused_existing = False
    if parent_node:
        space_id = _get_parent_space(parent_node, token)
        existing = _find_child_doc(space_id, parent_node, title or "创作-再创脚本", token)
        if existing:
            document_id, node_token = existing
            reused_existing = True
        else:
            resp = requests.post(
                f"{FEISHU_BASE}/wiki/v2/spaces/{space_id}/nodes",
                headers=_headers(token),
                json={"obj_type": "docx", "parent_node_token": parent_node, "node_type": "origin", "title": title or "创作-再创脚本"},
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
        body: dict[str, Any] = {"title": title or "创作-再创脚本"}
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
    if doc_kind == "deconstruct":
        assets = prepare_evidence_assets(content.get("evidence_assets") or [])
        if is_video and storyboard:
            content["storyboard_image_assets"] = assets
            strict_storyboard_images = True
        if is_image_post and image_post_script:
            content["image_post_assets"] = assets
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
        _post_docx_children(
            document_id,
            document_id,
            [_heading(f"补充记录｜{time.strftime('%Y-%m-%d %H:%M')}")],
            token,
            "追加补充记录标题失败",
        )
    append_blocks(document_id, content, token)
    if is_video and isinstance(storyboard, list) and storyboard:
        append_storyboard_table(
            document_id,
            storyboard,
            token,
            content.get("storyboard_image_assets") or [],
            strict_images=strict_storyboard_images,
        )
    if doc_kind == "deconstruct" and is_image_post and isinstance(image_post_script, list) and image_post_script:
        append_image_post_table(document_id, image_post_script, token, content.get("image_post_assets") or [])
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
    source_table_url = str(config.feishu_bitable_url or DEFAULT_DECONSTRUCT_SOURCE_TABLE_URL).strip()
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
        _paragraph("这里是爆款内容积累表的拆解文档索引；每条拆解文档已作为本页下的独立子文档存放，标题按“爆款拆解文档｜主旨”命名。"),
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
    old_count = _document_child_count(document_id, token)
    append_blocks_raw(document_id, children, token)
    if old_count:
        resp = requests.delete(
            f"{FEISHU_BASE}/docx/v1/documents/{document_id}/blocks/{document_id}/children/batch_delete",
            params={"document_revision_id": -1},
            headers=_headers(token),
            json={"start_index": 0, "end_index": old_count},
            timeout=20,
        )
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("code") != 0:
            raise RuntimeError(f"清理飞书文档旧索引失败：{payload}")


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
    """Backward-compatible helper for callers that still need document-scoped upload."""
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


def append_blocks(document_id: str, content: dict[str, Any], token: str) -> None:
    blocks: list[dict[str, Any]] = []
    media_type = _content_media_type(content)
    # Strict document whitelist: do not dump raw content-ingest caption/comments into docs.
    for title, key in [
        ("创作定位", "creative_positioning"),
        ("总结", "content_summary"),
        ("原作品总结", "source_summary"),
        ("爆点机制", "viral_mechanism"),
        ("可直接发布脚本", "final_script"),
        ("视频分镜", "video_storyboard"),
        ("图文脚本", "image_post_script"),
        ("标题备选", "titles"),
        ("标签", "hashtags"),
        ("制作注意事项", "production_notes"),
        ("避重说明", "anti_copy_notes"),
        ("避重/改写建议", "avoid_plagiarism_notes"),
    ]:
        if media_type == "video" and key == "image_post_script":
            continue
        if media_type == "image_post" and key == "video_storyboard":
            continue
        value = content.get(key)
        if value in (None, "", []):
            continue
        blocks.append(_heading(title))
        blocks.extend(_value_blocks(value))
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

    Columns: 画面图 / 画面描述 / 字幕 / 口播 / 运镜
    """
    if not storyboard:
        return
    cols = ["画面图", "画面描述", "字幕", "口播", "运镜"]
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
                    content = ""
                elif c == 1:
                    content = str(item.get("visual") or item.get("description") or "")
                elif c == 2:
                    content = str(item.get("subtitle") or item.get("subtitle_or_voiceover") or "")
                elif c == 3:
                    content = str(item.get("voiceover") or item.get("口播") or "")
                else:
                    content = str(item.get("camera_movement") or item.get("运镜") or "")
            if r > 0 and c == 0:
                row_item = storyboard[r - 1]
                shot_no = str(row_item.get("shot_no") or r)
                evidence_asset_id = str(row_item.get("evidence_asset_id") or "")
                image_path = image_paths_by_asset.get(evidence_asset_id) or image_paths_by_shot.get(shot_no, "")
                if image_path:
                    _append_image_file_to_cell(document_id, cell_id, image_path, token, f"写入视频分镜画面图失败 row={r} col={c}")
                else:
                    if strict_images:
                        raise RuntimeError(f"分镜表画面图缺少可插入图片路径：row={r} evidence_asset_id={evidence_asset_id}")
                    fallback = "图片生成失败" if has_storyboard_image_assets else ""
                    if fallback:
                        _append_cell_blocks(document_id, cell_id, [_paragraph(fallback)], token, f"写入视频分镜图片占位失败 row={r} col={c}")
            else:
                if content:
                    _append_cell_blocks(document_id, cell_id, [_paragraph(content)], token, f"写入视频分镜文本失败 row={r} col={c}")


def append_image_post_table(
    document_id: str,
    image_post_script: list[dict[str, Any]],
    token: str,
    image_assets: list[dict[str, Any]],
) -> None:
    if not image_post_script:
        return
    image_paths_by_asset = {str(item.get("asset_id")): str(item.get("path") or "") for item in image_assets if item.get("path")}
    cols = ["画面图", "图片提示词", "图上文字", "配文要点"]
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
                    content = ""
                elif c == 1:
                    content = str(item.get("image_prompt") or "")
                elif c == 2:
                    content = str(item.get("overlay_text") or "")
                else:
                    content = str(item.get("caption_note") or "")
            if r > 0 and c == 0:
                item = image_post_script[r - 1]
                evidence_asset_id = str(item.get("evidence_asset_id") or "")
                image_path = image_paths_by_asset.get(evidence_asset_id, "")
                if not image_path:
                    raise RuntimeError(f"图文表画面图缺少可插入图片路径：row={r} evidence_asset_id={evidence_asset_id}")
                _append_image_file_to_cell(document_id, cell_id, image_path, token, f"写入图文画面图失败 row={r} col={c}")
            else:
                if content:
                    _append_cell_blocks(document_id, cell_id, [_paragraph(content)], token, f"写入图文表文本失败 row={r} col={c}")
