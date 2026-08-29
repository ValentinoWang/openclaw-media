from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
DEPLOY_PATH = ROOT / "runtime" / "maintenance" / "deploy" / "deploy_openclaw_runtime.py"
TENANT_ID = "00000000-0000-4000-8000-000000000101"


def _load_module(name: str):
    spec = importlib.util.spec_from_file_location(name, DEPLOY_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_monthly_timer_units_are_explicit_and_point_to_remind() -> None:
    source_dir = ROOT / "openclaw-tag-router" / "deploy" / "systemd" / "user"
    timer = (source_dir / "openclaw-monthly-quote-reminder.timer").read_text(encoding="utf-8")
    service = (source_dir / "openclaw-monthly-quote-reminder.service").read_text(encoding="utf-8")

    assert "OnCalendar=*-*-01 00:00:00 Asia/Shanghai" in timer
    assert "@ID_BUSINESS_SCRIPT@ remind" in service
    assert "@ID_BUSINESS_SCRIPT@" in service
    assert "/home/ubuntu" not in service
    assert "@TENANT_ID@" in service


def test_register_monthly_timer_requires_tenant_and_registers_units(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    deploy = _load_module("biz16_deploy_register")
    monkeypatch.delenv("OPENCLAW_BUSINESS_QUOTE_REMINDER_TENANT_ID", raising=False)
    with pytest.raises(SystemExit, match="OPENCLAW_BUSINESS_QUOTE_REMINDER_TENANT_ID"):
        deploy.register_monthly_quote_reminder_timer()

    monkeypatch.setenv("OPENCLAW_BUSINESS_QUOTE_REMINDER_TENANT_ID", TENANT_ID)
    monkeypatch.setattr(deploy, "USER_SYSTEMD_DIR", tmp_path)
    commands: list[list[str]] = []
    monkeypatch.setattr(deploy, "run", lambda command, **_kwargs: commands.append(command) or SimpleNamespace(stdout="{}"))

    result = deploy.register_monthly_quote_reminder_timer()

    service = (tmp_path / deploy.MONTHLY_QUOTE_REMINDER_SERVICE).read_text(encoding="utf-8")
    assert TENANT_ID in service
    assert str(deploy.ID_BUSINESS_SCRIPT) in service
    assert "@ID_BUSINESS_SCRIPT@" not in service
    assert "--tenant-id " + TENANT_ID in service
    assert result["tenant_id"] == TENANT_ID
    assert commands[-2:] == [
        ["systemctl", "--user", "daemon-reload"],
        ["systemctl", "--user", "enable", "--now", deploy.MONTHLY_QUOTE_REMINDER_TIMER],
    ]


def test_deploy_main_invokes_monthly_registration(monkeypatch: pytest.MonkeyPatch) -> None:
    deploy = _load_module("biz16_deploy_pipeline")
    calls: list[str] = []
    monkeypatch.setattr(deploy, "assert_preflight_scripts", lambda: calls.append("preflight"))
    monkeypatch.setattr(deploy, "sync_tag_router_source_to_active", lambda: calls.append("sync"))
    monkeypatch.setattr(deploy, "install_journal_systemd_units", lambda: calls.append("journals"))
    monkeypatch.setattr(deploy, "build_and_publish_bot_center", lambda: calls.append("bot-center"))
    monkeypatch.setattr(deploy, "assert_no_forbidden_openclaw_cron_jobs", lambda: calls.append("cron-check"))
    monkeypatch.setattr(deploy, "register_media_daily_poll_timer", lambda: calls.append("daily-poll") or {})
    monkeypatch.setattr(
        deploy,
        "register_monthly_quote_reminder_timer",
        lambda: calls.append("monthly-quote") or {"timer_name": deploy.MONTHLY_QUOTE_REMINDER_TIMER},
    )

    result = deploy.deploy(restart_gateway=False, skip_guards=True)

    assert calls == ["preflight", "monthly-quote", "sync", "journals", "bot-center", "cron-check", "daily-poll"]
    assert result["monthly_quote_reminder_timer"]["timer_name"] == deploy.MONTHLY_QUOTE_REMINDER_TIMER


@pytest.mark.parametrize("skip_guards", [False, True])
def test_deploy_fails_closed_without_quote_reminder_tenant(
    monkeypatch: pytest.MonkeyPatch, skip_guards: bool
) -> None:
    deploy = _load_module(f"biz16_deploy_missing_tenant_{skip_guards}")
    monkeypatch.delenv("OPENCLAW_BUSINESS_QUOTE_REMINDER_TENANT_ID", raising=False)
    calls: list[str] = []
    monkeypatch.setattr(deploy, "assert_preflight_scripts", lambda: calls.append("preflight"))
    monkeypatch.setattr(deploy, "sync_tag_router_source_to_active", lambda: calls.append("sync"))

    with pytest.raises(SystemExit, match="OPENCLAW_BUSINESS_QUOTE_REMINDER_TENANT_ID"):
        deploy.deploy(restart_gateway=False, skip_guards=skip_guards)

    assert calls == ["preflight"]
