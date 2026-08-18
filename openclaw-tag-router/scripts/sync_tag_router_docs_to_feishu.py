#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.parse
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import requests


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT))
from openclaw_app.services.feishu_docx_renderer import expand_inline_code_literal_newlines  # noqa: E402
from openclaw_app.services.feishu_docx_table_limits import (  # noqa: E402
    chunk_docx_table_rows,
    ensure_docx_tables_write_budget,
    ensure_docx_table_write_budget,
    sleep_seconds_for_docx_write,
    validate_docx_table_create_shape,
)

CONFIG_PATH = PLUGIN_ROOT / "config" / "docs_sync.json"
DOC_PATH = Path("/home/ubuntu/docs/说明书/OpenClaw 标签功能说明.md")
GENERIC_FEISHU_BASE = os.getenv("FEISHU_API_BASE_URL", "https://open.feishu.cn/open-apis").rstrip("/")
GENERIC_TENANT_HOST = "https://tcnwueberajc.feishu.cn"
DEEPMATH_PUBLIC_HOST = "https://feishu.cn"
FEISHU_BASE = GENERIC_FEISHU_BASE
TENANT_HOST = GENERIC_TENANT_HOST
ENV_FILES = [
    Path("/home/ubuntu/.openclaw/openclaw.env"),
    Path("/home/ubuntu/.openclaw/openclaw-media.env"),
    Path("/home/ubuntu/openclaw-feishu-reminder/reminder.env"),
]
DEEPMATH_ENV_FILE = Path("/home/ubuntu/.openclaw-deepmath/openclaw.env")
WRITE_SLEEP_SEC = sleep_seconds_for_docx_write()
REQUEST_TIMEOUT_SEC = int(os.getenv("FEISHU_DOC_SYNC_REQUEST_TIMEOUT_SEC", "90"))
WRITE_TIMEOUT_SEC = int(os.getenv("FEISHU_DOC_SYNC_WRITE_TIMEOUT_SEC", "120"))
RAW_CONTENT_TIMEOUT_SEC = int(os.getenv("FEISHU_DOC_SYNC_RAW_TIMEOUT_SEC", "180"))
REQUEST_RETRIES = int(os.getenv("FEISHU_DOC_SYNC_RETRIES", "8"))


