from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from openclaw_app.services.media_business.runs import (
    RunsConflict,
    RunsForbidden,
    RunsInternalError,
    RunsInvalidRequest,
    RunsNotFound,
    RunsService,
)
from openclaw_app.services.media_business.foundation import TenantContext


UTC = timezone.utc
TENANT_A = "00000000-0000-4000-8000-000000000001"
TENANT_B = "00000000-0000-4000-8000-000000000002"
RUN_ID = "run_123456"
PROJECT_ID = "project_1234"
ARTIFACT_ID = "artifact_1234"
BASE_TIME = datetime(2026, 8, 5, 1, 0, tzinfo=UTC)


class FakeResult:
    def __init__(self, value: Any) -> None:
        self.value = value

    def fetchone(self) -> Any:
        if isinstance(self.value, list):
            return self.value[0] if self.value else None
        return self.value

    def fetchall(self) -> list[Any]:
        if isinstance(self.value, list):
            return list(self.value)
        return []


class FakeConnection:
    def __init__(self, responses: list[Any]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.commits = 0

    def execute(self, query: str, params: tuple[Any, ...] = ()) -> FakeResult:
        self.calls.append((query, params))
        if not self.responses:
            raise AssertionError("unexpected database call")
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return FakeResult(response)

    def commit(self) -> None:
        self.commits += 1


def factory_for(connection: FakeConnection):
    @contextmanager
    def factory():
        yield connection

    return factory


def service_for(connection: FakeConnection, *, id_factory=None, revision_executor=None) -> RunsService:
    return RunsService(
        factory_for(connection),
        cursor_secret=b"b05-test-cursor-secret",
        id_factory=id_factory,
        revision_executor=revision_executor,
    )


def context_for(tenant_id: str = TENANT_A) -> TenantContext:
    return TenantContext(tenant_id=tenant_id, user_public_id="user_1234")


def run_row(
    public_id: str = RUN_ID,
    revision: int = 2,
    *,
    updated_at: datetime = BASE_TIME,
    available_sections: list[str] | None = None,
) -> tuple[Any, ...]:
    return (
        public_id,
        revision,
        {
            "title": "A creation run",
            "entrypoint": "selfmedia_creation",
            "status": "completed",
            "availableSections": available_sections if available_sections is not None else ["sources", "decisions", "outputs"],
            "publicProjectId": PROJECT_ID,
        },
        BASE_TIME - timedelta(hours=1),
        updated_at,
    )


def artifact_row(public_id: str = ARTIFACT_ID, revision: int = 1) -> tuple[Any, ...]:
    return (
        public_id,
        PROJECT_ID,
        "creation_document",
        "internal",
        revision,
        BASE_TIME,
        "not_applicable",
    )


def test_list_runs_is_tenant_scoped_and_uses_an_opaque_cursor() -> None:
    connection = FakeConnection(
        [
            [
                run_row(updated_at=BASE_TIME),
                run_row(public_id="run_234567", updated_at=BASE_TIME - timedelta(minutes=1)),
                run_row(public_id="run_345678", updated_at=BASE_TIME - timedelta(minutes=2)),
            ]
        ]
    )
    response = service_for(connection).list_runs(context_for(), page_size=2)

    assert response["schemaVersion"] == "media_web_business_pages_v2"
    assert response["revision"] == 2
    assert [item["publicRunId"] for item in response["items"]] == [RUN_ID, "run_234567"]
    assert response["nextCursor"]
    assert "tenant_id" not in json.dumps(response)
    assert connection.calls[0][1][0] == TENANT_A
    assert "media_product.creation_runs" in connection.calls[0][0]
    assert "sqlite" not in connection.calls[0][0].lower()
    assert "mediavault" not in connection.calls[0][0].lower()


def test_list_runs_escapes_search_wildcards_and_validates_page_size() -> None:
    connection = FakeConnection([[]])
    service_for(connection).list_runs(context_for(), page_size=7, search="50%_match")

    params = connection.calls[0][1]
    assert params[0] == TENANT_A
    assert params[1] == "50%_match"
    assert params[2] == r"%50\%\_match%"
    assert params[3] == r"%50\%\_match%"
    assert params[-1] == 8

    with pytest.raises(RunsInvalidRequest):
        service_for(FakeConnection([])).list_runs(context_for(), page_size=0)


def test_missing_context_is_forbidden_without_a_database_call() -> None:
    connection = FakeConnection([])
    with pytest.raises(RunsForbidden):
        service_for(connection).list_runs(None)
    assert not connection.calls


def test_cursor_is_signed_for_scope_and_tenant() -> None:
    first = FakeConnection([[run_row(), run_row(public_id="run_234567")]])
    cursor = service_for(first).list_runs(context_for(), page_size=1)["nextCursor"]
    assert isinstance(cursor, str)

    second = FakeConnection([[]])
    with pytest.raises(RunsInvalidRequest):
        service_for(second).list_runs(context_for(TENANT_B), cursor=cursor, page_size=1)
    assert not second.calls

    with pytest.raises(RunsInvalidRequest):
        service_for(FakeConnection([])).list_runs(context_for(), cursor=cursor + "x", page_size=1)


def test_cross_tenant_run_is_not_found() -> None:
    connection = FakeConnection([None])
    with pytest.raises(RunsNotFound):
        service_for(connection).get_run(context_for(TENANT_B), RUN_ID)
    assert connection.calls[0][1] == (TENANT_B, RUN_ID)


def test_sections_keep_sources_decisions_and_outputs_separate() -> None:
    connection = FakeConnection(
        [
            run_row(),
            (
                RUN_ID,
                3,
                [{"sourceLabel": "approved brief", "factCount": 4}],
                ["research"],
                [
                    {
                        "kind": "brief",
                        "label": "approved brief",
                        "publicUrl": "https://example.com/brief",
                        "capturedAt": "2026-08-05T00:00:00Z",
                        "qualityStatus": "verified",
                    }
                ],
            ),
        ]
    )
    response = service_for(connection).get_run_sources(context_for(), RUN_ID)

    assert response["section"] == {
        "publicRunId": RUN_ID,
        "items": [{"sourceLabel": "approved brief", "factCount": 4}],
        "sourceKinds": ["research"],
        "evidenceRefs": [
            {
                "kind": "brief",
                "label": "approved brief",
                "publicUrl": "https://example.com/brief",
                "capturedAt": "2026-08-05T00:00:00Z",
                "qualityStatus": "verified",
            }
        ],
        "revision": 3,
    }
    assert "humanState" not in response["section"]
    assert "outputVariants" not in response["section"]


def test_public_projection_rejects_sensitive_section_fields() -> None:
    connection = FakeConnection(
        [
            run_row(),
            (RUN_ID, 1, [{"tenant_id": "secret"}], [], []),
        ]
    )
    with pytest.raises(RunsInternalError):
        service_for(connection).get_run_sources(context_for(), RUN_ID)


@pytest.mark.parametrize(
    "key",
    [
        "tenantId",
        "feishuRecordId",
        "localPath",
        "rawModelResponse",
        "accessToken",
        "tableId",
    ],
)
def test_string_value_map_rejects_camel_case_sensitive_fields(key: str) -> None:
    connection = FakeConnection(
        [
            run_row(),
            (RUN_ID, 1, [{key: "secret"}], [], []),
        ]
    )
    with pytest.raises(RunsInternalError):
        service_for(connection).get_run_sources(context_for(), RUN_ID)


def test_string_value_map_matches_if2_value_shape() -> None:
    nested = FakeConnection(
        [
            run_row(),
            (RUN_ID, 1, [{"facts": ["approved", ["not allowed"]]}], [], []),
        ]
    )
    with pytest.raises(RunsInternalError):
        service_for(nested).get_run_sources(context_for(), RUN_ID)

    nullable_array = FakeConnection(
        [
            run_row(),
            (RUN_ID, 1, [{"facts": ["approved", None]}], [], []),
        ]
    )
    with pytest.raises(RunsInternalError):
        service_for(nullable_array).get_run_sources(context_for(), RUN_ID)

    valid = FakeConnection(
        [
            run_row(),
            (RUN_ID, 1, [{"facts": ["approved", 4, True], "missing": None}], [], []),
        ]
    )
    assert service_for(valid).get_run_sources(context_for(), RUN_ID)["section"]["items"] == [
        {"facts": ["approved", 4, True], "missing": None}
    ]


def test_invalid_run_section_shape_fails_closed() -> None:
    connection = FakeConnection([[run_row(available_sections=["sources", "sources"])]])
    with pytest.raises(RunsInternalError):
        service_for(connection).list_runs(context_for())


def test_missing_section_is_explicitly_unavailable() -> None:
    connection = FakeConnection([run_row(), None])
    response = service_for(connection).get_run_sources(context_for(), RUN_ID)
    assert response["section"]["revision"] == 0
    assert response["section"]["items"] == []


def test_business_opportunity_dto_has_only_if2_fields() -> None:
    connection = FakeConnection(
        [
            [
                (
                    "opportunity_1234",
                    4,
                    {
                        "brand": "Example Brand",
                        "product": "Example Product",
                        "platform": "short_video",
                        "contentType": "review",
                        "validFrom": "2026-08-01T00:00:00Z",
                        "validUntil": None,
                        "authorizationScope": "tenant_campaigns",
                        "status": "authorized",
                    },
                    BASE_TIME,
                )
            ]
        ]
    )
    response = service_for(connection).list_business_opportunities(context_for(), page_size=20)

    assert response["revision"] == 4
    assert response["items"][0] == {
        "publicOpportunityId": "opportunity_1234",
        "brand": "Example Brand",
        "product": "Example Product",
        "platform": "short_video",
        "contentType": "review",
        "validFrom": "2026-08-01T00:00:00Z",
        "validUntil": None,
        "authorizationScope": "tenant_campaigns",
        "status": "authorized",
    }
    assert "revision" not in response["items"][0]


def test_revision_conflict_is_returned_before_writing() -> None:
    connection = FakeConnection([None, artifact_row(revision=2)])
    with pytest.raises(RunsConflict):
        service_for(connection).create_artifact_revision(
            context_for(),
            ARTIFACT_ID,
            {"expectedRevision": 1, "instruction": "Rewrite intro", "mode": "regenerate"},
            idempotency_key="b05-key-1234",
        )
    assert len(connection.calls) == 2


def test_revision_idempotency_replays_the_same_readback() -> None:
    request = {
        "publicArtifactId": ARTIFACT_ID,
        "expectedRevision": 1,
        "instruction": "Rewrite intro",
        "mode": "regenerate",
    }
    first_connection = FakeConnection(
        [
            None,
            artifact_row(revision=1),
            None,
            None,
            artifact_row(revision=2),
            None,
        ]
    )
    first = service_for(first_connection).create_artifact_revision(
        context_for(),
        ARTIFACT_ID,
        {key: request[key] for key in ("expectedRevision", "instruction", "mode")},
        idempotency_key="b05-key-1234",
    )
    checksum = hashlib.sha256(
        json.dumps(request, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()
    second_connection = FakeConnection([(checksum, json.dumps(first))])
    second = service_for(second_connection).create_artifact_revision(
        context_for(),
        ARTIFACT_ID,
        {key: request[key] for key in ("expectedRevision", "instruction", "mode")},
        idempotency_key="b05-key-1234",
    )

    assert first == second
    assert first["revision"] == 2
    assert first["item"]["currentRevision"] == 2
    assert first_connection.commits == 1
    assert len(second_connection.calls) == 1


def test_regenerate_revision_invokes_configured_executor_once_after_commit() -> None:
    calls = []
    connection = FakeConnection(
        [None, artifact_row(revision=1), None, None, artifact_row(revision=2), None]
    )
    service = service_for(
        connection,
        revision_executor=lambda context, artifact_id, revision, instruction: calls.append(
            (context.tenant_id, artifact_id, revision, instruction)
        ),
    )

    response = service.create_artifact_revision(
        context_for(), ARTIFACT_ID,
        {"expectedRevision": 1, "instruction": "Rewrite intro", "mode": "regenerate"},
        idempotency_key="b05-hook-key-1234",
    )

    assert response["item"]["currentRevision"] == 2
    assert connection.commits == 1
    assert calls == [(TENANT_A, ARTIFACT_ID, 2, "Rewrite intro")]


def test_save_as_creates_a_new_artifact_identity_and_starts_at_revision_one() -> None:
    new_artifact_id = "artifact_new1234"
    connection = FakeConnection(
        [
            None,
            artifact_row(revision=3),
            None,
            None,
            artifact_row(public_id=new_artifact_id, revision=1),
            None,
        ]
    )
    response = service_for(connection, id_factory=lambda prefix: f"{prefix}_new1234").create_artifact_revision(
        context_for(),
        ARTIFACT_ID,
        {"expectedRevision": 3, "instruction": "另存为新的创作文档", "mode": "save_as"},
        idempotency_key="b05-save-as-1",
    )

    assert response["revision"] == 1
    assert response["item"]["publicArtifactId"] == new_artifact_id
    assert response["item"]["currentRevision"] == 1
    assert connection.calls[2][1][1] == new_artifact_id
    assert connection.calls[3][1][1] == new_artifact_id
    assert connection.calls[4][1] == (TENANT_A, new_artifact_id)
    assert all(ARTIFACT_ID not in call[1] for call in connection.calls[2:5])
