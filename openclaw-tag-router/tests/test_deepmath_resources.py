import unittest
from pathlib import Path

from openclaw_app.services.deepmath_resources import (
    BASE_NAME,
    CALENDAR_NAME,
    DEEP_MATH_FEISHU_ACCOUNT_ID,
    DeepMathResourceContractError,
    DeepMathResourceConfig,
    DeepMathResourceSpec,
    approval_candidate_for_resolution,
    load_resource_config,
    parse_explicit_bitable_url,
    resolve_exact_resource,
    tenant_identity_status,
)


class DeepMathResourceContractTest(unittest.TestCase):
    def test_config_is_deepmath_only(self):
        config = load_resource_config(
            Path(__file__).parents[1] / "config" / "deepmath_ceo_thinking_resources.json"
        )
        self.assertEqual(config.tenant_key, "deepmath")
        self.assertEqual(config.calendar_name, CALENDAR_NAME)

    def test_exact_one_writable_match_binds(self):
        result = resolve_exact_resource(
            "calendar",
            CALENDAR_NAME,
            [{"tenant_key": "deepmath", "name": CALENDAR_NAME, "id": "cal_deep", "writable": True}],
        )
        self.assertEqual((result.status, result.resource_id), ("bind_pending", "cal_deep"))

    def test_zero_match_is_create_pending_and_old_tenant_is_ignored(self):
        result = resolve_exact_resource(
            "base",
            BASE_NAME,
            [
                {"tenant_key": "legacy", "name": BASE_NAME, "id": "old"},
                {"tenant_key": "deepmath", "name": "Other", "id": "other"},
            ],
        )
        self.assertEqual(result.status, "create_pending")
        self.assertIsNone(result.resource_id)

    def test_multiple_exact_matches_require_selection(self):
        result = resolve_exact_resource(
            "base",
            BASE_NAME,
            [
                {"tenant_key": "deepmath", "name": BASE_NAME, "id": "one", "writable": True},
                {"tenant_key": "deepmath", "name": BASE_NAME, "id": "two", "writable": True},
            ],
        )
        self.assertEqual(result.status, "selection_required")

    def test_zero_match_creates_a_resource_creation_approval_candidate(self):
        candidate = approval_candidate_for_resolution(
            DeepMathResourceSpec("base", BASE_NAME, None, False, "create_pending", "no exact match")
        )
        self.assertEqual(
            (candidate.object_type, candidate.candidate_action, candidate.approval_status),
            ("资源", "创建", "待审批"),
        )
        self.assertFalse(candidate.requires_manual_selection)

    def test_one_writable_match_creates_a_binding_approval_candidate(self):
        candidate = approval_candidate_for_resolution(
            DeepMathResourceSpec("calendar", CALENDAR_NAME, "cal-deep", True, "bind_pending")
        )
        self.assertEqual(
            (candidate.candidate_action, candidate.resource_id, candidate.approval_status),
            ("绑定", "cal-deep", "待审批"),
        )

    def test_multiple_matches_require_manual_selection_before_approval(self):
        candidate = approval_candidate_for_resolution(
            DeepMathResourceSpec("calendar", CALENDAR_NAME, None, False, "selection_required", "multiple")
        )
        self.assertEqual(candidate.approval_status, "人工处理")
        self.assertTrue(candidate.requires_manual_selection)

    def test_non_writable_match_cannot_be_approved_for_binding(self):
        candidate = approval_candidate_for_resolution(
            DeepMathResourceSpec("calendar", CALENDAR_NAME, "cal-readonly", False, "unavailable", "read only")
        )
        self.assertEqual((candidate.approval_status, candidate.resource_id), ("人工处理", "cal-readonly"))
        self.assertFalse(candidate.requires_manual_selection)

    def test_legacy_and_fallback_keys_are_rejected(self):
        value = DeepMathResourceConfig(
            "deepmath", BASE_NAME, "DeepMath CEO Actions", CALENDAR_NAME, "Asia/Shanghai"
        ).as_mapping()
        value["fallback"] = {"bitable_url": "https://legacy.example/base/old"}
        with self.assertRaises(DeepMathResourceContractError):
            DeepMathResourceConfig.from_mapping(value)

    def test_symbolic_tenant_label_cannot_be_used_as_api_proof(self):
        value = DeepMathResourceConfig(
            "deepmath", BASE_NAME, "DeepMath CEO Actions", CALENDAR_NAME, "Asia/Shanghai"
        ).as_mapping()
        value["tenant_proof"] = "deepmath"
        with self.assertRaises(DeepMathResourceContractError):
            DeepMathResourceConfig.from_mapping(value)

    def test_resource_binding_must_be_complete_and_atomic(self):
        value = DeepMathResourceConfig(
            "deepmath", BASE_NAME, "DeepMath CEO Actions", CALENDAR_NAME, "Asia/Shanghai"
        ).as_mapping()
        value["base_id"] = "appDeepMath123"
        with self.assertRaises(DeepMathResourceContractError):
            DeepMathResourceConfig.from_mapping(value)

    def test_complete_binding_preserves_base_url_and_requires_matching_token(self):
        value = DeepMathResourceConfig(
            "deepmath", BASE_NAME, "DeepMath CEO Actions", CALENDAR_NAME, "Asia/Shanghai"
        ).as_mapping()
        value.update(
            {
                "base_id": "appDeepMath123",
                "tasklist_id": "tasklist-deepmath",
                "calendar_id": "calendar-deepmath",
                "base_url": "https://deepmath.feishu.cn/base/appDeepMath123",
                "tenant_proof": "tenant-key-from-api",
            }
        )
        config = DeepMathResourceConfig.from_mapping(value)
        self.assertEqual(config.base_url, value["base_url"])
        self.assertEqual(config.as_mapping()["base_url"], value["base_url"])
        value["base_id"] = "wrong-token"
        with self.assertRaises(DeepMathResourceContractError):
            DeepMathResourceConfig.from_mapping(value)

    def test_tenant_identity_requires_approved_api_readback(self):
        self.assertEqual(DEEP_MATH_FEISHU_ACCOUNT_ID, "deepmath")
        self.assertEqual(tenant_identity_status(None, "tenant-from-api"), "approval_required")
        self.assertEqual(tenant_identity_status("tenant-a", "tenant-b"), "tenant_mismatch")
        self.assertEqual(tenant_identity_status("tenant-a", "tenant-a"), "verified")

    def test_explicit_base_url_is_parsed_without_accepting_old_or_non_feishu_hosts(self):
        self.assertEqual(
            parse_explicit_bitable_url("https://deepmath.feishu.cn/base/appDeepMath123"),
            "appDeepMath123",
        )
        with self.assertRaises(DeepMathResourceContractError):
            parse_explicit_bitable_url("https://example.test/base/appDeepMath123")


if __name__ == "__main__":
    unittest.main()
