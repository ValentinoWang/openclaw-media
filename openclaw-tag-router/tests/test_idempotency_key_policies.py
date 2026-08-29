"""TI-04: idempotency-key format consolidation.

Locks down the shared policies in media_business/foundation.py against the
specific invariant the audit flagged as easiest to lose in a refactor: a
colon-separated resource-run child key (f"{parent}:{step}", built by
stage1_organization_provisioning._child_idempotency_key) must remain a
*legal* RESOURCE_RUN_KEY, even though it would be illegal under IF2_KEY's
narrower alphanumeric+"_-" alphabet.
"""

from __future__ import annotations

import unittest

from openclaw_app.services.media_business.foundation import (
    DEVICE_KEY,
    IF2_KEY,
    RESOURCE_RUN_KEY,
    idempotency_key,
)
from openclaw_app.services.stage1_organization_provisioning import (
    _child_idempotency_key,
    _projection_key,
    _resource_run_key,
)


class Boom(Exception):
    pass


def _err() -> Boom:
    return Boom()


class ResourceRunKeyColonInvariantTests(unittest.TestCase):
    def test_child_idempotency_key_with_colon_is_a_legal_resource_run_key(self) -> None:
        child = _child_idempotency_key("a" * 10, "step_two")
        self.assertIn(":", child)
        self.assertEqual(_resource_run_key(child), child)
        self.assertEqual(idempotency_key(child, error=_err, policy=RESOURCE_RUN_KEY), child)

    def test_resource_run_key_accepts_a_hand_built_colon_subtask_key(self) -> None:
        key = "parent_run_0001:child_step"
        self.assertEqual(_resource_run_key(key), key)

    def test_colon_subtask_key_is_rejected_by_the_narrower_if2_alphabet(self) -> None:
        # Confirms RESOURCE_RUN_KEY and IF2_KEY are genuinely different
        # policies, not the same regex under two names.
        key = "parent_run_0001:child_step"
        with self.assertRaises(ValueError):
            _projection_key(key)
        with self.assertRaises(Boom):
            idempotency_key(key, error=_err, policy=IF2_KEY)

    def test_resource_run_key_rejects_padding_and_control_characters(self) -> None:
        with self.assertRaises(Boom):
            idempotency_key(" padded_key_123", error=_err, policy=RESOURCE_RUN_KEY)
        with self.assertRaises(Boom):
            idempotency_key("padded_key_123 ", error=_err, policy=RESOURCE_RUN_KEY)
        with self.assertRaises(Boom):
            idempotency_key("has\tcontrol_char", error=_err, policy=RESOURCE_RUN_KEY)

    def test_resource_run_key_enforces_length_bounds(self) -> None:
        with self.assertRaises(Boom):
            idempotency_key("short12", error=_err, policy=RESOURCE_RUN_KEY)  # 7 chars
        self.assertEqual(idempotency_key("exactly8", error=_err, policy=RESOURCE_RUN_KEY), "exactly8")
        self.assertEqual(idempotency_key("a" * 160, error=_err, policy=RESOURCE_RUN_KEY), "a" * 160)
        with self.assertRaises(Boom):
            idempotency_key("a" * 161, error=_err, policy=RESOURCE_RUN_KEY)


class If2AndDeviceKeyPolicyTests(unittest.TestCase):
    def test_if2_key_enforces_8_to_128_alphanumeric(self) -> None:
        self.assertEqual(idempotency_key("a" * 8, error=_err, policy=IF2_KEY), "a" * 8)
        self.assertEqual(idempotency_key("a" * 128, error=_err, policy=IF2_KEY), "a" * 128)
        with self.assertRaises(Boom):
            idempotency_key("a" * 7, error=_err, policy=IF2_KEY)
        with self.assertRaises(Boom):
            idempotency_key("a" * 129, error=_err, policy=IF2_KEY)
        with self.assertRaises(Boom):
            idempotency_key("has a space", error=_err, policy=IF2_KEY)

    def test_device_key_allows_a_single_character(self) -> None:
        self.assertEqual(idempotency_key("a", error=_err, policy=DEVICE_KEY), "a")
        with self.assertRaises(Boom):
            idempotency_key("", error=_err, policy=DEVICE_KEY)
        with self.assertRaises(Boom):
            idempotency_key("a" * 129, error=_err, policy=DEVICE_KEY)

    def test_neither_if2_nor_device_key_strips_whitespace(self) -> None:
        with self.assertRaises(Boom):
            idempotency_key(" abcdefgh", error=_err, policy=IF2_KEY)
        with self.assertRaises(Boom):
            idempotency_key(" a", error=_err, policy=DEVICE_KEY)


if __name__ == "__main__":
    unittest.main()
