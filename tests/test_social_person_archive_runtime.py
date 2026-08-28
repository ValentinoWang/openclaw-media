from __future__ import annotations

import json
import subprocess
from pathlib import Path

from openclaw_app.models.message import Message
from openclaw_app.router.social_archive import SocialArchiveMixin
from openclaw_app.services.archive_service import ArchiveService


def test_social_person_archive_uses_configured_profile_runtime(tmp_path, monkeypatch) -> None:
    script = tmp_path / "person-profile-skill" / "tools" / "person_archive.py"
    script.parent.mkdir(parents=True)
    script.write_text(
        "import argparse\nparser = argparse.ArgumentParser()\nparser.add_argument('--person')\nparser.parse_args()\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("SOCIAL_BOT_ROOT", str(tmp_path))
    router = SocialArchiveMixin()

    assert router._social_root() == tmp_path

    result = subprocess.run(
        ["python3", str(script), "--help"],
        check=False,
        text=True,
        capture_output=True,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert "--person PERSON" in result.stdout


def test_social_archive_keeps_raw_metadata_in_internal_artifact(tmp_path, monkeypatch) -> None:
    class Router(SocialArchiveMixin):
        pass

    router = Router()
    router.workspace_root = tmp_path
    router.archive_service = ArchiveService(tmp_path)
    raw_body = "敏感原文：请勿出现在用户档案"
    raw_metadata = {"ok": False, "reason": "内部模型回执", "evidence": "敏感证据"}
    monkeypatch.setattr(router, "_extract_social_metadata_with_llm", lambda *_args, **_kwargs: raw_metadata)

    result = router.handle_社交(Message(entry_tag="社交", raw_text=raw_body, body=raw_body))

    markdown = Path(result.local_path).read_text(encoding="utf-8")
    artifact = json.loads(Path(result.extra["internal_artifact"]).read_text(encoding="utf-8"))
    assert raw_body not in markdown
    assert "敏感证据" not in markdown
    assert "LLM元数据抽取" not in markdown
    assert artifact["message"] == raw_body
    assert artifact["metadata"] == raw_metadata


def test_social_archive_reply_does_not_echo_chat_transcript(tmp_path) -> None:
    router = SocialArchiveMixin()
    transcript = tmp_path / "chat-transcript.md"
    transcript.write_text("私密聊天原文", encoding="utf-8")

    summary = router._social_archive_reply_summary(
        Message(entry_tag="社交", raw_text="", body=""),
        {"chat_batch": {"ok": True, "transcript_path": str(transcript)}},
    )

    assert "私密聊天原文" not in summary
    assert "原始文字稿仅保存在内部事实归档中" in summary
