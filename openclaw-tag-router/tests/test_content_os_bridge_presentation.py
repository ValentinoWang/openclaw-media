from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

import yaml

from openclaw_app.models.message import Message
from openclaw_app.router.content_os_bridge import ContentOSBridgeMixin
from openclaw_app.router.content_os_project_lifecycle import CONTENT_OS_SPEC_VERSION, read_project_state
from openclaw_app.router.content_os_queue import RESULT_DIRECTORY
from openclaw_app.router.content_os_renderers import ContentOSRenderersMixin
from openclaw_app.router.content_os_state import ContentOSStateMixin
from openclaw_app.router.content_os_utils import ContentOSUtilsMixin


FIXED_NOW = datetime(2026, 8, 28, 8, 0, tzinfo=timezone.utc)
RAW_STAGES = ("captured", "planned", "edit_ready", "editing", "final_ready", "published")


class ContentOSBridgeHarness(ContentOSBridgeMixin, ContentOSStateMixin, ContentOSUtilsMixin, ContentOSRenderersMixin):
    def __init__(self, vault_root: Path) -> None:
        self.vault_root = vault_root

    def _content_os_vault_root(self) -> Path:
        return self.vault_root

    def _sync_content_os_feishu_project_board(self, _vault_root: Path, _project_id: str) -> None:
        return None


