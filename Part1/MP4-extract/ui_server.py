#!/usr/bin/env python3
from __future__ import annotations

import argparse
import functools
import json
import re
import subprocess
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

try:
    from browser_cookies import build_cookie_header
except Exception as exc:  # pragma: no cover - optional dependency
    build_cookie_header = None
    _COOKIE_IMPORT_ERROR = str(exc)
else:
    _COOKIE_IMPORT_ERROR = ""


BASE_DIR = Path(__file__).resolve().parent
SCRIPT_PATH = BASE_DIR / "extract_qishuimusic_mp4.py"
DOWNLOADS_DIR = BASE_DIR / "downloads"

URL_RE = re.compile(r"https?://[^\s<>'\"]+")
TRAILING_PUNCT = "\"'<>)]}>,.;"


def _parse_saved_path(stdout: str) -> str | None:
    for line in stdout.splitlines():
        if line.startswith("Saved:"):
            return line.split("Saved:", 1)[1].strip()
        if line.startswith("Saved playlist:"):
            return line.split("Saved playlist:", 1)[1].strip()
    return None


def _to_download_url(path: str) -> str | None:
    try:
        rel = Path(path).resolve().relative_to(BASE_DIR)
    except Exception:
        return None
    return f"/{rel.as_posix()}"


def _extract_first_url(text: str) -> str | None:
    match = URL_RE.search(text)
    if not match:
        return None
    url = match.group(0)
    while url and url[-1] in TRAILING_PUNCT:
        url = url[:-1]
    return url


class RequestHandler(SimpleHTTPRequestHandler):
    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._set_cors_headers()
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/health":
            self._send_json(200, {"ok": True})
            return
        if parsed.path == "/":
            self.path = "/ui/index.html"
        super().do_GET()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/api/download":
            self.send_error(404, "Not Found")
            return

        content_length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(content_length) if content_length else b"{}"
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except json.JSONDecodeError:
            self._send_json(400, {"ok": False, "error": "invalid_json"})
            return

        share_text = str(payload.get("share_text", "")).strip()
        curl_text = str(payload.get("curl_text", "")).strip()
        if not share_text and not curl_text:
            self._send_json(
                400, {"ok": False, "error": "missing_share_text_or_curl"}
            )
            return

        auto_capture = bool(payload.get("auto_capture", False))
        timeout = payload.get("timeout", None)
        cookie = str(payload.get("cookie", "")).strip() or None
        cookie_source = str(payload.get("cookie_source", "")).strip().lower()
        cookie_profile = str(payload.get("cookie_profile", "")).strip() or "Default"
        filename = str(payload.get("filename", "")).strip() or None
        ffmpeg = bool(payload.get("ffmpeg", False))

        DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)

        if not cookie and not curl_text and cookie_source in {"chrome", "edge"}:
            if not build_cookie_header:
                self._send_json(
                    500,
                    {
                        "ok": False,
                        "error": "cookie_reader_unavailable",
                        "message": _COOKIE_IMPORT_ERROR
                        or "browser cookie reader is unavailable",
                    },
                )
                return
            share_url = _extract_first_url(share_text)
            if not share_url:
                self._send_json(400, {"ok": False, "error": "missing_share_url"})
                return
            try:
                cookie = build_cookie_header(share_url, cookie_source, profile=cookie_profile)
            except Exception as exc:
                self._send_json(
                    500,
                    {
                        "ok": False,
                        "error": "cookie_read_failed",
                        "message": str(exc),
                    },
                )
                return

        cmd = [
            sys.executable,
            str(SCRIPT_PATH),
            "-o",
            str(DOWNLOADS_DIR),
        ]
        if isinstance(timeout, (int, float)) and timeout:
            cmd.extend(["--timeout", str(int(timeout))])
        stdin_text = ""
        if curl_text:
            cmd.extend(["--curl", curl_text])
            stdin_text = curl_text
        else:
            if auto_capture:
                cmd.append("--auto")
            cmd.append("-")
            stdin_text = share_text
        if cookie:
            cmd.extend(["--cookie", cookie])
        if filename:
            cmd.extend(["--filename", filename])
        if ffmpeg:
            cmd.append("--ffmpeg")

        try:
            proc = subprocess.run(
                cmd,
                input=stdin_text,
                text=True,
                capture_output=True,
                check=False,
            )
        except Exception as exc:
            self._send_json(500, {"ok": False, "error": str(exc)})
            return

        stdout = proc.stdout.strip()
        stderr = proc.stderr.strip()
        saved_path = _parse_saved_path(stdout)

        if proc.returncode != 0 or not saved_path:
            self._send_json(
                500,
                {
                    "ok": False,
                    "error": "download_failed",
                    "stdout": stdout,
                    "stderr": stderr,
                },
            )
            return

        download_url = _to_download_url(saved_path)
        response = {
            "ok": True,
            "output_path": saved_path,
            "download_url": download_url,
            "stdout": stdout,
        }
        if stderr:
            response["stderr"] = stderr
        self._send_json(200, response)

    def _set_cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _send_json(self, status_code: int, payload: dict) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self._set_cors_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def run_server(host: str, port: int) -> None:
    handler = functools.partial(RequestHandler, directory=str(BASE_DIR))
    server = ThreadingHTTPServer((host, port), handler)
    print(f"UI server running at http://{host}:{port}", flush=True)
    server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description="Qishu Music UI server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8888)
    args = parser.parse_args()
    run_server(args.host, args.port)


if __name__ == "__main__":
    main()
