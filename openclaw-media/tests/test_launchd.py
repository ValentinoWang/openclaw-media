from __future__ import annotations

from pathlib import Path
import plistlib
import subprocess

import pytest

from openclaw_media.launchd import LABEL, LaunchdError, LaunchdManager


def test_launchd_install_status_uninstall_uses_fake_launchctl_and_no_secret(tmp_path):
    commands = []

    def runner(command):
        commands.append(tuple(command))
        return subprocess.CompletedProcess(command, 0, "", "")

    manager = LaunchdManager(agent_dir=tmp_path / "LaunchAgents", runner=runner, platform_name="darwin", uid=501, python_executable="/usr/bin/python3")
    installed = manager.install(workspace=tmp_path / "workspace")
    assert installed == {"label": LABEL, "installed": True, "running": True}
    plist = plistlib.loads(manager.plist_path.read_bytes())
    assert plist["Label"] == LABEL
    assert "device-secret" not in manager.plist_path.read_text()
    assert "session-secret" not in manager.plist_path.read_text()
    assert manager.status()["running"] is True
    assert manager.uninstall()["installed"] is False
    assert not manager.plist_path.exists()
    assert any(command[1] == "bootstrap" for command in commands)
    assert any(command[1] == "bootout" for command in commands)


def test_no_start_disables_run_at_load_and_skips_kickstart(tmp_path):
    commands = []

    def runner(command):
        commands.append(tuple(command))
        return subprocess.CompletedProcess(command, 0, "", "")

    manager = LaunchdManager(
        agent_dir=tmp_path / "LaunchAgents",
        runner=runner,
        platform_name="darwin",
        uid=501,
        python_executable="/usr/bin/python3",
    )
    installed = manager.install(workspace=tmp_path / "workspace", start=False)
    plist = plistlib.loads(manager.plist_path.read_bytes())

    assert installed == {"label": LABEL, "installed": True, "running": False}
    assert plist["RunAtLoad"] is False
    assert plist["KeepAlive"] is False
    assert not any(command[1] == "bootstrap" for command in commands)
    assert not any(command[1] == "enable" for command in commands)
    assert not any(command[1] == "kickstart" for command in commands)


def test_restart_bootstraps_an_installed_but_unloaded_agent(tmp_path):
    commands = []
    loaded = False

    def runner(command):
        nonlocal loaded
        commands.append(tuple(command))
        if command[1] == "print":
            return subprocess.CompletedProcess(command, 0 if loaded else 113, "", "")
        if command[1] == "bootstrap":
            loaded = True
        elif command[1] == "bootout":
            if not loaded:
                return subprocess.CompletedProcess(command, 113, "", "")
            loaded = False
        return subprocess.CompletedProcess(command, 0, "", "")

    manager = LaunchdManager(
        agent_dir=tmp_path / "LaunchAgents",
        runner=runner,
        platform_name="darwin",
        uid=501,
        python_executable="/usr/bin/python3",
    )
    manager.install(workspace=tmp_path / "workspace", start=False)
    assert manager.status() == {"label": LABEL, "installed": True, "running": False}
    assert manager.restart() == {"label": LABEL, "installed": True, "running": True}
    assert manager.uninstall() == {"label": LABEL, "installed": False, "running": False}
    assert not manager.plist_path.exists()
    assert any(command[1] == "bootstrap" for command in commands)
    assert any(command[1] == "enable" for command in commands)
    assert any(command[1] == "kickstart" for command in commands)


def test_launchd_is_macos_only(tmp_path):
    manager = LaunchdManager(agent_dir=tmp_path, platform_name="linux")
    assert manager.plist_path.parent == tmp_path
    try:
        manager.status()
    except Exception as exc:
        assert getattr(exc, "code", None) == "macos_required"
    else:
        raise AssertionError("launchd unexpectedly enabled on Linux")


def test_uninstall_preserves_plist_when_bootout_fails(tmp_path):
    plist_dir = tmp_path / "LaunchAgents"
    calls = []

    def runner(command):
        calls.append(tuple(command))
        if command[1] == "bootout":
            return subprocess.CompletedProcess(command, 1, "busy", "")
        return subprocess.CompletedProcess(command, 0, "", "")

    manager = LaunchdManager(agent_dir=plist_dir, runner=runner, platform_name="darwin", uid=501)
    manager.plist_path.parent.mkdir(parents=True)
    manager.plist_path.write_bytes(b"original-plist")
    with pytest.raises(LaunchdError) as raised:
        manager.uninstall()
    assert raised.value.code == "launchctl_failed"
    assert manager.plist_path.read_bytes() == b"original-plist"


def test_upgrade_does_not_overwrite_when_existing_bootout_fails(tmp_path):
    calls = []

    def runner(command):
        calls.append(tuple(command))
        if command[1] == "bootout":
            return subprocess.CompletedProcess(command, 1, "busy", "")
        return subprocess.CompletedProcess(command, 0, "", "")

    manager = LaunchdManager(agent_dir=tmp_path, runner=runner, platform_name="darwin", uid=501)
    manager.plist_path.write_bytes(b"old-plist")
    with pytest.raises(LaunchdError):
        manager.install(workspace=tmp_path / "new")
    assert manager.plist_path.read_bytes() == b"old-plist"
    assert not any(command[1] == "bootstrap" for command in calls)


