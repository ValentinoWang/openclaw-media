from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from integrations.feishu.media_writer import (
    MediaModelFeishuWriterError,
    prepare_entity_bitable_fields,
)
from media_model import (
    EntrypointContractError,
    LLMIOContractError,
    MediaModelContract,
    MediaModelPayloadError,
    RenderSpecError,
    account_metric_snapshot_idempotency_key,
    assert_generation_write_policy,
    build_account_metric_snapshot_payload,
    build_business_opportunity_payload,
    build_creation_run_payload,
    build_decision_trace_payloads,
    build_llm_input_payload,
    build_material_deconstruction_payload,
    build_material_usage_payloads,
    build_metric_snapshot_payload,
    build_pattern_payload,
    build_quote_snapshot_payload,
    build_render_spec,
    build_source_asset_payload,
    content_fingerprint,
    metric_snapshot_idempotency_key,
    normalize_metric_key,
    normalize_rebate_ratio,
    normalize_source_url,
    platform_validation_report,
    render_spec_to_creator_doc_blocks,
    render_spec_to_task_card_blocks,
    validate_entrypoint_result,
)
from selfmedia.creation.request_parser import CreationRequest
from selfmedia.creation.writer import NATIVE_TABLE_KIND


class MediaModelTests(unittest.TestCase):
    def test_contract_loads_required_projection(self) -> None:
        contract = MediaModelContract()
        self.assertIn("SourceAsset", contract.data["entity_contracts"])
        self.assertIn("asset_id", contract.writable_fields("SourceAsset"))
        self.assertIn("DecisionTrace", contract.data["entity_contracts"])

    def test_source_asset_payload_uses_normalized_url_and_media_uri(self) -> None:
        payload = build_source_asset_payload(
            platform="xhs",
            title="起跑前一秒",
            source_url="HTTPS://Example.com/a/?utm_source=x&foo=1",
            evidence_uri="media://source_assets/xhs/asset_1/evidence/evidence.json",
            author_id="author_1",
        )
        self.assertEqual(payload["source_url"], "https://example.com/a?foo=1")
        self.assertTrue(payload["content_fingerprint"].startswith("sha256:"))

    def test_source_asset_rejects_non_media_evidence(self) -> None:
        with self.assertRaises(MediaModelPayloadError):
            build_source_asset_payload(
                platform="xhs",
                title="起跑前一秒",
                source_url="https://example.com/a",
                evidence_uri="/home/ubuntu/source.html",
            )

    def test_deconstruction_payload_requires_lineage(self) -> None:
        payload = build_material_deconstruction_payload(
            deconstruction_id="decon_1",
            asset_id="asset_1",
            summary="素材讲的是赛前紧张和反转。",
            evidence_uri="media://deconstructions/decon_1/evidence_refs.json",
            prompt_bundle_version="prompt_v1",
            model="gpt-test",
            confidence=0.82,
            cover_opening_hook="封面前2秒抓手",
            core_data_summary="点赞收藏评论分享摘要",
            top_comment_insight="三条高赞评论洞察",
            target_audience_summary="目标受众",
            pain_pleasure_summary="痛点爽点",
            attention_elements="吸睛元素",
            viral_breakdown="爆点拆解",
            viral_migration="爆点迁移",
            creative_upgrade_suggestion="千万年薪编导会怎么把这条改出彩",
        )
        self.assertEqual(payload["review_status"], "未复核")
        self.assertEqual(payload["prompt_bundle_version"], "prompt_v1")
        self.assertEqual(payload["creative_upgrade_suggestion"], "千万年薪编导会怎么把这条改出彩")

    def test_pattern_cannot_be_proven_from_single_unverified_source(self) -> None:
        with self.assertRaises(MediaModelPayloadError):
            build_pattern_payload(
                pattern_id="pattern_1",
                pattern_name="赛前反差开头",
                pattern_status="proven_pattern",
                supporting_asset_ids=["asset_1"],
            )
        payload = build_pattern_payload(
            pattern_id="pattern_1",
            pattern_name="赛前反差开头",
            pattern_status="proven_pattern",
            supporting_asset_ids=["asset_1", "asset_2"],
        )
        self.assertEqual(payload["pattern_status"], "proven_pattern")

    def test_creation_run_decision_trace_and_usage_payloads(self) -> None:
        run = build_creation_run_payload(
            run_id="run_20260620_test",
            entrypoint="【创作】",
            input_summary="生成短跑赛前小红书图文",
            status="待写入",
            generation_source="llm",
            run_artifact_uri="media://creation_runs/run_20260620_test/request.json",
            render_spec_uri="media://renders/render_20260620_test/render_spec.json",
        )
        self.assertEqual(run["run_id"], "run_20260620_test")

        traces = build_decision_trace_payloads(
            run_id="run_20260620_test",
            decision_version="matcher_v1",
            candidates=[
                {
                    "candidate_type": "material",
                    "candidate_id": "asset_1",
                    "rank": 1,
                    "score": 93,
                    "selected": True,
                    "reason_summary": "结构贴合赛前准备。",
                    "score_breakdown_uri": "media://creation_runs/run_20260620_test/decision_trace.json",
                }
            ],
        )
        self.assertEqual(traces[0]["candidate_type"], "material")
        self.assertTrue(traces[0]["trace_id"].startswith("trace:"))

        usages = build_material_usage_payloads(
            run_id="run_20260620_test",
            usages=[
                {
                    "asset_id": "asset_1",
                    "usage_type": "结构参考",
                    "score": 93,
                    "selected_for_final": True,
                }
            ],
        )
        self.assertTrue(usages[0]["usage_id"].startswith("usage:"))

    def test_decision_trace_score_bounds(self) -> None:
        with self.assertRaises(MediaModelPayloadError):
            build_decision_trace_payloads(
                run_id="run_1",
                decision_version="matcher_v1",
                candidates=[
                    {
                        "candidate_type": "material",
                        "candidate_id": "asset_1",
                        "rank": 1,
                        "score": 101,
                        "selected": True,
                        "reason_summary": "too high",
                    }
                ],
            )

    def test_quote_ratio_normalization(self) -> None:
        self.assertEqual(normalize_rebate_ratio("20%"), 0.2)
        self.assertEqual(normalize_rebate_ratio(20), 0.2)
        self.assertEqual(normalize_rebate_ratio(0.2), 0.2)
        payload = build_business_opportunity_payload(
            opportunity_id="opp_1",
            brand="adidas",
            current_quote_amount=1499,
            rebate_ratio="20%",
            quote_snapshot_uri="media://business/opp_1/quote_snapshot.json",
        )
        self.assertEqual(payload["rebate_ratio"], 0.2)

    def test_url_and_fingerprint_are_stable(self) -> None:
        first = normalize_source_url("https://example.com/post?a=1&utm_source=x")
        second = normalize_source_url("https://EXAMPLE.com/post/?utm_medium=y&a=1")
        self.assertEqual(first, second)
        self.assertEqual(
            content_fingerprint(platform="xhs", source_url=first, title="标题"),
            content_fingerprint(platform="xhs", source_url=second, title=" 标题 "),
        )

    def test_llm_input_requires_media_evidence_uri(self) -> None:
        with self.assertRaises(LLMIOContractError):
            build_llm_input_payload(
                run_id="run_20260620_test",
                request={"platform": "小红书", "content_type": "图文", "topic": "短跑"},
                candidates={"material": [{"id": "asset_1", "candidate_type": "material", "evidence_uri": "/home/ubuntu/a.json"}]},
            )
        payload = build_llm_input_payload(
            run_id="run_20260620_test",
            request={"platform": "小红书", "content_type": "图文", "topic": "短跑"},
            candidates={"material": [{"id": "asset_1", "candidate_type": "material", "evidence_uri": "media://source_assets/xhs/asset_1/evidence/evidence.json"}]},
            evidence_refs=["media://creation_runs/run_20260620_test/retrieval_candidates.json"],
        )
        self.assertEqual(payload["schema"]["evidence_scheme"], "media://")

    def test_platform_validation_failure_is_pending_manual_only(self) -> None:
        report = platform_validation_report("小红书", "图文", {"title": "", "tags": [], "image_script": []})
        self.assertFalse(report["ok"])
        self.assertEqual(report["write_policy"], "pending_manual_only")
        with self.assertRaises(LLMIOContractError):
            assert_generation_write_policy(generation_source="llm", llm_ok=False, validation_ok=True)
        with self.assertRaises(LLMIOContractError):
            assert_generation_write_policy(generation_source="llm", llm_ok=True, validation_ok=False)

    def test_render_spec_reuses_creator_doc_blocks_and_native_table(self) -> None:
        draft_uri = "media://creation_runs/run_20260620_test/draft_output.json"
        render_spec = build_render_spec(
            render_id="render_20260620_test",
            run_id="run_20260620_test",
            entry_tag="【创作>抖音】",
            platform="抖音",
            content_type="视频",
            theme="短跑赛前准备",
            sections=[{"type": "douyin_storyboard_doc", "title": "抖音分镜", "data_ref": draft_uri}],
        )
        request = CreationRequest(
            platform="抖音",
            content_type="视频",
            track="运动",
            topic="短跑赛前准备",
            publish_time="",
            keywords=["短跑", "比赛"],
        )
        blocks = render_spec_to_creator_doc_blocks(
            render_spec,
            {draft_uri: _draft_output("抖音", "视频")},
            request=request,
        )
        self.assertTrue(any(block.get("_openclaw_kind") == NATIVE_TABLE_KIND for block in blocks))

    def test_task_card_adapter_requires_existing_writer_interface(self) -> None:
        render_spec = build_render_spec(
            render_id="render_20260620_task",
            run_id="run_20260620_task",
            entry_tag="【创作-灵感】",
            platform="小红书",
            content_type="图文",
            theme="灵感任务卡",
            sections=[{"type": "summary", "title": "摘要", "data_ref": "media://creation_runs/run_20260620_task/input.json"}],
        )
        payloads = {"media://creation_runs/run_20260620_task/input.json": {"summary": "摘要"}}
        with self.assertRaises(RenderSpecError):
            render_spec_to_task_card_blocks(render_spec, payloads, writer=object(), doc_title="任务卡", record_type="创作灵感")
        writer = _FakeTaskCardWriter()
        blocks = render_spec_to_task_card_blocks(render_spec, payloads, writer=writer, doc_title="任务卡", record_type="创作灵感")
        self.assertTrue(writer.used_blocks_from_text)
        self.assertEqual(blocks[0]["heading"], "任务卡")

    def test_metric_registry_and_snapshot_payloads(self) -> None:
        self.assertEqual(normalize_metric_key("播放量"), "views")
        self.assertEqual(normalize_metric_key("曝光"), "impressions")
        snapshot_id = metric_snapshot_idempotency_key(post_id="post_1", review_node="24h", metric_key="播放量", collected_at="2026-06-20T12:00:00+08:00")
        payload = build_metric_snapshot_payload(
            snapshot_id=snapshot_id,
            post_id="post_1",
            review_node="24h",
            metric_key="views",
            raw_metric_name="播放量",
            metric_value=12345,
            unit="次",
            evidence_uri="media://published_posts/post_1/review/24h/metrics.json",
        )
        self.assertEqual(payload["metric_key"], "views")
        account_snapshot_id = account_metric_snapshot_idempotency_key(
            creator_profile_id="creator_1",
            platform="小红书",
            metric_key="粉丝数",
            collected_at="2026-06-20T12:00:00+08:00",
        )
        account_payload = build_account_metric_snapshot_payload(
            account_name="清华AI小王",
            snapshot_id=account_snapshot_id,
            creator_profile_id="creator_1",
            platform="小红书",
            metric_key="followers",
            raw_metric_name="粉丝数",
            metric_value=10000,
            unit="人",
            evidence_uri="media://published_posts/post_1/review/24h/metrics.json",
        )
        self.assertEqual(account_payload["account_name"], "清华AI小王")
        self.assertEqual(account_payload["metric_key"], "followers")

    def test_quote_snapshot_schema(self) -> None:
        payload = build_quote_snapshot_payload(
            opportunity_id="opp_1",
            platform="小红书",
            content_form="图文",
            report_type="报备",
            amount=1499,
            rebate_ratio="20%",
            tax_policy="tax_excluded",
            platform_fee_policy="excluded_from_rebate",
            settlement_entity="个人",
            authorization_duration="6个月",
            valid_from="2026-06-01",
            valid_until="2026-07-01",
            quote_status="current",
            source_confidence="chat_confirmed",
            evidence_uri="media://business/opp_1/evidence/chat.md",
        )
        self.assertEqual(payload["version"], "quote_snapshot_v1")
        self.assertEqual(payload["rebate_ratio"], 0.2)

    def test_entrypoint_guard_blocks_unauthorized_writes_and_missing_trace(self) -> None:
        with self.assertRaises(EntrypointContractError):
            validate_entrypoint_result(
                "【创作咨询】",
                {
                    "reads": ["Activity"],
                    "writes": ["MaterialUsage"],
                    "writes_artifacts": [],
                },
            )
        with self.assertRaises(EntrypointContractError):
            validate_entrypoint_result(
                "【创作】",
                {
                    "reads": ["Activity", "SourceAsset"],
                    "writes": ["CreationRun", "DecisionTrace", "MaterialUsage"],
                    "writes_artifacts": ["creation_run_artifacts", "render_artifacts"],
                    "candidate_count": 2,
                    "decision_trace_count": 0,
                    "final_reference_count": 1,
                    "material_usage_count": 1,
                },
            )
        validate_entrypoint_result(
            "【创作】",
            {
                "reads": ["Activity", "SourceAsset"],
                "writes": ["CreationRun", "DecisionTrace", "MaterialUsage"],
                "writes_artifacts": ["creation_run_artifacts", "render_artifacts"],
                "candidate_count": 2,
                "decision_trace_count": 2,
                "final_reference_count": 1,
                "material_usage_count": 1,
            },
        )

    def test_prepare_bitable_fields_rejects_option_ids_and_coerces_values(self) -> None:
        payload = build_decision_trace_payloads(
            run_id="run_20260620_test",
            decision_version="matcher_v1",
            candidates=[
                {
                    "candidate_type": "material",
                    "candidate_id": "asset_1",
                    "rank": 1,
                    "score": 93,
                    "selected": True,
                    "reason_summary": "结构贴合。",
                }
            ],
        )[0]
        fields = prepare_entity_bitable_fields(
            "DecisionTrace",
            payload,
            {
                "决策轨迹ID": 1,
                "创作运行ID": 1,
                "候选类型": 3,
                "候选记录ID": 1,
                "候选排序": 2,
                "匹配分": 2,
                "是否入选": 1,
                "入选理由摘要": 1,
                "决策版本": 1,
            },
        )
        self.assertEqual(fields["匹配分"], 93.0)
        self.assertEqual(fields["候选类型"], "material")
        bad_payload = dict(payload)
        bad_payload["candidate_type"] = "optABCDEFG"
        with self.assertRaises(MediaModelFeishuWriterError):
            prepare_entity_bitable_fields(
                "DecisionTrace",
                bad_payload,
                {
                    "候选类型": 3,
                    "决策轨迹ID": 1,
                    "创作运行ID": 1,
                    "候选记录ID": 1,
                    "候选排序": 2,
                    "匹配分": 2,
                    "是否入选": 1,
                    "入选理由摘要": 1,
                    "决策版本": 1,
                },
            )

    def test_contract_normalizes_chinese_feishu_fields_to_canonical_keys(self) -> None:
        contract = MediaModelContract()
        fields = contract.normalize_record_fields(
            "SourceAsset",
            {
                "素材ID": "asset_1",
                "标题": "起跑前一秒",
                "来源链接": "https://example.com/source",
                "证据URI": "media://source_asset/asset_1/evidence.json",
            },
        )
        self.assertEqual(fields["asset_id"], "asset_1")
        self.assertEqual(fields["source_url"], "https://example.com/source")
        self.assertEqual(contract.feishu_field_name("SourceAsset", "asset_id"), "素材ID")


