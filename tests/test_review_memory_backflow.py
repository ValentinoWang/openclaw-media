from __future__ import annotations

from selfmedia.context import build_media_context, record_review_memory
from selfmedia.review.data_review import DataReviewRequest, _review_memory_text, validate_data_review_analysis


TENANT_ID = "00000000-0000-4000-8000-000000000106"
OTHER_TENANT_ID = "00000000-0000-4000-8000-000000000206"


def test_data_review_evidence_backflows_to_next_creation_context_without_tenant_leakage(tmp_path) -> None:
    request = DataReviewRequest(platform="抖音", account="跑步小王", track="跑步训练", topic="配速焦虑")
    analysis = validate_data_review_analysis(
        {
            "conclusion": "前两秒先给出配速失控画面，才能降低早期流失。",
            "performance_level": "值得重剪",
            "media_format": "video",
            "media_format_evidence": "截图展示了播放曲线和完播率。",
            "metrics": {"播放量": 12000},
            "format_specific_metrics": {"2秒跳出率": "63%", "完播率": "28%"},
            "atomic_facts": [
                {
                    "fact": "前两秒跳出率为63%",
                    "metric": "2秒跳出率",
                    "value": "63%",
                    "evidence": "截图中前两秒曲线陡降",
                    "implication": "开头没有兑现配速焦虑的冲突",
                }
            ],
            "priority_metrics": [
                {
                    "metric": "2秒跳出率",
                    "value": "63%",
                    "signal": "偏高",
                    "why_it_matters": "首屏承诺没有留住目标跑者",
                    "content_action": "开头先放配速失控的瞬间",
                },
                {
                    "metric": "完播率",
                    "value": "28%",
                    "signal": "偏低",
                    "content_action": "删去中段重复讲解",
                },
            ],
            "key_insights": ["目标跑者会为真实失控画面停留", "中段讲解重复导致完播流失"],
            "content_guidance": ["首屏用失控画面和配速数字建立冲突"],
            "publishing_guidance": ["重剪后在晚间跑步时段复测"],
            "next_actions": ["重剪前两秒后复测跳出率", "删除重复讲解再观察完播率"],
            "problems": ["首屏承诺不足"],
            "data_quality_notes": ["截图可读"],
        }
    )

    result = record_review_memory(
        _review_memory_text(request, analysis),
        tenant_id=TENANT_ID,
        source="data-review",
        analysis=analysis,
        root=tmp_path,
    )

    persisted = result["review"]
    assert persisted["atomic_facts"] == analysis["atomic_facts"]
    assert persisted["priority_metrics"] == analysis["priority_metrics"]
    assert persisted["key_insights"] == analysis["key_insights"]
    assert persisted["performance_level"] == analysis["performance_level"]
    assert persisted["next_actions"] == analysis["next_actions"]

    context = build_media_context(
        platform=request.platform,
        account=request.account,
        track=request.track,
        topic=request.topic,
        tenant_id=TENANT_ID,
        root=tmp_path,
    )
    projected = context["recent_reviews"][0]
    assert projected["atomic_facts"] == analysis["atomic_facts"]
    assert projected["priority_metrics"] == analysis["priority_metrics"]
    assert projected["key_insights"] == analysis["key_insights"]
    assert projected["next_actions"] == analysis["next_actions"]
    assert projected["performance_level"] == analysis["performance_level"]
    assert "截图中前两秒曲线陡降" in context["prompt"]
    assert "表现评级：值得重剪" in context["prompt"]
    assert "2秒跳出率=63%（偏高）" in context["prompt"]
    assert "指标意义：首屏承诺没有留住目标跑者" in context["prompt"]
    assert "指标内容动作：开头先放配速失控的瞬间；删去中段重复讲解" in context["prompt"]
    assert "下一步：开头先放配速失控的瞬间；删去中段重复讲解；重剪前两秒后复测跳出率" in context["prompt"]
    assert context["prompt"].index("相关历史复盘") < context["prompt"].index("账号定位：")

    other_tenant_context = build_media_context(
        platform=request.platform,
        account=request.account,
        track=request.track,
        topic=request.topic,
        tenant_id=OTHER_TENANT_ID,
        root=tmp_path,
    )
    assert other_tenant_context["recent_reviews"] == []
    assert "截图中前两秒曲线陡降" not in other_tenant_context["prompt"]
