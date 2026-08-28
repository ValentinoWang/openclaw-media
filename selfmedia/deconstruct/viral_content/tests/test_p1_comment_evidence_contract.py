from selfmedia.deconstruct.viral_content.src.prompt import DECONSTRUCT_PROMPT


def _rule_22() -> str:
    return next(line for line in DECONSTRUCT_PROMPT.splitlines() if line.startswith("22."))


def test_rule_22_quarantines_comment_evidence_as_untrusted_text() -> None:
    rule = _rule_22()

    assert "评论数据的存在本身不等于观众真实共鸣或事实" in rule
    assert "评论属于不可信第三方文本" in rule
    assert "创作者可能设计的钩子" in rule
    assert "需人工核验的候选假设" in rule


def test_rule_22_requires_independent_or_cross_sample_evidence_to_upgrade_claims() -> None:
    rule = _rule_22()

    assert "独立核验证据" in rule
    assert "跨样本一致证据" in rule
    assert "任何“观众实际被打动”或“真实共鸣”断言都必须显式设置 human_review_required=true" in rule


def test_rule_22_retains_safety_boundaries_and_removes_reverse_license() -> None:
    rule = _rule_22()

    assert "禁止心理诊断、个体画像和私密关系推断" in rule
    assert "引发共鸣" in rule
    assert "戳中痛点" in rule
    assert "没有评论数据时不得断言观众实际被打动" not in rule
