import pytest

from selfmedia.deconstruct.viral_content.src import feishu_doc_writer, prompt
from selfmedia.deconstruct.viral_content.src.schemas import DeconstructResult, SchemaError, validate_schema


def _text(block: dict) -> str:
    return "".join(
        element.get("text_run", {}).get("content", "")
        for element in block.get("text", {}).get("elements", [])
    )


def test_fallback_renderer_does_not_expose_unknown_schema_keys() -> None:
    blocks = feishu_doc_writer._value_blocks({"summary": "摘要", "internal_debug": "secret"})
    rendered = "\n".join(_text(block) for block in blocks)
    assert "摘要：摘要" in rendered
    assert "internal_debug" not in rendered
    card_blocks = feishu_doc_writer._card_blocks(
        [{"shot_no": 1, "duration": "0-1s", "visual": "画面", "internal_debug": "secret"}]
    )
    assert "internal_debug" not in "\n".join(_text(block) for block in card_blocks)
    assert "internal_debug" not in feishu_doc_writer._summary_value({"internal_debug": "secret"})
    asr_blocks = feishu_doc_writer._deconstruct_evidence_blocks(
        {"speech_transcript": {"status": "provider_failed", "reason": "音轨不可用"}}
    )
    asr_text = "\n".join(_text(block) for block in asr_blocks)
    assert "status=" not in asr_text
    assert "音轨不可用" in asr_text


def test_index_uses_link_element_and_human_sort_wording() -> None:
    blocks = feishu_doc_writer._deconstruct_index_blocks(
        [{"title": "爆款拆解文档｜测试", "node_token": "node_123"}],
        {"爆款拆解文档｜测试": "rec_opaque_123"},
        "https://tcnwueberajc.feishu.cn/base/base_123",
    )
    rendered = "\n".join(_text(block) for block in blocks)
    assert "倒序" in rendered
    assert "倒叙" not in rendered
    assert "rec_opaque_123" not in rendered
    assert any(
        element.get("text_run", {}).get("text_element_style", {}).get("link", {}).get("url")
        == "https://tcnwueberajc.feishu.cn/wiki/node_123"
        for block in blocks
        for element in block.get("text", {}).get("elements", [])
    )


def test_deconstruct_prompt_allows_partial_evidence_storyboards() -> None:
    assert "证据覆盖不足时允许只输出已覆盖区间" in prompt.DECONSTRUCT_PROMPT
    assert "本次只产出候选，不负责晋升卡片" in prompt.DECONSTRUCT_PROMPT
    assert "不同 SourceAsset" not in prompt._human_insight_taxonomy_prompt()
    assert "至少" not in prompt._human_insight_taxonomy_prompt()


def test_deconstruct_prompt_and_schema_reject_retired_duplicate_fields() -> None:
    for field_name in ("target_audience_summary", "pain_pleasure_summary", "viral_breakdown"):
        assert field_name not in prompt.DECONSTRUCT_PROMPT
        with pytest.raises(SchemaError, match=field_name):
            validate_schema({field_name: "retired"}, DeconstructResult)
