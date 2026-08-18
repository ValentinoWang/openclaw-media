from __future__ import annotations

import unittest
from unittest.mock import patch

from openclaw_app.models.message import Message
from openclaw_app.router.business_vlog import BusinessVlogMixin


class BusinessReplyHarness(BusinessVlogMixin):
    pass


class BusinessVlogReplyTest(unittest.TestCase):
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
                    metadata={"tenant_id": "101"},
                )
            )

        self.assertTrue(result.ok)
        self.assertEqual(ingest.call_args.args[0].tenant_id, "101")
        self.assertEqual(result.reply, reply)
        self.assertNotIn("最近错误", result.reply)
        self.assertNotIn("商务>ID已写入", result.reply)


if __name__ == "__main__":
    unittest.main()
