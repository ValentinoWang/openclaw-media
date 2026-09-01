from __future__ import annotations

from pathlib import Path

import pytest

from openclaw_app.services.feishu_service import FeishuService
from openclaw_app.services.lark_resource_hydration import (
    HydrationPayload,
    HydrationTarget,
    LarkResourceHydrationRepository,
    LarkResourceHydrationService,
    _bitable_payload,
    _docx_payload,
    _wiki_node_token,
)


WEB_BASE_URL = "https://example.feishu.cn"


def _feishu_service() -> FeishuService:
    return FeishuService(mode="knowledge_base", local_docs_dir=str(Path("/tmp") / "lark-hydration-tests"))


def test_fixed_revision_child_hydration_recovers_nested_99991400_with_bounded_jittered_backoff():
    service = _feishu_service()
    calls: list[tuple[str, str, dict[str, object]]] = []
    responses = iter(
        [
            {"data": {"document_revision_id": 42, "items": [{"block_id": "table", "block_type": 31}]}},
            RuntimeError("Feishu API returned code=99991400, msg=temporary busy"),
            {"data": {"items": [{"block_id": "cell", "block_type": 2, "text": "recovered"}]}},
        ]
    )

    def request(method: str, path: str, *, params=None, **_kwargs):
        calls.append((method, path, dict(params or {})))
        outcome = next(responses)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    service._request = request
    pauses: list[float] = []

    tree = service.hydrate_docx_child_tree(
        "doc_123",
        request_budget=3,
        retry_attempts=2,
        retry_base_delay=0.4,
        sleep=pauses.append,
        jitter=lambda: 0.5,
    )

    assert tree[0]["children"][0]["block_id"] == "cell"
    assert [method for method, _path, _params in calls] == ["GET", "GET", "GET"]
    assert [params["document_revision_id"] for _method, _path, params in calls] == [-1, 42, 42]
    assert pauses == [0.2]


