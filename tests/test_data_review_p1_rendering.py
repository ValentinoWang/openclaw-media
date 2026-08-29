import json

from selfmedia.review.data_review import DataReviewRequest, data_review_doc_blocks, render_data_review_report


def _block_text(blocks):
    texts = []
    for block in blocks:
        text_block = block.get("text") or next(
            (block.get(key) for key in block if key.startswith("heading")), {}
        )
        texts.extend(element["text_run"]["content"] for element in text_block.get("elements") or [])
    return "\n".join(texts)


def _analysis_with_stringified_evidence():
    return {
        "conclusion": "先重做封面，再观察两小时。",
        "performance_level": "值得重剪",
        "media_format": "video",
        "media_format_evidence": "截图显示播放曲线。",
        "metrics": {"views": 1200, "saves": 18},
        "format_specific_metrics": {"completion_rate": "31%"},
        "atomic_facts": [
            '{"fact":"收藏偏低","metric":"saves","value":18,"confidence":"高"}'
        ],
        "priority_metrics": [
            {"metric": "completion_rate", "value": "31%", "signal": "中等"}
        ],
        "trend_curves": '{"views":{"peak":"首小时","trend":"回落"}}',
        "metric_interpretation": ["开头有效，后段流失"],
        "problems": ["封面承诺不足"],
        "content_guidance": ["封面先写结果"],
        "publishing_guidance": ["下次晚八点发布"],
        "next_actions": ["重做封面后观察两小时"],
        "data_quality_notes": ["截图可读"],
    }


def test_review_rendering_humanizes_nested_json_and_puts_appendix_last():
    analysis = _analysis_with_stringified_evidence()
    report = render_data_review_report({"reviewed_at": "2026-08-29", "analysis": analysis})
    document = _block_text(
        data_review_doc_blocks(
            "数据复盘",
            DataReviewRequest(platform="抖音", account="小王"),
            analysis,
            [],
            "2026-08-29",
            "",
        )
    )
    blocks = data_review_doc_blocks(
        "数据复盘",
        DataReviewRequest(platform="抖音", account="小王"),
        analysis,
        [],
        "2026-08-29",
        "",
    )
    document = _block_text(blocks)

    for rendered in (report, document):
        assert "收藏偏低" in rendered
        assert "指标：收藏" in rendered
        assert "完播率" in rendered
        assert "峰值：首小时" in rendered
        assert "{\"fact\"" not in rendered
        assert "\"completion_rate\"" not in rendered
        if rendered is report:
            assert "证据附录" in rendered
            assert rendered.index("证据附录") > rendered.index("下一步动作")
        else:
            assert "原始分析结构保留在复盘 JSON 产物中" in rendered

    assert report.index("## 下一步动作") < report.index("## 关键数据")
    assert json.dumps(analysis, ensure_ascii=False) not in report


def test_review_renderer_keeps_internal_fields_out_of_nested_stringified_json():
    analysis = _analysis_with_stringified_evidence()
    analysis["trend_curves"] = (
        '{"views":{"peak":"首小时","source_record_id":"private-1",'
        '"screenshot_path":"/private/review.png"}}'
    )

    report = render_data_review_report({"analysis": analysis})

    assert "private-1" not in report
    assert "/private/review.png" not in report
    assert "峰值：首小时" in report


def test_review_renderer_humanizes_object_arrays_in_guidance_fields():
    analysis = _analysis_with_stringified_evidence()
    analysis.update(
        {
            "problems": [{"维度": "选题", "问题": "承诺不够具体"}],
            "content_guidance": [{"维度": "封面", "建议": "先展示结果"}],
            "publishing_guidance": [{"渠道": "抖音", "建议": "晚八点发布"}],
            "next_actions": [{"动作": "重做封面", "期限": "今天"}],
            "data_quality_notes": [{"来源": "截图", "说明": "字段可读"}],
        }
    )

    report = render_data_review_report({"reviewed_at": "2026-08-29", "analysis": analysis})

    assert "维度：封面；建议：先展示结果" in report
    assert "渠道：抖音；建议：晚八点发布" in report
    assert "动作：重做封面；期限：今天" in report
    assert "{'维度':" not in report
    assert "{'动作':" not in report
