from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from selfmedia.growth.creation_run_detail import (
    CreationRunDetailBuilder,
    CreationRunDetailError,
    CreationRunDetailExporter,
    _public_id,
)


def fixture() -> tuple[dict, dict, dict]:
    run = {
        "_record_id": "recWrite123456",
        "run_id": "run_recInternal123456",
        "entrypoint": "【创作】",
        "input_summary": "校园运动创作",
        "status": "success",
        "generation_source": "llm",
        "run_artifact_uri": "media://creation_runs/private/request.json",
        "feishu_doc_link": "https://example.test/doc/1",
    }
    sources = {
        "run": {"read_state": "available", "records": [run], "reason": "matched"},
        "activities": {
            "read_state": "available",
            "records": [{"activity_id": "recActivity123456", "title": "校园运动会", "platform_name": "抖音", "_selected": True}],
            "reason": "matched",
        },
        "assets": {
            "read_state": "available",
            "records": [{"asset_id": "asset_private", "title": "跑步素材", "platform": "抖音", "status": "ready", "_selected": True}],
            "reason": "matched",
        },
        "decision_traces": {
            "read_state": "available",
            "records": [
                {
                    "_record_id": "recTrace123456",
                    "trace_id": "trace_private",
                    "run_id": "run_recInternal123456",
                    "candidate_type": "activity",
                    "candidate_id": "recActivity123456",
                    "rank": 1,
                    "score": 94,
                    "selected": True,
                    "reason_summary": "活动与主题一致",
                    "decision_version": "creation_v2",
                }
            ],
            "reason": "matched",
        },
        "material_usage": {
            "read_state": "available",
            "records": [
                {
                    "_record_id": "recUsage123456",
                    "usage_id": "usage_private",
                    "run_id": "run_recInternal123456",
                    "asset_id": "asset_private",
                    "usage_type": "结构参考",
                    "score": 91,
                    "selected_for_final": True,
                }
            ],
            "reason": "matched",
        },
    }
    artifacts = {
        "request.json": {"entrypoint": "【创作】"},
        "retrieval_candidates.json": {"activities": []},
        "decision_trace.json": [],
        "material_usage.json": [],
        "draft_output.json": {
            "title": "校园运动会怎么拍",
            "topic": "校园体育",
            "platform": "抖音",
            "content_type": "短视频",
            "hook_3s": "第一秒进入赛场",
            "final_copy": "正文",
            "recommended_option_id": "option_internal_1",
            "script_options": [
                {
                    "option_id": "option_internal_1",
                    "title": "赛场第一视角",
                    "angle": "回到校园",
                    "platform": "抖音",
                    "content_type": "短视频",
                    "hook_3s": "第一秒进入赛场",
                    "score": 93,
                    "selected_activity_ids": ["recActivity123456"],
                }
            ],
            "storyboard": [{"time": "0-3s", "visual": "冲进赛场", "subtitle": "回来比赛"}],
            "creator_report": {
                "overview": {"recommended_topic": "校园体育"},
                "evidence_appendix": {"scoring_and_record_ids": "recActivity123456"},
            },
        },
        "validation_report.json": {"ok": True},
        "writeback_report.json": {
            "writes": [{"entity": "CreationRun", "record_id": "recWrite123456", "mode": "write", "field_count": 10, "key_field": "run_id", "key_value": "run_recInternal123456"}],
            "readback": {"creation_run_matches": {"count": 1, "record_ids": ["recWrite123456"]}},
        },
    }
    return run, sources, artifacts