@pytest.mark.parametrize("operation", ["install", "uninstall"])
def test_existing_service_state_failure_preserves_plist(tmp_path, operation):
    def runner(command):
        return subprocess.CompletedProcess(command, 1, "launchctl unavailable", "")

    manager = LaunchdManager(agent_dir=tmp_path, runner=runner, platform_name="darwin", uid=501)
    manager.plist_path.write_bytes(b"old-plist")

    with pytest.raises(LaunchdError) as raised:
        if operation == "install":
            manager.install(start=False)
        else:
            manager.uninstall()

    assert raised.value.code == "launchctl_failed"
    assert manager.plist_path.read_bytes() == b"old-plist"


@pytest.mark.parametrize("failure", ["bootstrap", "enable", "kickstart"])
def test_install_failures_leave_plist_recoverable_and_never_report_running(tmp_path, failure):
    calls = []

    def runner(command):
        calls.append(tuple(command))
        if command[1] == failure:
            return subprocess.CompletedProcess(command, 1, "failed", "")
        return subprocess.CompletedProcess(command, 0, "", "")

    manager = LaunchdManager(agent_dir=tmp_path, runner=runner, platform_name="darwin", uid=501)
    with pytest.raises(LaunchdError):
        manager.install(start=True)
    assert manager.plist_path.is_file()
    assert not (tmp_path / f"{LABEL}.plist.tmp").exists()


def test_restart_kickstarts_and_reads_back_status_without_rewriting_secret_free_plist(tmp_path):
    calls = []

    def runner(command):
        calls.append(tuple(command))
        return subprocess.CompletedProcess(command, 0, "", "")

    manager = LaunchdManager(
        agent_dir=tmp_path / "LaunchAgents",
        runner=runner,
        platform_name="darwin",
        uid=501,
        python_executable="/usr/bin/python3",
    )
    manager.install(workspace=tmp_path / "workspace", start=False)
    calls.clear()
    original_plist = manager.plist_path.read_bytes()

    assert manager.restart() == {"label": LABEL, "installed": True, "running": True}
    assert manager.restart() == {"label": LABEL, "installed": True, "running": True}
    assert manager.plist_path.read_bytes() == original_plist
    assert calls == [
        ("launchctl", "print", f"gui/501/{LABEL}"),
        ("launchctl", "kickstart", "-k", f"gui/501/{LABEL}"),
        ("launchctl", "print", f"gui/501/{LABEL}"),
        ("launchctl", "print", f"gui/501/{LABEL}"),
        ("launchctl", "kickstart", "-k", f"gui/501/{LABEL}"),
        ("launchctl", "print", f"gui/501/{LABEL}"),
    ]
    serialized = manager.plist_path.read_text()
    assert "device-secret" not in serialized
    assert "session-secret" not in serialized
    assert all("secret" not in " ".join(command) for command in calls)


def test_restart_reports_missing_install_without_calling_launchctl(tmp_path):
    calls = []

    def runner(command):
        calls.append(tuple(command))
        return subprocess.CompletedProcess(command, 0, "", "")

    manager = LaunchdManager(agent_dir=tmp_path, runner=runner, platform_name="darwin", uid=501)
    with pytest.raises(LaunchdError) as raised:
        manager.restart()
    assert raised.value.code == "launchd_not_installed"
    assert calls == []


def test_restart_does_not_report_running_when_kickstart_or_status_fails(tmp_path):
    calls = []

    def runner(command):
        calls.append(tuple(command))
        if command[1] == "kickstart":
            return subprocess.CompletedProcess(command, 1, "restart failed", "")
        return subprocess.CompletedProcess(command, 0, "", "")

    manager = LaunchdManager(agent_dir=tmp_path, runner=runner, platform_name="darwin", uid=501)
    manager.install(start=False)
    calls.clear()
    original_plist = manager.plist_path.read_bytes()
    with pytest.raises(LaunchdError) as raised:
        manager.restart()
    assert raised.value.code == "launchctl_failed"
    assert manager.plist_path.read_bytes() == original_plist
    assert calls == [
        ("launchctl", "print", f"gui/501/{LABEL}"),
        ("launchctl", "kickstart", "-k", f"gui/501/{LABEL}"),
    ]


def test_restart_reports_status_failure_after_successful_kickstart(tmp_path):
    calls = []
    print_count = 0

    def runner(command):
        nonlocal print_count
        calls.append(tuple(command))
        if command[1] == "print":
            print_count += 1
            return subprocess.CompletedProcess(command, 0 if print_count == 1 else 113, "", "")
        return subprocess.CompletedProcess(command, 0, "", "")

    manager = LaunchdManager(agent_dir=tmp_path, runner=runner, platform_name="darwin", uid=501)
    manager.plist_path.write_bytes(b"installed-plist")

    with pytest.raises(LaunchdError) as raised:
        manager.restart()

    assert raised.value.code == "launchd_not_running"
    assert calls == [
        ("launchctl", "print", f"gui/501/{LABEL}"),
        ("launchctl", "kickstart", "-k", f"gui/501/{LABEL}"),
        ("launchctl", "print", f"gui/501/{LABEL}"),
    ]
