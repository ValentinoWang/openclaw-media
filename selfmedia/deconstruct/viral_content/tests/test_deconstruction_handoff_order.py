from __future__ import annotations

import json

from selfmedia.deconstruct.viral_content.src.feishu_doc_writer import _deconstruct_doc_blocks


def test_deconstruction_document_places_creator_handoff_before_explanatory_analysis() -> None:
    blocks = _deconstruct_doc_blocks(
        {
            "content_summary": "示例新品演示视频以一个明确问题开场。",
            "source_summary": "这是测试团队自制的咖啡新品演示素材。",
            "human_readable_brief": {
                "source_summary": "先展示成品，再给出一个可回答的问题。",
                "why_it_may_work": "先给结果能让观众立即理解观看收益。",
                "account_fit_reason": "适合本地生活账号的真实门店素材。",
                "usable_patterns": ["成品先出现，再提出单一问题"],
                "recommended_script_directions": ["用自家门店和原创提问重拍首三秒"],
                "must_transform": ["更换人物、场景和口播文案"],
                "must_not_copy": ["不复用参考素材的镜头组合或原句"],
                "human_review_flags": ["human_review_required"],
            },
            "viral_mechanism": "明确结果配合悬念问题，引导观众继续观看。",
            "viral_reuse_assessment": {
                "final_label": "weak_reuse_candidate",
                "confidence": 0.72,
                "observed_virality": {"level": "unknown", "reason": "测试素材没有公开热度数据"},
                "mechanism_strength": {"level": "medium", "reason": "首屏结果明确"},
                "account_fit": {"level": "medium", "reason": "可由门店自行拍摄"},
                "production_feasibility": {"level": "high", "reason": "只需手机和店内环境"},
                "reuse_risk": {"level": "low", "reason": "仅迁移结构"},
                "human_review_required": True,
            },
            "pacing_profile": {
                "llm_interpretation": {
                    "summary": "首三秒展示成品，随后提出原创问题。",
                    "rhythm_pattern": "成品、问题、制作过程。",
                    "edit_recommendations": ["在问题后保留短暂停顿"],
                    "reuse_notes": "用自己的制作过程承接问题。",
                }
            },
            "reuse_guardrails": {
                "allowed_reuse": ["先给结果再提问的结构"],
                "required_transformations": ["使用原创制作过程和文案"],
                "prohibited_reuse": ["参考素材的原始口播"],
                "similarity_risk": {"overall": "low"},
                "originality_requirements": ["自行拍摄门店画面"],
                "human_review_required": True,
            },
        },
        include_evidence_appendix=False,
    )

    rendered = json.dumps(blocks, ensure_ascii=False)
    handoff_index = rendered.index("创作交接提示")
    execution_direction_index = rendered.index("用自家门店和原创提问重拍首三秒")

    for analysis_heading in ("爆点机制", "爆款复用价值摘要", "节奏复用摘要", "复用护栏"):
        analysis_index = rendered.index(analysis_heading)
        assert handoff_index < analysis_index
        assert execution_direction_index < analysis_index