class ContentOSBridgePresentationTests(unittest.TestCase):
    def _make_vault(self, *, status: str = "editing") -> tuple[tempfile.TemporaryDirectory[str], Path, str]:
        temporary = tempfile.TemporaryDirectory()
        vault_root = Path(temporary.name)
        project_id = "20260828_测试项目"
        project_dir = vault_root / "08_内容项目" / project_id
        project_dir.mkdir(parents=True)
        rules = {
            "spec_version": CONTENT_OS_SPEC_VERSION,
            "project_statuses": list(RAW_STAGES),
            "transitions": {
                "editing_to_final_ready": {
                    "from": "editing",
                    "to": "final_ready",
                    "allowed_actor": "human",
                    "required_evidence": ["output_video_exists", "output_review_evidence_exists", "human_final_selected"],
                },
                "final_ready_to_published": {
                    "from": "final_ready",
                    "to": "published",
                    "allowed_actor": "human",
                    "required_evidence": ["human_published_confirmation"],
                },
            },
        }
        rules_path = vault_root / "00_入口与总览" / "state_transition_rules.yaml"
        rules_path.parent.mkdir(parents=True)
        rules_path.write_text(yaml.safe_dump(rules, allow_unicode=True, sort_keys=False), encoding="utf-8")
        overview = {
            "spec_version": CONTENT_OS_SPEC_VERSION,
            "doc_type": "project_overview",
            "project_id": project_id,
            "idea_id": "idea_20260828_001",
            "title": "测试项目",
            "status": status,
            "project_revision": 1,
            "editor_backend": "handoff_pack",
            "owner": "小李",
            "next_action": "提交成片质检",
            "blocked": False,
            "blocked_reason": "",
            "updated_at": "2026-08-28T08:00:00+00:00",
        }
        (project_dir / "00_项目总览.md").write_text(
            "---\n" + yaml.safe_dump(overview, allow_unicode=True, sort_keys=False).strip() + "\n---\n\n# 测试项目\n",
            encoding="utf-8",
        )
        return temporary, vault_root, project_id

    @staticmethod
    def _message(project_id: str, extra: str = "") -> Message:
        return Message(
            entry_tag="作品验收",
            raw_text=f"项目ID：{project_id}\n{extra}",
            body="请验收这条作品",
            source="test",
            chat_type="group",
            created_at=FIXED_NOW,
            metadata={},
        )

    @staticmethod
    def _accepted_output_review(project_id: str, **overrides: object) -> dict[str, object]:
        result: dict[str, object] = {
            "spec_version": CONTENT_OS_SPEC_VERSION,
            "doc_type": "mac_result",
            "task_id": "task_20260828_001",
            "task_type": "local_output_review",
            "completed_by": "mac_openclaw",
            "status": "done",
            "project_id": project_id,
            "project_revision": "1",
            "change_request_id": "",
            "editor_backend": "handoff_pack",
            "schema_version": "output_review_result.v1",
            "task_status": "success",
            "outputs": {"output_review": f"08_内容项目/{project_id}/07_output_review.md"},
            "local_outputs": {"metrics": "/Users/creator/Final.mp4"},
            "validation": {
                "output_review_nonempty": True,
                "metrics_json_parse_passed": True,
                "result_yaml_parse_passed": True,
                "human_final_ready_confirmation_required": True,
            },
            "accepted_by": "cloud_openclaw",
            "accepted_at": "2026-08-28T08:00:00+00:00",
        }
        result.update(overrides)
        return result

    @staticmethod
    def _write_result(vault_root: Path, filename: str, result: dict[str, object] | str) -> None:
        path = vault_root / RESULT_DIRECTORY / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(result, str):
            path.write_text(result, encoding="utf-8")
        else:
            path.write_text(yaml.safe_dump(result, allow_unicode=True, sort_keys=False), encoding="utf-8")

    def _apply_acceptance(self, harness: ContentOSBridgeHarness, project_id: str, extra: str = "") -> dict[str, object]:
        message = self._message(project_id, extra)
        if not extra:
            video_path = harness.vault_root / "Final.mp4"
            video_path.write_bytes(b"verified video")
            message = Message(
                entry_tag=message.entry_tag,
                raw_text=f"{message.raw_text}\n目标状态=final_ready",
                body=message.body,
                source=message.source,
                chat_type=message.chat_type,
                created_at=message.created_at,
                metadata={"content_os_acceptance": {
                    "output_video_path": str(video_path),
                    "output_review_evidence_exists": True,
                    "human_final_selected": True,
                }},
            )
        return harness._maybe_apply_content_os_work_acceptance(
            message,
            "通过",
            {},
            [],
        )

    def test_accepted_terminal_review_advances_with_creator_language(self) -> None:
        temporary, vault_root, project_id = self._make_vault()
        with temporary:
            self._write_result(vault_root, "stored-evidence.yaml", self._accepted_output_review(project_id))
            result = self._apply_acceptance(ContentOSBridgeHarness(vault_root), project_id)

            self.assertEqual(read_project_state(vault_root, project_id).status, "final_ready")
            self.assertEqual(result["from"], "editing")
            self.assertEqual(result["to"], "final_ready")
            self.assertEqual(result["reply"], "项目进度已更新：成片就绪。")
            for raw_stage in RAW_STAGES:
                self.assertNotIn(raw_stage, str(result["reply"]))

    def test_status_transition_helper_returns_machine_result_not_user_text(self) -> None:
        temporary, vault_root, project_id = self._make_vault()
        with temporary:
            advanced = ContentOSBridgeHarness(vault_root)._maybe_advance_content_os_status(
                project_id=project_id,
                from_status="editing",
                to_status="final_ready",
                actor="human",
                evidence={
                    "output_video_exists",
                    "output_review_evidence_exists",
                    "human_final_selected",
                },
                reason="作品验收通过",
                vault_root=vault_root,
            )

            self.assertIs(advanced, True)
            self.assertEqual(read_project_state(vault_root, project_id).status, "final_ready")

            not_advanced = ContentOSBridgeHarness(vault_root)._maybe_advance_content_os_status(
                project_id=project_id,
                from_status="editing",
                to_status="published",
                actor="human",
                evidence=set(),
                reason="重复推进",
                vault_root=vault_root,
            )
            self.assertIs(not_advanced, False)

    def test_chat_text_and_local_path_cannot_replace_accepted_review_evidence(self) -> None:
        temporary, vault_root, project_id = self._make_vault()
        with temporary:
            result = self._apply_acceptance(
                ContentOSBridgeHarness(vault_root),
                project_id,
                "成片路径：/Users/creator/Final.mp4\n作品验收：通过",
            )

            self.assertEqual(read_project_state(vault_root, project_id).status, "editing")
            self.assertEqual(result["reply"], "项目进度暂未更新：当前处于剪辑中，请明确下一步创作安排。")
            for raw_stage in RAW_STAGES:
                self.assertNotIn(raw_stage, str(result["reply"]))
            self.assertNotIn("状态机", str(result["reply"]))
            self.assertNotIn("->", str(result["reply"]))

    def test_unaccepted_malformed_and_nonterminal_results_do_not_advance(self) -> None:
        cases: tuple[tuple[str, dict[str, object] | str], ...] = (
            ("unaccepted-final.mp4.yaml", self._accepted_output_review("20260828_测试项目", accepted_by="")),
            ("malformed.yaml", "outputs: [\n"),
            ("nonterminal.yaml", self._accepted_output_review("20260828_测试项目", status="blocked", task_status="blocked")),
            ("macos-output.yaml", self._accepted_output_review("20260828_测试项目", outputs={"output_review": "/Users/creator/Final.mp4"})),
        )
        for filename, candidate in cases:
            with self.subTest(filename=filename):
                temporary, vault_root, project_id = self._make_vault()
                with temporary:
                    self._write_result(vault_root, filename, candidate)
                    result = self._apply_acceptance(ContentOSBridgeHarness(vault_root), project_id)

                    self.assertEqual(read_project_state(vault_root, project_id).status, "editing")
                    self.assertIn("剪辑中", str(result["reply"]))
                    self.assertNotIn("editing", str(result["reply"]))
                    self.assertNotIn("final_ready", str(result["reply"]))

    def test_data_review_receipt_uses_creator_language(self) -> None:
        temporary, vault_root, project_id = self._make_vault(status="final_ready")
        with temporary:
            result = ContentOSBridgeHarness(vault_root)._maybe_write_content_os_data_review(
                self._message(project_id, "发布链接：https://example.com/post/123"),
                {"record_id": "review_20260828_001"},
                "复盘内容",
            )

            self.assertIn("成片就绪", str(result["reply"]))
            for raw_stage in RAW_STAGES:
                self.assertNotIn(raw_stage, str(result["reply"]))

    def test_creation_project_receipt_hides_machine_identifiers_and_local_paths(self) -> None:
        reply = ContentOSBridgeHarness(Path("/tmp/content-os"))._creation_content_os_project_reply(
            {
                "project_id": "20260829_internal_project_001",
                "project_path": "/Users/creator/08_内容项目/20260829_internal_project_001",
                "task_path": "/Users/creator/tasks/task_internal_001.json",
            },
            {
                "reply": "Content OS 已写入：08_内容项目/20260829_internal_project_001/04_script.md",
                "script_path": "/Users/creator/08_内容项目/20260829_internal_project_001/04_script.md",
            },
        )

        self.assertEqual(reply, "创作项目已创建。\n创作内容已同步到项目档案。\n本地素材匹配任务已创建。")
        for internal_value in (
            "20260829_internal_project_001",
            "task_internal_001",
            "/Users/creator",
            "Content OS 已写入",
        ):
            self.assertNotIn(internal_value, reply)


if __name__ == "__main__":
    unittest.main()