def test_builds_complete_safe_detail_projection() -> None:
    run, sources, artifacts = fixture()
    builder = CreationRunDetailBuilder()

    projection = builder.build(run=run, source_payloads=sources, artifacts=artifacts, artifact_state="available")

    assert projection["schemaVersion"] == "media_creation_run_detail_v1"
    assert len(projection["sources"]) == 9
    assert len(projection["timeline"]) == 7
    assert projection["decisions"]["traces"][0]["selected"] is True
    assert projection["decisions"]["materialUsage"][0]["selectedForFinal"] is True
    assert projection["artifact"]["options"][0]["recommended"] is True
    assert "evidence_appendix" not in projection["artifact"]["creator_report"]
    output_states = {item["target"]: item["readbackState"] for item in projection["outputs"]}
    assert output_states["03_CreationRuns_创作运行"] == "matched"
    assert output_states["R01_MaterialUsage_素材使用记录"] == "not_attempted"
    assert output_states["R02_DecisionTrace_决策轨迹"] == "not_attempted"
    raw = json.dumps(projection, ensure_ascii=False).lower()
    assert "https://example.test/doc/1" not in raw
    assert "documenturl" not in raw
    for forbidden in ("/home/", "media://", "raw_prompt", "raw_response", "traceback", "record_id", "recactivity123456", "recwrite123456"):
        assert forbidden not in raw


def test_completeness_guard_rejects_missing_source_group() -> None:
    run, sources, artifacts = fixture()
    builder = CreationRunDetailBuilder()
    projection = builder.build(run=run, source_payloads=sources, artifacts=artifacts, artifact_state="available")
    projection["sources"].pop()

    with pytest.raises(CreationRunDetailError, match="source groups"):
        builder.assert_complete_and_safe(projection)


def test_live_source_group_controls_writeback_readback_state() -> None:
    run, sources, artifacts = fixture()
    artifacts["writeback_report.json"]["writes"].extend(
        [
                {"entity": "DecisionTrace", "record_id": "recTrace123456", "mode": "write", "field_count": 8, "key_field": "trace_id", "key_value": "trace_private"},
                {"entity": "MaterialUsage", "record_id": "recUsage123456", "mode": "write", "field_count": 7, "key_field": "usage_id", "key_value": "usage_private"},
        ]
    )
    builder = CreationRunDetailBuilder()

    projection = builder.build(run=run, source_payloads=sources, artifacts=artifacts, artifact_state="available")

    output_states = {item["target"]: item["readbackState"] for item in projection["outputs"]}
    assert output_states["03_CreationRuns_创作运行"] == "matched"
    assert output_states["R01_MaterialUsage_素材使用记录"] == "matched"
    assert output_states["R02_DecisionTrace_决策轨迹"] == "matched"
    for output in projection["outputs"]:
        assert output["fieldOrBlock"]
        assert output["expectedValueSummary"]
        assert output["actualValueSummary"]
        assert output["checkedAt"]

    sources["material_usage"] = {"read_state": "no_match", "records": [], "reason": "missing"}
    projection = builder.build(run=run, source_payloads=sources, artifacts=artifacts, artifact_state="available")
    output_states = {item["target"]: item["readbackState"] for item in projection["outputs"]}
    assert output_states["R01_MaterialUsage_素材使用记录"] == "mismatched"


