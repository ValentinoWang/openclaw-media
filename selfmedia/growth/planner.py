from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .capability_registry import capability_consumes, capability_produces, preset_flow_nodes, validate_artifact_consumption


@dataclass(frozen=True)
class WorkflowNode:
    canonical_capability_id: str
    consumes: tuple[str, ...] = field(default_factory=tuple)
    produces: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "canonical_capability_id": self.canonical_capability_id,
            "consumes": list(self.consumes),
            "produces": list(self.produces),
        }


@dataclass(frozen=True)
class WorkflowPlan:
    workflow_mode: str
    requested_capability_id: str
    input_artifact_ids: tuple[str, ...] = field(default_factory=tuple)
    input_artifact_types: tuple[str, ...] = field(default_factory=tuple)
    planned_nodes: tuple[WorkflowNode, ...] = field(default_factory=tuple)
    contract_check_result: str = "not_checked"
    requires_confirmation: bool = False
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "workflow_mode": self.workflow_mode,
            "requested_capability_id": self.requested_capability_id,
            "input_artifact_ids": list(self.input_artifact_ids),
            "input_artifact_types": list(self.input_artifact_types),
            "planned_nodes": [node.to_dict() for node in self.planned_nodes],
            "contract_check_result": self.contract_check_result,
            "requires_confirmation": self.requires_confirmation,
            "reason": self.reason,
        }


def plan_media_growth_workflow(
    *,
    requested_capability_id: str,
    text: str = "",
    input_artifact_ids: tuple[str, ...] | list[str] = (),
    input_artifact_types: tuple[str, ...] | list[str] = (),
    explicit_preset: str = "",
) -> WorkflowPlan:
    capability = str(requested_capability_id or "").strip()
    artifact_ids = tuple(str(item).strip() for item in input_artifact_ids if str(item).strip())
    artifact_types = tuple(str(item).strip() for item in input_artifact_types if str(item).strip())
    preset = str(explicit_preset or "").strip()
    if preset:
        nodes = tuple(_node(item) for item in preset_flow_nodes(preset))
        if not nodes:
            return WorkflowPlan(
                workflow_mode="contract_failed",
                requested_capability_id=capability,
                input_artifact_ids=artifact_ids,
                input_artifact_types=artifact_types,
                contract_check_result="failed",
                reason=f"unknown preset_flow: {preset}",
            )
        return WorkflowPlan(
            workflow_mode="preset_flow",
            requested_capability_id=capability or nodes[0].canonical_capability_id,
            input_artifact_ids=artifact_ids,
            input_artifact_types=artifact_types,
            planned_nodes=nodes,
            contract_check_result="passed",
            reason=f"explicit preset_flow={preset}",
        )
    if artifact_ids or artifact_types:
        check = validate_artifact_consumption(capability, artifact_types)
        return WorkflowPlan(
            workflow_mode="continue_from_artifact",
            requested_capability_id=capability,
            input_artifact_ids=artifact_ids,
            input_artifact_types=artifact_types,
            planned_nodes=(_node(capability, consumes=artifact_types),),
            contract_check_result="passed" if check == "passed" else "failed",
            reason=check,
        )
    mode = "preset_flow" if _looks_like_full_plan_request(text) else "single_node"
    if mode == "preset_flow":
        default_full_plan_preset = "asset_to_topic"
        nodes = tuple(_node(item) for item in preset_flow_nodes(default_full_plan_preset))
        return WorkflowPlan(
            workflow_mode=mode,
            requested_capability_id=capability or nodes[0].canonical_capability_id,
            planned_nodes=nodes,
            contract_check_result="passed",
            reason=f"user requested a complete plan; selected preset_flow={default_full_plan_preset}",
        )
    return WorkflowPlan(
        workflow_mode="single_node",
        requested_capability_id=capability,
        planned_nodes=(_node(capability),),
        contract_check_result="passed",
        requires_confirmation=False,
        reason="explicit tag defaults to single_node",
    )


def _node(capability_id: str, *, consumes: tuple[str, ...] | None = None) -> WorkflowNode:
    return WorkflowNode(
        canonical_capability_id=capability_id,
        consumes=consumes if consumes is not None else capability_consumes(capability_id),
        produces=capability_produces(capability_id),
    )


def _looks_like_full_plan_request(text: str) -> bool:
    normalized = str(text or "")
    return bool(re.search(r"(完整发布方案|一套发布方案|从.+到.+发布|全链路|完整链路)", normalized))
