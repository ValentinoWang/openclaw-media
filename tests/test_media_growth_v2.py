from __future__ import annotations

import os
import tempfile
import unittest
import json
import importlib.util
import hashlib
import threading
from pathlib import Path
from unittest.mock import patch

from media_vault import MediaVault
from selfmedia.growth import (
    TrackCreatorMembership,
    assert_dashboard_eligible,
    artifact_to_growth_summary_record,
    build_dashboard_projection,
    build_external_research_brief,
    build_publishing_pack,
    capture_source_asset,
    parse_media_growth_input,
    plan_media_growth_workflow,
    review_growth_artifact,
    run_media_growth_capability,
    sync_growth_summary_artifact,
)
from selfmedia.growth import service as growth_service
from selfmedia.growth.knowledge_evidence_contract import (
    InsufficientKnowledgeEvidence,
    KnowledgeEvidenceBundle,
    KnowledgeEvidenceContractError,
)
from selfmedia.growth.llm_runner import GrowthLLMJsonRunner


BACKFILL_SCRIPT = Path(__file__).resolve().parents[1] / "scripts/qa/check_media_growth_visibility_backfill.py"
DISPLAY_BACKFILL_SCRIPT = Path(__file__).resolve().parents[1] / "scripts/qa/check_media_growth_display_backfill.py"


def _load_optional_qa_backfill(path: Path, module_name: str):
    """Keep external operational-backfill checks out of the owned Growth suite."""
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


backfill_module = _load_optional_qa_backfill(BACKFILL_SCRIPT, "check_media_growth_visibility_backfill")
display_backfill_module = _load_optional_qa_backfill(DISPLAY_BACKFILL_SCRIPT, "check_media_growth_display_backfill")


