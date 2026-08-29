from __future__ import annotations

import json
from types import SimpleNamespace

from selfmedia.creation import shooting_execution
from selfmedia.creation.writer import _shooting_execution_doc_blocks


# The retired ``creation-inspiration`` entrypoint used to own this contract.
# Keep its protection on the current execution entrypoint instead of retaining
# a test that imports code removed with that entrypoint.
def _valid_execution_plan() -> dict[str, object]:
    return {
        "shooting_goal": {"platform": "抖音", "content_type": "视频", "mainline": "先给出结果，再解释路线。"},
        "route_map": [{"time_slot": "15:00-15:20", "location": "校园入口", "shooting_task": "拍开场群像", "people": "同学", "backup": "改拍手部特写"}],
        "must_shot_list": [{"priority": "P0", "location": "校园入口", "people": "同学", "action": "整理学位帽", "shot_size": "中景", "reference": "已确认拍摄计划", "usage": "开场", "reshoot_check": "人物和字幕清晰"}],
        "branch_plans": [{"condition": "下雨", "plan": "改在连廊拍群像", "priority": "P1"}],
        "storyboard": [{"time": "0-3 秒", "visual": "同学整理学位帽后看向镜头", "caption_or_voice": "三小时，拍完一次毕业告别。", "sound_or_note": "保留现场环境声"}],
        "onsite_checklist": ["拍完开场立即回看人物和收声"],
        "publishing_pack": {
            "title_directions": ["三小时拍完课题组毕业照"],
            "cover_frame": "全体同学和校园地标同框",
            "body_copy": "先拍最重要的群像，再完成路线。",
            "hashtags": ["毕业季"],
            "bgm_suggestion": "轻快现场音乐",
            "comment_prompt": "你毕业时最想留下哪个镜头？",
            "first_hour_action": "发布后置顶提问，并回复前十条有效评论。",
        },
        "evidence_appendix": [{"source": "已确认拍摄计划", "source_status": "confirmed", "available_evidence": "用户提供了时间和路线", "usage_reason": "只据此安排镜头", "risk": "天气变化时按分支方案执行"}],
    }


def _request() -> SimpleNamespace:
    return SimpleNamespace(
        topic="课题组毕业照",
        time_window="15:00-18:00",
        publish_time="",
        platform="抖音",
        content_type="视频",
        shooting_goal="完成可发布的毕业群像视频",
    )


def test_creator_execution_requires_a_non_empty_storyboard() -> None:
    draft = _valid_execution_plan()

    assert shooting_execution.validate_shooting_execution_plan(draft)["ok"] is True

    draft["storyboard"] = []
    rejected = shooting_execution.validate_shooting_execution_plan(draft)
    assert rejected["ok"] is False
    assert rejected["status"] == "pending_manual"
    assert rejected["empty_lists"] == ["storyboard"]


def test_creator_execution_document_places_storyboard_before_evidence() -> None:
    draft = _valid_execution_plan()
    validation = shooting_execution.validate_shooting_execution_plan(draft)

    blocks = _shooting_execution_doc_blocks("拍摄执行", _request(), draft, validation)
    rendered = json.dumps(blocks, ensure_ascii=False)

    assert validation["ok"] is True
    assert blocks[1]["heading2"]["elements"][0]["text_run"]["content"] == "分镜脚本"
    assert blocks[2]["rows"][0] == ["时间", "画面", "字幕/口播", "声音/拍摄注意"]
    assert "三小时，拍完一次毕业告别。" in rendered
    assert rendered.index("分镜脚本") < rendered.index("证据附录")
