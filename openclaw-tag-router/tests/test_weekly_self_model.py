from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from openclaw_app.models.message import Message
from openclaw_app.router.weekly_self_model import WeeklySelfModelMixin
from openclaw_app.services.archive_service import ArchiveService


class WeeklySelfModelHarness(WeeklySelfModelMixin):
    def __init__(self, workspace: Path) -> None:
        self.timezone = "Asia/Shanghai"
        self.archive_service = ArchiveService(workspace)


class WeeklySelfModelTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="weekly-self-model-"))
        self.archive_root = self.tmp / "Archieve"
        self.draft_dir = self.tmp / "自我模型" / "周记整理"
        self.archive_root.mkdir(parents=True)
        os.environ["OPENCLAW_WEEKLY_ARCHIVE_ROOT"] = str(self.archive_root)
        os.environ["OPENCLAW_SELF_MODEL_WEEKLY_DIR"] = str(self.draft_dir)
        self.harness = WeeklySelfModelHarness(self.tmp / "workspace")

    def tearDown(self) -> None:
        os.environ.pop("OPENCLAW_WEEKLY_ARCHIVE_ROOT", None)
        os.environ.pop("OPENCLAW_SELF_MODEL_WEEKLY_DIR", None)
        shutil.rmtree(self.tmp)

    def _message(self, tag: str, body: str, created_at: str) -> Message:
        return Message(
            entry_tag=tag,
            raw_text=f"【{tag}】{body}",
            body=body,
            source="feishu",
            chat_type="private",
            created_at=datetime.fromisoformat(created_at).replace(tzinfo=ZoneInfo("Asia/Shanghai")),
            metadata={"account_id": "daily"},
        )

    def test_weekly_self_model_uses_selected_sections_and_daily_archive(self) -> None:
        (self.archive_root / "20260525-20260531.md").write_text(
            """# 知识

- K12 教育 AI 产品需要把学生训练反馈讲给家长听。

# 内容

- 清华小王冲短跑一级，可以把体育 AI 创业讲成 Vlog 主线。

# 开发

<!-- codex-dev-review:usage:start -->
开发用量汇总不应该进入自我模型
<!-- codex-dev-review:usage:end -->
""",
            encoding="utf-8",
        )
        self.harness.archive_service.save_archive(
            self._message("待办", "2026-05-30 前完成租房小红书帖子", "2026-05-30T22:45:00"),
            "待办：完成租房小红书帖子",
            [("原始内容", "【待办】2026-05-30 前完成租房小红书帖子")],
        )

        result = self.harness.handle_周记(self._message("周记", "20260525-20260531", "2026-05-31T22:00:00"))

        self.assertTrue(result.ok)
        self.assertEqual(result.status, "draft")
        draft = Path(result.extra["drafts"][0]["draft_path"]).read_text(encoding="utf-8")
        self.assertIn("教育 AI 创业与产品方向", draft)
        self.assertIn("体育 AI 创业与产品方向", draft)
        self.assertIn("内容/IP 与账号定位", draft)
        self.assertIn("生活节奏、执行偏好、时间管理", draft)
        self.assertIn("完成租房小红书帖子", draft)
        self.assertNotIn("开发用量汇总", draft)

    def test_weekly_self_model_default_week_is_monday_to_sunday(self) -> None:
        (self.archive_root / "20260525-20260531.md").write_text("# 认知\n\n- AI 教育产品要保留阶段反馈。\n", encoding="utf-8")

        result = self.harness.handle_周记(self._message("周记", "", "2026-05-31T22:00:00"))

        self.assertTrue(result.ok)
        self.assertEqual(result.extra["drafts"][0]["week"], "20260525-20260531")
        self.assertTrue(Path(result.extra["drafts"][0]["draft_path"]).exists())


if __name__ == "__main__":
    unittest.main()
