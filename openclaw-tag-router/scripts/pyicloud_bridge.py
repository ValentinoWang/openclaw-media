#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import select
import signal
import subprocess
import sys
import time
from pathlib import Path, PurePosixPath
from typing import Any


RUNTIME_DIR = Path(
    os.environ.get(
        "OPENCLAW_ICLOUD_AUTH_RUNTIME_DIR",
        "/home/ubuntu/.openclaw/workspace/openclaw-tag-router/runtime/icloud_auth",
    )
)
SESSION_DIR = Path(
    os.environ.get(
        "OPENCLAW_PYICLOUD_SESSION_DIR",
        str(RUNTIME_DIR / "pyicloud_sessions"),
    )
)


def _json(data: dict[str, Any]) -> None:
    print(json.dumps(data, ensure_ascii=False))


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip().rstrip(":") or "icloud")


def _state_path(remote: str) -> Path:
    return RUNTIME_DIR / f"{_safe_name(remote)}.pyicloud.json"


def _read_state(remote: str) -> dict[str, Any]:
    path = _state_path(remote)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _write_state(remote: str, data: dict[str, Any]) -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    existing = _read_state(remote)
    existing.update(data)
    existing["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    path = _state_path(remote)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(existing, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    try:
        path.chmod(0o600)
    except OSError:
        pass


def _pid_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _tail(path: str | Path, limit: int = 3000) -> str:
    p = Path(path)
    if not p.exists():
        return ""
    data = p.read_bytes()[-limit:]
    return data.decode("utf-8", errors="replace")


def _redact(text: str) -> str:
    text = re.sub(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "<apple_id>", text)
    text = re.sub(r"(?i)(password\s*[:=]?\s*)\S+", r"\1<redacted>", text)
    return text


def _reply_for_status(status: str, method: str = "") -> str:
    if status == "awaiting_2fa":
        if method == "sms":
            return "iCloud 中国区认证正在等待短信验证码。请发送：`【灵感-vlog】验证码 123456`。"
        if method == "trusted_device":
            return "iCloud 中国区认证已向受信任 Apple 设备请求验证码。请发送：`【灵感-vlog】验证码 123456`；如需短信可发送：`【灵感-vlog】验证码 sms`。"
        return "iCloud 中国区认证正在等待验证码。请发送：`【灵感-vlog】验证码 123456`。"
    if status == "ready":
        return "iCloud 中国区会话已可用，可以上传 vlog 素材。"
    if status == "starting":
        return "iCloud 中国区认证正在启动，等待 Apple 返回下一步。"
    if status == "invalid_code":
        return "验证码未通过，请重新发送新的 `【灵感-vlog】验证码 123456`。"
    if status == "no_session":
        return "还没有 pyicloud 中国区会话。请先发送 iCloud 账号和密码初始化。"
    if status == "auth_required":
        return "iCloud 中国区会话已过期，需要重新发送 Apple ID 密码并完成 2FA。"
    return "iCloud 中国区认证未完成。"


def _import_pyi_cloud():
    from pyicloud import PyiCloudService
    from pyicloud.exceptions import PyiCloudAPIResponseException

    return PyiCloudService, PyiCloudAPIResponseException


def _probe_session(apple_id: str, session_dir: str, china_mainland: bool) -> dict[str, Any]:
    try:
        PyiCloudService, _ = _import_pyi_cloud()
        api = PyiCloudService(
            apple_id=apple_id,
            cookie_directory=session_dir,
            china_mainland=china_mainland,
            with_family=False,
            authenticate=False,
        )
        status = api.get_auth_status()
        return {"ok": bool(status.get("authenticated")), "auth_status": status}
    except Exception as exc:
        return {"ok": False, "error": _redact(str(exc))}


def status(remote: str) -> None:
    state = _read_state(remote)
    if not state:
        _json({"ok": True, "status": "no_session", "remote": remote, "reply": _reply_for_status("no_session")})
        return

    pid = int(state.get("pid") or 0)
    running = _pid_running(pid)
    current_status = str(state.get("status") or "unknown")
    apple_id = str(state.get("apple_id") or "")
    if not running and current_status in {"starting", "awaiting_2fa"}:
        current_status = "stopped"

    probe: dict[str, Any] = {}
    if apple_id and current_status not in {"awaiting_2fa", "starting"}:
        probe = _probe_session(
            apple_id,
            str(state.get("session_dir") or SESSION_DIR),
            bool(state.get("china_mainland", True)),
        )
        if probe.get("ok"):
            current_status = "ready"

    method = str(state.get("method") or "")
    _json(
        {
            "ok": current_status == "ready" or current_status in {"awaiting_2fa", "starting", "invalid_code"},
            "status": current_status,
            "remote": remote,
            "backend": "pyicloud",
            "running": running,
            "pid": pid,
            "apple_id": apple_id,
            "china_mainland": bool(state.get("china_mainland", True)),
            "method": method,
            "session_dir": str(state.get("session_dir") or SESSION_DIR),
            "transcript": state.get("transcript", ""),
            "tail": _redact(_tail(str(state.get("transcript") or ""))),
            "probe": probe,
            "reply": str(state.get("reply") or _reply_for_status(current_status, method)),
        }
    )


def start(remote: str, apple_id: str, china_mainland: bool) -> None:
    password = sys.stdin.readline().rstrip("\n")
    if not apple_id or not password:
        _json({"ok": False, "status": "missing_credentials", "reply": "缺少 Apple ID 或密码，无法启动 iCloud 中国区认证。"})
        return

    current = _read_state(remote)
    if _pid_running(int(current.get("pid") or 0)):
        status(remote)
        return

    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    safe = _safe_name(remote)
    fifo = RUNTIME_DIR / f"{safe}.pyicloud.fifo"
    transcript = RUNTIME_DIR / f"{safe}.pyicloud.transcript"
    for path in (fifo,):
        try:
            if path.exists():
                path.unlink()
        except OSError:
            pass
    os.mkfifo(fifo, 0o600)
    transcript.write_text("", encoding="utf-8")
    try:
        transcript.chmod(0o600)
    except OSError:
        pass

    cmd = [
        sys.executable,
        str(Path(__file__).resolve()),
        "daemon",
        "--remote",
        remote,
        "--apple-id",
        apple_id,
        "--fifo",
        str(fifo),
        "--transcript",
        str(transcript),
        "--session-dir",
        str(SESSION_DIR),
    ]
    if china_mainland:
        cmd.append("--china-mainland")

    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
        start_new_session=True,
    )
    assert proc.stdin is not None
    proc.stdin.write(password + "\n")
    proc.stdin.close()

    _write_state(
        remote,
        {
            "remote": remote,
            "backend": "pyicloud",
            "pid": proc.pid,
            "apple_id": apple_id,
            "china_mainland": china_mainland,
            "fifo": str(fifo),
            "transcript": str(transcript),
            "session_dir": str(SESSION_DIR),
            "status": "starting",
            "reply": _reply_for_status("starting"),
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        },
    )
    time.sleep(2.5)
    status(remote)


