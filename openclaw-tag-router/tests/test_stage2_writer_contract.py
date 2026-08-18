from __future__ import annotations

import json
from pathlib import Path


CONTRACT_PATH = (
    Path(__file__).resolve().parents[1]
    / "openclaw_app"
    / "contracts"
    / "stage2_writer_contract.json"
)

EXPECTED_ERROR_CODES = {
    "invalid_request",
    "contract_version_unsupported",
    "authority_override_forbidden",
    "authority_pair_invalid",
    "context_invalid",
    "context_receipt_invalid",
    "workspace_mismatch",
    "capability_not_registered",
    "capability_write_not_allowed",
    "idempotency_conflict",
    "write_failed",
    "registration_failed",
    "readback_incomplete",
    "external_write_needs_attention",
    "publish_blocked",
}


def load_contract() -> dict:
    with CONTRACT_PATH.open(encoding="utf-8") as handle:
        value = json.load(handle)
    assert isinstance(value, dict)
    return value


def test_contract_is_versioned_provisional_and_has_no_endpoint() -> None:
    contract = load_contract()

    assert contract["contractVersion"] == "stage2_writer_contract.v1"
    assert contract["schemaVersion"] == 1
    assert contract["status"] == "provisional"
    assert contract["runtimeIntegration"] is False
    assert contract["endpoints"] == []


def test_authority_policy_distinguishes_the_two_body_authorities() -> None:
    policy = load_contract()["authorityPolicy"]

    pairs = {
        (item["workspace"], item["bodyAuthority"], item["remoteRef"])
        for item in policy["workspaceBodyPairs"]
    }
    assert pairs == {
        ("personal_web", "internal", "forbidden"),
        ("organization_lark", "lark", "required"),
    }

    forbidden = set(policy["browserForbiddenFields"])
    assert {
        "authorityOverride",
        "tenantId",
        "bindingId",
        "workspace",
        "bodyAuthority",
        "containerId",
        "credentials",
        "larkAppId",
        "larkSpaceId",
        "parentNodeId",
    } <= forbidden


def test_context_and_receipt_are_strict_and_server_derived() -> None:
    defs = load_contract()["$defs"]

    for name in ("trustedContext", "contextReceipt"):
        schema = defs[name]
        assert schema["type"] == "object"
        assert schema["additionalProperties"] is False
        assert {"workspace", "bodyAuthority", "organizationBindingRef"} <= set(schema["required"])
        assert {"$ref": "#/$defs/workspaceBodyPair"} in schema["allOf"]

    trusted_properties = defs["trustedContext"]["properties"]
    assert {
        "sessionRef",
        "actorRef",
        "capabilityId",
        "sourceRefs",
    } <= set(trusted_properties)


def test_writer_request_rejects_browser_authority_fields() -> None:
    contract = load_contract()
    request = contract["$defs"]["writerRequest"]
    forbidden = set(contract["authorityPolicy"]["browserForbiddenFields"])

    assert request["additionalProperties"] is False
    assert not (set(request["properties"]) & forbidden)
    assert "trustedContext" in request["properties"]
    assert "server-derived trustedContext" in request["description"]


def test_write_result_is_never_publishable_and_enforces_remote_ref_rules() -> None:
    result = load_contract()["$defs"]["writeResult"]

    assert result["properties"]["publishable"] == {"const": False}
    assert {"$ref": "#/$defs/workspaceBodyPair"} in result["allOf"]

    personal_rule = next(
        item
        for item in result["allOf"]
        if item.get("if", {}).get("properties", {}).get("workspace", {}).get("const")
        == "personal_web"
    )
    organization_rule = next(
        item
        for item in result["allOf"]
        if item.get("if", {}).get("properties", {}).get("workspace", {}).get("const")
        == "organization_lark"
    )
    assert personal_rule["then"]["properties"]["artifact"]["properties"]["remoteRef"] == {
        "type": "null"
    }
    assert organization_rule["then"]["properties"]["artifact"]["properties"]["remoteRef"] == {
        "$ref": "#/$defs/identifier"
    }


def test_every_error_code_is_fail_closed_and_known_by_error_envelope() -> None:
    contract = load_contract()
    error_codes = contract["errorCodes"]

    assert len(error_codes) == len(EXPECTED_ERROR_CODES)
    assert {item["code"] for item in error_codes} == EXPECTED_ERROR_CODES
    assert all(item["failClosed"] is True for item in error_codes)

    envelope_codes = set(
        contract["$defs"]["failClosedError"]["properties"]["error"]["properties"]["code"][
            "enum"
        ]
    )
    assert envelope_codes == EXPECTED_ERROR_CODES
    assert contract["$defs"]["failClosedError"]["properties"]["ok"] == {"const": False}
    assert contract["$defs"]["failClosedError"]["properties"]["error"]["properties"][
        "publishable"
    ] == {"const": False}
