from __future__ import annotations

import json
import plistlib
import subprocess

import httpx

from openclaw_media import cli
from openclaw_media.agent import AgentState
from openclaw_media.launchd import LABEL, LaunchdManager
from openclaw_media.remote_client import RemoteClient


def test_agent_status_is_redacted_and_gc_has_dry_run_default(tmp_path, capsys):
    agent_dir = tmp_path / "agent"
    cli._agent_store(str(agent_dir)).save(AgentState(remote_base_url="http://fake", device_id="dev_1", credential_ref="device:dev_1:credential", workspace=str(tmp_path)))
    assert cli.main(["agent", "status", "--agent-dir", str(agent_dir)], package_version="0.2.0") == 0
    status = json.loads(capsys.readouterr().out)
    assert status["credential_ref"] == "device:dev_1:credential"
    assert "device-secret" not in json.dumps(status)
    assert cli.main(["gc", "--workspace", str(tmp_path)], package_version="0.2.0") == 0
    gc = json.loads(capsys.readouterr().out)
    assert gc["dry_run"] is True


def test_pair_command_stores_only_keychain_reference(monkeypatch, tmp_path, capsys):
    class FakeRemote:
        def __init__(self, *args, **kwargs):
            pass

        def pair(self, **kwargs):
            return {"device": {"device_id": "dev_1", "state": "paired", "revision": 1, "device_label": "Mac"}, "device_credential": "device-secret"}

        def close(self):
            pass

    class FakeStore:
        def __init__(self):
            self.values = {}

        def put_device(self, device_id, credential):
            self.values[device_id] = credential
            return type("Refs", (), {"device": "device:dev_1:credential"})()

    store = FakeStore()
    monkeypatch.setattr(cli, "RemoteClient", FakeRemote)
    monkeypatch.setattr(cli, "DeviceCredentialStore", lambda: store)
    agent_dir = tmp_path / "agent"
    assert cli.main(["pair", "--base-url", "https://example.invalid", "--pair-code", "one-time", "--device-label", "Mac", "--agent-dir", str(agent_dir), "--workspace", str(tmp_path)], package_version="0.2.0") == 0
    output = json.loads(capsys.readouterr().out)
    assert output["credential_ref"] == "device:dev_1:credential"
    state = (agent_dir / "state.json").read_text()
    assert "device-secret" not in state


def test_pair_does_not_consume_undocumented_session_response_field(monkeypatch, tmp_path):
    class FakeRemote:
        def __init__(self, *args, **kwargs):
            pass

        def pair(self, **kwargs):
            return {
                "device": {"device_id": "dev_1", "state": "paired", "revision": 1, "device_label": "Mac"},
                "device_credential": "device-secret",
                "session_credential": "must-not-be-consumed",
            }

        def close(self):
            pass

    class FakeStore:
        def __init__(self):
            self.device_values = {}
            self.session_values = {}

        def put_device(self, device_id, credential):
            self.device_values[device_id] = credential
            return type("Refs", (), {"device": "device:dev_1:credential"})()

        def put_session(self, device_id, credential):
            self.session_values[device_id] = credential
            raise AssertionError("pair must not configure owner session")

    store = FakeStore()
    monkeypatch.setattr(cli, "RemoteClient", FakeRemote)
    monkeypatch.setattr(cli, "DeviceCredentialStore", lambda: store)
    agent_dir = tmp_path / "agent"
    assert cli.main(
        ["pair", "--base-url", "https://example.invalid", "--pair-code", "one-time", "--device-label", "Mac", "--agent-dir", str(agent_dir), "--workspace", str(tmp_path)],
        package_version="0.2.0",
    ) == 0


