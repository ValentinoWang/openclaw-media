from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

import pytest

from openclaw_app.services.media_business.decisions import (
    DecisionsConflict,
    DecisionsInternalError,
    DecisionsInvalidRequest,
    DecisionsNotFound,
    DecisionsService,
)
from openclaw_app.services.media_business.foundation import TenantContext


UTC = timezone.utc
NOW = datetime(2026, 8, 5, 3, 0, tzinfo=UTC)
TENANT_A = "00000000-0000-0000-0000-00000000000a"
TENANT_B = "00000000-0000-0000-0000-00000000000b"
CONTEXT_A = TenantContext(TENANT_A, "user-a")


def decision_data(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "candidate_title": "训练后恢复的 3 个判断",
        "candidate_type": "activity",
        "platform": "xiaohongshu",
        "track_name": "运动恢复",
        "decision_status": "recommended",
        "evidence_refs": [
            {
                "kind": "research",
                "label": "调研简报",
                "public_url": "https://example.test/research/brief-123456",
                "captured_at": NOW.isoformat(),
                "quality_status": "verified",
            }
        ],
        "model_recommendation": {
            "recommendation": "先做一个 30 秒验证版本",
            "rationale": "来源事实支持明确的受众问题，但不支持因果结论。",
            "confidence": 0.78,
            "source_refs": [
                {
                    "kind": "brief",
                    "label": "模型引用的调研简报",
                    "public_url": "https://example.test/research/brief-123456",
                    "captured_at": NOW.isoformat(),
                    "quality_status": "verified",
                }
            ],
        },
        "next_step": "人工确认后进入选题简报修订。",
    }
    data.update(overrides)
    return data


DECISION_ROW = (
    "decision_123456",
    1,
    decision_data(),
    NOW,
    NOW,
)


class FakeResult:
    def __init__(self, rows: list[Any], *, rowcount: int | None = None) -> None:
        self.rows = rows
        self.rowcount = rowcount

    def fetchone(self) -> Any:
        return self.rows[0] if self.rows else None

    def fetchall(self) -> list[Any]:
        return list(self.rows)


class FakeConnection:
    def __init__(
        self,
        *,
        decision_rows: list[Any] | None = None,
        signal_rows: list[Any] | None = None,
    ) -> None:
        self.decision_rows = list(decision_rows if decision_rows is not None else [DECISION_ROW])
        self.signal_rows = list(signal_rows or [])
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.idempotency: dict[tuple[str, str], tuple[str, str]] = {}
        self.commits = 0
        self.update_count = 0

    def execute(self, query: str, params: tuple[Any, ...] = ()) -> FakeResult:
        self.calls.append((query, params))
        if "COUNT(*)::bigint" in query:
            latest = max((row[1] for row in self.decision_rows), default=0)
            return FakeResult([(len(self.decision_rows), latest, NOW if self.decision_rows else None)])
        if "SELECT request_checksum, response_json" in query:
            stored = self.idempotency.get((params[1], params[2]))
            return FakeResult([stored] if stored else [])
        if "UPDATE media_product.decision_traces" in query:
            self.update_count += 1
            stored_id = params[4]
            payload = json.loads(params[1])
            current = next(row for row in self.decision_rows if row[0] == stored_id)
            updated = (current[0], params[0], payload, current[3], params[2])
            self.decision_rows = [updated if row[0] == stored_id else row for row in self.decision_rows]
            return FakeResult([], rowcount=1)
        if "INSERT INTO media_product.b04_idempotency_keys" in query:
            self.idempotency[(params[1], params[2])] = (params[3], params[4])
            return FakeResult([])
        if "FROM media_product.signal_snapshots" in query:
            return FakeResult(self.signal_rows)
        if "FROM media_product.decision_traces" in query:
            if "public_id = %s" in query:
                requested = params[1]
                return FakeResult([row for row in self.decision_rows if row[0] == requested])
            return FakeResult(self.decision_rows)
        return FakeResult([])

    def commit(self) -> None:
        self.commits += 1


def service(connection: FakeConnection) -> DecisionsService:
    @contextmanager
    def factory() -> Any:
        yield connection

    return DecisionsService(
        factory,
        cursor_secret=b"b04-test-cursor-secret",
        clock=lambda: NOW,
    )


