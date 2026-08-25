from __future__ import annotations

import copy
import hashlib
import json
import os
import socket
import subprocess
import urllib.request
from pathlib import Path
from typing import Any

import pytest

from openclaw_app.services.production_reconciliation_planner import (
    PlannerValidationError,
    canonical_plan_json,
    plan_production_reconciliation,
)


SOURCE_SHA = "a" * 40
PREVIOUS_SHA = "b" * 40
OTHER_SHA = "d" * 40
RELEASE_BASE = "/srv/openclaw/releases"
CURRENT_POINTER = "/srv/openclaw/current"
TARGET_RELEASE_ID = f"openclaw-stage2-{SOURCE_SHA}"
PREVIOUS_RELEASE_ID = f"openclaw-stage2-{PREVIOUS_SHA}"
TARGET_ROOT = f"{RELEASE_BASE}/{TARGET_RELEASE_ID}"
PREVIOUS_ROOT = f"{RELEASE_BASE}/{PREVIOUS_RELEASE_ID}"
PREVIOUS_MANIFEST_SHA = "c" * 64


def _manifest_without_digest(
    *,
    source_sha: str = SOURCE_SHA,
    previous_sha: str = PREVIOUS_SHA,
    previous_manifest_sha: str = PREVIOUS_MANIFEST_SHA,
    files: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": "production-release-manifest.v1",
        "source": {"git_sha": source_sha, "git_clean": True},
        "target": {
            "root": ".",
            "files": files
            or [
                {
                    "path": "openclaw_app/services/stage2_runtime.py",
                    "sha256": "1" * 64,
                    "mode": "100644",
                },
                {
                    "path": "deploy/systemd/user/openclaw-stage2.service",
                    "sha256": "2" * 64,
                    "mode": "100644",
                },
            ],
        },
        "previous_release_identity": {
            "git_sha": previous_sha,
            "manifest_sha256": previous_manifest_sha,
        },
    }


