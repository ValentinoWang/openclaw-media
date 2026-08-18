from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

from common.model_transport_context import tenant_model_transport_required


def run_media_subprocess_with_watchdog(
    command: list[str],
    *,
    env: dict[str, str] | None,
    timeout: int,
    cwd: str | Path | None = None,
    input: str | None = None,
) -> subprocess.CompletedProcess[str]:
    if tenant_model_transport_required():
        raise RuntimeError(
            "authenticated Media execution cannot delegate model work to a process outside the tenant transport"
        )
    heartbeat_seconds = max(10, int(float(os.getenv("OPENCLAW_TAG_ROUTER_SUBPROCESS_WATCHDOG_HEARTBEAT_SECONDS", "60"))))
    started_at = time.monotonic()
    process = subprocess.Popen(
        command,
        cwd=str(cwd) if cwd is not None else None,
        text=True,
        stdin=subprocess.PIPE if input is not None else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    watchdog_lines: list[str] = []
    pending_input = input
    while True:
        elapsed = time.monotonic() - started_at
        remaining = max(0.1, float(timeout) - elapsed)
        wait_for = min(float(heartbeat_seconds), remaining)
        try:
            stdout, stderr = process.communicate(input=pending_input, timeout=wait_for)
            if watchdog_lines:
                stderr = "\n".join([*(line for line in watchdog_lines if line), stderr or ""]).strip()
            return subprocess.CompletedProcess(command, process.returncode, stdout or "", stderr or "")
        except subprocess.TimeoutExpired:
            pending_input = None
            elapsed = time.monotonic() - started_at
            if elapsed >= timeout:
                process.kill()
                stdout, stderr = process.communicate()
                watchdog_lines.append(f"[watchdog] timeout_after={int(elapsed)}s limit={timeout}s command={command[0]}")
                stderr = "\n".join([*(line for line in watchdog_lines if line), stderr or ""]).strip()
                return subprocess.CompletedProcess(command, -9, stdout or "", stderr)
            watchdog_lines.append(f"[watchdog] still_running elapsed={int(elapsed)}s command={command[0]}")
