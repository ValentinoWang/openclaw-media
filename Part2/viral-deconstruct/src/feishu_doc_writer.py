from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from .config import load_config
from .feishu_writer import FEISHU_BASE, _headers, resolve_wiki_bitable, tenant_access_token
from .storyboard_images import generate_and_upload_storyboard_images, upload_feishu_doc_image

MAX_SOURCE_TEXT_CHARS_IN_DOC = 300


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


def create_doc(title: str, content: dict[str, Any], folder_token: str | None = None, doc_kind: str = "deconstruct") -> str:
    token = tenant_access_token()
    config = load_config()
    parent_node = config.feishu_wiki_parent_node_token
    if parent_node:
        space_id = _get_parent_space(parent_node, token)
        resp = requests.post(
            f"{FEISHU_BASE}/wiki/v2/spaces/{space_id}/nodes",
            headers=_headers(token),
            json={"obj_type": "docx", "parent_node_token": parent_node, "node_type": "origin", "title": title or "再创作脚本"},
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
        body: dict[str, Any] = {"title": title or "再创作脚本"}
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
    strict_storyboard_images = False
    if doc_kind == "deconstruct":
        assets = upload_evidence_assets(document_id, content.get("evidence_assets") or [], token)
        if storyboard:
            content["storyboard_image_assets"] = assets
            strict_storyboard_images = True
        if image_post_script:
            content["image_post_assets"] = assets
    if doc_kind == "recreate" and isinstance(storyboard, list) and storyboard:
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
        strict_storyboard_images = True
    append_blocks(document_id, content, token)
    if isinstance(storyboard, list) and storyboard:
        append_storyboard_table(
            document_id,
            storyboard,
            token,
            content.get("storyboard_image_assets") or [],
            strict_images=strict_storyboard_images,
        )
    if doc_kind == "deconstruct" and isinstance(image_post_script, list) and image_post_script:
        append_image_post_table(document_id, image_post_script, token, content.get("image_post_assets") or [])
    content["feishu_doc_url"] = f"https://tcnwueberajc.feishu.cn/docx/{document_id}"
    if node_token:
        content["feishu_wiki_url"] = f"https://tcnwueberajc.feishu.cn/wiki/{node_token}"
    return document_id


def upload_evidence_assets(document_id: str, evidence_assets: list[dict[str, Any]], token: str) -> list[dict[str, str]]:
    uploaded: list[dict[str, str]] = []
    if not evidence_assets:
        raise RuntimeError("拆解文档缺少视觉证据资产，不能创建画面图表格")
    for item in evidence_assets:
        asset_id = str(item.get("asset_id") or "").strip()
        path = str(item.get("path") or "").strip()
        if not asset_id or not path:
            raise RuntimeError(f"视觉证据资产缺少 asset_id/path：{item}")
        file_token = upload_feishu_doc_image(document_id, path, token, feishu_base=FEISHU_BASE)
        uploaded.append({"asset_id": asset_id, "path": path, "file_token": file_token, "kind": str(item.get("kind") or "")})
    return uploaded


def create_checked_doc(title: str, content: dict[str, Any], folder_token: str | None = None, doc_kind: str = "deconstruct") -> DocRef:
    document_id = create_doc(title, content, folder_token=folder_token, doc_kind=doc_kind)
    ref = assert_doc_accessible(document_id)
    content["feishu_doc_id"] = ref.document_id
    content["feishu_doc_url"] = ref.url
    if ref.wiki_url:
        content["feishu_wiki_url"] = ref.wiki_url
    return ref


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
    # Strict document whitelist: do not dump raw Part1 caption/comments into docs.
    for title, key in [
        ("创作定位", "creative_positioning"),
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


def _heading(text: str) -> dict[str, Any]:
    return {"block_type": 4, "heading2": {"elements": [{"text_run": {"content": text}}]}}


def _paragraph(text: str) -> dict[str, Any]:
    return {"block_type": 2, "text": {"elements": [{"text_run": {"content": text[:1800]}}]}}


def _value_blocks(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, str):
        return [_paragraph(chunk) for chunk in _chunks(value)]
    if isinstance(value, dict):
        return [_paragraph(f"{k}：{v}") for k, v in value.items()]
    if isinstance(value, list):
        if value and all(isinstance(item, dict) for item in value):
            return _card_blocks(value)
        return [_paragraph(f"{idx}. {item}") for idx, item in enumerate(value, 1)]
    return [_paragraph(str(value))]


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

    Columns: 画面图 / 描述 / 字幕 / 口播 / 运镜
    """
    if not storyboard:
        return
    cols = ["画面图", "描述", "字幕", "口播", "运镜"]
    rows = len(storyboard) + 1
    table_id = "storyboard_table"
    descendants: list[dict[str, Any]] = []
    children_ids = []
    table_cells = []
    image_tokens_by_shot = {str(item.get("shot_no")): str(item.get("file_token") or "") for item in (storyboard_image_assets or []) if item.get("file_token")}
    image_tokens_by_asset = {str(item.get("asset_id")): str(item.get("file_token") or "") for item in (storyboard_image_assets or []) if item.get("file_token")}
    # table block
    for r in range(rows):
        for c in range(len(cols)):
            cell_id = f"storyboard_cell_{r}_{c}"
            text_id = f"storyboard_text_{r}_{c}"
            table_cells.append(cell_id)
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
                token_value = image_tokens_by_asset.get(evidence_asset_id) or image_tokens_by_shot.get(shot_no, "")
                if token_value:
                    image_id = f"storyboard_image_{r}_{c}"
                    descendants.append({"block_id": cell_id, "block_type": 32, "table_cell": {}, "children": [image_id]})
                    descendants.append({"block_id": image_id, "block_type": 27, "image": {"token": token_value}, "children": []})
                else:
                    if strict_images:
                        raise RuntimeError(f"分镜表画面图缺少可插入图片：row={r} evidence_asset_id={evidence_asset_id}")
                    descendants.append({"block_id": cell_id, "block_type": 32, "table_cell": {}, "children": [text_id]})
                    descendants.append({"block_id": text_id, "block_type": 2, "text": {"elements": [{"text_run": {"content": "图片生成失败" if storyboard_image_assets else ""}}]}, "children": []})
            else:
                descendants.append({"block_id": cell_id, "block_type": 32, "table_cell": {}, "children": [text_id]})
                descendants.append({"block_id": text_id, "block_type": 2, "text": {"elements": [{"text_run": {"content": content[:1800]}}]}, "children": []})
    descendants.insert(0, {"block_id": table_id, "block_type": 31, "table": {"property": {"row_size": rows, "column_size": len(cols)}}, "children": table_cells})
    descendants.insert(0, {"block_id": "storyboard_heading", "block_type": 4, "heading2": {"elements": [{"text_run": {"content": "视频分镜表"}}]}, "children": []})
    body = {"index": 0, "children_id": ["storyboard_heading", table_id], "descendants": descendants}
    resp = requests.post(
        f"{FEISHU_BASE}/docx/v1/documents/{document_id}/blocks/{document_id}/descendant?document_revision_id=-1",
        headers=_headers(token),
        json=body,
        timeout=30,
    )
    try:
        payload = resp.json()
    except ValueError:
        payload = {"raw": resp.text}
    if resp.status_code >= 400 or payload.get("code") != 0:
        raise RuntimeError(f"写入飞书真表格失败 HTTP {resp.status_code}：{payload}")


def append_image_post_table(
    document_id: str,
    image_post_script: list[dict[str, Any]],
    token: str,
    image_assets: list[dict[str, Any]],
) -> None:
    if not image_post_script:
        return
    image_tokens_by_asset = {str(item.get("asset_id")): str(item.get("file_token") or "") for item in image_assets if item.get("file_token")}
    cols = ["画面图", "图片提示词", "图上文字", "配文要点"]
    rows = len(image_post_script) + 1
    table_id = "image_post_table"
    descendants: list[dict[str, Any]] = []
    table_cells: list[str] = []
    for r in range(rows):
        for c in range(len(cols)):
            cell_id = f"image_post_cell_{r}_{c}"
            text_id = f"image_post_text_{r}_{c}"
            table_cells.append(cell_id)
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
                token_value = image_tokens_by_asset.get(evidence_asset_id, "")
                if not token_value:
                    raise RuntimeError(f"图文表画面图缺少可插入图片：row={r} evidence_asset_id={evidence_asset_id}")
                image_id = f"image_post_image_{r}_{c}"
                descendants.append({"block_id": cell_id, "block_type": 32, "table_cell": {}, "children": [image_id]})
                descendants.append({"block_id": image_id, "block_type": 27, "image": {"token": token_value}, "children": []})
            else:
                descendants.append({"block_id": cell_id, "block_type": 32, "table_cell": {}, "children": [text_id]})
                descendants.append({"block_id": text_id, "block_type": 2, "text": {"elements": [{"text_run": {"content": content[:1800]}}]}, "children": []})
    descendants.insert(0, {"block_id": table_id, "block_type": 31, "table": {"property": {"row_size": rows, "column_size": len(cols)}}, "children": table_cells})
    descendants.insert(0, {"block_id": "image_post_heading", "block_type": 4, "heading2": {"elements": [{"text_run": {"content": "图文画面表"}}]}, "children": []})
    body = {"index": 0, "children_id": ["image_post_heading", table_id], "descendants": descendants}
    resp = requests.post(
        f"{FEISHU_BASE}/docx/v1/documents/{document_id}/blocks/{document_id}/descendant?document_revision_id=-1",
        headers=_headers(token),
        json=body,
        timeout=30,
    )
    try:
        payload = resp.json()
    except ValueError:
        payload = {"raw": resp.text}
    if resp.status_code >= 400 or payload.get("code") != 0:
        raise RuntimeError(f"写入飞书图文真表格失败 HTTP {resp.status_code}：{payload}")
