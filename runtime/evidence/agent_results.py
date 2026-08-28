from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal, Mapping, cast, get_args


AgentResultFolder = Literal["media", "daily", "social", "knowledge", "public"]
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_CONTRACT_PATH = REPOSITORY_ROOT / "docs/ai-harness/agent_result_vault_contract.json"
LEGACY_CONTRACT_PATH = Path("/home/ubuntu/docs/ai-harness/agent_result_vault_contract.json")
CONTRACT_PATH_ENV = "OPENCLAW_AGENT_RESULTS_CONTRACT_PATH"
VALID_FOLDERS = frozenset(get_args(AgentResultFolder))


def resolve_agent_results_contract_path() -> Path:
    override = os.getenv(CONTRACT_PATH_ENV)
    if override:
        return Path(override)
    if REPOSITORY_CONTRACT_PATH.is_file():
        return REPOSITORY_CONTRACT_PATH
    return LEGACY_CONTRACT_PATH


CONTRACT_PATH = resolve_agent_results_contract_path()


@dataclass(frozen=True)
class AgentResultsVaultContract:
    physical_root: Path
    required_folders: tuple[AgentResultFolder, ...]
    agent_aliases: Mapping[str, AgentResultFolder]
    allowed_selector_env: str
    forbidden_base_env: str

    @classmethod
    def from_file(cls, path: Path = CONTRACT_PATH) -> "AgentResultsVaultContract":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise RuntimeError(f"agent result vault contract must be a JSON object: {path}")

        root = Path(_require_str(payload, "physical_root"))
        folders = tuple(cast(AgentResultFolder, item) for item in _require_str_list(payload, "required_folders"))
        if set(folders) != VALID_FOLDERS or len(folders) != len(VALID_FOLDERS):
            raise RuntimeError(f"agent result vault contract folders must be {sorted(VALID_FOLDERS)}: {folders}")
        expected_root = Path(_require_str(payload, "diary_vault")) / "公共开发集"
        if root != expected_root:
            raise RuntimeError(f"agent result vault root drifted: {root}")

        aliases_payload = payload.get("agent_aliases")
        if not isinstance(aliases_payload, dict):
            raise RuntimeError("agent result vault contract missing agent_aliases object")
        aliases: dict[str, AgentResultFolder] = {}
        for alias, folder in aliases_payload.items():
            if not isinstance(alias, str) or not isinstance(folder, str) or folder not in folders:
                raise RuntimeError(f"invalid agent result alias mapping: {alias!r} -> {folder!r}")
            aliases[alias] = cast(AgentResultFolder, folder)

        return cls(
            physical_root=root,
            required_folders=folders,
            agent_aliases=MappingProxyType(aliases),
            allowed_selector_env=_require_str(payload, "allowed_selector_env"),
            forbidden_base_env=_require_str(payload, "forbidden_base_env"),
        )

    def assert_no_forbidden_base_override(self) -> None:
        if os.getenv(self.forbidden_base_env):
            raise RuntimeError(
                f"{self.forbidden_base_env} is disabled; write evidence under {self.physical_root}"
            )

    def folder_for_agent(self, agent: str | None) -> AgentResultFolder:
        raw_agent = (agent or os.getenv(self.allowed_selector_env) or "public").strip()
        return self.agent_aliases.get(raw_agent, "public")


def _require_str(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"agent result vault contract missing string key: {key}")
    return value


def _require_str_list(payload: dict[str, Any], key: str) -> list[str]:
    value = payload.get(key)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise RuntimeError(f"agent result vault contract missing string list key: {key}")
    return value


def agent_results_contract() -> AgentResultsVaultContract:
    return AgentResultsVaultContract.from_file()


def agent_results_base() -> Path:
    contract = agent_results_contract()
    contract.assert_no_forbidden_base_override()
    return contract.physical_root


def agent_results_folder(agent: str | None = None) -> Path:
    contract = agent_results_contract()
    contract.assert_no_forbidden_base_override()
    return contract.physical_root / contract.folder_for_agent(agent)


def agent_results_path(*parts: str, agent: str | None = None, dated: bool = True) -> Path:
    root = agent_results_folder(agent)
    if dated:
        root = root / datetime.now().strftime("%Y-%m-%d")
    return root.joinpath(*parts)
