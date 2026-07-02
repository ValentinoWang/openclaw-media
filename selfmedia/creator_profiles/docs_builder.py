#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import requests

SELFMEDIA_ROOT = Path(__file__).resolve().parents[2]
if str(SELFMEDIA_ROOT) not in sys.path:
    sys.path.insert(0, str(SELFMEDIA_ROOT))

from common.social_runtime import (  # noqa: E402
    FEISHU_BASE,
    feishu_bitable_refs,
    feishu_ensure_fields,
    feishu_headers,
    feishu_list_records,
    feishu_plain_text,
    feishu_tenant_access_token,
    feishu_update_record,
)
from common.standard_fields import standard_field_specs  # noqa: E402
from selfmedia.creator_profiles.registry_sync import normalize_platform, normalize_platform_id  # noqa: E402


DEFAULT_CREATOR_REGISTRY_URL = (
    "https://tcnwueberajc.feishu.cn/wiki/WYaCwyPxpiYM02kzclJcJPC9n9b"
    "?table=tbli9yjd7DtTjqcV&view=vewxOPQ7ei"
)
DEFAULT_PARENT_NODE_TOKEN = "WYaCwyPxpiYM02kzclJcJPC9n9b"


def heading2(text: str) -> dict[str, Any]:
    return {"block_type": 4, "heading2": {"elements": [{"text_run": {"content": text[:500]}}]}}


def paragraph(text: str) -> dict[str, Any]:
    return {"block_type": 2, "text": {"elements": [{"text_run": {"content": str(text)[:1800]}}]}}


def get_wiki_node(node_token: str, token: str) -> dict[str, Any]:
    resp = requests.get(
        f"{FEISHU_BASE}/wiki/v2/spaces/get_node",
        params={"token": node_token},
        headers=feishu_headers(token),
        timeout=20,
    )
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("code") != 0:
        raise RuntimeError(f"获取知识库节点失败：{payload}")
    return payload.get("data", {}).get("node") or {}


def find_child_doc(space_id: str, parent_node_token: str, title: str, token: str) -> tuple[str, str] | None:
    page_token = ""
    while True:
        params: dict[str, Any] = {"parent_node_token": parent_node_token, "page_size": 50}
        if page_token:
            params["page_token"] = page_token
        resp = requests.get(
            f"{FEISHU_BASE}/wiki/v2/spaces/{space_id}/nodes",
            params=params,
            headers=feishu_headers(token),
            timeout=20,
        )
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("code") != 0:
            raise RuntimeError(f"查询知识库子节点失败：{payload}")
        data = payload.get("data", {}) or {}
        for item in data.get("items", []) or []:
            if str(item.get("title") or "").strip() != title.strip():
                continue
            if str(item.get("obj_type") or "").lower() != "docx":
                continue
            return str(item.get("obj_token") or ""), str(item.get("node_token") or "")
        if not data.get("has_more"):
            break
        page_token = str(data.get("page_token") or "")
        if not page_token:
            break
    return None


def create_or_reuse_doc(parent_node_token: str, title: str, token: str) -> tuple[str, str, bool]:
    parent = get_wiki_node(parent_node_token, token)
    space_id = str(parent.get("space_id") or "")
    if not space_id:
        raise RuntimeError("目标知识库节点缺少 space_id")
    existing = find_child_doc(space_id, parent_node_token, title, token)
    if existing:
        return existing[0], existing[1], True
    resp = requests.post(
        f"{FEISHU_BASE}/wiki/v2/spaces/{space_id}/nodes",
        headers=feishu_headers(token),
        json={"obj_type": "docx", "parent_node_token": parent_node_token, "node_type": "origin", "title": title},
        timeout=20,
    )
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("code") != 0:
        raise RuntimeError(f"创建博主档案文档失败：{payload}")
    node = payload.get("data", {}).get("node") or {}
    return str(node.get("obj_token") or ""), str(node.get("node_token") or ""), False


def append_doc_blocks(document_id: str, blocks: list[dict[str, Any]], token: str) -> None:
    for i in range(0, len(blocks), 20):
        resp = requests.post(
            f"{FEISHU_BASE}/docx/v1/documents/{document_id}/blocks/{document_id}/children?document_revision_id=-1",
            headers=feishu_headers(token),
            json={"children": blocks[i:i + 20], "index": -1},
            timeout=20,
        )
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("code") != 0:
            raise RuntimeError(f"写入博主档案文档失败：{payload}")


def non_empty_lines(values: list[str]) -> str:
    return "\n".join(item for item in values if item)


