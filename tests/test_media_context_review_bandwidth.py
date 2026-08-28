from __future__ import annotations

import os
from unittest.mock import patch

from selfmedia.context.media_context import (
    CONTEXT_PROMPT_MAX_CHARS_ENV,
    DEFAULT_CONTEXT_PROMPT_MAX_CHARS,
    MAX_CONTEXT_PROMPT_MAX_CHARS,
    render_context_for_prompt,
)


def _review() -> dict[str, object]:
    return {
        "created_at": "2026-08-28T10:30:00+08:00",
        "topic": "表达力训练",
        "lesson": "首屏先明确被追问的冲突，才能降低早期流失。",
        "performance_level": "值得重剪",
        "priority_metrics": [
            {
                "metric": "2秒跳出率",
                "value": "63%",
                "signal": "偏高",
                "content_action": "开头先给被追问的瞬间",
            },
            {
                "metric": "完播率",
                "value": "28%",
                "signal": "偏低",
            },
        ],
        "next_actions": ["重剪前两秒并复测跳出率"],
    }


def test_default_budget_keeps_structured_review_before_profile_markdown() -> None:
    prompt = render_context_for_prompt(
        {
            "recent_reviews": [_review()],
            "account_profile": {"markdown": "账号档案原文" * 800},
            "recent_creations": [{"created_at": "2026-08-27", "topic": "历史创作", "title": "标题"}],
        }
    )

    assert DEFAULT_CONTEXT_PROMPT_MAX_CHARS == 10_000
    assert len(prompt) <= DEFAULT_CONTEXT_PROMPT_MAX_CHARS
    assert "结论：首屏先明确被追问的冲突" in prompt
    assert "表现评级：值得重剪" in prompt
    assert "关键指标：2秒跳出率=63%（偏高）；完播率=28%（偏低）" in prompt
    assert "下一步：开头先给被追问的瞬间；重剪前两秒并复测跳出率" in prompt
    assert prompt.index("相关历史复盘") < prompt.index("账号 Markdown 档案原文")


def test_environment_budget_is_configurable_and_capped() -> None:
    context = {"recent_reviews": [_review()]}
    with patch.dict(os.environ, {CONTEXT_PROMPT_MAX_CHARS_ENV: "120"}, clear=False):
        prompt = render_context_for_prompt(context)
    with patch.dict(os.environ, {CONTEXT_PROMPT_MAX_CHARS_ENV: "999999"}, clear=False):
        capped_prompt = render_context_for_prompt({"recent_reviews": [_review() for _ in range(200)]})

    assert len(prompt) <= 120
    assert len(capped_prompt) <= MAX_CONTEXT_PROMPT_MAX_CHARS


def test_explicit_small_budget_truncates_review_deterministically() -> None:
    context = {"recent_reviews": [_review()], "account_profile": {"markdown": "账号档案原文" * 100}}

    first = render_context_for_prompt(context, max_chars=120)
    second = render_context_for_prompt(context, max_chars=120)

    assert first == second
    assert len(first) <= 120
    assert "相关历史复盘" in first
    assert first.endswith("\n...（上下文已截断）")
    assert "账号 Markdown 档案原文" not in first
    assert render_context_for_prompt(context, max_chars=0) == ""


def test_budget_reserves_each_available_evidence_dimension_before_profile_markdown() -> None:
    prompt = render_context_for_prompt(
        {
            "recent_reviews": [_review()],
            "account_profile": {
                "platform": "抖音",
                "account": "跑步小王",
                "identity_summary": "面向初跑者的配速训练创作者",
                "markdown": "账号档案原文" * 800,
            },
            "recent_creations": [{"created_at": "2026-08-27", "topic": "历史创作", "title": "历史标题"}],
            "recent_daily_metrics": [{"captured_at": "2026-08-28", "account_name": "跑步小王", "post_count": 2, "total_interactions": 66}],
            "top_comments": ["求这个训练方案"],
            "global_rules": ["只基于已收到的评论原话提出选题。" * 300],
        },
        max_chars=2_500,
    )

    assert len(prompt) <= 2_500
    assert "生成要求：必须显式继承账号定位和复盘结论" in prompt
    assert "相关历史复盘" in prompt
    assert "首屏先明确被追问的冲突" in prompt
    assert "最近自有作品高价值评论原话（日报采集）" in prompt
    assert "求这个训练方案" in prompt
    assert "身份定位：面向初跑者的配速训练创作者" in prompt
    assert "最近自有作品日报指标" in prompt
    assert "相关历史创作" in prompt
    assert "未沉淀" not in prompt