def send(remote: str, text: str) -> None:
    state = _read_state(remote)
    if not state:
        _json({"ok": False, "status": "no_session", "reply": _reply_for_status("no_session")})
        return
    if not _pid_running(int(state.get("pid") or 0)):
        status(remote)
        return
    fifo = str(state.get("fifo") or "")
    try:
        fd = os.open(fifo, os.O_WRONLY | os.O_NONBLOCK)
        try:
            os.write(fd, (text.strip() + "\n").encode("utf-8"))
        finally:
            os.close(fd)
    except Exception as exc:
        _json({"ok": False, "status": "send_failed", "error": _redact(str(exc)), "reply": f"验证码发送失败：{exc}"})
        return
    time.sleep(1.5)
    status(remote)


def cancel(remote: str) -> None:
    state = _read_state(remote)
    pid = int(state.get("pid") or 0) if state else 0
    if pid:
        try:
            os.killpg(pid, signal.SIGTERM)
        except Exception:
            try:
                os.kill(pid, signal.SIGTERM)
            except Exception:
                pass
    try:
        _state_path(remote).unlink()
    except OSError:
        pass
    _json({"ok": True, "status": "cancelled", "reply": "已取消 iCloud 中国区认证会话。"})


def _write_transcript(transcript: Path, line: str) -> None:
    with transcript.open("a", encoding="utf-8") as fh:
        fh.write(_redact(line.rstrip()) + "\n")


