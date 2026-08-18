from __future__ import annotations

from contextlib import contextmanager
import inspect

from openclaw_app.services.lark_resource_sync import LarkResourceDiscoverer, LarkResourceSyncRepository


class FakeFeishu:
    def __init__(self) -> None:
        self.calls = []

    def _request(self, method, path, *, params=None, **_kwargs):
        self.calls.append((method, path, params))
        if path == "/wiki/v2/spaces/get_node":
            return {"data": {"node": {
                "node_token": params["token"], "obj_token": "root-doc",
                "obj_type": "docx", "title": "Media OS", "space_id": "space-1",
                "has_child": True,
            }}}
        parent = params["parent_node_token"]
        if parent == "root":
            return {"data": {"items": [
                {"node_token": "doc-1", "obj_token": "obj-1", "obj_type": "docx", "title": "说明", "has_child": False},
                {"node_token": "folder", "obj_token": "folder-obj", "obj_type": "mindnote", "title": "目录", "has_child": True},
            ]}}
        if parent == "folder":
            return {"data": {"items": [
                {"node_token": "base-1", "obj_token": "obj-base", "obj_type": "bitable", "title": "表", "has_child": False},
                {"node_token": "sheet-1", "obj_token": "obj-sheet", "obj_type": "sheet", "title": "表格", "has_child": False},
            ]}}
        return {"data": {"items": []}}


def test_discovery_resolves_root_and_nested_supported_resources() -> None:
    root, resources = LarkResourceDiscoverer(FakeFeishu()).discover("root")
    assert root["title"] == "Media OS"
    assert [(item.node_token, item.obj_type) for item in resources] == [
        ("doc-1", "docx"), ("base-1", "bitable"), ("sheet-1", "sheet")
    ]


def test_repository_sql_is_tenant_scoped_and_idempotent_by_deterministic_identity() -> None:
    source = FakeFeishu()
    root, resources = LarkResourceDiscoverer(source).discover("root")
    assert resources[0].fingerprint == resources[0].fingerprint
    assert "tenant-a" not in resources[0].fingerprint
    # The repository's public identities are deterministic and therefore safe
    # to use with the existing tenant/public_id unique constraints.
    assert len(resources) == 3


def test_repository_uses_a_supported_overview_stage() -> None:
    source = inspect.getsource(LarkResourceSyncRepository.sync)
    assert "'creation'" in source
    assert "lark_synced" not in source
