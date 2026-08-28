from __future__ import annotations

import tempfile
import unittest
import shutil

from selfmedia.business.commercial_loop import (
    BusinessOpportunityLifecycle,
    CommercialLifecycleError,
    CommercialLoopLedger,
)
from selfmedia.business.publishing_package import PublishingPackageError, PublishingPackageProducer
from selfmedia.business.work_acceptance import WorkAcceptanceError, WorkAcceptanceWriteback
from media_vault import MediaVault, MediaVaultUriError


TENANT = "00000000-0000-4000-8000-000000000777"


class P7BCommercialClosureTests(unittest.TestCase):
    def test_canonical_lifecycle_requires_real_events_and_is_idempotent(self) -> None:
        state = {"lifecycle_status": "quoted"}
        state = BusinessOpportunityLifecycle.transition(state, "creation_started", idempotency_key="create-1")
        state = BusinessOpportunityLifecycle.transition(
            state,
            "delivery_confirmed",
            evidence_uri="https://docs.example.test/delivery",
            idempotency_key="delivery-1",
        )
        state = BusinessOpportunityLifecycle.transition(
            state,
            "publication_confirmed",
            evidence_uri="https://example.test/post/1",
            idempotency_key="publish-1",
            metadata={"published_url": "https://example.test/post/1"},
        )
        replay = BusinessOpportunityLifecycle.transition(
            state,
            "publication_confirmed",
            evidence_uri="https://example.test/post/1",
            idempotency_key="publish-1",
        )
        self.assertEqual(replay, state)
        self.assertEqual(state["lifecycle_stage"], "published")
        self.assertEqual(state["lifecycle_status"], "delivered")
        with self.assertRaises(CommercialLifecycleError):
            BusinessOpportunityLifecycle.transition(
                state,
                "publication_confirmed",
                evidence_uri="https://example.test/post/changed",
                idempotency_key="publish-1",
            )
        with self.assertRaisesRegex(ValueError, "illegal"):
            BusinessOpportunityLifecycle.transition(state, "settlement_confirmed", evidence_uri="https://pay.test/1", idempotency_key="settle-early")

    def test_ledger_full_flow_and_missing_evidence_stays_pending(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            ledger = CommercialLoopLedger(tenant_id=TENANT, loop_id="opp_p7b", root=root)
            ledger.ensure_quote_snapshot(business_account_id="acct", quote_snapshot_uri="media://quote", quote_refresh={})
            ledger.begin_delivery(request_text="delivery", links={"creation_run_id": "run_p7b"})
            state = ledger.confirm_delivery(
                doc_url="https://docs.example.test/delivery",
                record={"record_id": "record_p7b"},
                review_links={},
            )
            self.assertEqual(state["lifecycle_stage"], "delivered")
            pending = ledger.record_publication(published_url="", evidence_uri="")
            self.assertEqual(pending["publish_status"], "pending_manual")
            state = ledger.record_publication(
                published_url="https://example.test/post/1",
                evidence_uri="https://example.test/post/1",
                idempotency_key="pub-1",
            )
            state = ledger.record_acceptance(
                verdict="通过",
                evidence_uri="https://example.test/acceptance/1",
                external_verified=True,
                idempotency_key="accept-1",
            )
            state = ledger.record_retrospective(
                summary="首小时互动达到目标",
                evidence_uri="https://example.test/review/1",
                idempotency_key="review-1",
            )
            state = ledger.record_settlement(
                evidence_uri="https://example.test/settlement/1",
                settled_at="2026-08-29T12:00:00+00:00",
                idempotency_key="settle-1",
            )
            self.assertEqual(state["lifecycle_stage"], "settled")
            self.assertEqual(state["lifecycle_status"], "settled")
            self.assertEqual(len(state["lifecycle_events"]), 7)
            projected = ledger.canonical_opportunity_payload(
                {
                    "opportunity_id": "opp_p7b",
                    "brand": "测试品牌",
                    "quote_snapshot_uri": "media://quote",
                    "delivery_evidence_uri": "media://delivery",
                    "settlement_evidence_uri": "media://settlement",
                }
            )
            self.assertEqual(projected["lifecycle_status"], "settled")
            self.assertEqual(projected["delivery_published_url"], "https://example.test/post/1")

    def test_missing_evidence_cannot_bypass_lifecycle_order(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            ledger = CommercialLoopLedger(tenant_id=TENANT, loop_id="opp_order", root=root)
            ledger.ensure_quote_snapshot(business_account_id="acct", quote_snapshot_uri="media://quote", quote_refresh={})
            ledger.begin_delivery(request_text="delivery", links={})
            with self.assertRaises(CommercialLifecycleError):
                ledger.record_acceptance(verdict="通过")
            with self.assertRaises(CommercialLifecycleError):
                ledger.record_settlement()

    def test_publishing_package_rejects_private_publish_url(self) -> None:
        fields = {
            "title_1": "标题",
            "title_2": "副标题",
            "cover_text": "封面",
            "body_copy": "正文",
            "hashtags": ["标签"],
            "pinned_comment": "置顶",
            "comment_prompt": "互动",
            "first_hour_action": "回复评论",
        }
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(PublishingPackageError):
                PublishingPackageProducer(tenant_id=TENANT, opportunity_id="opp_private", root=root).produce(
                    creation_run_id="run_private",
                    platform="douyin",
                    content_fields=fields,
                    published_url="http://127.0.0.1/post",
                )

    def test_acceptance_replay_is_idempotent_but_changed_payload_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            ledger = CommercialLoopLedger(tenant_id=TENANT, loop_id="opp_replay", root=root)
            ledger.ensure_quote_snapshot(business_account_id="acct", quote_snapshot_uri="media://quote", quote_refresh={})
            ledger.begin_delivery(request_text="delivery", links={})
            ledger.confirm_delivery(doc_url="https://docs.example.test/delivery", record={"record_id": "r"}, review_links={})
            ledger.record_publication(published_url="https://example.test/post", evidence_uri="https://example.test/post")
            writer = WorkAcceptanceWriteback(tenant_id=TENANT, opportunity_id="opp_replay", root=root)
            first = writer.record(creation_run_id="run_replay", verdict="通过", evidence_uri="https://example.test/acceptance", external_verified=True)
            replay = writer.record(creation_run_id="run_replay", verdict="通过", evidence_uri="https://example.test/acceptance", external_verified=True)
            self.assertEqual(replay["readback"], first["readback"])
            with self.assertRaises(WorkAcceptanceError):
                writer.record(creation_run_id="run_replay", verdict="不通过", evidence_uri="https://example.test/acceptance", external_verified=True)

    def test_publishing_package_and_acceptance_are_structured_and_tenant_bound(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            producer = PublishingPackageProducer(tenant_id=TENANT, opportunity_id="opp_pkg", root=root)
            fields = {
                "title_1": "训练日记",
                "title_2": "训练前后",
                "cover_text": "坚持训练",
                "body_copy": "今天完成训练。",
                "hashtags": ["训练"],
                "pinned_comment": "你今天训练了吗？",
                "comment_prompt": "你会如何开始？",
                "first_hour_action": "发布后回复前十条评论。",
            }
            package = producer.produce(creation_run_id="run_pkg", platform="douyin", content_fields=fields)
            replay = producer.produce(creation_run_id="run_pkg", platform="douyin", content_fields=fields)
            self.assertFalse(package["replayed"])
            self.assertTrue(replay["replayed"])
            self.assertEqual(package["version"], "1")
            self.assertEqual(package["idempotency_identity"], replay["idempotency_identity"])
            pending_publish = PublishingPackageProducer(tenant_id=TENANT, opportunity_id="opp_pkg_publish", root=root).produce(
                creation_run_id="run_pkg",
                platform="douyin",
                content_fields=fields,
                published_url="https://example.test/post",
                external_evidence_uri="https://example.test/post",
                idempotency_identity="package-published",
            )
            self.assertEqual(pending_publish["status"], "pending_manual")
            private_evidence = PublishingPackageProducer(tenant_id=TENANT, opportunity_id="opp_pkg_private_evidence", root=root).produce(
                creation_run_id="run_pkg",
                platform="douyin",
                content_fields=fields,
                published_url="https://example.test/post",
                external_evidence_uri="http://127.0.0.1/evidence",
                external_verified=True,
            )
            self.assertEqual(private_evidence["status"], "pending_manual")

            ledger = CommercialLoopLedger(tenant_id=TENANT, loop_id="opp_accept", root=root)
            ledger.ensure_quote_snapshot(business_account_id="acct", quote_snapshot_uri="media://quote", quote_refresh={})
            ledger.begin_delivery(request_text="delivery", links={})
            ledger.confirm_delivery(doc_url="https://docs.example.test/delivery", record={"record_id": "r"}, review_links={})
            ledger.record_publication(published_url="https://example.test/post", evidence_uri="https://example.test/post")
            writer = WorkAcceptanceWriteback(tenant_id=TENANT, opportunity_id="opp_accept", root=root)
            pending = writer.record(creation_run_id="run_accept", verdict="通过", items=[])
            self.assertEqual(pending["status"], "pending_manual")
            confirmed = writer.record(
                creation_run_id="run_accept",
                verdict="通过",
                evidence_uri="https://example.test/acceptance",
                external_verified=True,
            )
            self.assertEqual(confirmed["status"], "confirmed")
            self.assertEqual(confirmed["readback"]["creation_run_id"], "run_accept")

            with self.assertRaises(PublishingPackageError):
                PublishingPackageProducer(tenant_id="00000000-0000-4000-8000-000000000778", opportunity_id="opp_pkg", root=root).read()
            foreign_acceptance = MediaVault(tenant_id=TENANT, root=root).business_dir("opp_accept") / "work_acceptance.json"
            foreign_target = MediaVault(tenant_id="00000000-0000-4000-8000-000000000778", root=root).business_dir("opp_accept") / "work_acceptance.json"
            foreign_target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(foreign_acceptance, foreign_target)
            with self.assertRaises(WorkAcceptanceError):
                WorkAcceptanceWriteback(tenant_id="00000000-0000-4000-8000-000000000778", opportunity_id="opp_accept", root=root).read()
            with self.assertRaises(MediaVaultUriError):
                MediaVault(tenant_id="00000000-0000-4000-8000-000000000778", root=root).read_json_artifact(package["artifact_uri"])


if __name__ == "__main__":
    unittest.main()
