"""Persistent idempotency for replayed tagged channel messages."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import fcntl
import hashlib
import json
import os
from pathlib import Path
import secrets
from typing import Any


DEFAULT_TTL = timedelta(days=7)
MAX_MESSAGE_ID_LENGTH = 512
MAX_RESPONSE_BYTES = 4 * 1024 * 1024


class MessageResultStoreError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class MessageExecutionResult:
    response: dict[str, Any]
    replayed: bool


class MessageResultStore:
    """Serialize one channel message across bridge processes and replay success."""

    def __init__(
        self,
        root: Path,
        *,
        ttl: timedelta = DEFAULT_TTL,
        now_factory: Callable[[], datetime] | None = None,
    ) -> None:
        if ttl <= timedelta(0):
            raise ValueError("ttl must be positive")
        self.root = root
        self.ttl = ttl
        self.now_factory = now_factory or (lambda: datetime.now(UTC))
        self.root.mkdir(parents=True, exist_ok=True)
        os.chmod(self.root, 0o700)

    def execute_once(
        self,
        *,
        account_id: str,
        message_id: str,
        text: str,
        operation: Callable[[], tuple[Mapping[str, Any], bool]],
    ) -> MessageExecutionResult:
        normalized_message_id = self._required_message_id(message_id)
        normalized_account_id = str(account_id or "unknown").strip() or "unknown"
        request_fingerprint = self._fingerprint(normalized_account_id, normalized_message_id, str(text or ""))
        key = hashlib.sha256(f"{normalized_account_id}\0{normalized_message_id}".encode("utf-8")).hexdigest()
        lock_path = self.root / f"{key}.lock"
        result_path = self.root / f"{key}.json"

        self.purge_expired()
        with lock_path.open("a+", encoding="utf-8") as lock_file:
            os.chmod(lock_path, 0o600)
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            cached = self._read(result_path)
            if cached is not None:
                if cached.get("requestFingerprint") != request_fingerprint:
                    raise MessageResultStoreError(
                        "tag_router_message_conflict",
                        "同一飞书消息标识对应了不同内容，已拒绝重复执行。",
                    )
                response = cached.get("response")
                if not isinstance(response, Mapping):
                    raise MessageResultStoreError("tag_router_message_cache_invalid", "消息成功回执缓存损坏，需人工核验。")
                return MessageExecutionResult(response=deepcopy(dict(response)), replayed=True)

            response, cacheable = operation()
            if not isinstance(response, Mapping):
                raise TypeError("message operation must return a mapping response")
            normalized_response = deepcopy(dict(response))
            if cacheable:
                self._write(
                    result_path,
                    {
                        "schemaVersion": 1,
                        "accountId": normalized_account_id,
                        "messageId": normalized_message_id,
                        "requestFingerprint": request_fingerprint,
                        "completedAt": self._now().isoformat(),
                        "expiresAt": (self._now() + self.ttl).isoformat(),
                        "response": normalized_response,
                    },
                )
            return MessageExecutionResult(response=normalized_response, replayed=False)

    def purge_expired(self) -> int:
        now = self._now()
        removed = 0
        for path in self.root.glob("*.json"):
            payload = self._read(path)
            expires_at = self._parse_datetime((payload or {}).get("expiresAt"))
            if payload is None or expires_at is None or expires_at <= now:
                path.unlink(missing_ok=True)
                removed += 1
        return removed

    @staticmethod
    def _required_message_id(value: Any) -> str:
        if not isinstance(value, str):
            raise MessageResultStoreError("tag_router_message_id_invalid", "飞书消息标识无效，不能执行幂等路由。")
        message_id = value.strip()
        if not message_id or len(message_id) > MAX_MESSAGE_ID_LENGTH or any(ord(char) < 32 for char in message_id):
            raise MessageResultStoreError("tag_router_message_id_invalid", "飞书消息标识无效，不能执行幂等路由。")
        return message_id

    @staticmethod
    def _fingerprint(account_id: str, message_id: str, text: str) -> str:
        raw = json.dumps(
            {"accountId": account_id, "messageId": message_id, "text": text},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @staticmethod
    def _read(path: Path) -> dict[str, Any] | None:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return None
        return value if isinstance(value, dict) else None

    @staticmethod
    def _write(path: Path, payload: Mapping[str, Any]) -> None:
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(encoded) > MAX_RESPONSE_BYTES:
            raise MessageResultStoreError("tag_router_message_result_too_large", "标签任务成功回执过大，不能安全缓存。")
        temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
        temporary.write_bytes(encoded)
        os.chmod(temporary, 0o600)
        temporary.replace(path)

    @staticmethod
    def _parse_datetime(value: Any) -> datetime | None:
        if not isinstance(value, str) or not value.strip():
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)

    def _now(self) -> datetime:
        value = self.now_factory()
        if not isinstance(value, datetime):
            raise TypeError("now_factory must return datetime")
        return value if value.tzinfo else value.replace(tzinfo=UTC)