def daemon(remote: str, apple_id: str, fifo: str, transcript: str, session_dir: str, china_mainland: bool) -> None:
    password = sys.stdin.readline().rstrip("\n")
    transcript_path = Path(transcript)
    _write_transcript(transcript_path, "[pyicloud-bridge] started China Mainland iCloud auth")
    fifo_fd = os.open(fifo, os.O_RDWR | os.O_NONBLOCK)
    api = None
    try:
        PyiCloudService, _ = _import_pyi_cloud()
        api = PyiCloudService(
            apple_id=apple_id,
            password=password,
            cookie_directory=session_dir,
            china_mainland=china_mainland,
            accept_terms=True,
            with_family=False,
        )
        password = ""

        if getattr(api, "requires_2fa", False):
            requested = False
            try:
                requested = bool(api.request_2fa_code())
            except Exception as exc:
                _write_transcript(transcript_path, f"[pyicloud-bridge] request_2fa_code failed: {_redact(str(exc))}")
            method = getattr(api, "two_factor_delivery_method", "unknown") or "manual"
            if requested:
                _write_transcript(transcript_path, f"[pyicloud-bridge] awaiting 2FA via {method}")
            else:
                # Some China Mainland Apple ID sessions report requires_2fa but don't expose
                # a delivery channel via pyicloud. The user may still receive/generate a
                # trusted-device code, so keep the session alive and allow manual code entry
                # instead of aborting as unsupported_2fa.
                method = "manual"
                _write_transcript(transcript_path, "[pyicloud-bridge] awaiting manual 2FA code")
            _write_state(
                remote,
                {
                    "status": "awaiting_2fa",
                    "method": method,
                    "reply": _reply_for_status("awaiting_2fa", method),
                },
            )
            invalid_attempts = 0
            while invalid_attempts < 3:
                ready, _, _ = select.select([fifo_fd], [], [], 300)
                if fifo_fd not in ready:
                    _write_state(remote, {"status": "awaiting_2fa", "reply": _reply_for_status("awaiting_2fa", method)})
                    continue
                data = os.read(fifo_fd, 4096).decode("utf-8", errors="replace").strip()
                if not data:
                    continue
                if data.lower() == "sms":
                    try:
                        request_sms = getattr(api, "_request_sms_2fa_code")
                        request_sms("SMS requested from media bot")
                        method = "sms"
                        _write_transcript(transcript_path, "[pyicloud-bridge] requested SMS code")
                        _write_state(remote, {"status": "awaiting_2fa", "method": method, "reply": _reply_for_status("awaiting_2fa", method)})
                    except Exception as exc:
                        _write_state(remote, {"status": "awaiting_2fa", "method": method, "reply": f"短信验证码请求失败：{_redact(str(exc))}"})
                    continue
                if not re.fullmatch(r"[0-9]{4,8}", data):
                    _write_state(remote, {"status": "awaiting_2fa", "method": method, "reply": "验证码格式不对，请发送 4-8 位数字。"})
                    continue
                _write_transcript(transcript_path, "[pyicloud-bridge] received 2FA code")
                if api.validate_2fa_code(data):
                    if not api.is_trusted_session:
                        api.trust_session()
                    _write_transcript(transcript_path, "[pyicloud-bridge] authentication completed")
                    _write_state(remote, {"status": "ready", "method": method, "reply": _reply_for_status("ready", method)})
                    return
                invalid_attempts += 1
                _write_transcript(transcript_path, "[pyicloud-bridge] invalid 2FA code")
                _write_state(remote, {"status": "invalid_code", "method": method, "reply": _reply_for_status("invalid_code", method)})
            return

        if getattr(api, "requires_2sa", False):
            _write_state(remote, {"status": "unsupported_2sa", "reply": "该账号触发旧版两步验证，媒体 bot 暂未实现设备选择流程。"})
            return

        _write_transcript(transcript_path, "[pyicloud-bridge] authentication completed without 2FA")
        _write_state(remote, {"status": "ready", "reply": _reply_for_status("ready")})
    except Exception as exc:
        password = ""
        _write_transcript(transcript_path, f"[pyicloud-bridge] failed: {_redact(str(exc))}")
        _write_state(remote, {"status": "failed", "error": _redact(str(exc)), "reply": f"iCloud 中国区认证失败：{_redact(str(exc))}"})
    finally:
        try:
            os.close(fifo_fd)
        except OSError:
            pass


