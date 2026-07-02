from __future__ import annotations

import json
import unittest
from datetime import datetime
from pathlib import Path

from openclaw_app.models.message import Message
from openclaw_app.router.system_routes import SystemRoutesMixin
from openclaw_app.router.tag_capabilities import TAG_CAPABILITIES
from openclaw_app.router.tag_router_common import BOT_CAPABILITY_IDENTITIES


class SystemRoutesHarness(SystemRoutesMixin):
    pass


FORBIDDEN_DESCRIPTION_TERMS = (
    "路由事实",
    "权限事实",
    "标签能力单一事实",
    "单一事实",
    "兼容",
    "回退",
    "fallback",
)
VALID_CAPABILITY_BOTS = {"任意 Bot", *BOT_CAPABILITY_IDENTITIES.values()}
CAPABILITY_DOC_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "capability_docs.json"
DOC_DIR = Path("/home/ubuntu/docs/说明书")


class SystemRoutesTest(unittest.TestCase):
    def _capability_result(self, account_id: str):
        message = Message(
            entry_tag="说明",
            raw_text="【说明】",
            body="",
            source="feishu",
            chat_type="private",
            created_at=datetime.now(),
            metadata={"account_id": account_id},
        )
        result = SystemRoutesHarness().handle_说明(message)
        self.assertTrue(result.ok)
        return result

    def _capability_reply(self, account_id: str) -> str:
        result = self._capability_result(account_id)
        return result.reply

    def _capability_doc_config(self) -> dict:
        return json.loads(CAPABILITY_DOC_CONFIG_PATH.read_text(encoding="utf-8"))

    def test_capability_bot_uses_feishu_account_id_metadata(self) -> None:
        message = Message(
            entry_tag="说明",
            raw_text="【说明】",
            body="",
            source="feishu",
            chat_type="private",
            created_at=datetime.now(),
            metadata={"account_id": "daily"},
        )

        bot_label = SystemRoutesHarness()._current_capability_bot(message)

        self.assertEqual(bot_label, "Daily bot")

    def test_capability_bot_rejects_compatibility_alias(self) -> None:
        message = Message(
            entry_tag="说明",
            raw_text="【说明】",
            body="",
            source="feishu",
            chat_type="private",
            created_at=datetime.now(),
            metadata={"account_id": "feishu-knowledge"},
        )

        bot_label = SystemRoutesHarness()._current_capability_bot(message)

        self.assertEqual(bot_label, "")

    def test_capability_description_requires_identity(self) -> None:
        message = Message(
            entry_tag="说明",
            raw_text="【说明】",
            body="",
            source="feishu",
            chat_type="private",
            created_at=datetime.now(),
            metadata={},
        )

        result = SystemRoutesHarness().handle_说明(message)

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "missing_bot_identity")

    def test_capability_description_does_not_infer_identity_from_source(self) -> None:
        message = Message(
            entry_tag="说明",
            raw_text="【说明】",
            body="",
            source="daily",
            chat_type="private",
            created_at=datetime.now(),
            metadata={},
        )

        result = SystemRoutesHarness().handle_说明(message)

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "missing_bot_identity")

    def test_capability_description_uses_unified_format(self) -> None:
        reply = self._capability_reply("daily")

        self.assertIn("入口事实：", reply)
        self.assertIn("当前 Bot：", reply)
        self.assertIn("完整说明文档：", reply)
        self.assertIn("当前 Bot 文档：", reply)
        self.assertIn("总文档：", reply)
        self.assertIn("输入写法：", reply)
        self.assertIn("当前 Bot 概览：", reply)
        self.assertIn("重点入口：", reply)
        self.assertIn("标签索引（", reply)
        self.assertIn("- `【说明】` 是所有 Bot 的唯一能力说明入口。", reply)
        self.assertIn("- `【说明】` 只返回能力说明文档链接和短入口，不执行归档、创作、入库或同步。", reply)
        self.assertIn("- 当前 Bot 只决定可用标签范围；`【说明】` 不是某个 Bot 的私有入口。", reply)
        self.assertIn("https://tcnwueberajc.feishu.cn/", reply)
        self.assertIn("- 最小格式：`【标签】正文内容`。", reply)
        self.assertIn("- 多字段格式：`【标签】\\n字段：内容\\n字段：内容`。", reply)
        self.assertIn("- `【待办】`", reply)
        self.assertLess(len(reply), 6000)
        self.assertNotIn("这是 Daily bot 的【说明】", reply)
        self.assertNotIn("只返回当前 Bot 的标签能力说明", reply)
        self.assertNotIn("完整能力详情（", reply)
        self.assertNotIn("完整能力标签（", reply)
        self.assertNotIn("  - 输入格式：", reply)
        self.assertNotIn("  - 适合场景：", reply)
        self.assertNotIn("  - 产出位置：", reply)
        self.assertNotIn("  - 用途：", reply)
        self.assertNotIn("  - 结果：", reply)
        self.assertNotIn("  - 示例：", reply)
        for term in FORBIDDEN_DESCRIPTION_TERMS:
            self.assertNotIn(term, reply)

    def test_capability_catalog_is_valid_for_description_generation(self) -> None:
        labels = [capability.label for capability in TAG_CAPABILITIES]
        self.assertEqual(len(labels), len(set(labels)))
        for retired_label in ("灵感-vlog", "创作-小红书", "创作-抖音", "素材创作-小红书", "素材创作-抖音", "完成", "延期", "取消"):
            self.assertNotIn(retired_label, labels)
        for canonical_label in ("灵感>vlog", "创作>小红书", "创作>抖音", "创作-拍摄执行", "素材创作>小红书", "素材创作>抖音", "认知"):
            self.assertIn(canonical_label, labels)
        for capability in TAG_CAPABILITIES:
            self.assertIn(capability.bot, VALID_CAPABILITY_BOTS)
            self.assertTrue(capability.label.strip())
            self.assertTrue(capability.purpose.strip())
            self.assertTrue(capability.result.strip())
            self.assertTrue(capability.example.strip())
            for term in FORBIDDEN_DESCRIPTION_TERMS:
                self.assertNotIn(term, capability.purpose)
                self.assertNotIn(term, capability.result)
                self.assertNotIn(term, capability.example)

    def test_retired_daily_status_tags_have_no_compatibility_branch(self) -> None:
        router_text = (Path(__file__).resolve().parents[1] / "openclaw_app/router/tag_router.py").read_text(encoding="utf-8")
        self.assertNotIn('{"完成", "延期", "取消"}', router_text)
        self.assertNotIn("deprecated_task_status_tag", router_text)
        self.assertNotIn("入口已废弃", router_text)

    def test_media_platform_and_content_type_are_decoupled(self) -> None:
        capabilities = {capability.label: capability for capability in TAG_CAPABILITIES}

        for label in ("创作>小红书", "创作>抖音", "素材创作>小红书", "素材创作>抖音"):
            with self.subTest(label=label):
                capability = capabilities[label]
                combined_text = "\n".join((capability.purpose, capability.result, capability.example))
                self.assertIn("图文", combined_text)
                self.assertIn("视频", combined_text)
                self.assertNotIn("默认视频", combined_text)
                self.assertNotIn("默认图文", combined_text)

        self.assertIn("类型=图文/视频", capabilities["创作>抖音"].example)
        self.assertIn("类型=图文/视频", capabilities["创作>小红书"].example)
        self.assertIn("类型=图文/视频", capabilities["素材创作>抖音"].example)
        self.assertIn("类型=图文/视频", capabilities["素材创作>小红书"].example)
        self.assertIn("平台=抖音 类型=图文/视频", capabilities["素材创作"].example)

        reply = self._capability_reply("media")
        self.assertIn("【素材创作】平台=抖音 类型=图文/视频", reply)
        self.assertIn("【创作>抖音】类型=图文/视频", reply)
        self.assertNotIn("默认视频", reply)
        self.assertNotIn("默认图文", reply)

        media_doc = (DOC_DIR / "OpenClaw Media bot 能力说明.md").read_text(encoding="utf-8")
        self.assertIn("小红书图文或视频", media_doc)
        self.assertIn("抖音图文或视频", media_doc)
        self.assertNotIn("默认视频", media_doc)
        self.assertNotIn("默认图文", media_doc)

    def test_all_bot_descriptions_link_docs_and_index_every_capability(self) -> None:
        harness = SystemRoutesHarness()
        for account_id, bot_label in BOT_CAPABILITY_IDENTITIES.items():
            with self.subTest(account_id=account_id):
                result = self._capability_result(account_id)
                reply = result.reply
                self.assertIn("capability_docs", result.extra)
                self.assertIn("当前 Bot 文档", result.extra["capability_docs"])
                self.assertIn("总文档", result.extra["capability_docs"])
                self.assertRegex(result.extra["capability_docs"]["当前 Bot 文档"]["url"], r"^https://tcnwueberajc\.feishu\.cn/")
                self.assertRegex(result.extra["capability_docs"]["总文档"]["url"], r"^https://tcnwueberajc\.feishu\.cn/")
                index = reply.split("标签索引", 1)[1]
                capabilities = harness._bot_capabilities(bot_label)
                for capability in capabilities:
                    self.assertIn(f"`【{capability.label}】`", index)
                for term in FORBIDDEN_DESCRIPTION_TERMS:
                    self.assertNotIn(term, reply)

    def test_capability_docs_group_dash_variants_and_render_details(self) -> None:
        reply = self._capability_reply("media")
        media_doc = (DOC_DIR / "OpenClaw Media bot 能力说明.md").read_text(encoding="utf-8")

        self.assertIn("- `【创作】`", reply)
        self.assertNotIn("完整能力详情", reply)
        self.assertIn("## 【灵感】 / 【灵感>vlog】", media_doc)
        self.assertIn("### 【灵感】", media_doc)
        self.assertIn("### 【灵感>vlog】", media_doc)
        self.assertIn("## 【拆解】 / 【拆解-再创】 / 【拆解-再创-简略】 / 【拆解-再创-详细】", media_doc)
        self.assertIn("### 【创作-灵感】", media_doc)
        self.assertIn("## 【素材创作】 / 【素材创作>小红书】 / 【素材创作>抖音】", media_doc)
        self.assertIn("### 【素材创作>抖音】", media_doc)
        self.assertIn("## 【转写】 / 【转写-文字】", media_doc)
        self.assertIn("### 【转写-文字】", media_doc)
        self.assertIn("- 用途：", media_doc)
        self.assertIn("- 产出：", media_doc)
        self.assertIn("- 输入格式：", media_doc)

    def test_bot_descriptions_include_domain_specific_guidance(self) -> None:
        expected = {
            "media": ("Content OS 工作流", "`【创作】`：根据平台、账号、类型、主体和发布时间生成可执行初稿。用法："),
            "daily": ("管理待办、日程、正式开发任务和今日执行清单", "`【待办】`：创建 Obsidian 待办清单或飞书提醒。用法："),
            "knowledge": ("把知识沉淀成可复用资产", "`【学习】`：自动判断解释类或整理类"),
            "social": ("沉淀人物交互、关系状态、人脉合作和社交复盘", "`【社交】`：整理某个人的聊天记录、互动状态、关系判断、风险点和下一步行动。用法："),
            "main": ("统一入口说明", "`【说明】`：查看当前统一入口说明。用法："),
        }
        for account_id, markers in expected.items():
            with self.subTest(account_id=account_id):
                reply = self._capability_reply(account_id)
                for marker in markers:
                    self.assertIn(marker, reply)

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
