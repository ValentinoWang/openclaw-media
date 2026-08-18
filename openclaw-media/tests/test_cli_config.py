import io
import json
from pathlib import Path

from openclaw_media import cli
from openclaw_media.provider_config import ProviderConfigRepository, ProviderConfigService


class MemoryCredentials:
    def __init__(self):
        self.values = {}

    def put(self, ref, secret):
        self.values[ref] = secret

    def get(self, ref):
        return self.values[ref]

    def delete(self, ref):
        self.values.pop(ref, None)


def make_cli(monkeypatch, tmp_path):
    credentials = MemoryCredentials()
    service = ProviderConfigService(ProviderConfigRepository(tmp_path), credentials)
    monkeypatch.setattr(cli, "_provider_service", lambda: service)
    return service, credentials


def test_provider_create_read_rotate_delete_is_sanitized(monkeypatch, tmp_path, capsys):
    service, credentials = make_cli(monkeypatch, tmp_path)
    secret = "sk-live-do-not-print"
    endpoint = "https://provider.example.test/v1"
    monkeypatch.setattr(cli.sys, "stdin", io.StringIO(f"{secret}\n"))
    args = ["config", "provider", "create", "--id", "main", "--base-url", endpoint,
            "--model", "gpt-test", "--model-label", "Primary"]
    assert cli.main(args, package_version="0.2.0") == 0
    created = json.loads(capsys.readouterr().out)
    assert created["provider_type"] == "openai_compatible"
    assert created["model_label"] == "Primary"
    assert "api_key" not in created and endpoint not in json.dumps(created)
    config = service.repository.load("main")
    old_ref = config.credential_ref
    assert credentials.values[old_ref] == secret

    assert cli.main(["config", "provider", "read", "--id", "main"], package_version="0.2.0") == 0
    assert endpoint not in capsys.readouterr().out
    monkeypatch.setattr(cli.sys, "stdin", io.StringIO("sk-new\n"))
    assert cli.main(["config", "provider", "rotate", "--id", "main"], package_version="0.2.0") == 0
    capsys.readouterr()
    rotated = service.repository.load("main")
    assert rotated.credential_ref != old_ref
    assert old_ref not in credentials.values and credentials.values[rotated.credential_ref] == "sk-new"

    assert cli.main(["config", "provider", "delete", "--id", "main"], package_version="0.2.0") == 0
    assert json.loads(capsys.readouterr().out) == {"deleted": True}
    assert not (Path(tmp_path) / "main.json").exists()


def test_invalid_or_missing_provider_input_does_not_mutate(monkeypatch, tmp_path, capsys):
    service, credentials = make_cli(monkeypatch, tmp_path)
    monkeypatch.setattr(cli.sys, "stdin", io.StringIO("secret\n"))
    assert cli.main(["config", "provider", "create", "--id", "bad id"], package_version="0.2.0") == 2
    assert capsys.readouterr().out == ""
    assert service.repository.list() == ()
    assert credentials.values == {}
    assert cli.main(["config", "provider", "read", "--id", "missing"], package_version="0.2.0") == 2
    assert capsys.readouterr().out == ""


def test_provider_api_key_argv_is_rejected_without_secret_leak(monkeypatch, tmp_path, capsys):
    service, credentials = make_cli(monkeypatch, tmp_path)
    secret = "sk-secret-must-not-appear"
    assert cli.main(
        [
            "config",
            "provider",
            "create",
            "--id",
            "main",
            "--base-url",
            "https://provider.example.test/v1",
            "--model",
            "gpt-test",
            "--model-label",
            "Primary",
            "--api-key",
            secret,
        ],
        package_version="0.2.0",
    ) == 2
    captured = capsys.readouterr()
    assert secret not in captured.out
    assert secret not in captured.err
    assert service.repository.list() == ()
    assert credentials.values == {}

    equal_form_secret = "sk-equals-form-must-not-appear"
    assert cli.main(
        ["config", "provider", "create", "--id", "main", "--api-key=" + equal_form_secret],
        package_version="0.2.0",
    ) == 2
    captured = capsys.readouterr()
    assert equal_form_secret not in captured.out
    assert equal_form_secret not in captured.err
    assert service.repository.list() == ()
    assert credentials.values == {}


def test_provider_command_source_has_no_secret_or_absolute_output_paths():
    source = Path(cli.__file__).read_text(encoding="utf-8")
    assert "print(opts.api_key)" not in source
    assert "print(config.base_url)" not in source
    assert "/home/" not in source