class _FakeTaskCardWriter:
    def __init__(self) -> None:
        self.used_blocks_from_text = False

    def blocks_from_text(self, doc_title: str, record_type: str, content: str) -> list[dict[str, object]]:
        self.used_blocks_from_text = True
        return [{"heading": doc_title}, {"text": record_type}, {"text": content}]


def _draft_output(platform: str, content_type: str) -> dict[str, object]:
    return {
        "platform": platform,
        "content_type": content_type,
        "title": "起跑前一秒",
        "tags": ["短跑", "比赛", "训练", "田径", "成长"],
        "topic": "短跑赛前准备",
        "final_copy": "起跑前一秒，所有准备都变成身体的记忆。",
        "script_options": [
            {
                "option_id": "opt_1",
                "score": 94,
                "title": "起跑前一秒",
                "angle": "赛前准备",
                "why_over_90": "证据清楚，可执行。",
                "activity_fit_reason": "自然承接运动主题。",
                "viral_reference_reason": "只迁移结构。",
                "inspiration_reference_reason": "落到起跑镜头。",
                "risk_level": "low",
                "risks_or_missing_info": [],
                "tags": ["短跑", "比赛", "训练", "田径", "成长"],
                "final_copy": "起跑前一秒，所有准备都变成身体的记忆。",
                "storyboard": [{"time": "0-1s", "visual": "蹲踞式起跑", "subtitle": "起跑前一秒", "sound": "现场声", "shooting_note": "近景"}],
                "production_checklist": ["起跑镜头"],
                "review_plan": ["看完播"],
            }
        ],
        "recommended_option_id": "opt_1",
        "creator_report": {
            "overview": {
                "recommended_topic": "短跑赛前准备",
                "core_sentence": "起跑前一秒，准备变成身体记忆。",
                "platform": platform,
                "content_type": content_type,
                "suitable_activity": "无",
                "strongly_recommend_activity": "否",
                "biggest_risk": "不要虚构成绩。",
            },
            "opening_3s": {
                "visual_0_0_5": "起跑姿势",
                "caption_or_voice_0_5_3": "起跑前一秒",
                "do_not_open_like_this": "不要先讲大道理。",
            },
            "mainline": {
                "conflict": "紧张和准备",
                "evidence": "钉鞋、起跑、检录",
                "emotional_payoff": "准备给人稳定感",
                "audience_resonance": "每个人都有上场前一秒",
            },
            "storyboard": [{"time": "0-1s", "visual": "蹲踞式起跑", "subtitle": "起跑前一秒", "sound": "现场声", "shooting_note": "近景"}],
            "publishing_pack": {
                "title_1": "起跑前一秒",
                "title_2": "赛前准备怎么拍",
                "cover_text": "起跑前一秒",
                "body_copy": "起跑前一秒，所有准备都变成身体的记忆。",
                "hashtags": ["短跑", "比赛", "训练", "田径", "成长"],
                "pinned_comment": "你赛前会紧张吗？",
                "comment_prompt": ["你赛前会做什么？"],
            },
            "material_checklist": {
                "must_have": ["起跑镜头"],
                "better_to_have": ["钉鞋"],
                "can_rescue_without": ["没有成绩也可以拍准备过程"],
                "must_not_fabricate": ["不能虚构成绩"],
            },
            "risk_controls": [{"condition": "没有成绩", "rewrite_or_action": "不写具体秒数"}],
            "evidence_appendix": {
                "activities": [],
                "viral_refs": [],
                "inspiration_refs": [],
                "business_info": "无",
                "scoring_and_record_ids": [],
            },
        },
    }


if __name__ == "__main__":
    unittest.main()