def _with_manifest_digest(manifest: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(manifest)
    result.pop("manifest_sha256", None)
    canonical = json.dumps(result, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    result["manifest_sha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return result


def _release_identity(
    *,
    release_id: str,
    git_sha: str,
    root: str,
    manifest_sha256: str,
) -> dict[str, str]:
    return {
        "release_id": release_id,
        "git_sha": git_sha,
        "root": root,
        "manifest_sha256": manifest_sha256,
    }


def _request() -> dict[str, Any]:
    manifest = _with_manifest_digest(_manifest_without_digest())
    previous = _release_identity(
        release_id=PREVIOUS_RELEASE_ID,
        git_sha=PREVIOUS_SHA,
        root=PREVIOUS_ROOT,
        manifest_sha256=PREVIOUS_MANIFEST_SHA,
    )
    return {
        "operation": "activate",
        "source": {"git_sha": SOURCE_SHA},
        "layout": {
            "release_base": RELEASE_BASE,
            "current_pointer": CURRENT_POINTER,
        },
        "target_release": {
            "release_id": TARGET_RELEASE_ID,
            "git_sha": SOURCE_SHA,
            "root": TARGET_ROOT,
            "manifest": manifest,
        },
        "pointer": {
            "expected": copy.deepcopy(previous),
            "observed": copy.deepcopy(previous),
        },
        "previous_release": {
            **previous,
            "manifest_schema": "production-release-manifest.v1",
            "rollback_compatible": True,
        },
        "known_releases": [],
        "user_systemd": {
            "enabled": False,
            "units": [],
            "actions": [],
        },
        "observation": {
            "window_seconds": 300,
            "signals": ["health", "readiness"],
        },
    }


def _assert_code(request: dict[str, Any], code: str) -> None:
    with pytest.raises(PlannerValidationError) as caught:
        plan_production_reconciliation(request)
    assert caught.value.code == code


def test_valid_activation_plan_has_canonical_ordered_planned_stages() -> None:
    plan = plan_production_reconciliation(_request())

    assert set(plan) == {
        "schema_version",
        "plan_id",
        "operation",
        "source",
        "target_release",
        "expected_current",
        "preflight",
        "steps",
        "external_actions",
        "redaction",
    }
    assert plan["schema_version"] == "production-reconciliation-plan.v1"
    assert plan["source"] == {"git_sha": SOURCE_SHA}
    assert plan["target_release"]["release_id"] == TARGET_RELEASE_ID
    assert plan["target_release"]["root"] == TARGET_ROOT
    assert [step["id"] for step in plan["steps"]] == [
        "manifest_preflight",
        "pointer_cas",
        "atomic_switch",
        "user_systemd",
        "same_round_readback",
        "observation",
        "rollback",
    ]
    assert plan["steps"][0]["effect"] == "none"
    assert all(step["effect"] == "planned_only" for step in plan["steps"][1:])
    assert plan["external_actions"] == []
    assert canonical_plan_json(plan).endswith("}")
    assert "\n" not in canonical_plan_json(plan)


def test_rollback_is_a_plan_for_the_same_non_executing_pipeline() -> None:
    request = _request()
    request["operation"] = "rollback"

    plan = plan_production_reconciliation(request)

    assert plan["operation"] == "rollback"
    assert [step["id"] for step in plan["steps"]] == [
        "manifest_preflight",
        "pointer_cas",
        "atomic_switch",
        "user_systemd",
        "same_round_readback",
        "observation",
        "rollback",
    ]
    assert all(step["effect"] in {"none", "planned_only"} for step in plan["steps"])
    assert plan["external_actions"] == []


@pytest.mark.parametrize(
    "bad_sha",
    [
        "a" * 7,
        "A" * 40,
        "g" * 40,
        "refs/heads/main",
        "",
    ],
)
def test_source_identity_requires_a_lowercase_full_git_sha(bad_sha: str) -> None:
    request = _request()
    request["source"]["git_sha"] = bad_sha

    _assert_code(request, "SOURCE_SHA_INVALID")


@pytest.mark.parametrize(
    "unsafe_base",
    [
        "/",
        "/srv",
        "/home",
        "/srv/../releases",
        "/srv/openclaw/releases\\candidate",
        "relative/releases",
        "/srv/openclaw/releases/./candidate",
    ],
)
def test_release_layout_rejects_unsafe_or_broad_paths(unsafe_base: str) -> None:
    request = _request()
    request["layout"]["release_base"] = unsafe_base

    _assert_code(request, "PATH_UNSAFE")


def test_current_pointer_must_be_a_safe_sibling_of_release_base() -> None:
    request = _request()
    request["layout"]["current_pointer"] = "/srv/openclaw/releases/current"

    _assert_code(request, "PATH_UNSAFE")


@pytest.mark.parametrize(
    "bad_manifest_path",
    [
        "../outside.py",
        "/absolute.py",
        "runtime/state.json",
        "state/worker.sqlite3",
        "secrets/token.txt",
        "service\\unit",
    ],
)
def test_manifest_preflight_rejects_unsafe_mutable_runtime_or_secret_paths(
    bad_manifest_path: str,
) -> None:
    request = _request()
    manifest = request["target_release"]["manifest"]
    manifest["target"]["files"][0]["path"] = bad_manifest_path
    request["target_release"]["manifest"] = _with_manifest_digest(manifest)

    _assert_code(request, "MANIFEST_INVALID")


def test_manifest_preflight_requires_clean_matching_identity_and_inventory() -> None:
    request = _request()
    request["target_release"]["manifest"]["source"]["git_clean"] = False
    request["target_release"]["manifest"] = _with_manifest_digest(
        request["target_release"]["manifest"]
    )

    _assert_code(request, "MANIFEST_INVALID")

    request = _request()
    request["target_release"]["manifest"]["source"]["git_sha"] = PREVIOUS_SHA
    request["target_release"]["manifest"] = _with_manifest_digest(
        request["target_release"]["manifest"]
    )

    _assert_code(request, "MANIFEST_INVALID")


def test_target_release_id_and_root_must_be_bound_to_the_full_sha() -> None:
    request = _request()
    request["target_release"]["release_id"] = f"openclaw-stage2-{PREVIOUS_SHA}"

    _assert_code(request, "SOURCE_ROOT_MISMATCH")

    request = _request()
    request["target_release"]["root"] = f"{RELEASE_BASE}/candidate"

    _assert_code(request, "SOURCE_ROOT_MISMATCH")


def test_pointer_cas_rejects_a_stale_observed_current_pointer() -> None:
    request = _request()
    request["pointer"]["observed"]["release_id"] = f"openclaw-stage2-{OTHER_SHA}"

    _assert_code(request, "POINTER_CAS_CONFLICT")


@pytest.mark.parametrize(
    "mutation",
    [
        lambda request: request.pop("previous_release"),
        lambda request: request["previous_release"].pop("root"),
        lambda request: request["previous_release"].update({"manifest_sha256": "bad"}),
        lambda request: request["previous_release"].update({"git_sha": OTHER_SHA}),
    ],
)
def test_previous_release_is_required_complete_and_identity_bound(mutation: Any) -> None:
    request = _request()
    mutation(request)

    _assert_code(request, "PREVIOUS_RELEASE_INVALID")


@pytest.mark.parametrize(
    "mutation",
    [
        lambda request: request["previous_release"].update({"rollback_compatible": False}),
        lambda request: request["previous_release"].update(
            {"manifest_schema": "production-release-manifest.v0"}
        ),
        lambda request: request["previous_release"].pop("rollback_compatible"),
    ],
)
def test_rollback_compatibility_is_explicit_and_fail_closed(mutation: Any) -> None:
    request = _request()
    mutation(request)

    _assert_code(request, "ROLLBACK_INCOMPATIBLE")


def test_identity_collision_is_rejected_before_planning() -> None:
    request = _request()
    request["known_releases"] = [
        {
            "release_id": TARGET_RELEASE_ID,
            "git_sha": OTHER_SHA,
            "root": TARGET_ROOT,
        }
    ]

    _assert_code(request, "IDENTITY_COLLISION")


def test_explicit_user_systemd_steps_have_no_commands_or_execution_receipts() -> None:
    request = _request()
    request["user_systemd"] = {
        "enabled": True,
        "units": ["openclaw-stage2.service"],
        "actions": ["daemon-reload", "restart"],
    }

    plan = plan_production_reconciliation(request)
    systemd_step = next(step for step in plan["steps"] if step["id"] == "user_systemd")

    assert systemd_step["enabled"] is True
    assert systemd_step["units"] == ["openclaw-stage2.service"]
    assert systemd_step["actions"] == ["daemon-reload", "restart"]
    assert not any(key in systemd_step for key in {"command", "argv", "receipt", "status"})


def test_readback_and_observation_are_declarative_and_bounded() -> None:
    request = _request()
    request["observation"] = {
        "window_seconds": 45,
        "signals": ["health", "readiness", "route"],
    }

    plan = plan_production_reconciliation(request)
    readback = next(step for step in plan["steps"] if step["id"] == "same_round_readback")
    observation = next(step for step in plan["steps"] if step["id"] == "observation")

    assert readback["effect"] == "planned_only"
    assert observation["window_seconds"] == 45
    assert observation["signals"] == ["health", "readiness", "route"]
    assert "url" not in json.dumps(plan, sort_keys=True).lower()
    assert "response" not in json.dumps(plan, sort_keys=True).lower()


def test_canonical_json_is_sorted_compact_and_key_order_idempotent() -> None:
    plan = plan_production_reconciliation(_request())
    reordered = {key: plan[key] for key in reversed(list(plan))}

    first = canonical_plan_json(plan)
    second = canonical_plan_json(reordered)

    assert first == second
    assert first == json.dumps(plan, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    assert "\n" not in first
    assert not first.endswith("\n")


def test_output_is_redacted_and_contains_no_manifest_bytes_commands_or_secrets() -> None:
    plan = plan_production_reconciliation(_request())
    serialized = canonical_plan_json(plan).lower()

    assert "stage2_runtime.py" not in serialized
    assert "deploy/systemd/user" not in serialized
    assert "command" not in serialized
    assert "ssh" not in serialized
    assert "feishu" not in serialized
    assert "token" not in serialized
    assert plan["redaction"] == {
        "secret_values_emitted": False,
        "manifest_file_bytes_emitted": False,
        "volatile_values_emitted": False,
    }


def test_secret_bearing_input_is_rejected_without_echoing_the_secret() -> None:
    request = _request()
    secret = "synthetic-planner-secret-value"
    request["api_token"] = secret

    with pytest.raises(PlannerValidationError) as caught:
        plan_production_reconciliation(request)

    assert caught.value.code == "SECRET_DISCLOSURE"
    assert secret not in str(caught.value)


def test_repeated_planning_is_idempotent_and_does_not_mutate_input() -> None:
    request = _request()
    before = copy.deepcopy(request)

    first = plan_production_reconciliation(request)
    second = plan_production_reconciliation(request)

    assert request == before
    assert first == second
    assert canonical_plan_json(first) == canonical_plan_json(second)
    assert first["plan_id"] == second["plan_id"]


def test_planner_performs_no_external_or_filesystem_mutation(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("dry-run planner attempted a forbidden external action")

    for name in ("run", "Popen", "call", "check_call", "check_output"):
        monkeypatch.setattr(subprocess, name, forbidden)
    for name in ("system", "popen", "replace", "rename", "symlink", "unlink", "mkdir", "makedirs"):
        if hasattr(os, name):
            monkeypatch.setattr(os, name, forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    for name in ("write_text", "write_bytes", "mkdir", "unlink", "rmdir", "replace", "rename", "touch"):
        if hasattr(Path, name):
            monkeypatch.setattr(Path, name, forbidden)

    plan = plan_production_reconciliation(_request())

    assert plan["external_actions"] == []
    assert all(step["effect"] in {"none", "planned_only"} for step in plan["steps"])


@pytest.mark.parametrize(
    "mutation,expected_code",
    [
        (lambda request: request.update({"unexpected": True}), "SCHEMA_INVALID"),
        (lambda request: request["observation"].update({"window_seconds": 0}), "OBSERVATION_INVALID"),
        (lambda request: request["observation"].update({"signals": []}), "OBSERVATION_INVALID"),
        (lambda request: request["user_systemd"].update({"units": ["/etc/unit"]}), "SCHEMA_INVALID"),
        (lambda request: request["pointer"].update({"observed": None}), "POINTER_CAS_CONFLICT"),
    ],
)
def test_required_failure_categories_are_stable_and_fail_closed(
    mutation: Any,
    expected_code: str,
) -> None:
    request = _request()
    mutation(request)

    _assert_code(request, expected_code)
