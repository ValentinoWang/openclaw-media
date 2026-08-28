from datetime import datetime, timezone
import unittest

from openclaw_app.services.deepmath_team_capability_schema import (
    FIELD_TYPE_MAP,
    FEISHU_PRIMARY_FIELD_NAME,
    STATUS_OPTIONS,
    TEAM_CAPABILITY_FIELDS,
    eligible_records,
    feishu_field_payload,
    feishu_record_payload,
    schema_manifest,
    validate_records,
    validate_schema,
)


NOW = datetime(2026, 8, 4, 12, 0, tzinfo=timezone.utc)


def _user(identity: str) -> list[dict[str, str]]:
    return [{"id": identity}]


def _valid_record(identity: str = "fixture-member") -> dict[str, object]:
    return {
        "成员": _user(identity),
        "职责范围": "研究实验与交付协调",
        "核心技能": "数学建模与实验设计",
        "可承担角色": "DRI；Reviewer",
        "技能证据": "已确认的近期项目记录",
        "未来7天可分配工时": 6,
        "不可用区间": "周末",
        "负荷确认时间": "2026-08-01T09:00:00+00:00",
        "负荷有效至": "2026-08-08T09:00:00+00:00",
        "记录状态": "有效",
        "维护人": _user("fixture-maintainer"),
    }


class DeepMathTeamCapabilitySchemaTest(unittest.TestCase):
    def test_schema_is_one_table_with_exact_order_and_types(self):
        validate_schema()
        manifest = schema_manifest()
        self.assertEqual(manifest["version"], 1)
        self.assertEqual(manifest["base_name"], "DeepMath Team Capability")
        self.assertEqual(manifest["feishu_primary_field"], FEISHU_PRIMARY_FIELD_NAME)
        self.assertEqual(len(manifest["tables"]), 1)
        table = manifest["tables"][0]
        self.assertEqual(table["name"], "成员能力与容量")
        self.assertEqual(
            [(field["name"], field["type"]) for field in table["fields"]],
            [
                ("成员", "user"),
                ("职责范围", "text"),
                ("核心技能", "text"),
                ("可承担角色", "text"),
                ("技能证据", "text"),
                ("未来7天可分配工时", "number"),
                ("不可用区间", "text"),
                ("负荷确认时间", "datetime"),
                ("负荷有效至", "datetime"),
                ("记录状态", "single_select"),
                ("维护人", "user"),
            ],
        )

    def test_user_fields_are_single_and_select_options_are_human_names(self):
        member = TEAM_CAPABILITY_FIELDS[0]
        status = next(field for field in TEAM_CAPABILITY_FIELDS if field.name == "记录状态")
        self.assertEqual(
            feishu_field_payload(member),
            {"field_name": "成员", "type": FIELD_TYPE_MAP["user"], "property": {"multiple": False}},
        )
        self.assertEqual(
            feishu_field_payload(status)["property"]["options"],
            [{"name": option} for option in STATUS_OPTIONS],
        )
        self.assertTrue(
            all(not option["name"].startswith("opt") for option in feishu_field_payload(status)["property"]["options"])
        )

    def test_effective_records_are_the_only_eligible_evidence(self):
        pending = {"成员": _user("fixture-pending"), "记录状态": "待确认"}
        valid = _valid_record()
        validate_records([pending, valid], now=NOW)
        self.assertEqual(eligible_records([pending, valid], now=NOW), [valid])

    def test_duplicate_member_identity_is_rejected(self):
        first = _valid_record("fixture-duplicate")
        second = _valid_record("fixture-duplicate")
        with self.assertRaisesRegex(ValueError, "duplicate"):
            validate_records([first, second], now=NOW)

    def test_ineligible_effective_records_are_rejected(self):
        expired = _valid_record()
        expired["负荷有效至"] = "2026-08-04T11:59:59+00:00"
        with self.assertRaisesRegex(ValueError, "future"):
            validate_records([expired], now=NOW)

        missing_evidence = _valid_record("fixture-missing-evidence")
        missing_evidence["技能证据"] = ""
        with self.assertRaisesRegex(ValueError, "技能证据"):
            validate_records([missing_evidence], now=NOW)

        negative_capacity = _valid_record("fixture-negative-capacity")
        negative_capacity["未来7天可分配工时"] = -1
        with self.assertRaisesRegex(ValueError, "nonnegative"):
            validate_records([negative_capacity], now=NOW)

    def test_user_cardinality_and_status_values_are_strict(self):
        multiple_members = _valid_record("fixture-multiple")
        multiple_members["成员"] = [_user("fixture-a")[0], _user("fixture-b")[0]]
        with self.assertRaisesRegex(ValueError, "exactly one"):
            validate_records([multiple_members], now=NOW)

        option_id_status = _valid_record("fixture-option-id")
        option_id_status["记录状态"] = "optStatusId"
        with self.assertRaisesRegex(ValueError, "human-facing"):
            validate_records([option_id_status], now=NOW)

    def test_record_payload_strips_user_display_copy_and_keeps_status_name(self):
        payload = feishu_record_payload(_valid_record(), now=NOW)
        self.assertEqual(payload["fields"]["成员"], [{"id": "fixture-member"}])
        self.assertEqual(payload["fields"]["维护人"], [{"id": "fixture-maintainer"}])
        self.assertEqual(payload["fields"]["记录状态"], "有效")
        self.assertNotIn("姓名", payload["fields"])


if __name__ == "__main__":
    unittest.main()
