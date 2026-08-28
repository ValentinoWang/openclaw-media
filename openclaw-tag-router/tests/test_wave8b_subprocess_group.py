from __future__ import annotations

import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from common.model_transport_context import bind_model_transport
from openclaw_app.router.media_subprocess import run_media_subprocess_with_watchdog
from openclaw_app.router.tag_router_common import run_media_subprocess_with_watchdog as common_watchdog


def _pid_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class MediaSubprocessGroupTests(unittest.TestCase):
    def test_success_preserves_standard_input_and_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            completed = run_media_subprocess_with_watchdog(
                [sys.executable, "-c", "import sys; print(sys.stdin.read().upper())"],
                env={},
                timeout=10,
                cwd=temporary_directory,
                input="ok",
            )

        self.assertEqual(completed.returncode, 0)
        self.assertEqual(completed.stdout.strip(), "OK")

    @unittest.skipUnless(os.name == "posix", "process groups require POSIX")
    def test_timeout_kills_the_grandchild_process_group(self) -> None:
        child_pid: int | None = None
        with tempfile.TemporaryDirectory() as temporary_directory:
            pid_file = Path(temporary_directory) / "grandchild.pid"
            command = [
                sys.executable,
                "-c",
                (
                    "import pathlib, subprocess, sys, time\n"
                    "child = subprocess.Popen(\n"
                    "    [sys.executable, '-c', 'import time; time.sleep(30)'],\n"
                    "    stdin=subprocess.DEVNULL,\n"
                    "    stdout=subprocess.DEVNULL,\n"
                    "    stderr=subprocess.DEVNULL,\n"
                    ")\n"
                    "pathlib.Path(sys.argv[1]).write_text(str(child.pid), encoding='utf-8')\n"
                    "time.sleep(30)\n"
                ),
                str(pid_file),
            ]
            try:
                completed = run_media_subprocess_with_watchdog(
                    command,
                    env={},
                    timeout=2,
                    cwd=temporary_directory,
                )
                child_pid = int(pid_file.read_text(encoding="utf-8"))

                self.assertEqual(completed.returncode, -9)
                self.assertIn("[watchdog] timeout_after=", completed.stderr)
                self.assertIn("limit=2s", completed.stderr)

                deadline = time.monotonic() + 3
                while _pid_is_alive(child_pid) and time.monotonic() < deadline:
                    time.sleep(0.05)
                self.assertFalse(_pid_is_alive(child_pid), "grandchild remained alive after watchdog timeout")
            finally:
                if child_pid is not None and _pid_is_alive(child_pid):
                    os.kill(child_pid, signal.SIGKILL)

    def test_tag_router_common_reuses_the_media_subprocess_helper(self) -> None:
        self.assertIs(common_watchdog, run_media_subprocess_with_watchdog)

    def test_required_tenant_transport_fails_closed_before_spawning(self) -> None:
        with bind_model_transport(None, required=True):
            with self.assertRaisesRegex(RuntimeError, "cannot delegate model work"):
                run_media_subprocess_with_watchdog(
                    [sys.executable, "-c", "raise SystemExit(0)"],
                    env={},
                    timeout=1,
                )
