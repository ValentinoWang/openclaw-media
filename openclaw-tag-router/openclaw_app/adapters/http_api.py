from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING, Any

from ..services.stage2_gateway import Stage2GatewayError
from ..services.stage2_runtime import Stage2RuntimeError

if TYPE_CHECKING:
    from ..app import OpenClawApp



class OpenClawHttpHandler(BaseHTTPRequestHandler):
    app: OpenClawApp | None = None

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/healthz":
            self._send_json(HTTPStatus.OK, {"ok": True})
            return
        if self.path == "/readyz":
            payload = {
                "ok": True,
                "content_flow_base_url": self.app.settings.get("content_flow", {}).get("base_url", "") if self.app else "",
                "feishu_mode": self.app.settings.get("feishu", {}).get("mode", "") if self.app else "",
                "mac_agent_mode": self.app.settings.get("mac_agent", {}).get("mode", "") if self.app else "",
            }
            self._send_json(HTTPStatus.OK, payload)
            return
        self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not_found"})

    def do_POST(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
            if self.path == "/ingest":
                self._handle_ingest(payload)
                return
            if self.path == "/qqbot/event":
                self._handle_qq_event(payload)
                return
            if self.path == "/stage2/personal":
                self._handle_stage2("personal", payload)
                return
            if self.path == "/stage2/organization":
                self._handle_stage2("organization", payload)
                return
            self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not_found"})
        except Stage2GatewayError as exc:
            self._send_json(exc.status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
        except Stage2RuntimeError as exc:
            status = HTTPStatus.CONFLICT if exc.code == "idempotency_conflict" else HTTPStatus.UNPROCESSABLE_ENTITY
            self._send_json(status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
        except ValueError as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)})
        except RuntimeError as exc:
            if str(exc) == "stage2_unavailable":
                self._send_json(HTTPStatus.SERVICE_UNAVAILABLE, {"ok": False, "error": {"code": "stage2_unavailable"}})
                return
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "error": str(exc)})
        except Exception as exc:
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "error": str(exc)})

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _handle_ingest(self, payload: dict[str, Any]) -> None:
        text = (payload.get("text") or "").strip()
        if not text:
            self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "missing_text"})
            return
        result = self.app.process_text(
            text,
            source=payload.get("source"),
            chat_type=payload.get("chat_type"),
            metadata=payload.get("metadata"),
        ) if self.app else None
        if result is None:
            raise RuntimeError("app not configured")
        self._send_json(HTTPStatus.OK, result.__dict__)

    def _handle_qq_event(self, payload: dict[str, Any]) -> None:
        from .qq_bot_adapter import QQBotAdapter

        if self.app is None:
            raise RuntimeError("app not configured")
        adapter = QQBotAdapter(self.app)
        parsed = adapter.parse_event(payload)
        if not parsed.text.startswith("【"):
            self._send_json(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "ignored": True,
                    "reason": "not_tag_protocol",
                    "text": parsed.text,
                    "chat_type": parsed.chat_type,
                },
            )
            return
        response = adapter.handle_event(parsed)
        response["ok"] = True
        response["ignored"] = False
        response["chat_type"] = parsed.chat_type
        response["user_id"] = parsed.user_id
        self._send_json(HTTPStatus.OK, response)

    def _handle_stage2(self, mode: str, payload: dict[str, Any]) -> None:
        if self.app is None:
            raise RuntimeError("app not configured")
        receipt = self.app.process_stage2(mode, payload)
        self._send_json(HTTPStatus.OK, {"ok": True, "receipt": receipt})


def make_server(host: str, port: int, app: OpenClawApp) -> ThreadingHTTPServer:
    handler = type("BoundOpenClawHttpHandler", (OpenClawHttpHandler,), {"app": app})
    return ThreadingHTTPServer((host, port), handler)
