from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from _support import load_script_module


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "selfmedia" / "business" / "id_business.py"
MODULE = load_script_module("biz16_id_business", SCRIPT_PATH)

TENANT_ID = "00000000-0000-4000-8000-000000000101"
MONTH = date(2026, 8, 1)


def _record(record_id: str, **fields: object) -> dict[str, object]:
    return {
        "record_id": record_id,
        "fields": {
            "租户ID": TENANT_ID,
            "作者ID": record_id,
            "平台": "小红书",
            "账号名称": record_id,
            "图文报价": "1000",
            "视频报价": "",
            **fields,
        },
    }


def _runner(records: list[dict[str, object]], *, dry_run: bool = False, notify=None, update=None):
    notify = notify or (lambda _message, *, dry_run=False: {"ok": True})
    update = update or (lambda *_args, **_kwargs: None)
    with patch.dict(MODULE.os.environ, {"MEDIA_OS_BUSINESS_ACCOUNTS_V2_URL": "https://example.test/base/app?table=tbl"}, clear=False):
        with patch.object(MODULE, "feishu_tenant_access_token", return_value="token"):
            with patch.object(MODULE, "feishu_list_records", return_value=records):
                with patch.object(MODULE, "notify_social", side_effect=notify) as notify_mock:
                    with patch.object(MODULE, "feishu_update_record", side_effect=update) as update_mock:
                        result = MODULE.run_monthly_quote_reminder(
                            tenant_id=TENANT_ID,
                            today=MONTH,
                            dry_run=dry_run,
                        )
    return result, notify_mock, update_mock


def test_duplicate_month_is_skipped_without_delivery_or_writeback() -> None:
    result, notify, update = _runner([_record("already", **{"报价提醒月份": "2026-08"})])

    assert result["ok"] is True
    assert result["counts"] == {"success": 0, "skipped": 1, "failed": 0, "dry_run": 0}
    assert notify.call_count == 0
    assert update.call_count == 0


def test_successful_delivery_writes_month_and_chinese_success_status() -> None:
    result, notify, update = _runner([_record("success")])

    assert result["ok"] is True
    assert result["counts"]["success"] == 1
    notify.assert_called_once()
    update.assert_called_once_with(
        "https://example.test/base/app?table=tbl",
        "success",
        {"报价提醒月份": "2026-08", "报价提醒状态": "已发送"},
        specs=MODULE.FIELD_SPECS,
        token="token",
    )


def test_failed_delivery_does_not_write_back() -> None:
    result, notify, update = _runner([_record("failed")], notify=lambda _message, *, dry_run=False: {"ok": False})

    assert result["ok"] is False
    assert result["counts"] == {"success": 0, "skipped": 0, "failed": 1, "dry_run": 0}
    assert notify.call_count == 1
    assert update.call_count == 0


def test_skipped_delivery_does_not_write_back() -> None:
    result, _notify, update = _runner(
        [_record("skipped")],
        notify=lambda _message, *, dry_run=False: {"ok": False, "skipped": True, "reason": "missing_notify_target"},
    )

    assert result["ok"] is True
    assert result["counts"] == {"success": 0, "skipped": 1, "failed": 0, "dry_run": 0}
    assert update.call_count == 0


def test_dry_run_lists_due_record_without_delivery_or_writeback() -> None:
    result, notify, update = _runner([_record("dry")], dry_run=True)

    assert result["ok"] is True
    assert result["counts"] == {"success": 0, "skipped": 0, "failed": 0, "dry_run": 1}
    assert result["records"][0]["record_id"] == "dry"
    assert result["records"][0]["message"]
    assert notify.call_count == 0
    assert update.call_count == 0


def test_single_record_failure_continues_and_overall_result_is_not_success() -> None:
    def notify(message: str, *, dry_run: bool = False) -> dict[str, object]:
        if "作者ID：first" in message:
            raise RuntimeError("transport failure")
        return {"ok": True}

    result, _notify, update = _runner([_record("first"), _record("second")], notify=notify)

    assert result["ok"] is False
    assert result["counts"] == {"success": 1, "skipped": 0, "failed": 1, "dry_run": 0}
    assert update.call_count == 1
    assert result["records"][0]["status"] == "failed"
    assert result["records"][1]["status"] == "success"


def test_cli_has_remind_route_with_explicit_tenant() -> None:
    args = MODULE.build_parser().parse_args(["remind", "--tenant-id", TENANT_ID, "--dry-run"])

    assert args.command == "remind"
    assert args.tenant_id == TENANT_ID
    assert args.dry_run is True
    assert args.func is MODULE.remind
