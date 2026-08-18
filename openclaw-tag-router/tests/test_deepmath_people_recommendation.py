import json
import unittest
from datetime import datetime, timezone

from openclaw_app.services.deepmath_people_recommendation import (
    DeepMathPeopleRecommendation,
    DirectoryPage,
)


NOW = datetime(2026, 8, 4, 12, 0, tzinfo=timezone.utc)


def capability(directory_id, **overrides):
    value = {
        "directory_id": directory_id,
        "status": "有效",
        "confirmation_time": "2026-01-01T00:00:00Z",
        "expiry_time": "2026-09-01T00:00:00Z",
        "maintainer": "capability-maintainer",
        "responsibilities": ["数学建模"],
        "skills": ["深度学习"],
        "roles": ["research"],
        "evidence": ["内部项目记录"],
        "declared_hours": 8,
    }
    value.update(overrides)
    return value


def person(directory_id, name, department="数学部", **extra):
    record = {
        "directory_id": directory_id,
        "name": name,
        "department": department,
    }
    record.update(extra)
    return record


class FakeTransport:
    def __init__(self, pages, capabilities=None, tasks=None, calendar=None):
        self.pages = pages
        self.capabilities = [] if capabilities is None else capabilities
        self.tasks = [] if tasks is None else tasks
        self.calendar = [] if calendar is None else calendar
        self.directory_calls = []
        self.capability_calls = 0
        self.tasks_calls = 0
        self.calendar_calls = 0
        self.directory_error = None
        self.capability_error = None
        self.tasks_error = None
        self.calendar_error = None

    def get_directory_page(self, page_token):
        self.directory_calls.append(page_token)
        if self.directory_error is not None:
            raise self.directory_error
        page = self.pages[page_token]
        return page() if callable(page) else page

    def get_capability_records(self):
        self.capability_calls += 1
        if self.capability_error is not None:
            raise self.capability_error
        return self.capabilities

    def get_tasks_snapshot(self):
        self.tasks_calls += 1
        if self.tasks_error is not None:
            raise self.tasks_error
        return self.tasks

    def get_calendar_snapshot(self):
        self.calendar_calls += 1
        if self.calendar_error is not None:
            raise self.calendar_error
        return self.calendar


def one_page(*records):
    return {None: DirectoryPage(records=list(records), has_more=False)}


def good_llm(request):
    return {
        "assignments": [
            {"candidate_ref": request["candidates"][0]["candidate_ref"], "role": "DRI"}
        ]
    }


