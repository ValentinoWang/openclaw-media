from __future__ import annotations

import json
import os
from functools import cached_property
from pathlib import Path
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
AI_HARNESS_CONTRACT_DIR = REPOSITORY_ROOT / "docs" / "ai-harness"
REPOSITORY_MEDIA_MODEL_CONTRACT_PATH = AI_HARNESS_CONTRACT_DIR / "media-model-v2-contract.json"
REPOSITORY_CREATION_RUN_DETAIL_CONTRACT_PATH = AI_HARNESS_CONTRACT_DIR / "media-creation-run-detail-contract.json"
LEGACY_MEDIA_MODEL_CONTRACT_PATH = Path("/home/ubuntu/docs/ai-harness/media-model-v2-contract.json")
LEGACY_CREATION_RUN_DETAIL_CONTRACT_PATH = Path("/home/ubuntu/docs/ai-harness/media-creation-run-detail-contract.json")
MEDIA_MODEL_CONTRACT_PATH_ENV = "OPENCLAW_MEDIA_MODEL_CONTRACT_PATH"
CREATION_RUN_DETAIL_CONTRACT_PATH_ENV = "OPENCLAW_MEDIA_CREATION_RUN_DETAIL_CONTRACT_PATH"
DEFAULT_MEDIA_MODEL_CONTRACT_PATH = REPOSITORY_MEDIA_MODEL_CONTRACT_PATH


class MediaModelContractError(RuntimeError):
    pass


def _resolve_contract_path(*, environment_key: str, repository_path: Path, legacy_path: Path) -> Path:
    override = os.getenv(environment_key, "").strip()
    if override:
        return Path(override).expanduser()
    if repository_path.is_file():
        return repository_path
    if legacy_path.is_file():
        return legacy_path
    return repository_path


def resolve_media_model_contract_path() -> Path:
    """Return the explicit override or the repository-owned Media Model contract."""
    return _resolve_contract_path(
        environment_key=MEDIA_MODEL_CONTRACT_PATH_ENV,
        repository_path=REPOSITORY_MEDIA_MODEL_CONTRACT_PATH,
        legacy_path=LEGACY_MEDIA_MODEL_CONTRACT_PATH,
    )


def resolve_creation_run_detail_contract_path() -> Path:
    """Return the explicit override or the repository-owned CreationRun detail contract."""
    return _resolve_contract_path(
        environment_key=CREATION_RUN_DETAIL_CONTRACT_PATH_ENV,
        repository_path=REPOSITORY_CREATION_RUN_DETAIL_CONTRACT_PATH,
        legacy_path=LEGACY_CREATION_RUN_DETAIL_CONTRACT_PATH,
    )