def test_session_config_reads_stdin_and_persists_only_a_reference(monkeypatch, tmp_path, capsys):
    class FakeStore:
        def __init__(self):
            self.values = {}

        def put_session(self, device_id, credential):
            self.values[device_id] = credential
            return type("Refs", (), {"session": f"device:{device_id}:session"})()

    store = FakeStore()
    monkeypatch.setattr(cli, "DeviceCredentialStore", lambda: store)
    monkeypatch.setattr(cli.sys, "stdin", type("Stdin", (), {"read": lambda self: "session-secret\n"})())
    agent_dir = tmp_path / "agent"
    cli._agent_store(str(agent_dir)).save(AgentState(remote_base_url="https://example.invalid", device_id="dev_1", workspace=str(tmp_path)))

    assert cli.main(["session", "--agent-dir", str(agent_dir)], package_version="0.2.0") == 0
    output = capsys.readouterr().out
    assert "session-secret" not in output
    assert store.values == {"dev_1": "session-secret"}
    state = (agent_dir / "state.json").read_text()
    assert "session-secret" not in state
    assert "device:dev_1:session" in state


def test_archive_fails_before_http_when_owner_session_is_not_configured(monkeypatch, tmp_path, capsys):
    agent_dir = tmp_path / "agent"
    cli._agent_store(str(agent_dir)).save(AgentState(remote_base_url="https://example.invalid", device_id="dev_1", workspace=str(tmp_path)))

    class ExplodingRemote:
        def __init__(self, *args, **kwargs):
            raise AssertionError("archive must fail before constructing HTTP client")

    monkeypatch.setattr(cli, "RemoteClient", ExplodingRemote)
    assert cli.main(["archive", "list", "--base-url", "https://example.invalid", "--agent-dir", str(agent_dir)], package_version="0.2.0") == 2
    assert "session_not_configured" in capsys.readouterr().err


def test_device_revoke_deletes_both_credentials_only_after_remote_success(monkeypatch, tmp_path, capsys):
    events = []

    class FakeStore:
        def get_session(self, device_id):
            events.append("get_session")
            return "session-secret"

        def delete_device(self, device_id):
            events.append("delete_device")

        def delete_session(self, device_id):
            events.append("delete_session")

    class FakeRemote:
        def __init__(self, *args, **kwargs):
            events.append(("remote_init", kwargs.get("session_credential")))

        def device_revoke(self, device_id, **request):
            events.append(("revoke", device_id, request["expected_revision"]))
            return {"device_id": device_id, "revoked_at": "2026-08-04T00:00:00Z"}

        def close(self):
            events.append("close")

    agent_dir = tmp_path / "agent"
    cli._agent_store(str(agent_dir)).save(AgentState(
        remote_base_url="https://example.invalid", device_id="dev_1", revision=4,
        credential_ref="device:dev_1:credential", session_ref="device:dev_1:session",
        workspace=str(tmp_path),
    ))
    monkeypatch.setattr(cli, "DeviceCredentialStore", lambda: FakeStore())
    monkeypatch.setattr(cli, "RemoteClient", FakeRemote)

    assert cli.main(["device", "revoke", "--base-url", "https://example.invalid", "--expected-revision", "4", "--agent-dir", str(agent_dir)], package_version="0.2.0") == 0
    assert events.index(("revoke", "dev_1", 4)) < events.index("delete_device") < events.index("delete_session")
    state = cli._agent_store(str(agent_dir)).load()
    assert state.status == "revoked"
    assert state.credential_ref is None and state.session_ref is None
    assert "session-secret" not in capsys.readouterr().out


def test_device_revoke_does_not_delete_credentials_when_remote_fails(monkeypatch, tmp_path):
    deleted = []

    class FakeStore:
        def get_session(self, device_id):
            return "session-secret"

        def delete_device(self, device_id):
            deleted.append("device")

        def delete_session(self, device_id):
            deleted.append("session")

    class FakeRemote:
        def __init__(self, *args, **kwargs):
            pass

        def device_revoke(self, device_id, **request):
            raise cli.RemoteError("remote_rejected")

        def close(self):
            pass

    agent_dir = tmp_path / "agent"
    original = AgentState(remote_base_url="https://example.invalid", device_id="dev_1", revision=4, credential_ref="device:dev_1:credential", session_ref="device:dev_1:session", workspace=str(tmp_path))
    cli._agent_store(str(agent_dir)).save(original)
    monkeypatch.setattr(cli, "DeviceCredentialStore", lambda: FakeStore())
    monkeypatch.setattr(cli, "RemoteClient", FakeRemote)
    assert cli.main(["device", "revoke", "--base-url", "https://example.invalid", "--expected-revision", "4", "--agent-dir", str(agent_dir)], package_version="0.2.0") == 2
    assert deleted == []
    assert cli._agent_store(str(agent_dir)).load() == original


