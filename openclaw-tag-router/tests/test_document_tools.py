from __future__ import annotations

import unittest

from openclaw_app.router.document_tools import DocumentToolsMixin


class DocumentToolsHarness(DocumentToolsMixin):
    pass


class DocumentToolsTest(unittest.TestCase):
    def test_supplement_patch_heading_is_rejected(self) -> None:
        harness = DocumentToolsHarness()

        reason = harness._patch_like_supplement_reason(
            "# 原标题\n\n## 补充：AI 攻略 + 拍照教程 + 成果展示融合版\n\n新方案内容"
        )

        self.assertIn("文末补丁", reason)

    def test_stable_pending_info_heading_is_allowed(self) -> None:
        harness = DocumentToolsHarness()

        reason = harness._patch_like_supplement_reason(
            "# 再创作任务卡\n\n## 待补充信息\n\n- 到现场确认开放线路"
        )

        self.assertEqual(reason, "")

    def test_standalone_fusion_version_heading_is_rejected(self) -> None:
        harness = DocumentToolsHarness()

        reason = harness._patch_like_supplement_reason(
            "# 创作文档\n\n## AI 攻略 + 拍照教程 + 成果展示融合版\n\n新方案内容"
        )

        self.assertIn("融合版", reason)


if __name__ == "__main__":
    unittest.main()
