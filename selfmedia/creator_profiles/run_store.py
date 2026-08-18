from __future__ import annotations

import fcntl
import json
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from media_vault.vault import MediaVault


class RunStoreError(RuntimeError):
    pass


class RunStore:
    def __init__(self, *, tenant_id: str, root: Path | None = None) -> None:
        self.root = MediaVault(tenant_id=tenant_id, root=root).root / "creator_profiles"

    def find_run_dir(self, run_id: str) -> Path:
        matches = [path for path in self.root.glob(f"*/*/{run_id}") if path.is_dir()]
        if not matches:
            raise RunStoreError(f"candidate run not found: {run_id}")
        if len(matches) > 1:
            raise RunStoreError(f"candidate run id is ambiguous: {run_id}")
        return matches[0]

    def read_json(self, run_id: str, filename: str) -> dict[str, Any]:
        path = self.find_run_dir(run_id) / filename
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise RunStoreError(f"missing run artifact: {path}") from exc
        if not isinstance(payload, dict):
            raise RunStoreError(f"run artifact must be JSON object: {path}")
        return payload

    def read_optional_json(self, run_id: str, filename: str) -> dict[str, Any] | None:
        path = self.find_run_dir(run_id) / filename
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        if not isinstance(payload, dict):
            raise RunStoreError(f"run artifact must be JSON object: {path}")
        return payload

    @contextmanager
    def confirmation_lock(self, run_id: str) -> Iterator[None]:
        path = self.find_run_dir(run_id) / ".confirm.lock"
        with path.open("a+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def write_json(self, run_id: str, filename: str, payload: dict[str, Any]) -> Path:
        path = self.find_run_dir(run_id) / filename
        temporary = path.with_suffix(f"{path.suffix}.tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)
        return path
