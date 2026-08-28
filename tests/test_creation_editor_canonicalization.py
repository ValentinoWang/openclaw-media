from __future__ import annotations

from test_creation_v1 import _blocks_text, _multi_option_payload, _script_option

from selfmedia.creation.llm_generator import build_creation_prompt, validate_llm_draft_payload
from selfmedia.creation.request_parser import parse_creation_request
from selfmedia.creation.writer import _creation_doc_blocks


def _request():
    return parse_creation_request("【创作>抖音】类型=视频 赛道=体育 主体=西安田径分区邀请赛")


def _candidate_ids() -> dict[str, set[str]]:
    return {
        "selected_activity_ids": {"act1"},
        "selected_viral_ids": {"vir1"},
        "selected_inspiration_ids": {"ins1"},
        "selected_business_ids": set(),
    }


def _payload() -> dict[str, object]:
    return _multi_option_payload([_script_option(score=94), _script_option("opt_2", score=91)])


def _recommended(draft: dict[str, object]) -> dict[str, object]:
    return next(option for option in draft["script_options"] if option["option_id"] == "opt_1")  # type: ignore[index]


def test_editor_revision_is_promoted_to_canonical_option_and_rendered() -> None:
    payload = _payload()
    recommended = payload["script_options"][0]  # type: ignore[index]
    recommended.update(
        {
            "title": "总编二改标题",
            "final_copy": "总编二改后的成片文案。",
            "hook_3s": "先给总编二改后的起跑画面。",
            "voiceover": "把总编二改后的画面直接说出来。",
            "subtitles": ["总编二改后的字幕"],
        }
    )

    draft = validate_llm_draft_payload(payload, _request(), candidate_ids=_candidate_ids())
    recommended = _recommended(draft)

    assert recommended["title"] == "总编二改标题"
    assert recommended["final_copy"] == "总编二改后的成片文案。"
    blocks = _creation_doc_blocks("测试文档", _request(), [], [], [], [], draft, {"ok": True})
    rendered = _blocks_text(blocks)
    script_section = rendered.split("脚本方案", 1)[1].split("证据附录", 1)[0]
    recommended_section = script_section.split("方案 2", 1)[0]
    assert "方案 1（推荐）：总编二改标题" in recommended_section
    assert "总编二改后的成片文案。" in recommended_section


def test_canonical_option_does_not_require_llm_top_level_mirrors() -> None:
    payload = _payload()
    draft = validate_llm_draft_payload(payload, _request(), candidate_ids=_candidate_ids())

    assert _recommended(draft)["final_copy"] == "毕业不是离开跑道，是换一种身份继续起跑。"
    assert draft["final_copy"] == _recommended(draft)["final_copy"]


def test_legacy_complete_top_level_mirror_remains_compatible() -> None:
    payload = _payload()
    legacy_option = payload["script_options"][0]  # type: ignore[index]
    legacy_mirror = dict(legacy_option)
    legacy_mirror["title"] = "旧协议总编二改标题"
    legacy_mirror["final_copy"] = "旧协议总编二改后的成片文案。"
    for key in (
        "title",
        "tags",
        "final_copy",
        "selected_activity_ids",
        "selected_viral_ids",
        "selected_inspiration_ids",
        "selected_business_ids",
        "image_script",
        "carousel",
        "hook_3s",
        "storyboard",
        "voiceover",
        "subtitles",
        "production_checklist",
        "review_plan",
        "risks_or_missing_info",
    ):
        payload[key] = legacy_mirror[key]

    draft = validate_llm_draft_payload(payload, _request(), candidate_ids=_candidate_ids())
    assert _recommended(draft)["title"] == "旧协议总编二改标题"
    assert draft["title"] == "旧协议总编二改标题"


def test_partial_top_level_mirror_cannot_overwrite_canonical_option() -> None:
    payload = _payload()
    payload["title"] = "未写回推荐方案的旧标题"

    try:
        validate_llm_draft_payload(payload, _request(), candidate_ids=_candidate_ids())
    except ValueError as exc:
        assert "顶层 title 必须等于 recommended_option_id 指向的 script_options 项" in str(exc)
    else:
        raise AssertionError("部分顶层镜像不能覆盖推荐方案")


def test_prompt_declares_option_as_editor_revision_target() -> None:
    prompt = build_creation_prompt(
        _request(),
        activity_candidates=[],
        viral_candidates=[],
        inspiration_candidates=[],
        business_candidates=[],
        reference_docs=[],
        media_context={},
    )

    assert "必须把所有可执行修订直接写回 recommended_option_id 指向的 script_options 项" in prompt
    assert "顶层 title/final_copy/hook_3s/storyboard/image_script/carousel/creator_report 必须镜像" not in prompt
