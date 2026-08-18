from __future__ import annotations

from unittest import TestCase

from openclaw_app.services.tenant_projection import (
    ProjectionRead,
    RunOwnerFact,
    RunSummaryPage,
    TenantProjectionError,
    TenantProjectionService,
)


TENANT_A = "618ff8c4-cc5a-4034-a2c5-226e3ad6cd37"
TENANT_B = "775e0c03-febc-4a39-8ad0-3e18bb8a6d45"


class _OwnerAccessor:
    def __init__(self) -> None:
        self.facts = {
            "run_a": RunOwnerFact(TENANT_A, "rev-a1"),
            "run_b": RunOwnerFact(TENANT_B, "rev-b1"),
        }
        self.calls: list[str] = []

    def resolve_run_owner(self, public_run_id: str) -> RunOwnerFact | None:
        self.calls.append(public_run_id)
        return self.facts.get(public_run_id)


class _Reader:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []
        self.base_query_count = 1
        self.section_query_count = 2

    def dashboard_summary(self, tenant_id: str) -> ProjectionRead:
        self.calls.append(("dashboard", tenant_id))
        return ProjectionRead({"runCount": 1}, f"dashboard-{tenant_id}", 1)

    def list_run_summaries(
        self,
        tenant_id: str,
        *,
        cursor: str | None,
        page_size: int,
        search: str,
    ) -> RunSummaryPage:
        self.calls.append(("runs", tenant_id, cursor, page_size, search))
        return RunSummaryPage(
            items=(
                {
                    "publicRunId": "run_a" if tenant_id == TENANT_A else "run_b",
                    "title": f"tenant-{tenant_id}",
                    "status": "completed",
                },
            ),
            next_cursor="next-page" if cursor is None else None,
            revision=f"runs-{tenant_id}",
            query_count=1,
        )

    def run_base_detail(self, tenant_id: str, public_run_id: str) -> ProjectionRead:
        self.calls.append(("base", tenant_id, public_run_id))
        revision = "rev-a1" if tenant_id == TENANT_A else "rev-b1"
        return ProjectionRead({"title": f"{tenant_id}:{public_run_id}", "status": "completed"}, revision, self.base_query_count)

    def run_section(self, tenant_id: str, public_run_id: str, section: str) -> ProjectionRead:
        self.calls.append(("section", tenant_id, public_run_id, section))
        revision = "rev-a1" if tenant_id == TENANT_A else "rev-b1"
        return ProjectionRead({"items": [{"label": f"{tenant_id}:{section}"}]}, revision, self.section_query_count)


class TenantProjectionServiceTests(TestCase):
    def setUp(self) -> None:
        self.owner = _OwnerAccessor()
        self.reader = _Reader()
        self.service = TenantProjectionService(self.reader, self.owner)

    def test_base_is_owner_plus_one_read_and_does_not_load_sections(self) -> None:
        response = self.service.run_base(TENANT_A, "run_a")
        self.assertEqual(response.query_count, 2)
        self.assertEqual(response.payload["base"]["title"], f"{TENANT_A}:run_a")
        self.assertEqual(response.payload["availableSections"], ["decisions", "outputs", "sources"])
        self.assertEqual(self.reader.calls, [("base", TENANT_A, "run_a")])

    def test_section_is_lazy_and_cache_key_is_tenant_run_section_revision_and_scope(self) -> None:
        base = self.service.run_base(TENANT_A, "run_a")
        self.assertFalse(base.cache_hit)
        self.assertFalse(any(call[0] == "section" for call in self.reader.calls))

        first = self.service.run_section(TENANT_A, "run_a", "sources")
        second = self.service.run_section(TENANT_A, "run_a", "sources")
        admin = self.service.run_section(TENANT_A, "run_a", "sources", scope="admin")
        self.assertFalse(first.cache_hit)
        self.assertTrue(second.cache_hit)
        self.assertFalse(admin.cache_hit)
        self.assertEqual(first.query_count, 3)
        self.assertEqual(second.query_count, 1)
        self.assertEqual(sum(call[0] == "section" for call in self.reader.calls), 2)

        self.owner.facts["run_a"] = RunOwnerFact(TENANT_A, "rev-a2")
        with self.assertRaises(TenantProjectionError) as raised:
            self.service.run_section(TENANT_A, "run_a", "sources")
        self.assertEqual(raised.exception.code, "projection_revision_conflict")

    def test_cross_tenant_run_is_indistinguishable_from_missing_and_never_read(self) -> None:
        with self.assertRaises(TenantProjectionError) as raised:
            self.service.run_base(TENANT_A, "run_b")
        self.assertEqual(raised.exception.code, "resource_not_found")
        self.assertEqual(self.reader.calls, [])

    def test_query_budgets_are_enforced(self) -> None:
        self.reader.base_query_count = 2
        with self.assertRaises(TenantProjectionError) as raised:
            self.service.run_base(TENANT_A, "run_a")
        self.assertEqual(raised.exception.code, "projection_contract_violation")

        self.reader.base_query_count = 1
        self.reader.section_query_count = 3
        with self.assertRaises(TenantProjectionError) as raised:
            self.service.run_section(TENANT_A, "run_a", "decisions")
        self.assertEqual(raised.exception.code, "projection_contract_violation")

    def test_runs_are_paginated_tenant_summaries_only(self) -> None:
        response = self.service.runs(TENANT_A, cursor=None, page_size=20, search="draft")
        self.assertEqual(response.payload["items"][0]["publicRunId"], "run_a")
        self.assertEqual(response.payload["nextCursor"], "next-page")
        self.assertEqual(self.reader.calls, [("runs", TENANT_A, None, 20, "draft")])

    def test_forbidden_internal_fields_and_base_links_fail_closed(self) -> None:
        self.reader.run_base_detail = lambda tenant_id, run_id: ProjectionRead(  # type: ignore[method-assign]
            {"record_id": "rec-secret", "url": "https://example.feishu.cn/base/secret"},
            "rev-a1",
            1,
        )
        with self.assertRaises(TenantProjectionError) as raised:
            self.service.run_base(TENANT_A, "run_a")
        self.assertEqual(raised.exception.code, "projection_contract_violation")

    def test_invalid_tenant_and_unknown_section_fail_before_reader(self) -> None:
        for tenant in ("", "0", "101", "tenant-a", "-1"):
            with self.assertRaises(TenantProjectionError):
                self.service.dashboard(tenant)
        with self.assertRaises(TenantProjectionError) as raised:
            self.service.run_section(TENANT_A, "run_a", "all-nine-tables")
        self.assertEqual(raised.exception.code, "resource_not_found")