def test_fixed_revision_child_hydration_stops_at_the_request_budget():
    service = _feishu_service()
    calls = 0

    def request(_method: str, _path: str, *, params=None, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return {"data": {"document_revision_id": 42, "items": [{"block_id": "table", "block_type": 31}]}}
        raise RuntimeError("Feishu API returned code=99991400, msg=temporary busy")

    service._request = request

    with pytest.raises(RuntimeError, match="request budget exhausted"):
        service.hydrate_docx_child_tree(
            "doc_123",
            request_budget=2,
            retry_attempts=3,
            retry_base_delay=0,
        )

    assert calls == 2


def test_latest_revision_lookup_is_never_retried():
    service = _feishu_service()
    calls = 0

    def request(_method: str, _path: str, **_kwargs):
        nonlocal calls
        calls += 1
        raise RuntimeError("Feishu API returned code=99991400, msg=temporary busy")

    service._request = request

    with pytest.raises(RuntimeError, match="99991400"):
        service.hydrate_docx_child_tree("doc_123", retry_attempts=3, retry_base_delay=0)

    assert calls == 1


def test_fixed_revision_child_hydration_does_not_retry_other_lark_codes():
    service = _feishu_service()
    calls = 0

    def request(_method: str, _path: str, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return {"data": {"document_revision_id": 42, "items": [{"block_id": "table", "block_type": 31}]}}
        raise RuntimeError("Feishu API returned code=99991401, msg=not retryable")

    service._request = request

    with pytest.raises(RuntimeError, match="99991401"):
        service.hydrate_docx_child_tree("doc_123", retry_attempts=3, retry_base_delay=0)

    assert calls == 2


@pytest.mark.parametrize("method", ["POST", "PUT"])
def test_document_writes_are_never_retried_for_99991400(monkeypatch, method: str):
    service = _feishu_service()
    monkeypatch.setattr(service, "_get_tenant_access_token", lambda: "token")
    calls: list[str] = []

    class Response:
        status_code = 503
        text = ""

        @staticmethod
        def json():
            return {"code": 99991400, "msg": "temporary busy"}

    def request(actual_method: str, *_args, **_kwargs):
        calls.append(actual_method)
        return Response()

    monkeypatch.setattr("openclaw_app.services.feishu_service.requests.request", request)

    with pytest.raises(RuntimeError, match="99991400"):
        service._request(method, "/docx/v1/documents/doc_123/blocks/doc_123/children")

    assert calls == [method]


def _target(obj_type="docx"):
    return HydrationTarget("tenant", "artifact_lark_123", 1, "actor", {"nodeToken": "node_token_123", "objToken": "object", "objType": obj_type, "title": "标题"})


def test_docx_payload_uses_actual_remote_block_mapping_and_read_fallback():
    payload = _docx_payload(_target(), {"root_blocks": [{"block_id": "remote-heading", "block_type": 3, "text": "小节"}, {"block_id": "remote-p", "block_type": 2, "text": "正文"}]}, "fallback", web_base_url=WEB_BASE_URL)
    assert payload.body["schemaVersion"] == "media.document.body.v1"
    assert [mapping[1] for mapping in payload.mappings] == ["docx:object:root", "remote-heading", "remote-p"]
    fallback = _docx_payload(_target(), None, "第一行\n第二行", web_base_url=WEB_BASE_URL)
    assert [mapping[1] for mapping in fallback.mappings][-2:] == ["docx:object:line:1", "docx:object:line:2"]


def test_bitable_payload_maps_every_body_block():
    payload = _bitable_payload(_target("bitable"), [{"table_id": "tbl", "name": "任务", "records": [{"record_id": "rec", "fields": {"名称": "A"}}]}], web_base_url=WEB_BASE_URL)
    assert len(payload.body["blocks"]) == len(payload.mappings) == 3
    assert payload.mappings[-1][1] == "bitable:object:table:tbl:record:rec"


class FakeRepository:
    def __init__(self): self.previous = None
    def targets(self, *_): return [_target()]
    def append_if_changed(self, _target, payload):
        current = str(payload.body)
        if current == self.previous: return "unchanged"
        self.previous = current
        return "inserted"


class FakeFeishu:
    def hydrate_docx_child_tree(self, _document_id):
        return [{"block_id": "b1", "block_type": 2, "text": "正文"}]

    def resolve_wiki_node_metadata(self, node_token):
        return {
            "node_token": node_token,
            "obj_token": "resolved-object",
            "obj_type": "docx",
            "title": "接入说明",
            "space_id": "space",
            "parent_node_token": "parent",
        }


def test_second_hydration_is_unchanged():
    service = LarkResourceHydrationService(FakeFeishu(), FakeRepository(), web_base_url=WEB_BASE_URL)
    assert (service.hydrate("tenant").inserted, service.hydrate("tenant").unchanged) == (1, 1)


def test_wiki_node_token_requires_exact_wiki_document_url():
    assert _wiki_node_token("https://example.feishu.cn/wiki/IphFw7KNni0EL7kSfIMcbWiDnhc") == "IphFw7KNni0EL7kSfIMcbWiDnhc"
    assert _wiki_node_token("https://example.feishu.cn/docx/IphFw7KNni0EL7kSfIMcbWiDnhc") == ""
    assert _wiki_node_token("not-a-url") == ""


def test_missing_resource_identity_is_resolved_from_wiki_node():
    unresolved = HydrationTarget("tenant", "onboarding_doc", 1, "actor", {"nodeToken": "node"})
    resolved = LarkResourceHydrationService(FakeFeishu(), FakeRepository(), web_base_url=WEB_BASE_URL)._resolved_target(unresolved)
    assert resolved.obj_token == "resolved-object"
    assert resolved.obj_type == "docx"
    assert resolved.lark_resource["spaceId"] == "space"


class FakeCursor:
    def __init__(self, row=None):
        self.row = row

    def fetchone(self):
        return self.row


class RecordingConnection:
    def __init__(self):
        self.queries = []
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def execute(self, query, _params=()):
        normalized = " ".join(query.split())
        self.queries.append(normalized)
        if "SELECT current_revision" in normalized:
            return FakeCursor((1,))
        return FakeCursor()

    def commit(self):
        self.committed = True


def test_hydration_finishes_batch_only_after_all_mappings_are_written():
    connection = RecordingConnection()
    repository = LarkResourceHydrationRepository(lambda: connection)
    payload = HydrationPayload(
        body={"schemaVersion": "media.document.body.v1", "blocks": []},
        mappings=(("block", "remote", "a" * 64),),
        source_url="https://example.test/wiki/node",
    )

    assert repository.append_if_changed(_target(), payload) == "inserted"

    running = next(index for index, query in enumerate(connection.queries) if "VALUES (%s,%s,'running'" in query)
    mapping = next(index for index, query in enumerate(connection.queries) if "INSERT INTO media_product.lark_document_block_mappings" in query)
    succeeded = next(index for index, query in enumerate(connection.queries) if "SET state='succeeded'" in query)
    binding = next(index for index, query in enumerate(connection.queries) if "INSERT INTO media_product.lark_document_bindings" in query)
    assert running < mapping < succeeded < binding
    assert connection.committed is True
