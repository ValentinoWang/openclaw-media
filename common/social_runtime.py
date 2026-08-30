from __future__ import annotations

import argparse
import json
import math
import os
import re
import sqlite3
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone, tzinfo as TzInfo
from functools import lru_cache
from pathlib import Path
from threading import Lock
from typing import Any, Callable, Iterable, Literal
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

import requests

from common import feishu_urls as _feishu_urls
from common import url_text as _url_text
from common.platform_links import platform_for_url

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
# Feishu bitable internal option ids (e.g. "optXXXXXX") — never valid as a
# display value for a single/multi-select field. Consolidated from three
# byte-identical copies (integrations/feishu/media_writer.py, and the
# unified_creation/commercial_delivery routers in openclaw-tag-router).
BITABLE_OPTION_ID_RE = re.compile(r"^opt[A-Za-z0-9]{6,}$")
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


def feishu_app_id_prefix(app_id: str | None = None) -> str:
    """Return a stable, non-secret display prefix for a Feishu app identity."""
    value = str(app_id if app_id is not None else os.getenv("FEISHU_APP_ID", "")).strip()
    if not value:
        return "未配置"
    # Feishu app ids normally use ``cli_``. Keep only four characters after
    # the public marker so logs and poll receipts cannot disclose credentials.
    if value.startswith("cli_"):
        return "cli_" + (value[4:8] or "xxxx")
    return value[:4] + "xxxx"


def effective_feishu_app_id() -> str:
    """Resolve the configured app id after the normal environment loading."""
    load_default_env_files()
    return str(os.getenv("FEISHU_APP_ID", "")).strip()


def feishu_identity_info() -> dict[str, Any]:
    """Return safe identity metadata suitable for daily-poll status payloads."""
    app_id = effective_feishu_app_id()
    return {
        "app_id_prefix": feishu_app_id_prefix(app_id),
        "configured": bool(app_id),
    }


# Explicitly named alias for jobs that need a stable preflight/identity call.
def feishu_identity_preflight() -> dict[str, Any]:
    return feishu_identity_info()


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@lru_cache(maxsize=None)
def _cached_zoneinfo(tz_name: str) -> ZoneInfo:
    return ZoneInfo(tz_name)


