from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


TAG_ROUTER_ROOT = Path(__file__).resolve().parents[1]
SELFMEDIA_ROOT = TAG_ROUTER_ROOT.parents[0]
for path in (SELFMEDIA_ROOT, TAG_ROUTER_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from openclaw_app.models.message import Message
from openclaw_app.models.task import TaskResult
from openclaw_app.router.media_growth import MediaGrowthMixin
from openclaw_app.router.tag_capabilities import COLLECT_ALIAS_LABELS, TAG_CAPABILITIES
from openclaw_app.router.tag_router import TagRouter
from selfmedia.growth.capability_registry import MEDIA_GROWTH_LABEL_CAPABILITIES
from selfmedia.growth import service as growth_service

TEST_TENANT_ID = "00000000-0000-4000-8000-000000000001"


def _tenant_vault_root(root: str | Path) -> Path:
    return Path(root) / "tenants" / TEST_TENANT_ID


class FakeGrowthContentFlowClient:
    def analyze(self, url: str, **_kwargs):
        return {
            "status": "done",
            "media_type": "article",
            "analysis": {
                "source_url": url,
                "media_type": "article",
                "analysis_provider": "test-source-extractor",
                "full_content": "校园体育内容需要明确受众、场景和可验证案例。",
            },
        }

    def _call_profile_provider_json(self, profile_name: str, prompt: str, user_content: str, stage: str, **_kwargs):
        if "commercial_brief" in user_content:
            return {
                "status": "done",
                "brand": "上海灵瑙科技",
                "project_name": "2026 WAIC 展会体验视频",
                "products": [
                    {
                        "name": "上海灵瑙科技沉境睡眠仪",
                        "coverage": "睡眠仪细节展示，强调脑电监测和闭环神经调控。",
                    },
                    {
                        "name": "启学象限 MindBCI 脑电耳机",
                        "coverage": "专注度检测、脑控艺术和脑控机器狗体验。",
                    },
                ],
                "platforms": ["小红书", "抖音", "视频号"],
                "content_format": "第一视角展会探秘体验原创视频",
                "duration_requirement": "120 秒以上",
                "locations": [
                    {
                        "name": "沉境睡眠仪展位",
                        "venue": "世博展馆地下一层 Future Tech 展区 FT-D019",
                    },
                    {
                        "name": "脑控机器狗竞速挑战展位",
                        "venue": "徐汇西岸会展中心 TechJoy 科技消费嘉年华",
                    },
                ],
                "required_brand_mentions": ["上海灵瑙科技沉境睡眠仪", "启学象限 MindBCI 脑电耳机"],
                "must_cover": ["睡眠仪细节", "专注度检测艺术体验", "脑机接口控制机器狗竞速"],
                "narrative_direction": ["第一视角探秘", "突出脑控因果链", "同台对比只能一句带过"],
                "interaction_design": ["博主亲身佩戴设备体验", "字幕解释脑电信号采集到响应链条"],
                "compliance_restrictions": ["不得暗示医疗诊断功能", "不得贬低或质疑技术真实性", "不得给其他公司 logo 特写"],
                "deliverables": [
                    {"type": "video", "spec": "MP4，1080P 以上，2 分钟以上，500MB 以内"},
                    {"type": "image", "spec": "6 张，3:4"},
                    {"type": "materials", "spec": "脚本、文案、成片及相关素材"},
                ],
                "technical_specs": {"format": "MP4", "ratio": "16:9 或 9:16", "resolution": ">=1080P", "max_size": "500MB"},
                "approval_requirements": ["脚本、文案、成片发布前提交甲方书面确认"],
                "cleaned_brief": "上海灵瑙科技 2026 WAIC 展会体验视频 brief，核心是第一视角体验两个展位。",
                "risk_notes": ["原始 brief 有 OCR 噪声，部分字词需品牌方最终确认"],
                "next_content_actions": ["进入 shooting_execution_plan"],
                "source_evidence": [{"kind": "pasted_commercial_brief", "status": "provided_by_user"}],
                "display_title": "上海灵瑙科技｜2026 WAIC 展会体验视频 Brief",
                "display_summary": "已整理平台、产品、展位、必拍、禁忌、交付和审批要求。",
            }
        if "external_research_brief" in user_content:
            return {
                "status": "done",
                "research_question": "校园体育内容是否值得做？",
                "media_goal": "判断是否进入选题。",
                "audience_relevance": "受众关注训练场景和可验证案例。",
                "content_opportunity": "可以从训练复盘切入。",
                "usable_angles": ["400 米训练复盘"],
                "unusable_angles": ["不编造成绩数据"],
                "risk_notes": ["需要人工复核"],
                "next_content_actions": ["进入 creation_decision_brief"],
                "source_evidence": [{"kind": "knowledge_evidence", "source_url": "https://example.com/source", "status": "ready"}],
                "display_title": "校园体育内容机会",
                "display_summary": "基于 typed evidence 形成调研 brief。",
            }
        if "publishing_pack_build" in user_content:
            return {
                "status": "done",
                "title": "400 米训练复盘",
                "cover_text": "训练不是鸡血",
                "caption": "一次 400 米训练，最重要的是看见复盘指标。",
                "hashtags": ["短跑", "训练复盘"],
                "comment_seed": "你复盘训练时最看重什么？",
                "publish_checklist": ["确认事实来源", "人工确认后发布"],
                "risk_notes": ["不自动发布"],
                "display_title": "400 米训练复盘发布包",
                "display_summary": "整理标题、封面和正文。",
            }
        return {
            "status": "done",
            "decision_goal": "判断下周选题。",
            "topic_candidates": [
                {
                    "title": "400 米训练为什么要复盘",
                    "target_audience": "校园跑者",
                    "audience_pain": "训练有效但不知道怎么复盘",
                    "content_angle": "用一场训练讲复盘方法",
                    "single_problem": "如何判断一次训练有没有价值",
                    "self_check": "必须引用 typed evidence",
                    "source_refs": ["media://source_assets/test/result.json"],
                }
            ],
            "recommended_next_capability_id": "selfmedia_creation",
            "risk_or_missing_info": ["需要人工确认拍摄素材"],
            "display_title": "400 米训练复盘选题",
            "display_summary": "基于证据生成一个候选选题。",
        }


class MediaGrowthRouteHarness(TagRouter):
    def __init__(self) -> None:
        self.source = "feishu"
        self.chat_type = "private"
        self.timezone = "Asia/Shanghai"
        self.content_flow_client = FakeGrowthContentFlowClient()
        self.captured_delegate = False
        self.captured_shooting_execution: Message | None = None

    def _delegate_to_knowledge_bot(self, message: Message, *, thinking_level: str) -> TaskResult:
        self.captured_delegate = True
        return TaskResult(ok=True, status="delegated", reply=f"delegated:{thinking_level}", task_id="")

    def handle_shooting_execution(self, message: Message) -> TaskResult:
        self.captured_shooting_execution = message
        return TaskResult(
            ok=True,
            status="shooting_execution_created",
            reply="delegated shooting execution",
            task_id="shooting-run-test",
            extra={"raw_text": message.raw_text},
        )

    def route(self, tag: str, body: str, created_at=None, *, source=None, chat_type=None, metadata=None) -> TaskResult:
        authenticated_metadata = dict(metadata or {})
        if str(authenticated_metadata.get("account_id") or "").strip() == "media":
            authenticated_metadata.setdefault("tenant_id", TEST_TENANT_ID)
        return super().route(
            tag,
            body,
            created_at,
            source=source,
            chat_type=chat_type,
            metadata=authenticated_metadata,
        )


class MediaGrowthV2RegistryTests(unittest.TestCase):
    def test_growth_labels_have_v2_registry_fields(self) -> None:
        capabilities = {item.label: item for item in TAG_CAPABILITIES}
        expected = {
            "策略": ("account_track_strategy", "Strategy"),
            "Brief": ("commercial_brief", "Decide"),
            "素材": ("source_asset_intake", "Collect"),
            "调研": ("external_research_brief", "Decide"),
            "选题": ("creation_decision_brief", "Decide"),
            "拍摄": ("shooting_execution_plan", "Create"),
            "润色": ("style_polish_run", "Polish"),
            "检查": ("creation_checklist_lookup", "Verify"),
            "发布包": ("publishing_pack_build", "Publish"),
            "复核": ("media_growth_review", "Verify"),
            "复盘": ("post_review_signal", "Learn"),
            "账号": ("owned_media_account_lookup", "Entity"),
            "赛道": ("track_registry_lookup", "Entity"),
        }
        for label, (canonical, layer) in expected.items():
            with self.subTest(label=label):
                capability = capabilities[label]
                self.assertEqual(capability.canonical_capability_id, canonical)
                self.assertEqual(capability.lifecycle_layer, layer)
                self.assertTrue(capability.produces)
                self.assertIn(capability.risk_level, {"low", "medium", "high", "destructive"})
                self.assertIn(capability.visibility, {"public", "ops", "maintainer", "hidden"})
                self.assertIn(capability.default_mode, {"reply_only", "reply_and_persist", "confirm_then_persist", "persist_and_update_status"})

    def test_source_asset_has_no_collect_aliases(self) -> None:
        capabilities = {item.label: item for item in TAG_CAPABILITIES}
        self.assertEqual(COLLECT_ALIAS_LABELS, ())
        self.assertEqual(capabilities["素材"].canonical_capability_id, "source_asset_intake")
        self.assertEqual(capabilities["素材"].aliases, ())
        for label in ("活动", "转写", "转写-文字", "灵感>vlog"):
            with self.subTest(label=label):
                self.assertIn(label, capabilities)
                self.assertNotIn(label, COLLECT_ALIAS_LABELS)

    def test_unknown_source_asset_like_labels_are_unsupported(self) -> None:
        router = MediaGrowthRouteHarness()
        result = router.route("素材入口", "平台=抖音 链接=https://example.com/a", metadata={"account_id": "media"})
        self.assertFalse(result.ok)
        self.assertEqual(result.status, "unsupported_tag")
        self.assertEqual(result.task_id, "")

    def test_publishing_pack_registry_is_not_platform_publish(self) -> None:
        capability = next(item for item in TAG_CAPABILITIES if item.label == "发布包")
        self.assertEqual(capability.canonical_capability_id, "publishing_pack_build")
        self.assertNotIn("platform_publish_action", capability.writes_to)
        self.assertIn("PublishingPack", capability.produces)
        self.assertIn("PublishReadinessGate", capability.produces)
        self.assertFalse(capability.requires_confirmation)

    def test_media_growth_research_route_does_not_delegate_to_knowledge_in_media_context(self) -> None:
        router = MediaGrowthRouteHarness()
        with tempfile.TemporaryDirectory() as tmp:
            old_root = os.environ.get("OPENCLAW_MEDIA_VAULT_ROOT")
            os.environ["OPENCLAW_MEDIA_VAULT_ROOT"] = tmp
            try:
                result = router.route(
                    "调研",
                    "账号=小王 平台=抖音 赛道=校园体育 问题=这个链接能不能做 https://www.douyin.com/video/7654247930551244785",
                    metadata={"account_id": "media"},
                )
            finally:
                if old_root is None:
                    os.environ.pop("OPENCLAW_MEDIA_VAULT_ROOT", None)
                else:
                    os.environ["OPENCLAW_MEDIA_VAULT_ROOT"] = old_root

        self.assertTrue(result.ok)
        self.assertFalse(router.captured_delegate)
        self.assertEqual(result.extra["canonical_capability_id"], "external_research_brief")
        self.assertIn("ExternalResearchBrief", result.reply)

    def test_retired_research_labels_are_unsupported_in_media_context(self) -> None:
        router = MediaGrowthRouteHarness()

        for label in ("复杂调研", "深度调研", "研究"):
            with self.subTest(label=label):
                result = router.route(label, "主题=测试", metadata={"account_id": "media"})
                self.assertFalse(result.ok)
                self.assertEqual(result.status, "unsupported_tag")

        self.assertEqual(MEDIA_GROWTH_LABEL_CAPABILITIES["调研"], "external_research_brief")
        self.assertNotIn("复杂调研", MEDIA_GROWTH_LABEL_CAPABILITIES)
        self.assertNotIn("深度调研", MEDIA_GROWTH_LABEL_CAPABILITIES)

    def test_commercial_brief_route_structures_and_persists_brand_brief(self) -> None:
        router = MediaGrowthRouteHarness()
        with tempfile.TemporaryDirectory() as tmp:
            old_root = os.environ.get("OPENCLAW_MEDIA_VAULT_ROOT")
            os.environ["OPENCLAW_MEDIA_VAULT_ROOT"] = tmp
            try:
                result = router.route(
                    "Brief",
                    "平台=抖音 Brief=上海灵瑙科技 2026 WAIC 展会体验视频拍摄要求：必须覆盖沉境睡眠仪和 MindBCI 脑电耳机。",
                    metadata={"account_id": "media"},
                )
                payload = json.loads((_tenant_vault_root(tmp) / "commercial_briefs" / result.task_id / "result.json").read_text(encoding="utf-8"))
            finally:
                if old_root is None:
                    os.environ.pop("OPENCLAW_MEDIA_VAULT_ROOT", None)
                else:
                    os.environ["OPENCLAW_MEDIA_VAULT_ROOT"] = old_root

        self.assertTrue(result.ok)
        self.assertEqual(result.status, "media_growth_done")
        self.assertEqual(result.extra["canonical_capability_id"], "commercial_brief")
        self.assertEqual(payload["artifact_type"], "CommercialBrief")
        self.assertEqual(payload["brand"], "上海灵瑙科技")
        self.assertIn("上海灵瑙科技沉境睡眠仪", payload["required_brand_mentions"])
        self.assertIn(f"media://tenants/{TEST_TENANT_ID}/commercial_briefs/", payload["artifact_uri"])
        self.assertIn(f"拍摄执行续跑指令：发送【拍摄】source=media://tenants/{TEST_TENANT_ID}/commercial_briefs/", result.reply)

    def test_research_route_is_unsupported_outside_media_context(self) -> None:
        router = MediaGrowthRouteHarness()

        result = router.route("调研", "某个行业问题", metadata={"account_id": "feishu-knowledge"})

        self.assertFalse(result.ok)
        self.assertFalse(router.captured_delegate)
        self.assertEqual(result.status, "unsupported_tag")

    def test_source_string_does_not_grant_media_research_access(self) -> None:
        router = MediaGrowthRouteHarness()
        router.source = "media"

        result = router.route("调研", "某个行业问题", metadata={})

        self.assertFalse(result.ok)
        self.assertFalse(router.captured_delegate)
        self.assertEqual(result.status, "unsupported_tag")

    def test_shooting_label_delegates_to_existing_shooting_execution_path(self) -> None:
        router = MediaGrowthRouteHarness()

        result = router.route("拍摄", "平台=抖音 主题=400米训练", metadata={"account_id": "media"})

        self.assertTrue(result.ok)
        self.assertEqual(result.status, "shooting_execution_created")
        self.assertIsNotNone(router.captured_shooting_execution)
        assert router.captured_shooting_execution is not None
        self.assertEqual(router.captured_shooting_execution.entry_tag, "创作-拍摄执行")
        self.assertTrue(router.captured_shooting_execution.raw_text.startswith("【创作-拍摄执行】"))
        self.assertIn("主题=400米训练", router.captured_shooting_execution.raw_text)

    def test_full_chain_request_uses_executable_default_subset(self) -> None:
        router = MediaGrowthRouteHarness()
        with tempfile.TemporaryDirectory() as tmp:
            old_root = os.environ.get("OPENCLAW_MEDIA_VAULT_ROOT")
            os.environ["OPENCLAW_MEDIA_VAULT_ROOT"] = tmp
            try:
                result = router.route("素材", "请给我完整发布方案", metadata={"account_id": "media"})
                self.assertTrue((_tenant_vault_root(tmp) / "source_assets").exists())
                self.assertTrue((_tenant_vault_root(tmp) / "decision_briefs").exists())
            finally:
                if old_root is None:
                    os.environ.pop("OPENCLAW_MEDIA_VAULT_ROOT", None)
                else:
                    os.environ["OPENCLAW_MEDIA_VAULT_ROOT"] = old_root

        self.assertTrue(result.ok)
        self.assertEqual(result.status, "media_growth_done")
        self.assertEqual(result.extra["workflow_plan"]["workflow_mode"], "preset_flow")
        self.assertEqual(
            [node["canonical_capability_id"] for node in result.extra["workflow_plan"]["planned_nodes"]],
            ["source_asset_intake", "creation_decision_brief"],
        )
        self.assertEqual(result.extra["artifact"]["preset_flow"], "asset_to_topic")

    def test_explicit_activity_to_shooting_flow_reuses_source_asset_then_delegates_shooting(self) -> None:
        router = MediaGrowthRouteHarness()
        with tempfile.TemporaryDirectory() as tmp:
            old_root = os.environ.get("OPENCLAW_MEDIA_VAULT_ROOT")
            os.environ["OPENCLAW_MEDIA_VAULT_ROOT"] = tmp
            try:
                result = router.route("素材", "流程=activity_brief_to_shooting 主题=毕业季田径赛", metadata={"account_id": "media"})
                self.assertTrue((_tenant_vault_root(tmp) / "source_assets").exists())
                self.assertTrue((_tenant_vault_root(tmp) / "decision_briefs").exists())
            finally:
                if old_root is None:
                    os.environ.pop("OPENCLAW_MEDIA_VAULT_ROOT", None)
                else:
                    os.environ["OPENCLAW_MEDIA_VAULT_ROOT"] = old_root

        self.assertTrue(result.ok)
        self.assertEqual(result.status, "media_growth_external_delegation_required")
        self.assertIn("计划节点：", result.reply)
        self.assertIn("可执行：source_asset_intake", result.reply)
        self.assertIn("可执行：creation_decision_brief", result.reply)
        self.assertIn("既有链路：shooting_execution_plan", result.reply)
        self.assertIn("已写入产物：2 个", result.reply)
        self.assertIn(f"续跑指令：发送【拍摄】source=media://tenants/{TEST_TENANT_ID}/decision_briefs/", result.reply)
        node_statuses = result.extra["artifact"]["planned_node_statuses"]
        self.assertEqual(node_statuses[0]["canonical_capability_id"], "source_asset_intake")
        self.assertTrue(node_statuses[0]["implemented"])
        self.assertEqual(node_statuses[2]["implementation_status"], "external")
        self.assertEqual(
            [item["source_capability_id"] for item in result.extra["artifact"]["preset_node_results"]],
            ["source_asset_intake", "creation_decision_brief"],
        )

    def test_media_review_tag_is_not_growth_runner(self) -> None:
        mixin = MediaGrowthMixin()
        message = Message(
            entry_tag="复盘",
            raw_text="【复盘】平台=小红书 播放=1000 点赞=100",
            body="平台=小红书 播放=1000 点赞=100",
            metadata={"account_id": "media"},
        )

        self.assertFalse(mixin._media_growth_should_handle(message))

    def test_explicit_review_signal_flow_routes_to_growth_and_next_topic(self) -> None:
        router = MediaGrowthRouteHarness()
        with tempfile.TemporaryDirectory() as tmp:
            old_root = os.environ.get("OPENCLAW_MEDIA_VAULT_ROOT")
            os.environ["OPENCLAW_MEDIA_VAULT_ROOT"] = tmp
            try:
                result = router.route(
                    "复盘",
                    "流程=metrics_to_next_topics 平台=小红书 播放=1000 收藏=300 结论=收藏明显高于点赞 下一步=做收藏理由拆解",
                    metadata={"account_id": "media"},
                )
                self.assertTrue((_tenant_vault_root(tmp) / "review_signals").exists())
                self.assertTrue((_tenant_vault_root(tmp) / "decision_briefs").exists())
            finally:
                if old_root is None:
                    os.environ.pop("OPENCLAW_MEDIA_VAULT_ROOT", None)
                else:
                    os.environ["OPENCLAW_MEDIA_VAULT_ROOT"] = old_root

        self.assertTrue(result.ok)
        self.assertEqual(result.status, "media_growth_done")
        self.assertEqual(result.extra["workflow_plan"]["workflow_mode"], "preset_flow")
        self.assertEqual(
            [item["source_capability_id"] for item in result.extra["artifact"]["preset_node_results"]],
            ["post_review_signal", "creation_decision_brief"],
        )
        self.assertEqual(result.extra["artifact"]["preset_node_results"][0]["artifact_type"], "ReviewSignal")

    def test_research_without_evidence_returns_pending_manual(self) -> None:
        router = MediaGrowthRouteHarness()
        with tempfile.TemporaryDirectory() as tmp:
            old_root = os.environ.get("OPENCLAW_MEDIA_VAULT_ROOT")
            os.environ["OPENCLAW_MEDIA_VAULT_ROOT"] = tmp
            try:
                result = router.route(
                    "调研",
                    "账号=小王 平台=抖音 赛道=校园体育 问题=校园体育长期内容策略怎么拆？",
                    metadata={"account_id": "media"},
                )
                self.assertFalse((_tenant_vault_root(tmp) / "research_briefs").exists())
            finally:
                if old_root is None:
                    os.environ.pop("OPENCLAW_MEDIA_VAULT_ROOT", None)
                else:
                    os.environ["OPENCLAW_MEDIA_VAULT_ROOT"] = old_root

        self.assertTrue(result.ok)
        self.assertEqual(result.status, "media_growth_pending_manual")
        self.assertIn("证据不足", result.reply)
        self.assertNotIn("pending_manual", result.reply)
        self.assertIn("等待人工补充或确认", result.reply)

    def test_growth_reply_hides_internal_evidence_diagnostics(self) -> None:
        mixin = MediaGrowthMixin()
        reply_reason = mixin._media_growth_display_reason(
            "KnowledgeEvidenceContractError: typed KnowledgeEvidenceBundle has no evidence_items"
        )

        self.assertIn("证据不足", reply_reason)
        self.assertNotIn("pending_manual", reply_reason)
        self.assertNotIn("KnowledgeEvidence", reply_reason)
        self.assertNotIn("typed evidence", reply_reason)

    def test_runtime_artifact_consumer_contract_rejects_wrong_type(self) -> None:
        router = MediaGrowthRouteHarness()
        with tempfile.TemporaryDirectory() as tmp:
            old_root = os.environ.get("OPENCLAW_MEDIA_VAULT_ROOT")
            os.environ["OPENCLAW_MEDIA_VAULT_ROOT"] = tmp
            try:
                source = router.route("素材", "平台=抖音 备注=候选素材", metadata={"account_id": "media"})
                self.assertTrue(source.ok)
                result = router.route("发布包", f"source_asset_id={source.task_id} 草稿=正文", metadata={"account_id": "media"})
            finally:
                if old_root is None:
                    os.environ.pop("OPENCLAW_MEDIA_VAULT_ROOT", None)
                else:
                    os.environ["OPENCLAW_MEDIA_VAULT_ROOT"] = old_root

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "media_growth_contract_failed")
        self.assertIn("cannot be consumed", result.reply)

    def test_artifact_result_exposes_review_card_metadata(self) -> None:
        router = MediaGrowthRouteHarness()
        with tempfile.TemporaryDirectory() as tmp:
            old_root = os.environ.get("OPENCLAW_MEDIA_VAULT_ROOT")
            os.environ["OPENCLAW_MEDIA_VAULT_ROOT"] = tmp
            try:
                result = router.route("素材", "一条候选素材", metadata={"account_id": "media"})
            finally:
                if old_root is None:
                    os.environ.pop("OPENCLAW_MEDIA_VAULT_ROOT", None)
                else:
                    os.environ["OPENCLAW_MEDIA_VAULT_ROOT"] = old_root

        review_card = result.extra["review_card"]
        self.assertEqual(review_card["artifact_id"], result.task_id)
        self.assertEqual(review_card["artifact_type"], "SourceAsset")
        self.assertTrue(review_card["artifact_ref"].startswith(f"media://tenants/{TEST_TENANT_ID}/source_assets/"))
        self.assertIn({"action": "approve", "label": "通过复核"}, review_card["actions"])
        self.assertIn("通过复核模板：【复核】artifact_id=", result.reply)
        self.assertIn("废弃模板：【复核】artifact_id=", result.reply)

    def test_review_tag_promotes_artifact_without_card_callback(self) -> None:
        router = MediaGrowthRouteHarness()
        with tempfile.TemporaryDirectory() as tmp:
            old_root = os.environ.get("OPENCLAW_MEDIA_VAULT_ROOT")
            old_reviewers = os.environ.get("OPENCLAW_MEDIA_GROWTH_REVIEWERS")
            os.environ["OPENCLAW_MEDIA_VAULT_ROOT"] = tmp
            try:
                source = router.route("素材", "备注=一条可通过素材", metadata={"account_id": "media"})
                os.environ["OPENCLAW_MEDIA_GROWTH_REVIEWERS"] = "media"
                result = router.route("复核", f"artifact_id={source.task_id} 动作=通过 备注=证据够用", metadata={"account_id": "media"})
                payload = json.loads((_tenant_vault_root(tmp) / "source_assets" / source.task_id / "result.json").read_text(encoding="utf-8"))
            finally:
                if old_root is None:
                    os.environ.pop("OPENCLAW_MEDIA_VAULT_ROOT", None)
                else:
                    os.environ["OPENCLAW_MEDIA_VAULT_ROOT"] = old_root
                if old_reviewers is None:
                    os.environ.pop("OPENCLAW_MEDIA_GROWTH_REVIEWERS", None)
                else:
                    os.environ["OPENCLAW_MEDIA_GROWTH_REVIEWERS"] = old_reviewers

        self.assertTrue(result.ok)
        self.assertEqual(result.status, "artifact_approved")
        self.assertEqual(payload["quality_status"], "cleaned")
        self.assertEqual(payload["review_history"][0]["action"], "approve")

    def test_web_canonical_post_review_signal_bypasses_generic_archive(self) -> None:
        router = MediaGrowthRouteHarness()
        with tempfile.TemporaryDirectory() as tmp:
            old_root = os.environ.get("OPENCLAW_MEDIA_VAULT_ROOT")
            os.environ["OPENCLAW_MEDIA_VAULT_ROOT"] = tmp
            try:
                result = router.route(
                    "复盘",
                    "平台=小红书 发布链接=https://example.com/post/qa 单一事实=收藏率高于点赞率 下一步=验证收藏理由",
                    metadata={
                        "account_id": "media",
                        "channel": "media_web",
                        "canonical_capability_id": "post_review_signal",
                    },
                )
                payload = json.loads((_tenant_vault_root(tmp) / "review_signals" / result.task_id / "result.json").read_text(encoding="utf-8"))
            finally:
                if old_root is None:
                    os.environ.pop("OPENCLAW_MEDIA_VAULT_ROOT", None)
                else:
                    os.environ["OPENCLAW_MEDIA_VAULT_ROOT"] = old_root

        self.assertTrue(result.ok)
        self.assertEqual(result.status, "media_growth_done")
        self.assertEqual(payload["artifact_type"], "ReviewSignal")
        self.assertEqual(payload["source_capability_id"], "post_review_signal")

    def test_explicit_external_preset_reply_is_not_planning_confusion(self) -> None:
        router = MediaGrowthRouteHarness()
        with tempfile.TemporaryDirectory() as tmp:
            old_root = os.environ.get("OPENCLAW_MEDIA_VAULT_ROOT")
            os.environ["OPENCLAW_MEDIA_VAULT_ROOT"] = tmp
            try:
                result = router.route("素材", "流程=quick_polish 原文=需要更有网感", metadata={"account_id": "media"})
            finally:
                if old_root is None:
                    os.environ.pop("OPENCLAW_MEDIA_VAULT_ROOT", None)
                else:
                    os.environ["OPENCLAW_MEDIA_VAULT_ROOT"] = old_root

        self.assertTrue(result.ok)
        self.assertEqual(result.status, "media_growth_external_delegation_required")
        self.assertIn("既有链路：style_polish_run", result.reply)
        self.assertIn("发送【润色】", result.reply)
        self.assertNotIn("规划中：style_polish_run", result.reply)
        self.assertIn("纯参数输入", result.reply)

    def test_preset_runtime_failure_reply_includes_resume_command(self) -> None:
        router = MediaGrowthRouteHarness()
        original_runner = growth_service.RUNNERS["creation_decision_brief"]

        def failing_runner(*args, **kwargs):
            raise RuntimeError("boom")

        with tempfile.TemporaryDirectory() as tmp:
            old_root = os.environ.get("OPENCLAW_MEDIA_VAULT_ROOT")
            os.environ["OPENCLAW_MEDIA_VAULT_ROOT"] = tmp
            growth_service.RUNNERS["creation_decision_brief"] = failing_runner
            try:
                result = router.route("素材", "流程=asset_to_topic 备注=需要断点续跑的素材", metadata={"account_id": "media"})
            finally:
                growth_service.RUNNERS["creation_decision_brief"] = original_runner
                if old_root is None:
                    os.environ.pop("OPENCLAW_MEDIA_VAULT_ROOT", None)
                else:
                    os.environ["OPENCLAW_MEDIA_VAULT_ROOT"] = old_root

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "media_growth_failed")
        self.assertIn("已写入产物：1 个", result.reply)
        self.assertIn(f"续跑指令：发送【选题】source=media://tenants/{TEST_TENANT_ID}/source_assets/", result.reply)
        self.assertIn("source_asset_id=source_asset_", result.reply)

    def test_verify_capability_selection(self) -> None:
        mixin = MediaGrowthMixin()
        self.assertEqual(mixin._media_growth_verify_capability_id("run_id=creation_run_1"), "publish_readiness_gate")
        self.assertEqual(mixin._media_growth_verify_capability_id("作品内容：一段稿件\n创作要求：不要编造"), "work_acceptance_report")
        self.assertEqual(mixin._media_growth_verify_capability_id("发布前看哪个清单"), "creation_checklist_lookup")

    def test_check_run_id_routes_to_publish_readiness_gate(self) -> None:
        router = MediaGrowthRouteHarness()
        with tempfile.TemporaryDirectory() as tmp:
            old_root = os.environ.get("OPENCLAW_MEDIA_VAULT_ROOT")
            os.environ["OPENCLAW_MEDIA_VAULT_ROOT"] = tmp
            try:
                vault = growth_service.make_media_vault(TEST_TENANT_ID)
                vault.write_creation_run_artifacts(
                    "creation_run_for_check",
                    request={"entrypoint": "【创作>抖音】", "input": "短跑赛前准备"},
                    draft_output={
                        "platform": "抖音",
                        "title": "起跑前一秒",
                        "final_copy": "起跑前一秒，所有准备都变成身体的记忆。",
                        "tags": ["短跑", "比赛"],
                    },
                )
                result = router.route("检查", "run_id=creation_run_for_check", metadata={"account_id": "media"})
            finally:
                if old_root is None:
                    os.environ.pop("OPENCLAW_MEDIA_VAULT_ROOT", None)
                else:
                    os.environ["OPENCLAW_MEDIA_VAULT_ROOT"] = old_root

        self.assertTrue(result.ok)
        self.assertEqual(result.status, "media_growth_done")
        self.assertEqual(result.extra["canonical_capability_id"], "publish_readiness_gate")
        self.assertEqual(result.extra["artifact"]["artifact_type"], "PublishReadinessGate")
        self.assertEqual(result.extra["artifact"]["gate_status"], "ready")

    def test_same_line_labeled_values_stop_at_next_label(self) -> None:
        mixin = MediaGrowthMixin()
        body = "账号=小王 平台=抖音 赛道=升学 问题=这个链接能不能做 https://www.douyin.com/video/7654247930551244785"

        self.assertEqual(mixin._media_growth_labeled_value(body, ("账号", "account", "account_id")), "小王")
        self.assertEqual(mixin._media_growth_labeled_value(body, ("平台", "platform")), "抖音")
        self.assertEqual(mixin._media_growth_labeled_value(body, ("赛道", "track", "track_id")), "升学")

        asset_body = "平台=小红书 用途=记录 链接=http://xhslink.com/o/16704LMMFPp"
        self.assertEqual(mixin._media_growth_labeled_value(asset_body, ("平台", "platform")), "小红书")

        new_field_body = "主题=短跑 场地=操场 模式=第一视角 正文=正文内容"
        self.assertEqual(mixin._media_growth_labeled_value(new_field_body, ("主题",)), "短跑")
        self.assertEqual(mixin._media_growth_labeled_value(new_field_body, ("场地",)), "操场")
        self.assertEqual(mixin._media_growth_labeled_value(new_field_body, ("模式",)), "第一视角")


if __name__ == "__main__":
    unittest.main()