def exporter_fixture(
    tmp_path: Path,
    *,
    decision_rows: list[dict] | None = None,
    material_usage_rows: list[dict] | None = None,
    activity_rows: list[dict] | None = None,
    write_entities: tuple[str, ...] | None = (),
) -> tuple[CreationRunDetailExporter, str, list[tuple[str, str, str]], list[str]]:
    raw_run_id = "run_test_detail_1"
    registry_keys = {
        "activities": "activity",
        "assets": "source_assets",
        "deconstructions": "material_deconstructions",
        "patterns": "creative_patterns",
        "run": "creation_runs",
        "business": "business_opportunities",
        "creators": "creator_profiles_v2",
        "material_usage": "material_usage",
        "decision_traces": "decision_trace",
    }
    urls = {key: f"https://example.test/base/app?table={key}" for key in registry_keys.values()}
    registry = {
        "tables": {
            key: {"env": {f"TEST_{key.upper()}_URL": url}}
            for key, url in urls.items()
        }
    }
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(json.dumps(registry), encoding="utf-8")
    rows_by_key = {
        "creation_runs": [
            {
                "record_id": "recRunDetail1",
                "fields": {
                    "创作运行ID": raw_run_id,
                    "入口标签": "【创作】",
                    "输入需求摘要": "按需读取测试",
                    "状态": "success",
                    "生成来源": "llm",
                "运行产物URI": "media://creation_runs/run_test_detail_1/request.json",
                    "租户ID": "00000000-0000-4000-8000-000000000101",
                },
            }
        ],
        "decision_trace": decision_rows or [],
        "material_usage": material_usage_rows or [],
        "activity": activity_rows or [],
    }
    url_to_key = {url: key for key, url in urls.items()}
    calls: list[tuple[str, str, str]] = []
    token_calls: list[str] = []

    def token_loader() -> str:
        token_calls.append("called")
        return "shared-token"

    def record_loader(url: str, *, token: str, filter_formula: str = "") -> list[dict]:
        key = url_to_key[url]
        calls.append((key, token, filter_formula))
        rows = rows_by_key.get(key, [])
        if key == "activity":
            return rows
        return [
            {**row, "fields": {**(row.get("fields") or {}), "租户ID": "00000000-0000-4000-8000-000000000101"}}
            for row in rows
        ]

    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()
    (artifact_dir / "request.json").write_text("{}", encoding="utf-8")
    if write_entities is not None:
        (artifact_dir / "writeback_report.json").write_text(
            json.dumps({"writes": [{"entity": entity} for entity in write_entities]}),
            encoding="utf-8",
        )

    class FakeVault:
        tenant_id = "00000000-0000-4000-8000-000000000101"

        def resolve_uri(self, uri: str) -> Path:
            assert uri == "media://creation_runs/run_test_detail_1/request.json"
            return artifact_dir / "request.json"

    class FakeRegistry:
        @staticmethod
        def list_all_by_tenant(tenant_id: str, *, resource_type: str, **_kwargs) -> list[object]:
            assert tenant_id == "00000000-0000-4000-8000-000000000101"
            ids = [raw_run_id] if resource_type == "media.creation_run" else []
            return [SimpleNamespace(canonical_resource_id=item) for item in ids]

    class FakeOwnerService:
        registry = FakeRegistry()

        @staticmethod
        def assert_projection_read(resource_type: str, resource_id: str, *, session_tenant_id: str, fields: dict, projection_source: str) -> dict:
            assert resource_type and resource_id and projection_source
            assert session_tenant_id == "00000000-0000-4000-8000-000000000101"
            assert fields.get("租户ID") == "00000000-0000-4000-8000-000000000101"
            return fields

    exporter = CreationRunDetailExporter(
        tenant_id="00000000-0000-4000-8000-000000000101",
        registry_path=registry_path,
        vault=FakeVault(),
        record_loader=record_loader,
        token_loader=token_loader,
        tenant_owned_resources=FakeOwnerService(),
    )
    return exporter, raw_run_id, calls, token_calls


def test_exporter_skips_relation_and_source_tables_not_declared_by_writeback(tmp_path: Path) -> None:
    exporter, raw_run_id, calls, token_calls = exporter_fixture(tmp_path)

    projection = exporter.export(_public_id("run", raw_run_id))

    assert token_calls == ["called"]
    assert [key for key, _, _ in calls] == ["creation_runs"]
    assert {token for _, token, _ in calls} == {"shared-token"}
    groups = {item["key"]: item for item in projection["sources"]}
    assert groups["decision_traces"]["readState"] == "not_queried"
    assert groups["material_usage"]["readState"] == "not_queried"
    for key in ("activities", "assets", "deconstructions", "patterns", "business", "creators"):
        assert groups[key]["readState"] == "not_queried"


def test_exporter_does_not_resolve_another_tenants_public_run_id(tmp_path: Path) -> None:
    exporter, _, calls, token_calls = exporter_fixture(tmp_path)

    with pytest.raises(CreationRunDetailError, match="not found"):
        exporter.export(_public_id("run", "run_owned_by_other_tenant"))

    assert calls == []
    assert token_calls == ["called"]


