from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from _support import load_script_module


ROOT = Path(__file__).resolve().parents[1]
DEPLOY_PATH = ROOT / "runtime" / "maintenance" / "deploy" / "deploy_openclaw_runtime.py"
TENANT_ID = "00000000-0000-4000-8000-000000000101"


def _load_module(name: str):
    return load_script_module(name, DEPLOY_PATH)


def test_deploy_root_and_preflight_scripts_are_repository_owned(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENCLAW_REPO_ROOT", "/tmp/not-the-repository")
    deploy = _load_module("wave7_rt10_root")

    assert deploy.REPO_ROOT == ROOT
    assert deploy.SELFMEDIA_CLI == ROOT / "runtime" / "cli" / "selfmedia.py"
    assert all(path.is_relative_to(ROOT) for path in deploy.PRE_DEPLOY_SCRIPTS)


def test_missing_preflight_script_fails_before_deployment(monkeypatch: pytest.MonkeyPatch) -> None:
    deploy = _load_module("wave7_rt10_preflight")
    monkeypatch.setattr(deploy, "PRE_DEPLOY_SCRIPTS", (ROOT / "scripts" / "quality" / "missing-guard.py",))

    with pytest.raises(SystemExit, match="missing repository preflight scripts"):
        deploy.assert_preflight_scripts()


def test_register_media_daily_poll_timer_invokes_repository_entrypoint(monkeypatch: pytest.MonkeyPatch) -> None:
    deploy = _load_module("wave7_rt10_register")
    commands: list[tuple[list[str], Path | None, int | None]] = []

    monkeypatch.setenv("OPENCLAW_MEDIA_DAILY_POLL_TENANT_ID", TENANT_ID)
    monkeypatch.setenv("OPENCLAW_MEDIA_DAILY_POLL_NAME", "media-daily-poll-test")
    monkeypatch.setenv("OPENCLAW_MEDIA_DAILY_POLL_CRON", "15 6 * * *")
    monkeypatch.setenv("OPENCLAW_MEDIA_DAILY_POLL_TZ", "Asia/Shanghai")
    monkeypatch.setattr(
        deploy,
        "run",
        lambda command, *, cwd=None, timeout=None: commands.append((command, cwd, timeout)) or SimpleNamespace(stdout="{}"),
    )

    registration = deploy.register_media_daily_poll_timer()

    assert commands == [
        (
            [
                deploy.sys.executable,
                str(ROOT / "runtime" / "cli" / "selfmedia.py"),
                "install-cron",
                "--name",
                "media-daily-poll-test",
                "--cron",
                "15 6 * * *",
                "--tz",
                "Asia/Shanghai",
                "--tenant-id",
                TENANT_ID,
            ],
            ROOT,
            90,
        )
    ]
    assert registration["tenant_id"] == TENANT_ID
    assert registration["timer_name"] == "media-daily-poll-test.timer"


def test_deploy_registers_daily_poll_before_reporting_success(monkeypatch: pytest.MonkeyPatch) -> None:
    deploy = _load_module("wave7_rt10_pipeline")
    calls: list[str] = []

    monkeypatch.setattr(deploy, "assert_preflight_scripts", lambda: calls.append("preflight"))
    monkeypatch.setattr(deploy, "sync_tag_router_source_to_active", lambda: calls.append("sync"))
    monkeypatch.setattr(deploy, "install_journal_systemd_units", lambda: calls.append("journals"))
    monkeypatch.setattr(deploy, "build_and_publish_bot_center", lambda: calls.append("bot-center"))
    monkeypatch.setattr(deploy, "assert_no_forbidden_openclaw_cron_jobs", lambda: calls.append("cron-check"))
    monkeypatch.setattr(
        deploy,
        "register_monthly_quote_reminder_timer",
        lambda: calls.append("monthly-quote") or {"timer_name": deploy.MONTHLY_QUOTE_REMINDER_TIMER},
    )
    monkeypatch.setattr(
        deploy,
        "register_media_daily_poll_timer",
        lambda: calls.append("daily-poll") or {"timer_name": "selfmedia-account-daily-poll.timer"},
    )

    result = deploy.deploy(restart_gateway=False, skip_guards=True)

    assert calls == ["preflight", "monthly-quote", "sync", "journals", "bot-center", "cron-check", "daily-poll"]
    assert result["media_daily_poll_timer"]["timer_name"] == "selfmedia-account-daily-poll.timer"
    assert result["monthly_quote_reminder_timer"]["timer_name"] == deploy.MONTHLY_QUOTE_REMINDER_TIMER
