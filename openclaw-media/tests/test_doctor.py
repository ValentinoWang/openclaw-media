import json
import sys

import pytest

import openclaw_media.doctor as doctor_module
from openclaw_media.doctor import DoctorReport, run_doctor
from openclaw_media import cli


class Runner:
    def __init__(self, *, missing=()):
        self.missing = set(missing)
        self.calls = []

    def which(self, name):
        return None if name in self.missing else f"/private/bin/{name}"

    def run(self, command):
        self.calls.append(tuple(command))
        name = command[0]
        if name == "ffmpeg" and command[1] == "-version":
            return (0, "ffmpeg version 6.1.1", "secret stderr")
        if name == "ffprobe" and command[1] == "-version":
            return (0, "ffprobe version 6.1.1", "")
        if name == "ffmpeg" and command[1] == "-codecs":
            return (0, " DEV.LS h264\n DEA.L. aac", "")
        if name == "ffmpeg" and command[1] == "-filters":
            return (0, " ... scale ...\n ... aresample ...", "")
        if name == "ffmpeg" and command[1] == "-f":
            return (0, "", "")
        raise AssertionError(command)


class FailingRunner(Runner):
    def run(self, command):
        if command[0] == "ffprobe":
            raise RuntimeError("token=sk-secret endpoint=https://private.example")
        return super().run(command)


def test_healthy_report_is_structured_and_path_free():
    report = run_doctor(runner=Runner(), python_version=(3, 12, 3), otio_version="0.17.0", kdenlive=None)
    assert isinstance(report, DoctorReport)
    assert report.status == "healthy"
    assert report.ffmpeg.version == "6.1.1"
    assert report.ffmpeg.executable == "ffmpeg"
    assert report.ffmpeg.transcode.status == "ok"
    payload = report.model_dump_json()
    assert "/private" not in payload
    assert "secret stderr" not in payload


def test_python_313_is_supported():
    report = run_doctor(runner=Runner(), python_version=(3, 13, 1), otio_version="0.17.0", kdenlive=None)
    assert report.status == "healthy"
    assert report.python.status == "ok"
    assert "python_unsupported" not in report.issues


def test_missing_ffmpeg_is_blocked_with_one_repair_path():
    report = run_doctor(runner=Runner(missing=("ffmpeg", "ffprobe")), python_version=(3, 12, 3), otio_version="0.17.0", kdenlive=None)
    assert report.status == "blocked"
    assert report.issues == ("ffmpeg_missing", "ffprobe_missing")
    assert report.repair == "Install FFmpeg >=6.1 (including ffprobe), then rerun openclaw-media doctor --json."


def test_unsupported_python_is_explicit_and_kdenlive_optional():
    report = run_doctor(runner=Runner(missing=("kdenlive",)), python_version=(3, 11, 9), otio_version="0.17.0", kdenlive=None)
    assert report.status == "blocked"
    assert report.python.status == "unsupported"
    assert report.kdenlive.status == "not_installed"
    assert report.issues == ("python_unsupported",)


def test_cli_doctor_json_returns_machine_readable_exit_status(monkeypatch, capsys):
    monkeypatch.setattr(cli, "run_doctor", lambda: run_doctor(runner=Runner(), python_version=(3, 12, 3), otio_version="0.17.0", kdenlive=None))
    assert cli.main(["doctor", "--json"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "healthy"
    assert output["schema_version"] == 1


def test_cli_help_exposes_doctor_and_plain_command_uses_the_same_report(monkeypatch, capsys):
    monkeypatch.setattr(cli, "run_doctor", lambda: run_doctor(runner=Runner(), python_version=(3, 12, 3), otio_version="0.17.0", kdenlive=None))
    assert "doctor" in cli.build_parser("0.2.0").format_help()
    assert cli.main(["doctor"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "healthy"
    assert output["schema_version"] == 1


def test_cli_doctor_rejects_unknown_options(capsys):
    assert cli.main(["doctor", "--unknown"]) == 2
    assert "unrecognized arguments" in capsys.readouterr().err


def test_ffprobe_minimum_and_issue_specific_repair():
    class OldProbe(Runner):
        def run(self, command):
            if command[:2] == ["ffprobe", "-version"]:
                return (0, "ffprobe version 5.0.0", "")
            return super().run(command)

    report = run_doctor(runner=OldProbe(), python_version=(3, 12, 3), otio_version="0.17.0", kdenlive=None)
    assert report.issues == ("ffprobe_version_unsupported",)
    assert report.repair == "Install ffprobe >=6.1, then rerun openclaw-media doctor --json."


def test_default_otio_and_optional_kdenlive_discovery(monkeypatch):
    monkeypatch.setattr(doctor_module, "distribution_version", lambda name: "0.17.0")
    runner = Runner(missing=("kdenlive",))
    report = run_doctor(runner=runner, python_version=(3, 12, 3))
    assert report.opentimelineio.status == "ok"
    assert report.kdenlive.status == "not_installed"


def test_runner_exceptions_are_sanitized():
    report = run_doctor(runner=FailingRunner(), python_version=(3, 12, 3), otio_version="0.17.0", kdenlive=None)
    assert "ffprobe_unavailable" in report.issues
    payload = report.model_dump_json()
    assert "sk-secret" not in payload
    assert "private.example" not in payload
