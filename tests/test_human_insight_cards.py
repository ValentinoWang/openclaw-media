from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from selfmedia.creation.insight_cards import load_insight_card_records
from selfmedia.deconstruct.viral_content.src.human_insight_cards import (
    CARD_LIBRARY_ROOT,
    HumanInsightCardError,
    load_human_insight_taxonomy,
    validate_card_markdown,
    validate_human_insight_candidate,
)
from selfmedia.deconstruct.viral_content.src.prompt import DECONSTRUCT_PROMPT


class HumanInsightCardTests(unittest.TestCase):
    def test_candidate_requires_controlled_mechanism_tag_and_evidence(self) -> None:
        taxonomy = load_human_insight_taxonomy()
        validate_human_insight_candidate(
            {
                "insight_id": "insight_001",
                "evidence_quote": "这不是你不努力，是你一直在用错方法。",
                "mechanism_tag": "被理解感",
                "target_emotion": "被看见后的释然",
                "desire_or_fear": "害怕自己的努力被判断为无效",
                "emotion_path": "自责 -> 被理解 -> 释然",
                "audience_group_hypothesis": "努力很久但害怕被说无效努力的内容创作者",
                "trigger_pattern": "先替受众卸下自责，再给可执行动作",
                "risk_boundary": "避免把焦虑扩大成羞辱或贩卖速成",
                "confidence": 0.72,
                "reasoning_summary": "证据句直接承接受众自责情绪。",
            },
            taxonomy,
        )
        with self.assertRaises(HumanInsightCardError):
            validate_human_insight_candidate(
                {
                    "insight_id": "insight_002",
                    "evidence_quote": "空泛共鸣。",
                    "mechanism_tag": "共鸣",
                    "target_emotion": "被看见",
                    "desire_or_fear": "害怕落后",
                    "emotion_path": "焦虑 -> 共鸣",
                    "audience_group_hypothesis": "年轻人",
                    "trigger_pattern": "引发共鸣",
                    "risk_boundary": "无",
                    "confidence": 0.5,
                    "reasoning_summary": "标签不受控。",
                },
                taxonomy,
            )

    def test_validated_card_requires_three_source_assets(self) -> None:
        card = """
---
card_type: mechanism
mechanism_tag: 被理解感
status: 已验证
---
# 被理解感
## 定义
让受众觉得自己的困境被准确说中。
## 触发方式
- 先说出具体自责句式。
## 情绪路径
身份焦虑 > 被看见 > 释然
## 适用群体标签
- 努力很久但害怕被说无效努力的内容创作者
## 证据条目
- source_asset_001 deconstruction_id=deconstruction_001 evidence_refs=sp_001: 证据句 A
## 反例/失效条件
- 证据不足时不能晋升。
## 平台风控风险
- 避免焦虑营销。
""".strip()
        with self.assertRaises(HumanInsightCardError):
            validate_card_markdown(card, card_type="mechanism")

    def test_template_frontmatter_does_not_treat_status_as_mechanism_tag(self) -> None:
        template = """---
card_type: mechanism
mechanism_tag: 被理解感
status: 假设
---
# 被理解感
## 定义
待补充。
## 触发方式
待补充。
## 情绪路径
待补充。
## 适用群体标签
待补充。
## 证据条目
待补充。
## 反例/失效条件
待补充。
## 平台风控风险
待补充。
"""
        validate_card_markdown(template, card_type="mechanism")

    def test_deconstruct_prompt_injects_taxonomy_values(self) -> None:
        self.assertIn("human_insight_taxonomy_v1.mechanism_tags", DECONSTRUCT_PROMPT)
        self.assertIn("被理解感", DECONSTRUCT_PROMPT)
        self.assertIn("candidate_tags", DECONSTRUCT_PROMPT)

    def test_loads_public_insight_cards_as_creation_references(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            mechanism_dir = root / "机制卡"
            group_dir = root / "群体卡"
            mechanism_dir.mkdir(parents=True)
            group_dir.mkdir(parents=True)
            (mechanism_dir / "被理解感.md").write_text(
                """---
card_type: mechanism_card
mechanism_tag: 被理解感
status: 已验证
---
# 被理解感
## 定义
准确说中受众困境。
## 触发方式
先说出具体自责句式。
## 情绪路径
身份焦虑 -> 被看见 -> 释然
## 适用群体标签
努力很久但害怕被说无效努力的内容创作者
## 平台风控风险
避免焦虑营销。
## 证据条目
- source_asset_001 deconstruction_id=deconstruction_001 evidence_refs=sp_001: 证据句 A
- source_asset_002 deconstruction_id=deconstruction_002 evidence_refs=sp_002: 证据句 B
- source_asset_003 deconstruction_id=deconstruction_003 evidence_refs=sp_003: 证据句 C
## 反例/失效条件
证据不足时保持假设。
""",
                encoding="utf-8",
            )
            (group_dir / "私密.md").write_text(
                """---
card_type: audience_group_card
audience_group_tag: 私密测试
status: 假设
---
# 私密测试
## 核心欲望/恐惧
social 私密人物档案
""",
                encoding="utf-8",
            )
            records = load_insight_card_records(root=root)
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0].source_table, "Obsidian:人性洞察库")
            self.assertIn("insight_card_path", records[0].detail_json)
            self.assertEqual(records[0].detail_json["evidence_boundary"], "public_content_only")
            self.assertEqual(records[0].detail_json["risk_boundary"], "避免焦虑营销。")

    def test_loader_skips_cards_outside_library_path_boundary(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "library"
            outside = Path(tmp) / "outside.md"
            mechanism_dir = root / "机制卡"
            mechanism_dir.mkdir(parents=True)
            outside.write_text("social 私密人物档案", encoding="utf-8")
            try:
                (mechanism_dir / "outside.md").symlink_to(outside)
            except OSError:
                return
            self.assertEqual(load_insight_card_records(root=root), [])

    def test_validated_card_requires_deconstruction_and_evidence_refs(self) -> None:
        card = """
---
card_type: mechanism
mechanism_tag: 被理解感
status: 已验证
---
# 被理解感
## 定义
让受众觉得自己的困境被准确说中。
## 触发方式
- 先说出具体自责句式。
## 情绪路径
身份焦虑 > 被看见 > 释然
## 适用群体标签
- 努力很久但害怕被说无效努力的内容创作者
## 证据条目
- source_asset_001: 证据句 A
- source_asset_002: 证据句 B
- source_asset_003: 证据句 C
## 反例/失效条件
- 证据不足时不能晋升。
## 平台风控风险
- 避免焦虑营销。
""".strip()
        with self.assertRaisesRegex(HumanInsightCardError, "deconstruction_id"):
            validate_card_markdown(card, card_type="mechanism")


if __name__ == "__main__":
    unittest.main()
