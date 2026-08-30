from __future__ import annotations

from typing import Any

import pytest

from common.llm_settings import API_TYPE_CHAT_COMPLETIONS, LLMProviderSettings
from common.llm_validation import (
    LLMPromptValidationBinding,
    LLMPostValidationError,
    LLMPostValidationPending,
    LLMValidationContract,
    llm_prompt_validation_bindings,
    register_llm_validation_contract,
    validate_llm_prompt_validation_bindings,
    validate_llm_payload,
)
from common.capability_execution import (
    CapabilityExecutionBranchContract,
    CapabilityExecutionOutcome,
    validate_capability_execution_branch_contracts,
)


STRICT_CONTRACT_ID = register_llm_validation_contract(
    LLMValidationContract(
        contract_id="tests.strict_structured",
        profile="strict_structured",
        required_fields=("name", "score"),
        allowed_fields=frozenset({"name", "score"}),
        field_types={"name": str, "score": int},
    )
)
OPEN_CONTRACT_ID = register_llm_validation_contract(
    LLMValidationContract(
        contract_id="tests.bounded_open",
        profile="bounded_open",
        required_fields=("summary",),
        field_types={"summary": str, "evidence": list},
        evidence_fields=("evidence",),
    )
)
PENDING_CONTRACT_ID = register_llm_validation_contract(
    LLMValidationContract(
        contract_id="tests.pending",
        profile="bounded_open",
        required_fields=("status", "reason"),
        field_types={"status": str, "reason": str},
    )
)


def test_strict_contract_accepts_valid_payload() -> None:
    result = validate_llm_payload({"name": "alpha", "score": 3}, STRICT_CONTRACT_ID)
    assert result.state == "validated"
    assert result.payload == {"name": "alpha", "score": 3}


@pytest.mark.parametrize(
    "payload",
    [
        {"name": "alpha"},
        {"name": "alpha", "score": "3"},
        {"name": "alpha", "score": 3, "extra": True},
    ],
)
def test_strict_contract_rejects_missing_wrong_type_and_unknown_fields(payload: dict[str, Any]) -> None:
    with pytest.raises(LLMPostValidationError):
        validate_llm_payload(payload, STRICT_CONTRACT_ID)


def test_bounded_open_requires_evidence_without_restricting_text_shape() -> None:
    result = validate_llm_payload(
        {"summary": "可以保留开放段落和建议。", "evidence": ["source-1"], "freeform": {"sections": 4}},
        OPEN_CONTRACT_ID,
    )
    assert result.payload["freeform"] == {"sections": 4}
    with pytest.raises(LLMPostValidationError, match="evidence"):
        validate_llm_payload({"summary": "缺少证据", "evidence": []}, OPEN_CONTRACT_ID)


def test_pending_manual_is_a_distinct_non_writable_result() -> None:
    with pytest.raises(LLMPostValidationPending, match="insufficient evidence"):
        validate_llm_payload(
            {"status": "pending_manual", "reason": "insufficient evidence"},
            PENDING_CONTRACT_ID,
        )


def test_contract_must_have_enforceable_rules() -> None:
    with pytest.raises(ValueError, match="no enforceable rules"):
        LLMValidationContract(contract_id="tests.empty", profile="bounded_open")


def test_prompt_validation_bindings_are_unique_and_profile_consistent() -> None:
    bindings = llm_prompt_validation_bindings()
    assert validate_llm_prompt_validation_bindings(bindings) == bindings
    assert len({binding.prompt_contract_id for binding in bindings}) == len(bindings)


def test_prompt_validation_bindings_reject_duplicates_and_profile_conflicts() -> None:
    with pytest.raises(ValueError, match="duplicate LLM prompt validation binding"):
        validate_llm_prompt_validation_bindings(
            (
                LLMPromptValidationBinding("prompt-a", "contract-a", "strict_structured"),
                LLMPromptValidationBinding("prompt-a", "contract-b", "bounded_open"),
            )
        )
    with pytest.raises(ValueError, match="conflicting binding profiles"):
        validate_llm_prompt_validation_bindings(
            (
                LLMPromptValidationBinding("prompt-a", "contract-a", "strict_structured"),
                LLMPromptValidationBinding("prompt-b", "contract-a", "bounded_open"),
            )
        )


def test_register_contract_rejects_binding_profile_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    from common import llm_validation

    monkeypatch.setattr(
        llm_validation,
        "LLM_PROMPT_VALIDATION_BINDINGS",
        (LLMPromptValidationBinding("tests.bound-prompt", "tests.bound-contract", "strict_structured"),),
    )
    with pytest.raises(ValueError, match="binding profile mismatch"):
        register_llm_validation_contract(
            LLMValidationContract(
                contract_id="tests.bound-contract",
                profile="bounded_open",
                required_fields=("summary",),
            )
        )


