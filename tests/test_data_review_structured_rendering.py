import selfmedia.review.data_review as data_review
from selfmedia.review.data_review import (
    DataReviewRequest,
    _review_memory_text,
    data_review_doc_blocks,
    render_data_review_report,
    validate_data_review_analysis,
)


def _analysis_with_guidance(guidance):
    return {
        "conclusion": "前两秒钩子需要重剪后再观察。",
        "media_format": "video",
        "media_format_evidence": "截图展示完播率和播放时长。",
        "metrics": {"播放量": 1200},
        "format_specific_metrics": {"完播率": "32%"},
        "atomic_facts": [{"fact": "完播率为32%"}],
        "priority_metrics": [{"metric": "完播率", "value": "32%"}],
        "content_guidance": guidance,
        "publishing_guidance": guidance,
        "next_actions": guidance,
        "problems": guidance,
        "data_quality_notes": guidance,
    }


def _block_texts(blocks):
    return [
        element["text_run"]["content"]
        for block in blocks
        for element in (block.get("text") or {}).get("elements") or []
    ]


def test_structured_guidance_renders_chinese_labels_without_dict_repr():
    guidance = [{"维度": "前两秒钩子", "建议": "先给出跑步姿势错误的结果"}]
    analysis = validate_data_review_analysis(_analysis_with_guidance(guidance))
    expected = "维度：前两秒钩子；建议：先给出跑步姿势错误的结果"

    assert analysis["content_guidance"] == [expected]
    blocks = data_review_doc_blocks(
        "数据复盘",
        DataReviewRequest(platform="抖音", account="小王"),
        analysis,
        [],
        "2026-08-28T10:00:00+08:00",
        "https://example.com/guide",
    )
    block_text = "\n".join(_block_texts(blocks))
    report = render_data_review_report({"analysis": analysis})
    memory_text = _review_memory_text(DataReviewRequest(platform="抖音", account="小王"), analysis)

    for rendered in (block_text, report, memory_text):
        assert expected in rendered
        assert "{'维度'" not in rendered


def test_plain_string_guidance_remains_unchanged():
    guidance = ["前两秒先给出跑步姿势错误的结果"]
    analysis = validate_data_review_analysis(_analysis_with_guidance(guidance))

    assert analysis["content_guidance"] == guidance
    assert analysis["publishing_guidance"] == guidance
    assert analysis["next_actions"] == guidance


def test_performance_level_is_canonicalized_for_published_post():
    analysis = _analysis_with_guidance(["先缩短开头"])
    analysis["performance_level"] = "建议重剪"

    validated = validate_data_review_analysis(analysis)

    assert validated["performance_level"] == "值得重剪"


def test_unknown_performance_level_is_explicitly_unrated():
    analysis = _analysis_with_guidance(["先缩短开头"])
    analysis["performance_level"] = "模型自定义评级"

    validated = validate_data_review_analysis(analysis)

    assert validated["performance_level"] == "未评级"


def test_retired_bitable_field_writer_surface_is_removed():
    retired_names = (
        "ensure_data_review_fields",
        "_data_review_field_items",
        "complete_data_review_fields",
        "build_metric_evidence_json",
        "build_action_guidance_json",
    )

    for name in retired_names:
        assert not hasattr(data_review, name)


def test_review_reply_leads_with_result_and_document_without_internal_metadata():
    reply = data_review.format_data_review_reply(
        {
            "ok": True,
            "doc_link": "https://example.test/review/doc-1",
            "record_id": "post_internal_1",
            "reviewed_at": "2026-08-29T10:00:00+08:00",
            "analysis": {"platform": "抖音", "account": "小王", "conclusion": "先重剪开头", "performance_level": "值得重剪"},
            "creation_plan": {"status": "loaded", "creation_record_id": "run_internal_1"},
        }
    )

    lines = reply.splitlines()
    assert lines[:3] == [
        "【数据复盘】已完成",
        "结论：先重剪开头",
        "复盘文档：https://example.test/review/doc-1",
    ]
    assert "post_internal_1" not in reply
    assert "run_internal_1" not in reply
    assert "2026-08-29T10:00:00+08:00" not in reply
