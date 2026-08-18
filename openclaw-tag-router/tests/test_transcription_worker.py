from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from transcription_worker import TranscriptionWorker, atomic_write_json, result_postprocess_resume_dir


FAKE_BRIDGE = r'''
import json
from pathlib import Path
import sys

payload = json.loads(sys.stdin.read())
metadata = payload["metadata"]
progress = Path(metadata["transcription_progress_path"])
progress.parent.mkdir(parents=True, exist_ok=True)
with progress.open("a", encoding="utf-8") as handle:
    if not payload["text"].startswith("【转写-文字】"):
        handle.write(json.dumps({"stage": "asr_started", "at": "2026-07-18T10:00:00+08:00"}) + "\n")
    handle.write(json.dumps({"stage": "postprocess_started", "at": "2026-07-18T10:00:01+08:00"}) + "\n")
mode = Path(sys.argv[2]).name
if mode == "fail-data":
    resume_dir = Path(sys.argv[2]) / "saved-postprocess"
    resume_dir.mkdir(parents=True, exist_ok=True)
    print(json.dumps({
        "ok": True,
        "status": "pending_manual",
        "reply": "Traceback private detail",
        "extra": {"postprocess": {"postprocess_artifacts": {"dir": str(resume_dir)}}}
    }))
else:
    print(json.dumps({
        "ok": True,
        "status": "archived",
        "reply": "转写完成\nObsidian：/tmp/meeting.md",
        "task_id": "archive-task",
        "local_path": "/tmp/archive.md",
        "received_text": payload["text"],
        "received_paths": metadata["downloaded_paths"],
        "received_source_message_id": metadata.get("source_message_id", ""),
        "received_message_result_id": metadata.get("message_result_id", ""),
        "received_resume_postprocess_dir": metadata.get("transcription_resume_postprocess_dir", "")
    }))
'''


class RecordingWorker(TranscriptionWorker):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.sent: list[str] = []

    def send_feishu(self, job: dict, text: str) -> dict[str, str]:
        self.sent.append(text)
        return {"message_id": f"om_test_{len(self.sent)}"}


class OrderRecordingWorker(TranscriptionWorker):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.processed_job_ids: list[str] = []

    def process_job(self, path: Path, job: dict) -> None:
        self.processed_job_ids.append(str(job["id"]))
        job["state"] = "completed"
        self.write_job(path, job)


