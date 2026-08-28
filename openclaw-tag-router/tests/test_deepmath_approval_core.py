from datetime import datetime, timedelta, timezone
import json
import multiprocessing
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from openclaw_app.services import deepmath_approval_callback as callback_module
from openclaw_app.services.deepmath_approval_callback import (
    DeepMathApprovalCallbackConfig,
    process_verified_callback,
)
from openclaw_app.services.deepmath_approval_service import (
    DeepMathApprovalService,
    DeepMathExecutorRegistry,
)
from openclaw_app.services.deepmath_approval_store import (
    DeepMathApprovalStore,
    DeepMathApprovalStoreConflict,
)
from openclaw_app.services.deepmath_ceo_thinking_schema import canonical_json, payload_fingerprint
from openclaw_app.services.deepmath_resources import DeepMathResourceConfig


UTC = timezone.utc


def _claim_in_child(path, output_queue, now):
    store = DeepMathApprovalStore(path)
    try:
        _, claimed = store.claim_approval(
            tenant_key="deepmath", proposal_id="process-proposal", approval_id="item",
            expected_version=1, expected_payload_sha256=payload_fingerprint({"object_type": "任务", "action": "创建"}),
            actor_id="approver", now=now,
        )
        output_queue.put(claimed)
    except Exception as exc:  # pragma: no cover - asserted by the parent if SQLite semantics regress
        output_queue.put(type(exc).__name__)


class CountingExecutor:
    def __init__(self):
        self.calls = 0
        self.lock = threading.Lock()

    def __call__(self, claim):
        with self.lock:
            self.calls += 1
        return {"status": "success", "receipt": {"result": "ok"}}


class DeepMathApprovalCoreTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.path = Path(self.tempdir.name) / "state" / "approval.sqlite3"
        self.now = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)

    def tearDown(self):
        self.tempdir.cleanup()

    def service(self, *, registry=None, clock=None, secret="stable-secret", people_resolver=None):
        store = DeepMathApprovalStore(self.path)
        return DeepMathApprovalService(
            store,
            approver_user_id="approver",
            authorized_actor_ids={"approver"},
            executor_registry=registry,
            token_signing_secret=secret,
            clock=clock or (lambda: self.now),
            people_resolver=people_resolver,
        )

    def proposal(self, service, *, payload=None, expires_at=None, proposal_id="proposal"):
        payload = payload or {"object_type": "任务", "action": "创建", "summary": "一项已批准动作"}
        result = service.create_item(
            tenant_key="deepmath",
            proposal_id=proposal_id,
            approval_id="item",
            payload=payload,
            expires_at=expires_at or self.now + timedelta(hours=1),
        )
        item = result["item"]
        common = {
            "tenant_key": "deepmath",
            "proposal_id": proposal_id,
            "proposal_version": 1,
            "approval_id": "item",
            "payload_sha256": item["payload_sha256"],
            "token": result["token"],
            "actor_id": "approver",
        }
        return result, item, common

    def test_store_is_0600_and_has_exact_minimum_columns(self):
        store = DeepMathApprovalStore(self.path)
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        connection = store._connect()
        try:
            columns = [row[1] for row in connection.execute("PRAGMA table_info(proposal_items)")]
        finally:
            connection.close()
        self.assertEqual(columns, list(store._EXPECTED_COLUMNS))

    def test_two_connections_claim_once(self):
        executor = CountingExecutor()
        registry = DeepMathExecutorRegistry()
        registry.register("任务", "创建", executor)
        first = self.service(registry=registry)
        created, item, common = self.proposal(first)
        second = self.service(registry=registry)
        results = []
        barrier = threading.Barrier(2)

        def approve(service):
            barrier.wait()
            results.append(service.approve(**common))

        threads = [threading.Thread(target=approve, args=(first,)), threading.Thread(target=approve, args=(second,))]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(executor.calls, 1)
        self.assertEqual(DeepMathApprovalStore(self.path).count_approved_unclaimed(), 0)
        self.assertTrue(all(result["execution_state"] in {"执行中", "执行成功"} for result in results))
        self.assertEqual(first.store.get_current_item(tenant_key="deepmath", proposal_id="proposal", approval_id="item")["execution_state"], "执行成功")
        self.assertEqual(second.approve(**common)["code"], "persisted_receipt")

    def test_two_processes_share_one_atomic_claim(self):
        store = DeepMathApprovalStore(self.path)
        payload = {"object_type": "任务", "action": "创建"}
        store.insert_proposal_item(
            tenant_key="deepmath", proposal_id="process-proposal", proposal_version=1, approval_id="item",
            canonical_payload_value=payload, token="process-token", expires_at=self.now + timedelta(hours=1),
        )
        context = multiprocessing.get_context("fork")
        output_queue = context.Queue()
        processes = [
            context.Process(target=_claim_in_child, args=(str(self.path), output_queue, self.now)),
            context.Process(target=_claim_in_child, args=(str(self.path), output_queue, self.now)),
        ]
        for process in processes:
            process.start()
        results = [output_queue.get(timeout=10) for _ in processes]
        for process in processes:
            process.join(timeout=10)
        self.assertEqual(sorted(results), [False, True])
        self.assertEqual(store.count_approved_unclaimed(), 0)

    def test_stale_version_and_token_cannot_execute(self):
        executor = CountingExecutor()
        registry = DeepMathExecutorRegistry()
        registry.register("任务", "创建", executor)
        service = self.service(registry=registry)
        created, item, common = self.proposal(service)
        modified = service.modify(
            **common,
            new_payload={"object_type": "任务", "action": "创建", "summary": "修订后的动作"},
        )
        self.assertEqual(modified["status"], "modified")
        stale = service.approve(**common)
        self.assertEqual(stale["code"], "stale_version")
        self.assertEqual(executor.calls, 0)
        self.assertNotIn(created["token"], json.dumps(modified["card"], ensure_ascii=False))

    def test_unauthorized_actor_has_zero_executor_calls_and_no_state_change(self):
        executor = CountingExecutor()
        registry = DeepMathExecutorRegistry()
        registry.register("任务", "创建", executor)
        service = self.service(registry=registry)
        _, item, common = self.proposal(service)
        result = service.approve(**{**common, "actor_id": "unauthorized"})
        self.assertEqual(result["code"], "unauthorized")
        self.assertEqual(executor.calls, 0)
        current = service.store.get_current_item(tenant_key="deepmath", proposal_id="proposal", approval_id="item")
        self.assertEqual(current["execution_state"], "未授权")
        self.assertEqual(current["decision_state"], "待决定")

    def test_expired_callback_has_zero_executor_calls(self):
        executor = CountingExecutor()
        registry = DeepMathExecutorRegistry()
        registry.register("任务", "创建", executor)
        service = self.service(registry=registry)
        _, _, common = self.proposal(service, expires_at=self.now - timedelta(seconds=1))
        result = service.approve(**common)
        self.assertEqual(result["code"], "expired")
        self.assertEqual(executor.calls, 0)
        item = service.store.get_current_item(tenant_key="deepmath", proposal_id="proposal", approval_id="item")
        self.assertEqual(item["proposal_state"], "已过期")
        self.assertEqual(item["execution_state"], "未授权")

    def test_reject_save_cancel_and_modify_are_side_effect_free(self):
        executor = CountingExecutor()
        registry = DeepMathExecutorRegistry()
        registry.register("任务", "创建", executor)
        for action in ("reject", "save", "cancel"):
            service = self.service(registry=registry)
            _, _, common = self.proposal(service, proposal_id=f"{action}-proposal")
            result = service.handle_callback({"action": action, **common})
            self.assertIn(result["status"], {"rejected", "saved", "cancelled"})
            self.assertEqual(executor.calls, 0)
        service = self.service(registry=registry)
        _, _, common = self.proposal(service, proposal_id="modify-proposal")
        result = service.handle_callback({"action": "modify", **common, "new_payload": {"object_type": "任务", "action": "创建", "summary": "new"}})
        self.assertEqual(result["status"], "modified")
        self.assertEqual(executor.calls, 0)

    def test_same_execution_key_with_different_payload_is_conflict(self):
        store = DeepMathApprovalStore(self.path)
        first = store.insert_proposal_item(
            tenant_key="deepmath", proposal_id="proposal", proposal_version=1, approval_id="item",
            canonical_payload_value={"object_type": "任务", "action": "创建"}, token="token-a",
            expires_at=self.now + timedelta(hours=1),
        )
        with self.assertRaises(DeepMathApprovalStoreConflict):
            store.insert_proposal_item(
                tenant_key="deepmath", proposal_id="other", proposal_version=1, approval_id="other",
                canonical_payload_value={"object_type": "任务", "action": "修改"}, token="token-b",
                expires_at=self.now + timedelta(hours=1), execution_key=first["execution_key"],
            )

    def test_replay_after_new_service_instance_returns_persisted_receipt(self):
        executor = CountingExecutor()
        registry = DeepMathExecutorRegistry()
        registry.register("任务", "创建", executor)
        first = self.service(registry=registry, secret="stable-secret")
        _, _, common = self.proposal(first)
        completed = first.approve(**common)
        restarted = self.service(registry=DeepMathExecutorRegistry(), secret="stable-secret")
        replay = restarted.approve(**common)
        self.assertEqual(completed["execution_state"], "执行成功")
        self.assertEqual(replay["code"], "persisted_receipt")
        self.assertTrue(replay["replayed"])
        self.assertEqual(replay["receipt"], {"result": "ok"})
        self.assertEqual(executor.calls, 1)

    def test_card_has_structured_actions_and_hash_only_store(self):
        service = self.service(secret="stable-secret")
        created, item, _ = self.proposal(service)
        rendered = json.dumps(created["card"], ensure_ascii=False)
        self.assertIn('"openclaw_action": "deepmath_approval"', rendered)
        self.assertIn('"action": "approve"', rendered)
        self.assertIn(created["token"], rendered)
        connection = service.store._connect()
        try:
            raw = connection.execute("SELECT token_hash, canonical_payload FROM proposal_items").fetchone()
        finally:
            connection.close()
        self.assertNotEqual(raw[0], created["token"])
        self.assertEqual(raw[1], canonical_json(item["canonical_payload"]))
        self.assertEqual(item["payload_sha256"], payload_fingerprint(item["canonical_payload"]))

    def test_people_required_card_disables_approve_until_confirmed(self):
        executor = CountingExecutor()
        registry = DeepMathExecutorRegistry()
        registry.register("任务", "创建", executor)

        def resolver(selection):
            return {
                "status": "accepted",
                "workload_fingerprint": selection["workload_fingerprint"],
                "assignments": [{"directory_id": "private-directory-id", "role": "DRI"}],
            }

        service = self.service(registry=registry, people_resolver=resolver)
        people = {
            "status": "recommended",
            "workload_fingerprint": "fresh-workload",
            "candidates": [{
                "candidate_ref": "candidate_safe",
                "name": "候选甲",
                "responsibilities": "研究",
                "declared_hours": 12,
            }],
            "recommendation": [{"candidate_ref": "candidate_safe", "role": "DRI"}],
        }
        created, _, common = self.proposal(service, payload={
            "object_type": "任务", "action": "创建", "summary": "需要人员", "people_assignment": people,
        })
        rendered = json.dumps(created["card"], ensure_ascii=False)
        self.assertNotIn('"action": "approve"', rendered)
        self.assertIn("deepmath_people_confirmation", rendered)
        blocked = service.approve(**common)
        self.assertEqual(blocked["code"], "people_confirmation_required_or_stale")
        self.assertEqual(executor.calls, 0)

        modified = service.modify(
            **common,
            new_payload={"people_selection": {
                "workload_fingerprint": "fresh-workload",
                "assignments": [{"candidate_ref": "candidate_safe", "role": "DRI"}],
            }},
        )
        self.assertEqual(modified["status"], "modified")
        confirmed_card = json.dumps(modified["card"], ensure_ascii=False)
        self.assertIn('"action": "approve"', confirmed_card)
        self.assertNotIn("private-directory-id", confirmed_card)
        current = service.store.get_current_item(tenant_key="deepmath", proposal_id="proposal", approval_id="item")
        self.assertEqual(current["canonical_payload"]["people_assignment"]["status"], "confirmed")
        self.assertEqual(current["proposal_version"], 2)

    def test_people_approval_rechecks_fresh_evidence_before_claim(self):
        calls = 0

        def resolver(selection):
            nonlocal calls
            calls += 1
            if calls > 1:
                return {"status": "pending_manual", "reason": "workload_drift"}
            return {
                "status": "accepted",
                "workload_fingerprint": selection["workload_fingerprint"],
                "assignments": [{"directory_id": "private-directory-id", "role": "DRI"}],
            }

        service = self.service(people_resolver=resolver)
        created, _, common = self.proposal(service, payload={
            "object_type": "任务", "action": "创建", "summary": "需要人员",
            "people_assignment": {
                "status": "recommended", "workload_fingerprint": "fp",
                "candidates": [{"candidate_ref": "candidate_safe", "name": "候选甲"}],
                "recommendation": [{"candidate_ref": "candidate_safe", "role": "DRI"}],
            },
        })
        modified = service.modify(**common, new_payload={"people_selection": {
            "workload_fingerprint": "fp",
            "assignments": [{"candidate_ref": "candidate_safe", "role": "DRI"}],
        }})
        card = modified["card"]
        approve = next(
            action["value"]
            for element in card["body"]["elements"] if element.get("tag") == "action"
            for action in element["actions"] if action["value"]["action"] == "approve"
        )
        result = service.approve(
            tenant_key=approve["tenant_key"], proposal_id=approve["proposal_id"],
            proposal_version=approve["proposal_version"], approval_id=approve["approval_id"],
            payload_sha256=approve["payload_sha256"], token=approve["token"], actor_id="approver",
        )
        self.assertEqual(result["code"], "people_confirmation_required_or_stale")
        current = service.store.get_current_item(tenant_key="deepmath", proposal_id="proposal", approval_id="item")
        self.assertEqual(current["decision_state"], "待决定")
        self.assertEqual(current["execution_state"], "未授权")

    def test_callback_output_is_safe_and_reads_only_configured_state(self):
        service = self.service()
        created, item, common = self.proposal(service)
        config = DeepMathApprovalCallbackConfig(
            state_path=str(self.path), approver_user_id="approver", authorized_actor_ids=frozenset({"approver"}),
            token_signing_secret="stable-secret", clock=lambda: self.now,
        )
        result = process_verified_callback({"transport_verified": True, "action": "save", **common}, config)
        self.assertEqual(result["status"], "saved")
        self.assertNotIn("token", json.dumps(result, ensure_ascii=False))
        self.assertNotIn("proposal_id", result)
        self.assertNotIn("approval_id", result)

    def test_production_callback_registers_only_task_create_after_claim(self):
        assignments = [{"directory_id": "private-dri", "role": "DRI"}]
        payload = {
            "object_type": "任务", "action": "创建", "tasklist_id": "canonical-tasklist",
            "summary": "approved task", "purpose": "prove integration", "source_thought_id": "thought-ref",
            "deliverable": "readback", "acceptance_criteria": "exact match",
            "due": {"timestamp": "1785945600000", "timezone": "Asia/Shanghai", "is_all_day": False},
            "reminders": [{"relative_fire_minute": 30}],
            "people_assignment": {
                "status": "confirmed", "workload_fingerprint": "fresh", "recommendation": [{"candidate_ref": "opaque", "role": "DRI"}],
                "resolved_assignments": assignments,
            },
        }
        service = self.service()
        _, _, common = self.proposal(service, payload=payload, proposal_id="callback-task")
        config = DeepMathApprovalCallbackConfig(
            state_path=str(self.path), approver_user_id="approver", authorized_actor_ids=frozenset({"approver"}),
            token_signing_secret="stable-secret", resource_config_path="/controlled/resource.json", clock=lambda: self.now,
        )
        resource = DeepMathResourceConfig(
            tenant_key="deepmath", base_name="DeepMath CEO Thinking", tasklist_name="DeepMath CEO Actions",
            calendar_name="DeepMath CEO Calendar", timezone="Asia/Shanghai", base_id="base",
            tasklist_id="canonical-tasklist", calendar_id="calendar", base_url=None, tenant_proof="tenant",
        )

        class Transport:
            def create(self, body):
                self.body = body
                task = {"guid": "task", "url": "https://example.invalid/task", **body}
                return {"code": 0, "data": {"task": task}}, "create-request"

            def get(self, task_guid):
                return {"code": 0, "data": {"task": {"guid": task_guid, "url": "https://example.invalid/task", **self.body}}}, "read-request"

        resolved = {"status": "accepted", "workload_fingerprint": "fresh", "assignments": assignments}
        with patch.object(callback_module, "load_resource_config", return_value=resource), \
             patch.object(callback_module, "_resolve_people_selection", return_value=resolved), \
             patch.object(callback_module, "_project_audit_item", return_value=True), \
             patch("openclaw_app.services.deepmath_runtime_config.load_deepmath_account", return_value=("app", "secret")), \
             patch.object(callback_module.DeepMathTasksTransport, "from_app_credentials", return_value=Transport()):
            result = process_verified_callback({"transport_verified": True, "action": "approve", **common}, config)
        self.assertEqual(result["status"], "executed")
        self.assertEqual(result["execution_state"], "执行成功")

    def test_json_callback_cli_emits_only_safe_result(self):
        now = datetime.now(UTC)
        service = self.service(clock=lambda: now)
        created, _, common = self.proposal(service, expires_at=now + timedelta(hours=1), proposal_id="cli-proposal")
        config_path = Path(self.tempdir.name) / "deepmath.json"
        config_path.write_text(
            json.dumps({
                "deepmath_ceo_thinking": {
                    "approval_state_path": str(self.path),
                    "approver_open_id": "approver",
                    "approval_token_signing_secret": "stable-secret",
                }
            }),
            encoding="utf-8",
        )
        callback_path = Path(__file__).parents[1] / "openclaw_app/services/deepmath_approval_callback.py"
        completed = subprocess.run(
            [sys.executable, str(callback_path), "--config-path", str(config_path)],
            input=json.dumps({"transport_verified": True, "action": "save", **common}),
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0)
        output = json.loads(completed.stdout)
        self.assertEqual(output["status"], "saved")
        self.assertEqual(completed.stderr, "")
        self.assertNotIn("token", completed.stdout)
        self.assertNotIn("cli-proposal", completed.stdout)

    def test_modify_callback_returns_replacement_card_payload(self):
        service = self.service()
        _, _, common = self.proposal(service, proposal_id="modify-card-proposal")
        config = DeepMathApprovalCallbackConfig(
            state_path=str(self.path), approver_user_id="approver", authorized_actor_ids=frozenset({"approver"}),
            token_signing_secret="stable-secret", clock=lambda: self.now,
        )
        result = process_verified_callback(
            {
                "transport_verified": True,
                "action": "modify",
                **common,
                "new_payload": {"object_type": "任务", "action": "创建", "summary": "revised"},
            },
            config,
        )
        self.assertEqual(result["status"], "modified")
        self.assertIn("card", result)
        self.assertTrue(result["card"]["body"]["elements"][-1]["actions"])


if __name__ == "__main__":
    unittest.main()
