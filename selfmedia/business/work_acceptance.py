"""Evidence-bounded work acceptance writeback for commercial deliveries."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from media_vault import MediaVault, require_tenant_id

from .commercial_loop import CommercialLoopLedger, has_external_evidence


class WorkAcceptanceError(ValueError):
    pass


def _normalise_items(items: Any) -> list[dict[str, str]]:
    if not isinstance(items, list):
        return []
    normalised: list[dict[str, str]] = []
    for item in items[:40]:
        if not isinstance(item, Mapping):
            continue
        requirement = str(item.get("requirement") or item.get("要求") or "").strip()
        if not requirement:
            continue
        judgment = str(item.get("judgment") or item.get("判定") or "不确定").strip()
        if judgment not in {"满足", "不满足", "不确定"}:
            judgment = "不确定"
        normalised.append(
            {
                "requirement": requirement,
                "judgment": judgment,
                "evidence": str(item.get("evidence") or item.get("证据") or "").strip(),
                "gap": str(item.get("gap") or item.get("缺口") or "").strip(),
                "fix": str(item.get("fix") or item.get("修改建议") or "").strip(),
            }
        )
    return normalised


class WorkAcceptanceWriteback:
    """Persist acceptance and update its commercial loop with readback."""

    def __init__(self, *, tenant_id: str, opportunity_id: str, root: str | None = None) -> None:
        self.tenant_id = require_tenant_id(tenant_id)
        self.opportunity_id = str(opportunity_id or "").strip()
        if not self.opportunity_id:
            raise WorkAcceptanceError("opportunity_id is required")
        self.vault = MediaVault(tenant_id=self.tenant_id, root=root)
        self.ledger = CommercialLoopLedger(tenant_id=self.tenant_id, loop_id=self.opportunity_id, root=root)

    def record(
        self,
        *,
        creation_run_id: str,
        verdict: str,
        items: Any = None,
        summary: str = "",
        evidence_uri: str = "",
        external_verified: bool = False,
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        run_id = str(creation_run_id or "").strip()
        if not run_id:
            raise WorkAcceptanceError("creation_run_id is required")
        normalized_items = _normalise_items(items)
        pass_count = sum(item["judgment"] == "满足" for item in normalized_items)
        fail_count = sum(item["judgment"] == "不满足" for item in normalized_items)
        uncertain_count = sum(item["judgment"] == "不确定" for item in normalized_items)
        normalized_verdict = str(verdict or "信息不足").strip() or "信息不足"
        evidence = str(evidence_uri or "").strip()
        status = "confirmed" if has_external_evidence(evidence) and external_verified else "pending_manual"
        identity = idempotency_key or "acceptance:" + hashlib.sha256(run_id.encode("utf-8")).hexdigest()
        ledger_before = self.ledger.load()
        if ledger_before.get("lifecycle_stage") != "published":
            replayed = any(
                isinstance(event, dict)
                and event.get("event") == "acceptance_confirmed"
                and event.get("idempotency_key") == identity
                for event in ledger_before.get("lifecycle_events", [])
            )
            if not replayed:
                raise WorkAcceptanceError("work acceptance requires a confirmed publication")
        payload = {
            "schema_version": "work_acceptance_v1",
            "tenant_id": self.tenant_id,
            "opportunity_id": self.opportunity_id,
            "creation_run_id": run_id,
            "verdict": normalized_verdict,
            "status": status,
            "counts": {"passed": pass_count, "failed": fail_count, "uncertain": uncertain_count},
            "items": normalized_items,
            "summary": str(summary or "").strip(),
            "evidence_uri": evidence,
            "external_verified": bool(external_verified),
            "idempotency_identity": identity,
        }
        package_dir = self.vault.business_dir(self.opportunity_id)
        acceptance_path = package_dir / "work_acceptance.json"
        if acceptance_path.exists():
            existing = self.read()
            if existing.get("idempotency_identity") != identity:
                raise WorkAcceptanceError("work acceptance identity was reused with different content")
            if _canonical_json(existing) != _canonical_json(payload) and not _is_pending_upgrade(existing, payload):
                raise WorkAcceptanceError("work acceptance replay payload differs")
        artifact = self.vault.write_json_artifact(
            package_dir,
            "work_acceptance.json",
            payload,
            owner_type="BusinessOpportunity",
            owner_id=self.opportunity_id,
            artifact_type="work_acceptance",
            artifact_id=f"work_acceptance_{self.opportunity_id}",
        )
        ledger_state = self.ledger.record_acceptance(
            verdict=normalized_verdict,
            evidence_uri=evidence,
            external_verified=external_verified,
            idempotency_key=identity,
            details={"creation_run_id": run_id, "counts": payload["counts"], "artifact_uri": artifact["uri"]},
        )
        return {
            "status": status,
            "artifact_uri": artifact["uri"],
            "creation_run_id": run_id,
            "commercial_loop": ledger_state,
            "readback": self.read(),
        }

    def read(self) -> dict[str, Any]:
        path = self.vault.business_dir(self.opportunity_id) / "work_acceptance.json"
        if not path.is_file():
            return {"status": "pending_manual", "opportunity_id": self.opportunity_id}
        try:
            import json

            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise WorkAcceptanceError("work acceptance artifact is unreadable") from exc
        if (
            not isinstance(value, dict)
            or value.get("tenant_id") != self.tenant_id
            or value.get("opportunity_id") != self.opportunity_id
        ):
            raise WorkAcceptanceError("work acceptance ownership mismatch")
        return value


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _is_pending_upgrade(existing: dict[str, Any], requested: dict[str, Any]) -> bool:
    if existing.get("status") != "pending_manual" or requested.get("status") != "confirmed":
        return False
    if existing.get("creation_run_id") != requested.get("creation_run_id"):
        return False
    comparable_existing = dict(existing)
    comparable_requested = dict(requested)
    for value in (comparable_existing, comparable_requested):
        value.pop("status", None)
        value.pop("evidence_uri", None)
        value.pop("external_verified", None)
    return _canonical_json(comparable_existing) == _canonical_json(comparable_requested)