def aggregate_creator_rows(records: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        fields = record.get("fields") or {}
        creator_ip = feishu_plain_text(fields.get("博主IP"))
        if creator_ip:
            grouped[creator_ip].append(record)
    return grouped


def creator_doc_blocks(creator_ip: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    schools: list[str] = []
    tags: list[str] = []
    tracks: list[str] = []
    account_lines: list[str] = []
    for record in rows:
        fields = record.get("fields") or {}
        school = feishu_plain_text(fields.get("院校背景"))
        if school and school not in schools:
            schools.append(school)
        raw_tags = feishu_plain_text(fields.get("关键词标签"))
        if raw_tags and raw_tags not in tags:
            tags.append(raw_tags)
        raw_track = fields.get("赛道")
        if isinstance(raw_track, list):
            for item in raw_track:
                text = feishu_plain_text(item)
                if text and text not in tracks:
                    tracks.append(text)
        else:
            text = feishu_plain_text(raw_track)
            if text and text not in tracks:
                tracks.append(text)
        platform = normalize_platform(fields.get("平台"))
        native_platform_id = normalize_platform_id(fields.get("平台ID"))
        fans_k = feishu_plain_text(fields.get("粉丝数(k)"))
        account_lines.append(
            non_empty_lines(
                [
                    f"平台：{platform or '待补'}",
                    f"平台ID：{native_platform_id or '待补'}",
                    f"主页链接：{feishu_plain_text(fields.get('主页链接')) or '待补'}",
                    f"账号名称：{feishu_plain_text(fields.get('账号名称')) or '待补'}",
                    f"作者ID：{feishu_plain_text(fields.get('作者ID')) or '待补'}",
                    f"粉丝数(k)：{fans_k or '待补'}",
                ]
            )
        )

    return [
        heading2(f"博主信息档案｜{creator_ip}"),
        paragraph(
            non_empty_lines(
                [
                    f"生成时间：{time.strftime('%Y-%m-%d %H:%M:%S')}",
                    f"博主IP：{creator_ip}",
                    f"院校背景：{'、'.join(schools) if schools else '待补'}",
                    f"赛道：{'、'.join(tracks) if tracks else '待补'}",
                ]
            )
        ),
        heading2("一、标签与画像"),
        paragraph("\n\n".join(tags) if tags else "待补"),
        heading2("二、平台账号清单"),
        *[paragraph(f"{idx}. {line}") for idx, line in enumerate(account_lines, start=1)],
        heading2("三、锚点补充清单"),
        paragraph(
            non_empty_lines(
                [
                    "优先顺序：",
                    "1. 平台ID",
                    "2. 主页链接",
                    "3. 平台 + 账号名称",
                    "4. 平台 + 作者ID",
                    "",
                    "当前要求：",
                    "- 不伪造主页链接、账号名称、作者ID。",
                    "- 平台ID 保留原始平台账号，不生成内部派生 ID。",
                    "- 缺失锚点保留“待补”，用于后续人工补全。",
                ]
            )
        ),
    ]


def ensure_registry_fields(creator_url: str, token: str) -> None:
    app_token, table_id, token = feishu_bitable_refs(creator_url, token)
    specs = {
        "主页链接": standard_field_specs()["主页链接"],
        "账号名称": standard_field_specs()["账号名称"],
        "作者ID": standard_field_specs()["作者ID"],
        "博主IP": standard_field_specs()["博主IP"],
        "平台ID": standard_field_specs()["平台ID"],
        "院校背景": standard_field_specs()["院校背景"],
        "粉丝数(k)": standard_field_specs()["粉丝数(k)"],
        "作品数": standard_field_specs()["作品数"],
        "关键词标签": standard_field_specs()["关键词标签"],
        "主状态": standard_field_specs()["主状态"],
        "创作者主档链接": standard_field_specs()["创作者主档链接"],
        "文档链接JSON": standard_field_specs()["文档链接JSON"],
    }
    feishu_ensure_fields(app_token, table_id, token, specs)


def registry_update_specs() -> dict[str, int]:
    return {
        "创作者主档链接": standard_field_specs()["创作者主档链接"],
        "文档链接JSON": standard_field_specs()["文档链接JSON"],
    }


def build_row_update(fields: dict[str, Any], creator_ip: str, wiki_url: str) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    existing_creator_doc = feishu_plain_text(fields.get("创作者主档链接"))
    if wiki_url and existing_creator_doc != wiki_url:
        payload["创作者主档链接"] = wiki_url
    existing_doc_json = feishu_plain_text(fields.get("文档链接JSON"))
    if wiki_url and existing_doc_json != wiki_url:
        payload["文档链接JSON"] = {"creator_doc": wiki_url}
    return payload


def build_creator_docs(
    creator_url: str,
    parent_node_token: str,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    token = feishu_tenant_access_token()
    ensure_registry_fields(creator_url, token)
    records = feishu_list_records(creator_url, token=token, page_size=500)
    grouped = aggregate_creator_rows(records)
    created_docs: list[dict[str, Any]] = []
    updated_rows: list[dict[str, Any]] = []
    for creator_ip, rows in grouped.items():
        title = f"博主信息档案｜{creator_ip}"
        if dry_run:
            document_id = ""
            node_token = ""
            reused = False
            wiki_url = ""
        else:
            document_id, node_token, reused = create_or_reuse_doc(parent_node_token, title, token)
            wiki_url = f"https://tcnwueberajc.feishu.cn/wiki/{node_token}"
            if not reused:
                append_doc_blocks(document_id, creator_doc_blocks(creator_ip, rows), token)
        created_docs.append({"博主IP": creator_ip, "document_id": document_id, "wiki_url": wiki_url, "rows": len(rows)})
        for record in rows:
            record_id = str(record.get("record_id") or "")
            fields = record.get("fields") or {}
            payload = build_row_update(fields, creator_ip, wiki_url)
            if not payload:
                continue
            updated_rows.append({"record_id": record_id, "博主IP": creator_ip, "fields": sorted(payload)})
            if not dry_run:
                feishu_update_record(
                    creator_url,
                    record_id,
                    payload,
                    specs=registry_update_specs(),
                    token=token,
                )
    return {
        "ok": True,
        "dry_run": dry_run,
        "creators": len(grouped),
        "docs": created_docs,
        "updated_rows": updated_rows,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create creator docs under a wiki node and sync registry fields.")
    parser.add_argument("--creator-url", default=DEFAULT_CREATOR_REGISTRY_URL, help="Creator registry table URL.")
    parser.add_argument("--parent-node-token", default=DEFAULT_PARENT_NODE_TOKEN, help="Wiki parent node token.")
    parser.add_argument("--write", action="store_true", help="Actually write docs and update table. Default is dry-run.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = build_creator_docs(
        args.creator_url,
        args.parent_node_token,
        dry_run=not args.write,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
