from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import unittest

import yaml

from openclaw_app.router.content_os_change_requests import (
    confirm_change_request,
    create_change_request,
    load_change_request,
    note_change_request,
)
from openclaw_app.router.content_os_change_router import ContentOSChangeRouterMixin
from openclaw_app.router.content_os_utils import ContentOSUtilsMixin
from openclaw_app.router.document_tools import DocumentToolsMixin
from openclaw_app.models.message import Message
from openclaw_app.router.content_os_project_lifecycle import (
    CONTENT_OS_SPEC_VERSION,
    ContentOSContractError,
    _read_frontmatter,
    _write_frontmatter,
    activate_confirmed_revision,
    read_project_state,
    transition_project_status,
)
from openclaw_app.router.content_os_projections import (
    build_feishu_project_projection,
    write_project_registry_projection,
)
from openclaw_app.router.content_os_feishu_projection import FeishuProjectBoardProjectionAdapter
from openclaw_app.router.content_os_queue import (
    accept_mac_result,
    create_ready_task,
    enqueue_confirmed_change,
    validate_mac_result,
)

from _fixtures.content_os_vault import make_content_os_vault


FIXED_NOW = datetime(2026, 7, 10, 8, 0, tzinfo=timezone.utc)


class ContentOSChangeHarness(ContentOSChangeRouterMixin, ContentOSUtilsMixin, DocumentToolsMixin):
    def __init__(self, vault_root: Path):
        self.vault_root = vault_root

    def _content_os_vault_root(self) -> Path:
        return self.vault_root


class GenericDocxPassThroughHarness(ContentOSChangeRouterMixin, ContentOSUtilsMixin, DocumentToolsMixin):
    def __init__(self, vault_root: Path):
        self.vault_root = vault_root
        self.generic_document_editor_called = False

    def _content_os_vault_root(self) -> Path:
        return self.vault_root

    @staticmethod
    def _extract_document_edit_target_url(_message: Message) -> tuple[str, str]:
        return "https://example.feishu.cn/docx/generic", "explicit_body_url"

    def _build_document_edit_request(self, _message: Message) -> dict[str, str]:
        self.generic_document_editor_called = True
        return {"target_doc_url": "", "edit_requirements": ""}


class FakeFeishuProjectBoardClient:
    def __init__(self, error: Exception | None = None):
        self.error = error
        self.calls: list[tuple[str, dict[str, str]]] = []

    def upsert_content_os_project(self, project_key: str, fields: dict[str, str]) -> None:
        self.calls.append((project_key, fields))
        if self.error is not None:
            raise self.error


