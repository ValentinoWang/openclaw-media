from __future__ import annotations

import unittest

from openclaw_app.services.content_os_feishu_project_board import FIELD_BINDINGS, SERVER_FIELDS, FeishuBitableProjectBoardClient
from openclaw_app.services.tenant_execution_context import bind_session_tenant_id


class FakeFeishuService:
    def __init__(self) -> None:
        self.fields = {"项目名称"}
        self.records = [{"record_id": "rec_existing", "fields": {"项目名称": "值-1", "项目ID": "internal_project_a", "租户ID": "101"}}]
        self.calls: list[tuple[str, str, dict | None, dict | None]] = []

    def _request(self, method: str, path: str, *, json_body=None, params=None):
        self.calls.append((method, path, json_body, params))
        if method == "GET" and path.endswith("/tables"):
            return {"data": {"items": [{"table_id": "tbl_projects", "name": "00_Projects_项目看板"}]}}
        if path.endswith("/fields"):
            if method == "GET":
                return {"data": {"items": [{"field_name": name} for name in sorted(self.fields)]}}
            if method == "POST":
                self.fields.add(json_body["field_name"])
                return {"data": {"field": {"field_name": json_body["field_name"]}}}
        if path.endswith("/records"):
            if method == "GET":
                return {"data": {"items": list(self.records), "has_more": False}}
            if method == "POST":
                self.records.append({"record_id": "rec_new", "fields": dict(json_body["fields"])})
                return {"data": {"record": self.records[-1]}}
        if "/records/" in path and method == "PUT":
            record_id = path.rsplit("/", 1)[1]
            target = next(item for item in self.records if item["record_id"] == record_id)
            target["fields"] = dict(json_body["fields"])
            return {"data": {"record": target}}
        raise AssertionError(f"unexpected request: {method} {path}")

    def read_bitable_record(self, app_token: str, table_id: str, record_id: str) -> dict:
        assert app_token == "BazubRWJ7a9SLRsLr4Bc8IvAnCg"
        assert table_id == "tbl_projects"
        return next(item for item in self.records if item["record_id"] == record_id)


class FakeOwnerService:
    @staticmethod
    def create_projection(resource_type: str, resource_id: str, *, session_tenant_id: str, fields: dict, writer):
        assert resource_type == "content_os.project"
        assert resource_id
        return writer({**fields, "租户ID": session_tenant_id})

    @staticmethod
    def assert_projection_read(resource_type: str, resource_id: str, *, session_tenant_id: str, fields: dict, projection_source: str):
        assert resource_type == "content_os.project"
        assert resource_id and projection_source
        assert fields.get("租户ID") == session_tenant_id
        return fields


def visible_fields() -> dict[str, str]:
    return {name: f"值-{index}" for index, name in enumerate(FIELD_BINDINGS, start=1)}


class ContentOsFeishuProjectBoardClientTests(unittest.TestCase):
    def test_creates_only_missing_v2_display_fields(self) -> None:
        service = FakeFeishuService()
        client = FeishuBitableProjectBoardClient(service, "BazubRWJ7a9SLRsLr4Bc8IvAnCg")
        client.ensure_schema()
        self.assertEqual(service.fields, set(FIELD_BINDINGS.values()) | set(SERVER_FIELDS.values()))
        created = [body["field_name"] for method, path, body, _ in service.calls if method == "POST" and path.endswith("/fields")]
        self.assertNotIn("当前状态", created)
        self.assertNotIn("项目路径", created)
        self.assertNotIn("project_id", created)

    def test_upsert_updates_one_existing_row_and_creates_one_new_row(self) -> None:
        service = FakeFeishuService()
        client = FeishuBitableProjectBoardClient(service, "BazubRWJ7a9SLRsLr4Bc8IvAnCg", tenant_owned_resources=FakeOwnerService())
        fields = visible_fields()
        with bind_session_tenant_id("101"):
            client.upsert_content_os_project("internal_project_a", fields)
        self.assertEqual(len(service.records), 1)
        self.assertEqual(service.records[0]["fields"]["项目名称"], fields["项目名称"])
        self.assertNotIn("当前状态", service.records[0]["fields"])
        next_fields = {**fields, "项目名称": "另一条项目"}
        with bind_session_tenant_id("101"):
            client.upsert_content_os_project("internal_project_b", next_fields)
        self.assertEqual(len(service.records), 2)
        self.assertEqual(service.records[1]["fields"]["项目名称"], "另一条项目")

    def test_rejects_legacy_or_extra_columns_instead_of_reusing_them(self) -> None:
        service = FakeFeishuService()
        service.fields.add("当前状态")
        client = FeishuBitableProjectBoardClient(service, "BazubRWJ7a9SLRsLr4Bc8IvAnCg")

        with self.assertRaisesRegex(Exception, "旧字段"):
            client.ensure_schema()


if __name__ == "__main__":
    unittest.main()
