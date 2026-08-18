"""Small, credential-free macOS launchd lifecycle adapter."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import plistlib
import platform
import subprocess
import sys
from typing import Callable, Sequence


LABEL = "com.openclaw.media.agent"


class LaunchdError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


Runner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


def _default_runner(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=False, capture_output=True, text=True)


@dataclass(slots=True)
class LaunchdManager:
    agent_dir: Path | None = None
    runner: Runner = _default_runner
    platform_name: str | None = None
    uid: int | None = None
    python_executable: str | None = None

    @property
    def plist_path(self) -> Path:
        return (self.agent_dir or Path.home() / "Library" / "LaunchAgents") / f"{LABEL}.plist"

    @property
    def domain(self) -> str:
        return f"gui/{self.uid if self.uid is not None else os.getuid()}"

    def _check_platform(self) -> None:
        if (self.platform_name or platform.system()).lower() != "darwin":
            raise LaunchdError("macos_required")
        if not self.python_executable:
            self.python_executable = sys.executable

    def _launchctl(self, *args: str, allow_failure: bool = False) -> subprocess.CompletedProcess[str]:
        self._check_platform()
        try:
            result = self.runner(("launchctl", *args))
        except OSError as exc:
            raise LaunchdError("launchctl_unavailable") from exc
        if result.returncode != 0 and not allow_failure:
            raise LaunchdError("launchctl_failed")
        return result

    def _is_loaded(self) -> bool:
        result = self._launchctl(
            "print", f"{self.domain}/{LABEL}", allow_failure=True
        )
        if result.returncode == 0:
            return True
        if result.returncode == 113:
            return False
        raise LaunchdError("launchctl_failed")

    def _plist(
        self,
        workspace: Path | None = None,
        *,
        run_at_load: bool = True,
    ) -> dict[str, object]:
        self._check_platform()
        executable = self.python_executable or sys.executable
        arguments = [executable, "-m", "openclaw_media.cli", "agent", "run", "--foreground"]
        value: dict[str, object] = {
            "Label": LABEL,
            "ProgramArguments": arguments,
            "RunAtLoad": run_at_load,
            "KeepAlive": run_at_load,
            "ProcessType": "Background",
            "ThrottleInterval": 10,
        }
        if workspace is not None:
            value["WorkingDirectory"] = str(workspace)
        return value

    def install(self, *, workspace: Path | None = None, start: bool = True) -> dict[str, object]:
        self._check_platform()
        directory = self.plist_path.parent
        directory.mkdir(parents=True, exist_ok=True)
        # Read/unload an existing label before replacing it, making upgrades
        # deterministic and avoiding two agents claiming the same lease.
        if self.plist_path.exists():
            result = self._launchctl("bootout", f"{self.domain}/{LABEL}", allow_failure=True)
            if result.returncode != 0 and self._is_loaded():
                raise LaunchdError("launchctl_failed")
        payload = plistlib.dumps(
            self._plist(workspace, run_at_load=start),
            fmt=plistlib.FMT_XML,
            sort_keys=True,
        )
        temporary = self.plist_path.with_suffix(".plist.tmp")
        temporary.write_bytes(payload)
        os.replace(temporary, self.plist_path)
        if start:
            self._launchctl("bootstrap", self.domain, str(self.plist_path))
            self._launchctl("enable", f"{self.domain}/{LABEL}")
            self._launchctl("kickstart", "-k", f"{self.domain}/{LABEL}")
        return {"label": LABEL, "installed": True, "running": bool(start)}

    def restart(self) -> dict[str, object]:
        self._check_platform()
        if not self.plist_path.is_file():
            raise LaunchdError("launchd_not_installed")
        if not self._is_loaded():
            self._launchctl("bootstrap", self.domain, str(self.plist_path))
            self._launchctl("enable", f"{self.domain}/{LABEL}")
        self._launchctl("kickstart", "-k", f"{self.domain}/{LABEL}")
        state = self.status()
        if not state["installed"]:
            raise LaunchdError("launchd_not_installed")
        if not state["running"]:
            raise LaunchdError("launchd_not_running")
        return state

    def status(self) -> dict[str, object]:
        self._check_platform()
        return {
            "label": LABEL,
            "installed": self.plist_path.is_file(),
            "running": self._is_loaded(),
        }

    def uninstall(self) -> dict[str, object]:
        self._check_platform()
        result = self._launchctl("bootout", f"{self.domain}/{LABEL}", allow_failure=True)
        if result.returncode != 0 and self._is_loaded():
            raise LaunchdError("launchctl_failed")
        try:
            self.plist_path.unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise LaunchdError("plist_delete_failed") from exc
        return {"label": LABEL, "installed": False, "running": False}


__all__ = ["LABEL", "LaunchdError", "LaunchdManager"]
