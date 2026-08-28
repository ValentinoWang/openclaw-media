from __future__ import annotations

import unittest

from openclaw_app.router.commercial_delivery import CommercialDeliveryMixin


class CommercialDeliveryReplyTest(unittest.TestCase):
    def test_success_reply_directs_user_to_review_the_draft_without_write_details(self) -> None:
        reply = CommercialDeliveryMixin._commercial_delivery_success_reply(
            "https://example.feishu.cn/docx/draft",
            [],
        )

        self.assertIn("初稿链接", reply)
        self.assertIn("下一步：请打开初稿核对内容", reply)
        self.assertNotIn("写入字段", reply)
        self.assertNotIn("多维表记录", reply)

    def test_failure_reply_is_actionable_and_hides_raw_failure_details(self) -> None:
        reply = CommercialDeliveryMixin._commercial_delivery_failure_reply(
            "commercial_delivery_failed",
            "HTTP 403 permission readback failed",
        )

        self.assertIn("商单交付未完成", reply)
        self.assertIn("请稍后重试原始需求", reply)
        self.assertNotIn("commercial_delivery_failed", reply)
        self.assertNotIn("HTTP 403", reply)
        self.assertNotIn("permission readback failed", reply)
