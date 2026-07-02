from __future__ import annotations

import importlib.util
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


SCRIPT_PATH = Path("/home/ubuntu/selfmedia-tools/selfmedia/business/id_business.py")
SPEC = importlib.util.spec_from_file_location("id_business", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class IdBusinessLlmExtractionTest(unittest.TestCase):
    def _forbid_legacy_field_rules(self):
        return [
            patch.object(MODULE, "extract_labeled_fields", side_effect=AssertionError("must not use labeled-field parser")),
            patch.object(MODULE, "enrich_brief_structured_fields", side_effect=AssertionError("must not use brief field enricher")),
            patch.object(MODULE, "infer_author_id", side_effect=AssertionError("must not infer author id with rules")),
            patch.object(MODULE, "detect_platform_cn", side_effect=AssertionError("must not infer platform with rules")),
            patch.object(MODULE, "add_brief_fields", side_effect=AssertionError("must not build brief fields with rules")),
            patch.object(MODULE, "add_creator_confirmation_fields", side_effect=AssertionError("must not build confirmation fields with templates")),
            patch.object(MODULE, "build_brand_brief", side_effect=AssertionError("must not build brand brief with template")),
        ]

    def test_parse_business_text_uses_llm_fields_as_source_of_truth(self) -> None:
        calls: list[dict] = []

        def fake_llm(**kwargs):
            calls.append(kwargs)
            return {
                "status": "done",
                "confidence": 0.91,
                "reason": "字段明确",
                "evidence": "LLM evidence",
                "fields": {
                    "作者ID": "llm-author",
                    "账号名称": "LLM账号",
                    "平台": "小红书",
                    "项目": "LLM项目",
                    "品牌": "LLM品牌",
                    "产品": "LLM产品",
                    "主页链接": "https://xhslink.com/llm",
                    "图文报价": "3000",
                    "待补充字段": "视频报价",
                    "需反问博主字段": "视频报价",
                    "反问博主话术": "请确认视频报价。",
                    "给品牌方信息": "LLM 生成给品牌方信息。",
                },
                "pending_fields": ["视频报价"],
                "confirmation_fields": ["视频报价"],
            }

        patches = self._forbid_legacy_field_rules()
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

        parsed = MODULE.parse_business_text(
            "【商务>ID】\n作者ID：rule-author\n项目：规则项目\nhttps://xhslink.com/rule",
            llm_extractor=fake_llm,
        )

        self.assertEqual(len(calls), 1)
        self.assertEqual(parsed["status"], "done")
        fields = parsed["fields"]
        self.assertEqual(fields["作者ID"], "llm-author")
        self.assertEqual(fields["项目"], "LLM项目")
        self.assertEqual(fields["品牌"], "LLM品牌")
        self.assertEqual(fields["给品牌方信息"], "LLM 生成给品牌方信息。")
        self.assertNotIn("详情JSON", fields)
        self.assertEqual(parsed["details"]["llm"]["profile"], "content_cleaner")
        self.assertEqual(parsed["pending_fields"], ["视频报价"])

    def test_llm_pending_does_not_fall_back_to_rule_generated_fields(self) -> None:
        def pending_llm(**_kwargs):
            return {
                "status": "pending_manual",
                "confidence": 0.2,
                "reason": "LLM 无法确认商务主体字段",
                "fields": {},
                "pending_fields": ["作者ID", "报价"],
            }

        patches = self._forbid_legacy_field_rules()
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

        parsed = MODULE.parse_business_text(
            "【商务>ID】\n作者ID：rule-author\n项目：规则项目\n图文报价：500\nhttps://xhslink.com/rule",
            llm_extractor=pending_llm,
        )

        self.assertEqual(parsed["status"], "pending_manual")
        self.assertEqual(parsed["fields"]["最近状态"], "llm_pending_manual")
        self.assertEqual(parsed["fields"]["最近错误"], "LLM 无法确认商务主体字段")
        self.assertNotIn("作者ID", parsed["fields"])
        self.assertNotIn("项目", parsed["fields"])
        self.assertNotIn("图文报价", parsed["fields"])
        self.assertNotIn("给品牌方信息", parsed["fields"])

    def test_id_business_trigger_is_single_source(self) -> None:
        self.assertTrue(MODULE.has_id_business_trigger("【商务>ID】主页链接"))
        self.assertTrue(MODULE.has_id_business_trigger("【商务>小王】主页链接"))
        self.assertFalse(MODULE.has_id_business_trigger("【商务-ID】主页链接"))
        self.assertFalse(MODULE.has_id_business_trigger("【ID+商务】主页链接"))
        self.assertFalse(MODULE.has_id_business_trigger("【商务>ID>小王】主页链接"))
        self.assertFalse(MODULE.has_id_business_trigger("【商务-小王】主页链接"))
        self.assertEqual(MODULE.strip_trigger("【商务>小王】主页链接"), "作者ID：小王\n主页链接")
        self.assertEqual(MODULE.strip_trigger("【商务-ID】主页链接"), "【商务-ID】主页链接")

    def test_notify_social_without_target_never_calls_agent_fallback(self) -> None:
        env = {name: "" for name in MODULE.NOTIFY_TARGET_ENV_NAMES}
        with patch.dict(MODULE.os.environ, env, clear=False):
            with patch.object(MODULE.subprocess, "run", side_effect=AssertionError("must not call OpenClaw agent fallback")):
                result = MODULE.notify_social("请补充报价")

        self.assertFalse(result["ok"])
        self.assertTrue(result["skipped"])
        self.assertEqual(result["reason"], "missing_notify_target")
        self.assertEqual(MODULE.notify_delivery_status(result), "notify_skipped")

    def test_notify_social_with_target_uses_direct_message_send(self) -> None:
        env = {name: "" for name in MODULE.NOTIFY_TARGET_ENV_NAMES}
        env["ID_BUSINESS_SOCIAL_TARGET"] = "ou_test"
        calls: list[list[str]] = []

        class Completed:
            returncode = 0
            stdout = '{"status":"ok"}'
            stderr = ""

        def fake_run(cmd, **_kwargs):
            calls.append(cmd)
            self.assertEqual(cmd[:8], ["openclaw", "message", "send", "--channel", "feishu", "--account", "social", "--target"])
            self.assertNotIn("agent", cmd)
            return Completed()

        with patch.dict(MODULE.os.environ, env, clear=False):
            with patch.object(MODULE, "run_openclaw_message_with_watchdog", side_effect=fake_run):
                result = MODULE.notify_social("请补充报价")

        self.assertEqual(len(calls), 1)
        self.assertTrue(result["ok"])
        self.assertEqual(MODULE.notify_delivery_status(result), "sent")

    def test_openclaw_message_watchdog_kills_total_timeout(self) -> None:
        completed = MODULE.run_openclaw_message_with_watchdog(
            [sys.executable, "-c", "import time; time.sleep(2)"],
            timeout=1,
            env=os.environ.copy(),
        )

        self.assertEqual(completed.returncode, -9)
        self.assertIn("[watchdog] timeout_after=", completed.stderr)
        self.assertIn("limit=1s", completed.stderr)

    def test_history_lookup_fills_creator_identity_and_existing_quotes(self) -> None:
        fields = {
            "作者ID": "小王",
            "账号名称": "清华AI小王冲一级",
            "平台": "小红书",
            "待补充字段": "图文报价、视频报价",
            "需反问博主字段": "图文报价、视频报价",
        }
        profile_record = {
            "record_id": "rec_profile",
            "fields": {
                "creator_profile_id": "creator_xhs_396554716",
                "account_name": "清华AI小王冲一级",
                "platform": "小红书",
                "author_id": "小王",
                "identity_summary": "清华AI硕、跑步",
            },
        }
        business_record = {
            "record_id": "rec_business",
            "fields": {
                "business_account_id": "business_account_xhs_xiaowang",
                "author_id": "小王",
                "account_name_snapshot": "清华AI小王冲一级",
                "platform": "小红书",
                "current_image_quote_amount": "1000",
                "current_video_quote_amount": "1800",
            },
        }

        with patch.object(MODULE, "feishu_tenant_access_token", return_value="token"):
            with patch.object(MODULE, "feishu_list_records", side_effect=[[profile_record], [business_record]]):
                summary = MODULE.enrich_business_fields_from_history(
                    fields,
                    business_url="https://example.com/base?table=business",
                    creator_profiles_url="https://example.com/base?table=profiles",
                )

        remaining = MODULE.refresh_pending_fields_from_values(fields, {"pending_fields": ["图文报价", "视频报价"]})

        self.assertTrue(summary["creator_profiles"]["matched"])
        self.assertTrue(summary["business_accounts"]["matched"])
        self.assertEqual(fields["图文报价"], "1000")
        self.assertEqual(fields["视频报价"], "1800")
        self.assertEqual(remaining, [])
        self.assertNotIn("需反问博主字段", fields)

    def test_ai_reply_uses_current_table_fields_after_history_lookup(self) -> None:
        fields = {
            "作者ID": "小王",
            "账号名称": "清华AI小王冲一级",
            "平台": "小红书",
            "品牌": "华为",
            "图文报价": "1499",
            "视频报价": "2499",
            "待补充字段": "报备返点、具体档期",
        }
        history_lookup = {
            "creator_profiles": {"table": "06_达人账号档案", "matched": True, "record_id": "rec_profile"},
            "business_accounts": {"table": "05_BusinessAccounts_商务账号", "matched": True, "record_id": "rec_business", "copied_fields": ["图文报价", "视频报价"]},
        }

        def fake_generate(parts, provider, **_kwargs):
            payload_text = parts[1]["text"]
            self.assertEqual(provider, "fake")
            self.assertIn('"图文报价": "1499"', payload_text)
            self.assertIn('"视频报价": "2499"', payload_text)
            self.assertIn("报价按账号/平台级别使用", payload_text)
            self.assertIn("30%", parts[0]["text"])
            self.assertIn("后续怎么谈", parts[0]["text"])
            return {
                "status": "pending_manual",
                "reply": "小王小红书当前表内报价：图文 1499，视频 2499。后续先按 30% 返点锚定，再确认档期和授权。",
                "missing_fields": ["报备返点", "具体档期"],
                "evidence": "使用 05 商务账号表中账号级报价。",
            }

        settings = SimpleNamespace(enabled=True, provider="fake", max_chars=4000)
        with patch.object(MODULE, "load_content_cleaner_llm_settings", return_value=settings):
            with patch.object(MODULE, "generate_json_from_parts", side_effect=fake_generate):
                reply = MODULE.generate_business_reply_from_current_fields(
                    fields,
                    history_lookup=history_lookup,
                    pending_fields=["报备返点", "具体档期"],
                )

        self.assertEqual(reply["status"], "pending_manual")
        self.assertIn("图文 1499", reply["reply"])
        self.assertIn("视频 2499", reply["reply"])
        self.assertIn("后续", reply["reply"])

    def test_ingest_pending_llm_skips_business_model_write(self) -> None:
        args = SimpleNamespace(
            text="【商务>ID】\n作者ID：小王\n图文报价：1000",
            stdin=False,
            screenshot="",
            account_name="",
            profile_url="",
            brief_file=[],
            feishu_url="",
            no_screenshot=True,
            dry_run=False,
            require_feishu=True,
            notify_confirmation=False,
        )
        parsed = {
            "status": "pending_manual",
            "reason": "LLM 无法确认商务主体字段",
            "fields": {
                "最近状态": "llm_pending_manual",
                "最近错误": "LLM 无法确认商务主体字段",
                "待补充字段": "作者ID",
            },
            "details": {},
            "pending_fields": ["作者ID"],
            "confirmation_fields": [],
            "urls": [],
            "profile_urls": [],
            "brief_urls": [],
        }

        with patch.object(MODULE, "load_id_business_env_files"):
            with patch.object(MODULE, "parse_business_text", return_value=parsed):
                with patch.object(MODULE, "table_url_from_args", return_value=""):
                    with patch.object(MODULE, "creator_profile_table_url", return_value=""):
                        with patch.object(MODULE, "generate_business_reply_from_current_fields", return_value={"status": "pending_manual", "reason": "仍需人工确认"}):
                            with patch.object(MODULE, "save_local", return_value="/tmp/id-business-pending.json"):
                                with patch.object(MODULE, "write_business_model_v2", side_effect=AssertionError("must not write when LLM is pending/manual")):
                                    result = MODULE.ingest(args)

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "id_business_llm_pending_manual")
        self.assertEqual(result["feishu"], {"ok": False, "skipped": True, "reason": "llm_pending_manual"})
        self.assertEqual(result["local_path"], "/tmp/id-business-pending.json")


if __name__ == "__main__":
    unittest.main()
