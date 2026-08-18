from __future__ import annotations

import unittest

from openclaw_app.account.contract import load_account_contract
from openclaw_app.account.database import AccountDatabaseSettings
from openclaw_app.account.errors import AccountContractError


class AccountContractTests(unittest.TestCase):
    def test_loads_the_only_account_database_contract(self) -> None:
        contract = load_account_contract()
        self.assertEqual(contract.database_environment_key, "OPENCLAW_ACCOUNT_DATABASE_URL")
        self.assertEqual(contract.database_namespace, "openclaw_account")
        self.assertEqual(contract.migration_id, "cm1-010-persistent-admission-codes")
        self.assertIn("insufficient_balance", contract.error_codes)

    def test_missing_database_url_fails_closed(self) -> None:
        with self.assertRaises(AccountContractError) as raised:
            AccountDatabaseSettings.from_environment({})
        self.assertEqual(raised.exception.code, "account_database_unavailable")

    def test_non_postgresql_database_is_rejected(self) -> None:
        with self.assertRaises(AccountContractError) as raised:
            AccountDatabaseSettings.from_environment({"OPENCLAW_ACCOUNT_DATABASE_URL": "sqlite:///tmp/account.db"})
        self.assertEqual(raised.exception.code, "account_contract_invalid")

    def test_postgresql_database_is_accepted_without_rewriting_the_url(self) -> None:
        value = "postgresql://account@127.0.0.1:5432/openclaw"
        settings = AccountDatabaseSettings.from_environment({"OPENCLAW_ACCOUNT_DATABASE_URL": value})
        self.assertEqual(settings.database_url, value)


if __name__ == "__main__":
    unittest.main()
