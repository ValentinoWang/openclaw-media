#!/usr/bin/env python3
"""Synchronise the Media OS Feishu Base into the B-tenant read model.

The command is read-only against Feishu.  It defaults to a dry run; pass
``--execute`` to commit PostgreSQL upserts.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from openclaw_app.account import AccountDatabase, AccountDatabaseSettings
from openclaw_app.services.feishu_service import FeishuService
from openclaw_app.services.media_business.lark_base_projection import (
    DEFAULT_REGISTRY_PATH,
    TABLE_SPECS,
    TARGET_TENANT_ID,
    LarkBaseProjection,
)


def _settings_activity_url(settings: dict[str, Any], env: dict[str, str]) -> str:
    """Read an explicitly declared activity URL without inventing a default."""

    for mapping, key in (
        (settings.get("media_os"), "activity_url"),
        (settings.get("media_business"), "activity_url"),
        (settings.get("feishu"), "media_os_activity_url"),
    ):
        if isinstance(mapping, dict):
            value = _resolved(mapping.get(key, ""), env)
            if value:
                return value
    return ""


def _validate_activity_url(value: str) -> str:
    url = str(value or "").strip()
    parsed = urlparse(url)
    table_id = (parse_qs(parsed.query).get("table") or [""])[0].strip()
    if parsed.scheme != "https" or not parsed.netloc or not table_id:
        raise RuntimeError("MEDIA_OS_ACTIVITY_URL must be an HTTPS Feishu Base/Wiki URL with a table query parameter")
    if not (parsed.path.startswith("/wiki/") or parsed.path.startswith("/base/")):
        raise RuntimeError("MEDIA_OS_ACTIVITY_URL must point to a Feishu Base or Wiki node")
    return url


def _resolve_activity_url(
    settings: dict[str, Any],
    registry_path: Path,
    env: dict[str, str],
) -> tuple[str, str]:
    """Resolve an activity URL in declared-authority order."""

    registry_value = ""
    if registry_path.is_file():
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        tables = registry.get("tables") if isinstance(registry, dict) else None
        if isinstance(tables, dict):
            activity = tables.get("activity")
            if isinstance(activity, dict):
                env_values = activity.get("env")
                if isinstance(env_values, dict):
                    registry_value = str(env_values.get("MEDIA_OS_ACTIVITY_URL") or "").strip()
    if registry_value:
        return _validate_activity_url(registry_value), "registry"

    configured = _settings_activity_url(settings, env)
    if configured:
        return _validate_activity_url(configured), "settings"

    environment_value = str(env.get("MEDIA_OS_ACTIVITY_URL") or "").strip()
    if environment_value:
        return _validate_activity_url(environment_value), "environment"
    raise RuntimeError("MEDIA_OS_ACTIVITY_URL is not declared by registry, settings, or environment")


def _load_registry_table_bindings(path: Path) -> tuple[str, dict[str, dict[str, str]]]:
    """Load the current registry-v2 table bindings for CLI/readback callers."""

    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"REGISTRY_INVALID: {path}") from exc
    tables = document.get("tables") if isinstance(document, dict) else None
    if not isinstance(tables, list):
        raise RuntimeError("REGISTRY_INVALID: tables must be a list")

    base_token = ""
    bindings: dict[str, dict[str, str]] = {}
    for index, raw_table in enumerate(tables):
        if not isinstance(raw_table, dict):
            raise RuntimeError(f"REGISTRY_INVALID: tables[{index}]")
        row_base_token = str(raw_table.get("base_token") or "").strip()
        table_id = str(raw_table.get("table_id") or "").strip()
        table_key = str(raw_table.get("table_key") or "").strip()
        target_table = str(raw_table.get("postgres_target") or raw_table.get("target_table") or "").strip()
        if not row_base_token or not table_id or not table_key:
            continue
        if not base_token or table_key == "source_asset":
            base_token = row_base_token
        if target_table:
            bindings[target_table] = {
                "base_token": row_base_token,
                "table_id": table_id,
                "table_name": str(raw_table.get("observed_feishu_table_display_name") or "").strip(),
                "target_table_name": str(raw_table.get("target_feishu_table_display_name") or "").strip(),
            }
    if not base_token or not bindings:
        raise RuntimeError("REGISTRY_INVALID: no current table bindings")
    return base_token, bindings


def _load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, separator, value = line.partition("=")
        if not separator:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key.strip()] = value
    return values


def _resolved(value: Any, env: dict[str, str]) -> str:
    text = str(value or "").strip()
    if text.startswith("${") and text.endswith("}"):
        return env.get(text[2:-1].strip(), "")
    return text


def _build_feishu(settings_path: Path, env: dict[str, str]) -> FeishuService:
    settings = yaml.safe_load(settings_path.read_text(encoding="utf-8")) or {}
    config = settings.get("feishu") or {}
    return FeishuService(
        config.get("mode", "api"),
        _resolved(config.get("local_docs_dir", "/tmp/openclaw-feishu-docs"), env),
        _resolved(config.get("webhook_url", ""), env),
        _resolved(config.get("app_id", ""), env) or env.get("FEISHU_APP_ID", ""),
        _resolved(config.get("app_secret", ""), env) or env.get("FEISHU_APP_SECRET", ""),
        _resolved(config.get("api_base_url", ""), env),
        _resolved(config.get("web_base_url", ""), env),
        _resolved(config.get("folder_token", ""), env),
        _resolved(config.get("knowledge_base_space_id", ""), env),
        _resolved(config.get("knowledge_base_parent_node_token", ""), env),
        config.get("knowledge_base_obj_type", "docx"),
        config.get("knowledge_base_spaces", []),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Project the Media OS Feishu Base into PostgreSQL")
    parser.add_argument("--execute", action="store_true", help="commit PostgreSQL upserts; default is dry-run")
    parser.add_argument("--tenant-id", default=TARGET_TENANT_ID)
    parser.add_argument("--base-token", default="", help="resolved Bitable app token")
    parser.add_argument("--settings", default="/home/ubuntu/selfmedia-tools/openclaw-tag-router/openclaw_app/config/settings.yaml")
    parser.add_argument("--feishu-env", default="/home/ubuntu/.openclaw/openclaw-feishu-env.conf")
    parser.add_argument("--auth-env", default="/home/ubuntu/.config/openclaw-bot-center/auth-media-cm1.env")
    parser.add_argument("--media-registry", default=str(DEFAULT_REGISTRY_PATH))
    parser.add_argument("--target-table", action="append", default=[], help="project only the named read-model table")
    args = parser.parse_args()

    env = dict(os.environ)
    env.update(_load_env_file(Path(args.feishu_env)))
    # The database URL is deliberately read through the existing account
    # contract.  No credentials are emitted by this script.
    auth_env = _load_env_file(Path(args.auth_env))
    auth_env.update({key: value for key, value in os.environ.items() if key.startswith("OPENCLAW_")})
    database = AccountDatabase(AccountDatabaseSettings.from_environment(auth_env))
    feishu = _build_feishu(Path(args.settings), env)
    projection = LarkBaseProjection(
        feishu,
        database.connect,
        tenant_id=args.tenant_id,
        base_token=args.base_token,
        registry_path=args.media_registry,
    )
    target_tables = set(args.target_table) or None
    unknown_targets = (target_tables or set()) - {spec.target_table for spec in TABLE_SPECS}
    if unknown_targets:
        parser.error(f"unknown target table(s): {', '.join(sorted(unknown_targets))}")
    result = projection.project(dry_run=not args.execute, target_tables=target_tables)
    result["base_token"] = projection.base_token
    result["table_binding_source"] = "media_registry"
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
