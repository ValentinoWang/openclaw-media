from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts/qa/build_candidate_topic_backfill.py"
spec = importlib.util.spec_from_file_location("build_candidate_topic_backfill", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)

TENANT_1 = "618ff8c4-cc5a-4034-a2c5-226e3ad6cd37"
TENANT_2 = "718ff8c4-cc5a-4034-a2c5-226e3ad6cd38"


def _record(
    candidate: int,
    event: int,
    *,
    title: str | None = None,
    tenant_id: str = TENANT_1,
    run_id: str | None = None,
    trace_id: str | None = None,
    record_id: str | None = None,
) -> dict:
    run_id = run_id or f"run_{candidate:02d}_0001"
    trace_id = trace_id or f"trace:{candidate:02d}:{event:03d}"
    record_id = record_id or f"record_{candidate:02d}_{event:03d}"
    return {
        "record_id": record_id,
        "decision_trace_id": trace_id,
        "creation_run_id": run_id,
        "retained_in_r02": True,
        "source_row_index": candidate * 100 + event,
        "source_field_values": {
            "候选记录ID": f"wrong_candidate_{candidate:02d}",
            "候选标题": title or f"候选 {candidate}",
            "候选类型": ["activity" if candidate % 2 else "research"],
            "创作运行ID": run_id,
            "决策轨迹ID": trace_id,
            "租户ID": tenant_id,
        },
    }


def _group(
    candidate: int,
    event_count: int,
    *,
    title: str | None = None,
    tenant_id: str = TENANT_1,
    run_id: str | None = None,
    record_ids: list[str] | None = None,
    c01_id: str | None = None,
) -> dict:
    run_id = run_id or f"run_{candidate:02d}_0001"
    record_ids = record_ids or [f"record_{candidate:02d}_{event:03d}" for event in range(1, event_count + 1)]
    c01_id = c01_id or f"c01_{tenant_id[-4:]}_{candidate:02d}"
    return {
        "historical_creation_run_id": run_id,
        "candidate_id": "legacy-value-must-not-be-trusted",
        "candidate_topic_title": title or f"候选 {candidate}",
        "r02_event_count": event_count,
        "r02_record_ids": record_ids,
        "c01_link_count": 1,
        "c01_record_ids": [c01_id],
        "c01_exact_match_field": "创作运行ID",
        "c01_field_values": {"创作运行ID": run_id, "租户ID": tenant_id},
    }


def _payload(topic_sizes: tuple[int, ...] = (9, 9, 9, 9, 9, 8, 8)) -> dict:
    records: list[dict] = []
    groups: list[dict] = []
    for candidate, count in enumerate(topic_sizes, start=1):
        records.extend(_record(candidate, event) for event in range(1, count + 1))
        groups.append(_group(candidate, count))
    return {"r02_records": records, "d01_groups": groups}


def test_builds_seven_topics_and_preserves_all_sixty_one_events() -> None:
    result = module.build_backfill(_payload())
    assert result["counts"] == {"candidate_topics": 7, "decision_traces": 61}
    assert sum(topic["decision_trace_count"] for topic in result["candidate_topics"]) == 61
    assert {trace["candidate_topic_public_id"] for trace in result["decision_traces"]} == {
        f"legacy:run_{index:02d}_0001" for index in range(1, 8)
    }
    assert all(topic["tenant_id"] == TENANT_1 for topic in result["candidate_topics"])
    assert [trace["decision_sequence"] for trace in result["decision_traces"][:9]] == list(range(1, 10))


def test_same_title_never_merges_distinct_run_ids() -> None:
    payload = {
        "r02_records": [_record(1, 1, title="同名选题"), _record(2, 1, title="同名选题")],
        "d01_groups": [_group(1, 1, title="同名选题"), _group(2, 1, title="同名选题")],
    }
    assert module.build_backfill(payload)["counts"]["candidate_topics"] == 2


def test_missing_creation_run_id_blocks_instead_of_trusting_old_candidate_id() -> None:
    payload = _payload((1,))
    record = payload["r02_records"][0]
    del record["creation_run_id"]
    del record["source_field_values"]["创作运行ID"]
    with pytest.raises(module.BackfillBlocked, match="B6_BLOCKED_MISSING_CREATION_RUN_ID"):
        module.build_backfill(payload)