def _resolve_folder(root, remote_folder: str):
    node = root
    normalized = PurePosixPath("/" + remote_folder.strip("/"))
    for part in normalized.parts:
        if part in {"", "/"}:
            continue
        children = node.get_children(force=True)
        child = next((item for item in children if item.name == part), None)
        if child is None:
            node.mkdir(part)
            children = node.get_children(force=True)
            child = next((item for item in children if item.name == part), None)
        if child is None:
            raise RuntimeError(f"iCloud folder create failed: {part}")
        node = child
    return node


def upload(remote: str, local_path: str, remote_folder: str, remote_filename: str) -> None:
    state = _read_state(remote)
    apple_id = str(state.get("apple_id") or "")
    session_dir = str(state.get("session_dir") or SESSION_DIR)
    china_mainland = bool(state.get("china_mainland", True))
    if not apple_id:
        _json({"ok": False, "status": "not_configured", "reply": "还没有 pyicloud Apple ID 会话。"})
        return
    path = Path(local_path)
    if not path.is_file():
        _json({"ok": False, "status": "local_missing", "error": str(path)})
        return
    try:
        PyiCloudService, _ = _import_pyi_cloud()
        api = PyiCloudService(
            apple_id=apple_id,
            cookie_directory=session_dir,
            china_mainland=china_mainland,
            with_family=False,
            authenticate=False,
        )
        auth_status = api.get_auth_status()
        if not auth_status.get("authenticated"):
            _json({"ok": False, "status": "auth_required", "auth_status": auth_status, "reply": _reply_for_status("auth_required")})
            return
        folder = _resolve_folder(api.drive.root, remote_folder)
        link_dir = RUNTIME_DIR / "pyicloud_upload_links" / str(os.getpid())
        link_dir.mkdir(parents=True, exist_ok=True)
        link_path = link_dir / remote_filename
        try:
            if link_path.exists() or link_path.is_symlink():
                link_path.unlink()
            link_path.symlink_to(path)
            with link_path.open("rb") as fh:
                stat = path.stat()
                folder.upload(fh, mtime=stat.st_mtime, ctime=stat.st_ctime)
        finally:
            try:
                link_path.unlink()
            except OSError:
                pass
            try:
                link_dir.rmdir()
            except OSError:
                pass
        remote_path = f"icloud:{remote_folder.rstrip('/')}/{remote_filename}"
        _json({"ok": True, "status": "uploaded", "backend": "pyicloud", "remote_path": remote_path})
    except Exception as exc:
        _json({"ok": False, "status": "upload_failed", "error": _redact(str(exc))})


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    start_parser = subparsers.add_parser("start")
    start_parser.add_argument("--remote", default="icloud")
    start_parser.add_argument("--apple-id", required=True)
    start_parser.add_argument("--china-mainland", action="store_true")

    for name in ("status", "cancel"):
        sub = subparsers.add_parser(name)
        sub.add_argument("--remote", default="icloud")

    send_parser = subparsers.add_parser("send")
    send_parser.add_argument("--remote", default="icloud")
    send_parser.add_argument("--text", required=True)

    daemon_parser = subparsers.add_parser("daemon")
    daemon_parser.add_argument("--remote", required=True)
    daemon_parser.add_argument("--apple-id", required=True)
    daemon_parser.add_argument("--fifo", required=True)
    daemon_parser.add_argument("--transcript", required=True)
    daemon_parser.add_argument("--session-dir", required=True)
    daemon_parser.add_argument("--china-mainland", action="store_true")

    upload_parser = subparsers.add_parser("upload")
    upload_parser.add_argument("--remote", default="icloud")
    upload_parser.add_argument("--local-path", required=True)
    upload_parser.add_argument("--remote-folder", required=True)
    upload_parser.add_argument("--remote-filename", required=True)

    args = parser.parse_args()
    if args.command == "start":
        start(args.remote, args.apple_id, args.china_mainland)
    elif args.command == "status":
        status(args.remote)
    elif args.command == "send":
        send(args.remote, args.text)
    elif args.command == "cancel":
        cancel(args.remote)
    elif args.command == "daemon":
        daemon(args.remote, args.apple_id, args.fifo, args.transcript, args.session_dir, args.china_mainland)
    elif args.command == "upload":
        upload(args.remote, args.local_path, args.remote_folder, args.remote_filename)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
