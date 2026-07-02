from __future__ import annotations

import sys
from pathlib import Path

from openclaw_app.router.tag_router_common import run_media_subprocess_with_watchdog


def test_tag_router_media_subprocess_watchdog_returns_success_stdout() -> None:
    completed = run_media_subprocess_with_watchdog(
        [sys.executable, "-c", "print('ok')"],
        env={},
        timeout=10,
        cwd=Path("/home/ubuntu"),
    )

    assert completed.returncode == 0
    assert completed.stdout.strip() == "ok"


def test_tag_router_media_subprocess_watchdog_passes_stdin() -> None:
    completed = run_media_subprocess_with_watchdog(
        [sys.executable, "-c", "import sys; print(sys.stdin.read().upper())"],
        env={},
        timeout=10,
        cwd=Path("/home/ubuntu"),
        input="ok",
    )

    assert completed.returncode == 0
    assert completed.stdout.strip() == "OK"


def test_tag_router_media_subprocess_watchdog_kills_total_timeout() -> None:
    completed = run_media_subprocess_with_watchdog(
        [sys.executable, "-c", "import time; time.sleep(2)"],
        env={},
        timeout=1,
        cwd=Path("/home/ubuntu"),
    )

    assert completed.returncode == -9
    assert "[watchdog] timeout_after=" in completed.stderr
    assert "limit=1s" in completed.stderr
