from datetime import datetime
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from openclaw_app.router.deepmath_ceo_thinking import DeepMathCeoThinkingMixin
from openclaw_app.services.deepmath_thinking_intake import DeepMathThinkingIntakeService
from openclaw_app.services.deepmath_ceo_thinking_schema import APPROVALS, DECISIONS, INBOX


class FakeBitable:
    def __init__(self):
        self.rows = {INBOX.name: [], DECISIONS.name: [], APPROVALS.name: []}
        self.events = []

    def find(self, table, field, value):
        return next((row for row in self.rows[table] if row["fields"].get(field) == value), None)

    def get(self, table, record_id):
        self.events.append(("get", table, {"record_id": record_id}))
        return next(row for row in self.rows[table] if row["record_id"] == record_id)

    def create(self, table, fields):
        self.events.append(("create", table, dict(fields)))
        row = {"record_id": f"rec-{table}-{len(self.rows[table]) + 1}", "fields": dict(fields)}
        self.rows[table].append(row)
        return row

    def update(self, table, record_id, fields):
        self.events.append(("update", table, dict(fields)))
        row = next(row for row in self.rows[table] if row["record_id"] == record_id)
        row["fields"].update(fields)
        return row

    def upload(self, path):
        self.events.append(("upload", path.name, {}))
        return {"file_token": "file-test"}

    def send_card(self, open_id, card):
        self.events.append(("send_card", "approval", {"open_id": open_id, "card": card}))
        return {"message_id": "om-card-test"}


class FakeApprovalService:
    def create_item(self, **kwargs):
        value = {
            "openclaw_action": "deepmath_approval",
            "action": "approve",
            "tenant_key": kwargs["tenant_key"],
            "proposal_id": kwargs["proposal_id"],
            "proposal_version": kwargs["proposal_version"],
            "approval_id": kwargs["approval_id"],
            "payload_sha256": "f" * 64,
            "token": "private-test-token",
        }
        return {"card": {"body": {"elements": [{"tag": "action", "actions": [{"value": value}]}]}}}


class FakePeopleService:
    def __init__(self):
        self.calls = []

    def recommend(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "status": "recommended",
            "workload_fingerprint": "w" * 64,
            "candidates": [{
                "candidate_ref": "candidate_test",
                "name": "测试成员",
                "department": ["测试部门"],
                "declared_hours": 4,
                "roles": "DRI",
                "evidence": "人工确认",
            }],
            "recommendation": [{"candidate_ref": "candidate_test", "role": "DRI"}],
        }


