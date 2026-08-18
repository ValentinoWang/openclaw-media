#!/usr/bin/env python3
"""Delete Media OS creation-run traces from Feishu and local generated files.

Default mode is a dry-run. Pass --apply to perform deletions.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import requests

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from openclaw_app.services.resource_owner_registry import ResourceOwnerRegistry, require_tenant_id
from openclaw_app.services.tenant_owned_resources import TenantOwnedResourceService


DEFAULT_MEDIA_ENV_PATH = Path("/home/ubuntu/openclaw-agents/media/.env.local")
AGENT_RESULTS_CONTRACT_PATH = Path("/home/ubuntu/docs/ai-harness/agent_result_vault_contract.json")


def agent_results_base() -> Path:
    contract = json.loads(AGENT_RESULTS_CONTRACT_PATH.read_text(encoding="utf-8"))
    return Path(str(contract["physical_root"]))


def agent_results_required_folders() -> tuple[str, ...]:
    contract = json.loads(AGENT_RESULTS_CONTRACT_PATH.read_text(encoding="utf-8"))
    folders = contract.get("required_folders")
    if not isinstance(folders, list) or not all(isinstance(folder, str) for folder in folders):
        raise RuntimeError(f"invalid agent result vault contract folders: {AGENT_RESULTS_CONTRACT_PATH}")
    return tuple(folders)


AGENT_RESULTS_BASE = agent_results_base()
AGENT_RESULT_ROOTS = tuple(
    AGENT_RESULTS_BASE / folder for folder in agent_results_required_folders()
)
DEFAULT_MEDIA_VAULT_ROOT = Path("/home/ubuntu/selfmedia-tools/data/media_vault")
RUN_ID_RE = re.compile(r"^run_[A-Za-z0-9_:-]+$")
URL_RE = re.compile(r"https?://[^\s，。；;、)）>\"']+")
FEISHU_BASE_DEFAULT = "https://open.feishu.cn/open-apis"


@dataclass
class DeletionAction:
    kind: str
    target: str
    status: str = "planned"
    detail: str = ""


@dataclass
class RunPlan:
    run_id: str
    record_id: str = ""
    input_summary: str = ""
    entrypoint: str = ""
    doc_urls: list[str] = field(default_factory=list)
    local_paths: list[str] = field(default_factory=list)
    actions: list[DeletionAction] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def load_env_file(path: Path, *, override: bool = False) -> None:
    if not path.exists() or not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key.startswith("export "):
            key = key[len("export ") :].strip()
        value = value.strip().strip("'").strip('"')
        if key and (override or key not in os.environ):
            os.environ[key] = value


def load_openclaw_feishu_account_env(account: str = "media", *, override: bool = False) -> None:
    config_path = Path(os.getenv("OPENCLAW_CONFIG", "/home/ubuntu/.openclaw/openclaw.json")).expanduser()
    if not config_path.exists():
        return
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return
    accounts = (((config.get("channels") or {}).get("feishu") or {}).get("accounts") or {})
    account_config = accounts.get(account) or {}
    app_id = str(account_config.get("appId") or account_config.get("app_id") or "").strip()
    app_secret = str(account_config.get("appSecret") or account_config.get("app_secret") or "").strip()
    if app_id and (override or not os.getenv("FEISHU_APP_ID")):
        os.environ["FEISHU_APP_ID"] = app_id
    if app_secret and (override or not os.getenv("FEISHU_APP_SECRET")):
        os.environ["FEISHU_APP_SECRET"] = app_secret


def load_default_env() -> None:
    selfmedia_root = Path("/home/ubuntu/selfmedia-tools")
    for path in (
        selfmedia_root / ".env",
        selfmedia_root / ".env.local",
        DEFAULT_MEDIA_ENV_PATH,
        Path("/home/ubuntu/.openclaw/openclaw-media.env"),
        Path("/home/ubuntu/openclaw-feishu-reminder/reminder.env"),
        selfmedia_root / "selfmedia" / "ingest" / "content_flow" / ".env",
    ):
        load_env_file(path)
    # The Media web service also hosts other Feishu-backed capabilities. Always
    # pin cleanup to the Media app instead of inheriting another app's process env.
    load_openclaw_feishu_account_env(
        os.getenv("SELFMEDIA_OPENCLAW_FEISHU_ACCOUNT", "media"),
        override=True,
    )
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


def feishu_base() -> str:
    return os.getenv("FEISHU_API_BASE_URL", FEISHU_BASE_DEFAULT).rstrip("/")


def tenant_access_token() -> str:
    app_id = os.getenv("FEISHU_APP_ID", "").strip()
    app_secret = os.getenv("FEISHU_APP_SECRET", "").strip()
    if not app_id or not app_secret:
        raise RuntimeError("FEISHU_APP_ID / FEISHU_APP_SECRET is not configured")
    response = requests.post(
        f"{feishu_base()}/auth/v3/tenant_access_token/internal",
        json={"app_id": app_id, "app_secret": app_secret},
        timeout=20,
    )
    payload = response_json(response)
    if response.status_code >= 400 or payload.get("code") not in {None, 0}:
        raise RuntimeError(f"failed to get tenant access token: status={response.status_code}, payload={payload}")
    token = str(payload.get("tenant_access_token") or (payload.get("data") or {}).get("tenant_access_token") or "")
    if not token:
        raise RuntimeError(f"tenant_access_token missing from response: {payload}")
    return token


def response_json(response: requests.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError:
        payload = {"raw": response.text}
    return payload if isinstance(payload, dict) else {"raw": payload}


def request_json(
    method: str,
    path: str,
    token: str,
    *,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
    timeout: int = 30,
) -> dict[str, Any]:
    response = requests.request(
        method,
        f"{feishu_base()}{path}",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"},
        params=params,
        json=json_body,
        timeout=timeout,
    )
    payload = response_json(response)
    if response.status_code >= 400 or payload.get("code") not in {None, 0}:
        raise RuntimeError(f"{method} {path} failed: status={response.status_code}, payload={payload}")
    return payload


def load_creation_runs_url(explicit: str = "") -> str:
    if explicit.strip():
        return explicit.strip()
    env_value = os.getenv("MEDIA_OS_CREATION_RUNS_URL", "").strip()
    if env_value:
        return env_value
    load_env_file(DEFAULT_MEDIA_ENV_PATH)
    env_value = os.getenv("MEDIA_OS_CREATION_RUNS_URL", "").strip()
    if env_value:
        return env_value
    return ""


def resolve_wiki_node(token: str, access_token: str) -> dict[str, Any]:
    payload = request_json("GET", "/wiki/v2/spaces/get_node", access_token, params={"token": token})
    node = (payload.get("data") or {}).get("node") or {}
    if not isinstance(node, dict):
        raise RuntimeError(f"wiki get_node returned invalid node: {payload}")
    return node


def parse_bitable_refs(table_url: str, access_token: str) -> tuple[str, str]:
    parsed = urlparse(table_url)
    query = parse_qs(parsed.query)
    table_id = (query.get("table") or [""])[0]
    if not table_id:
        raise RuntimeError("CreationRuns URL is missing table= parameter")
    wiki_match = re.search(r"/wiki/([A-Za-z0-9]+)", parsed.path)
    if wiki_match:
        node = resolve_wiki_node(wiki_match.group(1), access_token)
        if node.get("obj_type") != "bitable":
            raise RuntimeError(f"CreationRuns wiki node is not bitable: {node.get('obj_type')}")
        app_token = str(node.get("obj_token") or "")
        if not app_token:
            raise RuntimeError("CreationRuns wiki node is missing obj_token")
        return app_token, table_id
    base_match = re.search(r"/base/([A-Za-z0-9]+)", parsed.path)
    if base_match:
        return base_match.group(1), table_id
    raise RuntimeError("CreationRuns URL must contain /wiki/<token> or /base/<app_token>")


def list_records(
    app_token: str,
    table_id: str,
    access_token: str,
    *,
    run_ids: list[str],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for run_id in run_ids:
        page_token = ""
        while True:
            params: dict[str, Any] = {
                "page_size": 2,
                "filter": f'CurrentValue.[创作运行ID] = {json.dumps(run_id, ensure_ascii=False)}',
            }
            if page_token:
                params["page_token"] = page_token
            payload = request_json(
                "GET",
                f"/bitable/v1/apps/{app_token}/tables/{table_id}/records",
                access_token,
                params=params,
            )
            data = payload.get("data") or {}
            records.extend(data.get("items") or [])
            if not data.get("has_more"):
                break
            page_token = str(data.get("page_token") or "")
            if not page_token:
                raise RuntimeError("CreationRuns filtered pagination did not advance")
    return records


def extract_urls(value: Any) -> list[str]:
    result: list[str] = []
    if isinstance(value, dict):
        for key in ("link", "url", "text"):
            result.extend(extract_urls(value.get(key)))
    elif isinstance(value, list):
        for item in value:
            result.extend(extract_urls(item))
    elif isinstance(value, str):
        result.extend(match.rstrip(".,，。") for match in URL_RE.findall(value))
    seen: set[str] = set()
    unique: list[str] = []
    for item in result:
        if item and item not in seen:
            seen.add(item)
            unique.append(item)
    return unique


def delete_record(app_token: str, table_id: str, record_id: str, access_token: str) -> None:
    request_json("DELETE", f"/bitable/v1/apps/{app_token}/tables/{table_id}/records/{record_id}", access_token)


def parse_feishu_doc_url(url: str) -> dict[str, str] | None:
    parsed = urlparse(url)
    if "feishu.cn" not in parsed.netloc and "larksuite.com" not in parsed.netloc:
        return None
    parts = [part for part in parsed.path.split("/") if part]
    for index, part in enumerate(parts):
        if part in {"wiki", "docx", "doc", "docs"} and index + 1 < len(parts):
            kind = "docx" if part in {"docx", "doc", "docs"} else "wiki"
            token = re.sub(r"[^A-Za-z0-9_-]", "", parts[index + 1])
            if token:
                return {"kind": kind, "token": token}
    return None


def delete_doc_url(url: str, access_token: str) -> DeletionAction:
    parsed = parse_feishu_doc_url(url)
    if not parsed:
        return DeletionAction("feishu_doc", url, "skipped", "not a supported Feishu document URL")
    if parsed["kind"] == "wiki":
        node = resolve_wiki_node(parsed["token"], access_token)
        obj_token = str(node.get("obj_token") or "")
        obj_type = str(node.get("obj_type") or "")
        if not obj_token:
            return DeletionAction("feishu_doc", url, "failed", f"wiki node has no obj_token: {node}")
        obj_type = "docx" if obj_type == "doc" else (obj_type or "docx")
        try:
            request_json("DELETE", f"/drive/v1/files/{obj_token}", access_token, params={"type": obj_type})
            return DeletionAction("feishu_doc", url, "deleted", f"drive file deleted; obj_type={obj_type}, obj_token={obj_token}")
        except Exception as exc:
            return DeletionAction("feishu_doc", url, "failed", str(exc))
    obj_type = "docx"
    try:
        request_json("DELETE", f"/drive/v1/files/{parsed['token']}", access_token, params={"type": obj_type})
        return DeletionAction("feishu_doc", url, "deleted", f"drive file deleted; obj_type={obj_type}")
    except Exception as exc:
        return DeletionAction("feishu_doc", url, "failed", str(exc))


def safe_under(path: Path, roots: list[Path]) -> bool:
    resolved = path.resolve()
    for root in roots:
        try:
            resolved.relative_to(root.resolve())
            return True
        except ValueError:
            continue
    return False


def discover_local_paths(run_id: str, roots: list[Path]) -> list[Path]:
    paths: list[Path] = []
    for root in roots:
        root = root.expanduser()
        if not root.exists():
            continue
        exact = root / run_id
        if exact.exists():
            paths.append(exact)
        for path in root.rglob("*"):
            if path in paths:
                continue
            if run_id in path.name:
                paths.append(path)
                continue
    unique: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        resolved = path.resolve()
        if resolved not in seen and safe_under(resolved, roots):
            seen.add(resolved)
            unique.append(resolved)
    return unique


def delete_local_path(path: Path, roots: list[Path]) -> DeletionAction:
    if not safe_under(path, roots):
        return DeletionAction("local_path", str(path), "failed", "path is outside allowed local roots")
    try:
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()
        else:
            return DeletionAction("local_path", str(path), "skipped", "already absent")
    except OSError as exc:
        return DeletionAction("local_path", str(path), "failed", str(exc))
    return DeletionAction("local_path", str(path), "deleted", "")


def normalize_run_ids(args: argparse.Namespace) -> list[str]:
    values: list[str] = []
    values.extend(args.run_id or [])
    if args.run_ids_file:
        values.extend(Path(args.run_ids_file).read_text(encoding="utf-8").splitlines())
    result: list[str] = []
    seen: set[str] = set()
    for raw in values:
        value = raw.strip()
        if not value or value.startswith("#"):
            continue
        if not RUN_ID_RE.match(value):
            raise SystemExit(f"invalid run id: {value}")
        if value not in seen:
            seen.add(value)
            result.append(value)
    if not result:
        raise SystemExit("provide at least one --run-id or --run-ids-file")
    return result


def build_plans(
    run_ids: list[str],
    records: list[dict[str, Any]],
    local_roots: list[Path],
) -> dict[str, RunPlan]:
    plans = {run_id: RunPlan(run_id=run_id) for run_id in run_ids}
    by_run: dict[str, dict[str, Any]] = {}
    for record in records:
        fields = record.get("fields") or {}
        run_id = str(fields.get("创作运行ID") or "").strip()
        if run_id in plans:
            by_run[run_id] = record

    for run_id, plan in plans.items():
        record = by_run.get(run_id)
        if record:
            fields = record.get("fields") or {}
            plan.record_id = str(record.get("record_id") or record.get("id") or "")
            plan.input_summary = str(fields.get("输入需求摘要") or "")
            plan.entrypoint = str(fields.get("入口标签") or "")
            urls: list[str] = []
            for field_name in ("飞书文档链接", "运行产物URI"):
                urls.extend(extract_urls(fields.get(field_name)))
            plan.doc_urls = sorted(set(url for url in urls if parse_feishu_doc_url(url)))
            if plan.record_id:
                plan.actions.append(DeletionAction("creation_run_record", plan.record_id))
            else:
                plan.warnings.append("matching record has no record_id")
            for url in plan.doc_urls:
                plan.actions.append(DeletionAction("feishu_doc", url))
        else:
            plan.warnings.append("CreationRuns record not found")

        local_paths = discover_local_paths(run_id, local_roots)
        plan.local_paths = [str(path) for path in local_paths]
        for path in local_paths:
            plan.actions.append(DeletionAction("local_path", str(path)))
    return plans


def execute_plans(
    plans: dict[str, RunPlan],
    *,
    access_token: str,
    app_token: str,
    table_id: str,
    local_roots: list[Path],
    apply: bool,
    delete_docs: bool,
    delete_records: bool,
    delete_local: bool,
) -> None:
    if not apply:
        return
    for plan in plans.values():
        executed: list[DeletionAction] = []
        ordered_actions = sorted(
            plan.actions,
            key=lambda item: {"feishu_doc": 0, "local_path": 1, "creation_run_record": 2}.get(item.kind, 9),
        )
        blocked_record_delete = False
        for action in ordered_actions:
            if action.kind == "creation_run_record":
                if blocked_record_delete:
                    executed.append(DeletionAction(action.kind, action.target, "skipped", "Feishu document deletion failed"))
                    continue
                if not delete_records:
                    executed.append(DeletionAction(action.kind, action.target, "skipped", "--skip-records"))
                    continue
                try:
                    delete_record(app_token, table_id, action.target, access_token)
                    executed.append(DeletionAction(action.kind, action.target, "deleted", ""))
                except Exception as exc:
                    executed.append(DeletionAction(action.kind, action.target, "failed", str(exc)))
            elif action.kind == "feishu_doc":
                if not delete_docs:
                    executed.append(DeletionAction(action.kind, action.target, "skipped", "--skip-docs"))
                    continue
                result = delete_doc_url(action.target, access_token)
                if result.status == "failed":
                    blocked_record_delete = True
                executed.append(result)
            elif action.kind == "local_path":
                if not delete_local:
                    executed.append(DeletionAction(action.kind, action.target, "skipped", "--skip-local"))
                    continue
                executed.append(delete_local_path(Path(action.target), local_roots))
            else:
                executed.append(DeletionAction(action.kind, action.target, "skipped", "unknown action"))
        plan.actions = executed


def to_jsonable(plans: dict[str, RunPlan], *, apply: bool, creation_runs_url: str) -> dict[str, Any]:
    return {
        "mode": "apply" if apply else "dry_run",
        "creation_runs_url": creation_runs_url,
        "runs": [
            {
                "run_id": plan.run_id,
                "record_id": plan.record_id,
                "entrypoint": plan.entrypoint,
                "input_summary": plan.input_summary,
                "doc_urls": plan.doc_urls,
                "local_paths": plan.local_paths,
                "warnings": plan.warnings,
                "actions": [action.__dict__ for action in plan.actions],
            }
            for plan in plans.values()
        ],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", action="append", help="Creation run id to delete; repeatable")
    parser.add_argument("--run-ids-file", help="File with one run id per line")
    parser.add_argument("--creation-runs-url", default="", help="Override MEDIA_OS_CREATION_RUNS_URL")
    parser.add_argument("--local-root", action="append", help="Allowed local cleanup root; repeatable")
    parser.add_argument("--tenant-id", required=True, help="Authenticated Sub2API tenant id")
    parser.add_argument(
        "--resource-owner-db",
        default=os.getenv("OPENCLAW_RESOURCE_OWNER_DB_PATH", "/home/ubuntu/.openclaw/state/resource_owners.sqlite3"),
        help="Canonical resource owner registry path",
    )
    parser.add_argument("--apply", action="store_true", help="Actually delete. Default is dry-run only.")
    parser.add_argument("--skip-docs", action="store_true", help="Do not delete Feishu wiki/docx documents")
    parser.add_argument("--skip-records", action="store_true", help="Do not delete CreationRuns records")
    parser.add_argument("--skip-local", action="store_true", help="Do not delete local artifacts")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    load_default_env()
    tenant_id = require_tenant_id(args.tenant_id)
    run_ids = normalize_run_ids(args)
    owner_service = TenantOwnedResourceService(ResourceOwnerRegistry(args.resource_owner_db))
    for run_id in run_ids:
        owner_service.registry.assert_owner(
            "media.creation_run",
            run_id,
            session_tenant_id=tenant_id,
        )
    tenant_vault_root = DEFAULT_MEDIA_VAULT_ROOT / "tenants" / tenant_id
    local_roots = [Path(item).expanduser() for item in (args.local_root or [])] or [tenant_vault_root, *AGENT_RESULT_ROOTS]
    creation_runs_url = load_creation_runs_url(args.creation_runs_url)
    if not creation_runs_url:
        raise SystemExit("MEDIA_OS_CREATION_RUNS_URL is not configured")

    access_token = tenant_access_token()
    app_token, table_id = parse_bitable_refs(creation_runs_url, access_token)
    records = list_records(app_token, table_id, access_token, run_ids=run_ids)
    for record in records:
        fields = record.get("fields") or {}
        run_id = str(fields.get("创作运行ID") or "").strip()
        owner_service.assert_projection_read(
            "media.creation_run",
            run_id,
            session_tenant_id=tenant_id,
            fields=fields,
            projection_source=f"feishu:{table_id}/{record.get('record_id') or 'missing'}",
        )
    plans = build_plans(run_ids, records, local_roots)
    execute_plans(
        plans,
        access_token=access_token,
        app_token=app_token,
        table_id=table_id,
        local_roots=local_roots,
        apply=args.apply,
        delete_docs=not args.skip_docs,
        delete_records=not args.skip_records,
        delete_local=not args.skip_local,
    )
    print(json.dumps(to_jsonable(plans, apply=args.apply, creation_runs_url=creation_runs_url), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
