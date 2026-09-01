from __future__ import annotations

import copy
import importlib.util
import hashlib
import json
import re
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "agents-results/2026-08-15/media-c-b-stage-2-content-and-ai-document-routing"


def load_stage2_build():
    spec = importlib.util.spec_from_file_location("stage2_acceptance_build", BUNDLE / "build_ssot.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    original_path = sys.path.copy()
    try:
        sys.path.insert(0, str(BUNDLE))
        spec.loader.exec_module(module)
    finally:
        sys.path[:] = original_path
    return module


def test_human_acceptance_budget_demotes_machine_testable_item() -> None:
    module = load_stage2_build()
    policy = module.HUMAN_ACCEPTANCE_POLICY

    assert policy["blocking_budget"] == 3
    assert policy["blocking_task_ids"] == ["O1", "O5", "DB"]
    assert policy["demoted_machine_testable_task_ids"] == ["K"]
    assert len(policy["blocking_task_ids"]) <= policy["blocking_budget"]
    assert module.NODES["K"]["acceptance_lane"]["lane"] == "machine"
    assert module.NODES["K"]["acceptance_lane"]["blocking"] is False
    assert {
        node_id
        for node_id, node in module.NODES.items()
        if node["acceptance_lane"]["blocking"]
    } == {"O1", "O5", "DB"}
    assert module.HUMAN_ACCEPTANCE_FRAGMENTS["K"]["blocking"] is False


def test_ai_review_is_single_zero_write_with_one_scoped_rereview() -> None:
    module = load_stage2_build()
    policy = module.AI_REVIEW_POLICY
    rereview = policy["finding_rereview"]

    assert policy["mode"] == "single-independent-zero-write-with-scoped-rereview"
    assert policy["independent_lane_count"] == 1
    assert policy["write_authority"] == "zero-write"
    assert rereview["max_per_finding"] == 1
    assert rereview["scope"] == "finding-only"
    assert policy["parallel_dual_lanes"] is False


def test_planning_compiler_publishes_acceptance_policy() -> None:
    module = load_stage2_build()
    compiled = module.planning_compiler()

    assert compiled["acceptance_policy"]["human"] == module.HUMAN_ACCEPTANCE_POLICY
    assert compiled["acceptance_policy"]["ai_review"] == module.AI_REVIEW_POLICY
    assert compiled["nodes"]
    assert all("acceptance_lane" in node for node in compiled["nodes"])
    states = {node["id"]: node["execution_state"] for node in compiled["nodes"]}
    assert {node_id for node_id, state in states.items() if state == "ACCEPTED"} == {"A", "A1", "K"}
    assert sum(state == "BLOCKED" for state in states.values()) == 29


def test_generated_identity_and_invalidation_are_content_scoped() -> None:
    machine = BUNDLE / ".ssot"
    manifest = json.loads((machine / "manifest.json").read_text(encoding="utf-8"))
    planning = json.loads((machine / "planning-compiler.json").read_text(encoding="utf-8"))
    db = json.loads((machine / "nodes" / "DB.json").read_text(encoding="utf-8"))
    edge = json.loads((machine / "edges" / "E-055-DA-DB.json").read_text(encoding="utf-8"))

    source_identity = manifest["source_repository_identity"]
    module = load_stage2_build()
    assert source_identity["repository_commit"] == module.source_repository_identity()["repository_commit"]
    assert source_identity["revision_base_commit"] == source_identity["repository_commit"]
    assert isinstance(source_identity["dirty"], bool)
    assert re.fullmatch(r"[0-9a-f]{64}", source_identity["dirty_diff_sha256"])
    assert "source_root" not in source_identity
    assert manifest["source_repository_identity"]["historical_observation_commit"] == "007a7f906af4e23a6a4fa5d041da4cb0641646c2"
    assert manifest["identity_registry"]["DB"]["contract_identity"] == db["contract_identity"]
    assert manifest["identity_registry"]["DB"]["consumer_surface_digest"] == db["consumer_surface_digest"]["digest"]
    assert manifest["protected_test_identity"]["mutation_policy"] == "invalidate-and-rerun; never skip"
    assert db["consumer_surface_digest"]["surface"]["upstream_contract_inputs"]
    assert any("surface.sha256-" in key for key in db["invalidation_keys"])
    assert any("input.da.sha256-" in key for key in edge["invalidation_keys"])
    assert "source_consumer_surface_digest" not in edge
    assert "target_consumer_surface_digest" not in edge
    assert edge["transferred_output_contract"]["contract"]["source_acceptance_predicate"]
    assert not any(key.endswith(".v5") for key in db["invalidation_keys"])

    compiled_db = next(node for node in planning["nodes"] if node["id"] == "DB")
    for field in (
        "contract_identity",
        "verification_source_digest",
        "consumer_surface_digest",
        "protected_test_identity",
        "blockers",
    ):
        assert field in compiled_db
    blocker_classes = {record["class"] for record in compiled_db["blockers"]}
    assert "missing-authenticated-browser-device-proof" in blocker_classes
    assert "missing-deployment-release-evidence" in blocker_classes


def test_decision_consumers_bind_only_declared_shards() -> None:
    module = load_stage2_build()
    all_shards = set(module.DECISION_SHARD_FREEZE["shards"])
    expected_consumers = {"K"} | {
        node_id for node_id, spec in module.SPECS.items() if spec["consumes_decision"]
    }

    assert set(module.DECISION_SHARDS_BY_NODE) == expected_consumers
    assert set(module.DECISION_SHARDS_BY_NODE["S1"]) == {"session-authority", "entry-state"}
    assert set(module.DECISION_SHARDS_BY_NODE["S2"]) == {"artifact-closure"}
    assert set(module.DECISION_SHARDS_BY_NODE["S3"]) == {"writer-authority"}
    assert set(module.DECISION_SHARDS_BY_NODE["C6"]) == {"writer-authority"}
    assert set(module.DECISION_SHARDS_BY_NODE["O1"]) == {"artifact-closure"}
    assert set(module.DECISION_SHARDS_BY_NODE["O5"]) == {"artifact-closure"}
    assert any(set(shards) < all_shards for node_id, shards in module.DECISION_SHARDS_BY_NODE.items() if node_id != "K")

    for node_id, shard_ids in module.DECISION_SHARDS_BY_NODE.items():
        node = module.NODES[node_id]
        expected = module._decision_shard_values(node_id)
        assert node["decision_shard_freeze"]["shard_ids"] == list(shard_ids)
        assert node["decision_shard_freeze"]["shards"] == expected
        assert node["consumer_surface_digest"]["surface"]["consumed_decision_shards"] == expected

    declared_fields = {
        field
        for fields in module.DECISION_SHARD_FREEZE["shards"].values()
        for field in fields
    }
    assert declared_fields == set(module.PRODUCT_DECISION_VALUES)


def test_decision_and_transfer_mutations_have_exact_local_radius() -> None:
    module = load_stage2_build()
    original_writer = module.PRODUCT_DECISION_VALUES["writer_routing"]
    before = {
        node_id: module._consumer_surface_digest(node_id, item)["digest"]
        for node_id, item in module.SPECS.items()
    }
    module.PRODUCT_DECISION_VALUES["writer_routing"] = original_writer + " mutation"
    try:
        after = {
            node_id: module._consumer_surface_digest(node_id, item)["digest"]
            for node_id, item in module.SPECS.items()
        }
    finally:
        module.PRODUCT_DECISION_VALUES["writer_routing"] = original_writer
    assert {node_id for node_id in before if before[node_id] != after[node_id]} == {
        node_id
        for node_id, shard_ids in module.DECISION_SHARDS_BY_NODE.items()
        if "writer-authority" in shard_ids
    }

    s3_edges_before = {
        target: module._transferred_output_contract("S3", target, scope)["digest"]
        for source, target, scope in module.EDGES
        if source == "S3"
    }
    original_task = module.SPECS["S3"]["task"]
    module.SPECS["S3"]["task"] = str(original_task) + " non-semantic metadata"
    try:
        s3_edges_after = {
            target: module._transferred_output_contract("S3", target, scope)["digest"]
            for source, target, scope in module.EDGES
            if source == "S3"
        }
    finally:
        module.SPECS["S3"]["task"] = original_task
    assert s3_edges_after == s3_edges_before


def test_acceptance_fragment_invalidation_is_owned_and_local() -> None:
    module = load_stage2_build()

    for owner_node_id, fragment in module.HUMAN_ACCEPTANCE_FRAGMENTS.items():
        owner_keys = fragment["owner_invalidation_keys"]
        local_keys = fragment["local_invalidation_keys"]
        assert set(owner_keys) <= set(module.INVALIDATION_KEYS_BY_NODE[owner_node_id])
        assert all(key.startswith("file-summary.acceptance.") for key in local_keys)
        assert fragment["invalidation_keys"] == [*owner_keys, *local_keys]


def test_invalidated_evidence_cannot_silently_reactivate() -> None:
    module = load_stage2_build()

    assert module.EVIDENCE_INVALIDATION_POLICY["silent_reactivation"] == "forbidden"
    assert module.evidence_can_reuse(
        "INVALIDATED",
        consumer_surface_matches=True,
        verification_source_matches=True,
        protected_test_matches=True,
    ) is False
    assert module.evidence_can_reuse(
        "VERIFIED",
        consumer_surface_matches=True,
        verification_source_matches=True,
        protected_test_matches=True,
    ) is True
    assert module.evidence_can_reuse(
        "VERIFIED",
        consumer_surface_matches=False,
        verification_source_matches=True,
        protected_test_matches=True,
    ) is False
    for state in ("PENDING", "BLOCKED", "REJECTED", "NOT_BOUND"):
        assert module.evidence_can_reuse(
            state,
            consumer_surface_matches=True,
            verification_source_matches=True,
            protected_test_matches=True,
        ) is False

    ledger = module.load_evidence_state_ledger()
    module.validate_evidence_state_ledger(ledger)
    assert module.evidence_record_can_reuse(module.current_evidence_record("K", ledger), module.NODES["K"])

    editable_pointer = copy.deepcopy(ledger)
    editable_pointer["entries"]["K"]["current_evidence_id"] = editable_pointer["entries"]["K"]["history"][0]["evidence_id"]
    try:
        module.validate_evidence_state_ledger(editable_pointer)
    except RuntimeError as error:
        assert "append-only history" in str(error)
    else:
        raise AssertionError("editable current pointer must be rejected")

    invalidated = copy.deepcopy(ledger)
    history = invalidated["entries"]["K"]["history"]
    previous = history[-1]
    event = {
        "seq": len(history) + 1,
        "event_id": "EVT-K-INVALIDATED-NEGATIVE-PROOF",
        "evidence_id": previous["evidence_id"],
        "from_state": previous["to_state"],
        "to_state": "INVALIDATED",
        "supersedes": previous["evidence_id"],
        "prev_event_digest": previous["event_digest"],
        "consumer_surface_digest": previous["consumer_surface_digest"],
        "verification_source_digest": previous["verification_source_digest"],
        "protected_test_digest": previous["protected_test_digest"],
        "reason": "synthetic negative proof",
    }
    event["event_digest"] = "sha256:" + hashlib.sha256(
        json.dumps(event, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    history.append(event)
    with pytest.raises(RuntimeError, match="no current accepted evidence"):
        module.validate_evidence_state_ledger(invalidated)


def test_invalidated_evidence_id_cannot_reactivate_through_verified_intermediate() -> None:
    module = load_stage2_build()
    ledger = module.load_evidence_state_ledger()
    invalidated = copy.deepcopy(ledger)
    history = invalidated["entries"]["K"]["history"]
    previous = history[-1]

    def append_event(**fields: object) -> dict[str, object]:
        event = {
            "seq": len(history) + 1,
            "event_id": f"EVT-K-NEGATIVE-{len(history) + 1}",
            "prev_event_digest": history[-1]["event_digest"],
            **fields,
        }
        event["event_digest"] = "sha256:" + hashlib.sha256(
            json.dumps(event, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        history.append(event)
        return event

    append_event(
        evidence_id=previous["evidence_id"],
        from_state="ACCEPTED",
        to_state="INVALIDATED",
        supersedes=previous["evidence_id"],
        consumer_surface_digest=previous["consumer_surface_digest"],
        verification_source_digest=previous["verification_source_digest"],
        protected_test_digest=previous["protected_test_digest"],
        reason="synthetic tombstone",
    )
    append_event(
        evidence_id=previous["evidence_id"],
        from_state="INVALIDATED",
        to_state="VERIFIED",
        supersedes=previous["evidence_id"],
        consumer_surface_digest=previous["consumer_surface_digest"],
        verification_source_digest=previous["verification_source_digest"],
        protected_test_digest=previous["protected_test_digest"],
    )

    with pytest.raises(RuntimeError, match="invalidated evidence identity reused"):
        module.validate_evidence_state_ledger(invalidated)


def test_human_workspaces_match_fragment_policy_and_hashes() -> None:
    module = load_stage2_build()

    for owner_node_id, fragment in module.HUMAN_ACCEPTANCE_FRAGMENTS.items():
        contract = ROOT / fragment["contract_path"]
        logical_workspace = ROOT / fragment["human_workspace_path"]
        assert not logical_workspace.name.startswith("未-")
        workspace = logical_workspace.with_name(f"未-{logical_workspace.name}")
        binding = workspace / "binding.md"
        checklist = workspace / "checklist.md"
        contract_text = contract.read_text(encoding="utf-8")
        binding_text = binding.read_text(encoding="utf-8")
        checklist_text = checklist.read_text(encoding="utf-8")
        invalidation_line = ", ".join(fragment["invalidation_keys"])

        assert f"- Invalidation keys: {invalidation_line}" in contract_text
        assert f"- Human acceptance workspace: {logical_workspace.relative_to(ROOT)}" in contract_text
        assert f"- Human checklist: {logical_workspace.relative_to(ROOT)}/checklist.md" in binding_text
        assert f"- 人工验收绑定：{logical_workspace.relative_to(ROOT)}/binding.md" in checklist_text
        assert "未-" not in contract_text
        assert "未-" not in binding_text
        assert "未-" not in checklist_text
        assert f"- Contract SHA-256: {hashlib.sha256(contract.read_bytes()).hexdigest()}" in binding_text
        assert f"- Checklist SHA-256: {hashlib.sha256(checklist.read_bytes()).hexdigest()}" in binding_text

        expected_blocking = owner_node_id in {"O1", "O5", "DB"}
        assert module.NODES[owner_node_id]["acceptance_lane"]["blocking"] is expected_blocking
        if owner_node_id == "K":
            assert "| H-01 |" in contract_text
            assert "| Human | No |" in contract_text
            assert "| H-01 | 产品体验验收负责人 | No |" in binding_text
            assert "- 是否阻塞发布：否（机器门禁为阻断权威）" in checklist_text
