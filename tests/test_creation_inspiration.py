from __future__ import annotations

from selfmedia.creation.inspiration import CreationInspirationResult, format_inspiration_text


def _valid_inspiration_payload() -> dict[str, object]:
    return {
        "title": "毕业照路线",
        "theme": "课题组毕业照",
        "track": "校园生活",
        "platform": "小红书",
        "content_type": "视频",
        "cleaned_inspiration": "三小时内拍完导师和同学的毕业照，并形成可发布内容。",
        "material_summary": "导师、约 15 位工科硕士毕业生、清华 SIGS 校园地标。",
        "source_kind": "生活场景",
        "signal_type": "成果",
        "emotion_trigger": "毕业告别",
        "trigger_sentence": "6月25日下午3点到6点帮课题组拍毕业照",
        "event_scene": "清华大学深圳国际研究生院校园",
        "misalignment": "工科硕士理性日常和毕业告别情绪之间的反差",
        "core_viewpoint": "最后一次并肩出现，要拍出关系和告别。",
        "reader_problem": "不知道三小时毕业照怎么安排路线和镜头。",
        "material_stage": "已生成选题",
        "recreation_direction": "做成毕业季路线图和 60 秒群像视频。",
        "content_angles": ["导师见证", "三小时路线"],
        "reuse_angles": ["图文路线", "短视频花絮"],
        "derivative_topics": ["毕业照打卡路线", "课题组最后一次合影"],
        "publishable_formats": ["图文", "短视频"],
        "hook_options": ["三小时拍完课题组毕业照，先别急着找机位。"],
        "title_options": ["清华SIGS毕业照路线"],
        "script_outline": ["先保大合影", "再拍小组照", "最后拍抛帽收尾"],
        "execution_brief": "先拍正式合影，再拍书吧和台阶小组照，最后用开阔地收尾。",
        "route_map": ["信息大楼", "清芬楼", "银茶书吧", "书吧阶梯", "太阳树", "南国校园全景位"],
        "shooting_schedule": ["15:00-15:20 正式大合影", "16:00-16:40 书吧小组合照", "17:20-18:00 抛帽和收尾"],
        "shot_checklist": ["导师全体合影", "全体走来", "小组拍立得", "抛帽收尾"],
        "storyboard": [
            {
                "time": "0-3s",
                "visual": "信息大楼前，全体同学整理学位帽后看镜头。",
                "subtitle": "三小时，拍完一次课题组毕业告别。",
                "sound": "现场环境声起。",
                "shooting_note": "先拍全体，避免人到后面散掉。",
            },
            {
                "time": "3-10s",
                "visual": "导师站中间，同学分三排，拍正式合影。",
                "subtitle": "先把最稳的大合影拿下。",
                "sound": "快门声。",
                "shooting_note": "用建筑阴影避开硬光。",
            },
        ],
        "publishing_plan": ["标题突出三小时路线", "封面用全体合影加路线字"],
        "score": 88,
        "score_reason": "场景明确，人数和时间明确，适合图文和视频。",
        "strengths": ["人物关系明确", "场景可拍"],
        "risks": ["天气和硬光可能影响出片"],
        "next_actions": ["确认导师到场时间", "提前踩点"],
        "tags": ["毕业季", "清华SIGS"],
    }


def test_creation_inspiration_requires_creator_execution_storyboard_fields() -> None:
    payload = _valid_inspiration_payload()

    result = CreationInspirationResult.parse_obj(payload).dict()

    assert result["execution_brief"]
    assert result["route_map"]
    assert result["shooting_schedule"]
    assert result["shot_checklist"]
    assert result["storyboard"]
    assert result["publishing_plan"]


def test_creation_inspiration_report_puts_storyboard_before_evidence() -> None:
    payload = _valid_inspiration_payload()
    result = CreationInspirationResult.parse_obj(payload).dict()

    text = format_inspiration_text("【创作-灵感】6月25日下午3点到6点拍毕业照", result)

    assert "## 创作者执行稿" in text
    assert "## 打卡路线图" in text
    assert "## 分镜脚本" in text
    assert "| 时间 | 画面 | 字幕/口播 | 声音/拍摄注意 |" in text
    assert "三小时，拍完一次课题组毕业告别。" in text
    assert text.index("## 分镜脚本") < text.index("## 证据与边界")
