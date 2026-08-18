from __future__ import annotations

import json
import os
import signal
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

from openclaw_app.services import codex_maintenance_tasks

import codex_maintenance_worker


class CodexMaintenanceV2Test(unittest.TestCase):
    def test_sighup_requests_reload_without_interrupting_active_task(self) -> None:
        worker = codex_maintenance_worker.CodexMaintenanceWorker(root=Path("/tmp/codex-test"))
        handlers: dict[int, object] = {}

        def capture(signum: int, handler: object) -> None:
            handlers[signum] = handler

        with patch.object(codex_maintenance_worker.signal, "signal", side_effect=capture):
            worker.install_signal_handlers()

        handlers[signal.SIGHUP](signal.SIGHUP, None)
        self.assertTrue(worker.reload_requested)
        self.assertFalse(worker.stopping)

    def test_enqueue_requires_live_worker_and_writes_only_v2_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            codex_home = Path(directory) / "codex-home"
            codex_home.mkdir()
            (codex_home / "config.toml").write_text('model_provider = "test-provider"\n', encoding="utf-8")
            environment = {"OPENCLAW_CODEX_TASK_ROOT": directory, "CODEX_HOME": str(codex_home)}
            with patch.dict(os.environ, environment, clear=False):
                unavailable = codex_maintenance_tasks.enqueue_task(
                    "【codex】修复",
                    account_id="knowledge",
                    message_id="om_v2",
                    delivery={"channel": "feishu", "accountId": "knowledge", "target": "user:ou_test"},
                    notification_required=True,
                )
                self.assertEqual(unavailable["failureCode"], "codex_maintenance_worker_unavailable")
                self.assertFalse(any(Path(directory).glob("codex_*")))

                codex_maintenance_tasks.write_worker_health(Path(directory), pid=os.getpid())
                state = codex_maintenance_tasks.enqueue_task(
                    "【codex】修复",
                    account_id="knowledge",
                    message_id="om_v2",
                    delivery={"channel": "feishu", "accountId": "knowledge", "target": "user:ou_test"},
                    notification_required=True,
                )

            self.assertEqual(state["schemaVersion"], 2)
            self.assertEqual(state["plannedProvider"], "test-provider")
            self.assertEqual(state["plannedModel"], "gpt-5.6-sol")
            self.assertEqual(state["plannedThinking"], "high")
            self.assertEqual(state["delivery"]["target"], "user:ou_test")
            self.assertEqual(state["tenantProfile"], "default")
            self.assertNotIn("workerPid", state)

    def test_deepmath_task_freezes_tenant_profile_and_full_codex_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            codex_home = Path(directory) / "codex-home"
            codex_home.mkdir()
            (codex_home / "config.toml").write_text('model_provider = "test-provider"\n', encoding="utf-8")
            with patch.dict(os.environ, {"OPENCLAW_CODEX_TASK_ROOT": directory, "CODEX_HOME": str(codex_home)}, clear=False):
                codex_maintenance_tasks.write_worker_health(Path(directory), pid=os.getpid())
                state = codex_maintenance_tasks.enqueue_task(
                    "【codex】修改 https://wcno23y5j2nl.feishu.cn/wiki/test",
                    account_id="deepmath",
                    message_id="om_deepmath_codex",
                    delivery={"channel": "feishu", "accountId": "deepmath", "target": "user:ou_test"},
                    notification_required=True,
                )

            request = (Path(directory) / state["taskId"] / "request.md").read_text(encoding="utf-8")
            self.assertEqual(state["tenantProfile"], "deepmath")
            self.assertIn("Use only the DeepMath tenant credentials", request)
            self.assertIn("same full-access Codex maintenance and development capability", request)
            self.assertIn("Do not reject a local code or documentation task", request)
            self.assertIn("explicit Feishu wiki/docx URL", request)
            self.assertIn("User request (verbatim):", request)
            self.assertIn("wcno23y5j2nl.feishu.cn/wiki/test", request)

    def test_deepmath_local_document_development_does_not_require_feishu_url(self) -> None:
        request = codex_maintenance_tasks.agent_request(
            "【codex】修复并开发仓库内的算法说明文档",
            {"tenantProfile": "deepmath"},
        )

        self.assertIn("inspect and modify the relevant code, configuration, tests, Markdown", request)
        self.assertIn("Do not reject a local code or documentation task merely because it has no Feishu URL", request)
        self.assertIn("Apply the remaining document rules only when", request)
        self.assertIn("【codex】修复并开发仓库内的算法说明文档", request)

    def test_deepmath_execution_environment_replaces_shared_feishu_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / "deepmath.env"
            env_file.write_text(
                "OPENCLAW_STATE_DIR=/deepmath/state\n"
                "OPENCLAW_CONFIG_PATH=/deepmath/openclaw.json\n"
                "OPENCLAW_DEEPMATH_APP_ID=cli_deepmath\n"
                "OPENCLAW_DEEPMATH_APP_SECRET=secret\n",
                encoding="utf-8",
            )
            with patch.object(codex_maintenance_tasks, "DEEPMATH_ENV_FILE", env_file):
                env = codex_maintenance_tasks.execution_environment(
                    {"tenantProfile": "deepmath"},
                    {"PATH": "/bin", "FEISHU_APP_ID": "cli_main", "FEISHU_APP_SECRET": "main-secret"},
                )

            self.assertNotIn("FEISHU_APP_ID", env)
            self.assertNotIn("FEISHU_APP_SECRET", env)
            self.assertEqual(env["OPENCLAW_DEEPMATH_APP_ID"], "cli_deepmath")
            self.assertEqual(env["OPENCLAW_CONFIG_PATH"], "/deepmath/openclaw.json")

    def test_status_snapshot_rejects_v1_instead_of_compatibly_reading_it(self) -> None:
        task_id = "codex_" + "a" * 24
        with tempfile.TemporaryDirectory() as directory:
            task_dir = Path(directory) / task_id
            task_dir.mkdir()
            (task_dir / "state.json").write_text(
                json.dumps({"schemaVersion": 1, "taskId": task_id, "status": "succeeded"}),
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"OPENCLAW_CODEX_TASK_ROOT": directory}, clear=False):
                self.assertEqual(codex_maintenance_tasks.status_snapshot(task_id), {})

    def test_agent_command_is_direct_codex_full_access_with_fixed_model_and_effort(self) -> None:
        task_id = "codex_" + "b" * 24
        command = codex_maintenance_tasks.agent_command(Path("/tmp/task"), task_id, "test-provider")

        self.assertTrue(command[0].endswith("/codex"))
        self.assertEqual(command[1], "exec")
        self.assertIn("--dangerously-bypass-approvals-and-sandbox", command)
        self.assertEqual(command[command.index("--model") + 1], "gpt-5.6-sol")
        configs = [command[index + 1] for index, value in enumerate(command) if value == "--config"]
        self.assertEqual(configs, ['model_provider="test-provider"', 'model_reasoning_effort="high"'])
        self.assertEqual(command[-1], "-")
        self.assertNotIn("openclaw-maintenance", command)

    def test_agent_command_resumes_same_thread_without_replaying_request(self) -> None:
        task_id = "codex_" + "9" * 24
        thread_id = "019fc227-2202-7342-a04d-1c1c30704685"
        with patch.object(codex_maintenance_tasks, "session_path_for_thread", return_value=Path("/tmp/session")):
            command = codex_maintenance_tasks.agent_command(
                Path("/tmp/task"), task_id, "test-provider", resume_thread_id=thread_id
            )

        self.assertEqual(command[2], "resume")
        self.assertIn(thread_id, command)
        self.assertNotIn("--cd", command)
        self.assertNotEqual(command[-1], "-")
        self.assertIn("不要重复", command[-1])
        self.assertIn("你就是当前维护任务的执行者", command[-1])
        self.assertIn("不要读取、轮询或等待当前 task", command[-1])
        self.assertIn("state.json", command[-1])
        self.assertIn("events.jsonl", command[-1])
        self.assertIn("这些运行状态描述的是你自身", command[-1])

    def test_progress_notification_is_due_only_every_120_seconds(self) -> None:
        started = datetime(2026, 7, 22, 11, 0, tzinfo=UTC)
        state = {"startedAt": started.isoformat(), "lastProgressNotificationAt": ""}

        self.assertFalse(
            codex_maintenance_worker.progress_notification_due(
                state, now=started + timedelta(seconds=119), interval_seconds=120
            )
        )
        self.assertTrue(
            codex_maintenance_worker.progress_notification_due(
                state, now=started + timedelta(seconds=120), interval_seconds=120
            )
        )
        state["lastProgressNotificationAt"] = (started + timedelta(seconds=120)).isoformat()
        self.assertFalse(
            codex_maintenance_worker.progress_notification_due(
                state, now=started + timedelta(seconds=239), interval_seconds=120
            )
        )
        self.assertTrue(
            codex_maintenance_worker.progress_notification_due(
                state, now=started + timedelta(seconds=240), interval_seconds=120
            )
        )

    def test_runtime_contract_requires_exact_provider_model_and_thinking(self) -> None:
        runtime = {"provider": "test-provider", "model": "gpt-5.6-sol", "thinking": "high"}
        state = {"plannedProvider": "test-provider"}
        self.assertTrue(codex_maintenance_tasks.runtime_contract_matches(runtime, state))
        self.assertFalse(
            codex_maintenance_tasks.runtime_contract_matches(
                {**runtime, "model": "gpt-5.6-terra"}, state
            )
        )

    def test_feishu_delivery_uses_requester_private_target(self) -> None:
        payload = {
            "source": "feishu",
            "chat_type": "group",
            "metadata": {
                "account_id": "knowledge",
                "source_sender_id": "ou_requester",
                "source_conversation_id": "oc_group",
            },
        }
        self.assertEqual(
            codex_maintenance_tasks.delivery_from_payload(payload),
            {"channel": "feishu", "accountId": "knowledge", "target": "user:ou_requester"},
        )

    def test_progress_delivery_is_persisted_once_per_interval(self) -> None:
        task_id = "codex_" + "c" * 24
        with tempfile.TemporaryDirectory() as directory:
            task_dir = Path(directory) / task_id
            task_dir.mkdir()
            state = {
                "schemaVersion": 2,
                "taskId": task_id,
                "status": "running",
                "phase": "agent_running",
                "startedAt": (datetime.now(UTC) - timedelta(seconds=121)).isoformat(),
                "heartbeatAt": datetime.now(UTC).isoformat(),
                "plannedModel": "gpt-5.6-sol",
                "safeSummary": "running",
                "delivery": {"channel": "feishu", "accountId": "knowledge", "target": "user:ou_test"},
                "notificationState": "pending",
                "notifications": {},
            }
            codex_maintenance_tasks.write_state(task_dir, state)
            worker = codex_maintenance_worker.CodexMaintenanceWorker(root=Path(directory))
            sender = Mock(return_value={"message_id": "om_progress"})
            worker.send_feishu = sender

            worker.maybe_send_progress(task_dir, state)
            worker.maybe_send_progress(task_dir, state)

            persisted = codex_maintenance_tasks.read_state(task_dir)
            self.assertEqual(sender.call_count, 1)
            self.assertEqual(persisted["progressNotificationCount"], 1)
            self.assertEqual(persisted["notifications"]["lastProgress"]["messageId"], "om_progress")

    def test_model_capacity_failure_is_requeued_without_deleting_request(self) -> None:
        task_id = "codex_" + "e" * 24
        with tempfile.TemporaryDirectory() as directory:
            task_dir = Path(directory) / task_id
            task_dir.mkdir()
            request_path = task_dir / "request.md"
            request_path.write_text("【codex】执行维护", encoding="utf-8")
            codex_maintenance_tasks.write_state(
                task_dir,
                {
                    "schemaVersion": 2,
                    "taskId": task_id,
                    "status": "queued",
                    "phase": "queued",
                    "outcome": "pending",
                    "plannedModel": "gpt-5.6-sol",
                    "plannedProvider": "test-provider",
                    "delivery": {},
                    "notificationState": "disabled",
                    "attempt": 0,
                },
            )
            process = Mock(pid=1234, returncode=1)
            process.poll.return_value = 1

            def launch(*_args: object, **kwargs: object) -> Mock:
                stdout = kwargs["stdout"]
                stdout.write(
                    '{"type":"thread.started","thread_id":"019fc227-2202-7342-a04d-1c1c30704685"}\n'
                )
                stdout.write(
                    json.dumps(
                        {
                            "type": "turn.failed",
                            "error": {"message": "Selected model is at capacity. Please try a different model."},
                        }
                    )
                    + "\n"
                )
                stdout.flush()
                return process

            worker = codex_maintenance_worker.CodexMaintenanceWorker(root=Path(directory))
            with patch.object(codex_maintenance_worker.subprocess, "Popen", side_effect=launch):
                worker.process_task(task_dir)

            persisted = codex_maintenance_tasks.read_state(task_dir)
            self.assertEqual(persisted["status"], "queued")
            self.assertEqual(persisted["phase"], "agent_retry_wait")
            self.assertEqual(persisted["attempt"], 1)
            self.assertEqual(persisted["lastFailureCode"], "codex_maintenance_model_capacity")
            self.assertEqual(persisted["resumeThreadId"], "019fc227-2202-7342-a04d-1c1c30704685")
            self.assertIn("at capacity", persisted["lastFailureDetail"])
            self.assertTrue(persisted.get("nextAttemptAt"))
            self.assertTrue(request_path.exists())
            self.assertTrue((task_dir / "events.attempt-1.jsonl").exists())
            self.assertFalse((task_dir / "events.jsonl").exists())
            self.assertIsNone(worker.next_queued_task())
            persisted["nextAttemptAt"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
            codex_maintenance_tasks.write_state(task_dir, persisted)
            self.assertEqual(worker.next_queued_task(), task_dir)

    def test_model_capacity_retry_exhaustion_returns_specific_actionable_failure(self) -> None:
        task_id = "codex_" + "f" * 24
        with tempfile.TemporaryDirectory() as directory:
            task_dir = Path(directory) / task_id
            task_dir.mkdir()
            request_path = task_dir / "request.md"
            request_path.write_text("【codex】执行维护", encoding="utf-8")
            codex_maintenance_tasks.write_state(
                task_dir,
                {
                    "schemaVersion": 2,
                    "taskId": task_id,
                    "status": "queued",
                    "phase": "agent_retry_wait",
                    "outcome": "pending",
                    "plannedModel": "gpt-5.6-sol",
                    "plannedProvider": "test-provider",
                    "delivery": {},
                    "notificationState": "disabled",
                    "attempt": 2,
                },
            )
            process = Mock(pid=5678, returncode=1)
            process.poll.return_value = 1

            def launch(*_args: object, **kwargs: object) -> Mock:
                stdout = kwargs["stdout"]
                stdout.write(
                    '{"type":"thread.started","thread_id":"019fc227-2202-7342-a04d-1c1c30704685"}\n'
                    '{"type":"error","message":"Selected model is at capacity. Please try a different model."}\n'
                )
                stdout.flush()
                return process

            worker = codex_maintenance_worker.CodexMaintenanceWorker(root=Path(directory))
            with patch.object(codex_maintenance_worker.subprocess, "Popen", side_effect=launch):
                worker.process_task(task_dir)

            persisted = codex_maintenance_tasks.read_state(task_dir)
            self.assertEqual(persisted["status"], "failed")
            self.assertEqual(persisted["phase"], "model_capacity")
            self.assertEqual(persisted["failureCode"], "codex_maintenance_model_capacity")
            self.assertEqual(persisted["attempt"], 3)
            self.assertIn("at capacity", persisted["failureDetail"])
            self.assertIn("重新提交", persisted["suggestedAction"])
            self.assertFalse(request_path.exists())
            terminal = worker.terminal_text(persisted)
            self.assertIn("详情：Selected model is at capacity", terminal)
            self.assertIn("建议：模型容量恢复后重新提交", terminal)

    def test_capacity_after_tool_activity_keeps_same_resume_thread(self) -> None:
        events = "\n".join(
            [
                '{"type":"thread.started","thread_id":"019fc227-2202-7342-a04d-1c1c30704685"}',
                '{"type":"item.started","item":{"type":"command_execution"}}',
                '{"type":"error","message":"Selected model is at capacity. Please try a different model."}',
            ]
        )
        detail = codex_maintenance_worker.agent_failure_detail(events)

        self.assertTrue(codex_maintenance_worker.is_model_capacity_failure(detail))
        self.assertEqual(
            codex_maintenance_tasks.thread_id_from_events(events),
            "019fc227-2202-7342-a04d-1c1c30704685",
        )

    def test_terminal_delivery_failure_is_retried_from_persisted_state(self) -> None:
        task_id = "codex_" + "d" * 24
        with tempfile.TemporaryDirectory() as directory:
            task_dir = Path(directory) / task_id
            task_dir.mkdir()
            state = {
                "schemaVersion": 2,
                "taskId": task_id,
                "status": "failed",
                "phase": "agent_failed",
                "failureCode": "codex_maintenance_agent_failed",
                "safeSummary": "failed",
                "delivery": {"channel": "feishu", "accountId": "knowledge", "target": "user:ou_test"},
                "notificationState": "pending",
                "notifications": {},
            }
            codex_maintenance_tasks.write_state(task_dir, state)
            worker = codex_maintenance_worker.CodexMaintenanceWorker(root=Path(directory))
            worker.send_feishu = Mock(side_effect=[{"error": "gateway_down"}, {"message_id": "om_terminal"}])

            worker.maybe_send_terminal(task_dir, state)
            persisted = codex_maintenance_tasks.read_state(task_dir)
            self.assertEqual(persisted["notificationState"], "retrying")
            persisted["nextNotificationAttemptAt"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
            codex_maintenance_tasks.write_state(task_dir, persisted)
            worker.maybe_send_terminal(task_dir, persisted)

            delivered = codex_maintenance_tasks.read_state(task_dir)
            self.assertEqual(delivered["notificationState"], "sent")
            self.assertEqual(delivered["notifications"]["terminal"]["messageId"], "om_terminal")


if __name__ == "__main__":
    unittest.main()