def test_list_decisions_is_tenant_scoped_and_separates_summary_contract() -> None:
    connection = FakeConnection()
    response = service(connection).list_decisions(CONTEXT_A, page_size=20, search="恢复")

    assert response["schemaVersion"] == "media_web_business_pages_v2"
    assert response["revision"] == 1
    assert response["items"] == [
        {
            "publicDecisionId": "decision_123456",
            "candidateTitle": "训练后恢复的 3 个判断",
            "candidateType": "activity",
            "platform": "xiaohongshu",
            "trackName": "运动恢复",
            "decisionStatus": "recommended",
            "evidenceCount": 1,
            "humanConfirmedAt": None,
            "updatedAt": NOW.isoformat(),
        }
    ]
    list_query, list_params = next(
        (query, params)
        for query, params in connection.calls
        if "canonical_data::text" in query
    )
    assert "tenant_id = %s" in list_query
    assert list_params[0] == TENANT_A
    assert "tenant-a" not in json.dumps(response, ensure_ascii=False)


def test_detail_matches_if2_summary_response_contract() -> None:
    response = service(FakeConnection()).get_decision(CONTEXT_A, "decision_123456")

    assert response == {
        "schemaVersion": "media_web_business_pages_v2",
        "revision": 1,
        "decision": {
            "publicDecisionId": "decision_123456",
            "candidateTitle": "训练后恢复的 3 个判断",
            "candidateType": "activity",
            "platform": "xiaohongshu",
            "trackName": "运动恢复",
            "decisionStatus": "recommended",
            "evidenceCount": 1,
            "humanConfirmedAt": None,
            "updatedAt": NOW.isoformat(),
        },
    }


def test_missing_evidence_metadata_fails_closed() -> None:
    data = decision_data()
    data.pop("evidence_refs")
    connection = FakeConnection(
        decision_rows=[("decision_123456", 1, data, NOW, NOW)]
    )
    with pytest.raises(DecisionsInternalError, match="evidence count"):
        service(connection).get_decision(CONTEXT_A, "decision_123456")


def test_signal_list_requires_source_url_and_keeps_capture_time() -> None:
    signals = [
        (
            "signal_123456",
            2,
            {
                "kind": "hotlist",
                "platform": "douyin",
                "title": "恢复训练热榜",
                "rank": 3,
                "source_url": "https://example.test/hotlist/123456",
                "captured_at": NOW.isoformat(),
                "quality_status": "partial",
            },
            NOW,
            NOW,
            "snapshot",
        ),
        (
            "activity_123456",
            1,
            {
                "platform": "xiaohongshu",
                "title": "线下训练活动",
                "rank": 0,
                "source_url": "https://example.test/activity/123456",
                "captured_at": NOW.isoformat(),
                "quality_status": "verified",
            },
            NOW,
            NOW,
            "activity",
        ),
    ]
    response = service(FakeConnection(signal_rows=signals)).list_decision_signals(CONTEXT_A)

    assert [item["kind"] for item in response["items"]] == ["hotlist", "activity"]
    assert response["items"][0]["capturedAt"] == NOW.isoformat()
    assert response["items"][0]["sourceUrl"].startswith("https://")


def test_cursor_is_opaque_and_bound_to_tenant() -> None:
    rows = [
        DECISION_ROW,
        ("decision_234567", 1, decision_data(candidate_title="另一个候选"), NOW, NOW),
    ]
    connection = FakeConnection(decision_rows=rows)
    first = service(connection).list_decisions(CONTEXT_A, page_size=1)

    assert first["nextCursor"]
    with pytest.raises(DecisionsInvalidRequest, match="cursor"):
        service(connection).list_decisions(
            TenantContext(TENANT_B, "user-b"),
            cursor=first["nextCursor"],
            page_size=1,
        )


def test_confirmation_updates_canonical_trace_and_reads_back_new_revision() -> None:
    connection = FakeConnection()
    response = service(connection).confirm_decision(
        CONTEXT_A,
        "decision_123456",
        {
            "expectedRevision": 1,
            "decision": "confirmed",
            "reason": "来源证据完整，先验证一个小范围版本。",
        },
        idempotency_key="confirm-b04-1",
    )

    assert response["revision"] == 2
    assert response["decision"] == {
        "publicDecisionId": "decision_123456",
        "candidateTitle": "训练后恢复的 3 个判断",
        "candidateType": "activity",
        "platform": "xiaohongshu",
        "trackName": "运动恢复",
        "decisionStatus": "confirmed",
        "evidenceCount": 1,
        "humanConfirmedAt": NOW.isoformat(),
        "updatedAt": NOW.isoformat(),
    }
    assert "facts" not in response["decision"]
    assert "model" not in response["decision"]
    assert "human" not in response["decision"]
    assert connection.update_count == 1
    assert connection.commits == 1
    assert any(
        "b04_decision_confirmations" in query
        for query, _ in connection.calls
    )


