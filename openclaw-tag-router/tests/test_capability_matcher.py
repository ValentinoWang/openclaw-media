from __future__ import annotations

import json

import pytest

from openclaw_app.services.capability_matcher import CapabilityMatcher, CapabilityMatcherError
from openclaw_app.services.capability_registry import CAPABILITY_REGISTRY


PLAN_ID = "capplan_1234567890abcdef"


def matcher(raw):
    return CapabilityMatcher(model_call=lambda _: raw, plan_id_factory=lambda: PLAN_ID)


def creator_step(**overrides):
    value = {
        "order": 1,
        "capabilityId": "creator_profile_upsert",
        "variantId": "url_candidate",
        "extractedParams": {"profile_url": "https://xhslink.com/example"},
        "confidence": 0.94,
        "evidence": [{"fieldKey": "profile_url", "quote": "https://xhslink.com/example", "source": "query"}],
    }
    value.update(overrides)
    return value


def test_matched_returns_editable_structured_draft_and_derived_projection() -> None:
    result = matcher({
        "pathStatus": "matched", "needSummary": "录入小红书博主", "routeExplanation": "用户明确要求入库并提供主页链接。",
        "steps": [creator_step()],
    }).match({"query": "把博主录入，主页链接 https://xhslink.com/example", "currentBot": "media"})

    assert result["schemaVersion"] == "3"
    assert result["steps"][0]["extractedParams"] == {"profile_url": "https://xhslink.com/example"}
    assert result["steps"][0]["issues"] == []
    assert result["copyProjection"].startswith("【博主-入库】\n路径续接ID：")
    assert "https://xhslink.com/example" in result["copyProjection"]


def test_matcher_prompt_declares_exact_evidence_shape_without_text_alias() -> None:
    prompts: list[str] = []

    def capture(prompt: str):
        prompts.append(prompt)
        return {
            "pathStatus": "matched", "needSummary": "录入", "routeExplanation": "提供了主页链接。",
            "steps": [creator_step()],
        }

    CapabilityMatcher(model_call=capture, plan_id_factory=lambda: PLAN_ID).match(
        {"query": "录入 https://xhslink.com/example", "currentBot": "media"}
    )

    assert len(prompts) == 1
    assert '"quote":"用户原文中的连续片段"' in prompts[0]
    assert "禁止使用 text、content 或其他字段替代 quote" in prompts[0]


def test_missing_required_fields_are_server_recomputed_not_rejected() -> None:
    step = creator_step(variantId="manual", extractedParams={"platform": "小红书"}, evidence=[{"fieldKey": "platform", "quote": "小红书", "source": "query"}])
    result = matcher({"pathStatus": "matched", "needSummary": "手工录入", "routeExplanation": "选择手工入库。", "steps": [step]}).match({"query": "手工录入一个小红书博主", "currentBot": "media"})

    assert {issue["code"] for issue in result["steps"][0]["issues"]} == {"required", "at_least_one"}
    assert any(issue.get("fieldKey") == "expertise_domains" for issue in result["steps"][0]["issues"])


def test_ambiguous_returns_only_valid_candidates() -> None:
    result = matcher({
        "pathStatus": "ambiguous", "needSummary": "用户想查找或录入博主",
        "candidates": [
            {"capabilityId": "creator_profile_lookup", "variantId": "query", "confidence": 0.61, "reason": "可能只是查询。"},
            {"capabilityId": "creator_profile_upsert", "variantId": "url_candidate", "confidence": 0.58, "reason": "也可能需要入库。"},
        ],
    }).match({"query": "处理这个博主", "currentBot": "media"})

    assert result["pathStatus"] == "ambiguous"
    assert len(result["candidates"]) == 2
    assert "guidancePlanId" not in result


def test_needs_clarification_is_read_only_and_keeps_known_params() -> None:
    result = matcher({
        "pathStatus": "needs_clarification", "needSummary": "处理博主档案", "clarificationQuestion": "你想查询还是入库？",
        "candidates": [], "knownParams": {"platform": "小红书"},
    }).match({"query": "处理小红书博主", "currentBot": "media"})

    assert result == {
        "schemaVersion": "3", "pathStatus": "needs_clarification", "needSummary": "处理博主档案",
        "clarificationQuestion": "你想查询还是入库？", "candidates": [], "knownParams": {"platform": "小红书"},
    }


@pytest.mark.parametrize("mutation", [
    {"capabilityId": "missing_capability"},
    {"variantId": "missing_variant"},
    {"extractedParams": {"unknown": "value"}},
    {"evidence": [{"quote": "伪造证据", "source": "query"}]},
    {"evidence": [{"text": "https://xhslink.com/example", "source": "query"}]},
    {"confidence": 1.2},
])
def test_invalid_model_facts_fail_closed_after_retry(mutation) -> None:
    step = creator_step(**mutation)
    with pytest.raises(CapabilityMatcherError, match="能力|操作|证据|置信度|字段"):
        matcher({"pathStatus": "matched", "needSummary": "录入", "routeExplanation": "录入。", "steps": [step]}).match({"query": "录入 https://xhslink.com/example", "currentBot": "media"})


