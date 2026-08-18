from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from openclaw_app.services.guidance_plan import GuidancePlanError, GuidancePlanService, GuidancePlanStore


PLAN_ID = "capplan_1234567890abcdef"


def matched(steps=None):
    return {
        "schemaVersion": "3", "pathStatus": "matched", "needSummary": "录入博主", "routeExplanation": "使用博主入库。",
        "guidancePlanId": PLAN_ID,
        "steps": steps or [{"order": 1, "capabilityId": "creator_profile_upsert", "variantId": "url_candidate", "extractedParams": {"profile_url": "https://xhslink.com/a"}, "confidence": 0.9, "evidence": [{"fieldKey": "profile_url", "quote": "https://xhslink.com/a", "source": "query"}], "issues": []}],
        "copyProjection": "ignored derived projection",
    }


def test_register_persists_structured_facts_and_derives_copy_projection(tmp_path: Path) -> None:
    service = GuidancePlanService(store=GuidancePlanStore(tmp_path))
    result = service.register_match(matched(), query="录入 https://xhslink.com/a", current_bot="media")
    stored = json.loads((tmp_path / f"{PLAN_ID}.json").read_text())

    assert result["schemaVersion"] == "3"
    assert result["copyProjection"].startswith("【博主-入库】")
    assert stored["steps"][0]["extractedParams"] == {"profile_url": "https://xhslink.com/a"}
    assert "copyText" not in json.dumps(stored)


def test_non_matched_result_is_not_persisted(tmp_path: Path) -> None:
    response = {"schemaVersion": "3", "pathStatus": "ambiguous", "needSummary": "不明确", "candidates": []}
    assert GuidancePlanService(store=GuidancePlanStore(tmp_path)).register_match(response, query="x") == response
    assert list(tmp_path.glob("capplan_*.json")) == []


def test_submission_must_equal_derived_projection() -> None:
    service = GuidancePlanService()
    result = service.register_match(matched(), query="录入 https://xhslink.com/a")
    assert service.validate_submitted_step(PLAN_ID, tag="博主-入库", text=result["copyProjection"]) is None
    with pytest.raises(GuidancePlanError, match="投影不一致"):
        service.validate_submitted_step(PLAN_ID, tag="博主-入库", text=result["copyProjection"] + "\n额外字段：越权")


def test_real_result_binding_advances_structured_continuation() -> None:
    steps = [
        {"order": 1, "capabilityId": "source_asset_intake", "variantId": "default", "extractedParams": {"field_c675ffae69a2": "原始素材"}, "confidence": 0.9, "evidence": [], "issues": []},
        {"order": 2, "capabilityId": "creation_decision_brief", "variantId": "default", "extractedParams": {}, "confidence": 0.8, "evidence": [], "issues": [], "dependsOn": {"stepOrder": 1, "requiredOutputs": ["source_asset_id"]}},
    ]
    service = GuidancePlanService()
    service.register_match(matched(steps), query="先收素材再选题")
    context = service.bind_step_result(PLAN_ID, step_order=1, task_result=SimpleNamespace(ok=True, extra={"artifact": {"artifact_id": "source_asset_real"}}))
    assert context is not None and context.bindings == {"source_asset_id": "source_asset_real"}
    ready = service.finalize_next_step(PLAN_ID, step_order=2, step={"capabilityId": "creation_decision_brief", "variantId": "default", "extractedParams": {"artifact_id": "source_asset_real"}, "confidence": 1, "evidence": []})
    assert ready.step_order == 2


def test_expired_plan_is_removed() -> None:
    now = datetime(2026, 7, 29, tzinfo=UTC)
    service = GuidancePlanService(ttl=timedelta(seconds=1), now_factory=lambda: now)
    service.register_match(matched(), query="录入")
    service._now_factory = lambda: now + timedelta(seconds=2)
    with pytest.raises(GuidancePlanError, match="过期"):
        service.get_public_response(PLAN_ID)