def parse_env_file(env_path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not env_path.exists():
        return values
    for raw_line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key.lower() in {"http_proxy", "https_proxy", "all_proxy", "no_proxy"}:
            continue
        if key and value:
            values[key] = value
    return values


def load_env_files(env_files: list[Path] | tuple[Path, ...] = tuple(ENV_FILES)) -> None:
    for env_path in env_files:
        if not env_path.exists():
            continue
        for key, value in parse_env_file(env_path).items():
            if key not in os.environ:
                os.environ[key] = value


def is_deepmath_config(config: dict[str, Any] | None) -> bool:
    if not isinstance(config, dict):
        return False
    profile = str(config.get("credential_profile") or config.get("bot") or config.get("key") or "").strip().lower()
    title = str(config.get("doc_title") or "").strip().lower()
    return profile == "deepmath" or "deepmath" in title


def deepmath_env_values(config: dict[str, Any]) -> dict[str, str]:
    configured_path = Path(str(config.get("env_file") or DEEPMATH_ENV_FILE)).expanduser()
    if configured_path != DEEPMATH_ENV_FILE:
        raise RuntimeError(f"DeepMath doc sync must use the dedicated env file: {DEEPMATH_ENV_FILE}")
    return parse_env_file(DEEPMATH_ENV_FILE)


def configure_sync_target(config: dict[str, Any]) -> None:
    global FEISHU_BASE, TENANT_HOST
    if not is_deepmath_config(config):
        FEISHU_BASE = GENERIC_FEISHU_BASE
        TENANT_HOST = GENERIC_TENANT_HOST
        return

    values = deepmath_env_values(config)
    api_base_env = str(config.get("api_base_env") or "OPENCLAW_DEEPMATH_FEISHU_API_BASE_URL")
    host_env = str(config.get("tenant_host_env") or "OPENCLAW_DEEPMATH_TENANT_HOST")
    FEISHU_BASE = str(
        os.getenv(api_base_env)
        or values.get(api_base_env)
        or os.getenv("FEISHU_API_BASE_URL")
        or values.get("FEISHU_API_BASE_URL")
        or "https://open.feishu.cn/open-apis"
    ).rstrip("/")
    configured_host = (
        os.getenv(host_env)
        or values.get(host_env)
        or os.getenv("OPENCLAW_DEEPMATH_FEISHU_HOST")
        or values.get("OPENCLAW_DEEPMATH_FEISHU_HOST")
        or config.get("tenant_host")
    )
    if not configured_host:
        configured_url = str(config.get("wiki_url") or config.get("doc_url") or "").strip()
        parsed = urllib.parse.urlparse(configured_url)
        if parsed.scheme and parsed.netloc:
            configured_host = f"{parsed.scheme}://{parsed.netloc}"
    TENANT_HOST = str(configured_host or DEEPMATH_PUBLIC_HOST).strip().rstrip("/")


def request_json(method: str, path: str, token: str | None = None, **kwargs: Any) -> dict[str, Any]:
    headers = kwargs.pop("headers", {})
    if token:
        headers["Authorization"] = f"Bearer {token}"
    headers.setdefault("Content-Type", "application/json; charset=utf-8")
    timeout = kwargs.pop("timeout", REQUEST_TIMEOUT_SEC)
    last_error: Exception | None = None
    for attempt in range(REQUEST_RETRIES):
        try:
            resp = requests.request(method, f"{FEISHU_BASE}{path}", headers=headers, timeout=timeout, **kwargs)
        except (requests.Timeout, requests.ConnectionError) as exc:
            last_error = exc
            if attempt < REQUEST_RETRIES - 1:
                sleep_seconds = min(12.0, 1.5 + attempt * 1.5)
                print(
                    f"[feishu-doc-sync] retry {attempt + 1}/{REQUEST_RETRIES} after network timeout: {method} {path}",
                    file=sys.stderr,
                )
                time.sleep(sleep_seconds)
                continue
            raise RuntimeError(f"{method} {path} failed after network retries: {exc}") from exc
        try:
            payload = resp.json()
        except ValueError:
            payload = {"raw": resp.text}
        failed = resp.status_code >= 400 or payload.get("code") not in (None, 0)
        if not failed:
            return payload
        retryable_code = payload.get("code") in {1770002, 1770024}
        retryable_status = resp.status_code >= 500
        if (retryable_code or retryable_status) and attempt < REQUEST_RETRIES - 1:
            time.sleep(1.2 + attempt * 0.3)
            continue
        raise RuntimeError(f"{method} {path} failed: HTTP {resp.status_code} {payload}")
    raise RuntimeError(f"{method} {path} failed after retries: {last_error}")


def tenant_access_token(config: dict[str, Any] | None = None) -> str:
    if is_deepmath_config(config):
        selected_config = config or {}
        values = deepmath_env_values(selected_config)
        app_id_env = "OPENCLAW_DEEPMATH_APP_ID"
        app_secret_env = "OPENCLAW_DEEPMATH_APP_SECRET"
        app_id = str(os.getenv(app_id_env) or values.get(app_id_env) or "").strip()
        app_secret = str(os.getenv(app_secret_env) or values.get(app_secret_env) or "").strip()
        if not app_id or not app_secret:
            raise RuntimeError(f"{app_id_env} / {app_secret_env} not configured in the dedicated DeepMath env")
    else:
        load_env_files()
        app_id = os.getenv("FEISHU_APP_ID", "").strip()
        app_secret = os.getenv("FEISHU_APP_SECRET", "").strip()
        if not app_id or not app_secret:
            raise RuntimeError("FEISHU_APP_ID / FEISHU_APP_SECRET not configured")
    payload = request_json(
        "POST",
        "/auth/v3/tenant_access_token/internal",
        json={"app_id": app_id, "app_secret": app_secret},
        token=None,
    )
    token = payload.get("tenant_access_token")
    if not token:
        raise RuntimeError(f"tenant_access_token missing from response: {payload}")
    return str(token)


def load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        return {}
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def save_config(config: dict[str, Any]) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def source_text_and_hash() -> tuple[str, str]:
    text = DOC_PATH.read_text(encoding="utf-8")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return text, digest


def create_cloud_doc(config: dict[str, Any], token: str) -> tuple[str, str, str, str]:
    title = str(config.get("doc_title") or "OpenClaw 标签功能说明")
    parent_node = str(config.get("wiki_parent_node_token") or "").strip()
    if parent_node:
        parent_payload = request_json("GET", "/wiki/v2/spaces/get_node", token=token, params={"token": parent_node})
        node = parent_payload.get("data", {}).get("node", {})
        space_id = node.get("space_id")
        if not space_id:
            raise RuntimeError(f"cannot resolve wiki parent space_id: {parent_payload}")
        create_payload = request_json(
            "POST",
            f"/wiki/v2/spaces/{space_id}/nodes",
            token=token,
            json={
                "obj_type": "docx",
                "parent_node_token": parent_node,
                "node_type": "origin",
                "title": title,
            },
            timeout=30,
        )
        created = create_payload.get("data", {}).get("node", {})
        document_id = str(created.get("obj_token") or "")
        wiki_node_token = str(created.get("node_token") or "")
        if not document_id:
            raise RuntimeError(f"created wiki doc did not return obj_token: {create_payload}")
        return (
            document_id,
            f"{TENANT_HOST}/docx/{document_id}",
            f"{TENANT_HOST}/wiki/{wiki_node_token}" if wiki_node_token else "",
            wiki_node_token,
        )

    create_payload = request_json("POST", "/docx/v1/documents", token=token, json={"title": title}, timeout=30)
    document = create_payload.get("data", {}).get("document", {})
    document_id = str(document.get("document_id") or create_payload.get("data", {}).get("document_id") or "")
    if not document_id:
        raise RuntimeError(f"created doc did not return document_id: {create_payload}")
    return document_id, f"{TENANT_HOST}/docx/{document_id}", "", ""


def get_cloud_doc(config: dict[str, Any], token: str) -> tuple[str, dict[str, Any]]:
    document_id = str(config.get("document_id") or "").strip()
    if document_id:
        request_json("GET", f"/docx/v1/documents/{document_id}", token=token)
        return document_id, config
    document_id, doc_url, wiki_url, wiki_node_token = create_cloud_doc(config, token)
    config["document_id"] = document_id
    config["doc_url"] = doc_url
    config["wiki_url"] = wiki_url
    config["wiki_node_token"] = wiki_node_token
    save_config(config)
    return document_id, config


def configure_source_paths(doc_path: str = "", config_path: str = "") -> None:
    global DOC_PATH, CONFIG_PATH
    if doc_path:
        DOC_PATH = Path(doc_path).expanduser()
    if config_path:
        candidate = Path(config_path).expanduser()
        CONFIG_PATH = candidate if candidate.is_absolute() else PLUGIN_ROOT / candidate


def list_root_children(
    document_id: str,
    token: str,
    *,
    page_size: int = 100,
    max_items: int | None = None,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    page_token = ""
    while True:
        remaining = max_items - len(items) if max_items is not None else page_size
        params: dict[str, Any] = {
            "page_size": max(1, min(page_size, remaining)),
            "document_revision_id": -1,
        }
        if page_token:
            params["page_token"] = page_token
        payload = request_json(
            "GET",
            f"/docx/v1/documents/{document_id}/blocks/{document_id}/children",
            token=token,
            params=params,
        )
        data = payload.get("data", {})
        batch = data.get("items") or data.get("children") or []
        items.extend(item for item in batch if isinstance(item, dict))
        if max_items is not None and len(items) >= max_items:
            break
        if not data.get("has_more"):
            break
        page_token = str(data.get("page_token") or "")
        if not page_token:
            break
    return items


def clear_doc(document_id: str, token: str) -> None:
    print(f"[feishu-doc-sync] clearing document {document_id}", file=sys.stderr)
    while True:
        children = list_root_children(document_id, token, page_size=20, max_items=20)
        if not children:
            return
        # Feishu rejects larger root delete ranges in some partially-synced docs.
        end_index = min(len(children), 20)
        request_json(
            "DELETE",
            f"/docx/v1/documents/{document_id}/blocks/{document_id}/children/batch_delete",
            token=token,
            params={"document_revision_id": -1},
            json={"start_index": 0, "end_index": end_index},
            timeout=WRITE_TIMEOUT_SEC,
        )
        time.sleep(WRITE_SLEEP_SEC)


def delete_root_children_from(document_id: str, token: str, start_index: int) -> None:
    children = list_root_children(document_id, token)
    if len(children) <= start_index:
        return
    request_json(
        "DELETE",
        f"/docx/v1/documents/{document_id}/blocks/{document_id}/children/batch_delete",
        token=token,
        params={"document_revision_id": -1},
        json={"start_index": start_index, "end_index": len(children)},
        timeout=WRITE_TIMEOUT_SEC,
    )
    time.sleep(WRITE_SLEEP_SEC)


def text_run(content: str) -> dict[str, Any]:
    return {"text_run": {"content": content[:1800]}}


def heading_block(text: str, level: int) -> dict[str, Any]:
    block_type = {1: 3, 2: 4, 3: 5}.get(level, 6)
    key = {1: "heading1", 2: "heading2", 3: "heading3"}.get(level, "heading4")
    return {"block_type": block_type, key: {"elements": [text_run(text)]}}


def paragraph_block(text: str) -> dict[str, Any]:
    text = expand_inline_code_literal_newlines(text)
    return {"block_type": 2, "text": {"elements": [text_run(text)]}}


def split_long_line(line: str, limit: int = 1600) -> list[str]:
    if len(line) <= limit:
        return [line]
    return [line[i : i + limit] for i in range(0, len(line), limit)]


def is_table_row(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("|") and stripped.endswith("|") and stripped.count("|") >= 2


def is_table_separator(line: str) -> bool:
    if not is_table_row(line):
        return False
    cells = split_table_row(line)
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell.strip()) for cell in cells)


def split_table_row(line: str) -> list[str]:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    cells: list[str] = []
    current: list[str] = []
    in_code = False
    escaped = False
    for char in stripped:
        if escaped:
            current.append(char)
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == "`":
            in_code = not in_code
            current.append(char)
            continue
        if char == "|" and not in_code:
            cells.append("".join(current).strip())
            current = []
            continue
        current.append(char)
    cells.append("".join(current).strip())
    return cells


def cell_text(value: str) -> str:
    text = expand_inline_code_literal_newlines(value).strip()
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1：\2", text)
    text = text.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
    return text


def parse_markdown_table(lines: list[str]) -> list[list[str]]:
    if len(lines) < 2 or not is_table_separator(lines[1]):
        return []
    header = [cell_text(cell) for cell in split_table_row(lines[0])]
    rows = [[cell_text(cell) for cell in split_table_row(line)] for line in lines[2:] if is_table_row(line)]
    column_count = max([len(header), *(len(row) for row in rows)] or [0])
    if column_count == 0:
        return []

    def normalize(row: list[str]) -> list[str]:
        if len(row) < column_count:
            return row + [""] * (column_count - len(row))
        return row[:column_count]

    return [normalize(header), *(normalize(row) for row in rows)]


def markdown_to_parts(markdown: str, source_hash: str) -> list[dict[str, Any]]:
    parts: list[dict[str, Any]] = []
    pending_blocks: list[dict[str, Any]] = []

    def flush_blocks() -> None:
        if pending_blocks:
            parts.append({"kind": "blocks", "blocks": list(pending_blocks)})
            pending_blocks.clear()

    in_code = False
    in_html_comment = False
    lines = markdown.splitlines()
    index = 0
    while index < len(lines):
        raw_line = lines[index]
        line = raw_line.rstrip()
        stripped = line.strip()
        if not line:
            index += 1
            continue
        if in_html_comment:
            if "-->" in stripped:
                in_html_comment = False
            index += 1
            continue
        if stripped.startswith("<!--"):
            if "-->" not in stripped:
                in_html_comment = True
            index += 1
            continue
        if line.startswith("```"):
            in_code = not in_code
            pending_blocks.append(paragraph_block(line))
            index += 1
            continue
        if in_code:
            for chunk in split_long_line(line):
                pending_blocks.append(paragraph_block(chunk))
            index += 1
            continue
        if index + 1 < len(lines) and is_table_row(line) and is_table_separator(lines[index + 1]):
            table_lines = [line, lines[index + 1].rstrip()]
            index += 2
            while index < len(lines) and is_table_row(lines[index]):
                table_lines.append(lines[index].rstrip())
                index += 1
            table = parse_markdown_table(table_lines)
            if table:
                flush_blocks()
                parts.append({"kind": "table", "rows": table})
            else:
                for table_line in table_lines:
                    pending_blocks.append(paragraph_block(table_line))
            continue
        match = re.match(r"^(#{1,4})\s+(.+)$", line)
        if match:
            pending_blocks.append(heading_block(match.group(2).strip(), min(len(match.group(1)), 4)))
            index += 1
            continue
        for chunk in split_long_line(line):
            pending_blocks.append(paragraph_block(chunk))
        index += 1
    flush_blocks()
    return parts


def append_blocks(document_id: str, token: str, blocks: list[dict[str, Any]]) -> None:
    for i in range(0, len(blocks), 40):
        print(f"[feishu-doc-sync] append blocks {i + 1}-{min(i + 40, len(blocks))}/{len(blocks)}", file=sys.stderr)
        request_json(
            "POST",
            f"/docx/v1/documents/{document_id}/blocks/{document_id}/children",
            token=token,
            json={"children": blocks[i : i + 40], "index": -1},
            timeout=WRITE_TIMEOUT_SEC,
        )
        time.sleep(WRITE_SLEEP_SEC)


def extract_block_id(item: Any) -> str:
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        return str(item.get("block_id") or item.get("id") or "")
    return ""


def find_created_table(payload: dict[str, Any]) -> dict[str, Any]:
    children = payload.get("data", {}).get("children") or payload.get("data", {}).get("items") or []
    for child in children:
        if isinstance(child, dict) and child.get("block_type") == 31:
            return child
    return {}


def extract_table_cell_ids(table_block: dict[str, Any], expected: int) -> list[str]:
    table = table_block.get("table") if isinstance(table_block, dict) else {}
    candidates: list[Any] = []
    if isinstance(table, dict):
        candidates.extend(table.get("cells") or [])
    candidates.extend(table_block.get("children") or [])
    ids = [extract_block_id(item) for item in candidates]
    ids = [item for item in ids if item]
    return ids[:expected] if len(ids) >= expected else ids


def get_docx_block(document_id: str, block_id: str, token: str) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(30):
        try:
            payload = request_json("GET", f"/docx/v1/documents/{document_id}/blocks/{block_id}", token=token)
            return payload.get("data", {}).get("block") or payload.get("data", {})
        except RuntimeError as exc:
            last_error = exc
            if "1770002" not in str(exc) or attempt >= 29:
                raise
            time.sleep(1.0)
    raise last_error or RuntimeError(f"failed to get block {block_id}")


def get_docx_children(document_id: str, block_id: str, token: str) -> list[dict[str, Any]]:
    last_error: Exception | None = None
    for attempt in range(30):
        try:
            payload = request_json(
                "GET",
                f"/docx/v1/documents/{document_id}/blocks/{block_id}/children",
                token=token,
                params={"document_revision_id": -1},
            )
            return payload.get("data", {}).get("items") or payload.get("data", {}).get("children") or []
        except RuntimeError as exc:
            last_error = exc
            if "1770002" not in str(exc) or attempt >= 29:
                raise
            time.sleep(1.0)
    raise last_error or RuntimeError(f"failed to get block children {block_id}")


def clear_block_children(document_id: str, block_id: str, token: str) -> None:
    children = get_docx_children(document_id, block_id, token)
    if not children:
        return
    request_json(
        "DELETE",
        f"/docx/v1/documents/{document_id}/blocks/{block_id}/children/batch_delete",
        token=token,
        json={"start_index": 0, "end_index": len(children)},
        timeout=30,
    )
    time.sleep(WRITE_SLEEP_SEC)


def patch_text_block(document_id: str, block_id: str, text: str, token: str) -> None:
    request_json(
        "PATCH",
        f"/docx/v1/documents/{document_id}/blocks/{block_id}",
        token=token,
        json={"update_text_elements": {"elements": [text_run(text)]}},
        timeout=30,
    )
    time.sleep(WRITE_SLEEP_SEC)


def append_cell_text(document_id: str, cell_id: str, text: str, token: str) -> None:
    cleaned = text.strip()
    if not cleaned:
        return
    blocks = [paragraph_block(chunk) for line in cleaned.splitlines() for chunk in split_long_line(line, limit=900) if chunk.strip()]
    if not blocks:
        return
    last_error: Exception | None = None
    for attempt in range(10):
        try:
            request_json(
                "POST",
                f"/docx/v1/documents/{document_id}/blocks/{cell_id}/children",
                token=token,
                json={"children": blocks, "index": -1},
                timeout=30,
            )
            break
        except RuntimeError as exc:
            last_error = exc
            retryable = "1770002" in str(exc) or "1770024" in str(exc)
            if not retryable or attempt >= 9:
                raise
            time.sleep(1.0 + attempt * 0.4)
    else:
        raise last_error or RuntimeError(f"failed to append cell text {cell_id}")
    time.sleep(WRITE_SLEEP_SEC)


def table_chunks(rows: list[list[str]]) -> list[list[list[str]]]:
    return chunk_docx_table_rows(rows)


def append_table_chunk(document_id: str, token: str, rows: list[list[str]]) -> None:
    if not rows:
        return
    row_count = len(rows)
    column_count = max(len(row) for row in rows)
    validate_docx_table_create_shape(row_count, column_count)
    ensure_docx_table_write_budget(rows)
    start_index = len(list_root_children(document_id, token))
    try:
        payload = request_json(
            "POST",
            f"/docx/v1/documents/{document_id}/blocks/{document_id}/children",
            token=token,
            json={
                "children": [
                    {"block_type": 31, "table": {"property": {"row_size": row_count, "column_size": column_count}}},
                ],
                "index": -1,
            },
            timeout=30,
        )
        table_block = find_created_table(payload)
        time.sleep(2.0)
        table_id = str(table_block.get("block_id") or "")
        expected = row_count * column_count
        cell_ids = extract_table_cell_ids(table_block, expected)
        if len(cell_ids) < expected and table_id:
            hydrated = get_docx_block(document_id, table_id, token)
            cell_ids = extract_table_cell_ids(hydrated, expected)
        if len(cell_ids) < expected and table_id:
            children = get_docx_children(document_id, table_id, token)
            cell_ids = [extract_block_id(item) for item in children]
            cell_ids = [item for item in cell_ids if item]
        if len(cell_ids) < expected:
            raise RuntimeError(f"Feishu table creation did not return enough cell ids: expected={expected} got={len(cell_ids)} table_id={table_id}")

        for row_index, row in enumerate(rows):
            for column_index in range(column_count):
                text = row[column_index] if column_index < len(row) else ""
                append_cell_text(document_id, cell_ids[row_index * column_count + column_index], text, token)
    except Exception:
        delete_root_children_from(document_id, token, start_index)
        raise


def append_table(document_id: str, token: str, rows: list[list[str]]) -> None:
    chunks = table_chunks(rows)
    ensure_docx_tables_write_budget(chunks)
    for chunk in chunks:
        append_table_chunk(document_id, token, chunk)


def append_parts(document_id: str, token: str, parts: list[dict[str, Any]]) -> None:
    for part in parts:
        if part.get("kind") == "table":
            append_table(document_id, token, part.get("rows") or [])
        else:
            append_blocks(document_id, token, part.get("blocks") or [])


def block_text(block: dict[str, Any]) -> str:
    for key in ("text", "heading1", "heading2", "heading3", "heading4"):
        value = block.get(key)
        if not isinstance(value, dict):
            continue
        pieces: list[str] = []
        for element in value.get("elements") or []:
            if not isinstance(element, dict):
                continue
            text_run_value = element.get("text_run")
            if isinstance(text_run_value, dict):
                pieces.append(str(text_run_value.get("content") or ""))
        return "".join(pieces).strip()
    return ""


def visible_fragments(markdown: str, source_hash: str) -> list[str]:
    fragments: list[str] = []
    for part in markdown_to_parts(markdown, source_hash):
        if part.get("kind") == "table":
            for row in part.get("rows") or []:
                for cell in row:
                    text = str(cell).strip()
                    if text:
                        fragments.append(text)
        else:
            for block in part.get("blocks") or []:
                text = block_text(block)
                if text:
                    fragments.append(text)
    return fragments


def normalize_visible_text(text: str) -> str:
    return re.sub(r"\s+", "", text).replace("`", "").replace("*", "")


def assert_cloud_contains_visible_content(markdown: str, source_hash: str, remote_text: str) -> None:
    remote = normalize_visible_text(remote_text)
    missing: list[str] = []
    for fragment in visible_fragments(markdown, source_hash):
        normalized = normalize_visible_text(fragment)
        if len(normalized) < 2:
            continue
        if normalized not in remote:
            missing.append(fragment[:80])
            if len(missing) >= 8:
                break
    if missing:
        raise RuntimeError("cloud doc is missing current visible content; run npm run sync:docs. Missing: " + " | ".join(missing))


def raw_content(document_id: str, token: str) -> str:
    print(f"[feishu-doc-sync] reading raw content for {document_id}", file=sys.stderr)
    payload = request_json(
        "GET",
        f"/docx/v1/documents/{document_id}/raw_content",
        token=token,
        timeout=RAW_CONTENT_TIMEOUT_SEC,
    )
    data = payload.get("data", {})
    return str(data.get("content") or data.get("raw_content") or data.get("text") or "")


def configured_restricted_viewer(config: dict[str, Any]) -> str:
    env_name = str(config.get("restricted_viewer_open_id_env") or "").strip()
    open_id = os.getenv(env_name, "").strip() if env_name else ""
    return open_id or str(config.get("restricted_viewer_open_id") or "").strip()


def restrict_doc_visibility(config: dict[str, Any], document_id: str, token: str) -> None:
    if not config.get("restricted_visibility"):
        return
    doc_type = str(config.get("permission_type") or "docx")
    public_payload = {
        "external_access": False,
        "link_share_entity": "closed",
        "invite_external": False,
    }
    public_permission = request_json(
        "PATCH",
        f"/drive/v1/permissions/{document_id}/public",
        token=token,
        params={"type": doc_type},
        json=public_payload,
        timeout=30,
    ).get("data", {}).get("permission_public", {})
    config["last_public_permission"] = public_permission

    open_id = configured_restricted_viewer(config)
    if not open_id:
        raise RuntimeError("restricted_visibility is enabled, but no restricted viewer open_id is configured")
    member_payload = {
        "member_type": "openid",
        "member_id": open_id,
        "perm": str(config.get("restricted_viewer_perm") or "view"),
    }
    try:
        member = request_json(
            "POST",
            f"/drive/v1/permissions/{document_id}/members",
            token=token,
            params={"type": doc_type, "need_notification": "false"},
            json=member_payload,
            timeout=30,
        ).get("data", {}).get("member", {})
    except RuntimeError:
        member_id = urllib.parse.quote(open_id, safe="")
        member = request_json(
            "POST",
            f"/drive/v1/permissions/{document_id}/members/{member_id}",
            token=token,
            params={"type": doc_type, "need_notification": "false"},
            json=member_payload,
            timeout=30,
        ).get("data", {}).get("member", {})
    config["restricted_viewer_granted"] = bool(member)
    config["restricted_viewer_member_type"] = "openid"
    config["restricted_viewer_perm"] = str(member.get("perm") or member_payload["perm"])


def verify_restricted_visibility(config: dict[str, Any], document_id: str, token: str) -> None:
    if not config.get("restricted_visibility"):
        return
    doc_type = str(config.get("permission_type") or "docx")
    public_permission = request_json(
        "GET",
        f"/drive/v1/permissions/{document_id}/public",
        token=token,
        params={"type": doc_type},
    ).get("data", {}).get("permission_public", {})
    link_share_entity = str(public_permission.get("link_share_entity") or "")
    external_access = public_permission.get("external_access")
    if link_share_entity not in {"closed", "none", ""}:
        raise RuntimeError(f"restricted doc link sharing is not closed: link_share_entity={link_share_entity}")
    if external_access not in {False, "closed", "false", None}:
        raise RuntimeError(f"restricted doc external access is not closed: external_access={external_access}")


def sync_to_feishu() -> dict[str, Any]:
    config = load_config()
    configure_sync_target(config)
    source, source_hash = source_text_and_hash()
    print(f"[feishu-doc-sync] source={DOC_PATH} sha256={source_hash}", file=sys.stderr)
    token = tenant_access_token(config)
    document_id, config = get_cloud_doc(config, token)
    clear_doc(document_id, token)
    print(f"[feishu-doc-sync] converting markdown to Feishu blocks", file=sys.stderr)
    append_parts(document_id, token, markdown_to_parts(source, source_hash))
    remote_text = raw_content(document_id, token)
    print(f"[feishu-doc-sync] verifying cloud content", file=sys.stderr)
    assert_cloud_contains_visible_content(source, source_hash, remote_text)
    print(f"[feishu-doc-sync] restricting document visibility", file=sys.stderr)
    restrict_doc_visibility(config, document_id, token)
    config["last_synced_at"] = datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")
    config["last_source_sha256"] = source_hash
    config.setdefault("doc_url", f"{TENANT_HOST}/docx/{document_id}")
    save_config(config)
    return config


def check_feishu_sync() -> dict[str, Any]:
    config = load_config()
    configure_sync_target(config)
    source, source_hash = source_text_and_hash()
    document_id = str(config.get("document_id") or "").strip()
    if not document_id:
        raise RuntimeError("cloud doc is not configured; run npm run sync:docs")
    if config.get("last_source_sha256") != source_hash:
        raise RuntimeError("local doc changed after last cloud sync; run npm run sync:docs")
    token = tenant_access_token(config)
    remote_text = raw_content(document_id, token)
    print(f"[feishu-doc-sync] verifying cloud content", file=sys.stderr)
    assert_cloud_contains_visible_content(source, source_hash, remote_text)
    verify_restricted_visibility(config, document_id, token)
    return config


def main() -> int:
    parser = argparse.ArgumentParser(description="Create/update the Feishu cloud doc for tag-router docs.")
    parser.add_argument("--check", action="store_true", help="verify the cloud doc has the latest local source hash")
    parser.add_argument("--doc-path", default="", help="source markdown path; defaults to the main tag-router user guide")
    parser.add_argument("--config-path", default="", help="sync config path; relative paths are resolved from the plugin root")
    args = parser.parse_args()
    configure_source_paths(args.doc_path, args.config_path)
    try:
        if args.check:
            config = check_feishu_sync()
            print(f"Feishu cloud doc is synced: {config.get('wiki_url') or config.get('doc_url')}")
        else:
            config = sync_to_feishu()
            print(f"Synced Feishu cloud doc: {config.get('wiki_url') or config.get('doc_url')}")
        return 0
    except Exception as exc:
        print(f"Feishu cloud doc sync failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
