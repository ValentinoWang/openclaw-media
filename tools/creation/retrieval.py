from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import requests

from common.social_runtime import (
    FEISHU_BASE,
    feishu_bitable_refs,
    feishu_headers,
    feishu_list_records,
    feishu_tenant_access_token,
    load_default_env_files,
    load_env_file,
)


DEFAULT_CONTENT_CONFIG = Path("/home/ubuntu/openclaw-feishu-reminder/wiki-content-config.json")
DEFAULT_ACTIVITY_CONFIG = Path("/home/ubuntu/openclaw-feishu-reminder/wiki-activity-config.json")
DEFAULT_INSPIRATION_URL = (
    "https://tcnwueberajc.feishu.cn/wiki/UkSMwA36fiZuBdkk63ncnm84n0e"
    "?fromScene=spaceOverview&table=tbl3tNirtYn3eOUr&view=vewAaVJP2U"
)
MEDIA_ENV_FILES = (
    Path("/home/ubuntu/openclaw-agents/media/.env"),
    Path("/home/ubuntu/openclaw-agents/media/.env.local"),
)
BUSINESS_URL_ENV_NAMES = (
    "MEDIA_OS_BUSINESS_URL",
)


def load_rows_for_creation(*, viral_url: str = "", activity_url: str = "", limit: int = 300) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    load_default_env_files()
    viral = list_records_safe(resolve_viral_bitable_url(viral_url), limit=limit)
    activity = list_records_safe(resolve_activity_bitable_url(activity_url), limit=limit)
    return viral, activity


def load_business_rows_for_creation(*, business_url: str = "", limit: int = 300) -> list[dict[str, Any]]:
    load_creation_env_files()
    return list_records_safe(resolve_business_bitable_url(business_url), limit=limit)


def load_inspiration_rows_for_creation(*, inspiration_url: str = "", limit: int = 300) -> list[dict[str, Any]]:
    load_creation_env_files()
    return list_records_safe(resolve_inspiration_bitable_url(inspiration_url), limit=limit)


def list_records_safe(bitable_url: str, *, limit: int = 300) -> list[dict[str, Any]]:
    if not bitable_url:
        return []
    records = feishu_list_records(bitable_url, page_size=min(limit, 500))
    return records[:limit]


def resolve_viral_bitable_url(explicit: str = "") -> str:
    if explicit:
        return explicit
    env_url = os.getenv("MEDIA_OS_VIRAL_URL")
    if env_url:
        return env_url
    cfg = _load_json(DEFAULT_CONTENT_CONFIG)
    return _bitable_url_from_config(cfg)


def resolve_activity_bitable_url(explicit: str = "") -> str:
    if explicit:
        return explicit
    env_url = os.getenv("MEDIA_OS_ACTIVITY_URL")
    if env_url:
        return env_url
    cfg = _load_json(DEFAULT_ACTIVITY_CONFIG)
    return _bitable_url_from_config(cfg)


def resolve_business_bitable_url(explicit: str = "") -> str:
    if explicit:
        return explicit
    load_creation_env_files()
    for name in BUSINESS_URL_ENV_NAMES:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""


def resolve_inspiration_bitable_url(explicit: str = "") -> str:
    if explicit:
        return explicit
    load_creation_env_files()
    for name in ("MEDIA_OS_INSPIRATION_URL", "MEDIA_OS_CREATION_INSPIRATION_URL"):
        value = os.getenv(name, "").strip()
        if value:
            return value
    return DEFAULT_INSPIRATION_URL


def load_creation_env_files() -> None:
    load_default_env_files()
    for path in MEDIA_ENV_FILES:
        load_env_file(path)


def read_reference_docs(doc_urls: list[str], *, max_chars_per_doc: int = 1800) -> list[dict[str, str]]:
    load_default_env_files()
    token = feishu_tenant_access_token()
    results: list[dict[str, str]] = []
    for url in doc_urls:
        document_id = _extract_docx_token(url)
        if not document_id:
            continue
        try:
            content = read_docx_raw_content(document_id, token)
        except Exception as exc:
            results.append({"url": url, "content": "", "error": str(exc)})
            continue
        results.append({"url": url, "content": content[:max_chars_per_doc], "error": ""})
    return results


def read_docx_raw_content(document_id: str, token: str) -> str:
    resp = requests.get(
        f"{FEISHU_BASE}/docx/v1/documents/{document_id}/raw_content",
        headers=feishu_headers(token),
        timeout=20,
    )
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("code") != 0:
        raise RuntimeError(f"读取飞书文档纯文本失败：{payload}")
    return str((payload.get("data") or {}).get("content") or "")


def resolve_wiki_node(token_value: str) -> dict[str, Any]:
    load_default_env_files()
    token = feishu_tenant_access_token()
    resp = requests.get(
        f"{FEISHU_BASE}/wiki/v2/spaces/get_node",
        params={"token": token_value},
        headers=feishu_headers(token),
        timeout=15,
    )
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("code") != 0:
        raise RuntimeError(f"获取知识库节点失败：{payload}")
    return payload.get("data", {}).get("node") or {}


def bitable_refs_from_url(bitable_url: str) -> tuple[str, str, str]:
    load_default_env_files()
    return feishu_bitable_refs(bitable_url)


def _bitable_url_from_config(cfg: dict[str, Any]) -> str:
    url = str(cfg.get("url") or "").strip()
    app_token = str(cfg.get("app_token") or cfg.get("node_token") or "").strip()
    table_id = str(cfg.get("table_id") or "").strip()
    if url and "table=" in url:
        return url
    if url and table_id:
        joiner = "&" if "?" in url else "?"
        return f"{url}{joiner}table={table_id}"
    if app_token and table_id:
        return f"https://tcnwueberajc.feishu.cn/base/{app_token}?table={table_id}"
    return url


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _extract_docx_token(url: str) -> str:
    text = str(url or "").strip()
    if "/docx/" in text:
        return text.split("/docx/", 1)[1].split("?", 1)[0].split("#", 1)[0].strip("/")
    if text.startswith("dox") or text.startswith("doc"):
        return text
    return ""
