from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from openclaw_app.services.message_result_store import MessageResultStore, MessageResultStoreError


class MessageResultStoreTest(unittest.TestCase):
    def test_successful_message_executes_once_and_replays_exact_response(self) -> None:
        with TemporaryDirectory() as directory:
            store = MessageResultStore(Path(directory))
            calls = 0

            def operation():
                nonlocal calls
                calls += 1
                return ({"ok": True, "status": "created", "reply": "文档：https://example.com/doc"}, True)

            first = store.execute_once(
                account_id="media",
                message_id="om_test_creation_001",
                text="【创作>抖音】主体：测试",
                operation=operation,
            )
            second = store.execute_once(
                account_id="media",
                message_id="om_test_creation_001",
                text="【创作>抖音】主体：测试",
                operation=operation,
            )

            self.assertFalse(first.replayed)
            self.assertTrue(second.replayed)
            self.assertEqual(calls, 1)
            self.assertEqual(second.response, first.response)

    def test_failed_result_is_not_cached_and_can_retry(self) -> None:
        with TemporaryDirectory() as directory:
            store = MessageResultStore(Path(directory))
            calls = 0

            def operation():
                nonlocal calls
                calls += 1
                return ({"ok": True, "status": "provider_unavailable", "reply": "retry"}, False)

            store.execute_once(account_id="media", message_id="om_retry", text="【说明】", operation=operation)
            store.execute_once(account_id="media", message_id="om_retry", text="【说明】", operation=operation)
            self.assertEqual(calls, 2)

    def test_same_message_id_with_different_text_is_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            store = MessageResultStore(Path(directory))
            store.execute_once(
                account_id="media",
                message_id="om_conflict",
                text="【说明】素材",
                operation=lambda: ({"ok": True, "status": "created", "reply": "done"}, True),
            )
            with self.assertRaises(MessageResultStoreError) as raised:
                store.execute_once(
                    account_id="media",
                    message_id="om_conflict",
                    text="【说明】创作",
                    operation=lambda: ({"ok": True}, True),
                )
            self.assertEqual(raised.exception.code, "tag_router_message_conflict")

    def test_expired_success_is_removed_and_executes_again(self) -> None:
        with TemporaryDirectory() as directory:
            now = datetime(2026, 7, 18, tzinfo=UTC)
            store = MessageResultStore(Path(directory), ttl=timedelta(seconds=1), now_factory=lambda: now)
            calls = 0

            def operation():
                nonlocal calls
                calls += 1
                return ({"ok": True, "status": "created", "reply": "done"}, True)

            store.execute_once(account_id="media", message_id="om_expired", text="【说明】", operation=operation)
            now += timedelta(seconds=2)
            store.execute_once(account_id="media", message_id="om_expired", text="【说明】", operation=operation)
            self.assertEqual(calls, 2)


if __name__ == "__main__":
    unittest.main()
