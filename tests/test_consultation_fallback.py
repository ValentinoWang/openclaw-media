from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from selfmedia.creation.consultation import format_consultation_reply, handle_creation_consultation_command


def test_format_consultation_reply_uses_concise_colleague_voice() -> None:
    reply = format_consultation_reply(
        {
            "conclusion": "这个选题值得做，但要从真实的会议卡住瞬间切入。",
            "topic_diagnosis": {"target_audience": "刚开始带团队的管理者"},
            "evidence": ["近期高互动内容都先给出了具体的失语场景。", "第二条证据不应展开。"],
            "recommendations": ["把表达训练拆成三条。"],
            "next_actions": ["先录下那段会议复盘，再剪成开头 15 秒。", "第二步不应展开。"],
            "data_gaps": ["账号最近三条视频的完播率。"],
        }
    )

    assert "这个选题值得做，但要从真实的会议卡住瞬间切入。" in reply
    assert "最该做的一步是先录下那段会议复盘，再剪成开头 15 秒。" in reply
    assert "主要依据是近期高互动内容都先给出了具体的失语场景。" in reply
    assert "账号最近三条视频的完播率。" not in reply
    assert "第二条证据不应展开。" not in reply
    assert "第二步不应展开。" not in reply
    for label in ("选题拆解：", "依据：", "建议：", "下一步：", "缺口：", "\n- "):
        assert label not in reply


def test_format_consultation_reply_uses_safe_defaults_when_structured_fields_are_unreadable() -> None:
    reply = format_consultation_reply(
        {
            "conclusion": "选题拆解：把会议复盘做成三段。",
            "next_actions": [{"action": "不应渲染成字典"}, "下一步：收集评论"],
            "evidence": ["依据：近期内容数据"],
            "data_gaps": ["缺口：账号完播率"],
        }
    )

    assert reply.startswith("现有信息还不足以给出可靠的创作判断。")
    assert "最该做的一步是先补充一个准备讲述的具体场景或素材。" in reply
    for label in ("选题拆解：", "依据：", "建议：", "下一步：", "缺口："):
        assert label not in reply


def test_consultation_hides_unreadable_model_reply_but_keeps_readable_reply() -> None:
    with (
        patch("selfmedia.creation.consultation.load_rows_for_creation", return_value=([], [])),
        patch("selfmedia.creation.consultation.load_business_rows_for_creation", return_value=[]),
        patch("selfmedia.creation.consultation.load_inspiration_rows_for_creation", return_value=[]),
        patch("selfmedia.creation.consultation.read_reference_docs", return_value=[]),
        patch("selfmedia.creation.consultation.build_media_context", return_value={}),
        patch(
            "selfmedia.creation.consultation.generate_consultation_answer",
            return_value={
                "reply": "选题拆解：\n依据：虚构的内部报告\n建议：继续拆解\n下一步：补素材\n缺口：数据",
                "conclusion": "先从一次真实的会议卡住瞬间切入。",
                "next_actions": ["先把那次会议的原话和动作记下来。"],
                "evidence": ["用户提供了会议卡住的场景。"],
            },
        ),
    ):
        result = handle_creation_consultation_command(
            "【创作咨询】平台=小红书 问题=这个选题怎么讲更有记忆点",
            tenant_id="00000000-0000-4000-8000-000000000101",
        )

    assert result["reply"].startswith("先从一次真实的会议卡住瞬间切入。")
    assert "最该做的一步是先把那次会议的原话和动作记下来。" in result["reply"]
    for label in ("选题拆解：", "依据：", "建议：", "下一步：", "缺口："):
        assert label not in result["reply"]

    with (
        patch("selfmedia.creation.consultation.load_rows_for_creation", return_value=([], [])),
        patch("selfmedia.creation.consultation.load_business_rows_for_creation", return_value=[]),
        patch("selfmedia.creation.consultation.load_inspiration_rows_for_creation", return_value=[]),
        patch("selfmedia.creation.consultation.read_reference_docs", return_value=[]),
        patch("selfmedia.creation.consultation.build_media_context", return_value={}),
        patch(
            "selfmedia.creation.consultation.generate_consultation_answer",
            return_value={"reply": "先收窄到一段可复述的真实经历，再写开头。"},
        ),
    ):
        readable_result = handle_creation_consultation_command(
            "【创作咨询】平台=小红书 问题=这个选题怎么讲更有记忆点",
            tenant_id="00000000-0000-4000-8000-000000000101",
        )

    assert readable_result["reply"] == "先收窄到一段可复述的真实经历，再写开头。"
