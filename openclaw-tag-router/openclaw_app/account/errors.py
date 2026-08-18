from __future__ import annotations


class AccountError(RuntimeError):
    def __init__(self, code: str, detail: str, *, status: int) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.status = status


class AccountContractError(AccountError):
    def __init__(self, code: str, detail: str) -> None:
        status = 500 if code == "account_contract_invalid" else 503
        super().__init__(code, detail, status=status)


class AccountAuthError(AccountError):
    def __init__(self, code: str, detail: str, *, status: int) -> None:
        super().__init__(code, detail, status=status)
