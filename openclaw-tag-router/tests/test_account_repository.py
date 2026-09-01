from __future__ import annotations

import unittest
from uuid import UUID

from openclaw_app.account import AccountAuthRepository


USER_ID = UUID("11111111-1111-4111-8111-111111111111")
TENANT_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
CREDENTIAL_ROW = (
    USER_ID,
    TENANT_ID,
    "media-user",
    None,
    "unused-password-hash",
    "user",
    "active",
    "active",
    False,
)


class _Result:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self._rows = rows

    def fetchall(self) -> list[tuple[object, ...]]:
        return self._rows


class _Connection:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self.rows = rows
        self.query = ""
        self.parameters: dict[str, str | None] = {}

    def execute(self, query: str, parameters: dict[str, str | None]) -> _Result:
        self.query = " ".join(query.split())
        self.parameters = parameters
        return _Result(self.rows)


class AccountAuthRepositoryTests(unittest.TestCase):
    def test_feishu_identity_query_matches_open_id_or_union_id(self) -> None:
        connection = _Connection([CREDENTIAL_ROW])

        credential = AccountAuthRepository().credential_for_feishu_identity(
            connection,
            tenant_key="tenant-media-a",
            open_id="open-from-independent-media-app",
            union_id="stable-union-a",
        )

        self.assertIsNotNone(credential)
        self.assertEqual(credential.user_id, USER_ID)
        self.assertIn(
            "(CAST(%(open_id)s AS text) IS NOT NULL AND i.open_id = CAST(%(open_id)s AS text)) OR "
            "(CAST(%(union_id)s AS text) IS NOT NULL AND i.union_id = CAST(%(union_id)s AS text))",
            connection.query,
        )
        self.assertEqual(
            connection.parameters,
            {
                "tenant_key": "tenant-media-a",
                "open_id": "open-from-independent-media-app",
                "union_id": "stable-union-a",
            },
        )

    def test_feishu_identity_query_rejects_ambiguous_matches(self) -> None:
        connection = _Connection([CREDENTIAL_ROW, CREDENTIAL_ROW])

        credential = AccountAuthRepository().credential_for_feishu_identity(
            connection,
            tenant_key="tenant-media-a",
            open_id="open-a",
            union_id="union-a",
        )

        self.assertIsNone(credential)
        self.assertIn("LIMIT 2", connection.query)

    def test_organization_intent_requires_a_single_active_bound_organization_tenant(self) -> None:
        connection = _Connection([CREDENTIAL_ROW])

        credential = AccountAuthRepository().credential_for_feishu_identity(
            connection,
            tenant_key="tenant-media-a",
            open_id="open-a",
            union_id="union-a",
            workspace_intent="organization_lark",
        )

        self.assertIsNotNone(credential)
        self.assertIn("openclaw_account.tenant_members AS identity_members", connection.query)
        self.assertIn("openclaw_account.tenants AS tenant", connection.query)
        self.assertIn("tenant.workspace_mode = 'organization_lark'", connection.query)
        self.assertIn("tenant.body_authority = 'lark'", connection.query)
        self.assertIn("binding.status = 'active'", connection.query)
        self.assertNotIn("workspace_memberships", connection.query)
        self.assertNotIn("openclaw_account.workspaces", connection.query)
        self.assertIn("LIMIT 2", connection.query)


if __name__ == "__main__":
    unittest.main()
