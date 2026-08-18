from __future__ import annotations

from openclaw_app.services.media_business.foundation import validate_body
from openclaw_app.services.media_business.lark_sync import (
    FeishuResourceSynchronizer,
    ProjectionItem,
    LarkResource,
    bitable_body,
    stable_resource_ids,
)


class FakeFeishu:
    def __init__(self):
        self.nodes = {
            "root": [{"node_token": "doc-node", "obj_token": "doc-token", "obj_type": "docx", "title": "说明"}, {"node_token": "folder", "obj_token": "folder-token", "obj_type": "folder", "title": "资料"}],
            "folder": [{"node_token": "base-node", "obj_token": "base-token", "obj_type": "bitable", "title": "业务表"}],
            "doc-node": [],
            "base-node": [],
        }

    def _request(self, method, path, *, json_body=None, params=None):
        if path.endswith("get_node"):
            return {"data": {"node": {"space_id": "space-1"}}}
        if path.endswith("/nodes"):
            return {"data": {"items": self.nodes.get(params["parent_node_token"], []), "has_more": False}}
        if "/bitable/v1/apps/base-token/tables" in path:
            return {"data": {"items": [{"table_id": "table-1", "name": "任务"}], "has_more": False}}
        raise AssertionError(path)

    def _wiki_url(self, token):
        return f"https://example.feishu.cn/wiki/{token}"

    def read_document_text(self, url):
        return {"ok": True, "text": "第一行\n第二行"}

    def list_bitable_records(self, app_token, table_id, *, page_size=500, filter_formula=""):
        return [{"record_id": "r1", "fields": {"名称": "任务一"}}]


class FakeStore:
    def __init__(self):
        self.rows = {}
        self.calls = 0

    def upsert_resource(self, resource, source_url, body, checksum):
        self.calls += 1
        project_id, artifact_id, sync_id = stable_resource_ids("tenant", resource)
        old = self.rows.get(artifact_id)
        changed = old is None or old[0] != checksum
        revision = 1 if old is None else old[1] + int(changed)
        self.rows[artifact_id] = (checksum, revision)
        return ProjectionItem(resource, project_id, artifact_id, sync_id, revision, checksum, changed)


def test_discover_recurses_and_deduplicates_resources():
    sync = FeishuResourceSynchronizer(FakeFeishu(), FakeStore(), tenant_id="tenant", parent_node_token="root")
    resources = sync.discover()
    assert [(item.obj_type, item.obj_token) for item in resources] == [("bitable", "base-token"), ("docx", "doc-token")]


def test_first_import_and_second_run_are_idempotent():
    store = FakeStore()
    sync = FeishuResourceSynchronizer(FakeFeishu(), store, tenant_id="tenant", parent_node_token="root")
    first = sync.sync(execute=True)
    second = sync.sync(execute=True)
    assert first["discovered"] == first["projected"] == 2
    assert second["projected"] == 2 and second["failed"] == []
    assert sum(1 for item in second["items"] if item["changed"]) == 0
    assert store.calls == 4


def test_bitable_projection_is_a_valid_media_body():
    resource = LarkResource("bitable", "base-token", "base-node", "业务表", "space-1", "root")
    body = bitable_body(resource, [{"table_id": "t1", "name": "任务", "records": [{"record_id": "r1"}]}])
    assert validate_body(body)["schemaVersion"] == "media.document.body.v1"
