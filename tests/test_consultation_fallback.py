from __future__ import annotations

import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from common.llm_validation import LLMPostValidationError, validate_llm_payload
from selfmedia.creation.consultation import CONSULTATION_VALIDATION_CONTRACT, format_consultation_reply


def test_consultation_contract_requires_a_chat_ready_reply() -> None:
    payload = {
        "reply": "",
        "conclusion": "选题可做。",
        "next_actions": ["先写开头。"],
        "evidence": ["已有相关素材。"],
    }

    with pytest.raises(LLMPostValidationError, match=r"fields must not be empty: \['reply'\]"):
        validate_llm_payload(payload, CONSULTATION_VALIDATION_CONTRACT)


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
    assert "还需要补充账号最近三条视频的完播率。" in reply
    assert "第二条证据不应展开。" not in reply
    assert "第二步不应展开。" not in reply
    for label in ("选题拆解：", "依据：", "建议：", "下一步：", "缺口：", "\n- "):
        assert label not in reply