class ContentOSV2Test(unittest.TestCase):
    @staticmethod
    def _write_evidence(root: Path, project_id: str, *names: str) -> None:
        project_dir = root / "08_内容项目" / project_id
        for name in names:
            (project_dir / name).write_text("evidence\n", encoding="utf-8")

    @staticmethod
    def _read_yaml(path: Path) -> dict:
        return yaml.safe_load(path.read_text(encoding="utf-8"))

    def test_lifecycle_writes_only_project_overview_and_not_registry(self) -> None:
        temporary, root, project_id = make_content_os_vault()
        with temporary:
            registry = root / "90_索引与注册表" / "project_registry.md"
            registry.parent.mkdir(parents=True)
            registry.write_text("manual projection must stay untouched\n", encoding="utf-8")
            self._write_evidence(root, project_id, "01_idea_card.md", "02_project_brief.md", "04_script.md")

            state = transition_project_status(
                root,
                project_id,
                to_status="planned",
                actor="cloud_openclaw",
                reason="项目说明与脚本已齐",
                evidence=set(),
                now=FIXED_NOW,
            )

            self.assertEqual(state.status, "planned")
            self.assertEqual(registry.read_text(encoding="utf-8"), "manual projection must stay untouched\n")
            self.assertIn("| planned |", (root / "08_内容项目" / project_id / "00_state_log.md").read_text(encoding="utf-8"))

    def test_mac_actor_cannot_advance_project_stage(self) -> None:
        temporary, root, project_id = make_content_os_vault()
        with temporary:
            self._write_evidence(root, project_id, "01_idea_card.md", "02_project_brief.md", "04_script.md")
            with self.assertRaisesRegex(ContentOSContractError, "Mac 回传"):
                transition_project_status(
                    root,
                    project_id,
                    to_status="planned",
                    actor="mac_openclaw",
                    reason="Mac 回传",
                    evidence=set(),
                    now=FIXED_NOW,
                )
            self.assertEqual(read_project_state(root, project_id).status, "captured")

    def test_publish_requires_recorded_human_confirmation_but_not_post_url(self) -> None:
        temporary, root, project_id = make_content_os_vault(status="final_ready")
        with temporary:
            with self.assertRaisesRegex(ContentOSContractError, "human_published_confirmation"):
                transition_project_status(
                    root,
                    project_id,
                    to_status="published",
                    actor="human",
                    reason="负责人确认已发布",
                    evidence={"human_published_confirmation"},
                    now=FIXED_NOW,
                )

            overview = root / "08_内容项目" / project_id / "00_项目总览.md"
            frontmatter, body = _read_frontmatter(overview)
            frontmatter["publication_confirmed_at"] = "2026-07-11"
            frontmatter["publication_confirmed_by"] = "负责人"
            _write_frontmatter(overview, frontmatter, body)

            state = transition_project_status(
                root,
                project_id,
                to_status="published",
                actor="human",
                reason="负责人确认已发布",
                evidence=set(),
                now=FIXED_NOW,
            )
            self.assertEqual(state.status, "published")

    def test_note_only_change_does_not_change_project_or_create_task(self) -> None:
        temporary, root, project_id = make_content_os_vault()
        with temporary:
            request = create_change_request(
                root,
                project_id,
                requested_location="开头三秒",
                requested_change="把第一句更换成结果先行",
                reason="降低理解门槛",
                urgency="normal",
                submitted_by="运营小王",
                editor_backend="handoff_pack",
                now=FIXED_NOW,
            )
            noted = note_change_request(root, request.change_request_id, noted_by="运营小王", now=FIXED_NOW)

            self.assertEqual(noted.status, "noted")
            self.assertEqual(read_project_state(root, project_id).project_revision, 1)
            self.assertFalse((root / "98_Agent任务队列" / "01_cloud_to_mac_ready").exists())

    def test_media_bot_project_note_only_collects_then_preserves_all_project_facts(self) -> None:
        temporary, root, project_id = make_content_os_vault()
        with temporary:
            harness = ContentOSChangeHarness(root)
            collect = harness.handle_修改(
                Message(
                    entry_tag="修改",
                    raw_text="",
                    body=(
                        f"项目编号：{project_id}\n想改哪里：开头三秒\n希望改成什么：第一句先给结果\n"
                        "为什么：让观众更快理解\n是否很着急：否\n参考说明：同类视频开头"
                    ),
                    source="feishu",
                    created_at=FIXED_NOW,
                )
            )
            request_id = str(collect.extra["content_os_change_request_id"])
            note = harness.handle_修改(
                Message(
                    entry_tag="修改",
                    raw_text="",
                    body=f"项目编号：{project_id}\n先记下",
                    source="feishu",
                    created_at=FIXED_NOW,
                )
            )

            request = load_change_request(root, request_id)
            self.assertEqual(collect.status, "content_os_change_pending_confirmation")
            self.assertEqual(note.status, "content_os_change_noted")
            self.assertEqual(request.status, "noted")
            self.assertEqual(request.payload["doc_type"], "content_revision_request")
            self.assertEqual(request.payload["base_revision"], 1)
            self.assertEqual(request.payload["target_revision"], 2)
            self.assertEqual(request.payload["execution_intent"], "note_only")
            self.assertEqual(read_project_state(root, project_id).status, "captured")
            self.assertEqual(read_project_state(root, project_id).project_revision, 1)
            self.assertFalse((root / "98_Agent任务队列" / "01_cloud_to_mac_ready").exists())

    def test_media_bot_bare_change_request_returns_title_based_form(self) -> None:
        temporary, root, project_id = make_content_os_vault()
        with temporary:
            harness = ContentOSChangeHarness(root)
            result = harness.handle_修改(
                Message(entry_tag="修改", raw_text="", body="修改项目", source="feishu", created_at=FIXED_NOW)
            )

            self.assertEqual(result.status, "content_os_change_missing_project")
            self.assertIn("项目：<从下面选择项目名称>", result.reply)
            self.assertIn("测试项目", result.reply)
            self.assertNotIn(project_id, result.reply)

    def test_media_bot_accepts_project_title_without_exposing_project_id(self) -> None:
        temporary, root, project_id = make_content_os_vault()
        with temporary:
            harness = ContentOSChangeHarness(root)
            result = harness.handle_修改(
                Message(
                    entry_tag="修改",
                    raw_text="",
                    body=(
                        "修改项目\n项目：测试项目\n想改哪里：开头三秒\n希望改成什么：第一句先给结果\n"
                        "为什么：让观众更快理解\n是否很着急：否"
                    ),
                    source="feishu",
                    created_at=FIXED_NOW,
                )
            )

            self.assertEqual(result.status, "content_os_change_pending_confirmation")
            self.assertIn("测试项目", result.reply)
            self.assertNotIn(project_id, result.reply)

    def test_media_bot_only_enqueues_after_explicit_now_modify(self) -> None:
        temporary, root, project_id = make_content_os_vault()
        with temporary:
            harness = ContentOSChangeHarness(root)
            result = harness.handle_修改(
                Message(
                    entry_tag="修改",
                    raw_text="",
                    body=(
                        f"项目编号：{project_id}\n想改哪里：第二段\n希望改成什么：删除重复口播\n"
                        "为什么：节奏太慢\n是否很着急：是\n现在修改"
                    ),
                    source="feishu",
                    created_at=FIXED_NOW,
                    metadata={"sender_name": "主编"},
                )
            )

            self.assertEqual(result.status, "content_os_change_execution_ready")
            self.assertEqual(read_project_state(root, project_id).status, "captured")
            self.assertEqual(read_project_state(root, project_id).project_revision, 2)
            ready = list((root / "98_Agent任务队列" / "01_cloud_to_mac_ready").glob("*.yaml"))
            self.assertEqual(len(ready), 1)
            task = self._read_yaml(ready[0])
            self.assertEqual(task["task_type"], "revise_local_edit_artifacts")
            self.assertEqual(task["allowed_actions"], ["apply_confirmed_revision"])
            self.assertTrue(task["human_confirmed_impact"])
            self.assertEqual(task["project_revision"], 2)

    def test_explicit_feishu_docx_stays_on_generic_document_path(self) -> None:
        temporary, root, _project_id = make_content_os_vault()
        with temporary:
            harness = GenericDocxPassThroughHarness(root)
            result = harness.handle_修改(
                Message(
                    entry_tag="修改",
                    raw_text="",
                    body="文档链接：https://example.feishu.cn/docx/generic\n修改要求：调整标题",
                    source="feishu",
                    created_at=FIXED_NOW,
                )
            )
            self.assertTrue(harness.generic_document_editor_called)
            self.assertEqual(result.status, "missing_target_document")

    def test_confirmed_change_increments_revision_and_uses_selected_backend(self) -> None:
        temporary, root, project_id = make_content_os_vault()
        with temporary:
            request = create_change_request(
                root,
                project_id,
                requested_location="第二段",
                requested_change="换成更短的口播",
                reason="节奏太慢",
                urgency="urgent",
                submitted_by="运营小王",
                editor_backend="handoff_pack",
                now=FIXED_NOW,
            )
            confirm_change_request(root, request.change_request_id, confirmed_by="主编", now=FIXED_NOW)
            task = enqueue_confirmed_change(
                root,
                request.change_request_id,
                task_type="generate_edit_handoff_pack",
                inputs={"script_path": "08_内容项目/20260710_测试项目/04_script.md"},
                allowed_actions=["generate_edit_handoff_pack"],
                now=FIXED_NOW,
            )

            state = read_project_state(root, project_id)
            self.assertEqual(state.status, "captured")
            self.assertEqual(state.project_revision, 2)
            self.assertEqual(state.editor_backend, "handoff_pack")
            self.assertEqual(task.project_revision, 2)
            self.assertEqual(task.change_request_id, request.change_request_id)
            self.assertEqual(load_change_request(root, request.change_request_id).status, "executing")

    def test_confirmed_change_rejects_task_for_other_backend_without_fallback(self) -> None:
        temporary, root, project_id = make_content_os_vault()
        with temporary:
            request = create_change_request(
                root,
                project_id,
                requested_location="转场",
                requested_change="增加转场",
                reason="节奏衔接",
                urgency="normal",
                submitted_by="运营小王",
                editor_backend="handoff_pack",
                now=FIXED_NOW,
            )
            confirm_change_request(root, request.change_request_id, confirmed_by="主编", now=FIXED_NOW)
            with self.assertRaisesRegex(ContentOSContractError, "不支持所选剪辑方式"):
                enqueue_confirmed_change(root, request.change_request_id, task_type="generate_otio_kdenlive_timeline", now=FIXED_NOW)
            self.assertEqual(read_project_state(root, project_id).project_revision, 1)

    def test_mac_result_with_wrong_revision_is_rejected_as_stale(self) -> None:
        temporary, root, project_id = make_content_os_vault(status="planned")
        with temporary:
            task = create_ready_task(
                root,
                project_id,
                task_type="local_material_match",
                project_revision=1,
                change_request_id="",
                editor_backend="handoff_pack",
                now=FIXED_NOW,
            )
            result = {
                "spec_version": CONTENT_OS_SPEC_VERSION,
                "doc_type": "mac_result",
                "task_id": task.task_id,
                "task_type": task.task_type,
                "completed_by": "mac_openclaw",
                "status": "done",
                "project_id": project_id,
                "project_revision": 2,
                "change_request_id": "",
                "editor_backend": "handoff_pack",
                "outputs": {},
            }
            with self.assertRaisesRegex(ContentOSContractError, "project_revision"):
                validate_mac_result(root, result)
            self.assertTrue(task.path.exists())

    def test_mac_result_cannot_propose_project_stage_and_accept_preserves_stage(self) -> None:
        temporary, root, project_id = make_content_os_vault(status="planned")
        with temporary:
            task = create_ready_task(
                root,
                project_id,
                task_type="local_material_match",
                project_revision=1,
                change_request_id="",
                editor_backend="handoff_pack",
                now=FIXED_NOW,
            )
            result = {
                "spec_version": CONTENT_OS_SPEC_VERSION,
                "doc_type": "mac_result",
                "task_id": task.task_id,
                "task_type": task.task_type,
                "completed_by": "mac_openclaw",
                "status": "done",
                "project_id": project_id,
                "project_revision": 1,
                "change_request_id": "",
                "editor_backend": "handoff_pack",
                "outputs": {"storyboard": "08_内容项目/20260710_测试项目/05_storyboard.md"},
            }
            invalid = {**result, "proposed_next_status": "edit_ready"}
            with self.assertRaisesRegex(ContentOSContractError, "不得提出"):
                validate_mac_result(root, invalid)

            accepted = accept_mac_result(root, result, now=FIXED_NOW)
            self.assertTrue(accepted.result_path.exists())
            self.assertTrue(accepted.done_task_path.exists())
            self.assertFalse(task.path.exists())
            self.assertEqual(read_project_state(root, project_id).status, "planned")
            self.assertEqual(self._read_yaml(accepted.done_task_path)["status"], "done")

    def test_same_mac_result_replay_is_idempotent_after_ack_loss(self) -> None:
        temporary, root, project_id = make_content_os_vault(status="planned")
        with temporary:
            task = create_ready_task(
                root,
                project_id,
                task_type="local_material_match",
                project_revision=1,
                change_request_id="",
                editor_backend="handoff_pack",
                now=FIXED_NOW,
            )
            result = {
                "spec_version": CONTENT_OS_SPEC_VERSION,
                "doc_type": "mac_result",
                "task_id": task.task_id,
                "task_type": task.task_type,
                "completed_by": "mac_openclaw",
                "status": "done",
                "project_id": project_id,
                "project_revision": 1,
                "change_request_id": "",
                "editor_backend": "handoff_pack",
                "outputs": {"report": "report.md"},
            }
            first = accept_mac_result(root, result, now=FIXED_NOW)
            replay = accept_mac_result(root, result, now=FIXED_NOW)
            self.assertEqual(replay.result_path, first.result_path)
            self.assertEqual(replay.done_task_path, first.done_task_path)
            with self.assertRaisesRegex(ContentOSContractError, "不同结果"):
                accept_mac_result(root, {**result, "outputs": {"report": "changed.md"}}, now=FIXED_NOW)

    def test_http_result_requires_the_authenticated_tenant_on_task_and_result(self) -> None:
        temporary, root, project_id = make_content_os_vault(status="planned")
        with temporary:
            task = create_ready_task(
                root,
                project_id,
                task_type="local_material_match",
                project_revision=1,
                change_request_id="",
                editor_backend="handoff_pack",
                tenant_id="tenant_a",
                now=FIXED_NOW,
            )
            result = {
                "spec_version": CONTENT_OS_SPEC_VERSION,
                "doc_type": "mac_result",
                "task_id": task.task_id,
                "task_type": task.task_type,
                "completed_by": "mac_openclaw",
                "status": "done",
                "project_id": project_id,
                "project_revision": 1,
                "change_request_id": "",
                "editor_backend": "handoff_pack",
                "tenant_id": "tenant_a",
                "outputs": {},
            }
            self.assertEqual(validate_mac_result(root, result, expected_tenant_id="tenant_a").task_id, task.task_id)
            with self.assertRaisesRegex(ContentOSContractError, "当前设备租户"):
                validate_mac_result(root, {**result, "tenant_id": "tenant_b"}, expected_tenant_id="tenant_a")
            with self.assertRaisesRegex(ContentOSContractError, "不属于当前设备租户"):
                validate_mac_result(root, result, expected_tenant_id="tenant_b")

    def test_registry_and_feishu_are_derived_projections(self) -> None:
        temporary, root, project_id = make_content_os_vault(status="editing", backend="otio_kdenlive")
        with temporary:
            registry_path = write_project_registry_projection(root)
            registry = registry_path.read_text(encoding="utf-8")
            projection = build_feishu_project_projection(read_project_state(root, project_id))

            self.assertIn("自动投影", registry)
            self.assertIn("| 20260710_测试项目 | 测试项目 | editing | 1 | otio_kdenlive", registry)
            self.assertEqual(projection["项目阶段"], "剪辑中")
            self.assertEqual(projection["剪辑方式"], "自动生成可编辑时间线")
            self.assertEqual(projection["负责人"], "小李")

    def test_feishu_adapter_projects_only_chinese_collaborator_fields(self) -> None:
        temporary, root, project_id = make_content_os_vault(status="editing", backend="handoff_pack")
        with temporary:
            project_dir = root / "08_内容项目" / project_id
            (project_dir / "02_project_brief.md").write_text(
                "---\nspec_version: content_os_v0.2\ndoc_type: project_brief\n---\n\n# 项目说明\n\n面向新手解释运动训练的真实体验。\n",
                encoding="utf-8",
            )
            (project_dir / "04_script.md").write_text(
                "---\nspec_version: content_os_v0.2\ndoc_type: script\n---\n\n# 脚本\n\n前两秒先给结果，再补充过程和感受。\n",
                encoding="utf-8",
            )
            (project_dir / "05_storyboard.md").write_text(
                "---\nspec_version: content_os_v0.2\ndoc_type: storyboard\n---\n\n# 镜头安排\n\n开场结果镜头、过程镜头、结尾反应镜头。\n",
                encoding="utf-8",
            )
            overview_path = project_dir / "00_项目总览.md"
            before = overview_path.read_text(encoding="utf-8")
            client = FakeFeishuProjectBoardClient()
            adapter = FeishuProjectBoardProjectionAdapter(client)

            result = adapter.sync(read_project_state(root, project_id))

            self.assertTrue(result["ok"])
            self.assertEqual(result["reply"], "飞书项目看板已更新为当前项目情况。")
            self.assertEqual(len(client.calls), 1)
            _project_key, fields = client.calls[0]
            self.assertIn("项目说明摘要", fields)
            self.assertIn("面向新手解释运动训练的真实体验", fields["项目说明摘要"])
            self.assertIn("前两秒先给结果", fields["脚本摘要"])
            self.assertIn("开场结果镜头", fields["镜头安排与剪辑说明摘要"])
            self.assertEqual(fields["剪辑方式"], "标准剪辑")
            self.assertIn("Media Bot", fields["提交修改"])
            self.assertIn("不直接修改项目", fields["提交修改"])
            self.assertEqual(fields["阻塞原因"], "")
            visible = "\n".join(f"{key}：{value}" for key, value in fields.items())
            self.assertNotIn(project_id, visible)
            self.assertNotIn("handoff_pack", visible)
            self.assertNotIn("project_revision", visible)
            self.assertNotIn("/", visible)
            self.assertEqual(overview_path.read_text(encoding="utf-8"), before)

    def test_feishu_projection_translates_system_owner_to_chinese_role(self) -> None:
        temporary, root, project_id = make_content_os_vault()
        with temporary:
            overview_path = root / "08_内容项目" / project_id / "00_项目总览.md"
            frontmatter, body = overview_path.read_text(encoding="utf-8").split("---", 2)[1:]
            data = yaml.safe_load(frontmatter)
            data.pop("owner")
            data["owner_agent"] = "cloud_openclaw"
            overview_path.write_text(
                "---\n" + yaml.safe_dump(data, allow_unicode=True, sort_keys=False).strip() + "\n---" + body,
                encoding="utf-8",
            )

            projection = build_feishu_project_projection(read_project_state(root, project_id))

            self.assertEqual(projection["负责人"], "云端协作")

    def test_feishu_adapter_hides_permission_error_and_never_exposes_raw_details(self) -> None:
        temporary, root, project_id = make_content_os_vault()
        with temporary:
            adapter = FeishuProjectBoardProjectionAdapter(FakeFeishuProjectBoardClient(PermissionError("403 raw secret")))

            result = adapter.sync(read_project_state(root, project_id))

            self.assertFalse(result["ok"])
            self.assertEqual(result["status"], "feishu_project_board_permission_required")
            self.assertNotIn("403", result["reply"])
            self.assertNotIn("secret", result["reply"])
            self.assertNotIn(project_id, result["reply"])

    def test_revision_activation_requires_human_confirmation(self) -> None:
        temporary, root, project_id = make_content_os_vault()
        with temporary:
            with self.assertRaisesRegex(ContentOSContractError, "人工确认"):
                activate_confirmed_revision(
                    root,
                    project_id,
                    expected_revision=1,
                    editor_backend="handoff_pack",
                    change_request_id="change_20260710_001",
                    human_confirmed_impact=False,
                    now=FIXED_NOW,
                )


if __name__ == "__main__":
    unittest.main()
