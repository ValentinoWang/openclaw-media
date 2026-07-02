from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path


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


def _parse_openclaw_json(output: str) -> dict:
    text = output.strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        pass
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", text):
        try:
            parsed, _ = decoder.raw_decode(text[match.start() :])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return {}


def _extract_openclaw_reply(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        texts = [_extract_openclaw_reply(item) for item in value]
        return "\n".join(text for text in texts if text).strip()
    if isinstance(value, dict):
        for key in (
            "reply",
            "message",
            "text",
            "output",
            "final",
            "final_answer",
            "finalAssistantVisibleText",
            "finalAssistantRawText",
        ):
            text = _extract_openclaw_reply(value.get(key))
            if text:
                return text
        result = value.get("result")
        if isinstance(result, dict):
            text = _extract_openclaw_reply(result)
            if text:
                return text
        meta = value.get("meta")
        if isinstance(meta, dict):
            text = _extract_openclaw_reply(meta)
            if text:
                return text
    return ""


def _delegate_to_codex_maintenance(message: str) -> dict:
    cmd = [
        "openclaw",
        "agent",
        "--agent",
        "openclaw-maintenance",
        "--message",
        message,
        "--thinking",
        "high",
        "--json",
    ]
    timeout = int(os.environ.get("OPENCLAW_CODEX_MAINTENANCE_TIMEOUT", "1800"))
    progress_file = os.environ.get("OPENCLAW_CODEX_PROGRESS_FILE", "").strip()
    try:
        if progress_file:
            progress_path = Path(progress_file)
            progress_path.parent.mkdir(parents=True, exist_ok=True)
            with progress_path.open("w+", encoding="utf-8") as output:
                proc = subprocess.run(cmd, text=True, stdout=output, stderr=subprocess.STDOUT, timeout=timeout)
                output.seek(0)
                stdout = output.read()
            stderr = ""
        else:
            proc = subprocess.run(cmd, text=True, capture_output=True, timeout=timeout)
            stdout = proc.stdout
            stderr = proc.stderr
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "status": "codex_maintenance_timeout",
            "reply": f"模型编号：gpt5.5-high\n\n已识别 `【codex】` 维护请求，但 openclaw-maintenance 超时：{exc}",
            "task_id": "",
            "local_path": "",
            "feishu_doc": "",
            "extra": {},
        }
    except OSError as exc:
        return {
            "ok": False,
            "status": "codex_maintenance_failed",
            "reply": f"模型编号：gpt5.5-high\n\n已识别 `【codex】` 维护请求，但无法调用 OpenClaw CLI：{exc}",
            "task_id": "",
            "local_path": "",
            "feishu_doc": "",
            "extra": {},
        }

    parsed = _parse_openclaw_json(stdout)
    reply = _extract_openclaw_reply(parsed)
    if proc.returncode != 0:
        error_text = stderr.strip() or reply or f"openclaw agent exited with {proc.returncode}"
        return {
            "ok": False,
            "status": "codex_maintenance_failed",
            "reply": f"模型编号：gpt5.5-high\n\n{error_text}",
            "task_id": "",
            "local_path": "",
            "feishu_doc": "",
            "extra": {"delegate_result": parsed},
        }
    if not reply:
        reply = "openclaw-maintenance 已处理完成，但未返回可见文本。"
    if not reply.startswith(("模型编号：", "模型：", "Model:")):
        reply = f"模型编号：gpt5.5-high\n\n{reply}"
    return {
        "ok": True,
        "status": "delegated_to_codex_maintenance",
        "reply": reply,
        "task_id": str(parsed.get("task_id") or parsed.get("taskId") or parsed.get("id") or ""),
        "local_path": "",
        "feishu_doc": "",
        "extra": {
            "maintenance_agent": "openclaw-maintenance",
            "thinking_level": "high",
            "delegate_result": parsed,
        },
    }


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
        if _contains_codex_trigger(text):
            _bridge_progress("codex_delegate_start", mode=mode, text_preview=text[:120])
            result = _delegate_to_codex_maintenance(text)
            _bridge_progress("codex_delegate_done", mode=mode, status=result.get("status", ""))
            print(json.dumps(result, ensure_ascii=False, default=str))
            return 0
        if not text.startswith("【"):
            print(
                json.dumps(
                    {
                        "ok": True,
                        "ignored": True,
                        "reason": "not_tag_protocol",
                        "text": text,
                    },
                    ensure_ascii=False,
                )
            )
            return 0
        if not data_root.exists():
            data_root.mkdir(parents=True, exist_ok=True)
        from openclaw_app.app import OpenClawApp

        app = OpenClawApp(settings_path)
        _bridge_progress("route_start", mode=mode, text_preview=text[:120])
        result = app.process_text(
            text,
            source=payload.get("source"),
            chat_type=payload.get("chat_type"),
            created_at=_parse_created_at(payload.get("created_at")),
            metadata=payload.get("metadata"),
        )
        _bridge_progress("route_done", mode=mode, status=getattr(result, "status", ""))
        print(json.dumps(result.__dict__, ensure_ascii=False, default=str))
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
            result = _delegate_to_codex_maintenance(parsed.text)
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