def test_exporter_filters_relation_tables_declared_by_writeback(tmp_path: Path) -> None:
    exporter, raw_run_id, calls, _ = exporter_fixture(
        tmp_path,
        write_entities=("DecisionTrace", "MaterialUsage"),
    )

    projection = exporter.export(_public_id("run", raw_run_id))

    assert [key for key, _, _ in calls] == ["creation_runs", "decision_trace", "material_usage"]
    assert calls[1][2] == f'CurrentValue.[创作运行ID]="{raw_run_id}"'
    assert calls[2][2] == f'CurrentValue.[创作运行ID]="{raw_run_id}"'
    groups = {item["key"]: item for item in projection["sources"]}
    assert groups["decision_traces"]["readState"] == "no_match"
    assert groups["material_usage"]["readState"] == "no_match"


def test_exporter_loads_only_the_source_group_referenced_by_decision_trace(tmp_path: Path) -> None:
    raw_run_id = "run_test_detail_1"
    exporter, _, calls, _ = exporter_fixture(
        tmp_path,
        decision_rows=[
            {
                "record_id": "recTraceDetail1",
                "fields": {
                    "决策轨迹ID": "trace_detail_1",
                    "创作运行ID": raw_run_id,
                    "候选类型": "activity",
                    "候选记录ID": "activity_detail_1",
                    "候选排序": 1,
                    "匹配分": 90,
                    "是否入选": True,
                    "入选理由摘要": "活动关联测试",
                    "决策版本": "creation_v2",
                },
            }
        ],
        activity_rows=[
            {
                "record_id": "recActivityDetail1",
                "fields": {
                    "关联ID": "activity_detail_1",
                    "标题": "测试活动",
                    "平台名称": ["抖音"],
                },
            }
        ],
        write_entities=("DecisionTrace",),
    )

    projection = exporter.export(_public_id("run", raw_run_id))

    assert [key for key, _, _ in calls] == ["creation_runs", "decision_trace", "activity"]
    groups = {item["key"]: item for item in projection["sources"]}
    assert groups["activities"]["readState"] == "available"
    assert groups["activities"]["recordCount"] == 1
    for key in ("assets", "deconstructions", "patterns", "business", "creators"):
        assert groups[key]["readState"] == "not_queried"


def test_exporter_stops_after_run_lookup_when_public_id_is_unknown(tmp_path: Path) -> None:
    exporter, _, calls, token_calls = exporter_fixture(tmp_path)

    with pytest.raises(CreationRunDetailError, match="not found"):
        exporter.export("run_unknown")

    assert token_calls == ["called"]
    assert [key for key, _, _ in calls] == ["creation_runs"]


def test_exporter_does_not_probe_relation_tables_when_writeback_report_is_missing(tmp_path: Path) -> None:
    exporter, raw_run_id, calls, _ = exporter_fixture(tmp_path, write_entities=None)

    projection = exporter.export(_public_id("run", raw_run_id))

    assert [key for key, _, _ in calls] == ["creation_runs"]
    groups = {item["key"]: item for item in projection["sources"]}
    assert groups["decision_traces"]["readState"] == "not_queried"
    assert groups["material_usage"]["readState"] == "not_queried"


@pytest.mark.parametrize("leak", ["/home/ubuntu/private.json", "media://private/raw.json", "raw_prompt", "stack trace", "record_id"])
def test_leak_guard_rejects_forbidden_output(leak: str) -> None:
    run, sources, artifacts = fixture()
    builder = CreationRunDetailBuilder()
    projection = builder.build(run=run, source_payloads=sources, artifacts=artifacts, artifact_state="available")
    projection["run"]["inputSummary"] = leak

    with pytest.raises(CreationRunDetailError, match="forbidden token"):
        builder.assert_complete_and_safe(projection)
