from __future__ import annotations

from typing import Any, Protocol

from .contract import MediaModelContract


class MediaModelWriter(Protocol):
    def write_entity_record(self, entity_name: str, payload: dict[str, Any], *, table_url: str) -> dict[str, Any]:
        ...

    def update_entity_record(self, entity_name: str, record_id: str, payload: dict[str, Any], *, table_url: str) -> dict[str, Any]:
        ...


class EntrypointContractError(RuntimeError):
    pass


def entrypoint_contract(entrypoint: str, contract: MediaModelContract | None = None) -> dict[str, Any]:
    contracts = (contract or MediaModelContract()).data.get("entrypoint_io_contracts") or {}
    item = contracts.get(entrypoint)
    if not isinstance(item, dict):
        raise EntrypointContractError(f"unknown entrypoint contract: {entrypoint}")
    return item


def validate_entrypoint_io(
    entrypoint: str,
    *,
    reads: set[str] | list[str] | None = None,
    writes: set[str] | list[str] | None = None,
    writes_artifacts: set[str] | list[str] | None = None,
    contract: MediaModelContract | None = None,
) -> None:
    item = entrypoint_contract(entrypoint, contract)
    requested_reads = set(reads or [])
    requested_writes = set(writes or [])
    requested_artifacts = set(writes_artifacts or [])
    allowed_reads = set(item.get("reads") or [])
    allowed_writes = set(item.get("writes") or [])
    allowed_artifacts = set(item.get("writes_artifacts") or [])
    read_leaks = requested_reads - allowed_reads
    write_leaks = requested_writes - allowed_writes
    artifact_leaks = requested_artifacts - allowed_artifacts
    if read_leaks:
        raise EntrypointContractError(f"{entrypoint} reads unauthorized entities: {sorted(read_leaks)}")
    if write_leaks:
        raise EntrypointContractError(f"{entrypoint} writes unauthorized entities: {sorted(write_leaks)}")
    if artifact_leaks:
        raise EntrypointContractError(f"{entrypoint} writes unauthorized artifacts: {sorted(artifact_leaks)}")
    must_not_write = set(item.get("must_not_write") or [])
    forbidden_writes = requested_writes & must_not_write
    if forbidden_writes:
        raise EntrypointContractError(f"{entrypoint} writes explicitly forbidden entities: {sorted(forbidden_writes)}")


def validate_entrypoint_result(
    entrypoint: str,
    result: dict[str, Any],
    *,
    contract: MediaModelContract | None = None,
) -> None:
    writes = set(result.get("writes") or [])
    artifacts = set(result.get("writes_artifacts") or [])
    reads = set(result.get("reads") or [])
    validate_entrypoint_io(entrypoint, reads=reads, writes=writes, writes_artifacts=artifacts, contract=contract)
    if "DecisionTrace" in entrypoint_contract(entrypoint, contract).get("writes", []) and result.get("candidate_count", 0):
        if not result.get("decision_trace_count"):
            raise EntrypointContractError(f"{entrypoint} has candidates but no DecisionTrace")
    if "MaterialUsage" in entrypoint_contract(entrypoint, contract).get("writes", []) and result.get("final_reference_count", 0):
        if not result.get("material_usage_count"):
            raise EntrypointContractError(f"{entrypoint} has final references but no MaterialUsage")