class MediaModelContract:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path).expanduser() if path is not None else resolve_media_model_contract_path()

    @cached_property
    def data(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise MediaModelContractError(f"invalid media model contract JSON: {self.path}: {exc}") from exc
        if not isinstance(payload, dict):
            raise MediaModelContractError(f"media model contract must be object: {self.path}")
        if payload.get("version") != "canonical_data_model_v2":
            raise MediaModelContractError("unsupported media model contract version")
        return payload

    @cached_property
    def field_classes(self) -> set[str]:
        return set(self.data.get("field_classes") or [])

    def entity(self, entity_name: str) -> dict[str, Any]:
        entity = (self.data.get("entity_contracts") or {}).get(entity_name)
        if not isinstance(entity, dict):
            raise MediaModelContractError(f"unknown media model entity: {entity_name}")
        return entity

    def projection(self, entity_name: str) -> dict[str, Any]:
        matches = [
            projection
            for projection in (self.data.get("projection_contracts") or {}).values()
            if isinstance(projection, dict) and projection.get("entity") == entity_name
        ]
        if not matches:
            raise MediaModelContractError(f"missing projection for entity: {entity_name}")
        if len(matches) > 1:
            raise MediaModelContractError(f"multiple projections for entity: {entity_name}")
        return matches[0]

    def entity_fields(self, entity_name: str) -> dict[str, dict[str, Any]]:
        fields = self.entity(entity_name).get("fields") or {}
        if not isinstance(fields, dict):
            raise MediaModelContractError(f"entity fields must be object: {entity_name}")
        return fields

    def writable_fields(self, entity_name: str) -> set[str]:
        fields = self.projection(entity_name).get("agent_write_fields") or []
        return {str(item) for item in fields}

    def human_view_fields(self, entity_name: str) -> set[str]:
        fields = self.projection(entity_name).get("human_view_fields") or []
        return {str(item) for item in fields}

    def field_name_map(self, entity_name: str) -> dict[str, str]:
        mapping = self.projection(entity_name).get("field_name_map") or {}
        if not isinstance(mapping, dict):
            raise MediaModelContractError(f"{entity_name} field_name_map must be object")
        return {str(key): str(value) for key, value in mapping.items()}

    def feishu_field_name(self, entity_name: str, canonical_key: str) -> str:
        return self.field_name_map(entity_name).get(str(canonical_key), str(canonical_key))

    def canonical_field_name(self, entity_name: str, feishu_field_name: str) -> str:
        field_name = str(feishu_field_name)
        reverse = {display: canonical for canonical, display in self.field_name_map(entity_name).items()}
        return reverse.get(field_name, field_name)

    def normalize_record_fields(self, entity_name: str, fields: dict[str, Any]) -> dict[str, Any]:
        normalized: dict[str, Any] = {}
        for field_name, value in (fields or {}).items():
            normalized[self.canonical_field_name(entity_name, str(field_name))] = value
        return normalized

    def required_fields(self, entity_name: str) -> set[str]:
        required: set[str] = set()
        for field_name, field_contract in self.entity_fields(entity_name).items():
            if isinstance(field_contract, dict) and field_contract.get("required"):
                required.add(field_name)
        return required

    def validate_payload(self, entity_name: str, payload: dict[str, Any], *, allow_missing_required: bool = False) -> None:
        if not isinstance(payload, dict):
            raise MediaModelContractError(f"{entity_name} payload must be object")
        allowed = self.writable_fields(entity_name)
        fields = self.entity_fields(entity_name)
        unknown = set(payload) - allowed
        if unknown:
            raise MediaModelContractError(f"{entity_name} payload contains non-writable fields: {sorted(unknown)}")
        undeclared = set(payload) - set(fields)
        if undeclared:
            raise MediaModelContractError(f"{entity_name} payload contains undeclared fields: {sorted(undeclared)}")
        visible_json = [field for field in payload if str(field).endswith("JSON")]
        if visible_json:
            raise MediaModelContractError(f"{entity_name} payload contains visible JSON fields: {visible_json}")
        if not allow_missing_required:
            missing = [field for field in self.required_fields(entity_name) if field in allowed and is_empty(payload.get(field))]
            if missing:
                raise MediaModelContractError(f"{entity_name} payload missing required writable fields: {missing}")
        for field_name, value in payload.items():
            field_contract = fields.get(field_name) or {}
            if field_contract.get("type") == "media_uri":
                require_media_uri(value, f"{entity_name}.{field_name}")
            if field_contract.get("class") == "runtime_debug":
                raise MediaModelContractError(f"{entity_name}.{field_name} is runtime_debug and must not be written to Feishu")

    def validate_artifact_reference(self, value: Any, field_label: str) -> None:
        require_media_uri(value, field_label)


def is_empty(value: Any) -> bool:
    return value is None or value == "" or value == []


def require_media_uri(value: Any, field_label: str) -> None:
    if is_empty(value):
        raise MediaModelContractError(f"{field_label} requires media:// URI")
    if not str(value).startswith("media://"):
        raise MediaModelContractError(f"{field_label} must use media:// URI, got {value!r}")