def local_now_iso(tz_name: str = "Asia/Shanghai") -> str:
    return datetime.now(_cached_zoneinfo(tz_name)).isoformat(timespec="seconds")


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
    config_path = Path(os.getenv("OPENCLAW_CONFIG") or Path.home() / ".openclaw/openclaw.json").expanduser()
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
    media_env = Path(
        os.getenv("OPENCLAW_MEDIA_ENV_FILE") or Path.home() / ".openclaw/openclaw-media.env"
    ).expanduser()
    reminder_env = Path(
        os.getenv("OPENCLAW_FEISHU_REMINDER_ENV_FILE") or Path.home() / "openclaw-feishu-reminder/reminder.env"
    ).expanduser()
    for path in (
        ROOT / ".env",
        ROOT / ".env.local",
        media_env,
        reminder_env,
        ROOT / "selfmedia" / "ingest" / "content_flow" / ".env",
        ROOT / "integrations" / "platform_auth" / "cookies" / ".env.local",
        # Consolidated from openclaw-tag-router/scripts/cleanup_creation_runs.py's
        # former DEFAULT_MEDIA_ENV_PATH -- keep loading this file so cleanup
        # (and anything else routed through load_default_env_files) doesn't
        # silently stop picking up MEDIA_OS_* / FEISHU_* overrides kept there.
        Path.home() / "openclaw-agents" / "media" / ".env.local",
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


def infer_platform_keyword(text: str) -> str:
    """Infer a platform from Chinese keyword/URL-substring mentions in free text.

    This is distinct from platform_links.platform_for_url: it matches literal
    keyword mentions ("小红书", "抖音", "B站"...) in arbitrary prose, not URL
    hostnames. Consolidated from three byte-identical-or-near-identical copies
    (selfmedia/context/media_context.py, selfmedia/review/data_review.py,
    selfmedia/creation/consultation.py — the latter had one extra B站 branch,
    now included here so all three callers gain it).
    """
    haystack = str(text or "")
    if "小红书" in haystack or "xhslink" in haystack:
        return "小红书"
    if "抖音" in haystack or "douyin" in haystack:
        return "抖音"
    if "B站" in haystack or "哔哩哔哩" in haystack or "bilibili" in haystack.lower():
        return "B站"
    return ""


def extract_urls(values: Iterable[str]) -> list[str]:
    return _url_text.extract_urls_from_values(values)


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
    return platform_for_url(url)


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


#: (api_base, app_id) -> (token, expire_at_monotonic_time). Deliberately
#: keyed by identity, never a single process-wide slot -- different
#: identities (e.g. the DeepMath branch's injected app_id/app_secret vs.
#: this process's own default identity) must never share a cached token.
_TENANT_ACCESS_TOKEN_CACHE: dict[tuple[str, str], tuple[str, float]] = {}
_TENANT_ACCESS_TOKEN_CACHE_LOCK = Lock()


def fetch_tenant_access_token(
    app_id: str,
    app_secret: str,
    *,
    api_base: str = FEISHU_BASE,
    timeout: float = 10,
) -> str:
    """Fetch (and cache) a Feishu tenant_access_token for one (api_base, app_id) identity.

    Consolidates fetch logic that used to be duplicated across several call
    sites: a Chinese-language explanation for the 91403 permission error,
    raising on any other non-zero ``code``, and extracting the token from
    either a top-level or ``data``-nested payload shape.

    Cached entries expire 60s before the token's real ``expire``, with a
    60s floor -- matching FeishuService's own per-instance cache policy.
    """
    if not app_id or not app_secret:
        raise RuntimeError("FEISHU_APP_ID / FEISHU_APP_SECRET 未配置")
    cache_key = (api_base, app_id)
    now = time.time()
    cached = _TENANT_ACCESS_TOKEN_CACHE.get(cache_key)
    if cached and now < cached[1]:
        return cached[0]
    with _TENANT_ACCESS_TOKEN_CACHE_LOCK:
        now = time.time()
        cached = _TENANT_ACCESS_TOKEN_CACHE.get(cache_key)
        if cached and now < cached[1]:
            return cached[0]
        resp = requests.post(
            f"{api_base}/auth/v3/tenant_access_token/internal",
            json={"app_id": app_id, "app_secret": app_secret},
            timeout=timeout,
        )
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("code") != 0:
            if str(payload.get("code")) == "91403":
                raise RuntimeError(
                    f"当前身份 {feishu_app_id_prefix(app_id)} 对该 Base 无权限（不等于表被删）"
                )
            raise RuntimeError(f"获取飞书 token 失败：{payload}")
        token = payload.get("tenant_access_token") or (payload.get("data") or {}).get("tenant_access_token")
        if not token:
            raise RuntimeError(f"获取飞书 token 失败：{payload}")
        expire = payload.get("expire")
        if expire in (None, ""):
            expire = (payload.get("data") or {}).get("expire")
        try:
            expire_seconds = float(expire) if expire not in (None, "") else 3600.0
        except (TypeError, ValueError):
            expire_seconds = 3600.0
        _TENANT_ACCESS_TOKEN_CACHE[cache_key] = (token, now + max(expire_seconds - 60, 60))
        return token


def feishu_tenant_access_token() -> str:
    return fetch_tenant_access_token(
        effective_feishu_app_id(),
        os.getenv("FEISHU_APP_SECRET", ""),
        api_base=FEISHU_BASE,
        timeout=10,
    )


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
    obj_token = node.get("obj_token")
    if not obj_token:
        raise RuntimeError(f"wiki 节点缺少 obj_token：{node}")
    return obj_token


def parse_feishu_bitable_url(url: str, token: str) -> tuple[str, str]:
    parsed = _feishu_urls.parse_bitable_url(url)
    table_id = parsed["table_id"]
    if parsed["wiki_token"] and table_id:
        return resolve_wiki_bitable(parsed["wiki_token"], token), table_id
    if parsed["app_token"] and table_id:
        return parsed["app_token"], table_id
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


def feishu_ensure_fields(
    app_token: str,
    table_id: str,
    token: str,
    specs: dict[str, int] | None = None,
    *,
    on_error: Literal["ignore", "raise"] = "ignore",
    request: Callable[..., dict[str, Any]] | None = None,
) -> None:
    """Create any missing bitable fields from ``specs`` that aren't already present.

    ``on_error`` controls what happens when creating one field fails:
    ``"ignore"`` (the default, matching every existing caller's behavior)
    silently moves on to the next field; ``"raise"`` propagates.

    ``request`` is an optional injected transport -- ``request(method, path,
    *, json_body=None) -> parsed response body`` that already raises on a
    non-2xx status or a Feishu ``code != 0`` payload (the same convention
    ``feishu_ensure_select_options`` and ``common/feishu_wiki_docs.py``
    use). When omitted (the default), this uses the module-level
    ``requests`` + ``token`` + ``FEISHU_BASE`` path, unchanged from before.
    """
    specs = specs or FEISHU_FIELD_SPECS
    if request is None:
        existing = {item.get("field_name") for item in feishu_list_fields(app_token, table_id, token)}
    else:
        payload = request("GET", f"/bitable/v1/apps/{app_token}/tables/{table_id}/fields")
        existing = {item.get("field_name") for item in (payload.get("data") or {}).get("items", [])}
    for name, field_type in specs.items():
        if name in existing:
            continue
        try:
            if request is None:
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
                ok = resp.status_code < 400 and payload.get("code") == 0
            else:
                request(
                    "POST",
                    f"/bitable/v1/apps/{app_token}/tables/{table_id}/fields",
                    json_body={"field_name": name, "type": field_type},
                )
                ok = True
        except Exception:
            if on_error == "raise":
                raise
            ok = False
        if ok:
            existing.add(name)
        elif on_error == "raise":
            raise RuntimeError(f"创建飞书字段失败：{name}")


def feishu_ensure_select_options(
    app_token: str,
    table_id: str,
    specs: dict[str, int],
    select_options: dict[str, list[str]],
    raw_fields: dict[str, Any],
    *,
    request: Callable[..., dict[str, Any]],
) -> None:
    """Merge configured + observed select options onto existing single/multi-select fields.

    For each field name in ``select_options``, merges its configured base
    options with whatever options are observed in ``raw_fields`` (accepts
    a list, or a string split on common delimiters, filtering out bitable
    internal option-ids like ``optXXXXXX``), plus whatever options already
    exist on the field, then PUTs the union back if anything is missing.
    Fields not present in the table (per a GET of its fields) are skipped.

    ``request`` follows the same convention as ``feishu_ensure_fields``:
    ``request(method, path, *, json_body=None) -> parsed response body``,
    already raising on failure -- there is no ``on_error`` here because
    every known caller wants hard failure on a write error.
    """
    payload = request("GET", f"/bitable/v1/apps/{app_token}/tables/{table_id}/fields")
    items = {
        str(item.get("field_name")): item
        for item in (payload.get("data") or {}).get("items", [])
        if item.get("field_name")
    }
    for name, base_options in select_options.items():
        item = items.get(name)
        if not item:
            continue
        target_type = specs.get(name)
        options = [str(option).strip() for option in base_options if str(option).strip()]
        for option in _feishu_select_options_from_raw_value(raw_fields.get(name)):
            if option not in options:
                options.append(option)
        existing = [
            str(option.get("name") or "").strip()
            for option in ((item.get("property") or {}).get("options") or [])
            if str(option.get("name") or "").strip()
        ]
        if item.get("type") == target_type and all(option in existing for option in options):
            continue
        merged = list(options)
        for option in existing:
            if option not in merged:
                merged.append(option)
        request(
            "PUT",
            f"/bitable/v1/apps/{app_token}/tables/{table_id}/fields/{item.get('field_id')}",
            json_body={
                "field_name": name,
                "type": target_type,
                "property": {"options": [{"name": option} for option in merged]},
            },
        )


def _feishu_select_options_from_raw_value(value: Any) -> list[str]:
    if value in (None, "", []):
        return []
    raw_items = value if isinstance(value, list) else re.split(r"[,，/、;；|]\s*", str(value))
    result: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        text = str(item).strip()
        if not text or BITABLE_OPTION_ID_RE.fullmatch(text) or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _iter_bitable_records(
    request: Callable[..., dict[str, Any]],
    app_token: str,
    table_id: str,
    *,
    page_size: int = 500,
    view_id: str = "",
    filter_formula: str = "",
    automatic_fields: bool = False,
) -> list[dict[str, Any]]:
    """Shared pagination core for a Feishu bitable's ``/records`` list endpoint.

    ``request(method, path, *, params=None) -> dict`` is an injected
    transport that owns auth/headers and turns a non-2xx status or a
    Feishu ``code != 0`` payload into a raised exception -- this function
    only ever calls it with ``"GET"``.

    Consolidated from FC-03's five near-duplicate pagination loops: uses
    the strictest of the group's loop-termination guards (a ``seen_tokens``
    cycle check, raising if the next ``page_token`` doesn't advance) plus a
    ``data``/``items`` shape check, rather than the weaker "silently break
    on an empty page_token" some copies used -- an under-read now fails
    loudly instead of returning a truncated record list.
    """
    records: list[dict[str, Any]] = []
    page_token = ""
    seen_tokens: set[str] = set()
    while True:
        params: dict[str, Any] = {"page_size": max(1, min(page_size, 500))}
        if view_id:
            params["view_id"] = view_id
        if automatic_fields:
            params["automatic_fields"] = "true"
        if filter_formula:
            params["filter"] = filter_formula
        if page_token:
            params["page_token"] = page_token
        payload = request(
            "GET",
            f"/bitable/v1/apps/{app_token}/tables/{table_id}/records",
            params=params,
        )
        data = payload.get("data") if isinstance(payload, dict) else {}
        if not isinstance(data, dict):
            raise RuntimeError("Feishu Bitable record list returned invalid data")
        items = data.get("items") or []
        if not isinstance(items, list):
            raise RuntimeError("Feishu Bitable record list returned invalid items")
        records.extend(item for item in items if isinstance(item, dict))
        if not data.get("has_more"):
            return records
        next_token = str(data.get("page_token") or "").strip()
        if not next_token or next_token in seen_tokens:
            raise RuntimeError("Feishu Bitable record pagination did not advance")
        seen_tokens.add(next_token)
        page_token = next_token


def feishu_list_records(
    bitable_url: str,
    *,
    view_id: str = "",
    page_size: int = 200,
    token: str | None = None,
    filter_formula: str = "",
) -> list[dict[str, Any]]:
    app_token, table_id, token = feishu_bitable_refs(bitable_url, token)
    parsed = urlparse(bitable_url)
    query = parse_qs(parsed.query)
    view_id = view_id or (query.get("view") or [""])[0]

    def _request(method: str, path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        resp = requests.get(f"{FEISHU_BASE}{path}", params=params, headers=feishu_headers(token), timeout=15)
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("code") != 0:
            raise RuntimeError(f"读取飞书记录失败：{payload}")
        return payload

    return _iter_bitable_records(
        _request,
        app_token,
        table_id,
        page_size=page_size,
        view_id=view_id,
        filter_formula=filter_formula,
    )


def feishu_update_record(
    bitable_url: str,
    record_id: str,
    fields: dict[str, Any],
    *,
    specs: dict[str, int] | None = None,
    token: str | None = None,
    write_empty_fields: bool = False,
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
        if coerced is None or (coerced == [] and not write_empty_fields):
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


def parse_iso_datetime(
    value: Any,
    *,
    assume_tz: TzInfo = timezone.utc,
    convert_to: TzInfo | None = None,
) -> datetime | None:
    """Parse a loosely-ISO datetime (datetime / date / str) into an aware datetime.

    Consolidated (H9) from eight independent, near-identical try/except
    implementations (selfmedia/creation/matcher.py, shooting_execution.py,
    selfmedia/business/schedule.py, and four in openclaw-tag-router). Its
    core string-parsing logic is taken from what the H9 audit identified as
    the most careful of those eight,
    openclaw-tag-router's deepmath_people_recommendation._parse_datetime:
    it only strips a trailing "Z" (``text.endswith("Z")``) rather than
    blanket ``str.replace("Z", "+00:00")``, which would also mangle a "Z"
    occurring anywhere else in the string.

    A ``datetime`` input is returned as-is (module unresolved timezone
    handling below still applies); a ``date`` input is treated as
    midnight on that date; anything else is coerced with ``str(value)``
    and parsed via ``datetime.fromisoformat``.

    :param assume_tz: timezone attached to the result when parsing produced
        a naive datetime (no offset in the source string, or a bare
        ``date``). Defaults to UTC; callers that have historically assumed
        naive input means local time (selfmedia/creation/shooting_execution.py,
        selfmedia/business/schedule.py, both using a fixed +08:00) must pass
        their own local tzinfo here — silently defaulting everyone to UTC
        would shift those callers' naive-input results by 8 hours.
    :param convert_to: when given, the result is additionally converted
        with ``.astimezone(convert_to)`` — this also applies to an input
        that already carried its own offset (i.e. it is not limited to the
        naive/assume_tz case). Several call sites (schedule.py,
        shooting_execution.py, deepmath_people_recommendation.py) always
        normalize to one timezone regardless of the source offset; others
        (matcher.py, codex_maintenance_tasks.py, message_result_store.py)
        leave an already-aware input's offset untouched, so they must NOT
        pass this parameter.
    """
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        dt = datetime.combine(value, datetime.min.time())
    else:
        text = str(value or "").strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=assume_tz)
    if convert_to is not None:
        dt = dt.astimezone(convert_to)
    return dt


def _coerce_feishu_date(value: Any) -> int | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        # Respect whatever tzinfo the caller attached (or the system-local
        # interpretation Python gives a naive datetime) rather than
        # re-normalizing — this is the one case where the value is already
        # an unambiguous point in time, no string parsing involved.
        return int(value.timestamp() * 1000)
    if isinstance(value, (int, float)):
        number = int(value)
        return number if number > 10_000_000_000 else number * 1000
    dt = parse_iso_datetime(value, assume_tz=timezone.utc)
    return int(dt.timestamp() * 1000) if dt is not None else None


def feishu_first_url(value: Any) -> str:
    """Recursively pull the first http(s) URL out of ``value``.

    Handles a bare URL string, a URL embedded in a longer text blob, a dict
    (checking common link-ish keys first, then falling back to every value),
    a list/tuple/set of any of the above, and a JSON-encoded string of any
    of the above. Returns "" when nothing looks like a URL.

    Consolidated from two near-identical copies:
    openclaw-tag-router's ``router_shared_helpers._first_url_from_value``
    (dict priority-key walk + JSON-string parsing) and
    ``commercial_delivery._commercial_delivery_first_url`` (plain regex
    search). This is also the extraction primitive ``_coerce_feishu_url``
    uses for field_type 15 payloads.
    """
    if value in (None, "", []):
        return ""
    if isinstance(value, dict):
        for key in ("link", "url", "doc", "document_url", "inspiration_doc", "material_doc", "creation_doc"):
            found = feishu_first_url(value.get(key))
            if found:
                return found
        for item in value.values():
            found = feishu_first_url(item)
            if found:
                return found
        return ""
    if isinstance(value, (list, tuple, set)):
        for item in value:
            found = feishu_first_url(item)
            if found:
                return found
        return ""
    text = str(value).strip()
    if not text:
        return ""
    if text[:1] in "{[":
        try:
            return feishu_first_url(json.loads(text))
        except (TypeError, ValueError):
            pass
    match = URL_RE.search(text)
    return match.group(0).rstrip(".,，。") if match else ""


def feishu_first_url_or_text(value: Any) -> str:
    """Like :func:`feishu_first_url`, but falls back to ``str(value).strip()``
    instead of ``""`` when nothing looks like a URL.

    Consolidated from the url-3 dedup audit's second behavior class: a few
    call sites (router_shared_helpers._extract_first_url,
    commercial_delivery's first-URL lookup) historically pass a non-URL
    value straight through to the caller (e.g. using free text as a
    fallback title/description) rather than returning empty. That's a
    real behavior split from feishu_first_url's callers, which expect ""
    on a miss -- so this is a sibling function, not a merged one.
    """
    found = feishu_first_url(value)
    if found:
        return found
    return "" if value in (None, "", []) else str(value).strip()


def _coerce_feishu_url(value: Any, *, display_max_chars: int | None = None) -> dict[str, str] | str:
    if value in (None, "", []):
        return ""
    if isinstance(value, dict):
        link = str(value.get("link") or value.get("url") or "").strip()
        if not link.startswith(("http://", "https://")):
            link = feishu_first_url(value)
        if not link:
            return str(value.get("text") or "").strip()
        text = str(value.get("text") or "").strip() or link
        if display_max_chars is not None:
            text = text[:display_max_chars]
        return {"text": text, "link": link}
    if isinstance(value, str) and value.strip().startswith(("http://", "https://")):
        link = value.strip()
    else:
        link = feishu_first_url(value)
    if not link:
        return str(value).strip() if not isinstance(value, (list, tuple, set)) else ""
    text = link if display_max_chars is None else link[:display_max_chars]
    return {"text": text, "link": link}


def _coerce_feishu_attachments(value: Any) -> list[dict[str, str]]:
    if value in (None, "", []):
        return []
    raw_items = value if isinstance(value, list) else [value]
    attachments: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        file_token = str(item.get("file_token") or item.get("fileToken") or "").strip()
        if not file_token or file_token in seen:
            continue
        seen.add(file_token)
        attachments.append({"file_token": file_token})
    return attachments


def feishu_coerce_value(
    value: Any,
    field_type: Any,
    *,
    on_option_id: Literal["keep", "drop", "raise"] = "keep",
    url_display_max_chars: int | None = None,
) -> Any:
    """Coerce a business value into the payload shape a Feishu bitable field expects.

    ``on_option_id`` controls what happens when a select-type value (field_type
    3 or 4) looks like a Feishu-internal option id (``optXXXXXX`` — see
    ``BITABLE_OPTION_ID_RE``) instead of a real display name:
      - "keep" (default): pass it through unchanged. Preserves the original
        behavior of every pre-existing caller of this function.
      - "drop": silently discard that value (whole value for a single-select,
        just that item for a multi-select) — used by the two
        openclaw-tag-router callers that used to do this filtering themselves.
      - "raise": raise ValueError instead of writing it. Not currently wired
        up to any caller — integrations/feishu/media_writer.py keeps its own
        independent ``_reject_option_ids`` outer check instead.

    ``url_display_max_chars`` caps the display text of a field_type 15
    (hyperlink) payload; the link itself is never truncated. None (default)
    leaves the display text uncapped.
    """
    if value is None:
        return ""
    if field_type == 1:
        if isinstance(value, (dict, list)):
            return json_dumps(value)
        return str(value)
    if field_type == 3:
        if isinstance(value, list):
            value = next((item for item in value if str(item).strip()), "")
        text = str(value).strip()
        if on_option_id != "keep" and text and BITABLE_OPTION_ID_RE.fullmatch(text):
            if on_option_id == "raise":
                raise ValueError(f"feishu single-select value looks like an option id: {text!r}")
            return None
        return text
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
            if on_option_id != "keep" and BITABLE_OPTION_ID_RE.fullmatch(text):
                if on_option_id == "raise":
                    raise ValueError(f"feishu multi-select value looks like an option id: {text!r}")
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
        return _coerce_feishu_url(value, display_max_chars=url_display_max_chars)
    if field_type == 17:
        return _coerce_feishu_attachments(value)
    if isinstance(value, (dict, list)):
        return json_dumps(value)
    return str(value)


def feishu_plain_text(value: Any, *, list_separator: str = "\n", unknown_dict: str = "json") -> str:
    """Render a Feishu field value as plain text.

    ``list_separator`` joins a list's rendered items (default ``"\\n"``,
    matching every one of this function's 61 pre-existing call sites).

    ``unknown_dict`` controls what a dict renders as when none of its
    ``("text", "link", "url", "name", "value")`` keys yields text:
    ``"json"`` (the default, matching existing behavior) dumps the whole
    dict as JSON; ``"empty"`` returns ``""`` instead, for callers that
    would rather drop an unrecognized structured value than surface its
    raw JSON.
    """
    if value in (None, "", []):
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, dict):
        for key in ("text", "link", "url", "name", "value"):
            text = feishu_plain_text(value.get(key), list_separator=list_separator, unknown_dict=unknown_dict)
            if text:
                return text
        return json_dumps(value) if unknown_dict == "json" else ""
    if isinstance(value, list):
        parts = [feishu_plain_text(item, list_separator=list_separator, unknown_dict=unknown_dict) for item in value]
        return list_separator.join(part for part in parts if part)
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
        return f"已写入飞书 {len(record_ids)} 条记录"
    if not record_count:
        return "未发现需要写入的记录"
    if not bitable_url:
        return "未写入飞书：请提供明确的飞书多维表链接"
    return "已配置飞书，但没有写入记录"
