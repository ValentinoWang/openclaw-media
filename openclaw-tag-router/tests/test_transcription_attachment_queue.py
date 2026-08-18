from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from openclaw_app.models.message import Message
from openclaw_app.router.transcription_storage import TranscriptionStorageMixin


class AttachmentHarness(TranscriptionStorageMixin):
    def _conversation_context(self, _message: Message) -> dict[str, object]:
        return {}

    def _conversation_context_prompt(self, _message: Message) -> str:
        return ""


class TranscriptionAttachmentQueueTest(unittest.TestCase):
    def test_only_explicitly_associated_audio_paths_are_selected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            associated = root / "associated.m4a"
            unrelated = root / "unrelated.m4a"
            associated.write_bytes(b"associated")
            unrelated.write_bytes(b"unrelated")
            message = Message(
                entry_tag="转写",
                raw_text="【转写】确认 tx-test",
                body="确认 tx-test",
                source="feishu",
                created_at=datetime.now(),
                metadata={"downloaded_paths": [str(associated)]},
            )

            paths = AttachmentHarness()._transcription_attachment_paths(message)

            self.assertEqual(paths, [str(associated)])
            self.assertNotIn(str(unrelated), paths)

    def test_audio_directory_is_not_scanned_without_explicit_association(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "recent-but-unassociated.m4a"
            audio.write_bytes(b"audio")
            message = Message(
                entry_tag="转写",
                raw_text="【转写】",
                body="",
                source="feishu",
                created_at=datetime.now(),
                metadata={},
            )

            paths = AttachmentHarness()._transcription_attachment_paths(message)

            self.assertEqual(paths, [])


if __name__ == "__main__":
    unittest.main()
