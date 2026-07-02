from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

from openclaw_app.models.message import Message
from openclaw_app.router.deletion import DeletionMixin


class DeletionHarness(DeletionMixin):
    def __init__(self, workspace_root: Path):
        self.workspace_root = workspace_root

    def _creation_cleanup_script_path(self) -> Path:
        return Path(__file__).resolve()

    def _deletion_allowed_roots(self) -> list[Path]:
        return [self.workspace_root]


def deletion_message(body: str) -> Message:
    return Message(
        entry_tag="删除",
        raw_text=f"【删除】{body}",
        body=body,
        source="feishu",
        chat_type="private",
        created_at=datetime.now(),
        metadata={"account_id": "media"},
    )


def cleanup_stdout(mode: str = "dry_run") -> str:
    status = "deleted" if mode == "apply" else "planned"
    return json.dumps(
        {
            "mode": mode,
            "runs": [
                {
                    "run_id": "run_router_abc123",
                    "record_id": "rec1",
                    "warnings": [],
                    "actions": [
                        {"kind": "feishu_doc", "target": "https://example.feishu.cn/wiki/abc", "status": status, "detail": ""},
                        {"kind": "creation_run_record", "target": "rec1", "status": status, "detail": ""},
                    ],
                }
            ],
        },
        ensure_ascii=False,
    )


def write_frontmatter(path: Path, frontmatter: dict[str, object], body: str = "") -> None:
    lines = ["---"]
    for key, value in frontmatter.items():
        if isinstance(value, list):
            lines.append(f"{key}:")
            for item in value:
                lines.append(f"  - {item}")
        else:
            lines.append(f"{key}: {value}")
    lines.extend(["---", body])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


class DeletionMixinTest(unittest.TestCase):
    def test_missing_target_id_returns_usage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = DeletionHarness(Path(tmp)).handle_删除(deletion_message("帮我删一下"))

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "delete_missing_target_id")
        self.assertIn("20260412-030515-qq-灵感-0056", result.reply)
        self.assertIn("run_router_xxx", result.reply)

    def test_run_delete_is_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch(
            "openclaw_app.router.deletion_adapters.creation_run_adapter.subprocess.run",
            return_value=CompletedProcess(args=[], returncode=0, stdout=cleanup_stdout(), stderr=""),
        ) as run:
            result = DeletionHarness(Path(tmp)).handle_删除(deletion_message("run_router_abc123"))

        self.assertTrue(result.ok)
        self.assertEqual(result.status, "deletion_dry_run")
        self.assertNotIn("--apply", run.call_args.args[0])
        self.assertIn("删除预览", result.reply)

    def test_confirmed_run_delete_passes_apply(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch(
            "openclaw_app.router.deletion_adapters.creation_run_adapter.subprocess.run",
            return_value=CompletedProcess(args=[], returncode=0, stdout=cleanup_stdout("apply"), stderr=""),
        ) as run:
            result = DeletionHarness(Path(tmp)).handle_删除(deletion_message("确认删除 run_router_abc123"))

        self.assertTrue(result.ok)
        self.assertEqual(result.status, "deletion_applied")
        self.assertIn("--apply", run.call_args.args[0])
        self.assertIn("删除执行结果", result.reply)

    def test_archive_preview_keeps_files_and_lists_targets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target_id = "20260412-030515-qq-灵感-0056"
            inbox = root / "inbox" / "20260412-030515-qq-灵感-1566.json"
            archive = root / "archive" / "inspirations" / f"{target_id}.md"
            note = root / "obsidian" / "note.md"
            media_dir = root / "content_flow" / "asset-dir"
            inbox.parent.mkdir(parents=True)
            inbox.write_text("{}", encoding="utf-8")
            note.parent.mkdir(parents=True)
            note.write_text("note", encoding="utf-8")
            media_dir.mkdir(parents=True)
            (media_dir / "asset.json").write_text("{}", encoding="utf-8")
            write_frontmatter(
                archive,
                {"id": target_id, "entry_tag": "灵感", "obsidian_path": note, "media_dir": media_dir},
                "# test",
            )

            result = DeletionHarness(root).handle_删除(deletion_message(target_id))

            self.assertTrue(result.ok)
            self.assertEqual(result.status, "deletion_dry_run")
            self.assertTrue(inbox.exists())
            self.assertTrue(archive.exists())
            self.assertTrue(note.exists())
            self.assertTrue(media_dir.exists())
            self.assertIn("删除预览", result.reply)
            self.assertIn("本地归档", result.reply)
            self.assertIn("Obsidian会议纪要", result.reply)

    def test_archive_confirm_deletes_fixture_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target_id = "20260412-030515-qq-灵感-0056"
            inbox = root / "inbox" / "20260412-030515-qq-灵感-1566.json"
            archive = root / "archive" / "inspirations" / f"{target_id}.md"
            note = root / "obsidian" / "note.md"
            inbox.parent.mkdir(parents=True)
            inbox.write_text("{}", encoding="utf-8")
            note.parent.mkdir(parents=True)
            note.write_text("note", encoding="utf-8")
            write_frontmatter(archive, {"id": target_id, "entry_tag": "灵感", "obsidian_path": note}, "# test")

            result = DeletionHarness(root).handle_删除(deletion_message(f"确认删除 {target_id}"))

            self.assertTrue(result.ok)
            self.assertEqual(result.status, "deletion_applied")
            self.assertFalse(archive.exists())
            self.assertFalse(note.exists())
            self.assertIn("已删除", result.reply)

    def test_transcription_confirm_deletes_intermediate_products(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target_id = "20260412-030515-qq-转写-0056"
            archive = root / "archive" / "transcripts" / f"{target_id}.md"
            note = root / "obsidian" / "minutes.md"
            transcript = root / "obsidian" / "raw.md"
            text_json = root / "content_flow" / "text_transcripts" / "20260412-030515-qq-转写-abcd" / "task.json"
            post_json = root / "content_flow" / "postprocess" / "post.json"
            for path in (note, transcript, text_json, post_json):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("fixture", encoding="utf-8")
            write_frontmatter(
                archive,
                {
                    "id": target_id,
                    "entry_tag": "转写",
                    "obsidian_path": note,
                    "obsidian_transcript_path": transcript,
                    "postprocess_artifacts": [post_json],
                },
                "# transcript",
            )

            preview = DeletionHarness(root).handle_删除(deletion_message(target_id))

            self.assertTrue(preview.ok)
            self.assertTrue(note.exists())
            self.assertTrue(transcript.exists())
            self.assertTrue(text_json.exists())
            self.assertTrue(post_json.exists())

            applied = DeletionHarness(root).handle_删除(deletion_message(f"确认删除 {target_id}"))

            self.assertTrue(applied.ok)
            self.assertFalse(archive.exists())
            self.assertFalse(note.exists())
            self.assertFalse(transcript.exists())
            self.assertFalse(text_json.parent.exists())
            self.assertFalse(post_json.exists())
            self.assertIn("中间产物", applied.reply)


if __name__ == "__main__":
    unittest.main()
