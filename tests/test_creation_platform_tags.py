from __future__ import annotations

from selfmedia.creation.platform_validator import validate_platform_draft


def test_platform_tag_minima_allow_only_strong_relevant_tags() -> None:
    xhs = validate_platform_draft(
        "小红书",
        "图文",
        {"title": "跑步热身", "tags": ["跑步", "热身", "训练"], "image_script": ["热身动作"]},
    )
    douyin = validate_platform_draft(
        "抖音",
        "视频",
        {
            "title": "跑步热身",
            "tags": ["跑步", "热身"],
            "hook_3s": "先别急着加速",
            "storyboard": ["热身动作"],
            "voiceover": "先热身，再加速。",
            "subtitles": ["先热身，再加速。"],
        },
    )

    assert xhs.ok
    assert douyin.ok


def test_platform_tag_minima_still_reject_insufficient_tags() -> None:
    xhs = validate_platform_draft("小红书", "图文", {"title": "跑步热身", "tags": ["跑步", "热身"], "image_script": ["热身动作"]})
    douyin = validate_platform_draft("抖音", "视频", {"title": "跑步热身", "tags": ["跑步"], "hook_3s": "先别急着加速", "storyboard": ["热身动作"]})

    assert not xhs.ok
    assert not douyin.ok


def test_xhs_image_post_accepts_carousel_without_duplicate_image_script() -> None:
    result = validate_platform_draft(
        "小红书",
        "图文",
        {"title": "跑步热身", "tags": ["跑步", "热身", "训练"], "carousel": ["封面", "动作拆解"]},
    )

    assert result.ok