class FakeLLM:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def _call_profile_provider_json(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.payload

    def transcribe_file(self, path, output_dir):
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        transcript = Path(output_dir) / "transcript.txt"
        transcript.write_text("语音中的原始想法", encoding="utf-8")
        return {"status": "done", "transcript_path": str(transcript)}


def service(payload):
    value = object.__new__(DeepMathThinkingIntakeService)
    value.client = FakeBitable()
    value.content_flow_client = FakeLLM(payload)
    value.allowed_sender_ids = frozenset({"ou_ceo"})
    value.approver_open_id = "ou_approver"
    value.approval_service = FakeApprovalService()
    value.people_service = FakePeopleService()
    return value


def metadata(message_id="om-u3-test", attachments=None):
    return {"account_id": "deepmath", "source_sender_id": "ou_ceo", "source_message_id": message_id, "attachments": attachments or []}


class DeepMathThinkingIntakeTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 8, 3, 12, 0, 0)

    def test_source_is_written_before_exactly_one_llm_and_candidates_trace_back(self):
        svc = service({
            "status": "done", "title": "验证数学助教付费假设", "core_meaning": "先比较验证路径", "facts": ["已有两个意向客户"],
            "judgments": ["付费意愿尚不清晰"], "hypotheses": ["访谈能缩小不确定性"], "domains": ["产品", "市场与客户"], "missing_reason": "",
            "decisions": [{"question": "是否先做客户访谈？", "background": "当前只有意向信号", "options": ["先访谈", "直接开发"], "recommendation": "先访谈，仍需验证", "basis": "用户原文", "inaction_consequence": "继续不确定"}],
            "action_candidates": [{"candidate_kind": "最小实验", "object_type": "任务", "action": "创建", "summary": "访谈两名客户", "owner_role": "产品负责人", "owner_reason": "需要直接验证客户需求", "deliverable": "两份访谈纪要", "acceptance_criteria": "保留两份原始记录并列出付费信号", "execution_parameters": "截止时间待填写", "decision_index": 0}],
        })
        result = svc.ingest(body="我们是否应先访谈两个客户？", chat_type="private", metadata=metadata(), created_at=self.now)
        self.assertEqual(result["status"], "structured")
        self.assertEqual(len(svc.content_flow_client.calls), 1)
        self.assertEqual(len(svc.people_service.calls), 1)
        self.assertEqual(svc.client.events[0][0:2], ("create", INBOX.name))
        inbox_id = svc.client.rows[INBOX.name][0]["record_id"]
        self.assertEqual(svc.client.rows[DECISIONS.name][0]["fields"]["关联思考"], [inbox_id])
        self.assertEqual(svc.client.rows[APPROVALS.name][0]["fields"]["关联思考"], [inbox_id])
        approval_fields = svc.client.rows[APPROVALS.name][0]["fields"]
        self.assertEqual(approval_fields["提案版本"], 1)
        self.assertEqual(approval_fields["提案项序号"], 1)
        self.assertEqual(approval_fields["提案状态"], "待确认")
        self.assertEqual(approval_fields["审批决定"], "待决定")
        self.assertEqual(approval_fields["执行状态"], "未授权")
        self.assertEqual(len(approval_fields["参数指纹"]), 64)
        self.assertIn('"object_type":"任务"', approval_fields["执行参数"])
        parameters = svc.client.rows[APPROVALS.name][0]["fields"]["执行参数"]
        self.assertIn("候选类型：最小实验", parameters)
        self.assertIn("负责人类型：产品负责人", parameters)
        self.assertIn("交付物：两份访谈纪要", parameters)
        self.assertIn("验收标准：保留两份原始记录并列出付费信号", parameters)
        self.assertEqual(result["approval_card_count"], 1)
        card_events = [event for event in svc.client.events if event[0] == "send_card"]
        self.assertEqual(len(card_events), 1)
        rendered_card = str(card_events[0][2]["card"])
        self.assertIn("deepmath_approval", rendered_card)
        self.assertFalse(result["side_effects_executed"])

    def test_group_intake_persists_group_source_and_returns_receipt_only(self):
        svc = service({"status": "done", "title": "群内思考", "facts": [], "judgments": [], "hypotheses": [], "domains": []})
        router = DeepMathCeoThinkingMixin()
        router.deepmath_thinking_intake_service = svc
        result = router.handle_思考(SimpleNamespace(body="群里的原始思考", chat_type="group", metadata=metadata("om-group"), created_at=self.now))
        self.assertEqual(result.status, "deepmath_thinking_group_received")
        self.assertIn("已收件", result.reply)
        self.assertIn("仅在私聊处理", result.reply)
        self.assertNotIn("决策候选", result.reply)
        self.assertEqual(svc.client.rows[INBOX.name][0]["fields"]["来源"], "群聊")

    def test_incomplete_action_candidate_routes_to_manual_without_partial_candidate(self):
        svc = service({
            "status": "done", "title": "缺少验收字段", "facts": [], "judgments": [], "hypotheses": [], "domains": [],
            "action_candidates": [{"candidate_kind": "任务", "object_type": "任务", "action": "创建", "summary": "做一件事", "owner_role": "研发", "owner_reason": "技术实现", "deliverable": "原型"}],
        })
        result = svc.ingest(body="建议做一个原型", chat_type="private", metadata=metadata("om-incomplete"), created_at=self.now)
        self.assertEqual(result["status"], "pending_manual")
        self.assertEqual(svc.client.rows[APPROVALS.name], [])
        self.assertEqual(svc.client.rows[INBOX.name][0]["fields"]["处理状态"], "人工处理")

    def test_ambiguous_text_is_saved_without_forced_candidates(self):
        svc = service({"status": "done", "title": "记录对长期研究节奏的感受", "core_meaning": "保留感受", "facts": [], "judgments": [], "hypotheses": [], "domains": ["科研方向"], "missing_reason": "没有明确选择或行动"})
        result = svc.ingest(body="今天感觉长期研究需要一点耐心。", chat_type="private", metadata=metadata("om-ambiguous"), created_at=self.now)
        self.assertEqual(result["processing_status"], "仅保存")
        self.assertEqual(svc.client.rows[DECISIONS.name], [])
        self.assertEqual(svc.client.rows[APPROVALS.name], [])

    def test_llm_failure_preserves_evidence_and_marks_manual_without_fallback(self):
        svc = service({"status": "pending_manual", "reason": "model unavailable"})
        result = svc.ingest(body="一条不能丢的原始想法", chat_type="private", metadata=metadata("om-failure"), created_at=self.now)
        self.assertEqual(result["status"], "pending_manual")
        self.assertEqual(len(svc.content_flow_client.calls), 1)
        fields = svc.client.rows[INBOX.name][0]["fields"]
        self.assertEqual(fields["原始内容"], "一条不能丢的原始想法")
        self.assertEqual(fields["处理状态"], "人工处理")
        self.assertEqual(svc.client.rows[APPROVALS.name], [])

    def test_replay_is_idempotent_and_does_not_call_llm_twice(self):
        svc = service({"status": "done", "title": "只保存", "facts": [], "judgments": [], "hypotheses": [], "domains": []})
        first = svc.ingest(body="相同消息", chat_type="private", metadata=metadata("om-replay"), created_at=self.now)
        second = svc.ingest(body="相同消息", chat_type="private", metadata=metadata("om-replay"), created_at=self.now)
        self.assertEqual(first["status"], "structured")
        self.assertEqual(second["status"], "idempotent_replay")
        self.assertEqual(len(svc.client.rows[INBOX.name]), 1)
        self.assertEqual(len(svc.content_flow_client.calls), 1)

    def test_audio_is_uploaded_transcribed_and_structured_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "idea.wav"
            audio.write_bytes(b"RIFF-test")
            svc = service({"status": "done", "title": "语音思考", "facts": [], "judgments": [], "hypotheses": [], "domains": []})
            result = svc.ingest(body="", chat_type="private", metadata=metadata("om-audio", [{"local_path": str(audio), "mime_type": "audio/wav", "file_name": "idea.wav"}]), created_at=self.now)
            self.assertEqual(result["status"], "structured")
            self.assertIn("[语音转写]", svc.client.rows[INBOX.name][0]["fields"]["原始内容"])
            self.assertEqual(len(svc.content_flow_client.calls), 1)


if __name__ == "__main__":
    unittest.main()
