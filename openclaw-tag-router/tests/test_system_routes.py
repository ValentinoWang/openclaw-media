from __future__ import annotations

import json
import unittest
from datetime import datetime
from pathlib import Path

from openclaw_app.models.message import Message
from openclaw_app.models.archive_entry import ArchiveEntry
from openclaw_app.router.system_routes import SystemRoutesMixin
from openclaw_app.router.tag_capabilities import TAG_CAPABILITIES
from openclaw_app.router.tag_router_common import BOT_CAPABILITY_IDENTITIES
from openclaw_app.services.capability_matcher import CapabilityMatcherError
from openclaw_app.services.capability_registry import CAPABILITY_REGISTRY


class SystemRoutesHarness(SystemRoutesMixin):
    def __init__(self, matcher=None) -> None:
        self.matcher = matcher
        self.plan_service = PassthroughGuidancePlanService()

    def _capability_matcher(self):
        if self.matcher is None:
            return super()._capability_matcher()
        return self.matcher

    def _guidance_plan_service(self):
        return self.plan_service


class PassthroughGuidancePlanService:
    def register_match(self, match: dict, **_: object) -> dict:
        return match


class StubMatcher:
    def __init__(self, response: dict) -> None:
        self.response = response
        self.requests: list[dict] = []

    def match(self, request: dict) -> dict:
        self.requests.append(request)
        return self.response


class RaisingMatcher:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def match(self, request: dict) -> dict:
        raise self.error


class ReadOnlyArchiveService:
    def __init__(self, entries: list[ArchiveEntry]) -> None:
        self.entries = entries
        self.save_calls = 0

    def list_archives(self, **_: object) -> list[ArchiveEntry]:
        return list(self.entries)

    def get_archive_by_id(self, record_id: str) -> ArchiveEntry | None:
        return next((entry for entry in self.entries if entry.frontmatter.get("id") == record_id), None)

    def save_archive(self, *_: object, **__: object) -> ArchiveEntry:
        self.save_calls += 1
        raise AssertionError("read-only system routes must not create archive records")


VALID_CAPABILITY_BOTS = {"任意 Bot", *BOT_CAPABILITY_IDENTITIES.values()}
CAPABILITY_DOC_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "capability_docs.json"


def matched_response(capability_id: str, *, summary: str, plan_id: str = "capplan_abcdefghijklmnop") -> dict:
    definition = CAPABILITY_REGISTRY.get(capability_id)
    assert definition is not None
    variant = definition.variants[0]
    return {
        "schemaVersion": "3", "pathStatus": "matched", "needSummary": summary,
        "routeExplanation": "模型将需求映射到 canonical capability registry。",
        "guidancePlanId": plan_id,
        "steps": [{
            "order": 1, "capabilityId": capability_id, "variantId": variant.variant_id,
            "extractedParams": {}, "confidence": 0.9, "evidence": [], "issues": [],
        }],
        "copyProjection": f"【{definition.label}】\n路径续接ID：{plan_id}",
    }