class MediaGrowthV2Tests(unittest.TestCase):
    def _ready_knowledge_evidence_bundle(self) -> KnowledgeEvidenceBundle:
        return KnowledgeEvidenceBundle.from_dict(
            {
                "bundle_id": "knowledge_bundle_test",
                "query": "校园体育内容策略",
                "status": "ready",
                "evidence_items": [
                    {
                        "source_url": "https://example.com/research/source-1",
                        "source_type": "web_page",
                        "text_or_summary": "校园体育内容需要明确受众、场景和可验证案例。",
                        "citations": ["https://example.com/research/source-1#summary"],
                        "limitations": ["样本只覆盖公开页面。"],
                        "blocked_sources": ["https://blocked.example.com/paywalled"],
                        "status": "ready",
                    }
                ],
            }
        )

    @staticmethod
    def _research_payload(*, source_url: str = "https://example.com/research/source-1") -> dict[str, object]:
        return {
            "status": "done",
            "research_question": "校园体育内容是否值得做？",
            "media_goal": "判断校园体育赛道是否进入选题。",
            "audience_relevance": "受众关注训练场景和可验证案例。",
            "content_opportunity": "可以从训练复盘切入。",
            "usable_angles": ["400 米训练前后对比"],
            "unusable_angles": ["不编造成绩数据"],
            "risk_notes": ["公开页面样本有限"],
            "next_content_actions": ["进入 creation_decision_brief"],
            "source_evidence": [
                {"kind": "user_question", "text": "校园体育内容是否值得做？"},
                {"kind": "knowledge_evidence", "source_url": source_url, "status": "ready"},
            ],
            "display_title": "校园体育内容机会",
            "display_summary": "基于 typed evidence 形成调研 brief。",
        }

    @staticmethod
    def _decision_payload(*, source_ref: str = "https://example.com/research/source-1") -> dict[str, object]:
        return {
            "status": "done",
            "decision_goal": "判断下周选题。",
            "topic_candidates": [
                {
                    "title": "校园体育",
                    "target_audience": "校园跑者",
                    "audience_pain": "训练有效但不知道怎么复盘",
                    "content_angle": "用一场训练讲复盘方法",
                    "single_problem": "如何判断一次训练有没有价值",
                    "self_check": "必须引用证据",
                    "source_refs": [source_ref],
                }
            ],
            "recommended_next_capability_id": "selfmedia_creation",
            "risk_or_missing_info": ["需要人工确认拍摄素材"],
            "display_title": "校园体育选题",
            "display_summary": "基于证据生成候选选题。",
        }

    @staticmethod
    def _publishing_payload(*, title: str, caption: str, hashtags: list[str]) -> dict[str, object]:
        return {
            "status": "done",
            "title": title,
            "cover_text": title[:16],
            "caption": caption,
            "hashtags": hashtags,
            "comment_seed": "你会怎么判断这条内容是否值得继续做？",
            "publish_checklist": ["确认事实来源", "人工确认后发布"],
            "risk_notes": ["不执行自动发布"],
            "display_title": f"{title}发布包",
            "display_summary": "整理标题、封面和正文。",
        }

    def test_knowledge_evidence_bundle_validates_ready_typed_items(self) -> None:
        bundle = self._ready_knowledge_evidence_bundle().require_ready()

        payload = bundle.to_dict()
        item = payload["evidence_items"][0]
        self.assertEqual(payload["schema_version"], "knowledge_evidence_bundle_v1")
        self.assertEqual(item["source_url"], "https://example.com/research/source-1")
        self.assertEqual(item["source_type"], "web_page")
        self.assertTrue(item["source_hash"].startswith("sha256:"))
        self.assertEqual(item["status"], "ready")
        self.assertIn("https://example.com/research/source-1", item["citations"])
        self.assertIn("样本只覆盖公开页面。", item["limitations"])
        self.assertIn("https://blocked.example.com/paywalled", payload["blocked_sources"])

    def test_knowledge_reply_only_payload_is_pending_not_evidence(self) -> None:
        bundle = KnowledgeEvidenceBundle.from_dict(
            {
                "bundle_id": "reply_only",
                "query": "校园体育内容策略",
                "reply": "可以做，建议从校园跑步故事切入。",
                "status": "done",
            }
        )

        self.assertEqual(bundle.status, "pending_manual")
        self.assertEqual(bundle.evidence_items, ())
        self.assertIn("knowledge_reply", bundle.blocked_sources)
        with self.assertRaises(InsufficientKnowledgeEvidence):
            bundle.require_ready()

    def test_knowledge_reply_source_type_is_rejected_as_evidence_item(self) -> None:
        bundle = KnowledgeEvidenceBundle.from_dict(
            {
                "bundle_id": "reply_item",
                "query": "校园体育内容策略",
                "status": "ready",
                "evidence_items": [
                    {
                        "source_url": "knowledge://reply/latest",
                        "source_type": "knowledge_reply",
                        "text_or_summary": "Knowledge bot 的自然语言答复。",
                        "citations": ["knowledge://reply/latest"],
                        "status": "ready",
                    }
                ],
            }
        )

        with self.assertRaises(KnowledgeEvidenceContractError):
            bundle.require_ready()

    def test_growth_llm_runner_uses_fake_provider_with_typed_evidence(self) -> None:
        calls: list[dict[str, object]] = []
        settings = object()
        bundle = self._ready_knowledge_evidence_bundle()

        def fake_provider(parts, settings_arg, **kwargs):
            calls.append({"parts": parts, "settings": settings_arg, "kwargs": kwargs})
            request_text = "\n".join(str(part.get("text") or "") for part in parts)
            self.assertIn('"knowledge_evidence_bundle"', request_text)
            self.assertIn('"source_url": "https://example.com/research/source-1"', request_text)
            self.assertNotIn('"reply"', request_text)
            return {"status": "done", "decision": "manual_review_ready"}

        result = GrowthLLMJsonRunner(provider=fake_provider, settings=settings).run_json(
            task="media_growth_decision",
            prompt="判断是否进入选题。",
            evidence_bundle=bundle,
        )

        self.assertEqual(len(calls), 1)
        self.assertIs(calls[0]["settings"], settings)
        self.assertEqual(result["status"], "done")
        self.assertEqual(result["decision"], "manual_review_ready")
        self.assertEqual(result["evidence_bundle_id"], "knowledge_bundle_test")

    def test_growth_llm_runner_defaults_to_media_analysis_profile(self) -> None:
        loaded_profiles: list[str] = []

        def settings_loader(profile_name: str):
            loaded_profiles.append(profile_name)
            return object()

        result = GrowthLLMJsonRunner(
            provider=lambda *_args, **_kwargs: {"status": "done"},
            settings_loader=settings_loader,
        ).run_json(
            task="media_evidence_research",
            prompt="基于证据生成调研结论。",
            evidence_bundle=self._ready_knowledge_evidence_bundle(),
        )

        self.assertEqual(loaded_profiles, ["media_analysis"])
        self.assertEqual(result["status"], "done")

    def test_growth_llm_runner_without_provider_is_pending_manual(self) -> None:
        result = GrowthLLMJsonRunner(settings=object()).run_json(
            task="external_research_brief",
            prompt="基于证据生成调研结论。",
            evidence_bundle=self._ready_knowledge_evidence_bundle(),
        )

        self.assertEqual(result["status"], "pending_manual")
        self.assertIn("provider is unavailable", result["reason"])
        self.assertIn("growth_llm_json_provider", result["blocked_sources"])

    def test_growth_llm_runner_done_without_task_fields_is_pending_manual(self) -> None:
        result = GrowthLLMJsonRunner(
            provider=lambda *_args, **_kwargs: {"status": "done"},
            settings=object(),
        ).run_json(
            task="publishing_pack_build",
            prompt="生成发布包。",
            evidence_bundle=self._ready_knowledge_evidence_bundle(),
        )

        self.assertEqual(result["status"], "pending_manual")
        self.assertIn("missing required semantic fields", result["reason"])

    def test_growth_llm_runner_repairs_incomplete_success_once_with_llm(self) -> None:
        calls: list[str] = []

        def provider(parts, *_args, **_kwargs):
            calls.append("\n".join(str(part.get("text") or "") for part in parts))
            if len(calls) == 1:
                return {"status": "structured", "title": "首轮不完整发布包"}
            return self._publishing_payload(
                title="修复后的发布包",
                caption="完整正文",
                hashtags=["QA"],
            )

        result = GrowthLLMJsonRunner(provider=provider, settings=object(), max_retries=1).run_json(
            task="publishing_pack_build",
            prompt="生成发布包。",
            evidence_bundle=self._ready_knowledge_evidence_bundle(),
        )

        self.assertEqual(result["status"], "done")
        self.assertEqual(result["title"], "修复后的发布包")
        self.assertEqual(len(calls), 2)
        self.assertIn("validation_error", calls[1])

    def test_growth_llm_runner_normalizes_shapes_without_inventing_semantics(self) -> None:
        payload = {
            "status": "structured",
            "brand": "QA 品牌",
            "project_name": "QA 项目",
            "products": {"name": "QA 产品"},
            "platforms": "小红书",
            "content_format": "竖屏视频",
            "duration_requirement": "30 秒",
            "locations": [],
            "required_brand_mentions": "QA 品牌",
            "must_cover": "QA 标识",
            "narrative_direction": [],
            "interaction_design": [],
            "compliance_restrictions": "不得自动发布",
            "deliverables": {"type": "video"},
            "technical_specs": "1080P",
            "approval_requirements": "人工确认",
            "cleaned_brief": "QA 品牌 30 秒竖屏视频。",
            "risk_notes": [],
            "next_content_actions": "进入 shooting_execution_plan",
            "source_evidence": {"kind": "pasted_commercial_brief"},
            "display_title": "QA 商务 Brief",
            "display_summary": "已按原文整理。",
        }
        result = GrowthLLMJsonRunner(
            provider=lambda *_args, **_kwargs: payload,
            settings=object(),
        ).run_json(
            task="commercial_brief",
            prompt="整理 Brief。",
            require_evidence=False,
        )

        self.assertEqual(result["status"], "done")
        self.assertEqual(result["technical_specs"], {"description": "1080P"})
        self.assertEqual(result["platforms"], ["小红书"])
        self.assertEqual(result["products"], [{"name": "QA 产品"}])

    def test_growth_llm_runner_normalizes_legacy_audience_pain_to_main_creation_field(self) -> None:
        result = GrowthLLMJsonRunner(
            provider=lambda *_args, **_kwargs: self._decision_payload(),
            settings=object(),
        ).run_json(
            task="creation_decision_brief",
            prompt="基于证据生成选题。",
            evidence_bundle=self._ready_knowledge_evidence_bundle(),
        )

        candidate = result["topic_candidates"][0]
        self.assertEqual(candidate["pain_point"], "训练有效但不知道怎么复盘")
        self.assertEqual(candidate["audience_pain"], candidate["pain_point"])

    def test_growth_llm_runner_normalizes_completed_to_done(self) -> None:
        for provider_status in ("complete", "completed", "structured", "ready", "success", "succeeded"):
            with self.subTest(provider_status=provider_status):
                result = GrowthLLMJsonRunner(
                    provider=lambda *_args, **_kwargs: {"status": provider_status, "decision": "ready"},
                    settings=object(),
                ).run_json(
                    task="generic_growth_probe",
                    prompt="验证状态归一化。",
                    evidence_bundle=self._ready_knowledge_evidence_bundle(),
                )

                self.assertEqual(result["status"], "done")
                self.assertEqual(result["decision"], "ready")

    def test_growth_llm_runner_pending_manual_for_insufficient_evidence_skips_provider(self) -> None:
        calls: list[str] = []

        def forbidden_provider(*_args, **_kwargs):
            calls.append("called")
            raise AssertionError("provider must not run without typed evidence")

        result = GrowthLLMJsonRunner(provider=forbidden_provider, settings=object()).run_json(
            task="media_growth_decision",
            prompt="判断是否进入选题。",
            evidence_bundle={
                "bundle_id": "reply_only",
                "query": "校园体育内容策略",
                "reply": "可以做，建议从校园跑步故事切入。",
                "status": "done",
            },
        )

        self.assertEqual(calls, [])
        self.assertEqual(result["status"], "pending_manual")
        self.assertEqual(result["runtime_status"], "pending_manual")
        self.assertIn("evidence_items", result["reason"])
        self.assertIn("knowledge_reply", result["blocked_sources"])

    def test_external_research_brief_uses_typed_evidence_llm_payload(self) -> None:
        calls: list[str] = []
        bundle = self._ready_knowledge_evidence_bundle()

        def fake_provider(parts, settings_arg, **kwargs):
            calls.append("\n".join(str(part.get("text") or "") for part in parts))
            self.assertIsNotNone(settings_arg)
            return {
                "status": "done",
                "research_question": "校园体育内容是否值得做？",
                "media_goal": "判断校园体育赛道是否进入选题。",
                "audience_relevance": "受众关注训练场景和可验证案例。",
                "content_opportunity": "可以从训练复盘切入。",
                "usable_angles": ["400 米训练前后对比"],
                "unusable_angles": ["不编造成绩数据"],
                "risk_notes": ["公开页面样本有限"],
                "next_content_actions": ["进入 creation_decision_brief"],
                "source_evidence": [
                    {
                        "kind": "knowledge_evidence",
                        "source_url": "https://example.com/research/source-1",
                        "status": "ready",
                    }
                ],
                "display_title": "校园体育内容机会",
                "display_summary": "基于 typed evidence 形成调研 brief。",
            }

        with tempfile.TemporaryDirectory() as tmp:
            vault = MediaVault(tenant_id="00000000-0000-4000-8000-000000000101", root=tmp)
            brief = build_external_research_brief(
                "【调研】问题=校园体育内容是否值得做？",
                vault=vault,
                run_id="typed_research_brief",
                knowledge_evidence_bundle=bundle,
                growth_json_provider=fake_provider,
                growth_json_settings=object(),
            )
            payload = brief.to_dict()

        self.assertEqual(len(calls), 1)
        self.assertIn('"knowledge_evidence_bundle"', calls[0])
        self.assertEqual(payload["research_question"], "校园体育内容是否值得做？")
        self.assertEqual(payload["source_evidence"][0]["kind"], "knowledge_evidence")
        self.assertEqual(payload["display_title"], "校园体育内容机会")
        trace = next(item for item in payload["source_trace"] if item["source_type"] == "knowledge_evidence")
        self.assertTrue(trace["loaded"])
        self.assertEqual(trace["bundle_id"], "knowledge_bundle_test")

    def test_decision_brief_uses_typed_evidence_llm_candidates(self) -> None:
        def fake_provider(parts, settings_arg, **kwargs):
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
                        "source_refs": ["https://example.com/research/source-1"],
                    }
                ],
                "recommended_next_capability_id": "selfmedia_creation",
                "risk_or_missing_info": ["需要人工确认拍摄素材"],
                "display_title": "400 米训练复盘选题",
                "display_summary": "基于证据生成一个候选选题。",
            }

        with tempfile.TemporaryDirectory() as tmp:
            vault = MediaVault(tenant_id="00000000-0000-4000-8000-000000000101", root=tmp)
            brief = growth_service.build_decision_brief(
                "【选题】主题=400米训练",
                vault=vault,
                run_id="typed_decision_brief",
                knowledge_evidence_bundle=self._ready_knowledge_evidence_bundle(),
                growth_json_provider=fake_provider,
                growth_json_settings=object(),
            )
            payload = brief.to_dict()

        self.assertEqual(payload["decision_goal"], "判断下周选题。")
        self.assertEqual(payload["topic_candidates"][0]["title"], "400 米训练为什么要复盘")
        self.assertEqual(payload["topic_candidates"][0]["source_refs"], ["https://example.com/research/source-1"])
        self.assertEqual(payload["display_title"], "400 米训练复盘选题")
        trace = next(item for item in payload["source_trace"] if item["source_type"] == "knowledge_evidence")
        self.assertTrue(trace["loaded"])

    def test_publishing_pack_uses_typed_evidence_llm_payload(self) -> None:
        def fake_provider(parts, settings_arg, **kwargs):
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

        with tempfile.TemporaryDirectory() as tmp:
            vault = MediaVault(tenant_id="00000000-0000-4000-8000-000000000101", root=tmp)
            pack = build_publishing_pack(
                "【发布包】草稿=一次 400 米训练复盘",
                vault=vault,
                run_id="typed_publishing_pack",
                knowledge_evidence_bundle=self._ready_knowledge_evidence_bundle(),
                growth_json_provider=fake_provider,
                growth_json_settings=object(),
            )
            payload = pack.to_dict()

        self.assertEqual(payload["title"], "400 米训练复盘")
        self.assertEqual(payload["cover_text"], "训练不是鸡血")
        self.assertEqual(payload["caption"], "一次 400 米训练，最重要的是看见复盘指标。")
        self.assertEqual(payload["hashtags"], ["#短跑", "#训练复盘"])
        self.assertEqual(payload["publish_checklist"], ["确认事实来源", "人工确认后发布"])
        self.assertEqual(payload["display_title"], "400 米训练复盘发布包")

    def test_growth_service_pending_llm_payload_does_not_persist_artifact(self) -> None:
        def pending_provider(parts, settings_arg, **kwargs):
            return {
                "status": "pending_manual",
                "runtime_status": "pending_manual",
                "reason": "typed evidence is not sufficient",
            }

        with tempfile.TemporaryDirectory() as tmp:
            vault = MediaVault(tenant_id="00000000-0000-4000-8000-000000000101", root=tmp)
            with self.assertRaises(growth_service.MediaGrowthPendingManual):
                build_external_research_brief(
                    "【调研】问题=校园体育内容是否值得做？",
                    vault=vault,
                    run_id="pending_typed_research_brief",
                    knowledge_evidence_bundle=self._ready_knowledge_evidence_bundle(),
                    growth_json_provider=pending_provider,
                    growth_json_settings=object(),
                )
            self.assertFalse((vault.root / "research_briefs").exists())

    def test_publishing_pack_rejects_object_scalar_without_persisting(self) -> None:
        invalid_payload = self._publishing_payload(
            title="合法标题",
            caption="合法正文",
            hashtags=["QA"],
        )
        invalid_payload["title"] = {"unexpected": "object"}

        with tempfile.TemporaryDirectory() as tmp:
            vault = MediaVault(tenant_id="00000000-0000-4000-8000-000000000101", root=tmp)
            with patch.object(growth_service, "sync_growth_summary_artifact") as sync_summary:
                with self.assertRaises(growth_service.MediaGrowthPendingManual):
                    build_publishing_pack(
                        "【发布包】草稿=类型契约 QA",
                        vault=vault,
                        knowledge_evidence_bundle=self._ready_knowledge_evidence_bundle(),
                        growth_json_provider=lambda *_args, **_kwargs: invalid_payload,
                        growth_json_settings=object(),
                    )
                sync_summary.assert_not_called()
            self.assertFalse((vault.root / "publishing_packs").exists())

    def test_llm_driven_builders_without_provider_do_not_persist_artifacts(self) -> None:
        cases = (
            (
                build_external_research_brief,
                "【调研】问题=校园体育内容是否值得做？ https://example.com/source",
                "research_briefs",
                {"knowledge_evidence_bundle": self._ready_knowledge_evidence_bundle()},
            ),
            (
                growth_service.build_commercial_brief,
                "【Brief】品牌 brief 正文",
                "commercial_briefs",
                {},
            ),
            (
                growth_service.build_decision_brief,
                "【选题】主题=校园体育",
                "decision_briefs",
                {"knowledge_evidence_bundle": self._ready_knowledge_evidence_bundle()},
            ),
            (
                build_publishing_pack,
                "【发布包】草稿=校园体育复盘",
                "publishing_packs",
                {"knowledge_evidence_bundle": self._ready_knowledge_evidence_bundle()},
            ),
        )
        for builder, text, artifact_root, kwargs in cases:
            with self.subTest(artifact_root=artifact_root), tempfile.TemporaryDirectory() as tmp:
                vault = MediaVault(tenant_id="00000000-0000-4000-8000-000000000101", root=tmp)
                with self.assertRaises(growth_service.MediaGrowthPendingManual):
                    builder(text, vault=vault, **kwargs)
                self.assertFalse((vault.root / artifact_root).exists())

    def test_llm_driven_builders_reject_done_only_payload_without_persisting(self) -> None:
        def done_only_provider(*_args, **_kwargs):
            return {"status": "done"}

        cases = (
            (
                build_external_research_brief,
                "【调研】问题=校园体育内容是否值得做？ https://example.com/source",
                "research_briefs",
                {"knowledge_evidence_bundle": self._ready_knowledge_evidence_bundle()},
            ),
            (growth_service.build_commercial_brief, "【Brief】品牌 brief 正文", "commercial_briefs", {}),
            (
                growth_service.build_decision_brief,
                "【选题】主题=校园体育",
                "decision_briefs",
                {"knowledge_evidence_bundle": self._ready_knowledge_evidence_bundle()},
            ),
            (
                build_publishing_pack,
                "【发布包】草稿=校园体育复盘",
                "publishing_packs",
                {"knowledge_evidence_bundle": self._ready_knowledge_evidence_bundle()},
            ),
        )
        for builder, text, artifact_root, kwargs in cases:
            with self.subTest(artifact_root=artifact_root), tempfile.TemporaryDirectory() as tmp:
                vault = MediaVault(tenant_id="00000000-0000-4000-8000-000000000101", root=tmp)
                with self.assertRaises(growth_service.MediaGrowthPendingManual):
                    builder(
                        text,
                        vault=vault,
                        growth_json_provider=done_only_provider,
                        growth_json_settings=object(),
                        **kwargs,
                    )
                self.assertFalse((vault.root / artifact_root).exists())

    def test_decision_brief_without_llm_candidates_is_pending_manual_and_not_persisted(self) -> None:
        def empty_provider(parts, settings_arg, **kwargs):
            return {"status": "done", "topic_candidates": []}

        with tempfile.TemporaryDirectory() as tmp:
            vault = MediaVault(tenant_id="00000000-0000-4000-8000-000000000101", root=tmp)
            with self.assertRaises(growth_service.MediaGrowthPendingManual):
                growth_service.build_decision_brief(
                    "【选题】主题=校园体育",
                    vault=vault,
                    run_id="empty_candidate_decision_brief",
                    knowledge_evidence_bundle=self._ready_knowledge_evidence_bundle(),
                    growth_json_provider=empty_provider,
                    growth_json_settings=object(),
                )
            self.assertFalse(list((vault.root / "decision_briefs").glob("*/result.json")))

    def test_source_asset_preserves_existing_link_and_writes_media_vault_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = MediaVault(tenant_id="00000000-0000-4000-8000-000000000101", root=tmp)
            asset = capture_source_asset(
                "【素材】做题家+清北候选人，真的很难大成 http://xhslink.com/o/16704LMMFPp",
                platform="小红书",
                vault=vault,
                run_id="source_asset_test",
            )

            payload = asset.to_dict()
            self.assertEqual(payload["artifact_type"], "SourceAsset")
            self.assertEqual(payload["schema_version"], "media_growth_artifact_v1")
            self.assertEqual(payload["quality_status"], "pending_review")
            self.assertEqual(payload["urls"], ["http://xhslink.com/o/16704LMMFPp"])
            self.assertTrue(payload["artifact_uri"].startswith("media://tenants/00000000-0000-4000-8000-000000000101/source_assets/source_asset_test/"))
            self.assertTrue((vault.root / "source_assets/source_asset_test/result.json").exists())

    def test_source_asset_preserves_deconstruct_request_constraints(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            vault = MediaVault(tenant_id="00000000-0000-4000-8000-000000000101", root=Path(tmpdir))
            asset = growth_service.capture_source_asset(
                "【素材】\n素材类型：视频\n用途：拆解\n链接或附件：https://example.com/v\n补充说明：只分析前5秒钩子和转场，输出人性洞察心理机制卡",
                vault=vault,
                run_id="source_asset_constraints",
            )
            payload = asset.to_dict()

        constraints = payload["request_constraints"]
        self.assertEqual(constraints["analysis_scope"], "开头")
        self.assertEqual(constraints["analysis_time_range"], "0-5s")
        self.assertIn("钩子", constraints["deconstruction_focus"])
        self.assertIn("转场", constraints["deconstruction_focus"])
        self.assertIn("人性洞察", constraints["deconstruction_focus"])
        self.assertIn("心理机制卡", constraints["output_types"])
        self.assertEqual(constraints["write_policy"], "source_asset_only")

    def test_transition_only_constraints_keep_valid_time_range_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            vault = MediaVault(tenant_id="00000000-0000-4000-8000-000000000101", root=Path(tmpdir))
            asset = growth_service.capture_source_asset(
                "【素材】\n用途：拆解\n链接或附件：https://example.com/v\n补充说明：只分析转场，不做全片拆解",
                vault=vault,
                run_id="source_asset_transition_constraints",
            )
            payload = asset.to_dict()

        constraints = payload["request_constraints"]
        self.assertEqual(constraints["analysis_scope"], "转场")
        self.assertEqual(constraints["analysis_time_range"], "全部")
        self.assertIn("转场", constraints["deconstruction_focus"])
        self.assertNotEqual(constraints["analysis_time_range"], "全部转场")

    def test_media_research_brief_is_media_artifact_not_knowledge_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = MediaVault(tenant_id="00000000-0000-4000-8000-000000000101", root=tmp)
            brief = build_external_research_brief(
                "【调研】账号=小王 平台=抖音 问题=高考专业选择内容能不能做 https://www.douyin.com/video/7654247930551244785",
                platform="抖音",
                account_id="小王",
                track_id="升学",
                vault=vault,
                run_id="research_brief_test",
                knowledge_evidence_bundle=self._ready_knowledge_evidence_bundle(),
                growth_json_provider=lambda *_args, **_kwargs: self._research_payload(
                    source_url="https://www.douyin.com/video/7654247930551244785"
                ),
                growth_json_settings=object(),
            )

            payload = brief.to_dict()
            self.assertEqual(payload["source_capability_id"], "external_research_brief")
            self.assertEqual(payload["artifact_type"], "ExternalResearchBrief")
            self.assertTrue(payload["source_trace"][1]["loaded"])
            self.assertEqual(payload["source_evidence"][1]["source_url"], "https://www.douyin.com/video/7654247930551244785")

    def test_media_research_display_fields_strip_url_but_source_evidence_keeps_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = MediaVault(tenant_id="00000000-0000-4000-8000-000000000101", root=tmp)
            url = "https://www.douyin.com/video/7654247930551244785"
            brief = build_external_research_brief(
                f"【调研】问题=高考专业选择内容能不能做 {url}",
                platform="抖音",
                vault=vault,
                run_id="research_brief_url_display_test",
                knowledge_evidence_bundle=self._ready_knowledge_evidence_bundle(),
                growth_json_provider=lambda *_args, **_kwargs: self._research_payload(source_url=url),
                growth_json_settings=object(),
            )

            payload = brief.to_dict()
            self.assertNotIn("http://", payload["display_title"])
            self.assertNotIn("https://", payload["display_title"])
            self.assertNotIn("http://", payload["display_summary"])
            self.assertNotIn("https://", payload["display_summary"])
            self.assertEqual(payload["source_evidence"][1]["source_url"], url)

    def test_media_research_without_evidence_does_not_write_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = MediaVault(tenant_id="00000000-0000-4000-8000-000000000101", root=tmp)
            plan, payload = run_media_growth_capability(
                "external_research_brief",
                "【调研】账号=小王 平台=抖音 问题=校园体育长期内容策略怎么拆？",
                vault=vault,
            )
            self.assertFalse((vault.root / "research_briefs").exists())
        self.assertEqual(plan.contract_check_result, "passed")
        self.assertEqual(payload["runtime_status"], "pending_manual")

    def test_publishing_pack_never_allows_auto_publish(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = MediaVault(tenant_id="00000000-0000-4000-8000-000000000101", root=tmp)
            pack = build_publishing_pack(
                "【发布包】平台=抖音 草稿=清北光环为什么不等于创业成功 #创业 #清北",
                platform="抖音",
                vault=vault,
                run_id="publishing_pack_test",
                knowledge_evidence_bundle=self._ready_knowledge_evidence_bundle(),
                growth_json_provider=lambda *_args, **_kwargs: self._publishing_payload(
                    title="清北光环为什么不等于创业成功",
                    caption="清北光环为什么不等于创业成功 #创业 #清北",
                    hashtags=["创业", "清北"],
                ),
                growth_json_settings=object(),
            )
            payload = pack.to_dict()
            self.assertEqual(payload["artifact_type"], "PublishingPack")
            self.assertEqual(payload["caption"], "清北光环为什么不等于创业成功 #创业 #清北")
            self.assertFalse(payload["automatic_publish_allowed"])
            self.assertIn("不执行自动发布", " ".join(payload["risk_notes"]))

    def test_publishing_pack_adapter_maps_only_source_backed_creator_fields(self) -> None:
        legacy_pack = self._publishing_payload(
            title="起跑前一秒",
            caption="起跑前一秒，所有准备都变成身体的记忆。",
            hashtags=["短跑", "比赛"],
        )
        legacy_pack["publish_checklist"] = ["发布后 1 小时回复前三条具体提问"]
        adapter = growth_service.normalize_publishing_pack_for_creation(legacy_pack)

        creator_pack = adapter["creator_publishing_pack"]
        self.assertEqual(creator_pack["title_1"], "起跑前一秒")
        self.assertEqual(creator_pack["cover_text"], "起跑前一秒")
        self.assertEqual(creator_pack["body_copy"], "起跑前一秒，所有准备都变成身体的记忆。")
        self.assertEqual(creator_pack["pinned_comment"], legacy_pack["comment_seed"])
        self.assertEqual(creator_pack["comment_prompt"], legacy_pack["comment_seed"])
        self.assertEqual(creator_pack["first_hour_action"], "发布后 1 小时回复前三条具体提问")
        self.assertEqual(creator_pack["title_2"], "")
        self.assertEqual(adapter["missing_creator_fields"], ["title_2"])
        self.assertEqual(adapter["field_mappings"]["body_copy"], ["caption"])

    def test_publishing_pack_loads_bare_creation_run_draft_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = MediaVault(tenant_id="00000000-0000-4000-8000-000000000101", root=tmp)
            vault.write_creation_run_artifacts(
                "creation_run_for_publish",
                request={"entrypoint": "【创作>抖音】", "input": "短跑赛前准备"},
                draft_output={
                    "platform": "抖音",
                    "content_type": "视频",
                    "title": "起跑前一秒",
                    "final_copy": "起跑前一秒，所有准备都变成身体的记忆。",
                    "tags": ["短跑", "比赛"],
                },
            )

            self.assertFalse((vault.root / "creation_runs/creation_run_for_publish/result.json").exists())
            resolved_type = growth_service.resolve_growth_artifact_type("creation_run_for_publish", vault=vault)
            self.assertEqual(resolved_type, "DraftPackage")
            self.assertEqual(growth_service.resolve_growth_artifact_path("creation_run_for_publish", vault=vault).name, "draft_output.json")
            typed_plan = plan_media_growth_workflow(
                requested_capability_id="publishing_pack_build",
                input_artifact_ids=("creation_run_for_publish",),
                input_artifact_types=(resolved_type,),
            )
            self.assertEqual(typed_plan.contract_check_result, "passed")
            plan, payload = run_media_growth_capability(
                "publishing_pack_build",
                "【发布包】draft_id=creation_run_for_publish",
                vault=vault,
                growth_json_provider=lambda *_args, **_kwargs: self._publishing_payload(
                    title="起跑前一秒",
                    caption="起跑前一秒，所有准备都变成身体的记忆。",
                    hashtags=["短跑", "比赛"],
                ),
                growth_json_settings=object(),
            )

        self.assertEqual(plan.contract_check_result, "passed")
        self.assertEqual(payload["runtime_status"], "artifact_created")
        self.assertEqual(payload["title"], "起跑前一秒")
        self.assertEqual(payload["caption"], "起跑前一秒，所有准备都变成身体的记忆。")
        self.assertEqual(payload["hashtags"], ["#短跑", "#比赛"])
        self.assertNotIn("{", payload["caption"])
        trace = next(item for item in payload["source_trace"] if item["source_type"] == "input_artifacts")
        self.assertTrue(trace["loaded"])
        self.assertEqual(trace["artifacts"][0]["artifact_type"], "DraftPackage")
        self.assertEqual(trace["artifacts"][0]["source_creation_run_file"], "draft_output.json")

    def test_publishing_pack_loads_creation_run_draft_json_uri_and_run_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = MediaVault(tenant_id="00000000-0000-4000-8000-000000000101", root=tmp)
            draft_manifest = vault.write_json_artifact(
                vault.creation_run_dir("legacy_creation_run"),
                "draft.json",
                {
                    "title": "麦积山石窟避坑",
                    "caption": "去麦积山石窟怕踩坑，先看交通、体力和机位。",
                    "hashtags": ["天水", "毕业旅行"],
                },
                owner_type="CreationRun",
                owner_id="legacy_creation_run",
                artifact_type="draft",
            )

            pack = build_publishing_pack(
                "【发布包】run_id=legacy_creation_run",
                vault=vault,
                input_artifact_ids=(draft_manifest["uri"],),
                run_id="pack_from_legacy_creation_run",
                growth_json_provider=lambda *_args, **_kwargs: self._publishing_payload(
                    title="麦积山石窟避坑",
                    caption="去麦积山石窟怕踩坑，先看交通、体力和机位。",
                    hashtags=["天水", "毕业旅行"],
                ),
                growth_json_settings=object(),
            )
            resolved_type = growth_service.resolve_growth_artifact_type(draft_manifest["uri"], vault=vault)

        payload = pack.to_dict()
        self.assertEqual(resolved_type, "DraftPackage")
        self.assertEqual(payload["title"], "麦积山石窟避坑")
        self.assertEqual(payload["caption"], "去麦积山石窟怕踩坑，先看交通、体力和机位。")
        self.assertEqual(payload["hashtags"], ["#天水", "#毕业旅行"])
        self.assertIn("media://tenants/00000000-0000-4000-8000-000000000101/creation_runs/legacy_creation_run/draft.json", payload["asset_refs"])

    def test_publish_readiness_gate_accepts_publishing_pack_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = MediaVault(tenant_id="00000000-0000-4000-8000-000000000101", root=tmp)
            pack = build_publishing_pack(
                "【发布包】平台=抖音 标题=起跑前一秒 草稿=起跑前一秒，所有准备都变成身体的记忆。",
                vault=vault,
                run_id="pack_for_readiness",
                knowledge_evidence_bundle=self._ready_knowledge_evidence_bundle(),
                growth_json_provider=lambda *_args, **_kwargs: self._publishing_payload(
                    title="起跑前一秒",
                    caption="起跑前一秒，所有准备都变成身体的记忆。",
                    hashtags=[],
                ),
                growth_json_settings=object(),
            )
            plan, payload = run_media_growth_capability(
                "publish_readiness_gate",
                f"【检查】source={pack.artifact_uri}",
                input_artifact_ids=(pack.artifact_uri,),
                input_artifact_types=("PublishingPack",),
                vault=vault,
            )

        self.assertEqual(plan.contract_check_result, "passed")
        self.assertEqual(payload["runtime_status"], "artifact_created")
        self.assertEqual(payload["artifact_type"], "PublishReadinessGate")
        self.assertTrue(payload["ready_to_publish"])
        self.assertEqual(payload["gate_status"], "ready")
        self.assertFalse(payload["automatic_publish_allowed"])

    def test_decision_brief_recommends_existing_creation_path(self) -> None:
        def provider(parts, settings_arg, **kwargs):
            return self._decision_payload(source_ref="explicit:user_input")

        with tempfile.TemporaryDirectory() as tmp:
            vault = MediaVault(tenant_id="00000000-0000-4000-8000-000000000101", root=tmp)
            plan, payload = run_media_growth_capability(
                "creation_decision_brief",
                "【选题】主题=400米训练",
                vault=vault,
                knowledge_evidence_bundle=self._ready_knowledge_evidence_bundle(),
                growth_json_provider=provider,
                growth_json_settings=object(),
            )
        self.assertEqual(plan.contract_check_result, "passed")
        self.assertEqual(payload["recommended_next_capability_id"], "selfmedia_creation")
        self.assertNotEqual(payload["recommended_next_capability_id"], "creator_brief_to_draft")

    def test_planner_supports_single_node_continue_and_preset(self) -> None:
        single = plan_media_growth_workflow(requested_capability_id="style_polish_run", text="【润色】原文=...")
        self.assertEqual(single.workflow_mode, "single_node")
        self.assertEqual(single.planned_nodes[0].produces, ("StylePolishResult", "OutputVariant"))

        continued = plan_media_growth_workflow(
            requested_capability_id="creation_decision_brief",
            input_artifact_ids=("source_asset_1",),
            input_artifact_types=("SourceAsset",),
        )
        self.assertEqual(continued.workflow_mode, "continue_from_artifact")
        self.assertEqual(continued.contract_check_result, "passed")

        rejected = plan_media_growth_workflow(
            requested_capability_id="publishing_pack_build",
            input_artifact_ids=("source_asset_1",),
            input_artifact_types=("SourceAsset",),
        )
        self.assertEqual(rejected.contract_check_result, "failed")

        preset = plan_media_growth_workflow(requested_capability_id="", explicit_preset="draft_to_publish_pack")
        self.assertEqual([node.canonical_capability_id for node in preset.planned_nodes], ["style_polish_run", "publishing_pack_build", "publish_readiness_gate"])

    def test_preset_flow_serial_executes_only_when_all_nodes_are_implemented(self) -> None:
        def provider(parts, settings_arg, **kwargs):
            return self._decision_payload(source_ref="explicit:user_input")

        with tempfile.TemporaryDirectory() as tmp:
            vault = MediaVault(tenant_id="00000000-0000-4000-8000-000000000101", root=tmp)
            plan, payload = run_media_growth_capability(
                "",
                "【素材】一条素材",
                explicit_preset="asset_to_topic",
                vault=vault,
                growth_json_provider=provider,
                growth_json_settings=object(),
            )
        self.assertEqual(plan.workflow_mode, "preset_flow")
        self.assertEqual(payload["runtime_status"], "artifact_created")
        self.assertEqual([item["source_capability_id"] for item in payload["preset_node_results"]], ["source_asset_intake", "creation_decision_brief"])

    def test_metrics_to_next_topics_preset_writes_review_signal_then_decision(self) -> None:
        calls: list[str] = []

        def fake_provider(parts, settings_arg, **kwargs):
            request_text = "\n".join(str(part.get("text") or "") for part in parts)
            calls.append(request_text)
            self.assertIn("media_growth_artifact:ReviewSignal", request_text)
            return {
                "status": "done",
                "decision_goal": "把复盘信号转成下周选题。",
                "topic_candidates": [
                    {
                        "title": "高收藏内容为什么值得做系列化",
                        "target_audience": "校园成长内容受众",
                        "audience_pain": "收藏高但不知道如何复用方法",
                        "content_angle": "围绕收藏原因拆系列选题",
                        "single_problem": "如何把一次有效内容复用成系列",
                        "self_check": "引用 ReviewSignal",
                        "source_refs": ["review_signal"],
                    }
                ],
                "recommended_next_capability_id": "selfmedia_creation",
                "risk_or_missing_info": ["需要核对平台后台截图"],
                "display_title": "复盘驱动选题",
                "display_summary": "从 ReviewSignal 生成候选选题。",
            }

        with tempfile.TemporaryDirectory() as tmp:
            vault = MediaVault(tenant_id="00000000-0000-4000-8000-000000000101", root=tmp)
            plan, payload = run_media_growth_capability(
                "post_review_signal",
                "【复盘】流程=metrics_to_next_topics 平台=小红书 播放=1000 收藏=300 结论=收藏明显高于点赞 下一步=做收藏理由拆解",
                explicit_preset="metrics_to_next_topics",
                vault=vault,
                growth_json_provider=fake_provider,
                growth_json_settings=object(),
                require_typed_evidence_for_semantic_runs=True,
            )

        self.assertEqual(plan.workflow_mode, "preset_flow")
        self.assertEqual(payload["runtime_status"], "artifact_created")
        self.assertEqual([item["source_capability_id"] for item in payload["preset_node_results"]], ["post_review_signal", "creation_decision_brief"])
        self.assertEqual(payload["preset_node_results"][0]["artifact_type"], "ReviewSignal")
        self.assertEqual(payload["topic_candidates"][0]["title"], "高收藏内容为什么值得做系列化")
        self.assertEqual(len(calls), 1)

    def test_decision_brief_loads_only_same_tenant_review_memory_and_signals(self) -> None:
        captured: list[str] = []

        def provider(parts, _settings, **_kwargs):
            captured.append("\n".join(str(part.get("text") or "") for part in parts))
            return self._decision_payload(source_ref="same_tenant_review")

        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"SELFMEDIA_MEMORY_ROOT": tmp}):
            own_vault = MediaVault(tenant_id="00000000-0000-4000-8000-000000000101", root=tmp)
            foreign_vault = MediaVault(tenant_id="00000000-0000-4000-8000-000000000102", root=tmp)
            own_signal = growth_service.capture_review_signal(
                "【复盘】结论=同租户复盘：收藏高的训练拆解值得继续做 下一步=继续做训练复盘系列",
                platform="抖音",
                account_id="主账号",
                vault=own_vault,
                run_id="same_tenant_review",
            )
            growth_service.capture_review_signal(
                "【复盘】结论=跨租户内容绝不能进入当前选题 下一步=不应被读取",
                platform="抖音",
                account_id="主账号",
                vault=foreign_vault,
                run_id="foreign_review",
            )
            brief = growth_service.build_decision_brief(
                "【选题】主题=训练复盘系列",
                platform="抖音",
                account_id="主账号",
                vault=own_vault,
                run_id="decision_from_owned_review",
                growth_json_provider=provider,
                growth_json_settings=object(),
            )
            memory_rows = [
                json.loads(line)
                for line in (Path(tmp) / "tenants" / own_vault.tenant_id / "reviews.jsonl").read_text(encoding="utf-8").splitlines()
            ]

        self.assertEqual(len(captured), 1)
        self.assertIn("同租户复盘：收藏高的训练拆解值得继续做", captured[0])
        self.assertNotIn("跨租户内容绝不能进入当前选题", captured[0])
        self.assertIn("account_memory", captured[0])
        self.assertEqual(memory_rows[0]["source"], "media_growth:ReviewSignal:same_tenant_review")
        self.assertEqual(memory_rows[0]["account"], "主账号")
        self.assertEqual(brief.topic_candidates[0]["pain_point"], "训练有效但不知道怎么复盘")
        self.assertEqual(brief.topic_candidates[0]["audience_pain"], brief.topic_candidates[0]["pain_point"])
        trace = next(item for item in brief.to_dict()["source_trace"] if item["source_type"] == "input_artifacts")
        self.assertEqual(trace["artifacts"][0]["artifact_uri"], own_signal.artifact_uri)

    def test_default_full_plan_stops_pending_manual_without_llm_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = MediaVault(tenant_id="00000000-0000-4000-8000-000000000101", root=tmp)
            plan, payload = run_media_growth_capability(
                "",
                "【素材】请给我完整发布方案",
                vault=vault,
            )
            self.assertTrue((vault.root / "source_assets").exists())
            self.assertFalse(list((vault.root / "decision_briefs").glob("*/result.json")))
        self.assertEqual(plan.workflow_mode, "preset_flow")
        self.assertEqual(payload["runtime_status"], "pending_manual")
        self.assertEqual(
            [node.canonical_capability_id for node in plan.planned_nodes],
            ["source_asset_intake", "creation_decision_brief"],
        )

    def test_fresh_candidate_is_not_dashboard_visible_until_reviewed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = MediaVault(tenant_id="00000000-0000-4000-8000-000000000101", root=tmp)
            asset = capture_source_asset("【素材】平台=小红书 备注=一条候选素材", vault=vault, run_id="candidate_source")
        payload = asset.to_dict()
        projection = build_dashboard_projection([payload], growth_summaries=[payload])
        self.assertEqual(projection["provenance"]["visibleGrowthSummaries"], 0)

    def test_review_approval_promotes_candidate_to_dashboard_visible(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = MediaVault(tenant_id="00000000-0000-4000-8000-000000000101", root=tmp)
            asset = capture_source_asset("【素材】一条候选素材", vault=vault, run_id="reviewable_source")
            with patch.dict(os.environ, {"OPENCLAW_MEDIA_GROWTH_REVIEWERS": "tester", "FEISHU_ALLOWED_USERS": ""}):
                result = review_growth_artifact(asset.artifact_id, action="approve", reviewer_id="tester", vault=vault)
            payload = json.loads((vault.root / "source_assets/reviewable_source/result.json").read_text(encoding="utf-8"))
            manifest = json.loads((vault.root / "source_assets/reviewable_source/result.json.manifest.json").read_text(encoding="utf-8"))
            result_bytes = (vault.root / "source_assets/reviewable_source/result.json").read_bytes()
            projection = build_dashboard_projection([payload], growth_summaries=[payload])

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "artifact_approved")
        self.assertEqual(payload["quality_status"], "cleaned")
        self.assertEqual(payload["review_action"], "approve")
        self.assertEqual(payload["reviewed_by"], "tester")
        self.assertEqual(projection["provenance"]["visibleGrowthSummaries"], 1)
        self.assertEqual(manifest["content_hash"], f"sha256:{hashlib.sha256(result_bytes).hexdigest()}")
        self.assertEqual(manifest["size_bytes"], len(result_bytes))

    def test_review_rejection_keeps_candidate_off_dashboard(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = MediaVault(tenant_id="00000000-0000-4000-8000-000000000101", root=tmp)
            asset = capture_source_asset("【素材】一条不采用素材", vault=vault, run_id="rejected_source")
            with patch.dict(os.environ, {"OPENCLAW_MEDIA_GROWTH_REVIEWERS": "tester", "FEISHU_ALLOWED_USERS": ""}):
                result = review_growth_artifact(asset.artifact_id, action="reject", reviewer_id="tester", vault=vault)
            payload = json.loads((vault.root / "source_assets/rejected_source/result.json").read_text(encoding="utf-8"))
        projection = build_dashboard_projection([payload], growth_summaries=[payload])

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "artifact_rejected")
        self.assertEqual(payload["quality_status"], "rejected")
        self.assertFalse(payload["front_end_eligible"])
        self.assertEqual(projection["provenance"]["visibleGrowthSummaries"], 0)

    def test_review_approval_after_rejection_restores_candidate_and_keeps_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = MediaVault(tenant_id="00000000-0000-4000-8000-000000000101", root=tmp)
            asset = capture_source_asset("【素材】一条先废弃后恢复的素材", vault=vault, run_id="review_history_source")
            with patch.dict(os.environ, {"OPENCLAW_MEDIA_GROWTH_REVIEWERS": "tester", "FEISHU_ALLOWED_USERS": ""}):
                rejected = review_growth_artifact(asset.artifact_id, action="reject", reviewer_id="tester", note="证据不足", vault=vault)
                approved = review_growth_artifact(asset.artifact_id, action="approve", reviewer_id="tester", note="补证据后通过", vault=vault)
            payload = json.loads((vault.root / "source_assets/review_history_source/result.json").read_text(encoding="utf-8"))
        projection = build_dashboard_projection([payload], growth_summaries=[payload])

        self.assertTrue(rejected["ok"])
        self.assertTrue(approved["ok"])
        self.assertEqual(payload["status"], "candidate")
        self.assertEqual(payload["quality_status"], "cleaned")
        self.assertTrue(payload["front_end_eligible"])
        self.assertEqual([item["action"] for item in payload["review_history"]], ["reject", "approve"])
        self.assertEqual(projection["provenance"]["visibleGrowthSummaries"], 1)

    def test_concurrent_review_preserves_history_entries_and_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = MediaVault(tenant_id="00000000-0000-4000-8000-000000000101", root=tmp)
            asset = capture_source_asset("【素材】一条并发复核素材", vault=vault, run_id="review_concurrent_source")
            errors: list[dict[str, object]] = []

            def run_review(action: str, reviewer_id: str) -> None:
                result = review_growth_artifact(asset.artifact_id, action=action, reviewer_id=reviewer_id, vault=vault)
                if not result.get("ok"):
                    errors.append(result)

            threads = [
                threading.Thread(target=run_review, args=("approve", "reviewer-a")),
                threading.Thread(target=run_review, args=("reject", "reviewer-b")),
            ]
            with patch.dict(os.environ, {"OPENCLAW_MEDIA_GROWTH_REVIEWERS": "reviewer-a,reviewer-b", "FEISHU_ALLOWED_USERS": ""}):
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join()

            result_path = vault.root / "source_assets/review_concurrent_source/result.json"
            payload = json.loads(result_path.read_text(encoding="utf-8"))
            manifest = json.loads(result_path.with_name("result.json.manifest.json").read_text(encoding="utf-8"))
            result_bytes = result_path.read_bytes()

        self.assertFalse(errors)
        self.assertEqual(len(payload["review_history"]), 2)
        self.assertEqual({item["action"] for item in payload["review_history"]}, {"approve", "reject"})
        self.assertEqual({item["reviewed_by"] for item in payload["review_history"]}, {"reviewer-a", "reviewer-b"})
        self.assertEqual(manifest["content_hash"], f"sha256:{hashlib.sha256(result_bytes).hexdigest()}")
        self.assertEqual(manifest["size_bytes"], len(result_bytes))

    def test_review_requires_allowed_reviewer_when_configured(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = MediaVault(tenant_id="00000000-0000-4000-8000-000000000101", root=tmp)
            asset = capture_source_asset("【素材】一条需要授权复核的素材", vault=vault, run_id="review_acl_source")
            with patch.dict(os.environ, {"OPENCLAW_MEDIA_GROWTH_REVIEWERS": "allowed-user", "FEISHU_ALLOWED_USERS": ""}):
                denied = review_growth_artifact(asset.artifact_id, action="approve", reviewer_id="other-user", vault=vault)
                approved = review_growth_artifact(asset.artifact_id, action="approve", reviewer_id="allowed-user", vault=vault)

        self.assertFalse(denied["ok"])
        self.assertEqual(denied["status"], "review_unauthorized")
        self.assertTrue(approved["ok"])
        self.assertEqual(approved["quality_status"], "cleaned")

    def test_review_rejects_when_reviewer_allowlist_is_not_configured(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = MediaVault(tenant_id="00000000-0000-4000-8000-000000000101", root=tmp)
            asset = capture_source_asset("【素材】一条没有 allowlist 的素材", vault=vault, run_id="review_no_acl_source")
            with patch.dict(os.environ, {"OPENCLAW_MEDIA_GROWTH_REVIEWERS": "", "FEISHU_ALLOWED_USERS": ""}):
                result = review_growth_artifact(asset.artifact_id, action="approve", reviewer_id="tester", vault=vault)
            payload = json.loads((vault.root / "source_assets/review_no_acl_source/result.json").read_text(encoding="utf-8"))

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "review_authorization_not_configured")
        self.assertEqual(payload["quality_status"], "pending_review")

    def test_review_does_not_use_general_feishu_allowed_users_as_reviewers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = MediaVault(tenant_id="00000000-0000-4000-8000-000000000101", root=tmp)
            asset = capture_source_asset("【素材】一条普通消息 allowlist 用户不能复核的素材", vault=vault, run_id="review_general_acl_source")
            with patch.dict(os.environ, {"OPENCLAW_MEDIA_GROWTH_REVIEWERS": "", "FEISHU_ALLOWED_USERS": "tester"}):
                result = review_growth_artifact(asset.artifact_id, action="approve", reviewer_id="tester", vault=vault)
            payload = json.loads((vault.root / "source_assets/review_general_acl_source/result.json").read_text(encoding="utf-8"))

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "review_authorization_not_configured")
        self.assertEqual(payload["quality_status"], "pending_review")

    def test_review_rejects_absolute_path_outside_vault(self) -> None:
        with tempfile.TemporaryDirectory() as vault_tmp, tempfile.TemporaryDirectory() as outside_tmp:
            vault = MediaVault(tenant_id="00000000-0000-4000-8000-000000000101", root=vault_tmp)
            outside = Path(outside_tmp) / "result.json"
            outside.write_text(
                json.dumps(
                    {
                        "schema_version": "media_growth_artifact_v1",
                        "artifact_id": "outside",
                        "artifact_type": "SourceAsset",
                        "source_capability_id": "source_asset_intake",
                    }
                ),
                encoding="utf-8",
            )
            result = review_growth_artifact(str(outside), action="approve", reviewer_id="tester", vault=vault)

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "artifact_not_found")

    def test_dashboard_projection_filters_raw_failed_debug_and_pending_artifacts(self) -> None:
        visible = {
            "artifact_id": "ok",
            "artifact_type": "SourceAsset",
            "status": "candidate",
            "visibility": "ops",
            "quality_status": "cleaned",
            "front_end_eligible": True,
            "display_title": "可展示素材",
            "display_summary": "已清洗",
        }
        failed = {**visible, "artifact_id": "failed", "status": "failed"}
        raw = {**visible, "artifact_id": "raw", "quality_status": "raw"}
        debug = {**visible, "artifact_id": "debug", "visibility": "debug"}
        pending = {**visible, "artifact_id": "pending", "quality_status": "pending_review"}

        artifacts = [visible, failed, raw, debug, pending]
        projection = build_dashboard_projection(artifacts, growth_summaries=artifacts)
        self.assertEqual(projection["provenance"]["visibleGrowthSummaries"], 1)
        self.assertNotIn("items", projection)
        self.assertNotIn("reviewQueue", projection)

    def test_fit_score_invalid_string_is_rejected_without_semantic_fallback(self) -> None:
        with self.assertRaisesRegex(ValueError, "fit_score"):
            TrackCreatorMembership(membership_id="m1", track_id="t1", creator_profile_id="c1", fit_score="abc")

    def test_structured_parser_separates_params_and_display_text(self) -> None:
        parsed = parse_media_growth_input("【拍摄】平台=抖音 主题=400米训练 场地=操场 模式=第一视角 正文=说明正文")
        self.assertEqual(parsed.value("平台"), "抖音")
        self.assertEqual(parsed.value("主题"), "400米训练")
        self.assertEqual(parsed.value("场地"), "操场")
        self.assertEqual(parsed.value("模式"), "第一视角")
        self.assertEqual(parsed.value("正文"), "说明正文")

    def test_structured_parser_accepts_chinese_source_alias_and_keeps_review_action_text(self) -> None:
        parsed = parse_media_growth_input("【选题】来源=media://tenants/00000000-0000-4000-8000-000000000101/source_assets/source_1/result.json 目标=判断能不能做")
        self.assertEqual(parsed.value("来源"), "media://tenants/00000000-0000-4000-8000-000000000101/source_assets/source_1/result.json")
        self.assertEqual(parsed.artifact_refs, ("media://tenants/00000000-0000-4000-8000-000000000101/source_assets/source_1/result.json",))

        review = parse_media_growth_input("【复核】artifact_id=source_asset_1 通过")
        self.assertEqual(review.value("artifact_id"), "source_asset_1")
        self.assertEqual(review.artifact_refs, ("source_asset_1",))
        self.assertEqual(review.content_text, "通过")

    def test_source_asset_display_uses_semantic_param_not_raw_route_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = MediaVault(tenant_id="00000000-0000-4000-8000-000000000101", root=tmp)
            asset = capture_source_asset(
                "【素材】平台=抖音 账号=主账号 链接=https://www.douyin.com/video/765 备注=判断能不能做校园体育切入",
                vault=vault,
                run_id="clean_display_source",
            )
        payload = asset.to_dict()

        self.assertEqual(payload["display_title"], "判断能不能做校园体育切入")
        self.assertNotIn("平台=", payload["display_title"])
        self.assertNotIn("账号=", payload["display_title"])
        self.assertNotIn("https://", payload["display_title"])

    def test_decision_brief_consumes_input_artifact_trace_and_source_refs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = MediaVault(tenant_id="00000000-0000-4000-8000-000000000101", root=tmp)
            source = capture_source_asset("【素材】备注=校园体育素材 https://www.douyin.com/video/765", vault=vault, run_id="source_for_decision")
            def provider(parts, settings_arg, **kwargs):
                return self._decision_payload(source_ref=source.artifact_uri)
            plan, payload = run_media_growth_capability(
                "creation_decision_brief",
                f"【选题】source_asset_id={source.artifact_uri} 目标=判断是否做成下周选题",
                input_artifact_ids=(source.artifact_uri,),
                input_artifact_types=("SourceAsset",),
                vault=vault,
                growth_json_provider=provider,
                growth_json_settings=object(),
            )

        self.assertEqual(plan.workflow_mode, "continue_from_artifact")
        self.assertEqual(payload["runtime_status"], "artifact_created")
        trace = next(item for item in payload["source_trace"] if item["source_type"] == "input_artifacts")
        self.assertTrue(trace["loaded"])
        self.assertEqual(trace["artifacts"][0]["artifact_id"], "source_for_decision")
        self.assertIn(source.artifact_uri, payload["topic_candidates"][0]["source_refs"])

    def test_external_preset_reports_delegation_instead_of_planned_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = MediaVault(tenant_id="00000000-0000-4000-8000-000000000101", root=tmp)
            plan, payload = run_media_growth_capability("", "【润色】原文=需要更有网感", explicit_preset="quick_polish", vault=vault)

        self.assertEqual(plan.workflow_mode, "preset_flow")
        self.assertEqual(payload["runtime_status"], "external_delegation_required")
        self.assertEqual(payload["blocked_capability_id"], "style_polish_run")
        self.assertEqual(payload["planned_node_statuses"][0]["implementation_status"], "external")

    def test_preset_midway_exception_returns_structured_failure_with_partial_results(self) -> None:
        original_runner = growth_service.RUNNERS["creation_decision_brief"]

        def failing_runner(*args, **kwargs):
            raise RuntimeError("boom")

        with tempfile.TemporaryDirectory() as tmp:
            vault = MediaVault(tenant_id="00000000-0000-4000-8000-000000000101", root=tmp)
            growth_service.RUNNERS["creation_decision_brief"] = failing_runner
            try:
                plan, payload = run_media_growth_capability("", "【素材】一条素材", explicit_preset="asset_to_topic", vault=vault)
            finally:
                growth_service.RUNNERS["creation_decision_brief"] = original_runner

        self.assertEqual(plan.workflow_mode, "preset_flow")
        self.assertEqual(payload["runtime_status"], "execution_failed")
        self.assertEqual(payload["blocked_capability_id"], "creation_decision_brief")
        self.assertEqual([item["source_capability_id"] for item in payload["preset_node_results"]], ["source_asset_intake"])

    def test_dashboard_eligibility_rejects_route_param_only_display(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = MediaVault(tenant_id="00000000-0000-4000-8000-000000000101", root=tmp)
            asset = capture_source_asset("【素材】平台=抖音 账号=主账号", vault=vault, run_id="route_param_only")
        with self.assertRaises(ValueError):
            assert_dashboard_eligible(asset)

    def test_visibility_backfill_uses_vault_root_and_updates_sidecar_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = MediaVault(tenant_id="00000000-0000-4000-8000-000000000101", root=tmp)
            payload = {
                "artifact_id": "old_source",
                "artifact_type": "SourceAsset",
                "source_capability_id": "source_asset_intake",
                "status": "candidate",
                "visibility": "ops",
                "quality_status": "cleaned",
                "front_end_eligible": True,
                "display_title": "旧素材",
                "display_summary": "旧素材摘要",
            }
            path = vault.root / "source_assets" / "old_source"
            vault.write_json_artifact(
                path,
                "result.json",
                payload,
                owner_type="SourceAsset",
                owner_id="old_source",
                artifact_type="SourceAsset",
                artifact_id="old_source",
            )

            dry_run = backfill_module.backfill_vault_visibility(vault, apply=False)
            self.assertEqual(dry_run["matched_unreviewed_cleaned_candidates"], 1)
            self.assertEqual(json.loads((path / "result.json").read_text(encoding="utf-8"))["quality_status"], "cleaned")

            applied = backfill_module.backfill_vault_visibility(vault, apply=True)
            updated = json.loads((path / "result.json").read_text(encoding="utf-8"))
            manifest = json.loads((path / "result.json.manifest.json").read_text(encoding="utf-8"))
            result_bytes = (path / "result.json").read_bytes()

        self.assertEqual(applied["updated"], 1)
        self.assertEqual(updated["quality_status"], "pending_review")
        self.assertEqual(updated["schema_version"], "media_growth_artifact_v1")
        self.assertEqual(manifest["content_hash"], f"sha256:{hashlib.sha256(result_bytes).hexdigest()}")
        self.assertEqual(manifest["size_bytes"], len(result_bytes))

    def test_visibility_backfill_skips_reviewed_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = MediaVault(tenant_id="00000000-0000-4000-8000-000000000101", root=tmp)
            payload = {
                "artifact_id": "reviewed_source",
                "artifact_type": "SourceAsset",
                "source_capability_id": "source_asset_intake",
                "status": "candidate",
                "visibility": "ops",
                "quality_status": "cleaned",
                "front_end_eligible": True,
                "display_title": "已审素材",
                "display_summary": "已审素材摘要",
                "reviewed_at": "2026-07-04T00:00:00+00:00",
            }
            path = vault.root / "source_assets" / "reviewed_source"
            vault.write_json_artifact(
                path,
                "result.json",
                payload,
                owner_type="SourceAsset",
                owner_id="reviewed_source",
                artifact_type="SourceAsset",
                artifact_id="reviewed_source",
            )

            applied = backfill_module.backfill_vault_visibility(vault, apply=True)
            updated = json.loads((path / "result.json").read_text(encoding="utf-8"))

        self.assertEqual(applied["updated"], 0)
        self.assertEqual(updated["quality_status"], "cleaned")

    def test_display_backfill_strips_urls_and_updates_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = MediaVault(tenant_id="00000000-0000-4000-8000-000000000101", root=tmp)
            payload = {
                "artifact_id": "url_title_source",
                "artifact_type": "SourceAsset",
                "schema_version": "media_growth_artifact_v1",
                "source_capability_id": "source_asset_intake",
                "status": "candidate",
                "visibility": "ops",
                "quality_status": "pending_review",
                "front_end_eligible": True,
                "display_title": "https://xhslink.com/o/abc 值得拆的素材",
                "display_summary": "摘要 https://xhslink.com/o/abc 保留可读部分",
                "urls": ["https://xhslink.com/o/abc"],
            }
            path = vault.root / "source_assets" / "url_title_source"
            vault.write_json_artifact(
                path,
                "result.json",
                payload,
                owner_type="SourceAsset",
                owner_id="url_title_source",
                artifact_type="SourceAsset",
                artifact_id="url_title_source",
            )

            dry_run = display_backfill_module.backfill_vault_display(vault, apply=False, sync_growth_summary=False)
            self.assertEqual(dry_run["matched_display_url_artifacts"], 1)
            self.assertIn("https://", json.loads((path / "result.json").read_text(encoding="utf-8"))["display_title"])

            applied = display_backfill_module.backfill_vault_display(vault, apply=True, sync_growth_summary=False)
            updated = json.loads((path / "result.json").read_text(encoding="utf-8"))
            manifest = json.loads((path / "result.json.manifest.json").read_text(encoding="utf-8"))
            result_bytes = (path / "result.json").read_bytes()

        self.assertEqual(applied["updated"], 1)
        self.assertEqual(updated["display_title"], "值得拆的素材")
        self.assertEqual(updated["display_summary"], "摘要 保留可读部分")
        self.assertEqual(updated["urls"], ["https://xhslink.com/o/abc"])
        self.assertEqual(manifest["content_hash"], f"sha256:{hashlib.sha256(result_bytes).hexdigest()}")
        self.assertEqual(manifest["size_bytes"], len(result_bytes))

    def test_display_backfill_skips_non_growth_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = MediaVault(tenant_id="00000000-0000-4000-8000-000000000101", root=tmp)
            path = vault.root / "style_polish_runs" / "style_1"
            vault.write_json_artifact(
                path,
                "result.json",
                {"display_title": "https://example.com 非 Growth", "artifact_uri": "media://tenants/00000000-0000-4000-8000-000000000101/style_polish_runs/style_1/result.json"},
                owner_type="StylePolishResult",
                owner_id="style_1",
                artifact_type="StylePolishResult",
                artifact_id="style_1",
            )

            applied = display_backfill_module.backfill_vault_display(vault, apply=True, sync_growth_summary=False)
            updated = json.loads((path / "result.json").read_text(encoding="utf-8"))

        self.assertEqual(applied["matched_display_url_artifacts"], 0)
        self.assertIn("https://example.com", updated["display_title"])

    def test_growth_summary_maps_artifact_fields_without_semantic_inference(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = MediaVault(tenant_id="00000000-0000-4000-8000-000000000101", root=tmp)
            asset = capture_source_asset(
                "【素材】平台=抖音 备注=增长摘要同步素材",
                platform="抖音",
                account_id="account-1",
                track_id="track-1",
                vault=vault,
                run_id="summary_source",
            )
            with patch.dict(os.environ, {"OPENCLAW_MEDIA_GROWTH_REVIEWERS": "tester", "FEISHU_ALLOWED_USERS": ""}):
                reviewed = review_growth_artifact(asset.artifact_id, action="approve", reviewer_id="tester", vault=vault)

        record = artifact_to_growth_summary_record(reviewed["payload"])

        self.assertEqual(record["artifact_id"], "summary_source")
        self.assertEqual(record["artifact_type"], "SourceAsset")
        self.assertEqual(record["source_capability_id"], "source_asset_intake")
        self.assertEqual(record["display_title"], "增长摘要同步素材")
        self.assertEqual(record["platform"], "抖音")
        self.assertEqual(record["account_id"], "account-1")
        self.assertEqual(record["track_id"], "track-1")
        self.assertEqual(record["status"], "candidate")
        self.assertEqual(record["quality_status"], "cleaned")
        self.assertEqual(record["visibility"], "ops")
        self.assertTrue(record["front_end_eligible"])
        self.assertTrue(record["artifact_uri"].startswith("media://tenants/00000000-0000-4000-8000-000000000101/source_assets/summary_source/"))
        self.assertEqual(record["reviewed_by"], "tester")

    def test_growth_summary_sync_is_disabled_without_url(self) -> None:
        payload = {
            "artifact_id": "summary_disabled",
            "artifact_type": "SourceAsset",
            "source_capability_id": "source_asset_intake",
            "display_title": "summary",
            "display_summary": "summary",
            "status": "candidate",
            "quality_status": "cleaned",
            "visibility": "ops",
            "front_end_eligible": True,
            "artifact_uri": "media://tenants/00000000-0000-4000-8000-000000000101/source_assets/summary_disabled/result.json",
            "created_at": "2026-07-04T00:00:00+00:00",
            "updated_at": "2026-07-04T00:00:00+00:00",
        }
        with patch.dict(os.environ, {"MEDIA_OS_GROWTH_SUMMARY_URL": ""}):
            result = sync_growth_summary_artifact(payload, tenant_id="00000000-0000-4000-8000-000000000101")

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "disabled")
        self.assertIn("MEDIA_OS_GROWTH_SUMMARY_URL", result["reason"])

    def test_growth_summary_sync_uses_injected_client(self) -> None:
        calls: list[dict[str, object]] = []

        def fake_upsert(entity_name: str, table_url: str, payload: dict[str, object], *, key_field: str, contract: object, session_tenant_id: str) -> dict[str, object]:
            calls.append({"entity": entity_name, "table_url": table_url, "payload": payload, "key_field": key_field, "tenant_id": session_tenant_id})
            return {"mode": "fake_upsert", "record_id": "rec-summary"}

        payload = {
            "artifact_id": "summary_injected",
            "artifact_type": "SourceAsset",
            "source_capability_id": "source_asset_intake",
            "display_title": "summary",
            "display_summary": "summary",
            "status": "candidate",
            "quality_status": "cleaned",
            "visibility": "ops",
            "front_end_eligible": True,
            "artifact_uri": "media://tenants/00000000-0000-4000-8000-000000000101/source_assets/summary_injected/result.json",
            "created_at": "2026-07-04T00:00:00+00:00",
            "updated_at": "2026-07-04T00:00:00+00:00",
        }
        result = sync_growth_summary_artifact(payload, tenant_id="00000000-0000-4000-8000-000000000101", table_url="mock://growth-summary", client=fake_upsert)

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "synced")
        self.assertEqual(result["record_id"], "rec-summary")
        self.assertEqual(calls[0]["entity"], "GrowthSummary")
        self.assertEqual(calls[0]["key_field"], "artifact_id")
        self.assertEqual(calls[0]["tenant_id"], "00000000-0000-4000-8000-000000000101")

    def test_growth_artifact_creation_triggers_growth_summary_sync(self) -> None:
        calls: list[dict[str, object]] = []

        def fake_sync(payload, **_kwargs):
            calls.append(dict(payload))
            return {"ok": True, "status": "synced", "record_id": "rec_summary"}

        with tempfile.TemporaryDirectory() as tmp:
            vault = MediaVault(tenant_id="00000000-0000-4000-8000-000000000101", root=tmp)
            with patch.object(growth_service, "sync_growth_summary_artifact", side_effect=fake_sync):
                asset = capture_source_asset(
                    "【素材】备注=创建时同步摘要",
                    vault=vault,
                    run_id="summary_sync_on_create",
                )

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["artifact_id"], "summary_sync_on_create")
        self.assertEqual(calls[0]["artifact_uri"], asset.artifact_uri)

    def test_growth_summary_sync_result_is_persisted_and_returned(self) -> None:
        sync_result = {"ok": True, "status": "synced", "record_id": "rec_summary"}
        with tempfile.TemporaryDirectory() as tmp:
            vault = MediaVault(tenant_id="00000000-0000-4000-8000-000000000101", root=tmp)
            with patch.object(growth_service, "sync_growth_summary_artifact", return_value=sync_result):
                _plan, payload = run_media_growth_capability(
                    "source_asset_intake",
                    "【素材】备注=持久化同步结果",
                    vault=vault,
                )
            asset_uri = str(payload["artifact_uri"])
            persisted = vault.read_json_artifact(asset_uri)

        self.assertEqual(persisted["growth_summary_sync"], sync_result)
        self.assertEqual(payload["growth_summary_sync"], sync_result)

    def test_growth_summary_execution_failure_is_persisted_returned_and_logged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = MediaVault(tenant_id="00000000-0000-4000-8000-000000000101", root=tmp)
            with patch.object(
                growth_service,
                "sync_growth_summary_artifact",
                side_effect=RuntimeError("Feishu unavailable"),
            ):
                with self.assertLogs(growth_service.LOGGER, level="ERROR") as logs:
                    asset = capture_source_asset(
                        "【素材】备注=同步失败可见",
                        vault=vault,
                        run_id="summary_sync_failed",
                    )
            persisted = vault.read_json_artifact(asset.artifact_uri)

        self.assertEqual(persisted["growth_summary_sync"]["status"], "execution_failed")
        self.assertIn("Feishu unavailable", persisted["growth_summary_sync"]["reason"])
        self.assertIn("GrowthSummary 同步失败", persisted["display_summary"])
        self.assertTrue(any("GrowthSummary sync execution failed" in message for message in logs.output))

    def test_growth_artifact_review_returns_growth_summary_sync_result(self) -> None:
        calls: list[dict[str, object]] = []

        def fake_sync(payload, **_kwargs):
            calls.append(dict(payload))
            return {"ok": True, "status": "synced", "record_id": "rec_review_summary"}

        with tempfile.TemporaryDirectory() as tmp:
            vault = MediaVault(tenant_id="00000000-0000-4000-8000-000000000101", root=tmp)
            asset = capture_source_asset("【素材】备注=复核后同步摘要", vault=vault, run_id="summary_sync_on_review")
            with patch.dict(os.environ, {"OPENCLAW_MEDIA_GROWTH_REVIEWERS": "tester", "FEISHU_ALLOWED_USERS": ""}):
                with patch.object(growth_service, "sync_growth_summary_artifact", side_effect=fake_sync):
                    result = review_growth_artifact(asset.artifact_id, action="approve", reviewer_id="tester", vault=vault)

        self.assertTrue(result["ok"])
        self.assertEqual(result["growth_summary_sync"]["record_id"], "rec_review_summary")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["artifact_id"], "summary_sync_on_review")
        self.assertEqual(calls[0]["quality_status"], "cleaned")


if __name__ == "__main__":
    unittest.main()
