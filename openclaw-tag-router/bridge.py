from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path


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


def _main() -> int:
    if len(sys.argv) < 4:
        raise SystemExit("usage: bridge.py <mode> <data_root> <settings_path>")

    mode = sys.argv[1]
    data_root = Path(sys.argv[2])
    settings_path = Path(sys.argv[3])
    plugin_root = Path(__file__).resolve().parent
    sys.path.insert(0, str(plugin_root))
    _load_default_env()

    from openclaw_app.app import OpenClawApp
    from openclaw_app.adapters.qq_bot_adapter import QQBotAdapter

    payload = _load_payload()
    if not data_root.exists():
        data_root.mkdir(parents=True, exist_ok=True)
    app = OpenClawApp(settings_path)

    if mode == "ingest":
        text = str(payload.get("text") or "").strip()
        if not text:
            print(json.dumps({"ok": False, "error": "missing_text"}, ensure_ascii=False))
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
        result = app.process_text(
            text,
            source=payload.get("source"),
            chat_type=payload.get("chat_type"),
            created_at=_parse_created_at(payload.get("created_at")),
            metadata=payload.get("metadata"),
        )
        print(json.dumps(result.__dict__, ensure_ascii=False))
        return 0

    if mode == "qqbot":
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
        result = adapter.handle_event(parsed)
        result["ok"] = True
        result["ignored"] = False
        result["chat_type"] = parsed.chat_type
        result["user_id"] = parsed.user_id
        print(json.dumps(result, ensure_ascii=False))
        return 0

    print(json.dumps({"ok": False, "error": f"unsupported_mode:{mode}"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