def test_gc_rejects_non_finite_or_negative_age_and_never_uses_cwd(monkeypatch, tmp_path):
    for value in ("nan", "inf", "-inf", "-1"):
        assert cli.main(["gc", "--workspace", str(tmp_path), "--min-age-seconds", value], package_version="0.2.0") == 2
    monkeypatch.chdir(tmp_path)
    assert cli.main(["gc", "--apply"], package_version="0.2.0") == 2


def test_archive_unexpected_failure_is_sanitized_and_actionable(monkeypatch, tmp_path, capsys):
    class ExplodingRemote:
        def archive_list(self):
            raise RuntimeError("private token at /Users/private/archive.log")

        def close(self):
            pass

    class FakeClient:
        pass

    monkeypatch.setattr(cli, "_archive_client", lambda *args: (FakeClient(), ExplodingRemote()))
    result = cli.main(
        ["archive", "list", "--base-url", "https://example.invalid", "--agent-dir", str(tmp_path / "agent")],
        package_version="0.2.0",
    )

    assert result == 2
    captured = capsys.readouterr()
    assert "operation_failed" in captured.err
    assert "private token" not in captured.err
    assert "/Users/private" not in captured.err


def test_gc_unexpected_failure_is_sanitized_in_json_mode(monkeypatch, tmp_path, capsys):
    def explode(self, **kwargs):
        raise RuntimeError("secret filesystem detail")

    monkeypatch.setattr(cli.ArchiveClient, "gc", explode)
    result = cli.main(
        ["--json", "gc", "--workspace", str(tmp_path)],
        package_version="0.2.0",
    )

    assert result == 2
    captured = capsys.readouterr()
    assert json.loads(captured.err) == {"error": {"code": "operation_failed"}}
    assert "secret filesystem detail" not in captured.err


def test_workspace_is_required_before_pair_remote_or_state_side_effect(monkeypatch, tmp_path, capsys):
    class ExplodingRemote:
        def __init__(self, *args, **kwargs):
            raise AssertionError("remote must not be constructed")

    monkeypatch.setattr(cli, "RemoteClient", ExplodingRemote)
    agent_dir = tmp_path / "agent"
    assert cli.main(["pair", "--base-url", "https://example.invalid", "--pair-code", "one-time", "--device-label", "Mac", "--agent-dir", str(agent_dir)], package_version="0.2.0") == 2
    assert "workspace_not_configured" in capsys.readouterr().err
    assert not (agent_dir / "state.json").exists()


