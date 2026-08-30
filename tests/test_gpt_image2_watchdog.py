from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from _support import load_script_module


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "selfmedia/creation/image_generation.py"
MODULE = load_script_module("gpt_image2", SCRIPT_PATH)


def test_gpt_image2_openclaw_run_has_timeout() -> None:
    captured: dict[str, object] = {}

    def fake_run(cmd, **kwargs):
        captured.update(kwargs)
        return MODULE.subprocess.CompletedProcess(cmd, 0, "{}", "")

    with patch.object(MODULE.subprocess, "run", side_effect=fake_run):
        completed = MODULE.run(["openclaw", "capability", "image"])

    assert completed.returncode == 0
    assert captured["timeout"] == 1800


def test_gpt_image2_openclaw_timeout_returns_watchdog_result() -> None:
    def fake_run(cmd, **_kwargs):
        raise MODULE.subprocess.TimeoutExpired(cmd, 1)

    with patch.object(MODULE.subprocess, "run", side_effect=fake_run):
        completed = MODULE.run(["openclaw", "capability", "image"])

    assert completed.returncode == 124
    assert "[watchdog] gpt-image2 OpenClaw timeout_after=" in completed.stderr
