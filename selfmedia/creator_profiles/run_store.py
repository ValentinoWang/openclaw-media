from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .evidence import DEFAULT_VAULT_ROOT


class RunStoreError(RuntimeError):
    pass


class RunStore:
    def __init__(self, root: Path = DEFAULT_VAULT_ROOT) -> None:
        self.root = Path(root)

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

    def write_json(self, run_id: str, filename: str, payload: dict[str, Any]) -> Path:
        path = self.find_run_dir(run_id) / filename
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path
