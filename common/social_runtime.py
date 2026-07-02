from __future__ import annotations

import argparse
import json
import math
import os
import re
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qs, urlparse

import requests

from .standard_fields import (
    STANDARD_ALIAS_MAP,
    STANDARD_FIELD_SPECS,
    STANDARD_JSON_FIELDS,
    choose_primary_value,
    merge_json_group,
    normalize_standard_field_name,
    normalize_standard_fields,
    standard_field_specs,
)


ROOT = Path(__file__).resolve().parents[1]
CONTENT_INGEST_PATH = ROOT / "selfmedia" / "ingest" / "content_flow"
URL_RE = re.compile(r"https?://[^\s，。；;、)）>]+")
INTERACTION_KEYS = ("like_count", "collect_count", "comment_count", "share_count")
FEISHU_BASE = os.getenv("FEISHU_API_BASE_URL", "https://open.feishu.cn/open-apis").rstrip("/")
FEISHU_FIELD_SPECS = {
    "模块": 1,
    "运行时间": 5,
    "平台": 1,
    "作品ID": 1,
    "参考链接": 15,
    "点赞": 2,
    "收藏": 2,
    "评论": 2,
    "分享": 2,
    "总互动": 2,
    "收藏率": 2,
    "评论率": 2,
    "分享率": 2,
    "状态": 1,
    "失败原因": 1,
    "分数": 2,
    "决策": 1,
    "摘要": 1,
    "详情JSON": 1,
    "报告路径": 1,
}


@dataclass(frozen=True)
class RuntimePaths:
    root: Path
    data_dir: Path
    output_dir: Path
    db_path: Path


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_env_file(path: str | Path, *, override: bool = False) -> None:
    env_path = Path(path).expanduser()
    if not env_path.exists() or not env_path.is_file():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key.startswith("export "):
            key = key[len("export ") :].strip()
        value = value.strip().strip("'").strip('"')
        if not key:
            continue
        if override or key not in os.environ:
            os.environ[key] = value


def load_openclaw_feishu_account_env(account: str | None = None, *, override: bool = False) -> None:
    account = account or os.getenv("SELFMEDIA_OPENCLAW_FEISHU_ACCOUNT", "media")
    config_path = Path(os.getenv("OPENCLAW_CONFIG", "/home/ubuntu/.openclaw/openclaw.json")).expanduser()
    if not config_path.exists():
        return
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return
    account_config = (((config.get("channels") or {}).get("feishu") or {}).get("accounts") or {}).get(account) or {}
    app_id = str(account_config.get("appId") or account_config.get("app_id") or "").strip()
    app_secret = str(account_config.get("appSecret") or account_config.get("app_secret") or "").strip()
    if app_id and (override or not os.getenv("FEISHU_APP_ID")):
        os.environ["FEISHU_APP_ID"] = app_id
    if app_secret and (override or not os.getenv("FEISHU_APP_SECRET")):
        os.environ["FEISHU_APP_SECRET"] = app_secret


def load_default_env_files() -> None:
    for path in (
        ROOT / ".env",
        ROOT / ".env.local",
        Path("/home/ubuntu/openclaw-agents/media/.env.local"),
        Path("/home/ubuntu/.openclaw/openclaw-media.env"),
        Path("/home/ubuntu/openclaw-feishu-reminder/reminder.env"),
        ROOT / "selfmedia" / "ingest" / "content_flow" / ".env",
        ROOT / "integrations" / "platform_auth" / "cookies" / ".env.local",
    ):
        load_env_file(path)
    load_openclaw_feishu_account_env()
    ensure_feishu_no_proxy()


def ensure_feishu_no_proxy() -> None:
    required = ("open.feishu.cn", "tcnwueberajc.feishu.cn", ".feishu.cn", ".larksuite.com")
    for env_name in ("NO_PROXY", "no_proxy"):
        existing = [item.strip() for item in os.getenv(env_name, "").split(",") if item.strip()]
        merged = list(existing)
        for item in required:
            if item not in merged:
                merged.append(item)
        os.environ[env_name] = ",".join(merged)


def ensure_paths(part_dir: Path, db_name: str) -> RuntimePaths:
    data_dir = part_dir / "data"
    output_dir = part_dir / "outputs"
    data_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    return RuntimePaths(
        root=part_dir,
        data_dir=data_dir,
        output_dir=output_dir,
        db_path=data_dir / db_name,
    )


def load_content_ingest():
    from selfmedia.ingest.content_flow.src.config import load_settings  # type: ignore
    from selfmedia.ingest.content_flow.src.downloader import clean_douyin_url, refresh_stats_only  # type: ignore

    return load_settings, clean_douyin_url, refresh_stats_only


