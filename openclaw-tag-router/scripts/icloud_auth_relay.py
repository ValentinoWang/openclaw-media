#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import pty
import re
import select
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


RUNTIME_DIR = Path(os.environ.get("OPENCLAW_ICLOUD_AUTH_RUNTIME_DIR", "/home/ubuntu/.openclaw/workspace/openclaw-tag-router/runtime/icloud_auth"))
RCLONE_BIN = os.environ.get("OPENCLAW_RCLONE_BIN", "rclone")


def _json(data: dict[str, Any]) -> None:
    print(json.dumps(data, ensure_ascii=False))


def _state_path(remote: str) -> Path:
    return RUNTIME_DIR / f"{_safe_name(remote)}.json"


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip().rstrip(":") or "icloud")


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
    _state_path(remote).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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


def _tail(path: str | Path, limit: int = 5000) -> str:
    p = Path(path)
    if not p.exists():
        return ""
    data = p.read_bytes()[-limit:]
    return data.decode("utf-8", errors="replace")


def _redact(text: str) -> str:
    text = re.sub(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "<apple_id>", text)
    text = re.sub(r"(?i)(password\s*[:=]?\s*)\S+", r"\1<redacted>", text)
    return text


def _classify(text: str, running: bool) -> str:
    lower = text.lower()
    if "password" in lower:
        return "password_required"
    if any(marker in lower for marker in ("2fa", "two-factor", "verification code", "two factor", "trusted device", "enter code")):
        return "awaiting_2fa"
    if re.search(r"\b(sms|y/n|yes/no)\b", lower):
        return "awaiting_choice"
    if running:
        return "running"
    if "process exited code 0" in lower or "configuration complete" in lower:
        return "completed"
    return "stopped"


def _remote_configured(remote: str) -> bool:
    proc = subprocess.run([RCLONE_BIN, "listremotes"], text=True, capture_output=True, timeout=20)
    return proc.returncode == 0 and f"{remote.rstrip(':')}:" in proc.stdout.splitlines()


def _status(remote: str) -> dict[str, Any]:
    state = _read_state(remote)
    if not state:
        return {"ok": True, "status": "no_active_session", "remote": remote}
    pid = int(state.get("pid") or 0)
    running = _pid_running(pid)
    transcript = str(state.get("transcript") or "")
    tail = _redact(_tail(transcript))
    status = _classify(tail, running)
    reply = _reply_for_status(status, state, tail)
    return {
        "ok": status not in {"password_required"},
        "status": status,
        "remote": remote,
        "running": running,
        "pid": pid,
        "transcript": transcript,
        "fifo": state.get("fifo", ""),
        "tail": tail[-1600:],
        "reply": reply,
    }


def _reply_for_status(status: str, state: dict[str, Any], tail: str) -> str:
    if status == "awaiting_2fa":
        return "iCloud 认证正在等待验证码。请在飞书发送：`【灵感>vlog】验证码 123456`。"
    if status == "awaiting_choice":
        return "iCloud 认证正在等待选择。请按提示发送：`【灵感>vlog】验证码 y`、`【灵感>vlog】验证码 n` 或 `【灵感>vlog】验证码 sms`。"
    if status == "password_required":
        return (
            "rclone 正在要求 Apple ID 密码。为避免密码在飞书聊天里明文流动，我没有继续接收密码。"
            "请先用一次安全方式完成 rclone iCloud remote 初始化；之后 30 天左右的 2FA 续期可以在媒体 bot 里完成。"
        )
    if status == "completed":
        return "iCloud 认证/续期流程已结束。可以发送 `【灵感>vlog】iCloud状态` 检查是否可上传。"
    if status == "no_active_session":
        return "当前没有正在进行的 iCloud 认证会话。"
    if status == "running":
        return "iCloud 认证流程正在运行，等待 rclone 输出下一步提示。"
    return f"iCloud 认证流程未在运行。最近输出：{tail[-500:]}"


