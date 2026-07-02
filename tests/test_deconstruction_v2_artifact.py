from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DECONSTRUCT_ROOT = ROOT / "selfmedia" / "deconstruct" / "viral_content"
for path in (ROOT, DECONSTRUCT_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from selfmedia.deconstruct.viral_content.src.artifact_v2 import build_deconstruction_artifact, validate_deconstruction_artifact, validate_llm_deconstruction_v2_payload
from selfmedia.creation.deconstruction_artifact import DeconstructionArtifactUnavailable, attach_deconstruction_artifact_brief
from selfmedia.creation.field_contract import CanonicalMediaRecord
from media_vault.vault import MediaVault


def _result_payload() -> dict[str, object]:
    return {
        "schema_version": "deconstruction.v2",
        "content_summary": "用拉片做复刻 SOP",
        "source_summary": "讲解如何把视频拆成可复刻 SOP。",
        "viral_mechanism": "强需求开头 + 流程承诺 + 成本消疑。",
        "video_storyboard": [{"shot_no": 1, "duration": "0-3s", "visual": "封面大字", "subtitle": "", "voiceover": "", "evidence_asset_id": "frame_001"}],
        "image_post_script": [{"page_no": 1, "image_prompt": "封面", "evidence_asset_id": "frame_001"}],
        "avoid_plagiarism_notes": "不要照搬原句。",
        "production_checklist": ["替换为自己的素材"],
        "cover_opening_hook": "视频前2秒用封面大字承诺结果，适合知识类停留。",
        "core_data_summary": "平台数据不足，暂按机制强度和证据完整度判断。",
        "top_comment_insight": "评论证据不足，需要补抓 3 条高赞评论。",
        "target_audience": ["自媒体学习者", "内容运营"],
        "target_audience_summary": "想把爆款拆成 SOP 的内容创作者。",
        "pain_or_pleasure_points": ["省时间", "可复刻"],
        "pain_pleasure_summary": "用户爽点是把复杂拉片变成可执行清单。",
        "attention_elements": ["封面大字", "结果承诺", "流程感"],
        "viral_breakdown": "强需求开头、流程承诺和成本消疑共同降低学习门槛。",
        "viral_migration": "迁移到自有工具链演示，保留结果前置和步骤化结构。",
        "creative_upgrade_suggestion": "千万年薪编导会把它改成真实项目闯关式拆解，增加前后对比和失败代价。",
        "evidence_manifest": {
            "frame_001": {"type": "visual", "asset_id": "frame_001", "path": "/tmp/frame.jpg"},
            "sp_001": {"type": "speech", "segment_id": "sp_001", "text": "所有自媒体博主都关心拉片。"},
            "ocr_001": {"type": "ocr", "text_segment_id": "ocr_001", "asset_id": "frame_001", "text": "可复刻 SOP"},
        },
        "visual_hook": {
            "media_kind": "video",
            "primary_asset_ids": ["frame_001"],
            "feature_fields": ["video_opening_2s_frames"],
            "not_applicable_fields": ["image_cover_page_order"],
            "substitute_fields": {},
        },
        "engagement": {"status": "missing", "raw_stats": {}},
        "comments": {"status": "no_comments", "required_count": 3, "comments": []},
        "speech_transcript": {"status": "success", "full_text": "所有自媒体博主都关心拉片。"},
        "speech_timeline": [{"segment_id": "sp_001", "start": 0.0, "end": 2.0, "text": "所有自媒体博主都关心拉片。"}],
        "visible_text_segments": [{"text_segment_id": "ocr_001", "asset_id": "frame_001", "text": "可复刻 SOP"}],
        "reference_shots": [
            {
                "shot_id": "shot_001",
                "source_refs": ["frame_001"],
                "time_range": {"start_sec": 0.0, "end_sec": 3.0},
                "subject": {"summary": "屏幕录制主体"},
                "subject_motion": {"summary": "演示工具链"},
                "scene": {"summary": "教程画面"},
                "spatial_framing": {"summary": "中近景屏幕"},
                "camera": {"summary": "固定镜头"},
                "motion_type": "motion_clip",
                "production_route": "real_footage_or_video_generation",
                "reference_keep": ["流程承诺"],
                "reference_transform": ["替换成自己的工具链"],
                "reference_avoid": ["不要照搬原句"],
                "confidence": 0.8,
            }
        ],
        "reference_production_summary": {
            "motion_clip_count": 1,
            "animated_still_count": 0,
            "static_image_count": 0,
            "recommended_route": "real_footage_or_video_generation",
            "sample_required": True,
        },
        "viral_reuse_assessment": {
            "observed_virality": {"level": "unknown", "reason": "无平台数据"},
            "mechanism_strength": {"level": "strong", "reason": "目标人群和高价值动作前置", "evidence_ids": ["sp_001", "ocr_001"]},
            "account_fit": {"level": "high", "reason": "适合知识视频账号"},
            "production_feasibility": {"level": "easy", "reason": "可屏录复现"},
            "reuse_risk": {"level": "medium", "reason": "不能照搬原 skill 承诺"},
            "final_label": "strong_reuse_candidate",
            "confidence": 0.82,
            "human_review_required": True,
        },
        "pacing_profile": {
            "python_facts": {"duration_sec": 37.5},
            "llm_interpretation": {"edit_recommendations": ["前 3 秒保留结果数字"]},
        },
        "reuse_guardrails": {
            "allowed_reuse": [{"item": "结果前置结构", "evidence_ids": ["ocr_001"]}],
            "required_transformations": [{"source_part": "开头文案", "required_change": "重写为自己的语气"}],
            "prohibited_reuse": [{"element": "原视频原句", "reason": "表达复制风险"}],
            "own_account_mapping": {"own_persona": "当前账号"},
            "similarity_risk": {"overall": "medium"},
            "originality_requirements": ["必须加入自己的真实素材"],
            "human_review_required": True,
        },
        "human_readable_brief": {"recommended_script_directions": ["用自己的工具链复现"]},
        "validation": {"warnings": []},
    }


class DeconstructionV2ArtifactTests(unittest.TestCase):
    def test_builds_top_level_deconstruction_v2_artifact(self) -> None:
        artifact = build_deconstruction_artifact(
            result=_result_payload(),
            deconstruction_id="decon_test",
            source_asset_id="asset_test",
            source_asset_evidence_uri="media://source_assets/xhs/asset_test/evidence/evidence.json",
            source_text="原文",
        )
        self.assertEqual(artifact["schema_version"], "deconstruction.v2")
        self.assertEqual(artifact["deconstruction_id"], "decon_test")
        self.assertIn("reuse_guardrails", artifact)
        self.assertEqual(artifact["analysis_fields"]["creative_upgrade_suggestion"], "千万年薪编导会把它改成真实项目闯关式拆解，增加前后对比和失败代价。")
        validate_deconstruction_artifact(artifact)

    def test_rejects_old_wrapper_artifact(self) -> None:
        with self.assertRaises(Exception):
            validate_deconstruction_artifact({"deconstruction_id": "decon_test", "result": _result_payload()})

    def test_llm_payload_rejects_is_viral(self) -> None:
        payload = dict(_result_payload())
        payload["is_viral"] = True
        with self.assertRaises(Exception):
            validate_llm_deconstruction_v2_payload(payload, {"evidence_manifest": payload["evidence_manifest"]})

    def test_creation_reader_requires_deconstruction_v2_and_distills_brief(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            previous = os.environ.get("OPENCLAW_MEDIA_VAULT_ROOT")
            os.environ["OPENCLAW_MEDIA_VAULT_ROOT"] = str(Path(tmp) / "media_vault")
            try:
                vault = MediaVault()
                artifact = build_deconstruction_artifact(
                    result=_result_payload(),
                    deconstruction_id="decon_test",
                    source_asset_id="asset_test",
                    source_asset_evidence_uri="media://source_assets/xhs/asset_test/evidence/evidence.json",
                    source_text="原文",
                )
                written = vault.write_json_artifact(
                    vault.deconstruction_dir("decon_test"),
                    "deconstruction.json",
                    artifact,
                    owner_type="MaterialDeconstruction",
                    owner_id="decon_test",
                    artifact_type="material_deconstruction",
                )
                record = CanonicalMediaRecord(
                    source_table="02B_MaterialDeconstructions_素材拆解",
                    source_record_id="rec1",
                    record_type="素材拆解",
                    relation_id="decon_test",
                    detail_json={"evidence_uri": written["uri"]},
                    doc_links={"evidence": written["uri"]},
                )
                enriched = attach_deconstruction_artifact_brief(record)
                brief = enriched.detail_json["usable_material_brief"]
                self.assertEqual(brief["reuse_candidate_label"], "strong_reuse_candidate")
                self.assertIn("结果前置结构", " ".join(brief["usable_mechanisms"]))
                self.assertEqual(enriched.detail_json["reference_shots"][0]["shot_id"], "shot_001")
                self.assertEqual(brief["reference_shot_contract"][0]["production_route"], "real_footage_or_video_generation")
            finally:
                if previous is None:
                    os.environ.pop("OPENCLAW_MEDIA_VAULT_ROOT", None)
                else:
                    os.environ["OPENCLAW_MEDIA_VAULT_ROOT"] = previous

    def test_creation_reader_rejects_unsupported_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            previous = os.environ.get("OPENCLAW_MEDIA_VAULT_ROOT")
            os.environ["OPENCLAW_MEDIA_VAULT_ROOT"] = str(Path(tmp) / "media_vault")
            try:
                vault = MediaVault()
                written = vault.write_json_artifact(
                    vault.deconstruction_dir("decon_old"),
                    "deconstruction.json",
                    {"schema_version": "deconstruction.v1", "result": _result_payload()},
                    owner_type="MaterialDeconstruction",
                    owner_id="decon_old",
                    artifact_type="material_deconstruction",
                )
                record = CanonicalMediaRecord(
                    source_table="02B_MaterialDeconstructions_素材拆解",
                    source_record_id="rec1",
                    record_type="素材拆解",
                    relation_id="decon_old",
                    detail_json={"evidence_uri": written["uri"]},
                    doc_links={"evidence": written["uri"]},
                )
                with self.assertRaises(DeconstructionArtifactUnavailable):
                    attach_deconstruction_artifact_brief(record)
            finally:
                if previous is None:
                    os.environ.pop("OPENCLAW_MEDIA_VAULT_ROOT", None)
                else:
                    os.environ["OPENCLAW_MEDIA_VAULT_ROOT"] = previous


if __name__ == "__main__":
    unittest.main()