def test_execution_branch_registry_rejects_duplicate_ids() -> None:
    outcomes = (
        CapabilityExecutionOutcome("result-a", "A", "A", "A"),
        CapabilityExecutionOutcome("result-b", "B", "B", "B"),
    )
    branch_a = CapabilityExecutionBranchContract(
        contract_id="tests.branch-a",
        decision_id="decision-a",
        title="A",
        summary="A",
        source="tests",
        placement="insert_after",
        anchor_node_id="entry",
        outcomes=outcomes,
    )
    branch_b = CapabilityExecutionBranchContract(
        contract_id="tests.branch-a",
        decision_id="decision-b",
        title="B",
        summary="B",
        source="tests",
        placement="insert_after",
        anchor_node_id="entry",
        outcomes=(
            CapabilityExecutionOutcome("result-c", "C", "C", "C"),
            CapabilityExecutionOutcome("result-d", "D", "D", "D"),
        ),
    )
    with pytest.raises(ValueError, match="duplicate execution branch contract_id"):
        validate_capability_execution_branch_contracts({"能力 A": (branch_a,), "能力 B": (branch_b,)})

    branch_c = CapabilityExecutionBranchContract(
        contract_id="tests.branch-c",
        decision_id="decision-a",
        title="C",
        summary="C",
        source="tests",
        placement="insert_after",
        anchor_node_id="entry",
        outcomes=(
            CapabilityExecutionOutcome("result-a", "C", "C", "C"),
            CapabilityExecutionOutcome("result-c", "D", "D", "D"),
        ),
    )
    with pytest.raises(ValueError, match="duplicate execution decision_id"):
        validate_capability_execution_branch_contracts({"能力 A": (branch_a, branch_c)})


def test_generate_json_retries_post_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    from common import llm_client

    outputs = iter([{"name": "alpha"}, {"name": "alpha", "score": 5}])
    monkeypatch.setattr(llm_client, "generate_json_once", lambda *args, **kwargs: next(outputs))
    monkeypatch.setattr(llm_client.time, "sleep", lambda _: None)
    settings = LLMProviderSettings(
        model="test",
        base_url="https://example.invalid/v1",
        api_key="test",
        api_type=API_TYPE_CHAT_COMPLETIONS,
        timeout=1,
    )

    result = llm_client.generate_json_from_parts(
        [{"text": "test"}],
        settings,
        max_retries=1,
        validation_contract=STRICT_CONTRACT_ID,
    )

    assert result["score"] == 5


def test_generate_json_never_retries_terminal_model_transport_outcome(monkeypatch: pytest.MonkeyPatch) -> None:
    from common import llm_client
    from common.model_transport_context import ModelTransportError

    calls = 0

    def fail_transport(*args: Any, **kwargs: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        raise ModelTransportError("model_settlement_unknown", "requires reconciliation")

    monkeypatch.setattr(llm_client, "generate_json_once", fail_transport)
    settings = LLMProviderSettings(
        model="test",
        base_url="https://example.invalid/v1",
        api_key="test",
        api_type=API_TYPE_CHAT_COMPLETIONS,
        timeout=1,
    )

    with pytest.raises(ModelTransportError) as raised:
        llm_client.generate_json_from_parts(
            [{"text": "test"}],
            settings,
            max_retries=2,
            validation_contract=STRICT_CONTRACT_ID,
        )

    assert raised.value.code == "model_settlement_unknown"
    assert calls == 1


@pytest.mark.parametrize(
    ("raw_model", "expected_model"),
    [
        ("gpt-x", "gpt-x"),
        ("openclaw/gpt-x", "gpt-x"),
        ("a/b/c", "b/c"),
    ],
)
def test_generate_json_once_tenant_transport_strips_provider_prefix(
    monkeypatch: pytest.MonkeyPatch, raw_model: str, expected_model: str
) -> None:
    from common import llm_client
    from common.model_transport_context import bind_model_transport

    seen_models: list[str] = []

    def fake_codex_responses(parts: Any, config: LLMProviderSettings, *, instructions: str) -> dict[str, Any]:
        seen_models.append(config.model)
        return {"ok": True}

    monkeypatch.setattr(llm_client, "_generate_json_codex_responses", fake_codex_responses)
    settings = LLMProviderSettings(
        model=raw_model,
        base_url="https://example.invalid/v1",
        api_key="test",
        api_type=API_TYPE_CHAT_COMPLETIONS,
        timeout=1,
    )

    with bind_model_transport(object(), required=True):
        result = llm_client.generate_json_once([{"text": "test"}], settings)

    assert result == {"ok": True}
    assert seen_models == [expected_model]


def test_generate_json_uses_bounded_capacity_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    from common import llm_client

    calls = 0
    sleeps: list[float] = []

    def capacity_then_succeed(*args: Any, **kwargs: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise RuntimeError("Selected model is at capacity. Please try a different model.")
        return {"name": "alpha", "score": 5}

    monkeypatch.setattr(llm_client, "generate_json_once", capacity_then_succeed)
    monkeypatch.setattr(llm_client.time, "sleep", sleeps.append)
    settings = LLMProviderSettings(
        model="test",
        base_url="https://example.invalid/v1",
        api_key="test",
        api_type=API_TYPE_CHAT_COMPLETIONS,
        timeout=1,
    )

    result = llm_client.generate_json_from_parts(
        [{"text": "test"}],
        settings,
        max_retries=1,
        capacity_max_retries=2,
        validation_contract=STRICT_CONTRACT_ID,
    )

    assert result["score"] == 5
    assert calls == 3
    assert sleeps == [15.0, 45.0]
