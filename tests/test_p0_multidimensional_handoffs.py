from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from selfmedia.creation import shooting_execution
from selfmedia.creation.deconstruction_artifact import DeconstructionArtifactUnavailable
from selfmedia.deconstruct.viral_content.src import runner
from selfmedia.ingest.content_flow.src import pipeline


TENANT_ID = "00000000-0000-4000-8000-000000000101"


class P0MultidimensionalHandoffTests(unittest.TestCase):
    def test_content_analysis_skips_pattern_sync_without_controlled_tenant(self) -> None:
        with patch.dict(os.environ, {pipeline.PATTERN_TENANT_ID_ENV: ""}, clear=False):
            result = pipeline._sync_creative_pattern_from_analysis(
                {"url": "https://example.com/video"},
                {"action_plan": "1. 先给结果"},
            )

        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["reason"], "not_configured")

    def test_content_analysis_persists_stable_candidate_pattern_only(self) -> None:
        calls: list[dict[str, object]] = []

        def fake_upsert(entity: str, table_url: str, payload: dict[str, object], **kwargs: object) -> dict[str, str]:
            calls.append({"entity": entity, "table_url": table_url, "payload": payload, **kwargs})
            return {"mode": "write", "record_id": "rec_pattern"}

        analysis = {
            "title": "把教程开头改成反常识提问",
            "primary_category": "内容创作",
            "secondary_category": ["短视频运营"],
            "target_audience": "知识类创作者",
            "hooks": "先抛出常见误区",
            "action_plan": "1. 反常识开头 2. 演示过程 3. 给出行动",
            "visual_cues": "屏录配口播",
            "emotion": "好奇",
            "transferable_expression": "你以为 X，其实先做 Y",
        }
        state = {"url": "https://example.com/video?utm_source=test", "platform": "抖音", "media_type": "video"}
        with patch.dict(os.environ, {pipeline.PATTERN_TENANT_ID_ENV: TENANT_ID}, clear=False), patch(
            "selfmedia.creation.retrieval.resolve_inspiration_bitable_url",
            return_value="mock://patterns",
        ), patch("integrations.feishu.media_writer.upsert_entity_record", side_effect=fake_upsert):
            first = pipeline._sync_creative_pattern_from_analysis(state, analysis)
            second = pipeline._sync_creative_pattern_from_analysis(state, analysis)

        self.assertEqual(first["status"], "persisted")
        self.assertEqual(second["pattern_id"], first["pattern_id"])
        self.assertEqual(len(calls), 2)
        payload = calls[0]["payload"]
        self.assertEqual(calls[0]["entity"], "CreativePattern")
        self.assertEqual(calls[0]["session_tenant_id"], TENANT_ID)
        self.assertEqual(payload["pattern_status"], "candidate_pattern")
        self.assertEqual(payload["supporting_asset_ids"], [])
        self.assertEqual(payload["supporting_run_ids"], [])

    def test_shooting_handoff_uses_only_matching_valid_artifact(self) -> None:
        request = shooting_execution.ShootingExecutionRequest(
            platform="小红书",
            content_type="视频",
            track="教程",
            topic="拍摄计划",
            shooting_goal="完成产品演示",
            locations=["办公室"],
            people=["主讲人"],
            reference_links=["https://example.com/ref?utm_source=share"],
        )
        row = {
            "record_id": "record_decon",
            "fields": {
                "source_url": "https://example.com/ref",
                "deconstruction_id": "decon_001",
                "evidence_uri": "media://tenants/00000000-0000-4000-8000-000000000101/artifact.json",
            },
        }

        def attach(record: object, *, tenant_id: str) -> object:
            self.assertEqual(tenant_id, TENANT_ID)
            record.detail_json.update(
                {
                    "reference_shots": [{"shot_id": "shot_001"}],
                    "pacing_notes": {"edit_recommendations": ["前三秒给结果"]},
                    "reuse_guardrails": {"required_transformations": ["换成自己的案例"]},
                }
            )
            return record

        with patch.object(shooting_execution, "load_material_candidate_rows_for_creation", return_value=[row]), patch.object(
            shooting_execution,
            "attach_deconstruction_artifact_brief",
            side_effect=attach,
        ):
            evidence = shooting_execution._resolve_deconstruction_evidence(request, tenant_id=TENANT_ID)

        self.assertEqual(evidence["status"], "confirmed")
        self.assertEqual(evidence["items"][0]["source_link"], "https://example.com/ref")
        self.assertEqual(evidence["items"][0]["reference_shots"], [{"shot_id": "shot_001"}])

    def test_shooting_handoff_degrades_when_artifact_is_invalid(self) -> None:
        request = shooting_execution.ShootingExecutionRequest(
            platform="小红书",
            content_type="视频",
            track="教程",
            topic="拍摄计划",
            shooting_goal="完成产品演示",
            locations=["办公室"],
            people=["主讲人"],
            reference_links=["https://example.com/ref"],
        )
        row = {"record_id": "record_decon", "fields": {"source_url": "https://example.com/ref"}}
        with patch.object(shooting_execution, "load_material_candidate_rows_for_creation", return_value=[row]), patch.object(
            shooting_execution,
            "attach_deconstruction_artifact_brief",
            side_effect=DeconstructionArtifactUnavailable("unsupported_deconstruction_schema"),
        ):
            evidence = shooting_execution._resolve_deconstruction_evidence(request, tenant_id=TENANT_ID)

        self.assertEqual(evidence["status"], "manual_description_only")
        self.assertEqual(evidence["reason"], "no_valid_deconstruction_artifact")
        self.assertEqual(evidence["unavailable"][0]["reason"], "unsupported_deconstruction_schema")

    def test_deconstruction_account_context_uses_allowlisted_profile_projection(self) -> None:
        with patch.object(
            runner,
            "build_media_context",
            return_value={
                "account_profile": {
                    "identity_summary": "独立开发者",
                    "content_pillars": ["产品实战"],
                    "internal_secret": "must never reach prompt",
                }
            },
        ):
            context = runner._account_context_for_deconstruction(
                "【拆解】 https://www.douyin.com/video/1 平台=抖音 账号=小王开发日志",
                tenant_id=TENANT_ID,
                platform="未抓取",
            )

        self.assertEqual(context["status"], "provided")
        self.assertEqual(context["platform"], "抖音")
        self.assertEqual(context["profile"], {"identity_summary": "独立开发者", "content_pillars": ["产品实战"]})

    def test_deconstruction_without_profile_cannot_claim_account_fit(self) -> None:
        result = runner._apply_account_context_boundary(
            {
                "viral_reuse_assessment": {"account_fit": {"level": "high", "reason": "原作文本说适合"}},
                "reuse_guardrails": {"own_account_mapping": {"own_persona": "原作人物"}},
            },
            {"status": "profile_not_found", "reason": runner.ACCOUNT_CONTEXT_UNAVAILABLE_REASON},
        )

        self.assertEqual(result["viral_reuse_assessment"]["account_fit"]["level"], "not_assessed")
        self.assertEqual(
            result["reuse_guardrails"]["own_account_mapping"]["reason"],
            runner.ACCOUNT_CONTEXT_UNAVAILABLE_REASON,
        )

    def test_deconstruction_prompt_marks_missing_profile_as_not_assessed(self) -> None:
        captured: list[list[dict[str, object]]] = []
        llm_result = {
            "viral_reuse_assessment": {"account_fit": {"level": "high", "reason": "bad"}},
            "reuse_guardrails": {"own_account_mapping": {"own_persona": "bad"}},
        }

        def fake_llm(parts: list[dict[str, object]], *args: object, **kwargs: object) -> dict[str, object]:
            captured.append(parts)
            return llm_result

        with patch.object(runner, "_call_llm", side_effect=fake_llm), patch.object(
            runner,
            "merge_llm_result_with_evidence",
            side_effect=lambda result, _evidence: result,
        ):
            result = runner.run_main_deconstruction_llm(
                text="【拆解】 https://example.com/video",
                evidence_store={},
                evidence=SimpleNamespace(parts=[], evidence_paths=[]),
                valid_asset_ids=set(),
                tenant_id="",
            )

        prompt = "\n".join(str(part.get("text") or "") for part in captured[0])
        self.assertIn(runner.ACCOUNT_CONTEXT_UNAVAILABLE_REASON, prompt)
        self.assertEqual(result["account_context"]["status"], "tenant_context_missing")
        self.assertEqual(result["viral_reuse_assessment"]["account_fit"]["level"], "not_assessed")


if __name__ == "__main__":
    unittest.main()