class DeepMathPeopleRecommendationTests(unittest.TestCase):
    def make_core(self, transport, llm=good_llm):
        return DeepMathPeopleRecommendation(transport, llm, clock=lambda: NOW)

    def test_multipage_directory_and_opaque_public_output(self):
        transport = FakeTransport(
            {
                None: DirectoryPage([person("dir-1", "甲")], True, "page-2"),
                "page-2": DirectoryPage([person("dir-2", "乙")], False),
            },
            capabilities=[capability("dir-1"), capability("dir-2")],
            tasks=[{"task_id": "task-1", "title": "证明"}],
            calendar=[{"event_id": "event-1", "title": "评审"}],
        )
        result = self.make_core(transport).recommend(now=NOW)

        self.assertEqual(result["status"], "recommended")
        self.assertEqual(transport.directory_calls, [None, "page-2"])
        self.assertEqual(transport.capability_calls, 1)
        self.assertEqual(transport.tasks_calls, 1)
        self.assertEqual(transport.calendar_calls, 1)
        self.assertEqual(len(result["candidates"]), 2)
        self.assertNotIn("dir-1", json.dumps(result, ensure_ascii=False))
        self.assertNotIn("dir-2", json.dumps(result, ensure_ascii=False))
        self.assertRegex(result["candidates"][0]["candidate_ref"], r"^candidate_[0-9a-f]{64}$")

    def test_directory_and_capability_sources_are_separate(self):
        directory_record = person("dir-1", "甲")
        transport = FakeTransport(
            one_page(directory_record),
            capabilities=[capability("dir-1", responsibilities=["独立能力"])],
        )

        result = self.make_core(transport).recommend(now=NOW)

        self.assertEqual(result["status"], "recommended")
        self.assertEqual(set(directory_record), {"directory_id", "name", "department"})
        self.assertEqual(result["candidates"][0]["responsibilities"], ["独立能力"])
        self.assertEqual(transport.capability_calls, 1)

    def test_embedded_capability_in_directory_is_rejected(self):
        transport = FakeTransport(
            one_page(person("dir-1", "甲", capability=capability("dir-1"))),
            capabilities=[],
        )

        result = self.make_core(transport).recommend(now=NOW)

        self.assertEqual(result["status"], "pending_manual")
        self.assertEqual(result["reason"], "embedded_capability")
        self.assertEqual(transport.capability_calls, 0)

    def test_unknown_capability_directory_id_is_rejected(self):
        transport = FakeTransport(
            one_page(person("dir-1", "甲")),
            capabilities=[capability("unknown")],
        )

        result = self.make_core(transport).recommend(now=NOW)

        self.assertEqual(result["status"], "pending_manual")
        self.assertEqual(result["reason"], "unknown_directory_id")

    def test_duplicate_capability_directory_id_is_rejected(self):
        transport = FakeTransport(
            one_page(person("dir-1", "甲")),
            capabilities=[capability("dir-1"), capability("dir-1", skills=["另一项"])],
        )

        result = self.make_core(transport).recommend(now=NOW)

        self.assertEqual(result["status"], "pending_manual")
        self.assertEqual(result["reason"], "duplicate_capability_identity")

    def test_repeated_page_token_is_pending_manual(self):
        transport = FakeTransport(
            {
                None: DirectoryPage([person("dir-1", "甲")], True, "repeat"),
                "repeat": DirectoryPage([], True, "repeat"),
            }
        )

        result = self.make_core(transport).recommend(now=NOW)

        self.assertEqual(result["status"], "pending_manual")
        self.assertEqual(result["reason"], "repeated_page_token")
        self.assertEqual(transport.directory_calls, [None, "repeat"])

    def test_missing_page_token_is_pending_manual(self):
        transport = FakeTransport({None: DirectoryPage([], True, None)})

        result = self.make_core(transport).recommend(now=NOW)

        self.assertEqual(result["status"], "pending_manual")
        self.assertEqual(result["reason"], "missing_page_token")

    def test_duplicate_identity_is_rejected(self):
        transport = FakeTransport(
            one_page(person("same-id", "甲"), person("same-id", "乙")),
            capabilities=[],
        )

        result = self.make_core(transport).recommend(now=NOW)

        self.assertEqual(result["status"], "pending_manual")
        self.assertEqual(result["reason"], "duplicate_identity")

    def test_name_lookup_is_exact_and_rejects_ambiguity_without_department_heuristics(self):
        transport = FakeTransport(
            one_page(
                person("dir-1", "同名", "A"),
                person("dir-2", "同名", "B"),
                person("dir-3", "大小写", "C"),
            ),
            capabilities=[capability("dir-1"), capability("dir-2"), capability("dir-3")],
        )
        core = self.make_core(transport)

        ambiguous = core.lookup_by_name("同名", now=NOW)
        miss = core.lookup_by_name("同名 ", now=NOW)

        self.assertEqual(ambiguous["status"], "pending_manual")
        self.assertEqual(ambiguous["reason"], "ambiguous_name")
        self.assertEqual(miss["status"], "pending_manual")
        self.assertEqual(miss["reason"], "name_not_found")

    def test_missing_multiple_pending_expired_and_incomplete_capability_are_not_eligible(self):
        cases = {
            "missing": (person("missing", "缺失"), []),
            "multiple": (
                person("multiple", "多个"),
                [capability("multiple"), capability("multiple")],
            ),
            "pending": (person("pending", "待确认"), [capability("pending", status="待审核")]),
            "expired": (
                person("expired", "已过期"),
                [capability("expired", expiry_time="2026-08-04T12:00:00Z")],
            ),
            "incomplete": (person("incomplete", "不完整"), [capability("incomplete", evidence=[])]),
        }
        for label, (record, capability_records) in cases.items():
            with self.subTest(label=label):
                result = self.make_core(
                    FakeTransport(one_page(record), capabilities=capability_records)
                ).recommend(now=NOW)
                self.assertEqual(result["status"], "pending_manual")
                if label == "multiple":
                    self.assertEqual(result["reason"], "duplicate_capability_identity")
                else:
                    self.assertEqual(result["reason"], "no_eligible_candidate")

    def test_permission_failure_is_pending_manual(self):
        transport = FakeTransport(
            one_page(person("dir-1", "甲")),
            capabilities=[capability("dir-1")],
        )
        transport.tasks_error = PermissionError("denied")

        result = self.make_core(transport).recommend(now=NOW)

        self.assertEqual(result["status"], "pending_manual")
        self.assertEqual(result["reason"], "permission_failure")
        self.assertEqual(transport.tasks_calls, 1)
        self.assertEqual(transport.calendar_calls, 0)

    def test_cross_department_is_allowed_and_department_is_only_evidence(self):
        transport = FakeTransport(
            one_page(person("other-dept", "甲", "其他部门")),
            capabilities=[capability("other-dept")],
        )
        captured = []

        def llm(request):
            captured.append(request)
            return good_llm(request)

        result = self.make_core(transport, llm).recommend(now=NOW, department="请求部门")

        self.assertEqual(result["status"], "recommended")
        self.assertEqual(result["candidates"][0]["department"], "其他部门")
        self.assertEqual(captured[0]["department_evidence"], "请求部门")

    def test_invented_llm_reference_is_pending_manual(self):
        transport = FakeTransport(
            one_page(person("dir-1", "甲")),
            capabilities=[capability("dir-1")],
        )

        def llm(_request):
            return {"assignments": [{"candidate_ref": "candidate_invented", "role": "DRI"}]}

        result = self.make_core(transport, llm).recommend(now=NOW)

        self.assertEqual(result["status"], "pending_manual")
        self.assertEqual(result["reason"], "invented_candidate_ref")
        self.assertNotIn("dir-1", json.dumps(result, ensure_ascii=False))

    def test_multiple_dri_roles_are_rejected(self):
        transport = FakeTransport(
            one_page(person("dir-1", "甲"), person("dir-2", "乙")),
            capabilities=[capability("dir-1"), capability("dir-2")],
        )

        def llm(request):
            return {
                "assignments": [
                    {"candidate_ref": request["candidates"][0]["candidate_ref"], "role": "DRI"},
                    {"candidate_ref": request["candidates"][1]["candidate_ref"], "role": "DRI"},
                ]
            }

        result = self.make_core(transport, llm).recommend(now=NOW)

        self.assertEqual(result["status"], "pending_manual")
        self.assertEqual(result["reason"], "duplicate_role")

    def test_participant_assignments_are_unbounded_and_refs_remain_unique(self):
        transport = FakeTransport(
            one_page(
                person("dir-1", "甲"),
                person("dir-2", "乙"),
                person("dir-3", "丙"),
                person("dir-4", "丁"),
            ),
            capabilities=[
                capability("dir-1"),
                capability("dir-2"),
                capability("dir-3"),
                capability("dir-4"),
            ],
        )

        def llm(request):
            refs = [candidate["candidate_ref"] for candidate in request["candidates"]]
            return {
                "assignments": [
                    {"candidate_ref": refs[0], "role": "DRI"},
                    {"candidate_ref": refs[1], "role": "Reviewer"},
                    {"candidate_ref": refs[2], "role": "Participant"},
                    {"candidate_ref": refs[3], "role": "Participant"},
                ]
            }

        result = self.make_core(transport, llm).recommend(now=NOW)

        self.assertEqual(result["status"], "recommended")
        self.assertEqual([item["role"] for item in result["recommendation"]], [
            "DRI", "Reviewer", "Participant", "Participant"
        ])

    def test_duplicate_candidate_ref_is_rejected_for_participants(self):
        transport = FakeTransport(
            one_page(person("dir-1", "甲")),
            capabilities=[capability("dir-1")],
        )

        def llm(request):
            ref = request["candidates"][0]["candidate_ref"]
            return {
                "assignments": [
                    {"candidate_ref": ref, "role": "Participant"},
                    {"candidate_ref": ref, "role": "Participant"},
                ]
            }

        result = self.make_core(transport, llm).recommend(now=NOW)

        self.assertEqual(result["status"], "pending_manual")
        self.assertEqual(result["reason"], "duplicate_candidate_ref")

    def test_human_selection_accepts_valid_change_but_rejects_modified_id(self):
        tasks = [{"task_id": "task-1", "title": "证明"}]
        transport = FakeTransport(
            one_page(person("dir-1", "甲"), person("dir-2", "乙")),
            capabilities=[capability("dir-1"), capability("dir-2")],
            tasks=tasks,
            calendar=[],
        )
        core = self.make_core(transport)
        recommendation = core.recommend(now=NOW)
        second_ref = recommendation["candidates"][1]["candidate_ref"]
        fingerprint = recommendation["workload_fingerprint"]

        changed_validly = core.validate_human_selection(
            {
                "workload_fingerprint": fingerprint,
                "assignments": [{"candidate_ref": second_ref, "role": "DRI"}],
            },
            now=NOW,
        )
        changed_to_id = core.validate_human_selection(
            {
                "workload_fingerprint": fingerprint,
                "assignments": [{"candidate_ref": "dir-2", "role": "DRI"}],
            },
            now=NOW,
        )

        self.assertEqual(changed_validly["status"], "accepted")
        self.assertEqual(changed_validly["selection"][0]["candidate_ref"], second_ref)
        self.assertEqual(changed_to_id["status"], "pending_manual")
        self.assertEqual(changed_to_id["reason"], "invented_candidate_ref")
        self.assertNotIn("dir-2", json.dumps(changed_to_id, ensure_ascii=False))

    def test_workload_drift_is_rejected(self):
        transport = FakeTransport(
            one_page(person("dir-1", "甲")),
            capabilities=[capability("dir-1")],
            tasks=[{"task_id": "task-1", "title": "原任务"}],
            calendar=[],
        )
        core = self.make_core(transport)
        recommendation = core.recommend(now=NOW)
        selection = {
            "workload_fingerprint": recommendation["workload_fingerprint"],
            "assignments": recommendation["recommendation"],
        }
        transport.tasks = [{"task_id": "task-1", "title": "已修改任务"}]

        result = core.validate_human_selection(selection, now=NOW)

        self.assertEqual(result["status"], "pending_manual")
        self.assertEqual(result["reason"], "workload_drift")

    def test_private_resolution_rereads_and_returns_exact_directory_ids(self):
        transport = FakeTransport(
            one_page(person("dir-1", "甲"), person("dir-2", "乙")),
            capabilities=[capability("dir-1"), capability("dir-2")],
            tasks=[{"task_id": "task-1", "title": "证明"}],
            calendar=[{"event_id": "event-1", "title": "评审"}],
        )
        core = self.make_core(transport)
        recommendation = core.recommend(now=NOW)
        refs = [candidate["candidate_ref"] for candidate in recommendation["candidates"]]
        selection = {
            "workload_fingerprint": recommendation["workload_fingerprint"],
            "assignments": [
                {"candidate_ref": refs[1], "role": "DRI"},
                {"candidate_ref": refs[0], "role": "Participant"},
            ],
        }

        public_validation = core.validate_human_selection(selection, now=NOW)
        private_payload = core._resolve_private_selection(selection, now=NOW)

        self.assertEqual(public_validation["status"], "accepted")
        self.assertNotIn("dir-1", json.dumps(public_validation, ensure_ascii=False))
        self.assertNotIn("dir-2", json.dumps(public_validation, ensure_ascii=False))
        self.assertEqual(private_payload["status"], "accepted")
        self.assertEqual(private_payload["assignments"], [
            {"directory_id": "dir-2", "role": "DRI"},
            {"directory_id": "dir-1", "role": "Participant"},
        ])
        self.assertEqual(transport.directory_calls, [None, None, None])
        self.assertEqual(transport.capability_calls, 3)
        self.assertEqual(transport.tasks_calls, 3)
        self.assertEqual(transport.calendar_calls, 3)

    def test_private_resolution_rejects_workload_drift(self):
        transport = FakeTransport(
            one_page(person("dir-1", "甲")),
            capabilities=[capability("dir-1")],
            tasks=[{"task_id": "task-1", "title": "原任务"}],
            calendar=[],
        )
        core = self.make_core(transport)
        recommendation = core.recommend(now=NOW)
        selection = {
            "workload_fingerprint": recommendation["workload_fingerprint"],
            "assignments": recommendation["recommendation"],
        }
        transport.tasks = [{"task_id": "task-1", "title": "已修改任务"}]

        result = core._resolve_private_selection(selection, now=NOW)

        self.assertEqual(result["status"], "pending_manual")
        self.assertEqual(result["reason"], "workload_drift")
        self.assertNotIn("dir-1", json.dumps(result, ensure_ascii=False))

    def test_negative_hours_and_unknown_llm_failure_are_pending_manual(self):
        transport = FakeTransport(
            one_page(person("dir-1", "甲")),
            capabilities=[capability("dir-1", declared_hours=-1)],
        )
        result = self.make_core(transport).recommend(now=NOW)
        self.assertEqual(result["status"], "pending_manual")
        self.assertEqual(result["reason"], "no_eligible_candidate")

        failing_transport = FakeTransport(
            one_page(person("dir-2", "乙")),
            capabilities=[capability("dir-2")],
        )

        def failing_llm(_request):
            raise RuntimeError("model unavailable")

        failed = self.make_core(failing_transport, failing_llm).recommend(now=NOW)
        self.assertEqual(failed["status"], "pending_manual")
        self.assertEqual(failed["reason"], "llm_failure")


if __name__ == "__main__":
    unittest.main()
