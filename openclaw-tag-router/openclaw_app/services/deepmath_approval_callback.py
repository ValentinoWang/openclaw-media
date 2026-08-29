"""Thin JSON callback entrypoint for the existing verified card transport."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Callable, Mapping, Sequence
from datetime import datetime

try:
    import yaml
except ImportError:  # pragma: no cover - the active tag-router already requires PyYAML
    yaml = None

_YAML_ERROR = getattr(yaml, "YAMLError", ValueError)

if __package__ in {None, ""}:  # Allow the gateway to invoke this file as a thin process.
    # parents[2] is the openclaw-tag-router package root (needed for the
    # openclaw_app.* imports below); parents[3] is the repository root,
    # needed because deepmath_people_recommendation.py (imported transitively
    # via deepmath_thinking_intake below) imports from common.social_runtime.
    # Insert the repository root first so the router root -- which owns its
    # own same-named subpackages -- still takes priority, matching
    # tests/conftest.py's reverse-priority ordering.
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from openclaw_app.services.deepmath_approval_service import DeepMathApprovalService, DeepMathExecutorRegistry
    from openclaw_app.services.deepmath_approval_store import DeepMathApprovalStore, DeepMathApprovalStoreError
    from openclaw_app.services.deepmath_tasks_executor import (
        DeepMathTasksExecutor,
        DeepMathTasksResultUnknown,
        DeepMathTasksTransport,
        DeepMathTasksUpstreamRejected,
    )
    from openclaw_app.services.deepmath_thinking_intake import DeepMathBitableClient
    from openclaw_app.services.deepmath_resources import load_resource_config
else:
    from .deepmath_approval_service import DeepMathApprovalService, DeepMathExecutorRegistry
    from .deepmath_approval_store import DeepMathApprovalStore, DeepMathApprovalStoreError
    from .deepmath_tasks_executor import (
        DeepMathTasksExecutor,
        DeepMathTasksResultUnknown,
        DeepMathTasksTransport,
        DeepMathTasksUpstreamRejected,
    )
    from .deepmath_thinking_intake import DeepMathBitableClient
    from .deepmath_resources import load_resource_config


DEEP_MATH_TENANT_KEY = "deepmath"
CONFIG_ENV = "OPENCLAW_DEEPMATH_CONFIG_PATH"
TOKEN_SECRET_ENV = "OPENCLAW_DEEPMATH_APPROVAL_TOKEN_SECRET"
_ENV_REFERENCE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}\Z")


class DeepMathApprovalCallbackError(ValueError):
    pass


@dataclass(frozen=True)
class DeepMathApprovalCallbackConfig:
    state_path: str
    approver_user_id: str
    authorized_actor_ids: frozenset[str]
    token_signing_secret: str | None = None
    resource_config_path: str = ""
    settings_path: str = ""
    clock: Callable[[], datetime] | None = None


def _resolve_config_value(value: Any, *, secret: bool = False) -> str:
    text = str(value or "").strip()
    match = _ENV_REFERENCE.fullmatch(text)
    if match:
        text = os.environ.get(match.group(1), "").strip()
    if secret and not text:
        text = os.environ.get(TOKEN_SECRET_ENV, "").strip()
    return text


def load_deepmath_approval_config(path: str | Path) -> DeepMathApprovalCallbackConfig:
    """Read only the canonical DeepMath config section needed by U5."""

    config_path = Path(str(path or "")).expanduser()
    if not config_path.is_file():
        raise DeepMathApprovalCallbackError("DeepMath approval config is unavailable")
    try:
        if config_path.suffix.lower() == ".json":
            value = json.loads(config_path.read_text(encoding="utf-8"))
        else:
            if yaml is None:
                raise DeepMathApprovalCallbackError("DeepMath approval YAML loader is unavailable")
            value = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError, _YAML_ERROR) as exc:
        raise DeepMathApprovalCallbackError("DeepMath approval config is unreadable") from exc
    section = value.get("deepmath_ceo_thinking") if isinstance(value, Mapping) else None
    if not isinstance(section, Mapping):
        raise DeepMathApprovalCallbackError("DeepMath approval config section is missing")
    state_path = _resolve_config_value(section.get("approval_state_path"))
    approver = _resolve_config_value(section.get("approver_open_id"))
    if not state_path or not approver:
        raise DeepMathApprovalCallbackError("DeepMath approval state path or approver is not configured")
    if "authorized_actor_ids" in section:
        raise DeepMathApprovalCallbackError("DeepMath approval uses exactly one configured approver")
    actors = frozenset({approver})
    signing_secret = _resolve_config_value(section.get("approval_token_signing_secret"), secret=True)
    if not signing_secret:
        raise DeepMathApprovalCallbackError("DeepMath approval token signing secret is unavailable")
    resource_config_path = _resolve_config_value(section.get("resource_config_path"))
    return DeepMathApprovalCallbackConfig(
        state_path=state_path,
        approver_user_id=approver,
        authorized_actor_ids=actors,
        token_signing_secret=signing_secret,
        resource_config_path=resource_config_path,
        settings_path=str(config_path),
    )


def _resolve_people_selection(config: DeepMathApprovalCallbackConfig, selection: Mapping[str, Any]) -> Mapping[str, Any]:
    """Freshly resolve opaque human selections without invoking an LLM."""

    if not config.settings_path or not config.resource_config_path:
        return {"status": "pending_manual", "reason": "people_runtime_unavailable"}
    from openclaw_app.services.deepmath_people_runtime import (
        load_people_capability_base_id,
        make_people_recommendation_service,
    )
    from openclaw_app.services.deepmath_runtime_config import load_deepmath_account

    resource = load_resource_config(config.resource_config_path)
    app_id, app_secret = load_deepmath_account()
    token_client = DeepMathBitableClient(resource.base_id, app_id, app_secret)
    service = make_people_recommendation_service(
        capability_app_token=load_people_capability_base_id(config.settings_path),
        resource=resource,
        access_token=token_client.token,
        llm=lambda _request: (_ for _ in ()).throw(RuntimeError("LLM is not part of approval validation")),
    )
    return service._resolve_private_selection(selection)


def _tasks_executor_registry(config: DeepMathApprovalCallbackConfig) -> DeepMathExecutorRegistry:
    """Register only the canonical U7 task-create executor, initialized after claim."""

    registry = DeepMathExecutorRegistry()
    if not config.resource_config_path:
        return registry

    def execute_task(claim):
        from openclaw_app.services.deepmath_runtime_config import load_deepmath_account

        resource = load_resource_config(config.resource_config_path)
        app_id, app_secret = load_deepmath_account()
        try:
            transport = DeepMathTasksTransport.from_app_credentials(app_id, app_secret)
        except DeepMathTasksUpstreamRejected:
            return {
                "status": "failed", "error_code": "tasks_auth_rejected",
                "receipt": {"status": "failed", "reason": "authentication_rejected"},
            }
        except DeepMathTasksResultUnknown:
            return {
                "status": "result_unknown", "error_code": "tasks_auth_result_unknown",
                "receipt": {"status": "result_unknown", "retry": "forbidden_without_reconciliation"},
            }
        return DeepMathTasksExecutor(transport, resource)(claim)

    registry.register("任务", "创建", execute_task)
    return registry


_SECRET_KEYS = frozenset({
    "token", "token_hash", "claim_token", "actor_id", "approver_user_id", "open_id", "chat_id",
    "app_secret", "access_token", "authorization", "payload_sha256", "tenant_key", "proposal_id", "approval_id",
})


def _safe_value(key: str, value: Any) -> Any:
    if key == "card":
        # A replacement card is an intentional outbound transport payload;
        # it is not written to logs or included in diagnostic errors.
        return value
    if key.lower() in _SECRET_KEYS or "secret" in key.lower() or "password" in key.lower():
        return None
    if isinstance(value, Mapping):
        return {str(child_key): child_value for child_key, child in value.items() if (child_value := _safe_value(str(child_key), child)) is not None}
    if isinstance(value, list):
        return [_safe_value(key, child) for child in value]
    return value


def safe_callback_result(value: Mapping[str, Any]) -> dict[str, Any]:
    result = _safe_value("result", value)
    return result if isinstance(result, dict) else {"status": "error", "code": "unsafe_result"}


def _timestamp_ms(value: Any) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return int(parsed.timestamp() * 1000)


def _project_audit_item(config: DeepMathApprovalCallbackConfig, item: Mapping[str, Any], actor_id: str) -> bool:
    if not config.resource_config_path:
        return False
    resource = load_resource_config(config.resource_config_path)
    if not resource.base_id:
        raise DeepMathApprovalCallbackError("DeepMath approval projection Base is unavailable")
    from openclaw_app.services.deepmath_runtime_config import load_deepmath_account
    app_id, app_secret = load_deepmath_account()
    client = DeepMathBitableClient(resource.base_id, app_id, app_secret)
    approval_id = str(item.get("approval_id") or "")
    record = client.find("审批记录", "审批ID", approval_id)
    if not record:
        raise DeepMathApprovalCallbackError("DeepMath approval audit row is unavailable")
    fields: dict[str, Any] = {
        "提案状态": item.get("proposal_state"),
        "审批决定": item.get("decision_state"),
        "执行状态": item.get("execution_state"),
        "执行尝试": int(item.get("attempt_no") or 0),
    }
    if item.get("decided_at"):
        fields["审批时间"] = _timestamp_ms(item.get("decided_at"))
        fields["审批人"] = [{"id": actor_id}]
    for source, target in (
        ("upstream_request_id", "上游请求ID"),
        ("external_object_id", "外部对象ID"),
        ("external_url", "外部对象链接"),
    ):
        if item.get(source):
            fields[target] = item[source]
    if item.get("last_readback_at"):
        fields["最后回读时间"] = _timestamp_ms(item.get("last_readback_at"))
    if item.get("receipt") is not None:
        fields["执行结果"] = json.dumps(item["receipt"], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    client.update("审批记录", str(record.get("record_id") or ""), fields)
    readback = client.get("审批记录", str(record.get("record_id") or ""))
    current = readback.get("fields") or {}
    return all(
        current.get(name) == fields.get(name)
        for name in ("提案状态", "审批决定", "执行状态")
    )


def process_verified_callback(facts: Mapping[str, Any], config: DeepMathApprovalCallbackConfig) -> dict[str, Any]:
    if not isinstance(facts, Mapping):
        raise DeepMathApprovalCallbackError("callback facts must be an object")
    if facts.get("transport_verified") is not True:
        return {"status": "rejected", "code": "transport_unverified", "replayed": False}
    if str(facts.get("tenant_key") or "") != DEEP_MATH_TENANT_KEY:
        return {"status": "rejected", "code": "tenant_rejected", "replayed": False}
    store = DeepMathApprovalStore(config.state_path)
    service = DeepMathApprovalService(
        store,
        approver_user_id=config.approver_user_id,
        authorized_actor_ids=config.authorized_actor_ids,
        executor_registry=_tasks_executor_registry(config),
        token_signing_secret=config.token_signing_secret,
        clock=config.clock,
        people_resolver=lambda selection: _resolve_people_selection(config, selection),
    )
    raw_result = service.handle_callback(facts)
    item = store.get_item(
        tenant_key=str(facts.get("tenant_key") or ""),
        proposal_id=str(facts.get("proposal_id") or ""),
        proposal_version=int(facts.get("proposal_version") or 0),
        approval_id=str(facts.get("approval_id") or ""),
    )
    if item is not None and config.resource_config_path:
        raw_result["audit_projection_readback"] = _project_audit_item(config, item, str(facts.get("actor_id") or ""))
    return safe_callback_result(raw_result)


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="DeepMath verified approval callback")
    parser.add_argument("--config-path", "--config", dest="config_path", default=os.environ.get(CONFIG_ENV, ""))
    args = parser.parse_args(argv)
    try:
        facts = json.load(sys.stdin)
        config = load_deepmath_approval_config(args.config_path)
        result = process_verified_callback(facts, config)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        return 0
    except (DeepMathApprovalCallbackError, DeepMathApprovalStoreError, ValueError, OSError, TypeError):
        print(json.dumps({"status": "error", "code": "callback_unavailable", "replayed": False}, ensure_ascii=False, separators=(",", ":")))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