def test_not_implemented_capability_cannot_be_recommended() -> None:
    step = creator_step(capabilityId="account_track_strategy", variantId="default", extractedParams={}, evidence=[])
    with pytest.raises(CapabilityMatcherError, match="不可执行"):
        matcher({"pathStatus": "matched", "needSummary": "策略", "routeExplanation": "策略。", "steps": [step]}).match({"query": "给我账号策略", "currentBot": "media"})


def test_current_bot_scope_rejects_cross_bot_recommendation() -> None:
    step = creator_step(capabilityId="reminder", variantId="default", extractedParams={}, evidence=[])
    with pytest.raises(CapabilityMatcherError, match="当前 Bot"):
        matcher({"pathStatus": "matched", "needSummary": "提醒", "routeExplanation": "提醒。", "steps": [step]}).match(
            {"query": "在 Media bot 设置提醒", "currentBot": "media"}
        )


def test_deepmath_prompt_catalog_contains_only_deepmath_capabilities() -> None:
    prompts: list[str] = []
    definition = CAPABILITY_REGISTRY.get("deepmath_ceo_thinking_intake")
    assert definition is not None
    variant = definition.variants[0]

    def capture(prompt: str):
        prompts.append(prompt)
        return {
            "pathStatus": "matched",
            "needSummary": "收件并生成思考候选",
            "routeExplanation": "使用 DeepMath 思考收件入口。",
            "steps": [{
                "order": 1,
                "capabilityId": definition.capability_id,
                "variantId": variant.variant_id,
                "extractedParams": {},
                "confidence": 0.9,
                "evidence": [],
            }],
        }

    result = CapabilityMatcher(model_call=capture, plan_id_factory=lambda: PLAN_ID).match(
        {"query": "验证这个假设", "currentBot": "deepmath"}
    )

    assert result["steps"][0]["capabilityId"] == "deepmath_ceo_thinking_intake"
    assert len(prompts) == 1
    catalog_text = prompts[0].split("候选目录：", 1)[1].split("\n用户需求：", 1)[0]
    catalog = json.loads(catalog_text)
    assert {item["capabilityId"] for item in catalog} == {"deepmath_ceo_thinking_intake"}
    assert "creator_profile_upsert" not in catalog_text


def test_deepmath_rejects_model_candidate_outside_deepmath_scope() -> None:
    with pytest.raises(CapabilityMatcherError, match="当前 Bot"):
        matcher({
            "pathStatus": "matched",
            "needSummary": "错误跨 Bot 路由",
            "routeExplanation": "不应推荐 Media 能力。",
            "steps": [creator_step()],
        }).match({"query": "录入 https://xhslink.com/example", "currentBot": "deepmath"})


def test_provider_failure_returns_pending_manual_style_error_without_fallback() -> None:
    def fail(_: str):
        raise RuntimeError("provider offline")

    with pytest.raises(CapabilityMatcherError) as raised:
        CapabilityMatcher(model_call=fail).match({"query": "录入博主", "currentBot": "media"})
    assert raised.value.code == "provider_unavailable"


def test_continuation_binds_real_output_and_returns_structured_step() -> None:
    continuation = {"extractedParams": {"field_c675ffae69a2": "source_asset_real"}, "confidence": 1, "evidence": [{"fieldKey": "field_c675ffae69a2", "quote": "source_asset_real", "source": "bound_result"}]}
    plan = {
        "guidancePlanId": PLAN_ID, "originalQuery": "先收素材再选题",
        "steps": [{"order": 2, "capabilityId": "source_asset_intake", "variantId": "default", "extractedParams": {}, "confidence": 0.8, "evidence": [], "issues": [], "dependsOn": {"stepOrder": 1, "requiredOutputs": ["source_asset_id"]}}],
    }
    result = CapabilityMatcher(continuation_model_call=lambda _: continuation).compose_continuation(plan, {"source_asset_id": "source_asset_real"})

    assert result["extractedParams"]["field_c675ffae69a2"] == "source_asset_real"
    assert "source_asset_real" in result["copyProjection"]


def test_catalog_uses_canonical_ids_and_aliases() -> None:
    catalog = CapabilityMatcher(model_call=lambda _: {}).public_catalog()
    polish = next(item for item in catalog if item["capabilityId"] == "style_polish_run")
    assert "去AI味" in polish["aliases"]
    assert len({item["capabilityId"] for item in catalog}) == len(catalog)
