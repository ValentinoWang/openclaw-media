from __future__ import annotations

import json
import os
import stat
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable


PLATFORM_CREDENTIAL_REF = "secret://openclaw/platform-sub2api/api-token"


class UpstreamCredentialError(RuntimeError):
    pass


@dataclass(frozen=True)
class UpstreamCredential:
    provider: str
    secret_ref: str
    status: str
    version: int
    rotated_at: int | None


class CanonicalFileSecretStore:
    """Owns the one canonical platform token and one short-lived staging file."""

    def __init__(self, active_path: str | Path, staged_path: str | Path) -> None:
        self.active_path = Path(active_path)
        self.staged_path = Path(staged_path)
        if self.active_path == self.staged_path:
            raise UpstreamCredentialError("staged credential path must be distinct")
        self.active_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.active_path.parent.chmod(0o700)

    def resolve(self, secret_ref: str) -> str:
        self._require_ref(secret_ref)
        return self._read_secret(self.active_path)

    def read_staged(self) -> str:
        return self._read_secret(self.staged_path)

    def activate(self, plaintext: str) -> None:
        self._validate_plaintext(plaintext)
        temporary = self.active_path.with_name(f".{self.active_path.name}.{os.getpid()}.tmp")
        try:
            temporary.write_text(plaintext, encoding="utf-8")
            temporary.chmod(0o600)
            os.replace(temporary, self.active_path)
            self.active_path.chmod(0o600)
        finally:
            if temporary.exists():
                temporary.unlink()

    def delete_active(self, secret_ref: str) -> None:
        self._require_ref(secret_ref)
        if self.active_path.exists():
            self._require_regular_secret(self.active_path)
            self.active_path.unlink()

    def delete_staged(self) -> None:
        if self.staged_path.exists():
            self._require_regular_secret(self.staged_path)
            self.staged_path.unlink()

    @staticmethod
    def _validate_plaintext(plaintext: str) -> None:
        if not plaintext or plaintext != plaintext.strip() or "\n" in plaintext or "\r" in plaintext:
            raise UpstreamCredentialError("platform credential is invalid")

    @classmethod
    def _read_secret(cls, path: Path) -> str:
        cls._require_regular_secret(path)
        value = path.read_text(encoding="utf-8")
        cls._validate_plaintext(value)
        return value

    @staticmethod
    def _require_regular_secret(path: Path) -> None:
        try:
            metadata = path.lstat()
        except FileNotFoundError as exc:
            raise UpstreamCredentialError("platform credential is unavailable") from exc
        if not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o600:
            raise UpstreamCredentialError("platform credential is unavailable")

    @staticmethod
    def _require_ref(secret_ref: str) -> None:
        if secret_ref != PLATFORM_CREDENTIAL_REF:
            raise UpstreamCredentialError("invalid platform credential reference")


class PlatformCredentialService:
    """The sole server-side owner of the stock Sub2API platform credential."""

    def __init__(self, state_path: str | Path, secrets: CanonicalFileSecretStore) -> None:
        self.state_path = Path(state_path)
        self.state_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.state_path.parent.chmod(0o700)
        self.secrets = secrets
        self._lock = threading.RLock()

    def adopt_existing(self) -> UpstreamCredential:
        with self._lock:
            if self.state_path.exists():
                raise UpstreamCredentialError("platform credential is already initialized")
            self.secrets.resolve(PLATFORM_CREDENTIAL_REF)
            credential = UpstreamCredential("sub2api", PLATFORM_CREDENTIAL_REF, "active", 1, None)
            self._write_state({"active": asdict(credential), "staged": None, "retired": None})
            return credential

    def active(self) -> UpstreamCredential:
        with self._lock:
            raw = self._read_state().get("active")
            if not isinstance(raw, dict) or raw.get("status") != "active":
                raise UpstreamCredentialError("active platform credential is unavailable")
            credential = UpstreamCredential(**raw)
            if credential.provider != "sub2api" or credential.secret_ref != PLATFORM_CREDENTIAL_REF:
                raise UpstreamCredentialError("platform credential state is invalid")
            return credential

    def resolve(self) -> str:
        credential = self.active()
        return self.secrets.resolve(credential.secret_ref)

    def rotate_from_staged(self, healthcheck: Callable[[str], bool]) -> UpstreamCredential:
        with self._lock:
            current = self.active()
            plaintext = self.secrets.read_staged()
            staged = UpstreamCredential(
                "sub2api", PLATFORM_CREDENTIAL_REF, "staged", current.version + 1, int(time.time())
            )
            self._write_state({"active": asdict(current), "staged": asdict(staged), "retired": None})
            try:
                if not healthcheck(plaintext):
                    raise UpstreamCredentialError("staged platform credential failed healthcheck")
                previous = self.secrets.resolve(current.secret_ref)
                try:
                    self.secrets.activate(plaintext)
                    activated = UpstreamCredential(
                        staged.provider, staged.secret_ref, "active", staged.version, staged.rotated_at
                    )
                    self._write_state(
                        {"active": asdict(activated), "staged": None, "retired": asdict(current)}
                    )
                except Exception:
                    self.secrets.activate(previous)
                    self._write_state({"active": asdict(current), "staged": None, "retired": None})
                    raise
            except Exception:
                self._write_state({"active": asdict(current), "staged": None, "retired": None})
                raise
            finally:
                self.secrets.delete_staged()
            return activated

    def revoke(self) -> UpstreamCredential:
        with self._lock:
            current = self.active()
            self.secrets.delete_active(current.secret_ref)
            retired = UpstreamCredential(
                current.provider, current.secret_ref, "retired", current.version, int(time.time())
            )
            self._write_state({"active": None, "staged": None, "retired": asdict(retired)})
            return retired

    def health(self) -> dict[str, object]:
        current = self.active()
        self.secrets.resolve(current.secret_ref)
        return {"provider": current.provider, "status": current.status, "version": current.version}

    def _read_state(self) -> dict[str, object]:
        try:
            metadata = self.state_path.lstat()
        except FileNotFoundError as exc:
            raise UpstreamCredentialError("platform credential state is unavailable") from exc
        if not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o600:
            raise UpstreamCredentialError("platform credential state is unavailable")
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise UpstreamCredentialError("platform credential state is invalid") from exc
        if not isinstance(payload, dict) or set(payload) != {"active", "staged", "retired"}:
            raise UpstreamCredentialError("platform credential state is invalid")
        return payload

    def _write_state(self, payload: dict[str, object]) -> None:
        temporary = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        try:
            temporary.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")), encoding="utf-8")
            temporary.chmod(0o600)
            os.replace(temporary, self.state_path)
            self.state_path.chmod(0o600)
        finally:
            if temporary.exists():
                temporary.unlink()