def test_direct_run_requires_workspace(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("OPENCLAW_MEDIA_WORKSPACE", raising=False)
    monkeypatch.chdir(tmp_path)
    assert cli.main(["run", "media.plan", "--descriptor-json", "{}"], package_version="0.2.0") == 2
    assert "workspace_not_configured" in capsys.readouterr().err


def test_device_revoke_cli_uses_real_remote_generated_operation(monkeypatch, tmp_path, capsys):
    requests = []

    class Transport:
        def request(self, method, path, *, headers=None, content=None, credential=None):
            requests.append({
                "method": method,
                "path": path,
                "headers": headers,
                "content": content,
                "credential": credential,
            })
            return httpx.Response(200, json={"device_id": "dev_1", "revoked_at": "2026-08-04T00:00:00Z"})

    class CredentialStore:
        def get_session(self, device_id):
            assert device_id == "dev_1"
            return "session-secret"

        def delete_device(self, device_id):
            assert device_id == "dev_1"

        def delete_session(self, device_id):
            assert device_id == "dev_1"

    transport = Transport()
    monkeypatch.setattr(
        cli,
        "RemoteClient",
        lambda base_url, **kwargs: RemoteClient(base_url, transport=transport, **kwargs),
    )
    monkeypatch.setattr(cli, "DeviceCredentialStore", lambda: CredentialStore())
    agent_dir = tmp_path / "agent"
    cli._agent_store(str(agent_dir)).save(AgentState(
        remote_base_url="https://example.invalid",
        device_id="dev_1",
        revision=4,
        credential_ref="device:dev_1:credential",
        session_ref="device:dev_1:session",
        workspace=str(tmp_path),
    ))

    assert cli.main(
        ["device", "revoke", "--base-url", "https://example.invalid", "--expected-revision", "4", "--agent-dir", str(agent_dir)],
        package_version="0.2.0",
    ) == 0

    assert len(requests) == 1
    assert requests[0]["method"] == "POST"
    assert requests[0]["path"] == "/openclaw/media/api/devices/dev_1/revoke"
    assert json.loads(requests[0]["content"]) == {"expected_revision": 4}
    assert requests[0]["credential"] == "session-secret"
    assert "session-secret" not in capsys.readouterr().out


def test_launchd_install_uses_real_manager_and_single_constructor_path(monkeypatch, tmp_path, capsys):
    calls = []
    managers = []
    loaded = False

    def runner(command):
        nonlocal loaded
        calls.append(tuple(command))
        if command[1] == "print":
            return subprocess.CompletedProcess(command, 0 if loaded else 113, "", "")
        if command[1] == "bootstrap":
            loaded = True
        elif command[1] == "bootout":
            if not loaded:
                return subprocess.CompletedProcess(command, 113, "", "")
            loaded = False
        return subprocess.CompletedProcess(command, 0, "", "")

    def manager_factory(agent_dir=None):
        manager = LaunchdManager(
            agent_dir=agent_dir,
            runner=runner,
            platform_name="darwin",
            uid=501,
            python_executable="/usr/bin/python3",
        )
        managers.append(manager)
        return manager

    monkeypatch.setattr(cli, "LaunchdManager", manager_factory)
    agent_dir = tmp_path / "LaunchAgents"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    assert cli.main(
        ["launchd", "install", "--agent-dir", str(agent_dir), "--workspace", str(workspace), "--no-start"],
        package_version="0.2.0",
    ) == 0

    result = json.loads(capsys.readouterr().out)
    assert result == {"label": LABEL, "installed": True, "running": False}
    assert [manager.agent_dir for manager in managers] == [agent_dir]
    plist = plistlib.loads((agent_dir / f"{LABEL}.plist").read_bytes())
    assert plist["WorkingDirectory"] == str(workspace)
    assert not any(command[1] == "bootstrap" for command in calls)
    assert not any(command[1] == "enable" for command in calls)
    assert not any(command[1] == "kickstart" for command in calls)

    assert cli.main(["launchd", "status", "--agent-dir", str(agent_dir)], package_version="0.2.0") == 0
    assert json.loads(capsys.readouterr().out) == {"label": LABEL, "installed": True, "running": False}
    assert cli.main(["launchd", "restart", "--agent-dir", str(agent_dir)], package_version="0.2.0") == 0
    assert json.loads(capsys.readouterr().out) == {"label": LABEL, "installed": True, "running": True}
    assert any(command[1] == "kickstart" for command in calls)
    assert cli.main(["launchd", "uninstall", "--agent-dir", str(agent_dir)], package_version="0.2.0") == 0
    assert [manager.agent_dir for manager in managers[-2:]] == [agent_dir, agent_dir]


def test_launchd_restart_reports_missing_install(monkeypatch, tmp_path, capsys):
    def manager_factory(agent_dir=None):
        return LaunchdManager(
            agent_dir=agent_dir,
            runner=lambda command: subprocess.CompletedProcess(command, 0, "", ""),
            platform_name="darwin",
            uid=501,
        )

    monkeypatch.setattr(cli, "LaunchdManager", manager_factory)
    assert cli.main(
        ["launchd", "restart", "--agent-dir", str(tmp_path / "LaunchAgents")],
        package_version="0.2.0",
    ) == 2
    assert "launchd_not_installed" in capsys.readouterr().err
