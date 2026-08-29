from __future__ import annotations

from unittest.mock import patch

from selfmedia.creation.consultation import format_consultation_reply, handle_creation_consultation_command


def test_empty_reply_fallback_is_a_single_chat_paragraph() -> None:
    reply = format_consultation_reply(
        {
            "reply": "",
            "conclusion": "这个方向可以继续，但要先收窄到一个真实场景。",
            "next_actions": ["先记下场景里的原话和动作。"],
            "evidence": ["近期同类内容都从具体冲突切入。"],
        }
    )

    assert reply == (
        "这个方向可以继续，但要先收窄到一个真实场景。 "
        "最该做的一步是先记下场景里的原话和动作。 "
        "主要依据是近期同类内容都从具体冲突切入。"
    )
    assert "\n" not in reply
    for label in ("选题拆解：", "依据：", "建议：", "下一步：", "缺口："):
        assert label not in reply


def test_empty_model_reply_uses_chat_paragraph_fallback() -> None:
    with (
        patch("selfmedia.creation.consultation.load_rows_for_creation", return_value=([], [])),
        patch("selfmedia.creation.consultation.load_business_rows_for_creation", return_value=[]),
        patch("selfmedia.creation.consultation.load_inspiration_rows_for_creation", return_value=[]),
        patch("selfmedia.creation.consultation.read_reference_docs", return_value=[]),
        patch("selfmedia.creation.consultation.build_media_context", return_value={}),
        patch(
            "selfmedia.creation.consultation.generate_consultation_answer",
            return_value={
                "reply": "",
                "conclusion": "现有信息还不足以给出可靠的创作判断。",
                "next_actions": ["先补充一个准备讲述的具体场景或素材。"],
            },
        ),
    ):
        result = handle_creation_consultation_command(
            "【创作咨询】平台=小红书 问题=这个选题怎么讲更有记忆点",
            tenant_id="00000000-0000-4000-8000-000000000101",
        )

    assert result["reply"] == (
        "现有信息还不足以给出可靠的创作判断。 "
        "最该做的一步是先补充一个准备讲述的具体场景或素材。"
    )
    assert "\n" not in result["reply"]
