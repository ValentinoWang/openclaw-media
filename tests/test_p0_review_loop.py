from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from media_vault.vault import MediaVault
from selfmedia.creation.request_parser import CreationRequest
from selfmedia.creation.workflow import format_creation_reply
from selfmedia.review import data_review


TENANT_ID = "00000000-0000-4000-8000-000000000101"


class P0ReviewLoopTests(unittest.TestCase):
    def test_load_creation_plan_projects_only_review_relevant_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ, {"OPENCLAW_MEDIA_VAULT_ROOT": directory}, clear=False
        ):
            vault = MediaVault(tenant_id=TENANT_ID)
            vault.write_json_artifact(
                vault.creation_run_dir("run_review_loop"),
                "draft_output.json",
                {
                    "title": "训练后的真实反应",
                    "hook_3s": "跑完 400 米后我没马上停表。",
                    "validation_targets": {"two_hour": ["收藏"]},
                    "review_plan": ["两小时后对照收藏"],
                    "publishing_pack": {
                        "title_1": "训练日记",
                        "first_hour_action": "置顶提问并回复前十条评论",
                        "internal_trace": "must_not_reach_review_prompt",
                    },
                    "raw_response": "must_not_reach_review_prompt",
                },
                owner_type="CreationRun",
                owner_id="run_review_loop",
                artifact_type="draft_output",
            )
            plan = data_review.load_creation_plan(TENANT_ID, "run_review_loop")

        self.assertEqual(plan["status"], "loaded")
        self.assertEqual(plan["creation_record_id"], "run_review_loop")
        self.assertEqual(plan["plan"]["title"], "训练后的真实反应")
        self.assertEqual(plan["plan"]["validation_targets"], {"two_hour": ["收藏"]})
        self.assertNotIn("internal_trace", plan["plan"]["publishing_pack"])
        self.assertNotIn("raw_response", json.dumps(plan, ensure_ascii=False))

    def test_review_prompt_receives_loaded_creation_plan(self) -> None:
        request = data_review.DataReviewRequest(creation_record_id="run_review_loop", title="训练日记")
        captured: list[dict[str, object]] = []
        plan = {
            "status": "loaded",
            "creation_record_id": "run_review_loop",
            "plan": {"title": "训练日记", "hook_3s": "先冲线", "validation_targets": {}, "review_plan": [], "publishing_pack": {}},
        }
        with patch.object(data_review, "load_llm_config", return_value={}), patch.object(
            data_review, "generate_validated_review_json", side_effect=lambda parts, _config, **_kwargs: captured.extend(parts) or {"conclusion": "ok"}
        ):
            data_review.analyze_data_screenshots(
                request=request,
                screenshots=[],
                reviewed_at="2026-08-28T10:00:00+08:00",
                guide_text="",
                conversation_context={},
                creation_plan=plan,
            )

        prompt_payload = json.loads(str(captured[0]["text"]).split("输入上下文：", 1)[1])
        self.assertEqual(prompt_payload["creation_plan"], plan)

    def test_review_rendering_prioritizes_actions_without_raw_json(self) -> None:
        analysis = {
            "conclusion": "收藏率偏低，先重写封面。",
            "media_format": "video",
            "media_format_evidence": "截图显示完播率",
            "metrics": {"播放": 1200, "收藏": 18},
            "format_specific_metrics": {"完播率": "31%"},
            "atomic_facts": [{"fact": "收藏偏低", "metric": "收藏", "value": 18, "confidence": "高"}],
            "priority_metrics": [{"metric": "完播率", "value": "31%", "content_action": "压缩中段"}],
            "trend_curves": {"播放": "首小时后回落"},
            "metric_interpretation": ["开头有效，后段流失"],
            "problems": ["封面承诺不足"],
            "content_guidance": ["封面先写结果"],
            "publishing_guidance": ["下次晚八点发布"],
            "next_actions": ["重做封面后观察两小时"],
            "data_quality_notes": ["截图可读"],
        }
        report = data_review.render_data_review_report({"reviewed_at": "2026-08-28", "analysis": analysis})
        blocks = data_review.data_review_doc_blocks("测试复盘", data_review.DataReviewRequest(), analysis, [], "2026-08-28", "")
        rendered_blocks = json.dumps(blocks, ensure_ascii=False)

        self.assertLess(report.index("## 下一步动作"), report.index("## 关键数据"))
        self.assertNotIn('"atomic_facts"', report)
        self.assertNotIn('"atomic_facts"', rendered_blocks)
        self.assertIn("事实：收藏偏低", report)

    def test_creation_reply_exposes_record_id_for_later_review(self) -> None:
        request = CreationRequest(
            platform="抖音",
            content_type="视频",
            track="跑步训练",
            topic="训练日记",
            publish_time="今天 20:00",
        )
        reply = format_creation_reply(
            request,
            [],
            [],
            [],
            [],
            "",
            {"ok": True},
            creation_record_id="run_review_loop",
        )
        self.assertIn("创作记录ID：run_review_loop", reply)

    def test_review_write_uses_creation_record_as_stable_post_key(self) -> None:
        request = data_review.DataReviewRequest(creation_record_id="run_review_loop", platform="抖音")
        writes: list[tuple[object, ...]] = []
        with patch.dict(
            os.environ,
            {
                "MEDIA_OS_POST_REVIEWS_URL": "https://bitable.example.test/post-reviews",
                "MEDIA_OS_METRIC_SNAPSHOT_URL": "https://bitable.example.test/metrics",
            },
            clear=False,
        ), patch.object(data_review.MediaVault, "write_post_review", return_value={"metrics": {"uri": "media://review"}}), patch.object(
            data_review, "upsert_entity_record", side_effect=lambda *args, **_kwargs: writes.append(args) or {"record_id": "rec_1"}
        ):
            result = data_review.write_data_review_model_v2(
                tenant_id=TENANT_ID,
                request=request,
                analysis={"data_window": "2h", "performance_level": "建议重剪", "metrics": {}, "priority_metrics": [], "atomic_facts": [], "trend_curves": {}},
                screenshots=[],
                reviewed_at="2026-08-28T10:00:00+08:00",
                doc_link="",
                source_record_id="run_review_loop",
            )

        self.assertEqual(result["post_id"], "post_run_review_loop")
        self.assertEqual(writes[0][2]["creation_run_id"], "run_review_loop")
        self.assertEqual(writes[0][2]["performance_rating"], "值得重剪")
        self.assertIn(writes[0][2]["performance_rating"], data_review.PERFORMANCE_LEVELS)

    def test_review_advances_explicitly_selected_business_to_delivered(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ,
            {
                "OPENCLAW_MEDIA_VAULT_ROOT": directory,
                "MEDIA_OS_POST_REVIEWS_URL": "https://bitable.example.test/post-reviews",
                "MEDIA_OS_METRIC_SNAPSHOT_URL": "https://bitable.example.test/metrics",
                "MEDIA_OS_BUSINESS_OPPORTUNITIES_URL": "https://bitable.example.test/opportunities",
            },
            clear=False,
        ):
            vault = MediaVault(tenant_id=TENANT_ID)
            run_dir = vault.creation_run_dir("run_business_delivery")
            vault.write_json_artifact(
                run_dir,
                "decision_trace.json",
                [{"candidate_type": "business", "candidate_id": "opp_1", "selected": True}],
                owner_type="CreationRun",
                owner_id="run_business_delivery",
                artifact_type="decision_trace",
            )
            vault.write_json_artifact(
                run_dir,
                "retrieval_candidates.json",
                {
                    "businesses": [
                        {
                            "record": {
                                "relation_id": "opp_1",
                                "platform": "小红书",
                                "content_type_requirement": "不限",
                                "detail_json": {"brand": "测试品牌", "product": "测试产品", "linked_run_ids": ["run_old"]},
                            }
                        }
                    ]
                },
                owner_type="CreationRun",
                owner_id="run_business_delivery",
                artifact_type="retrieval_candidates",
            )
            writes: list[tuple[object, ...]] = []
            with patch.object(data_review.MediaVault, "write_post_review", return_value={"metrics": {"uri": "media://review"}}), patch.object(
                data_review, "upsert_entity_record", side_effect=lambda *args, **_kwargs: writes.append(args) or {"record_id": "rec_1"}
            ):
                result = data_review.write_data_review_model_v2(
                    tenant_id=TENANT_ID,
                    request=data_review.DataReviewRequest(creation_record_id="run_business_delivery", platform="小红书", publish_url="https://example.test/post"),
                    analysis={"data_window": "2h", "metrics": {}, "priority_metrics": [], "atomic_facts": [], "trend_curves": {}},
                    screenshots=[],
                    reviewed_at="2026-08-28T10:00:00+08:00",
                    doc_link="",
                    source_record_id="run_business_delivery",
                )

        business_payload = writes[-1][2]
        self.assertEqual(result["business_delivery_count"], 1)
        self.assertEqual(writes[-1][0], "BusinessOpportunity")
        self.assertEqual(business_payload["lifecycle_status"], "delivered")
        self.assertEqual(business_payload["linked_run_ids"], ["run_old", "run_business_delivery"])
        self.assertNotIn("content_type", business_payload)
        self.assertEqual(business_payload["delivery_published_url"], "https://example.test/post")

    def test_resolve_creation_plan_auto_links_only_one_exact_title_and_account_match(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ, {"OPENCLAW_MEDIA_VAULT_ROOT": directory}, clear=False
        ):
            vault = MediaVault(tenant_id=TENANT_ID)
            vault.write_creation_run_artifacts(
                "run_matched",
                request={"request": {"account": "训练小王", "topic": "跑步训练"}},
                draft_output={"title": "跑步训练", "validation_targets": {}},
            )
            resolved = data_review.resolve_creation_plan_for_review(
                TENANT_ID,
                data_review.DataReviewRequest(account="训练小王", title="跑步训练"),
            )

        self.assertEqual(resolved["status"], "loaded")
        self.assertEqual(resolved["creation_record_id"], "run_matched")
        self.assertEqual(resolved["matched_by"], "publish_url_or_title_account")

    def test_loaded_plan_requires_structured_comparison(self) -> None:
        base = {
            "conclusion": "需要重做开头。",
            "media_format": "video",
            "media_format_evidence": "截图显示完播率",
            "metrics": {},
            "format_specific_metrics": {},
            "atomic_facts": [{"fact": "完播率较低"}],
            "priority_metrics": [{"metric": "完播率", "value": "31%"}],
            "content_guidance": ["压缩中段"],
            "publishing_guidance": ["下次观察两小时"],
        }
        with self.assertRaisesRegex(ValueError, "plan_comparison"):
            data_review.validate_data_review_analysis(base, {"creation_plan_loaded": True})

        validated = data_review.validate_data_review_analysis(
            {
                **base,
                "plan_comparison": [
                    {
                        "plan_item": "两小时观察收藏",
                        "status": "证据不足",
                        "evidence": "截图没有收藏趋势",
                        "next_step": "两小时后补充截图",
                    }
                ],
            },
            {"creation_plan_loaded": True},
        )
        self.assertEqual(validated["plan_comparison"][0]["status"], "证据不足")


if __name__ == "__main__":
    unittest.main()
