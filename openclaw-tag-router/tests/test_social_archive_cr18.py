from openclaw_app.models.message import Message
from openclaw_app.router.social_archive import SocialArchiveMixin


def test_non_chat_summary_does_not_read_raw_archive_markdown(tmp_path) -> None:
    archive_path = tmp_path / "archive.md"
    archive_path.write_text(
        "## 001\n\n```json\n{\"provider\": \"openai\", \"status\": \"done\"}\n```\n"
        "RuntimeError: provider response\n",
        encoding="utf-8",
    )

    summary = SocialArchiveMixin()._social_archive_reply_summary(
        Message(entry_tag="社交", raw_text="原始输入", body="原始输入"),
        {"archive_path": str(archive_path)},
    )

    assert summary == ""


def test_chat_summary_is_human_receipt_without_machine_payload() -> None:
    summary = SocialArchiveMixin()._social_archive_reply_summary(
        Message(entry_tag="社交", raw_text="截图", body="截图"),
        {"chat_batch": {"ok": True, "json_path": "/internal/chat-analysis.json"}},
    )

    assert summary == "已完成聊天材料提取与关系事实整理，原始文字稿仅保存在内部事实归档中。"
    assert "json" not in summary.lower()
    assert "provider" not in summary.lower()