def test_duplicate_decision_event_identity_blocks_within_tenant() -> None:
    payload = _payload((2,))
    payload["r02_records"][1]["decision_trace_id"] = payload["r02_records"][0]["decision_trace_id"]
    payload["r02_records"][1]["source_field_values"]["决策轨迹ID"] = payload["r02_records"][0]["decision_trace_id"]
    with pytest.raises(module.BackfillBlocked, match="B6_BLOCKED_DUPLICATE_DECISION_TRACE_ID"):
        module.build_backfill(payload)


def test_same_run_and_trace_ids_in_two_tenants_do_not_merge() -> None:
    run_id = "run_shared_0001"
    trace_id = "trace:shared:001"
    record_id = "record_shared_001"
    payload = {
        "r02_records": [
            _record(1, 1, tenant_id=TENANT_1, run_id=run_id, trace_id=trace_id, record_id=record_id),
            _record(1, 1, tenant_id=TENANT_2, run_id=run_id, trace_id=trace_id, record_id=record_id),
        ],
        "d01_groups": [
            _group(1, 1, tenant_id=TENANT_1, run_id=run_id, record_ids=[record_id], c01_id="c01_tenant_1"),
            _group(1, 1, tenant_id=TENANT_2, run_id=run_id, record_ids=[record_id], c01_id="c01_tenant_2"),
        ],
    }
    result = module.build_backfill(payload)

    assert result["counts"] == {"candidate_topics": 2, "decision_traces": 2}
    assert {
        (topic["tenant_id"], topic["candidate_id"])
        for topic in result["candidate_topics"]
    } == {
        (TENANT_1, "legacy:run_shared_0001"),
        (TENANT_2, "legacy:run_shared_0001"),
    }
    assert {
        (trace["tenant_id"], trace["decision_trace_id"])
        for trace in result["decision_traces"]
    } == {
        (TENANT_1, trace_id),
        (TENANT_2, trace_id),
    }


def test_same_trace_id_in_distinct_tenants_is_tenant_scoped() -> None:
    shared_trace_id = "trace:shared:001"
    payload = {
        "r02_records": [
            _record(1, 1, tenant_id=TENANT_1, run_id="run_tenant_1_0001", trace_id=shared_trace_id),
            _record(2, 1, tenant_id=TENANT_2, run_id="run_tenant_2_0001", trace_id=shared_trace_id),
        ],
        "d01_groups": [
            _group(1, 1, tenant_id=TENANT_1, run_id="run_tenant_1_0001"),
            _group(2, 1, tenant_id=TENANT_2, run_id="run_tenant_2_0001"),
        ],
    }
    assert module.build_backfill(payload)["counts"] == {
        "candidate_topics": 2,
        "decision_traces": 2,
    }


def test_output_is_deterministic_for_input_order() -> None:
    payload = _payload((2, 1))
    reverse = {"r02_records": list(reversed(payload["r02_records"])), "d01_groups": list(reversed(payload["d01_groups"]))}
    assert module.build_backfill(payload) == module.build_backfill(reverse)


def test_sql_contract_has_identity_sequence_unique_and_rollback_guards() -> None:
    migration = (ROOT / "openclaw_app/migrations/canonical/038_candidate_topics.sql").read_text()
    rollback = (ROOT / "openclaw_app/migrations/rollback/038_candidate_topics.rollback.sql").read_text()
    assert "CREATE TABLE IF NOT EXISTS media_product.candidate_topics" in migration
    assert "B6_BLOCKED_MISSING_CREATION_RUN_ID" in migration
    assert "B6_BLOCKED_ORPHAN_DECISION_TRACE" in migration
    assert "'legacy:' ||" in migration
    assert "creation_run_id" in migration
    assert "UNIQUE (tenant_id, candidate_id, decision_sequence)" in migration
    assert "B6_BLOCKED_RUN_TENANT_CONFLICT" not in migration
    assert "CREATE UNIQUE INDEX IF NOT EXISTS creation_runs_candidate_id_unique" in migration
    assert migration.count("ON DELETE RESTRICT") >= 3
    assert "GROUP BY classified.tenant_id, classified.candidate_id" in migration
    assert "PARTITION BY candidate_title" not in migration
    assert "DROP TABLE IF EXISTS media_product.candidate_topics" in rollback
    assert "B6_BLOCKED_ROLLBACK_POST_MIGRATION_WRITE" in rollback
    assert (ROOT / "tests/fixtures/b6_candidate_topic_missing_id.sql").is_file()