def extract_urls(values: Iterable[str]) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for value in values:
        for match in URL_RE.findall(value or ""):
            url = match.strip().rstrip(".,，。")
            if url and url not in seen:
                seen.add(url)
                urls.append(url)
    return urls


def read_urls_from_args(args: argparse.Namespace) -> list[str]:
    values: list[str] = []
    values.extend(args.urls or [])
    for path in args.input or []:
        values.append(Path(path).read_text(encoding="utf-8"))
    if args.stdin:
        values.append(sys.stdin.read())
    urls = extract_urls(values)
    if not urls:
        raise SystemExit("no URLs found; pass --urls, --input, or --stdin")
    return urls


def add_url_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--urls", nargs="*", default=[], help="One or more share URLs or text snippets containing URLs.")
    parser.add_argument("--input", nargs="*", default=[], help="Text files containing share URLs.")
    parser.add_argument("--stdin", action="store_true", help="Read URL text from stdin.")
    parser.add_argument("--label", default="", help="Optional run label.")


def detect_platform(url: str) -> str:
    lower = (url or "").lower()
    if "xiaohongshu.com" in lower or "xhslink.com" in lower:
        return "xiaohongshu"
    if "douyin.com" in lower or "iesdouyin.com" in lower:
        return "douyin"
    return "unknown"


def health_status(stats: dict[str, Any]) -> str:
    if all(stats.get(key) is not None for key in INTERACTION_KEYS):
        return "ok"
    if any(stats.get(key) is not None for key in INTERACTION_KEYS):
        return "partial"
    return "missing"


def failure_reason(stats: dict[str, Any]) -> str:
    status = health_status(stats)
    if status == "ok":
        return ""
    if stats.get("interaction_screenshot_status") == "captured_for_ocr":
        return "captcha_or_visible_text_missing"
    if stats.get("stats_notice"):
        return str(stats["stats_notice"])
    return "missing_interaction_fields"


def refresh_posts(urls: list[str]) -> list[dict[str, Any]]:
    load_settings, clean_douyin_url, refresh_stats_only = load_content_ingest()
    settings = load_settings()
    rows: list[dict[str, Any]] = []
    captured_at = now_iso()
    for url in urls:
        cleaned_url = clean_douyin_url(url)
        stats = refresh_stats_only(cleaned_url, settings)
        row = {
            "url": url,
            "cleaned_url": cleaned_url,
            "platform": detect_platform(cleaned_url or url),
            "post_id": str(stats.get("video_id") or ""),
            "captured_at": captured_at,
            "like_count": stats.get("like_count"),
            "collect_count": stats.get("collect_count"),
            "comment_count": stats.get("comment_count"),
            "share_count": stats.get("share_count"),
            "top_comments": stats.get("top_comments") or [],
            "cover_url": stats.get("cover_url") or "",
            "interaction_status": stats.get("interaction_status") or "",
            "stats_sources": stats.get("stats_sources") or {},
            "missing_interaction_fields": stats.get("missing_interaction_fields") or [],
            "stats_notice": stats.get("stats_notice") or "",
            "health_status": health_status(stats),
            "failure_reason": failure_reason(stats),
            "raw_stats": stats,
        }
        rows.append(row)
    return rows


def count_value(row: dict[str, Any], key: str) -> int:
    value = row.get(key)
    if value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def total_interactions(row: dict[str, Any]) -> int:
    return sum(count_value(row, key) for key in INTERACTION_KEYS)


def safe_ratio(numerator: int | float, denominator: int | float) -> float:
    if not denominator:
        return 0.0
    return round(float(numerator) / float(denominator), 4)


def metric_summary(row: dict[str, Any]) -> dict[str, Any]:
    likes = count_value(row, "like_count")
    collect = count_value(row, "collect_count")
    comments = count_value(row, "comment_count")
    shares = count_value(row, "share_count")
    total = likes + collect + comments + shares
    return {
        "total_interactions": total,
        "collect_ratio": safe_ratio(collect, likes),
        "comment_ratio": safe_ratio(comments, likes),
        "share_ratio": safe_ratio(shares, likes),
    }


