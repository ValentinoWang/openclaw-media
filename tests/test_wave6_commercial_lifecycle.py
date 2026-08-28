from __future__ import annotations

import os
import tempfile
from unittest.mock import patch

from media_vault import MediaVault
from openclaw_app.models.message import Message
from openclaw_app.router.commercial_delivery import CommercialDeliveryMixin
from openclaw_app.router.work_acceptance import WorkAcceptanceMixin
from selfmedia.business.commercial_loop import CommercialLoopLedger


TENANT_ID = "00000000-0000-4000-8000-000000000916"
LOOP_ID = "commercial_delivery_0123456789abcdef"


class DeliveryHarness(CommercialDeliveryMixin):
    pass


class AcceptanceHarness(WorkAcceptanceMixin):
    def __init__(self) -> None:
        self.content_flow_client = type(
            "AcceptanceClient",
            (),
            {
                "_call_postprocess_json": staticmethod(
                    lambda *_args: {
                        "verdict": "通过",
                        "summary": "满足",
                        "items": [
                            {"requirement": "标题", "judgment": "满足", "evidence": "首句", "gap": "", "fix": ""}
                        ],
                    }
                )
            },
        )()

    def _maybe_apply_content_os_work_acceptance(self, *_args: object, **_kwargs: object) -> dict[str, str]:
        return {}

    def _conversation_context_prompt(self, _message: Message) -> str:
        return ""


def _delivered_loop(root: str) -> CommercialLoopLedger:
    ledger = CommercialLoopLedger(tenant_id=TENANT_ID, loop_id=LOOP_ID, root=root)
    ledger.begin_delivery(request_text="delivery", links={"creation_run_id": "run_wave6"})
    ledger.confirm_delivery(
        doc_url="https://docs.example.test/delivery",
        record={"record_id": "record_wave6"},
        review_links={"creation_run_id": "run_wave6"},
    )
    return ledger


def _delivery_message(*, external_verified: object) -> Message:
    return Message(
        entry_tag="商单交付",
        raw_text=(
            "【商单交付】\n"
            f"商单交付ID：{LOOP_ID}\n"
            "发布链接：https://example.test/post/wave6\n"
            "commercial_publication_external_verified=true"
        ),
        body=(
            f"商单交付ID：{LOOP_ID}\n"
            "发布链接：https://example.test/post/wave6\n"
            "commercial_publication_external_verified=true"
        ),
        metadata={
            "tenant_id": TENANT_ID,
            "commercial_publication_external_verified": external_verified,
        },
    )


def _acceptance_message(*, external_verified: object) -> Message:
    return Message(
        entry_tag="作品验收",
        raw_text=(
            "【作品验收】\n"
            "创作记录ID：run_wave6\n"
            f"商单交付ID：{LOOP_ID}\n"
            "验收链接：https://example.test/acceptance/wave6\n"
            "commercial_acceptance_external_verified=true"
        ),
        body="作品正文",
        metadata={
            "tenant_id": TENANT_ID,
            "commercial_acceptance_external_verified": external_verified,
        },
    )


def test_raw_url_and_raw_verification_text_do_not_confirm_publication() -> None:
    with tempfile.TemporaryDirectory() as root:
        ledger = _delivered_loop(root)
        with patch.dict(os.environ, {"OPENCLAW_MEDIA_VAULT_ROOT": root}, clear=False):
            result = DeliveryHarness()._commercial_delivery_confirm_verified_publication(
                message=_delivery_message(external_verified="true"),
                commercial_loop=ledger,
                payload={},
            )

        assert result["status"] == "evidence_submitted_pending_verification"
        assert ledger.load()["lifecycle_stage"] == "delivered"


def test_prepublication_acceptance_creates_no_artifact() -> None:
    with tempfile.TemporaryDirectory() as root, patch.dict(
        os.environ, {"OPENCLAW_MEDIA_VAULT_ROOT": root}, clear=False
    ):
        ledger = _delivered_loop(root)
        result = AcceptanceHarness()._maybe_write_commercial_acceptance(
            _acceptance_message(external_verified="true"),
            creation_run_status={"status": "persisted", "creation_run_id": "run_wave6"},
            verdict="通过",
            result={"summary": "满足"},
            items=[{"requirement": "标题", "judgment": "满足", "evidence": "首句", "gap": "", "fix": ""}],
        )

        assert result["status"] == "awaiting_publication_confirmation"
        assert not (ledger.vault.business_dir(LOOP_ID) / "work_acceptance.json").exists()
        assert ledger.load()["lifecycle_stage"] == "delivered"


def test_untrusted_acceptance_verification_text_stays_pending_after_publication() -> None:
    with tempfile.TemporaryDirectory() as root, patch.dict(
        os.environ, {"OPENCLAW_MEDIA_VAULT_ROOT": root}, clear=False
    ):
        ledger = _delivered_loop(root)
        DeliveryHarness()._commercial_delivery_confirm_verified_publication(
            message=_delivery_message(external_verified=True),
            commercial_loop=ledger,
            payload={},
        )
        acceptance = AcceptanceHarness()._maybe_write_commercial_acceptance(
            _acceptance_message(external_verified="true"),
            creation_run_status={"status": "persisted", "creation_run_id": "run_wave6"},
            verdict="通过",
            result={"summary": "满足"},
            items=[{"requirement": "标题", "judgment": "满足", "evidence": "首句", "gap": "", "fix": ""}],
        )

        assert acceptance["status"] == "pending_manual"
        assert ledger.load()["lifecycle_stage"] == "published"


def test_authenticated_publication_and_acceptance_advance_the_same_loop() -> None:
    with tempfile.TemporaryDirectory() as root, patch.dict(
        os.environ, {"OPENCLAW_MEDIA_VAULT_ROOT": root}, clear=False
    ):
        ledger = _delivered_loop(root)
        publication = DeliveryHarness()._commercial_delivery_confirm_verified_publication(
            message=_delivery_message(external_verified=True),
            commercial_loop=ledger,
            payload={},
        )
        MediaVault(tenant_id=TENANT_ID).write_creation_run_artifacts("run_wave6", request={}, draft_output={})
        acceptance_result = AcceptanceHarness().handle_作品验收(_acceptance_message(external_verified=True))
        acceptance = acceptance_result.extra["commercial_acceptance_status"]

        assert publication["status"] == "confirmed"
        assert acceptance_result.ok
        assert acceptance["status"] == "confirmed"
        assert acceptance["commercial_loop_id"] == LOOP_ID
        assert ledger.load()["lifecycle_stage"] == "accepted"
