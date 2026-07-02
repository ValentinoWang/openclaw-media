from __future__ import annotations

from common.knowledge_categories import normalize_knowledge_secondary_categories


def test_normalize_custom_xhs_growth_categories_to_standard_values() -> None:
    normalized = normalize_knowledge_secondary_categories(
        ["平台机制", "内容增长", "创作者变现"],
        primary="运营/管理",
        text="小红书新规让普通创作者获得流量和变现窗口",
    )

    assert normalized == ["算法拆解/增长", "自媒体运营"]


def test_normalize_markdown_bullet_categories_to_standard_values() -> None:
    normalized = normalize_knowledge_secondary_categories(
        "- AI前端动画\n- AI工具应用\n- 代码生成",
        primary="AI/工具",
    )

    assert normalized == ["AI工具应用", "模型/智能体"]


def test_normalize_relation_risk_categories_to_standard_values() -> None:
    normalized = normalize_knowledge_secondary_categories(
        "- 亲密关系\n- 反PUA\n- 传播机制",
        primary="学习/认知",
    )

    assert normalized == ["关系认知", "关系风险"]
