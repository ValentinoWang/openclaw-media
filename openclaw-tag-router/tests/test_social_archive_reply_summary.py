from pathlib import Path

from openclaw_app.models.message import Message
from openclaw_app.router.social_archive import SocialArchiveMixin


def test_social_archive_reply_summary_fails_closed_without_material_content(tmp_path) -> None:
    archive_path = tmp_path / "archive.md"
    archive_path.write_text(
        "\n".join(
            (
                "## 001｜【人物照片】2026-06-13｜空记录",
                "",
                "> 待归入本表的提纯材料如下。后续编辑时应拆成逐行聊天记录、事实摘要和分析证据；原始音频/截图/图片不进入档案。",
                "",
                "| 日期/时间 | 发言人 | 内容 | 备注 |",
            )
        ),
        encoding="utf-8",
    )

    summary = SocialArchiveMixin()._social_archive_reply_summary(
        Message(entry_tag="社交", raw_text="不应作为摘要回退", body="不应作为摘要回退"),
        {"archive_path": str(archive_path)},
    )

    assert summary == ""


def test_social_archive_reply_summary_fails_closed_when_archive_cannot_be_read(tmp_path) -> None:
    summary = SocialArchiveMixin()._social_archive_reply_summary(
        Message(entry_tag="社交", raw_text="", body=""),
        {"archive_path": str(tmp_path)},
    )

    assert summary == ""
