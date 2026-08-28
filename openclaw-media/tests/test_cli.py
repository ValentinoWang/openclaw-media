from importlib.metadata import PackageNotFoundError
import json
from pathlib import Path

import pytest

from openclaw_media import cli


def test_root_without_arguments_prints_product_help(capsys):
    assert cli.main([], package_version="1.2.3") == 0

    captured = capsys.readouterr()
    assert "Media Agent CLI" in captured.out
    assert "usage: openclaw-media" in captured.out
    assert captured.err == ""


def test_version_uses_injected_installed_distribution_value(capsys):
    with pytest.raises(SystemExit) as stopped:
        cli.main(["--version"], package_version="1.2.3")

    assert stopped.value.code == 0
    assert capsys.readouterr().out == "openclaw-media 1.2.3\n"


def test_default_version_reads_installed_distribution_metadata(monkeypatch, capsys):
    calls = []

    def installed_version():
        calls.append(True)
        return "2.0.0"

    monkeypatch.setattr(cli, "_installed_version", installed_version)
    with pytest.raises(SystemExit):
        cli.main(["--version"])

    assert calls == [True]
    assert capsys.readouterr().out == "openclaw-media 2.0.0\n"


def test_missing_distribution_metadata_is_explicit_and_sanitized(monkeypatch, capsys):
    def unavailable():
        raise PackageNotFoundError("private build path")

    monkeypatch.setattr(cli, "_installed_version", unavailable)
    assert cli.main([]) == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        "openclaw-media: error: installed package metadata unavailable\n"
    )
    assert "private build path" not in captured.err


def test_cli_source_contains_no_development_generator_or_absolute_path():
    source = Path(cli.__file__).read_text(encoding="utf-8")

    assert "generate-catalog" not in source
    assert "/home/" not in source


def test_cli_errors_explain_the_problem_and_json_mode_stays_machine_readable(tmp_path, capsys):
    arguments = [
        "pair",
        "--base-url",
        "https://example.invalid",
        "--pair-code",
        "one-time",
        "--device-label",
        "Mac",
        "--agent-dir",
        str(tmp_path / "agent"),
    ]

    assert cli.main(arguments, package_version="1.2.3") == 2
    human_error = capsys.readouterr()
    assert human_error.out == ""
    assert human_error.err == (
        "openclaw-media: error: workspace_not_configured — 未找到可用的本地工作区；使用 --workspace 指定一个存在的目录。\n"
    )

    assert cli.main(["--json", *arguments], package_version="1.2.3") == 2
    machine_error = capsys.readouterr()
    assert machine_error.out == ""
    assert json.loads(machine_error.err) == {"error": {"code": "workspace_not_configured"}}