class TranscriptionWorkerTest(unittest.TestCase):
    def test_empty_result_never_resets_resume_directory_to_current_working_directory(self) -> None:
        self.assertIsNone(result_postprocess_resume_dir({}))

    def make_job(self, root: Path, *, job_id: str = "tr-test") -> tuple[Path, Path]:
        jobs_root = root / "transcription-jobs"
        job_dir = jobs_root / job_id
        audio = root / f"{job_id}.m4a"
        audio.write_bytes(b"audio")
        progress = job_dir / "stage-events.jsonl"
        job = {
            "version": 1,
            "id": job_id,
            "batch_id": "tx-test",
            "state": "queued",
            "notification_state": "pending",
            "attempts": 0,
            "account_id": "daily",
            "source_message_id": "om_original_audio",
            "target": "user:ou_test",
            "progress_path": str(progress),
            "notifications": {},
            "payload": {
                "text": "【转写】关键词",
                "source": "feishu",
                "chat_type": "private",
                "metadata": {
                    "source_message_id": "om_original_audio",
                    "downloaded_paths": [str(audio)],
                    "transcription_attachments": [{"path": str(audio), "name": "讨论.m4a"}],
                },
            },
        }
        job_path = job_dir / "job.json"
        atomic_write_json(job_path, job)
        return job_path, audio

    def test_worker_sends_stages_persists_result_then_deletes_audio_and_notifies(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugin = root / "plugin"
            plugin.mkdir()
            (plugin / "bridge.py").write_text(FAKE_BRIDGE, encoding="utf-8")
            (plugin / "settings.yaml").write_text("{}\n", encoding="utf-8")
            job_path, audio = self.make_job(root)
            worker = RecordingWorker(
                data_root=root,
                plugin_root=plugin,
                settings_path=plugin / "settings.yaml",
                poll_seconds=0.01,
            )

            self.assertEqual(worker.run_once(), 1)

            job = json.loads(job_path.read_text(encoding="utf-8"))
            self.assertEqual(job["state"], "completed")
            self.assertEqual(job["notification_state"], "sent")
            self.assertFalse(audio.exists())
            self.assertEqual(len(worker.sent), 3)
            self.assertIn("录音转写中", worker.sent[0])
            self.assertIn("正在整理会议纪要", worker.sent[1])
            self.assertIn("转写任务完成", worker.sent[2])
            result = json.loads((job_path.parent / "result.json").read_text(encoding="utf-8"))
            self.assertEqual(result["received_source_message_id"], "om_original_audio")
            self.assertRegex(result["received_message_result_id"], r"^tr-test:[0-9a-f]{16}$")

    def test_worker_processes_jobs_in_persisted_fifo_order_not_random_job_id_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            later_path, _ = self.make_job(root, job_id="tr-a-later")
            earlier_path, _ = self.make_job(root, job_id="tr-z-earlier")
            later = json.loads(later_path.read_text(encoding="utf-8"))
            earlier = json.loads(earlier_path.read_text(encoding="utf-8"))
            later.update({"created_at": "2026-08-12T01:00:01+08:00", "enqueue_order": "0002"})
            earlier.update({"created_at": "2026-08-12T01:00:00+08:00", "enqueue_order": "0001"})
            atomic_write_json(later_path, later)
            atomic_write_json(earlier_path, earlier)
            worker = OrderRecordingWorker(data_root=root, plugin_root=root)

            self.assertEqual(worker.run_once(), 2)

            self.assertEqual(worker.processed_job_ids, ["tr-z-earlier", "tr-a-later"])

    def test_worker_failure_keeps_audio_and_never_exposes_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugin = root / "plugin"
            plugin.mkdir()
            (plugin / "bridge.py").write_text(FAKE_BRIDGE, encoding="utf-8")
            (plugin / "settings.yaml").write_text("{}\n", encoding="utf-8")
            job_path, audio = self.make_job(root, job_id="tr-fail")
            worker = RecordingWorker(
                data_root=root / "fail-data",
                plugin_root=plugin,
                settings_path=plugin / "settings.yaml",
                poll_seconds=0.01,
            )
            fail_job_path = worker.jobs_root / "tr-fail" / "job.json"
            fail_job_path.parent.mkdir(parents=True)
            fail_job_path.write_text(job_path.read_text(encoding="utf-8"), encoding="utf-8")

            self.assertEqual(worker.run_once(), 1)

            job = json.loads(fail_job_path.read_text(encoding="utf-8"))
            self.assertEqual(job["state"], "pending_manual")
            self.assertTrue(audio.exists())
            self.assertIn("TRANSCRIPTION_PIPELINE_FAILED", worker.sent[-1])
            self.assertNotIn("Traceback", worker.sent[-1])
            self.assertTrue(Path(job["resume_postprocess_dir"]).is_dir())

    def test_worker_passes_saved_postprocess_directory_into_retry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugin = root / "plugin"
            plugin.mkdir()
            (plugin / "bridge.py").write_text(FAKE_BRIDGE, encoding="utf-8")
            (plugin / "settings.yaml").write_text("{}\n", encoding="utf-8")
            job_path, _audio = self.make_job(root, job_id="tr-postprocess-resume")
            resume_dir = root / "saved-postprocess"
            resume_dir.mkdir()
            job = json.loads(job_path.read_text(encoding="utf-8"))
            job["resume_postprocess_dir"] = str(resume_dir)
            atomic_write_json(job_path, job)
            worker = RecordingWorker(
                data_root=root,
                plugin_root=plugin,
                settings_path=plugin / "settings.yaml",
                poll_seconds=0.01,
            )

            self.assertEqual(worker.run_once(), 1)

            result = json.loads((job_path.parent / "result.json").read_text(encoding="utf-8"))
            self.assertEqual(result["received_resume_postprocess_dir"], str(resume_dir))

    def test_worker_recovers_from_clean_transcripts_without_repeating_asr(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugin = root / "plugin"
            plugin.mkdir()
            (plugin / "bridge.py").write_text(FAKE_BRIDGE, encoding="utf-8")
            (plugin / "settings.yaml").write_text("{}\n", encoding="utf-8")
            job_path, _audio = self.make_job(root, job_id="tr-resume")
            clean_transcript = root / "clean-transcript.txt"
            clean_transcript.write_text("已完成的逐字稿", encoding="utf-8")
            job = json.loads(job_path.read_text(encoding="utf-8"))
            progress = Path(job["progress_path"])
            progress.parent.mkdir(parents=True, exist_ok=True)
            progress.write_text(
                json.dumps({"stage": "asr_started", "attachment_count": 1}) + "\n"
                + json.dumps(
                    {
                        "stage": "asr_file_completed",
                        "attachment_id": "audio-01",
                        "clean_transcript_path": str(clean_transcript),
                        "display_name": "讨论.m4a",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            worker = RecordingWorker(
                data_root=root,
                plugin_root=plugin,
                settings_path=plugin / "settings.yaml",
                poll_seconds=0.01,
            )

            self.assertEqual(worker.run_once(), 1)

            updated = json.loads(job_path.read_text(encoding="utf-8"))
            result = json.loads((job_path.parent / "result.json").read_text(encoding="utf-8"))
            self.assertEqual(updated["resume_mode"], "clean_transcripts")
            self.assertTrue(result["received_text"].startswith("【转写-文字】"))
            self.assertEqual(len(result["received_paths"]), 1)
            self.assertTrue(result["received_paths"][0].endswith("讨论.txt"))


if __name__ == "__main__":
    unittest.main()