def start(remote: str) -> None:
    current = _status(remote)
    if current.get("running"):
        _json(current)
        return

    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    safe_remote = _safe_name(remote)
    fifo = RUNTIME_DIR / f"{safe_remote}.fifo"
    transcript = RUNTIME_DIR / f"{safe_remote}.transcript"
    for path in (fifo,):
        try:
            if path.exists():
                path.unlink()
        except OSError:
            pass
    os.mkfifo(fifo, 0o600)
    transcript.write_text("", encoding="utf-8")

    configured = _remote_configured(remote)
    if configured:
        cmd = [RCLONE_BIN, "config", "reconnect", f"{remote.rstrip(':')}:"]
        mode = "reconnect"
    elif os.environ.get("OPENCLAW_ICLOUD_AUTH_ALLOW_CREATE", "").strip().lower() in {"1", "true", "yes"}:
        cmd = [RCLONE_BIN, "config", "create", remote.rstrip(":"), "iclouddrive"]
        mode = "create"
    else:
        _json(
            {
                "ok": False,
                "status": "not_configured",
                "remote": remote,
                "reply": (
                    f"rclone remote `{remote.rstrip(':')}:` 还没有配置。首次 iCloud 初始化需要 Apple ID 密码，"
                    "不建议通过飞书发送；请先用一次安全方式完成 remote 初始化。之后认证过期时可通过 media bot 输入 2FA 验证码续期。"
                ),
            }
        )
        return

    daemon_cmd = [
        sys.executable,
        str(Path(__file__).resolve()),
        "daemon",
        "--remote",
        remote,
        "--fifo",
        str(fifo),
        "--transcript",
        str(transcript),
        "--cmd-json",
        json.dumps(cmd),
    ]
    proc = subprocess.Popen(daemon_cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    state = {
        "remote": remote,
        "pid": proc.pid,
        "fifo": str(fifo),
        "transcript": str(transcript),
        "mode": mode,
        "cmd": cmd,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    _write_state(remote, state)
    time.sleep(1.2)
    status = _status(remote)
    status["mode"] = mode
    _json(status)


def send(remote: str, text: str) -> None:
    state = _read_state(remote)
    if not state:
        _json({"ok": False, "status": "no_active_session", "reply": "当前没有正在进行的 iCloud 认证会话。"})
        return
    status = _status(remote)
    if status.get("status") == "password_required":
        _json(status)
        return
    if not status.get("running"):
        _json(status)
        return
    fifo = str(state.get("fifo") or "")
    try:
        fd = os.open(fifo, os.O_WRONLY | os.O_NONBLOCK)
        try:
            os.write(fd, (text.strip() + "\n").encode("utf-8"))
        finally:
            os.close(fd)
    except Exception as exc:
        _json({"ok": False, "status": "send_failed", "error": str(exc), "reply": f"验证码发送失败：{exc}"})
        return
    time.sleep(1.0)
    _json(_status(remote))


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
    _json({"ok": True, "status": "cancelled", "reply": "已取消 iCloud 认证会话。"})


def daemon(remote: str, fifo: str, transcript: str, cmd_json: str) -> None:
    cmd = json.loads(cmd_json)
    master_fd, slave_fd = pty.openpty()
    child = subprocess.Popen(cmd, stdin=slave_fd, stdout=slave_fd, stderr=slave_fd, close_fds=True)
    os.close(slave_fd)
    fifo_fd = os.open(fifo, os.O_RDWR | os.O_NONBLOCK)
    transcript_path = Path(transcript)
    with transcript_path.open("ab", buffering=0) as out:
        out.write(f"[icloud-auth-relay] started: {' '.join(cmd)}\n".encode("utf-8"))
        while True:
            ready, _, _ = select.select([master_fd, fifo_fd], [], [], 0.5)
            if master_fd in ready:
                try:
                    data = os.read(master_fd, 4096)
                except OSError:
                    data = b""
                if data:
                    out.write(data)
            if fifo_fd in ready:
                try:
                    data = os.read(fifo_fd, 4096)
                except OSError:
                    data = b""
                if data:
                    os.write(master_fd, data)
            code = child.poll()
            if code is not None:
                try:
                    while True:
                        data = os.read(master_fd, 4096)
                        if not data:
                            break
                        out.write(data)
                except OSError:
                    pass
                out.write(f"\n[icloud-auth-relay] process exited code {code}\n".encode("utf-8"))
                break
    os.close(master_fd)
    os.close(fifo_fd)


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("start", "status", "cancel"):
        sub = subparsers.add_parser(name)
        sub.add_argument("--remote", default="icloud")
    send_parser = subparsers.add_parser("send")
    send_parser.add_argument("--remote", default="icloud")
    send_parser.add_argument("--text", required=True)
    daemon_parser = subparsers.add_parser("daemon")
    daemon_parser.add_argument("--remote", required=True)
    daemon_parser.add_argument("--fifo", required=True)
    daemon_parser.add_argument("--transcript", required=True)
    daemon_parser.add_argument("--cmd-json", required=True)
    args = parser.parse_args()

    if args.command == "start":
        start(args.remote)
    elif args.command == "status":
        _json(_status(args.remote))
    elif args.command == "send":
        send(args.remote, args.text)
    elif args.command == "cancel":
        cancel(args.remote)
    elif args.command == "daemon":
        daemon(args.remote, args.fifo, args.transcript, args.cmd_json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
