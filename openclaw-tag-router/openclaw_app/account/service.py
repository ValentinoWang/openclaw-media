from __future__ import annotations

from .contract import AccountContract, load_account_contract
from .database import AccountDatabase
from .errors import AccountContractError
from .repository import AccountSchemaRepository


class AccountSchemaService:
    def __init__(
        self,
        database: AccountDatabase,
        repository: AccountSchemaRepository | None = None,
        contract: AccountContract | None = None,
    ) -> None:
        self._database = database
        self._repository = repository or AccountSchemaRepository()
        self._contract = contract or load_account_contract()

    def ensure_current(self) -> str:
        migration_id = self._contract.migration_id
        with self._database.connect() as connection:
            try:
                present = self._repository.has_migration(connection, migration_id)
            except Exception as exc:
                raise AccountContractError("account_schema_outdated", "canonical account schema is unavailable") from exc
        if not present:
            raise AccountContractError("account_schema_outdated", "canonical account migration is missing")
        return migration_id
