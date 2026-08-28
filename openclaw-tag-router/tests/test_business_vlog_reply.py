from __future__ import annotations

import unittest
from unittest.mock import patch

from openclaw_app.models.message import Message
from openclaw_app.router.business_vlog import BusinessVlogMixin


class BusinessReplyHarness(BusinessVlogMixin):
    pass


class BusinessVlogReplyTest(unittest.TestCase):
    TENANT_ID = "00000000-0000-4000-8000-000000000101"

    def test_success_reply_only_exposes_counterparty_copy(self) -> None:
        reply = "老师您好，这里是清华AI小王冲一级博主\n视频报价：3499元\n返点：30%可谈"
        payload = {
            "ok": True,
            "fields": {
                "作者ID": "396554716",
                "账号名称": "清华AI小王冲一级",
                "平台": "小红书",
                "AI回复话术": reply,
                "最近错误": "小红书登录态无效，未生成有效主页截图",
            },
            "details": {"ai_reply": {"status": "done", "reply": reply}},
            "capture": {"ok": False, "status": "capture_auth_required"},
            "feishu": {"account_record_id": "rec_account"},
        }
        with patch(
            "selfmedia.business.id_business.ingest", return_value=payload,
        ) as ingest:
            result = BusinessReplyHarness().handle_id_business(
                Message(
                    entry_tag="商务>ID",
                    raw_text="【商务>ID】测试",
                    body="测试",
                    metadata={"tenant_id": self.TENANT_ID},
                )
            )

        self.assertTrue(result.ok)
        self.assertEqual(ingest.call_args.args[0].tenant_id, self.TENANT_ID)
        self.assertEqual(result.reply, reply)
        self.assertNotIn("最近错误", result.reply)
        self.assertNotIn("商务>ID已写入", result.reply)

    def test_fallback_reply_localizes_internal_status_values(self) -> None:
        payload = {
            "ok": True,
            "fields": {
                "作者ID": "396554716",
                "账号名称": "清华AI小王冲一级",
                "平台": "小红书",
                "反问博主状态": "pending",
            },
            "details": {},
            "capture": {"ok": False, "status": "capture_auth_required"},
            "feishu": {"account_record_id": "rec_account"},
        }
        with patch("selfmedia.business.id_business.ingest", return_value=payload):
            result = BusinessReplyHarness().handle_id_business(
                Message(
                    entry_tag="商务>ID",
                    raw_text="【商务>ID】测试",
                    body="测试",
                    metadata={"tenant_id": self.TENANT_ID},
                )
            )

        self.assertIn("截图状态：登录状态失效，待重新获取", result.reply)
        self.assertIn("反问状态：待确认", result.reply)
        self.assertNotIn("capture_auth_required", result.reply)
        self.assertNotIn("pending", result.reply)


if __name__ == "__main__":
    unittest.main()
