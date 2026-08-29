from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from runtime.cli import selfmedia
from selfmedia.context import build_media_context


TENANT_ID = "00000000-0000-4000-8000-000000000101"


class DailyPollTenantFlowTests(unittest.TestCase):
    def test_install_cron_rejects_non_daily_cron_expression(self) -> None:
        with self.assertRaisesRegex(SystemExit, "minute/hour"):
            selfmedia._systemd_calendar("*/15 * * * *")

    def test_cli_help_does_not_advertise_legacy_host(self) -> None:
        parser = selfmedia.build_parser()
        help_text = parser.format_help()
        self.assertNotIn("/home/ubuntu", help_text)
        self.assertIn("systemd", help_text)
        self.assertIn("user timer", help_text)

    def test_runtime_documentation_uses_repository_relative_entrypoints(self) -> None:
        repository_root = Path(__file__).resolve().parents[1]
        architecture = (repository_root / "docs" / "architecture.md").read_text(encoding="utf-8")
        environment_example = (repository_root / "runtime" / "cli" / "selfmedia.env.example").read_text(encoding="utf-8")

        self.assertNotIn("/home/ubuntu", architecture)
        self.assertIn("runtime/cli/selfmedia.py", architecture)
        self.assertNotIn("/home/ubuntu", environment_example)
        self.assertIn("root `.env.local`", environment_example)

    def test_daily_poll_writes_only_to_the_requested_tenant_partition(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ,
            {"OPENCLAW_MEDIA_VAULT_ROOT": directory},
            clear=False,
        ), patch.object(selfmedia, "feishu_list_records", return_value=[]):
            payload = selfmedia.daily_poll(
                SimpleNamespace(
                    monitor_url="https://bitable.example.test/monitor",
                    report_url="",
                    view_id="",
                    limit=0,
                    require_feishu=False,
                    dry_run=True,
                    tenant_id=TENANT_ID,
                )
            )
            self.assertTrue(Path(payload["json_path"]).is_file())

        self.assertEqual(payload["account_count"], 0)
        self.assertIn(f"tenants/{TENANT_ID}/account_daily_runs", payload["json_path"])

    def test_daily_poll_dry_run_accepts_legacy_and_v2_account_fields(self) -> None:
        records = [
            {
                "record_id": "legacy-account",
                "fields": {
                    "账号名称": "旧账号",
                    "平台": "抖音",
                    "近期作品链接": [{"link": "https://www.douyin.com/video/legacy"}],
                    "启用": True,
                },
            },
            {
                "record_id": "v2-account",
                "fields": {
                    "account_name": "新账号",
                    "platform": "小红书",
                    "urls": ["https://www.xiaohongshu.com/explore/current"],
                    "enabled": True,
                },
            },
        ]
        rows = [
            {
                "post_id": "post-1",
                "url": "https://example.test/post-1",
                "health_status": "ok",
                "like_count": 12,
                "collect_count": 3,
                "comment_count": 2,
                "share_count": 1,
            }
        ]
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ,
            {
                "OPENCLAW_MEDIA_VAULT_ROOT": directory,
                "FEISHU_ACCOUNT_REPORT_URL": "https://bitable.example.test/report-from-env",
            },
            clear=False,
        ), patch.object(selfmedia, "feishu_list_records", return_value=records), patch.object(
            selfmedia, "refresh_posts", return_value=rows
        ):
            payload = selfmedia.daily_poll(
                SimpleNamespace(
                    monitor_url="https://bitable.example.test/monitor",
                    report_url="",
                    view_id="",
                    limit=0,
                    require_feishu=True,
                    dry_run=True,
                    tenant_id=TENANT_ID,
                )
            )
            stored = json.loads(Path(payload["json_path"]).read_text(encoding="utf-8"))

        self.assertEqual(payload["account_count"], 2)
        self.assertEqual(payload["polled_account_count"], 2)
        self.assertEqual(stored["report_url"], "https://bitable.example.test/report-from-env")
        self.assertEqual([account["account_name"] for account in stored["accounts"]], ["旧账号", "新账号"])
        self.assertTrue(all(account["urls"] for account in stored["accounts"]))

    def test_daily_poll_artifact_is_consumed_only_by_its_tenant_context(self) -> None:
        other_tenant_id = "00000000-0000-4000-8000-000000000102"
        records = [
            {
                "record_id": "account-1",
                "fields": {
                    "账号名称": "主账号",
                    "平台": "小红书",
                    "近期作品链接": "https://example.test/post",
                    "启用": True,
                },
            }
        ]
        rows = [
            {
                "post_id": "post-1",
                "url": "https://example.test/post",
                "health_status": "ok",
                "like_count": 12,
                "collect_count": 3,
                "comment_count": 2,
                "share_count": 1,
                "top_comments": [{"text": "求这个训练方案"}],
            }
        ]
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ,
            {"OPENCLAW_MEDIA_VAULT_ROOT": directory},
            clear=False,
        ), patch.object(selfmedia, "feishu_list_records", return_value=records), patch.object(
            selfmedia, "refresh_posts", return_value=rows
        ):
            selfmedia.daily_poll(
                SimpleNamespace(
                    monitor_url="https://bitable.example.test/monitor",
                    report_url="",
                    view_id="",
                    limit=0,
                    require_feishu=False,
                    dry_run=True,
                    tenant_id=TENANT_ID,
                )
            )
            context = build_media_context(platform="小红书", account="主账号", tenant_id=TENANT_ID, root=directory)
            other_context = build_media_context(platform="小红书", account="主账号", tenant_id=other_tenant_id, root=directory)

        self.assertIn("求这个训练方案", context["prompt"])
        self.assertEqual(other_context["loaded"]["recent_daily_metrics"], 0)
        self.assertEqual(other_context["top_comments"], [])

    def test_daily_poll_persists_bounded_comments_into_review_memory(self) -> None:
        records = [
            {
                "record_id": "account-1",
                "fields": {
                    "账号名称": "主账号",
                    "平台": "小红书",
                    "近期作品链接": "https://example.test/post",
                    "启用": True,
                },
            }
        ]
        rows = [
            {
                "post_id": "post-1",
                "url": "https://example.test/post",
                "health_status": "ok",
                "captured_at": "2026-08-29T10:00:00+08:00",
                "like_count": 12,
                "collect_count": 3,
                "comment_count": 2,
                "share_count": 1,
                "top_comments": [{"text": f"评论{i}"} for i in range(7)],
            }
        ]
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ,
            {"OPENCLAW_MEDIA_VAULT_ROOT": directory, "SELFMEDIA_MEMORY_ROOT": directory},
            clear=False,
        ), patch.object(selfmedia, "feishu_list_records", return_value=records), patch.object(
            selfmedia, "refresh_posts", return_value=rows
        ), patch.object(selfmedia, "feishu_update_record"), patch.object(
            selfmedia, "write_feishu_records", return_value=["rec-report"]
        ):
            payload = selfmedia.daily_poll(
                SimpleNamespace(
                    monitor_url="https://bitable.example.test/monitor",
                    report_url="https://bitable.example.test/report",
                    view_id="",
                    limit=0,
                    require_feishu=False,
                    dry_run=False,
                    tenant_id=TENANT_ID,
                )
            )
            review_path = Path(directory) / "tenants" / TENANT_ID / "reviews.jsonl"
            review = json.loads(review_path.read_text(encoding="utf-8").splitlines()[0])

        assert payload["record_ids"] == ["rec-report"]
        assert review["source"] == "selfmedia:daily-poll"
        assert review["publish_url"] == "https://example.test/post"
        assert review["metrics"] == {"点赞": "12", "收藏": "3", "评论": "2", "分享": "1"}
        assert review["top_comments"] == [f"评论{i}" for i in range(5)]

    def test_daily_poll_requires_tenant_id_at_cli_boundary(self) -> None:
        parser = selfmedia.build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["daily-poll", "--monitor-url", "https://bitable.example.test/monitor"])

    def test_daily_poll_rejects_invalid_tenant_before_reading_feishu(self) -> None:
        with patch.object(selfmedia, "feishu_list_records", side_effect=AssertionError("must not read before tenant validation")):
            with self.assertRaisesRegex(Exception, "tenant_id"):
                selfmedia.daily_poll(
                    SimpleNamespace(
                        monitor_url="https://bitable.example.test/monitor",
                        report_url="",
                        view_id="",
                        limit=0,
                        require_feishu=False,
                        dry_run=True,
                        tenant_id="not-a-tenant",
                    )
                )

    def test_daily_poll_rejects_monitor_rows_without_explicit_enablement(self) -> None:
        records = [
            {
                "record_id": "account-without-enabled",
                "fields": {"账号名称": "主账号", "平台": "抖音", "近期作品链接": "https://example.test/post"},
            }
        ]
        with patch.object(selfmedia, "feishu_list_records", return_value=records), patch.object(
            selfmedia, "refresh_posts", side_effect=AssertionError("must not poll without explicit enablement")
        ):
            with self.assertRaisesRegex(SystemExit, "显式包含启用字段"):
                selfmedia.daily_poll(
                    SimpleNamespace(
                        monitor_url="https://bitable.example.test/monitor",
                        report_url="",
                        view_id="",
                        limit=0,
                        require_feishu=False,
                        dry_run=True,
                        tenant_id=TENANT_ID,
                    )
                )

    def test_daily_poll_rejects_profile_links_and_platform_mismatch(self) -> None:
        profile_record = [{
            "record_id": "profile-link",
            "fields": {
                "账号名称": "主账号",
                "平台": "抖音",
                "近期作品链接": "https://www.douyin.com/user/abc",
                "启用": True,
            },
        }]
        with patch.object(selfmedia, "feishu_list_records", return_value=profile_record):
            with self.assertRaisesRegex(SystemExit, "不能使用账号主页"):
                selfmedia.daily_poll(SimpleNamespace(
                    monitor_url="https://bitable.example.test/monitor",
                    report_url="",
                    view_id="",
                    limit=0,
                    require_feishu=False,
                    dry_run=True,
                    tenant_id=TENANT_ID,
                ))

        mismatch_record = [{
            "record_id": "mismatch-link",
            "fields": {
                "账号名称": "主账号",
                "平台": "抖音",
                "近期作品链接": "https://www.xiaohongshu.com/explore/65abc123456789",
                "启用": True,
            },
        }]
        with patch.object(selfmedia, "feishu_list_records", return_value=mismatch_record):
            with self.assertRaisesRegex(SystemExit, "平台不一致"):
                selfmedia.daily_poll(SimpleNamespace(
                    monitor_url="https://bitable.example.test/monitor",
                    report_url="",
                    view_id="",
                    limit=0,
                    require_feishu=False,
                    dry_run=True,
                    tenant_id=TENANT_ID,
                ))

    def test_install_cron_uses_current_python_and_script_with_tenant(self) -> None:
        captured: list[list[str]] = []
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(
                os.environ,
                {
                    "FEISHU_ACCOUNT_REPORT_URL": "https://bitable.example.test/report",
                    "OPENCLAW_USER_SYSTEMD_DIR": directory,
                },
                clear=False,
            ), patch.object(
                selfmedia, "run_command", side_effect=lambda command, *_args, **_kwargs: captured.append(command) or {"ok": True}
            ):
                result = selfmedia.install_cron(
                    SimpleNamespace(
                        name="daily-test",
                        cron="0 8 * * *",
                        tz="Asia/Shanghai",
                        monitor_url="https://bitable.example.test/monitor",
                        report_url="",
                        disabled=False,
                        tenant_id=TENANT_ID,
                    )
                )
            self.assertTrue(result["ok"])
            service = Path(result["service_path"])
            timer = Path(result["timer_path"])
            self.assertTrue(service.is_file())
            self.assertTrue(timer.is_file())
            service_text = service.read_text(encoding="utf-8")
            self.assertIn(sys.executable, service_text)
            self.assertIn(str(Path(selfmedia.__file__).resolve()), service_text)
            self.assertIn(f"--tenant-id {TENANT_ID}", service_text)
            self.assertIn("--monitor-url https://bitable.example.test/monitor", service_text)
            self.assertNotIn("openclaw cron", service_text.lower())
            self.assertEqual(result["calendar"], "*-*-* 08:00:00")
            timer_text = timer.read_text(encoding="utf-8")
            self.assertIn("OnCalendar=*-*-* 08:00:00 Asia/Shanghai", timer_text)
            self.assertNotIn("Timezone=", timer_text)
            self.assertNotIn("bot_runtime", Path(selfmedia.__file__).read_text(encoding="utf-8"))
        self.assertEqual(captured[0][:3], ["systemctl", "--user", "daemon-reload"])
        self.assertEqual(captured[1][:4], ["systemctl", "--user", "enable", "--now"])

    def test_install_cron_rejects_missing_report_target(self) -> None:
        with patch.dict(os.environ, {"FEISHU_ACCOUNT_REPORT_URL": ""}, clear=False):
            with self.assertRaisesRegex(SystemExit, "refusing to register"):
                selfmedia.install_cron(
                    SimpleNamespace(
                        name="daily-test",
                        cron="0 8 * * *",
                        tz="Asia/Shanghai",
                        monitor_url="https://bitable.example.test/monitor",
                        report_url="",
                        disabled=False,
                        tenant_id=TENANT_ID,
                    )
                )

    def test_install_cron_rejects_missing_monitor_target(self) -> None:
        with patch.dict(os.environ, {"FEISHU_ACCOUNT_MONITOR_URL": "", "FEISHU_SELFMEDIA_ACCOUNT_MONITOR_URL": ""}, clear=False):
            with self.assertRaisesRegex(SystemExit, "FEISHU_ACCOUNT_MONITOR_URL"):
                selfmedia.install_cron(
                    SimpleNamespace(
                        name="daily-test",
                        cron="0 8 * * *",
                        tz="Asia/Shanghai",
                        monitor_url="",
                        report_url="https://bitable.example.test/report",
                        disabled=False,
                        tenant_id=TENANT_ID,
                    )
                )

    def test_install_cron_rejects_invalid_timezone(self) -> None:
        with self.assertRaisesRegex(SystemExit, "IANA timezone"):
            selfmedia._systemd_calendar("0 8 * * *", timezone="not-a-timezone")


if __name__ == "__main__":
    unittest.main()
