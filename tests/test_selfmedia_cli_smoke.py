from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from runtime.cli import selfmedia


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "runtime" / "cli" / "selfmedia.py"
TEST_TENANT_ID = "00000000-0000-4000-8000-000000000101"


def _run_cli(*args: str) -> dict[str, object]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    completed = subprocess.run(
        [sys.executable, str(CLI), *args],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
    payload = json.loads(completed.stdout)
    assert payload["ok"] is True
    assert payload["mode"] == "smoke"
    assert payload["write_policy"] == "no_feishu_write_no_llm_generation"
    return payload


def test_creation_cli_smoke_validates_canonical_entrypoint_without_llm() -> None:
    payload = _run_cli(
        "run",
        "creation",
        "--text",
        "【创作>抖音】平台=抖音 类型=视频 赛道=旅行 账号=主账号 主题=天水麦积山石窟毕业旅行避坑提问",
        "--smoke",
        "--limit",
        "5",
        "--tenant-id",
        TEST_TENANT_ID,
    )
    assert payload["module"] == "selfmedia.creation.workflow"
    assert payload["request"]["platform"] == "抖音"  # type: ignore[index]


def test_retired_material_creation_cli_is_not_exposed() -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    completed = subprocess.run(
        [sys.executable, str(CLI), "material-creation", "--text", "旧素材创作"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )

    assert completed.returncode != 0
    assert "invalid choice" in completed.stderr


def test_retired_creation_inspiration_cli_is_not_exposed() -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    completed = subprocess.run(
        [sys.executable, str(CLI), "creation-inspiration", "--text", "旧创作灵感"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )

    assert completed.returncode != 0
    assert "invalid choice" in completed.stderr


def test_deconstruct_cli_smoke_validates_url_and_route_without_llm() -> None:
    payload = _run_cli(
        "run",
        "deconstruct",
        "--text",
        "【拆解】https://v.douyin.com/fKD3JbS5aXk/ 【再创作】田径服转场金牌视频",
        "--smoke",
    )
    assert payload["module"] == "selfmedia.deconstruct.viral_content"
    assert payload["source_url"] == "https://v.douyin.com/fKD3JbS5aXk/"


def test_id_business_cli_smoke_validates_trigger_without_llm() -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "selfmedia.business.id_business",
            "ingest",
            "--text",
            "【商务>ID】小王 项目：HF绿氨糖",
            "--smoke",
            "--no-screenshot",
            "--tenant-id",
            TEST_TENANT_ID,
        ],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
    payload = json.loads(completed.stdout)
    assert payload["ok"] is True
    assert payload["mode"] == "smoke"
    assert payload["module"] == "selfmedia.business.id_business"
    assert payload["fields"]["作者ID"] == "小王"
    assert payload["fields"]["项目"] == "HF绿氨糖"


def _daily_poll_args(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "monitor_url": "https://bitable.example.test/monitor",
        "report_url": "",
        "view_id": "",
        "limit": 0,
        "require_feishu": False,
        "dry_run": True,
        "tenant_id": TEST_TENANT_ID,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_daily_poll_smoke_honors_feishu_required_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FEISHU_REQUIRED", "1")

    args = selfmedia.build_parser().parse_args(["daily-poll", "--tenant-id", TEST_TENANT_ID])

    assert args.require_feishu is True
    with pytest.raises(SystemExit, match="--require-feishu"):
        selfmedia.daily_poll(_daily_poll_args(dry_run=False))


def test_daily_poll_rejects_creator_profile_rows_without_feishu_write(monkeypatch: pytest.MonkeyPatch) -> None:
    update_calls: list[object] = []
    with patch.object(
        selfmedia,
        "feishu_list_records",
        return_value=[{"record_id": "rec_profile", "fields": {"creator_profile_id": "creator-1", "platform": "抖音"}}],
    ), patch.object(selfmedia, "feishu_update_record", side_effect=lambda *args, **kwargs: update_calls.append((args, kwargs))), patch.object(
        selfmedia, "refresh_posts", side_effect=AssertionError("v2 profile rows must not be polled")
    ):
        with pytest.raises(SystemExit, match="CreatorProfile"):
            selfmedia.daily_poll(_daily_poll_args())

    assert update_calls == []


def test_daily_poll_rejects_unclassified_rows_without_feishu_write() -> None:
    with patch.object(
        selfmedia,
        "feishu_list_records",
        return_value=[{"record_id": "rec_unknown", "fields": {"账号名称": "未分类账号", "平台": "抖音"}}],
    ), patch.object(selfmedia, "feishu_update_record", side_effect=AssertionError("unclassified rows must not be updated")):
        with pytest.raises(SystemExit, match="无法确认"):
            selfmedia.daily_poll(_daily_poll_args())


def test_daily_poll_report_is_chinese_and_redacts_runtime_exceptions(monkeypatch: pytest.MonkeyPatch) -> None:
    from tempfile import TemporaryDirectory

    with TemporaryDirectory() as directory:
        monkeypatch.setenv("OPENCLAW_MEDIA_VAULT_ROOT", directory)
        with patch.object(
            selfmedia,
            "feishu_list_records",
            return_value=[
                {
                    "record_id": "rec_monitor",
                    "fields": {"账号名称": "测试账号", "平台": "抖音", "近期作品链接": "https://example.test/post", "启用": True},
                }
            ],
        ), patch.object(
            selfmedia,
            "refresh_posts",
            side_effect=RuntimeError("Traceback (most recent call last):\n  File '/Users/example/private.py', line 1\nnetwork failure"),
        ), patch.object(selfmedia, "feishu_update_record", side_effect=AssertionError("dry run must not write Feishu")):
            payload = selfmedia.daily_poll(_daily_poll_args())

        report = Path(payload["report_path"]).read_text(encoding="utf-8")

    assert payload["errors"] == [{"account_name": "测试账号", "error": "轮询失败，请检查运行日志。"}]
    assert payload["status"] == "error"
    assert payload["completion_status"] == "error"
    assert payload["ok"] is False
    assert "## 轮询失败" in report
    assert "轮询失败，请检查运行日志。" in report
    assert "总互动" in report
    assert "/Users/example" not in report
    assert "Traceback" not in report


def test_daily_poll_redacts_monitor_status_write_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    from tempfile import TemporaryDirectory

    records = [
        {
            "record_id": "rec_monitor",
            "fields": {"账号名称": "测试账号", "平台": "抖音", "近期作品链接": "", "启用": True},
        }
    ]
    with TemporaryDirectory() as directory:
        monkeypatch.setenv("OPENCLAW_MEDIA_VAULT_ROOT", directory)
        with patch.object(selfmedia, "feishu_list_records", return_value=records), patch.object(
            selfmedia,
            "feishu_update_record",
            side_effect=RuntimeError("Traceback: /Users/example/private.py"),
        ):
            with pytest.raises(SystemExit, match="账号监控表状态写入失败：轮询失败，请检查运行日志。") as exc_info:
                selfmedia.daily_poll(_daily_poll_args(dry_run=False))

    assert "/Users/example" not in str(exc_info.value)


def test_daily_poll_feishu_fields_are_compact_and_user_facing(monkeypatch: pytest.MonkeyPatch) -> None:
    from tempfile import TemporaryDirectory

    written: list[dict[str, object]] = []
    rows = [
        {
            "post_id": "post-1",
            "url": "https://example.test/post-1",
            "health_status": "error",
            "failure_reason": "Traceback: /Users/example/private.py",
            "like_count": 12,
            "collect_count": 3,
            "comment_count": 2,
            "share_count": 1,
            "top_comments": [{"text": "这条怎么练", "author": "不应写入"}],
            "raw_fields": {"private": "不应写入"},
            "raw_stats": {"secret": "不应写入"},
        }
    ]
    with TemporaryDirectory() as directory:
        monkeypatch.setenv("OPENCLAW_MEDIA_VAULT_ROOT", directory)
        with patch.object(
            selfmedia,
            "feishu_list_records",
            return_value=[
                {
                    "record_id": "rec_monitor",
                    "fields": {"账号名称": "测试账号", "平台": "抖音", "近期作品链接": "https://example.test/post", "启用": True},
                }
            ],
        ), patch.object(selfmedia, "refresh_posts", return_value=rows), patch.object(selfmedia, "feishu_update_record"), patch.object(
            selfmedia,
            "write_feishu_records",
            side_effect=lambda _url, records, **_kwargs: written.extend(records) or ["rec_report"],
        ):
            payload = selfmedia.daily_poll(_daily_poll_args(dry_run=False, report_url="https://bitable.example.test/report"))

    assert payload["record_ids"] == ["rec_report"]
    assert len(written) == 1
    fields = written[0]
    details = fields["详情JSON"]
    assert fields["状态"] == "轮询失败"
    assert fields["失败原因"] == "轮询失败，请检查运行日志。"
    assert fields["决策"] == "继续观察"
    assert fields["报告路径"] == Path(payload["report_path"]).name
    assert details["高价值评论原话"] == ["这条怎么练"]
    serialized = json.dumps(fields, ensure_ascii=False)
    assert "raw_fields" not in serialized
    assert "raw_stats" not in serialized
    assert "/Users/example" not in serialized


def test_daily_poll_marks_unconfigured_feishu_report_as_unsuccessful(monkeypatch: pytest.MonkeyPatch) -> None:
    from tempfile import TemporaryDirectory

    with TemporaryDirectory() as directory:
        monkeypatch.setenv("OPENCLAW_MEDIA_VAULT_ROOT", directory)
        with patch.object(
            selfmedia,
            "feishu_list_records",
            return_value=[
                {
                    "record_id": "rec_monitor",
                    "fields": {
                        "账号名称": "测试账号",
                        "平台": "抖音",
                        "近期作品链接": "https://example.test/post",
                        "启用": True,
                    },
                }
            ],
        ), patch.object(
            selfmedia,
            "refresh_posts",
            return_value=[
                {
                    "post_id": "post-1",
                    "url": "https://example.test/post",
                    "health_status": "ok",
                    "like_count": 1,
                }
            ],
        ), patch.object(selfmedia, "feishu_update_record"):
            payload = selfmedia.daily_poll(_daily_poll_args(dry_run=False, report_url=""))

    assert payload["ok"] is False
    assert payload["record_ids"] == []
    assert payload["feishu"] == "未配置飞书日报表，未写入跨平台记录"


def test_daily_poll_empty_table_is_explicitly_unsuccessful_but_writes_dry_run_artifacts(monkeypatch: pytest.MonkeyPatch) -> None:
    from tempfile import TemporaryDirectory

    with TemporaryDirectory() as directory:
        monkeypatch.setenv("OPENCLAW_MEDIA_VAULT_ROOT", directory)
        with patch.object(selfmedia, "feishu_list_records", return_value=[]), patch.object(
            selfmedia, "refresh_posts", side_effect=AssertionError("empty table must not poll")
        ):
            payload = selfmedia.daily_poll(_daily_poll_args())
        assert Path(payload["json_path"]).is_file()
        assert Path(payload["report_path"]).is_file()

    assert payload["ok"] is False
    assert payload["status"] == "ok_empty"
    assert payload["completion_status"] == "ok_empty"
    assert payload["account_count"] == 0
    assert payload["enabled_account_count"] == 0
    assert payload["polled_account_count"] == 0


def test_daily_poll_all_disabled_accounts_are_explicitly_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    from tempfile import TemporaryDirectory

    records = [
        {
            "record_id": "disabled-account",
            "fields": {"账号名称": "停用账号", "平台": "抖音", "近期作品链接": "https://example.test/post", "启用": False},
        }
    ]
    with TemporaryDirectory() as directory:
        monkeypatch.setenv("OPENCLAW_MEDIA_VAULT_ROOT", directory)
        with patch.object(selfmedia, "feishu_list_records", return_value=records), patch.object(
            selfmedia, "refresh_posts", side_effect=AssertionError("disabled accounts must not poll")
        ):
            payload = selfmedia.daily_poll(_daily_poll_args())

    assert payload["ok"] is False
    assert payload["status"] == "ok_empty"
    assert payload["completion_status"] == "ok_empty"
    assert payload["account_count"] == 1
    assert payload["enabled_account_count"] == 0
    assert payload["polled_account_count"] == 0


def test_daily_poll_enabled_account_without_urls_is_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from tempfile import TemporaryDirectory

    records = [
        {
            "record_id": "missing-url-account",
            "fields": {"账号名称": "缺链接账号", "平台": "抖音", "近期作品链接": "", "启用": True},
        }
    ]
    with TemporaryDirectory() as directory:
        monkeypatch.setenv("OPENCLAW_MEDIA_VAULT_ROOT", directory)
        with patch.object(selfmedia, "feishu_list_records", return_value=records), patch.object(
            selfmedia, "refresh_posts", side_effect=AssertionError("missing URLs must not poll")
        ):
            payload = selfmedia.daily_poll(_daily_poll_args())

    assert payload["ok"] is False
    assert payload["status"] == "error"
    assert payload["completion_status"] == "error"
    assert payload["enabled_account_count"] == 1
    assert payload["polled_account_count"] == 0
    assert payload["errors"] == [{"account_name": "缺链接账号", "error": "missing_urls"}]


def test_daily_poll_nonempty_success_reports_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    from tempfile import TemporaryDirectory

    records = [
        {
            "record_id": "active-account",
            "fields": {"账号名称": "正常账号", "平台": "抖音", "近期作品链接": "https://example.test/post", "启用": True},
        }
    ]
    rows = [{"post_id": "post-1", "url": "https://example.test/post", "health_status": "ok", "like_count": 1}]
    with TemporaryDirectory() as directory:
        monkeypatch.setenv("OPENCLAW_MEDIA_VAULT_ROOT", directory)
        with patch.object(selfmedia, "feishu_list_records", return_value=records), patch.object(
            selfmedia, "refresh_posts", return_value=rows
        ):
            payload = selfmedia.daily_poll(_daily_poll_args())

    assert payload["ok"] is True
    assert payload["status"] == "ok"
    assert payload["completion_status"] == "ok"
    assert payload["enabled_account_count"] == 1
    assert payload["polled_account_count"] == 1


def test_verify_schema_accepts_account_monitor_field_specs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(selfmedia, "feishu_bitable_refs", lambda url, token=None: ("app", "table", "token"))
    monkeypatch.setattr(selfmedia, "feishu_field_types", lambda app, table, token: dict(selfmedia.ACCOUNT_MONITOR_FIELD_SPECS))

    result = selfmedia.verify_schema("https://feishu.local/base/app?table=table")

    assert result["ok"] is True
    assert result["missing_fields"] == []
    assert result["mismatched_fields"] == []


def test_account_monitor_binding_requires_public_id_and_tenant_owned_record() -> None:
    record = {
        "record_id": "rec-bound",
        "fields": {
            "public_account_id": "acct_12345678",
            "账号名称": "展示名可变",
            "平台": "抖音",
            "近期作品链接": "https://example.test/post",
            "启用": True,
        },
    }
    calls: list[tuple[str, str]] = []

    def validator(tenant_id: str, public_account_id: str) -> bool:
        calls.append((tenant_id, public_account_id))
        return tenant_id == TEST_TENANT_ID and public_account_id == "acct_12345678"

    selfmedia.validate_account_monitor_records(
        [record], tenant_id=TEST_TENANT_ID, binding_validator=validator, require_binding=True
    )
    assert calls == [(TEST_TENANT_ID, "acct_12345678")]


def test_account_monitor_binding_rejects_missing_or_foreign_public_id() -> None:
    missing = {"record_id": "rec-missing", "fields": {"近期作品链接": "https://example.test/post", "启用": True}}
    with pytest.raises(SystemExit, match="public_account_id"):
        selfmedia.validate_account_monitor_records(
            [missing], tenant_id=TEST_TENANT_ID, binding_validator=lambda *_: True, require_binding=True
        )

    foreign = {"record_id": "rec-foreign", "fields": {"public_account_id": "acct_foreign", "近期作品链接": "https://example.test/post", "启用": True}}
    with pytest.raises(SystemExit, match="不属于当前租户"):
        selfmedia.validate_account_monitor_records(
            [foreign], tenant_id=TEST_TENANT_ID, binding_validator=lambda *_: False, require_binding=True
        )


def test_verify_schema_rejects_empty_table_without_records(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(selfmedia, "feishu_bitable_refs", lambda url, token=None: ("app", "empty", "token"))
    monkeypatch.setattr(selfmedia, "feishu_field_types", lambda app, table, token: {})

    result = selfmedia.verify_schema("https://feishu.local/base/app?table=empty")

    assert result["ok"] is False
    assert set(result["missing_fields"]) == set(selfmedia.ACCOUNT_MONITOR_FIELD_SPECS)


def test_verify_schema_reports_type_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    actual = dict(selfmedia.ACCOUNT_MONITOR_FIELD_SPECS)
    actual["启用"] = 1
    monkeypatch.setattr(selfmedia, "feishu_bitable_refs", lambda url, token=None: ("app", "table", "token"))
    monkeypatch.setattr(selfmedia, "feishu_field_types", lambda app, table, token: actual)

    result = selfmedia.verify_schema("https://feishu.local/base/app?table=table")

    assert result["ok"] is False
    assert result["mismatched_fields"] == [{"field": "启用", "expected_type": 7, "actual_type": 1}]


def test_daily_poll_parser_exposes_schema_verification_flag() -> None:
    args = selfmedia.build_parser().parse_args(
        ["daily-poll", "--monitor-url", "https://feishu.local/base/app?table=table", "--tenant-id", TEST_TENANT_ID, "--verify-schema"]
    )

    assert args.verify_schema is True
