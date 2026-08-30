from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import yaml

from openclaw_app.app import OpenClawApp
from openclaw_app.router.tag_capabilities import TAG_CAPABILITIES
from openclaw_app.services.message_result_store import MessageResultStore
from openclaw_app.services.utils import parse_tag_message, parse_tag_message_with_metadata

from _support import load_script_module


def load_bridge_module():
    bridge_path = Path(__file__).resolve().parents[1] / "bridge.py"
    return load_script_module("openclaw_tag_router_bridge", bridge_path)


class BridgeProtocolTest(unittest.TestCase):
    def test_app_uses_daily_and_development_checklist_roots_independent_from_schedule_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = {
                "workspace_root": str(root / "workspace"),
                "source": "feishu",
                "chat_type": "private",
                "timezone": "Asia/Shanghai",
                "feishu": {"local_docs_dir": str(root / "docs")},
                "content_flow": {"base_url": ""},
                "mac_agent": {
                    "mode": "local",
                    "queue_dir": str(root / "queue"),
                    "obsidian_root": str(root / "obsidian" / "日程"),
                    "local_obsidian_root": str(root / "obsidian" / "日程"),
                },
                "daily_checklist": {"weekly_archive_root": str(root / "obsidian" / "Archieve")},
                "development_checklist": {"weekly_archive_root": str(root / "obsidian" / "Archieve")},
                "feishu_reminder": {"enabled": False},
            }
            settings_path = root / "settings.yaml"
            settings_path.write_text(yaml.safe_dump(settings, allow_unicode=True), encoding="utf-8")

            app = OpenClawApp(settings_path)

            service = app.router.obsidian_daily_checklist_service
            self.assertEqual(service.archive_root, root / "obsidian" / "Archieve")
            development_service = app.router.obsidian_development_checklist_service
            self.assertEqual(development_service.archive_root, root / "obsidian" / "Archieve")

    def test_normalizes_native_openclaw_timestamp_prefix_before_tag(self) -> None:
        bridge = load_bridge_module()

        text = bridge._normalize_tag_protocol_text("[Fri 2026-05-29 04:09 GMT+8] 【说明】")

        self.assertEqual(text, "【说明】")

    def test_leaves_plain_non_tag_text_untouched(self) -> None:
        bridge = load_bridge_module()

        text = bridge._normalize_tag_protocol_text("普通聊天")

        self.assertEqual(text, "普通聊天")

    def test_bridge_progress_writes_to_stderr_only(self) -> None:
        bridge = load_bridge_module()
        stderr = io.StringIO()

        with redirect_stderr(stderr):
            bridge._bridge_progress("route_start", mode="ingest", text_preview="【说明】")

        self.assertIn("[tag-router-bridge] stage=route_start", stderr.getvalue())
        self.assertIn("mode=ingest", stderr.getvalue())

    def test_exact_tags_are_kept_before_routing(self) -> None:
        self.assertEqual(parse_tag_message("【说明】media")[0], "说明")
        self.assertEqual(parse_tag_message("【自媒体知识】https://xhslink.com/xxx")[0], "自媒体知识")
        self.assertEqual(parse_tag_message("【衣橱】优衣库黑色速干T")[0], "衣橱")

    def test_business_author_parameter_tag_routes_to_id_business(self) -> None:
        tag, body = parse_tag_message("【商务>小王】辛苦填下")

        self.assertEqual(tag, "商务>ID")
        self.assertEqual(body, "作者ID：小王\n辛苦填下")


    def test_creator_profile_tags_route_directly(self) -> None:
        self.assertEqual(parse_tag_message("【博主】")[0], "博主")
        self.assertEqual(parse_tag_message("【博主-入库】平台ID：123")[0], "博主-入库")

    def test_transcription_text_tag_routes_directly(self) -> None:
        tag, body = parse_tag_message("【转写-文字】文字稿：今天讨论了项目安排")

        self.assertEqual(tag, "转写-文字")
        self.assertEqual(body, "文字稿：今天讨论了项目安排")

    def test_tag_thinking_suffix_is_metadata_not_route_tag(self) -> None:
        tag, body, metadata = parse_tag_message_with_metadata("【归档^high】一段资料")

        self.assertEqual(tag, "归档")
        self.assertEqual(body, "一段资料")
        self.assertEqual(metadata["raw_entry_tag"], "归档^high")
        self.assertEqual(metadata["tag_thinking_suffix"], "high")
        self.assertEqual(metadata["tag_thinking"], "high")

    def test_xhigh_tag_thinking_suffix_maps_to_supported_high(self) -> None:
        tag, body, metadata = parse_tag_message_with_metadata("【学习^xhigh】API")

        self.assertEqual(tag, "学习")
        self.assertEqual(body, "API")
        self.assertEqual(metadata["tag_thinking_suffix"], "xhigh")
        self.assertEqual(metadata["tag_thinking"], "high")

    def test_hyphen_is_no_longer_tag_thinking_suffix(self) -> None:
        tag, body, metadata = parse_tag_message_with_metadata("【归档-high】一段资料")

        self.assertEqual(tag, "归档-high")
        self.assertEqual(body, "一段资料")
        self.assertNotIn("tag_thinking", metadata)

    def test_codex_trigger_is_detected_anywhere(self) -> None:
        bridge = load_bridge_module()

        self.assertTrue(bridge._contains_codex_trigger("【codex】修复路由"))
        self.assertTrue(bridge._contains_codex_trigger("请处理【Codex】这个问题"))
        self.assertFalse(bridge._contains_codex_trigger("蒸馏 #codex 内容"))

    def test_codex_has_priority_over_every_registered_capability_in_either_tag_order(self) -> None:
        bridge = load_bridge_module()
        payload = {"source": "feishu", "metadata": {"account_id": "daily"}}
        messages = [
            message
            for capability in TAG_CAPABILITIES
            for message in (
                f"【codex】修改【{capability.label}】能力",
                f"【{capability.label}】请使用【codex】修改该能力",
            )
        ]
        delegated = {"ok": True, "status": "codex_maintenance_queued", "reply": "queued"}

        with patch.object(bridge, "_delegate_to_codex_maintenance", return_value=delegated) as delegate:
            for text in messages:
                with self.subTest(text=text):
                    response, cacheable = bridge._process_ingest(
                        payload,
                        text=text,
                        data_root=Path("/path-that-must-not-be-created"),
                        settings_path=Path("/settings-that-must-not-be-read.yaml"),
                    )
                    self.assertEqual(response, delegated)
                    self.assertTrue(cacheable)

        self.assertEqual(delegate.call_count, len(messages))
        self.assertEqual([call.args[0] for call in delegate.call_args_list], messages)

    def test_codex_delegate_queues_one_persistent_background_task_without_sync_wait(self) -> None:
        bridge = load_bridge_module()
        payload = {
            "source": "feishu",
            "metadata": {
                "account_id": "daily",
                "source_message_id": "om_codex_task_001",
                "source_sender_id": "ou_requester",
            },
        }

        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"OPENCLAW_CODEX_TASK_ROOT": directory}, clear=False):
                bridge.codex_maintenance_tasks.write_worker_health(Path(directory), pid=os.getpid())
                first = bridge._delegate_to_codex_maintenance("【codex】修复长任务", payload=payload)
                second = bridge._delegate_to_codex_maintenance("【codex】修复长任务", payload=payload)

            self.assertEqual(first["status"], "codex_maintenance_queued")
            self.assertEqual(first["task_id"], second["task_id"])
            task_dir = Path(directory) / first["task_id"]
            state_text = (task_dir / "state.json").read_text(encoding="utf-8")
            state = json.loads(state_text)
            self.assertEqual(state["schemaVersion"], 2)
            self.assertEqual(state["status"], "queued")
            self.assertEqual(state["delivery"]["target"], "user:ou_requester")
            self.assertNotIn("修复长任务", state_text)
            self.assertEqual((task_dir / "request.md").stat().st_mode & 0o777, 0o600)

    def test_codex_status_command_returns_only_safe_progress_fields(self) -> None:
        bridge = load_bridge_module()
        task_id = "codex_" + "a" * 24
        self.assertEqual(
            bridge.codex_maintenance_tasks.parse_status_task_id(f"【codex】状态 {task_id}"),
            task_id,
        )
        with tempfile.TemporaryDirectory() as directory:
            task_dir = Path(directory) / task_id
            task_dir.mkdir()
            state = {
                "schemaVersion": 2,
                "taskId": task_id,
                "status": "running",
                "phase": "agent_running",
                "toolType": "OpenClaw maintenance agent",
                "createdAt": "2026-07-22T00:00:00+00:00",
                "startedAt": "2026-07-22T00:00:00+00:00",
                "updatedAt": "2026-07-22T00:01:00+00:00",
                "heartbeatAt": "2026-07-22T00:01:00+00:00",
                "safeSummary": "维护代理仍在执行。",
                "outcome": "pending",
                "plannedModel": "gpt-5.6-sol",
            }
            (task_dir / "state.json").write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
            with patch.dict(os.environ, {"OPENCLAW_CODEX_TASK_ROOT": directory}, clear=False):
                result = bridge._codex_task_response(task_id)

        self.assertEqual(result["status"], "codex_maintenance_running")
        self.assertIn("阶段：agent_running", result["reply"])
        self.assertIn("工具类型：OpenClaw maintenance agent", result["reply"])
        self.assertNotIn("command", result["reply"].lower())
        self.assertNotIn("request", result["extra"])

    def test_codex_worker_termination_escalates_after_grace_period(self) -> None:
        bridge = load_bridge_module()
        proc = Mock(pid=9876)
        proc.poll.return_value = None
        proc.wait.side_effect = [subprocess.TimeoutExpired(["openclaw"], 15), None]

        with patch.object(bridge.codex_maintenance_tasks.os, "killpg") as killpg:
            bridge.codex_maintenance_tasks.terminate_process_group(proc, grace_seconds=15)

        self.assertEqual(
            killpg.call_args_list,
            [
                unittest.mock.call(9876, bridge.codex_maintenance_tasks.signal.SIGTERM),
                unittest.mock.call(9876, bridge.codex_maintenance_tasks.signal.SIGKILL),
            ],
        )

    def test_codex_failed_status_includes_code_detail_and_action(self) -> None:
        bridge = load_bridge_module()
        task_id = "codex_" + "9" * 24
        state = {
            "schemaVersion": 2,
            "taskId": task_id,
            "status": "failed",
            "phase": "model_capacity",
            "failureCode": "codex_maintenance_model_capacity",
            "safeSummary": "计划模型容量暂满；已重试 3 次。",
            "failureDetail": "Selected model is at capacity. Please try a different model.",
            "suggestedAction": "模型容量恢复后重新提交相同维护目标。",
            "plannedModel": "gpt-5.6-sol",
            "outcome": "failure",
        }

        result = bridge._codex_task_response(task_id, state)

        self.assertEqual(result["status"], "codex_maintenance_model_capacity")
        self.assertIn("详情：Selected model is at capacity", result["reply"])
        self.assertIn("建议：模型容量恢复后重新提交", result["reply"])

    def test_source_message_identity_accepts_plugin_and_history_backfill_keys(self) -> None:
        bridge = load_bridge_module()

        self.assertEqual(
            bridge._source_message_identity(
                {"metadata": {"account_id": "media", "source_message_id": "om_plugin"}}
            ),
            ("media", "om_plugin"),
        )
        self.assertEqual(
            bridge._source_message_identity(
                {"metadata": {"account_id": "media", "message_id": "om_history"}}
            ),
            ("media", "om_history"),
        )

    def test_message_result_identity_uses_background_execution_id_without_losing_source_identity(self) -> None:
        bridge = load_bridge_module()
        payload = {
            "metadata": {
                "account_id": "knowledge",
                "source_message_id": "om_original_audio",
                "message_result_id": "tr-job:full-payload-hash",
            }
        }

        self.assertEqual(
            bridge._source_message_identity(payload),
            ("knowledge", "om_original_audio"),
        )
        self.assertEqual(
            bridge._message_result_identity(payload),
            ("knowledge", "tr-job:full-payload-hash"),
        )

    def test_ingest_codex_trigger_delegates_before_tag_routing(self) -> None:
        bridge = load_bridge_module()
        text = "【转写】请使用【codex】修改会议纪要结构"
        payload = {"text": text}
        stdout = io.StringIO()
        delegate = Mock(return_value={"ok": True, "status": "delegated_to_codex_maintenance", "reply": "done"})

        with (
            patch.object(sys, "argv", ["bridge.py", "ingest", "/tmp/openclaw-test", "/tmp/missing-settings.yaml"]),
            patch.object(sys, "stdin", io.StringIO(json.dumps(payload))),
            patch.object(bridge, "_delegate_to_codex_maintenance", delegate),
            redirect_stderr(io.StringIO()),
            patch("sys.stdout", stdout),
        ):
            exit_code = bridge._main()

        self.assertEqual(exit_code, 0)
        self.assertEqual(json.loads(stdout.getvalue())["status"], "delegated_to_codex_maintenance")
        delegate.assert_called_once_with(text, payload=payload)

    def test_ingest_surfaces_business_guard_without_transport_failure(self) -> None:
        bridge = load_bridge_module()
        stdout = io.StringIO()
        guarded = SimpleNamespace(
            ok=False,
            status="guidance_url_missing",
            reply="路径续接未执行：待发送内容遗漏了原始需求中的链接。",
            task_id="",
            local_path="",
            feishu_doc="",
            extra={},
        )

        with (
            patch.object(sys, "argv", ["bridge.py", "ingest", "/tmp/openclaw-test", "/tmp/settings.yaml"]),
            patch.object(sys, "stdin", io.StringIO(json.dumps({"text": "【素材】路径续接ID：capplan_abcdefghijklmnop"}))),
            patch("openclaw_app.app.OpenClawApp", return_value=SimpleNamespace(process_text=lambda *_args, **_kwargs: guarded)),
            redirect_stderr(io.StringIO()),
            patch("sys.stdout", stdout),
        ):
            exit_code = bridge._main()

        response = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertTrue(response["ok"])
        self.assertEqual(response["status"], "guidance_url_missing")
        self.assertIn("遗漏了原始需求中的链接", response["reply"])

    def test_ingest_replays_success_for_the_same_feishu_message_id(self) -> None:
        bridge = load_bridge_module()
        calls = 0

        def process_text(*_args, **_kwargs):
            nonlocal calls
            calls += 1
            return SimpleNamespace(
                ok=True,
                status="created",
                reply="脚本文档：https://example.com/script",
                task_id="run_test",
                local_path="",
                feishu_doc="https://example.com/script",
                extra={},
            )

        payload = {
            "text": "【创作>抖音】\n主体：测试",
            "source": "feishu",
            "metadata": {"account_id": "media", "source_message_id": "om_bridge_replay_001"},
        }
        with tempfile.TemporaryDirectory() as directory:
            outputs = []
            with patch.dict(os.environ, {"OPENCLAW_TAG_ROUTER_MESSAGE_RESULT_ROOT": directory}):
                for _ in range(2):
                    stdout = io.StringIO()
                    with (
                        patch.object(sys, "argv", ["bridge.py", "ingest", "/tmp/openclaw-test", "/tmp/settings.yaml"]),
                        patch.object(sys, "stdin", io.StringIO(json.dumps(payload))),
                        patch("openclaw_app.app.OpenClawApp", return_value=SimpleNamespace(process_text=process_text)),
                        redirect_stderr(io.StringIO()),
                        patch("sys.stdout", stdout),
                    ):
                        self.assertEqual(bridge._main(), 0)
                    outputs.append(json.loads(stdout.getvalue()))

        self.assertEqual(calls, 1)
        self.assertEqual(outputs[0], outputs[1])
        self.assertEqual(outputs[1]["status"], "created")
        self.assertIn("脚本文档", outputs[1]["reply"])

    def test_background_execution_id_isolated_from_conflicting_source_message_cache(self) -> None:
        bridge = load_bridge_module()
        calls = 0

        def process_text(*_args, **_kwargs):
            nonlocal calls
            calls += 1
            return SimpleNamespace(
                ok=True,
                status="archived",
                reply="转写完成",
                task_id="transcription_test",
                local_path="/tmp/archive.md",
                feishu_doc="",
                extra={},
            )

        payload = {
            "text": "【转写】",
            "source": "feishu",
            "metadata": {
                "account_id": "knowledge",
                "source_message_id": "om_historical_audio",
                "message_result_id": "tr-background-job:0123456789abcdef",
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            MessageResultStore(Path(directory)).execute_once(
                account_id="knowledge",
                message_id="om_historical_audio",
                text="<media:document> (历史录音.m4a)",
                operation=lambda: ({"ok": True, "status": "ignored", "reply": "普通消息"}, True),
            )
            outputs = []
            with patch.dict(os.environ, {"OPENCLAW_TAG_ROUTER_MESSAGE_RESULT_ROOT": directory}):
                for _ in range(2):
                    stdout = io.StringIO()
                    with (
                        patch.object(sys, "argv", ["bridge.py", "ingest", "/tmp/openclaw-test", "/tmp/settings.yaml"]),
                        patch.object(sys, "stdin", io.StringIO(json.dumps(payload))),
                        patch(
                            "openclaw_app.app.OpenClawApp",
                            return_value=SimpleNamespace(process_text=process_text),
                        ),
                        redirect_stderr(io.StringIO()),
                        patch("sys.stdout", stdout),
                    ):
                        self.assertEqual(bridge._main(), 0)
                    outputs.append(json.loads(stdout.getvalue()))

        self.assertEqual(calls, 1)
        self.assertEqual(outputs[0], outputs[1])
        self.assertEqual(outputs[1]["status"], "archived")

    def test_codex_delegate_uses_completed_runtime_model_and_replaces_static_label(self) -> None:
        bridge = load_bridge_module()
        task_id = "codex_" + "c" * 24
        state = {
            "taskId": task_id,
            "status": "succeeded",
            "phase": "completed",
            "runtimeModel": "openai/gpt-runtime",
            "reply": "模型编号：legacy-static-model\n\n已完成",
            "outcome": "success",
        }

        result = bridge._codex_task_response(task_id, state)

        self.assertTrue(result["ok"])
        self.assertEqual(result["extra"]["runtime_model"], "openai/gpt-runtime")
        self.assertEqual(result["reply"], "模型：openai/gpt-runtime\n\n已完成")

    def test_codex_runtime_contract_uses_provider_independent_session_transcript(self) -> None:
        bridge = load_bridge_module()
        thread_id = "019f899b-8a4e-71c3-90f8-5734c7c6022c"
        events = json.dumps({"type": "thread.started", "thread_id": thread_id})
        with tempfile.TemporaryDirectory() as directory:
            session_dir = Path(directory) / "sessions" / "2026" / "07" / "22"
            session_dir.mkdir(parents=True)
            session_path = session_dir / f"rollout-test-{thread_id}.jsonl"
            session_path.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {"type": "session_meta", "payload": {"model_provider": "test-provider"}}
                        ),
                        json.dumps(
                            {
                                "type": "turn_context",
                                "payload": {"model": "gpt-5.6-sol", "effort": "high"},
                            }
                        ),
                    ]
                ),
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"CODEX_HOME": directory}, clear=False):
                runtime = bridge.codex_maintenance_tasks.extract_runtime_contract(events)

        self.assertEqual(
            runtime,
            {"provider": "test-provider", "model": "gpt-5.6-sol", "thinking": "high"},
        )

    def test_codex_delegate_pre_run_failure_uses_safe_model_label(self) -> None:
        bridge = load_bridge_module()
        payload = {
            "source": "feishu",
            "metadata": {
                "account_id": "daily",
                "source_message_id": "om_codex_failure",
                "source_sender_id": "ou_requester",
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"OPENCLAW_CODEX_TASK_ROOT": directory}, clear=False):
                result = bridge._delegate_to_codex_maintenance("【codex】修复", payload=payload)

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "codex_maintenance_worker_unavailable")
        self.assertTrue(result["reply"].startswith("计划模型：gpt-5.6-sol\n\n"))
        self.assertNotIn("运行时模型不可用", result["reply"])


if __name__ == "__main__":
    unittest.main()