class SystemRoutesTest(unittest.TestCase):
    def _message(self, *, account_id: str = "media", body: str = "", metadata: dict | None = None) -> Message:
        return Message(
            entry_tag="说明",
            raw_text=f"【说明】{body}",
            body=body,
            source="feishu",
            chat_type="private",
            created_at=datetime.now(),
            metadata={"account_id": account_id} if metadata is None else metadata,
        )

    def _capability_doc_config(self) -> dict:
        return json.loads(CAPABILITY_DOC_CONFIG_PATH.read_text(encoding="utf-8"))

    def _archive_entry(self) -> ArchiveEntry:
        return ArchiveEntry(
            frontmatter={
                "id": "record_20260729",
                "entry_tag": "素材",
                "status": "archived",
                "created_at": "2026-07-29 22:00:00",
            },
            title="QA record",
            sections=[("正文", "验证纯读系统能力")],
            local_path="/controlled/archive/record_20260729.md",
        )

    def test_recent_records_is_a_true_read_and_never_archives_the_query(self) -> None:
        archive_service = ReadOnlyArchiveService([self._archive_entry()])
        harness = SystemRoutesHarness()
        harness.archive_service = archive_service
        message = self._message(body="1")
        message.entry_tag = "最近"

        result = harness.handle_最近(message)

        self.assertTrue(result.ok)
        self.assertEqual(result.status, "recent_records_listed")
        self.assertEqual(result.task_id, "")
        self.assertEqual(result.local_path, "")
        self.assertEqual(archive_service.save_calls, 0)

    def test_task_status_is_a_true_read_and_never_archives_the_query(self) -> None:
        archive_service = ReadOnlyArchiveService([self._archive_entry()])
        harness = SystemRoutesHarness()
        harness.archive_service = archive_service
        message = self._message(body="record_20260729")
        message.entry_tag = "状态"

        result = harness.handle_状态(message)

        self.assertTrue(result.ok)
        self.assertEqual(result.status, "task_status_returned")
        self.assertIn("任务ID：record_20260729", result.reply)
        self.assertEqual(result.task_id, "")
        self.assertEqual(result.local_path, "")
        self.assertEqual(archive_service.save_calls, 0)

    def test_capability_bot_uses_feishu_account_id_metadata(self) -> None:
        self.assertEqual(SystemRoutesHarness()._current_capability_bot(self._message(account_id="daily")), "Daily bot")
        self.assertEqual(SystemRoutesHarness()._current_capability_bot(self._message(account_id="feishu_deepmath")), "DeepMath bot")

    def test_capability_bot_rejects_compatibility_alias(self) -> None:
        self.assertEqual(SystemRoutesHarness()._current_capability_bot(self._message(metadata={"account_id": "feishu-knowledge"})), "")

    def test_empty_description_returns_only_the_two_document_lines(self) -> None:
        config = self._capability_doc_config()
        for account_id, bot_label in BOT_CAPABILITY_IDENTITIES.items():
            with self.subTest(account_id=account_id):
                result = SystemRoutesHarness().handle_说明(self._message(account_id=account_id))
                self.assertTrue(result.ok)
                self.assertEqual(result.status, "bot_capability_documents")
                if bot_label == "DeepMath bot":
                    self.assertEqual(
                        result.reply.splitlines(),
                        [f"{config['bots'][bot_label]['title']}：{config['bots'][bot_label]['url']}"],
                    )
                    self.assertNotIn(config["total"]["url"], result.reply)
                else:
                    self.assertEqual(
                        result.reply.splitlines(),
                        [
                            f"{config['total']['title']}：{config['total']['url']}",
                            f"{config['bots'][bot_label]['title']}：{config['bots'][bot_label]['url']}",
                        ],
                    )
                for removed_section in ("入口事实", "当前 Bot 概览", "重点入口", "标签索引", "输入写法"):
                    self.assertNotIn(removed_section, result.reply)

    def test_deepmath_empty_description_is_read_only_and_dedicated(self) -> None:
        matcher = StubMatcher(matched_response("deepmath_ceo_thinking_intake", summary="不应被调用"))
        archive_service = ReadOnlyArchiveService([self._archive_entry()])
        harness = SystemRoutesHarness(matcher)
        harness.archive_service = archive_service

        result = harness.handle_说明(self._message(account_id="deepmath"))

        self.assertTrue(result.ok)
        self.assertEqual(result.status, "bot_capability_documents")
        self.assertEqual(matcher.requests, [])
        self.assertEqual(archive_service.save_calls, 0)
        self.assertEqual(len(result.reply.splitlines()), 1)
        self.assertIn("DeepMath", result.reply)
        self.assertNotIn("OpenClaw 全部", result.reply)
        self.assertNotIn("Daily bot", result.reply)
        self.assertNotIn("Media bot", result.reply)

    def test_deepmath_nonempty_description_uses_deepmath_matcher_scope(self) -> None:
        matcher = StubMatcher(matched_response("deepmath_ceo_thinking_intake", summary="进入 DeepMath 思考收件入口。"))
        result = SystemRoutesHarness(matcher).handle_说明(
            self._message(account_id="deepmath", body="如何验证这个假设？")
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.status, "capability_match")
        self.assertEqual(matcher.requests, [{"query": "如何验证这个假设？", "currentBot": "deepmath"}])
        self.assertIn("进入 DeepMath 思考收件入口", result.reply)
        self.assertNotIn("OpenClaw 全部", result.reply)

    def test_explicit_bot_document_request_uses_the_requested_bot(self) -> None:
        config = self._capability_doc_config()
        result = SystemRoutesHarness().handle_说明(self._message(account_id="daily", body="media"))

        self.assertTrue(result.ok)
        self.assertEqual(result.status, "bot_capability_documents")
        self.assertEqual(
            result.reply.splitlines(),
            [
                f"{config['total']['title']}：{config['total']['url']}",
                f"{config['bots']['Media bot']['title']}：{config['bots']['Media bot']['url']}",
            ],
        )

    def test_description_requires_identity_when_no_target_bot_is_given(self) -> None:
        result = SystemRoutesHarness().handle_说明(self._message(metadata={}))

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "missing_bot_identity")

    def test_exact_capability_request_still_uses_llm_matcher(self) -> None:
        matcher = StubMatcher(matched_response("source_asset_intake", summary="使用素材入口整理本轮资料。"))
        result = SystemRoutesHarness(matcher).handle_说明(self._message(body="【素材】"))

        self.assertTrue(result.ok)
        self.assertEqual(result.status, "capability_match")
        self.assertEqual(matcher.requests, [{"query": "【素材】", "currentBot": "media"}])
        self.assertIn("需求理解：使用素材入口整理本轮资料。", result.reply)
        self.assertIn("直接复制填写：", result.reply)

    def test_every_recommendable_exact_capability_request_enters_matcher(self) -> None:
        recommendable = [
            definition for definition in CAPABILITY_REGISTRY.definitions
            if definition.enabled and set(definition.bots) & {"Media bot", "任意 Bot"}
        ]
        self.assertGreaterEqual(len(recommendable), 20)

        for definition in recommendable:
            with self.subTest(label=definition.label):
                plan_id = "capplan_abcdefghijklmnop"
                matcher = StubMatcher(matched_response(
                    definition.capability_id,
                    summary=f"按本轮需求使用【{definition.label}】。",
                    plan_id=plan_id,
                ))
                result = SystemRoutesHarness(matcher).handle_说明(
                    self._message(body=f"【{definition.label}】")
                )

                self.assertTrue(result.ok)
                self.assertEqual(result.status, "capability_match")
                self.assertEqual(
                    matcher.requests,
                    [{"query": f"【{definition.label}】", "currentBot": "media"}],
                )
                self.assertIn(f"需求理解：按本轮需求使用【{definition.label}】。", result.reply)

    def test_natural_language_request_uses_matcher_and_renders_copy_ready_guidance(self) -> None:
        matcher = StubMatcher(
            {
                "schemaVersion": "3",
                "pathStatus": "matched",
                "needSummary": "把视频拆解后改成小红书稿。",
                "routeExplanation": "先登记素材，再拆解结构，最后生成小红书稿。",
                "guidancePlanId": "capplan_abcdefghijklmnop",
                "steps": [
                    {"order": 1, "capabilityId": "source_asset_intake", "variantId": "default", "extractedParams": {"field_3be96f8eb83d": "视频"}, "confidence": 0.95, "evidence": [], "issues": []},
                    {"order": 2, "capabilityId": "creation_decision_brief", "variantId": "default", "extractedParams": {}, "confidence": 0.85, "evidence": [], "issues": [], "dependsOn": {"stepOrder": 1, "requiredOutputs": ["source_asset_id"]}},
                ],
                "copyProjection": "【素材】\n路径续接ID：capplan_abcdefghijklmnop\n素材类型：视频",
            }
        )
        result = SystemRoutesHarness(matcher).handle_说明(self._message(body="我有一条 AI 视频，想拆解后改成小红书稿"))

        self.assertTrue(result.ok)
        self.assertEqual(result.status, "capability_match")
        self.assertEqual(matcher.requests, [{"query": "我有一条 AI 视频，想拆解后改成小红书稿", "currentBot": "media"}])
        self.assertTrue(result.reply.startswith("需求理解："))
        self.assertIn("为什么是这些能力：", result.reply)
        self.assertIn("直接复制填写：", result.reply)
        self.assertIn("1. 【素材】", result.reply)
        self.assertIn("2. 【选题】", result.reply)
        self.assertIn("后续调用说明：", result.reply)
        self.assertIn("- 调用标签：`【选题】`", result.reply)
        self.assertIn("- 依赖字段：source_asset_id（由第 1 步真实结果自动绑定）", result.reply)
        self.assertNotIn("用途：", result.reply)
        self.assertNotIn("网页路径：", result.reply)

    def test_waiting_xiaohongshu_creation_shows_source_asset_call_contract(self) -> None:
        lines = SystemRoutesHarness()._format_waiting_capability_call(
            {"capabilityId": "selfmedia_creation"},
            {"stepOrder": 1, "requiredOutputs": ["source_asset_id"]},
        )

        self.assertEqual(
            lines,
            [
                "后续调用说明：",
                "- 调用标签：`【创作】`",
                "- 必填字段：平台、类型、赛道、主体",
                "- 依赖字段：source_asset_id（由第 1 步真实结果自动绑定）",
            ],
        )

    def test_unclear_path_shows_one_clarification_question_without_partial_matches(self) -> None:
        matcher = StubMatcher(
            {
                "schemaVersion": "3",
                "pathStatus": "needs_clarification",
                "needSummary": "这个需求包含多个彼此独立的目标。",
                "clarificationQuestion": "你希望优先完成内容创作、日程安排还是知识归档？",
                "candidates": [], "knownParams": {},
            }
        )
        result = SystemRoutesHarness(matcher).handle_说明(self._message(body="帮我把所有事情都处理好"))

        self.assertTrue(result.ok)
        self.assertEqual(result.status, "capability_needs_clarification")
        self.assertIn("需要你补充：你希望优先完成内容创作、日程安排还是知识归档？", result.reply)
        self.assertNotIn("1. 【", result.reply)

    def test_invalid_model_response_exposes_contract_failure_detail(self) -> None:
        result = SystemRoutesHarness(
            RaisingMatcher(
                CapabilityMatcherError(
                    "invalid_model_response",
                    "后续粘贴提示必须作为字段值出现，不能单独占一行。",
                )
            )
        ).handle_说明(self._message(account_id="daily", body="根据录音附件和散乱关键词整理内容"))

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "invalid_model_response")
        self.assertIn("错误代码：invalid_model_response", result.reply)
        self.assertIn("原因：能力匹配模型已返回结果，但结果未通过可执行指令契约校验。", result.reply)
        self.assertIn("详情：后续粘贴提示必须作为字段值出现，不能单独占一行。", result.reply)
        self.assertIn("建议：请直接重试原请求", result.reply)
        self.assertNotIn("能力匹配暂不可用，请稍后重试", result.reply)
        self.assertEqual(result.extra["matcher_error_detail"], "后续粘贴提示必须作为字段值出现，不能单独占一行。")

    def test_provider_error_is_distinguished_without_exposing_provider_secrets(self) -> None:
        result = SystemRoutesHarness(
            RaisingMatcher(
                CapabilityMatcherError(
                    "provider_unavailable",
                    "模型调用失败，底层敏感信息未向对话公开。",
                )
            )
        ).handle_说明(self._message(account_id="daily", body="帮我匹配能力"))

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "provider_unavailable")
        self.assertIn("错误代码：provider_unavailable", result.reply)
        self.assertIn("原因：能力匹配模型调用未完成，未取得可供校验的结果。", result.reply)
        self.assertIn("详情：模型调用失败，底层敏感信息未向对话公开。", result.reply)
        self.assertIn("建议：请稍后重试", result.reply)
        self.assertNotIn("能力匹配暂不可用，请稍后重试", result.reply)

    def test_capability_catalog_is_valid_for_matching(self) -> None:
        labels = [capability.label for capability in TAG_CAPABILITIES]
        self.assertEqual(len(labels), len(set(labels)))
        self.assertEqual(TAG_CAPABILITIES[-4].label, "说明")
        for capability in TAG_CAPABILITIES:
            self.assertIn(capability.bot, VALID_CAPABILITY_BOTS)
            self.assertTrue(capability.label.strip())
            self.assertTrue(capability.purpose.strip())
            self.assertTrue(capability.result.strip())
            self.assertTrue(capability.example.strip())

    def test_no_exact_capability_introduction_bypass_remains(self) -> None:
        source = Path(__file__).resolve().parents[1].joinpath("openclaw_app/router/system_routes.py").read_text(encoding="utf-8")
        self.assertNotIn("_explicit_capability", source)
        self.assertNotIn("_format_capability_introduction_reply", source)
        self.assertNotIn("capability_introduction", source)


if __name__ == "__main__":
    unittest.main()
