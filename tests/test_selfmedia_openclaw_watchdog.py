from __future__ import annotations

import sys

from runtime.cli.selfmedia import ROOT, run_command_with_watchdog


def test_selfmedia_openclaw_watchdog_returns_success_stdout() -> None:
    completed = run_command_with_watchdog(
        [sys.executable, "-c", "print('ok')"],
        ROOT,
        timeout=10,
    )

    assert completed.returncode == 0
    assert completed.stdout.strip() == "ok"


def test_selfmedia_openclaw_watchdog_kills_total_timeout() -> None:
    completed = run_command_with_watchdog(
        [sys.executable, "-c", "import time; time.sleep(2)"],
        ROOT,
        timeout=1,
    )

    assert completed.returncode == -9
    assert "[watchdog] timeout_after=" in completed.stderr
    assert "limit=1s" in completed.stderr
