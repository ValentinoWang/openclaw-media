from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from openclaw_app.services import codex_maintenance_tasks


def _bridge_progress(stage: str, **fields: object) -> None:
    parts = [f"stage={stage}"]
    for key, value in fields.items():
        if value in (None, "", [], {}):
            continue
        text = str(value).replace("\n", "\\n")
        parts.append(f"{key}={text[:240]}")
    print("[tag-router-bridge] " + " ".join(parts), file=sys.stderr, flush=True)


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        value = value.strip().strip('"').strip("'")
        os.environ[key] = value


def _load_default_env() -> None:
    env_file = os.environ.get("OPENCLAW_TAG_ROUTER_ENV_FILE", "").strip()
    candidates = []
    if env_file:
        candidates.append(Path(env_file))
    candidates.append(Path("/home/ubuntu/.openclaw/openclaw.env"))
    for path in candidates:
        _load_env_file(path)


def _load_payload() -> dict:
    raw = sys.stdin.read().strip()
    return json.loads(raw) if raw else {}


def _parse_created_at(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _normalize_tag_protocol_text(value: object) -> str:
    text = str(value or "").strip()
    if text.startswith("【"):
        return text
    # Native OpenClaw agent prompts prefix messages like:
    # [Fri 2026-05-29 04:09 GMT+8] 【说明】
    match = re.match(r"^\[[^\]\n]{8,80}\]\s*(【.+)\Z", text, flags=re.S)
    return match.group(1).strip() if match else text


def _contains_codex_trigger(value: object) -> bool:
    return bool(re.search(r"【\s*codex\s*】", str(value or ""), flags=re.I))


def _without_model_label(reply: str) -> str:
    text = reply.strip()
    if not text.startswith(("模型编号：", "模型：", "Model:")):
        return text
    _, separator, remainder = text.partition("\n")
    return remainder.lstrip() if separator else ""


def _with_model_label(reply: str, *, runtime_model: str = "", planned_model: str = "") -> str:
    model = runtime_model.strip() or planned_model.strip()
    if not model:
        raise ValueError("Codex task response requires a planned or runtime model")
    label = "模型" if runtime_model.strip() else "计划模型"
    text = _without_model_label(reply)
    return f"{label}：{model}" if not text else f"{label}：{model}\n\n{text}"


def _source_message_identity(payload: dict) -> tuple[str, str]:
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    message_id = str(metadata.get("source_message_id") or metadata.get("message_id") or "").strip()
    account_id = str(metadata.get("account_id") or metadata.get("account") or "unknown").strip() or "unknown"
    return account_id, message_id


def _message_result_identity(payload: dict) -> tuple[str, str]:
    account_id, source_message_id = _source_message_identity(payload)
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    execution_id = str(metadata.get("message_result_id") or "").strip()
    return account_id, execution_id or source_message_id


def _message_result_root() -> Path:
    configured = os.environ.get("OPENCLAW_TAG_ROUTER_MESSAGE_RESULT_ROOT", "").strip()
    return Path(configured) if configured else Path("/home/ubuntu/.openclaw/state/tag_router_message_results")


def _codex_task_response(task_id: str, state: dict | None = None) -> dict:
    state = state or codex_maintenance_tasks.status_snapshot(task_id)
    if not state:
        return {
            "ok": True,
            "status": "codex_maintenance_task_not_found",
            "reply": f"未找到 v2 维护任务 `{task_id}`；请核对 task_id 后重试。",
            "task_id": task_id,
            "local_path": "",
            "feishu_doc": "",
            "extra": {},
        }
    status = str(state.get("status") or "unknown")
    phase = str(state.get("phase") or status)
    tool_type = str(state.get("toolType") or "OpenClaw maintenance agent")
    safe_summary = str(state.get("safeSummary") or "维护任务状态已更新。")
    heartbeat = str(state.get("heartbeatAt") or state.get("updatedAt") or "未知")
    runtime_model = str(state.get("runtimeModel") or "")
    planned_model = str(state.get("plannedModel") or "")
    elapsed = codex_maintenance_tasks.elapsed_seconds(state)
    if status == "succeeded":
        reply = str(state.get("reply") or "维护任务已完成，但没有可见结果。")
        response_status = "codex_maintenance_completed"
    elif status == "failed":
        response_status = str(state.get("failureCode") or "codex_maintenance_failed")
        failure_detail = str(state.get("failureDetail") or "底层未提供错误详情。").strip()
        suggested_action = str(state.get("suggestedAction") or "检查运行条件后重新提交任务。").strip()
        reply = (
            f"维护任务失败（{response_status}）。{safe_summary}\n"
            f"详情：{failure_detail}\n"
            f"建议：{suggested_action}"
        )
    else:
        response_status = "codex_maintenance_running" if status == "running" else "codex_maintenance_queued"
        reply = (
            f"维护任务 `{task_id}` 正在后台执行。\n\n"
            f"- 阶段：{phase}\n"
            f"- 工具类型：{tool_type}\n"
            f"- 已运行：{elapsed} 秒\n"
            f"- 最近心跳：{heartbeat}\n"
            f"- 安全摘要：{safe_summary}\n\n"
            f"继续查询：`【codex】状态 {task_id}`"
        )
    return {
        "ok": True,
        "status": response_status,
        "reply": _with_model_label(reply, runtime_model=runtime_model, planned_model=planned_model),
        "task_id": task_id,
        "local_path": "",
        "feishu_doc": "",
        "extra": {
            "phase": phase,
            "tool_type": tool_type,
            "elapsed_seconds": elapsed,
            "heartbeat_at": heartbeat,
            "outcome": str(state.get("outcome") or "pending"),
            "runtime_model": runtime_model,
            "planned_model": planned_model,
        },
    }


def _process_ingest(payload: dict, *, text: str, data_root: Path, settings_path: Path) -> tuple[dict, bool]:
    if _contains_codex_trigger(text):
        _bridge_progress("codex_delegate_start", mode="ingest", text_preview=text[:120])
        status_task_id = codex_maintenance_tasks.parse_status_task_id(text)
        response = _codex_task_response(status_task_id) if status_task_id else _delegate_to_codex_maintenance(text, payload=payload)
        _bridge_progress("codex_delegate_done", mode="ingest", status=response.get("status", ""))
        return response, response.get("ok") is True
    if not text.startswith("【"):
        return {
            "ok": True,
            "ignored": True,
            "reason": "not_tag_protocol",
            "text": text,
        }, True
    if not data_root.exists():
        data_root.mkdir(parents=True, exist_ok=True)
    from openclaw_app.app import OpenClawApp

    app = OpenClawApp(settings_path)
    _bridge_progress("route_start", mode="ingest", text_preview=text[:120])
    result = app.process_text(
        text,
        source=payload.get("source"),
        chat_type=payload.get("chat_type"),
        created_at=_parse_created_at(payload.get("created_at")),
        metadata=payload.get("metadata"),
    )
    _bridge_progress("route_done", mode="ingest", status=getattr(result, "status", ""))
    response = dict(result.__dict__)
    cacheable = getattr(result, "ok", None) is True
    # The bridge transport completed even when a business guard rejected the
    # request. Preserve the business status while avoiding channel retries.
    response["ok"] = True
    return response, cacheable


def _delegate_to_codex_maintenance(message: str, *, payload: dict | None = None) -> dict:
    task_payload = payload or {}
    account_id, message_id = _source_message_identity(task_payload)
    state = codex_maintenance_tasks.enqueue_task(
        message,
        account_id=account_id,
        message_id=message_id,
        delivery=codex_maintenance_tasks.delivery_from_payload(task_payload),
        notification_required=str(task_payload.get("source") or "") == "feishu",
    )
    task_id = str(state.get("taskId") or "")
    return _codex_task_response(task_id, state)


def _main() -> int:
    if len(sys.argv) < 4:
        raise SystemExit("usage: bridge.py <mode> <data_root> <settings_path>")

    mode = sys.argv[1]
    data_root = Path(sys.argv[2])
    settings_path = Path(sys.argv[3])
    plugin_root = Path(__file__).resolve().parent
    sys.path.insert(0, str(plugin_root))
    _load_default_env()

    _bridge_progress("waiting_for_stdin", mode=mode)
    payload = _load_payload()
    _bridge_progress("payload_loaded", mode=mode, has_text=bool(payload.get("text")))

    if mode == "health":
        if not data_root.exists():
            data_root.mkdir(parents=True, exist_ok=True)
        from openclaw_app.app import OpenClawApp

        app = OpenClawApp(settings_path)
        print(
            json.dumps(
                {
                    "ok": True,
                    "status": "tag_router_bridge_ready",
                    "settings_path": str(settings_path),
                    "data_root": str(data_root),
                    "feishu_mode": app.settings.get("feishu", {}).get("mode", ""),
                    "mac_agent_mode": app.settings.get("mac_agent", {}).get("mode", ""),
                },
                ensure_ascii=False,
                default=str,
            )
        )
        return 0

    if mode == "ingest":
        text = _normalize_tag_protocol_text(payload.get("text"))
        if not text:
            print(json.dumps({"ok": False, "error": "missing_text"}, ensure_ascii=False))
            return 0
        account_id, message_result_id = _message_result_identity(payload)
        _, source_message_id = _source_message_identity(payload)
        if message_result_id:
            from openclaw_app.services.message_result_store import MessageResultStore, MessageResultStoreError

            try:
                execution = MessageResultStore(_message_result_root()).execute_once(
                    account_id=account_id,
                    message_id=message_result_id,
                    text=text,
                    operation=lambda: _process_ingest(payload, text=text, data_root=data_root, settings_path=settings_path),
                )
                response = execution.response
                _bridge_progress(
                    "message_result_replayed" if execution.replayed else "message_result_saved",
                    mode=mode,
                    message_result_id=message_result_id,
                    source_message_id=source_message_id,
                    status=response.get("status", ""),
                )
            except MessageResultStoreError as exc:
                response = {
                    "ok": True,
                    "status": exc.code,
                    "reply": f"标签消息未执行（{exc.code}）：{exc.message}",
                    "task_id": "",
                    "local_path": "",
                    "feishu_doc": "",
                    "extra": {},
                }
        else:
            response, _ = _process_ingest(payload, text=text, data_root=data_root, settings_path=settings_path)
        print(json.dumps(response, ensure_ascii=False, default=str))
        return 0

    if mode == "qqbot":
        if not data_root.exists():
            data_root.mkdir(parents=True, exist_ok=True)
        from openclaw_app.app import OpenClawApp
        from openclaw_app.adapters.qq_bot_adapter import QQBotAdapter

        app = OpenClawApp(settings_path)
        adapter = QQBotAdapter(app)
        ignored_reason = adapter.should_ignore_event(payload)
        if ignored_reason is not None:
            print(
                json.dumps(
                    {
                        "ok": True,
                        "ignored": True,
                        "reason": ignored_reason,
                    },
                    ensure_ascii=False,
                )
            )
            return 0
        parsed = adapter.parse_event(payload)
        if _contains_codex_trigger(parsed.text):
            _bridge_progress("codex_delegate_start", mode=mode, text_preview=parsed.text[:120])
            status_task_id = codex_maintenance_tasks.parse_status_task_id(parsed.text)
            qq_payload = {
                "source": "qqbot",
                "metadata": {
                    "account_id": "qqbot",
                    "message_id": str(getattr(parsed, "message_id", "") or ""),
                },
            }
            result = _codex_task_response(status_task_id) if status_task_id else _delegate_to_codex_maintenance(parsed.text, payload=qq_payload)
            _bridge_progress("codex_delegate_done", mode=mode, status=result.get("status", ""))
            print(json.dumps(result, ensure_ascii=False, default=str))
            return 0
        if not parsed.text.startswith("【"):
            print(
                json.dumps(
                    {
                        "ok": True,
                        "ignored": True,
                        "reason": "not_tag_protocol",
                        "text": parsed.text,
                        "chat_type": parsed.chat_type,
                        "user_id": parsed.user_id,
                    },
                    ensure_ascii=False,
                )
            )
            return 0
        _bridge_progress("route_start", mode=mode, text_preview=parsed.text[:120])
        result = adapter.handle_event(parsed)
        result["ok"] = True
        result["ignored"] = False
        result["chat_type"] = parsed.chat_type
        result["user_id"] = parsed.user_id
        _bridge_progress("route_done", mode=mode, status=result.get("status", ""))
        print(json.dumps(result, ensure_ascii=False))
        return 0

    print(json.dumps({"ok": False, "error": f"unsupported_mode:{mode}"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