def test_confirmation_replay_is_idempotent_and_different_payload_conflicts() -> None:
    connection = FakeConnection()
    confirm = {
        "expectedRevision": 1,
        "decision": "rejected",
        "reason": "证据质量不足，暂不进入生产。",
    }
    first = service(connection).confirm_decision(
        CONTEXT_A,
        "decision_123456",
        confirm,
        idempotency_key="confirm-b04-replay",
    )
    second = service(connection).confirm_decision(
        CONTEXT_A,
        "decision_123456",
        confirm,
        idempotency_key="confirm-b04-replay",
    )

    assert second == first
    assert connection.update_count == 1
    with pytest.raises(DecisionsConflict, match="Idempotency-Key"):
        service(connection).confirm_decision(
            CONTEXT_A,
            "decision_123456",
            {**confirm, "decision": "confirmed"},
            idempotency_key="confirm-b04-replay",
        )


def test_confirmation_revision_conflict_and_cross_tenant_not_found_are_explicit() -> None:
    connection = FakeConnection()
    with pytest.raises(DecisionsConflict):
        service(connection).confirm_decision(
            CONTEXT_A,
            "decision_123456",
            {
                "expectedRevision": 9,
                "decision": "confirmed",
                "reason": "旧版本不应覆盖当前决定。",
            },
            idempotency_key="confirm-b04-conflict",
        )
    with pytest.raises(DecisionsNotFound):
        service(FakeConnection(decision_rows=[])).get_decision(
            TenantContext(TENANT_B, "user-b"),
            "decision_123456",
        )


def test_missing_signal_source_fails_closed_and_error_shape_is_if2() -> None:
    missing_source = (
        "signal_123456",
        1,
        {
            "kind": "research",
            "platform": "douyin",
            "title": "没有来源链接的信号",
            "rank": 0,
            "captured_at": NOW.isoformat(),
        },
        NOW,
        NOW,
        "snapshot",
    )
    with pytest.raises(DecisionsInternalError, match="source_url"):
        service(FakeConnection(signal_rows=[missing_source])).list_decision_signals(CONTEXT_A)

    error = DecisionsNotFound()
    assert DecisionsService.error_response(error) == {
        "error": {
            "code": "resource_not_found",
            "message": "decision resource was not found",
            "field": None,
        }
    }
    assert DecisionsService.error_status(error) == 404


def test_missing_signal_rank_fails_closed() -> None:
    missing_rank = (
        "signal_123456",
        1,
        {
            "kind": "research",
            "platform": "douyin",
            "title": "missing rank signal",
            "source_url": "https://example.test/research/123456",
            "captured_at": NOW.isoformat(),
        },
        NOW,
        NOW,
        "snapshot",
    )
    with pytest.raises(DecisionsInternalError, match="rank"):
        service(FakeConnection(signal_rows=[missing_rank])).list_decision_signals(CONTEXT_A)


def test_confirmation_rejects_unknown_fields_and_oversized_reason() -> None:
    connection = FakeConnection()
    with pytest.raises(DecisionsInvalidRequest, match="unexpected field"):
        service(connection).confirm_decision(
            CONTEXT_A,
            "decision_123456",
            {"expectedRevision": 1, "decision": "confirmed", "reason": "ok", "prompt": "hidden"},
            idempotency_key="confirm-b04-extra",
        )
    with pytest.raises(DecisionsInvalidRequest, match="reason is required"):
        service(connection).confirm_decision(
            CONTEXT_A,
            "decision_123456",
            {"expectedRevision": 1, "decision": "confirmed", "reason": "x" * 2001},
            idempotency_key="confirm-b04-long",
        )


def test_idempotency_key_currently_accepts_non_alphanumeric_and_short_values() -> None:
    """SV-03 regression pin, not an endorsement of the current contract.

    decisions._validate_idempotency_key only requires a non-blank string of
    at most 200 characters -- unlike runs/tracks/documents/admin_* it does
    not enforce IF2's ``^[A-Za-z0-9_-]{8,128}$`` charset or length floor, so
    a key such as "中文键值" (non-ASCII, 4 characters) is accepted here today
    even though the same key would 400 against the strict endpoints. This
    test only pins that current behavior; per the SV-03 remediation plan it
    is deliberately not being tightened in this pass, since there is no way
    to verify the change against whatever keys are already stored in
    media_product.b04_idempotency_keys.
    """
    connection = FakeConnection()
    response = service(connection).confirm_decision(
        CONTEXT_A,
        "decision_123456",
        {
            "expectedRevision": 1,
            "decision": "confirmed",
            "reason": "来源证据完整，先验证一个小范围版本。",
        },
        idempotency_key="中文键值",
    )

    assert response["revision"] == 2
    assert connection.update_count == 1
    assert connection.commits == 1
