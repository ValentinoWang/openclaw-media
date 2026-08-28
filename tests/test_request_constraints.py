from __future__ import annotations

import pytest

from selfmedia import request_constraints
from selfmedia.deconstruct.viral_content.src import human_insight_cards


def test_promotion_threshold_uses_human_insight_taxonomy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        human_insight_cards,
        "load_human_insight_taxonomy",
        lambda: {"promotion_evidence_threshold": 5},
    )

    parsed = request_constraints.parse_request_constraints("【拆解】请沉淀为机制卡")
    assert parsed.promotion_evidence_threshold == 5
    assert "少于 5 个不同 SourceAsset 证据" in human_insight_cards.aggregation_prompt_contract()

    payload = parsed.to_dict()
    payload["promotion_evidence_threshold"] = 4
    with pytest.raises(ValueError, match="不能小于 5"):
        request_constraints.validate_request_constraints_payload(payload)
