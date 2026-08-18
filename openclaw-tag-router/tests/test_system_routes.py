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

    def _capability_doc_config(self) -> dict:
        return json.loads(CAPABILITY_DOC_CONFIG_PATH.read_text(encoding="utf-8"))

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

    def test_knowledge_description_includes_common_entry_cheatsheet(self) -> None:
        reply = self._capability_reply("knowledge")
        inspiration_index = "`【灵感】`：归档碎片想法和未来可展开的内容线，输入：`【灵感】` 后按填写模板补充内容，输出：详文写入 Obsidian `灵感/归档/`，周记 `# 灵感` 凝练宏观总结、5句内摘要和详情链接"

        expected = (
            "重点入口：",
            inspiration_index,
            "`【归档】`：整理知识、资料片段、网页摘录或零散观点，写入 Obsidian 周记 `# 知识`。用法：`【归档】需要归档的一段知识`",
            "`【补全】`：整理已有转写文字或口语化记录，去重复、补结构、保留关键细节，写入周记 `# 认知`。用法：`【补全】\\n主题：...\\n原文：已经转出来的文字稿`。",
            "`【认知】`：整理经历、反思或判断；详文写 `认知/`，周记留宏观总结、5句摘要和链接。用法：`【认知】今天意识到：...`",
            "`【学习】`：自动判断解释类或整理类",
            "`【学习-整理】`：强制按整理类沉淀长资料、课程笔记、文章、AI 回答",
            "`【自媒体知识】`：处理图文、视频或网页链接",
            "用法：`【自媒体知识】\\n链接：https://...\\n平台：小红书\\n备注：重点提取选题方法`。",
            "`【转写】`：处理上传录音，生成逐字稿、总结、Obsidian 会议纪要和原字稿",
            "用法：先上传录音附件，再发 `【转写】`",
            "`【转写-文字】`：整理和合并已经由语音转文字得到的文字稿，生成总结、待解决问题、说话人标注、Obsidian 会议纪要和原字稿",
            "用法：`【转写-文字】\\n主题：...\\n文字稿：...`",
            "`【说明】`：查看当前 Bot 能力说明文档。用法：`【说明】`",
        )
        for marker in expected:
            self.assertIn(marker, reply)
        self.assertIn(inspiration_index, self._capability_reply("main"))

    def test_all_bot_descriptions_include_common_entry_usage(self) -> None:
        expected = {
            "media": ("重点入口：", "`【创作】`：根据平台、账号、类型、主体和发布时间生成可执行初稿。用法："),
            "daily": ("重点入口：", "`【待办】`：创建 Obsidian 待办清单或飞书提醒。用法："),
            "knowledge": ("重点入口：", "`【归档】`：整理知识、资料片段、网页摘录或零散观点，写入 Obsidian 周记 `# 知识`。用法："),
            "social": ("重点入口：", "`【社交】`：整理某个人的聊天记录、互动状态、关系判断、风险点和下一步行动。用法："),
            "main": ("重点入口：", "`【说明】`：查看当前统一入口说明。用法："),
        }
        for account_id, markers in expected.items():
            with self.subTest(account_id=account_id):
                reply = self._capability_reply(account_id)
                for marker in markers:
                    self.assertIn(marker, reply)

    def test_all_bot_common_entries_are_structured_without_fixed_count(self) -> None:
        for account_id in BOT_CAPABILITY_IDENTITIES:
            with self.subTest(account_id=account_id):
                reply = self._capability_reply(account_id)
                section = reply.split("重点入口：", 1)[1].split("\n\n标签索引", 1)[0]
                lines = [line for line in section.splitlines() if line.startswith("- `【")]

                self.assertGreater(len(lines), 0)
                for line in lines:
                    self.assertIn("：", line)
                    self.assertIn("。用法：", line)
                    self.assertRegex(line, r"^- `【[^】]+】`：.+。用法：.+")

    def test_social_description_exposes_creator_profile_lookup_for_business_homepage(self) -> None:
        reply = self._capability_reply("social")

        self.assertIn("`【博主】`", reply)
        self.assertIn("主页链接", reply)
        self.assertIn("商务邀约前查询已归档博主的主页链接", reply)
        self.assertIn("`【博主-入库】`", reply)

    def test_capability_doc_links_precede_label_index(self) -> None:
        for account_id in BOT_CAPABILITY_IDENTITIES:
            with self.subTest(account_id=account_id):
                reply = self._capability_reply(account_id)
                docs_index = reply.find("完整说明文档：")
                label_index = reply.find("标签索引（")
                self.assertGreaterEqual(docs_index, 0)
                self.assertGreater(label_index, docs_index)
                self.assertNotIn("完整能力标签（", reply)
                self.assertNotIn("完整能力详情（", reply)

    def test_generated_capability_docs_cover_bot_labels(self) -> None:
        harness = SystemRoutesHarness()
        config = self._capability_doc_config()
        total_doc = Path(config["total"]["local_path"]).read_text(encoding="utf-8")
        inspiration_index = "`【灵感】`：归档碎片想法和未来可展开的内容线，输入：`【灵感】` 后按填写模板补充内容，输出：详文写入 Obsidian `灵感/归档/`，周记 `# 灵感` 凝练宏观总结、5句内摘要和详情链接"
        knowledge_doc = Path(config["bots"]["Knowledge bot"]["local_path"]).read_text(encoding="utf-8")
        self.assertIn(inspiration_index, total_doc)
        self.assertIn(inspiration_index, knowledge_doc)
        for capability in TAG_CAPABILITIES:
            section_start = total_doc.find(f"### 【{capability.label}】")
            self.assertGreaterEqual(section_start, 0, msg=f"missing total doc detail for {capability.label}")
            next_section = total_doc.find("\n### ", section_start + 1)
            section = total_doc[section_start : next_section if next_section > 0 else len(total_doc)]
            self.assertIn("- 用途：", section)
            self.assertIn("- 产出：", section)
            self.assertIn("- 输入格式：", section)
        for bot_label, entry in config["bots"].items():
            with self.subTest(bot_label=bot_label):
                doc = Path(entry["local_path"]).read_text(encoding="utf-8")
                self.assertRegex(entry["url"], r"^https://tcnwueberajc\.feishu\.cn/")
                for capability in harness._bot_capabilities(bot_label):
                    self.assertIn(f"### 【{capability.label}】", doc)


if __name__ == "__main__":
    unittest.main()