def quality_score(row: dict[str, Any]) -> dict[str, Any]:
    metrics = metric_summary(row)
    complete_fields = sum(1 for key in INTERACTION_KEYS if row.get(key) is not None)
    field_score = int(complete_fields / len(INTERACTION_KEYS) * 100)
    interaction_score = min(100, int(math.log10(metrics["total_interactions"] + 1) * 25))
    collect_score = min(100, int(metrics["collect_ratio"] * 200))
    comment_score = min(100, int(metrics["comment_ratio"] * 400))
    share_score = min(100, int(metrics["share_ratio"] * 400))
    recreate_value = int((collect_score * 0.45) + (comment_score * 0.25) + (share_score * 0.2) + (field_score * 0.1))
    overall = int(field_score * 0.35 + interaction_score * 0.3 + recreate_value * 0.35)
    if row.get("health_status") != "ok":
        overall = min(overall, 59)
    if overall >= 75:
        decision = "deconstruct"
    elif overall >= 55:
        decision = "review"
    else:
        decision = "skip"
    return {
        "field_completeness_score": field_score,
        "interaction_quality_score": interaction_score,
        "recreate_value_score": recreate_value,
        "overall_score": overall,
        "decision": decision,
        **metrics,
    }


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_markdown(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def table_lines(rows: list[dict[str, Any]]) -> list[str]:
    lines = [
        "| 平台 | 作品 ID | 点赞 | 收藏 | 评论 | 分享 | 状态 | 链接 |",
        "| --- | --- | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for row in rows:
        lines.append(
            "| {platform} | {post_id} | {like} | {collect} | {comment} | {share} | {status} | {url} |".format(
                platform=row.get("platform", ""),
                post_id=row.get("post_id", ""),
                like=row.get("like_count"),
                collect=row.get("collect_count"),
                comment=row.get("comment_count"),
                share=row.get("share_count"),
                status=row.get("health_status", ""),
                url=row.get("cleaned_url") or row.get("url", ""),
            )
        )
    return lines


def slug_time() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")


def feishu_tenant_access_token() -> str:
    load_default_env_files()
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


def feishu_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"}


def resolve_wiki_bitable(wiki_token: str, token: str) -> str:
    resp = requests.get(
        f"{FEISHU_BASE}/wiki/v2/spaces/get_node",
        params={"token": wiki_token},
        headers=feishu_headers(token),
        timeout=10,
    )
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("code") != 0:
        raise RuntimeError(f"解析飞书 wiki 节点失败：{payload}")
    node = payload.get("data", {}).get("node", {})
    if node.get("obj_type") != "bitable":
        raise RuntimeError(f"wiki 节点不是多维表格：{node.get('obj_type')}")
    return node["obj_token"]


def parse_feishu_bitable_url(url: str, token: str) -> tuple[str, str]:
    wiki_match = re.search(r"/wiki/([A-Za-z0-9]+)", url)
    table_match = re.search(r"[?&]table=([^&#]+)", url)
    if wiki_match and table_match:
        return resolve_wiki_bitable(wiki_match.group(1), token), table_match.group(1)
    parsed = urlparse(url)
    app_match = re.search(r"/base/([A-Za-z0-9]+)", parsed.path)
    if app_match and table_match:
        return app_match.group(1), table_match.group(1)
    raise ValueError("飞书链接必须包含 /wiki/<token> 或 /base/<app_token>，且带 table= 参数")


def feishu_table_url_from_env(*names: str) -> str:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""


def feishu_bitable_refs(bitable_url: str, token: str | None = None) -> tuple[str, str, str]:
    token = token or feishu_tenant_access_token()
    app_token, table_id = parse_feishu_bitable_url(bitable_url, token)
    return app_token, table_id, token


def feishu_list_fields(app_token: str, table_id: str, token: str) -> list[dict[str, Any]]:
    resp = requests.get(
        f"{FEISHU_BASE}/bitable/v1/apps/{app_token}/tables/{table_id}/fields",
        headers=feishu_headers(token),
        timeout=10,
    )
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("code") != 0:
        raise RuntimeError(f"读取飞书字段失败：{payload}")
    return payload.get("data", {}).get("items", [])


def feishu_field_types(app_token: str, table_id: str, token: str) -> dict[str, Any]:
    return {
        str(item.get("field_name")): item.get("type")
        for item in feishu_list_fields(app_token, table_id, token)
        if item.get("field_name")
    }


def feishu_ensure_fields(app_token: str, table_id: str, token: str, specs: dict[str, int] | None = None) -> None:
    specs = specs or FEISHU_FIELD_SPECS
    existing = {item.get("field_name") for item in feishu_list_fields(app_token, table_id, token)}
    for name, field_type in specs.items():
        if name in existing:
            continue
        resp = requests.post(
            f"{FEISHU_BASE}/bitable/v1/apps/{app_token}/tables/{table_id}/fields",
            headers=feishu_headers(token),
            json={"field_name": name, "type": field_type},
            timeout=10,
        )
        try:
            payload = resp.json()
        except ValueError:
            payload = {}
        if resp.status_code < 400 and payload.get("code") == 0:
            existing.add(name)


def feishu_list_records(
    bitable_url: str,
    *,
    view_id: str = "",
    page_size: int = 200,
    token: str | None = None,
) -> list[dict[str, Any]]:
    app_token, table_id, token = feishu_bitable_refs(bitable_url, token)
    parsed = urlparse(bitable_url)
    query = parse_qs(parsed.query)
    view_id = view_id or (query.get("view") or [""])[0]
    records: list[dict[str, Any]] = []
    page_token = ""
    while True:
        params: dict[str, Any] = {"page_size": min(max(page_size, 1), 500)}
        if view_id:
            params["view_id"] = view_id
        if page_token:
            params["page_token"] = page_token
        resp = requests.get(
            f"{FEISHU_BASE}/bitable/v1/apps/{app_token}/tables/{table_id}/records",
            params=params,
            headers=feishu_headers(token),
            timeout=15,
        )
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("code") != 0:
            raise RuntimeError(f"读取飞书记录失败：{payload}")
        data = payload.get("data", {})
        records.extend(data.get("items") or [])
        if not data.get("has_more"):
            break
        page_token = str(data.get("page_token") or "")
        if not page_token:
            break
    return records


def feishu_update_record(
    bitable_url: str,
    record_id: str,
    fields: dict[str, Any],
    *,
    specs: dict[str, int] | None = None,
    token: str | None = None,
) -> None:
    if not record_id:
        return
    app_token, table_id, token = feishu_bitable_refs(bitable_url, token)
    feishu_ensure_fields(app_token, table_id, token, specs or FEISHU_FIELD_SPECS)
    field_types = feishu_field_types(app_token, table_id, token)
    existing = set(field_types)
    payload_fields: dict[str, Any] = {}
    for key, value in fields.items():
        if key not in existing:
            continue
        coerced = feishu_coerce_value(value, field_types.get(key))
        if coerced in (None, []):
            continue
        payload_fields[key] = coerced
    if not payload_fields:
        return
    resp = requests.put(
        f"{FEISHU_BASE}/bitable/v1/apps/{app_token}/tables/{table_id}/records/{record_id}",
        headers=feishu_headers(token),
        json={"fields": payload_fields},
        timeout=15,
    )
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("code") != 0:
        raise RuntimeError(f"更新飞书记录失败：{payload}")


def _coerce_feishu_date(value: Any) -> int | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        number = int(value)
        return number if number > 10_000_000_000 else number * 1000
    text = str(value).strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def _coerce_feishu_url(value: Any) -> dict[str, str] | str:
    if value in (None, "", []):
        return ""
    if isinstance(value, dict):
        link = str(value.get("link") or value.get("url") or "").strip()
        text = str(value.get("text") or link or "").strip()
        if link.startswith(("http://", "https://")):
            return {"text": text or link, "link": link}
        return text
    text = str(value).strip()
    if text.startswith(("http://", "https://")):
        return {"text": text, "link": text}
    return text


def feishu_coerce_value(value: Any, field_type: Any) -> Any:
    if value is None:
        return ""
    if field_type == 1:
        if isinstance(value, (dict, list)):
            return json_dumps(value)
        return str(value)
    if field_type == 3:
        if isinstance(value, list):
            value = next((item for item in value if str(item).strip()), "")
        return str(value).strip()
    if field_type == 4:
        if value in (None, "", []):
            return []
        raw_items = value if isinstance(value, list) else re.split(r"[,，/、;；|]\s*", str(value))
        items: list[str] = []
        seen: set[str] = set()
        for item in raw_items:
            text = str(item).strip()
            if not text or text in seen:
                continue
            seen.add(text)
            items.append(text)
        return items
    if field_type == 2:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    if field_type == 5:
        return _coerce_feishu_date(value)
    if field_type == 7:
        return feishu_bool(value, default=False)
    if field_type == 15:
        return _coerce_feishu_url(value)
    if isinstance(value, (dict, list)):
        return json_dumps(value)
    return str(value)


def feishu_plain_text(value: Any) -> str:
    if value in (None, "", []):
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, dict):
        for key in ("text", "link", "url", "name", "value"):
            text = feishu_plain_text(value.get(key))
            if text:
                return text
        return json_dumps(value)
    if isinstance(value, list):
        parts = [feishu_plain_text(item) for item in value]
        return "\n".join(part for part in parts if part)
    return str(value).strip()


def feishu_bool(value: Any, default: bool = True) -> bool:
    if value in (None, "", []):
        return default
    if isinstance(value, bool):
        return value
    text = feishu_plain_text(value).strip().lower()
    if not text:
        return default
    if text in {"0", "false", "no", "off", "停用", "否", "不启用", "disabled"}:
        return False
    return True


def feishu_first_field(fields: dict[str, Any], names: Iterable[str], default: str = "") -> str:
    for name in names:
        value = feishu_plain_text(fields.get(name))
        if value:
            return value
    return default


def feishu_urls_from_fields(fields: dict[str, Any], names: Iterable[str]) -> list[str]:
    values = [feishu_plain_text(fields.get(name)) for name in names if name in fields]
    return extract_urls(values)


def row_to_feishu_fields(module: str, row: dict[str, Any], summary: str = "", report_path: str = "", score: Any = "", decision: str = "") -> dict[str, Any]:
    metrics = metric_summary(row)
    return {
        "模块": module,
        "运行时间": str(row.get("captured_at") or now_iso()),
        "平台": str(row.get("platform") or ""),
        "作品ID": str(row.get("post_id") or row.get("video_id") or ""),
        "参考链接": str(row.get("cleaned_url") or row.get("url") or ""),
        "点赞": row.get("like_count"),
        "收藏": row.get("collect_count"),
        "评论": row.get("comment_count"),
        "分享": row.get("share_count"),
        "总互动": metrics["total_interactions"],
        "收藏率": metrics["collect_ratio"],
        "评论率": metrics["comment_ratio"],
        "分享率": metrics["share_ratio"],
        "状态": str(row.get("health_status") or row.get("interaction_status") or ""),
        "失败原因": str(row.get("failure_reason") or ""),
        "分数": score,
        "决策": decision,
        "摘要": summary,
        "详情JSON": row,
        "报告路径": report_path,
    }


def write_feishu_records(
    bitable_url: str | None,
    records: list[dict[str, Any]],
    *,
    module: str,
    report_path: str = "",
    require: bool = False,
) -> list[str]:
    bitable_url = bitable_url or ""
    if not bitable_url:
        if require:
            raise RuntimeError("缺少显式 --feishu-url，已开启飞书必写模式")
        return []
    token = feishu_tenant_access_token()
    app_token, table_id = parse_feishu_bitable_url(bitable_url, token)
    feishu_ensure_fields(app_token, table_id, token)
    field_items = feishu_list_fields(app_token, table_id, token)
    field_types = {str(item.get("field_name")): item.get("type") for item in field_items if item.get("field_name")}
    existing = set(field_types)
    record_ids: list[str] = []
    for record in records:
        raw_fields = record if "模块" in record else row_to_feishu_fields(module, record, report_path=report_path)
        fields = {}
        for key, value in raw_fields.items():
            if key not in existing:
                continue
            coerced = feishu_coerce_value(value, field_types.get(key))
            if coerced in (None, "", []):
                continue
            fields[key] = coerced
        if not fields:
            continue
        resp = requests.post(
            f"{FEISHU_BASE}/bitable/v1/apps/{app_token}/tables/{table_id}/records",
            headers=feishu_headers(token),
            json={"fields": fields},
            timeout=15,
        )
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("code") != 0:
            raise RuntimeError(f"写入飞书多维表格失败：{payload}")
        record_id = payload.get("data", {}).get("record", {}).get("record_id")
        if record_id:
            record_ids.append(record_id)
    if require and records and not record_ids:
        raise RuntimeError("飞书写入没有返回 record_id，请检查多维表格权限和字段配置")
    return record_ids


def feishu_required_default() -> bool:
    return os.getenv("FEISHU_REQUIRED", "").lower() in {"1", "true", "yes", "on"}


def add_feishu_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--feishu-url", default="", help="Explicit Feishu bitable URL. No default table is inferred.")
    parser.add_argument("--require-feishu", action="store_true", default=feishu_required_default(), help="Fail when Feishu write is not completed. Also enabled by FEISHU_REQUIRED=1.")


def feishu_status_message(record_ids: list[str], bitable_url: str | None, record_count: int) -> str:
    bitable_url = bitable_url or ""
    if record_ids:
        return f"wrote {len(record_ids)} feishu records"
    if not record_count:
        return "feishu skipped: no records to write"
    if not bitable_url:
        return "feishu skipped: pass an explicit Feishu table URL to write cross-platform records"
    return "feishu configured but no records were written"
