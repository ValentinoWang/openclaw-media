from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from openclaw_app.services.deepmath_approval_callback import (
    DeepMathApprovalCallbackConfig,
    process_verified_callback,
)
from openclaw_app.services.deepmath_approval_service import DeepMathApprovalService
from openclaw_app.services.deepmath_approval_store import DeepMathApprovalStore
from openclaw_app.services.deepmath_team_capability_schema import feishu_record_payload


NOW = datetime(2026, 8, 4, 12, 0, tzinfo=timezone.utc)


def _capability_record(*, expires_at: datetime) -> dict[str, object]:
    return {
        "成员": [{"id": "clock-contract-member"}],
        "职责范围": "研究实验与交付协调",
        "核心技能": "数学建模与实验设计",
        "可承担角色": "DRI；Reviewer",
        "技能证据": "已确认的近期项目记录",
        "未来7天可分配工时": 6,
        "负荷确认时间": "2026-08-01T09:00:00+00:00",
        "负荷有效至": expires_at.isoformat(),
        "记录状态": "有效",
        "维护人": [{"id": "clock-contract-maintainer"}],
    }


class DeepMathApprovalClockContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.state_path = Path(self.tempdir.name) / "approval.sqlite3"

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _callback_config(self) -> DeepMathApprovalCallbackConfig:
        return DeepMathApprovalCallbackConfig(
            state_path=str(self.state_path),
            approver_user_id="approver",
            authorized_actor_ids=frozenset({"approver"}),
            token_signing_secret="clock-contract-secret",
            clock=lambda: NOW,
        )

    def _callback_facts(self, *, expires_at: datetime) -> dict[str, object]:
        service = DeepMathApprovalService(
            DeepMathApprovalStore(self.state_path),
            approver_user_id="approver",
            authorized_actor_ids={"approver"},
            token_signing_secret="clock-contract-secret",
            clock=lambda: NOW,
        )
        created = service.create_item(
            tenant_key="deepmath",
            proposal_id="clock-contract-proposal",
            approval_id="clock-contract-item",
            payload={"object_type": "任务", "action": "创建"},
            expires_at=expires_at,
        )
        item = created["item"]
        return {
            "transport_verified": True,
            "action": "save",
            "tenant_key": "deepmath",
            "proposal_id": "clock-contract-proposal",
            "proposal_version": 1,
            "approval_id": "clock-contract-item",
            "payload_sha256": item["payload_sha256"],
            "token": created["token"],
            "actor_id": "approver",
        }

    def test_injected_clock_rejects_records_expired_relative_to_it(self):
        result = process_verified_callback(
            self._callback_facts(expires_at=NOW - timedelta(seconds=1)), self._callback_config()
        )
        self.assertEqual(result["code"], "expired")
        with self.assertRaisesRegex(ValueError, "future"):
            feishu_record_payload(_capability_record(expires_at=NOW - timedelta(seconds=1)), now=NOW)

    def test_injected_clock_keeps_valid_records_stable_after_fixture_date(self):
        result = process_verified_callback(
            self._callback_facts(expires_at=NOW + timedelta(hours=1)), self._callback_config()
        )
        self.assertEqual(result["status"], "saved")
        payload = feishu_record_payload(_capability_record(expires_at=NOW + timedelta(hours=1)), now=NOW)
        self.assertEqual(payload["fields"]["记录状态"], "有效")


if __name__ == "__main__":
    unittest.main()
