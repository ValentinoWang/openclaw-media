from __future__ import annotations

import copy
import importlib.util
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "agents-results/2026-08-15/media-c-b-stage-2-content-and-ai-document-routing"


def load_build_module():
    spec = importlib.util.spec_from_file_location("stage2_digest_bindings", BUNDLE / "build_ssot.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    original_path = sys.path.copy()
    try:
        sys.path.insert(0, str(BUNDLE))
        spec.loader.exec_module(module)
    finally:
        sys.path[:] = original_path
    return module


def test_every_node_has_a_verification_source_binding() -> None:
    module = load_build_module()

    assert set(module.VERIFICATION_SOURCE_KEYS_BY_NODE) == set(module.SPECS)
    assert all(module._verification_source_digest(node_id)["source_keys"] for node_id in module.SPECS)
    assert all(
        module.NODES[node_id]["verification_source_digest"]["verification_state"] == "DECLARED_NOT_ACCEPTED"
        for node_id in module.SPECS
    )


@pytest.mark.parametrize("field", ("inputs", "processing", "tests", "write_authority", "acceptance_authority"))
def test_consumer_surface_digest_binds_contract_field(field: str) -> None:
    module = load_build_module()
    node_id = "S3"
    original = module.SPECS[node_id][field]
    before = module._consumer_surface_digest(node_id, module.SPECS[node_id])["digest"]
    module.SPECS[node_id][field] = f"{original} mutation"
    try:
        after = module._consumer_surface_digest(node_id, module.SPECS[node_id])["digest"]
    finally:
        module.SPECS[node_id][field] = original
    assert before != after


def test_transfer_digest_binds_producer_content_and_evidence_identity() -> None:
    module = load_build_module()
    source, target, scope = "A", "A1", "specific-output"
    before = module._transferred_output_contract(source, target, scope)["digest"]

    original_output = module.SPECS[source]["output"]
    module.SPECS[source]["output"] = f"{original_output} mutation"
    try:
        content_after = module._transferred_output_contract(source, target, scope)["digest"]
    finally:
        module.SPECS[source]["output"] = original_output
    assert before != content_after

    original_source = copy.deepcopy(module.NODES[source]["evidence_identity"])
    module.NODES[source]["evidence_identity"]["observed_at"] = "synthetic-evidence-mutation"
    try:
        evidence_after = module._transferred_output_contract(source, target, scope)["digest"]
    finally:
        module.NODES[source]["evidence_identity"] = original_source
    assert before != evidence_after


def test_protected_test_digest_binds_execution_result() -> None:
    module = load_build_module()
    before = module.protected_test_identity()["digest"]
    original = copy.deepcopy(module.PROTECTED_TEST_EXECUTION_RESULT)
    module.PROTECTED_TEST_EXECUTION_RESULT["exit_code"] = 2
    module.PROTECTED_TEST_EXECUTION_RESULT["status"] = "BLOCKED"
    try:
        after = module.protected_test_identity()["digest"]
    finally:
        module.PROTECTED_TEST_EXECUTION_RESULT.clear()
        module.PROTECTED_TEST_EXECUTION_RESULT.update(original)
    assert before != after
