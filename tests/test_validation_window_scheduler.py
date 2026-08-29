from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from media_vault import MediaVault
from selfmedia.business.commercial_loop import CommercialLoopLedger
from selfmedia.review import data_review
from selfmedia.review.validation_window_scheduler import ValidationWindowScheduler


TENANT = "00000000-0000-4000-8000-000000000913"
OTHER_TENANT = "00000000-0000-4000-8000-000000000914"
PUBLISHED_URL = "https://creator.example.test/posts/one"
EVIDENCE_URL = "https://analytics.example.test/evidence/one"
PUBLISHED_AT = datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc)


def write_creation_run(root: str, run_id: str = "run_validation") -> None:
    MediaVault(tenant_id=TENANT, root=root).write_creation_run_artifacts(
        run_id,
        request={"platform": "抖音"},
        draft_output={
            "validation_targets": {
                "two_hour": ["收藏", "完播率"],
                "24h": ["分享"],
                "seven_day": ["新增关注"],
            },
            "publishing_pack": {"first_hour_action": "置顶提问并回复前十条评论"},
        },
    )


class ValidationWindowSchedulerTests(unittest.TestCase):
    def test_multi_window_schedule_is_idempotent_and_clock_injected(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            write_creation_run(root)
            scheduler = ValidationWindowScheduler(tenant_id=TENANT, root=root, clock=lambda: PUBLISHED_AT)
            first = scheduler.schedule_for_publication(
                creation_run_id="run_validation",
                published_url=PUBLISHED_URL,
                publication_evidence_uri=EVIDENCE_URL,
                publication_confirmed=True,
            )
            replay = scheduler.schedule_for_publication(
                creation_run_id="run_validation",
                published_url=PUBLISHED_URL,
                publication_evidence_uri=EVIDENCE_URL,
                publication_confirmed=True,
            )

            self.assertEqual(first["status"], "scheduled")
            self.assertEqual(len(first["tasks"]), 4)
            self.assertTrue(replay["replayed"])
            self.assertEqual([task["window"] for task in first["tasks"]], ["1h", "2h", "24h", "7d"])
            self.assertEqual(first["tasks"][1]["validation_targets"], ["收藏", "完播率"])
            self.assertEqual(first["tasks"][0]["due_at"], (PUBLISHED_AT + timedelta(hours=1)).isoformat())
            self.assertIn("回复【数据复盘】并附截图", first["tasks"][1]["reminder_text"])
            self.assertIn("收藏、完播率", first["tasks"][1]["reminder_text"])
            self.assertIn(PUBLISHED_URL, first["tasks"][1]["reminder_text"])
            self.assertIn("首小时动作", first["tasks"][0]["reminder_text"])
            self.assertEqual(len(scheduler.due_pending_windows(now=PUBLISHED_AT + timedelta(hours=2))), 2)

    def test_missing_confirmation_is_blocked_and_tenant_readback_is_isolated(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            write_creation_run(root)
            scheduler = ValidationWindowScheduler(tenant_id=TENANT, root=root, clock=lambda: PUBLISHED_AT)
            blocked = scheduler.schedule_for_publication(
                creation_run_id="run_validation",
                published_url=PUBLISHED_URL,
                publication_evidence_uri=EVIDENCE_URL,
                publication_confirmed=False,
            )

            self.assertEqual(blocked["status"], "blocked")
            self.assertEqual(blocked["blocking_reason"], "publication_confirmation_missing")
            missing_evidence = scheduler.schedule_for_publication(
                creation_run_id="run_validation",
                published_url=PUBLISHED_URL,
                publication_evidence_uri="",
                publication_confirmed=True,
            )
            self.assertEqual(missing_evidence["status"], "blocked")
            self.assertEqual(missing_evidence["blocking_reason"], "publication_external_evidence_missing")
            self.assertEqual(missing_evidence["tasks"], [])
            self.assertEqual(ValidationWindowScheduler(tenant_id=OTHER_TENANT, root=root).read_schedule("run_validation")["status"], "not_found")

    def test_failed_review_blocks_then_retry_consumes_first_hour_action(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            write_creation_run(root)
            scheduler = ValidationWindowScheduler(tenant_id=TENANT, root=root, clock=lambda: PUBLISHED_AT)
            schedule = scheduler.schedule_for_publication(
                creation_run_id="run_validation",
                published_url=PUBLISHED_URL,
                publication_evidence_uri=EVIDENCE_URL,
                publication_confirmed=True,
            )
            action_task = schedule["tasks"][0]
            due_at = PUBLISHED_AT + timedelta(hours=1)

            failed = scheduler.consume_due_task(
                creation_run_id="run_validation",
                task_id=action_task["task_id"],
                evidence_uri=EVIDENCE_URL,
                review_runner=lambda _task: (_ for _ in ()).throw(RuntimeError("review offline")),
                now=due_at,
            )
            consumed: list[dict[str, object]] = []
            recovered = scheduler.consume_due_task(
                creation_run_id="run_validation",
                task_id=action_task["task_id"],
                evidence_uri=EVIDENCE_URL,
                review_runner=lambda task: consumed.append(task) or {"ok": True, "status": "written", "record_id": "post_1"},
                now=due_at,
                retry_blocked=True,
            )

            self.assertEqual(failed["status"], "blocked")
            self.assertEqual(recovered["status"], "completed")
            self.assertEqual(consumed[0]["task_kind"], "first_hour_action")
            self.assertEqual(consumed[0]["first_hour_action"], "置顶提问并回复前十条评论")
            self.assertEqual(scheduler.due_pending_windows(now=PUBLISHED_AT + timedelta(hours=2))[0]["window"], "2h")

    def test_confirmed_commercial_publication_produces_readable_schedule(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            write_creation_run(root)
            ledger = CommercialLoopLedger(tenant_id=TENANT, loop_id="opp_validation", root=root)
            ledger.ensure_quote_snapshot(business_account_id="account", quote_snapshot_uri="media://quote", quote_refresh={})
            ledger.begin_delivery(request_text="delivery", links={})
            ledger.confirm_delivery(
                doc_url="https://docs.example.test/delivery",
                record={"record_id": "delivery_1"},
                review_links={"creation_run_id": "run_validation"},
            )
            state = ledger.record_publication(
                published_url=PUBLISHED_URL,
                evidence_uri=EVIDENCE_URL,
                published_at=PUBLISHED_AT.isoformat(),
            )
            replay = ledger.record_publication(
                published_url=PUBLISHED_URL,
                evidence_uri=EVIDENCE_URL,
            )

            self.assertEqual(state["validation_schedule"]["status"], "scheduled")
            self.assertEqual(replay["validation_schedule"]["status"], "scheduled")
            self.assertEqual(
                len(ValidationWindowScheduler(tenant_id=TENANT, root=root).read_schedule("run_validation")["tasks"]),
                4,
            )

    def test_data_review_consumer_receives_due_window_and_actual_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {"OPENCLAW_MEDIA_VAULT_ROOT": root}, clear=False):
            write_creation_run(root)
            scheduler = ValidationWindowScheduler(tenant_id=TENANT, root=root, clock=lambda: PUBLISHED_AT)
            schedule = scheduler.schedule_for_publication(
                creation_run_id="run_validation",
                published_url=PUBLISHED_URL,
                publication_evidence_uri=EVIDENCE_URL,
                publication_confirmed=True,
            )
            action_task = schedule["tasks"][0]
            image = Path(root) / "metrics.png"
            image.write_bytes(b"image")
            captured: dict[str, object] = {}

            def fake_review(text: str, **kwargs: object) -> dict[str, object]:
                captured["text"] = text
                captured["attachments"] = kwargs["attachment_paths"]
                return {"ok": True, "status": "written", "record_id": "post_action"}

            with patch.object(data_review, "handle_data_review_command", side_effect=fake_review):
                result = data_review.consume_scheduled_validation_review(
                    tenant_id=TENANT,
                    creation_run_id="run_validation",
                    task_id=action_task["task_id"],
                    evidence_uri=EVIDENCE_URL,
                    attachment_paths=[str(image)],
                    now=PUBLISHED_AT + timedelta(hours=1),
                )

            self.assertEqual(result["status"], "completed")
            self.assertIn("数据节点=1h", str(captured["text"]))
            self.assertIn("首小时动作：置顶提问并回复前十条评论", str(captured["text"]))
            self.assertIn(f"外部复盘证据={EVIDENCE_URL}", str(captured["text"]))
            self.assertEqual(captured["attachments"], [str(image)])
