from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from media_vault import MediaVault, require_tenant_id


COMMERCIAL_LOOP_SCHEMA_VERSION = "commercial_loop_v1"
COMMERCIAL_LOOP_FILENAME = "commercial_loop_state.json"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _request_fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class CommercialLoopLedger:
    """Tenant-scoped durable state for commercial work that awaits external proof."""

    def __init__(self, *, tenant_id: str, loop_id: str) -> None:
        self.tenant_id = require_tenant_id(tenant_id)
        self.loop_id = str(loop_id or "").strip()
        if not self.loop_id:
            raise ValueError("commercial loop_id is required")
        self.vault = MediaVault(tenant_id=self.tenant_id)
        self.path = self.vault.business_dir(self.loop_id) / COMMERCIAL_LOOP_FILENAME

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return self._empty_state()
        try:
            state = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise RuntimeError("commercial loop state is unreadable") from exc
        if not isinstance(state, dict):
            raise RuntimeError("commercial loop state must be an object")
        if state.get("schema_version") != COMMERCIAL_LOOP_SCHEMA_VERSION:
            raise RuntimeError("commercial loop state schema is unsupported")
        if state.get("tenant_id") != self.tenant_id or state.get("loop_id") != self.loop_id:
            raise RuntimeError("commercial loop state ownership mismatch")
        return state

    def ensure_quote_snapshot(
        self,
        *,
        business_account_id: str,
        quote_snapshot_uri: str,
        quote_refresh: dict[str, Any],
    ) -> dict[str, Any]:
        state = self.load()
        state["business_account_id"] = str(business_account_id or "")
        state["quote_snapshot_uri"] = str(quote_snapshot_uri or "")
        state["quote_refresh"] = dict(quote_refresh)
        state["lifecycle_status"] = self._advance_lifecycle(
            str(state.get("lifecycle_status") or "quoted"), "quoted"
        )
        self._append_event(state, "quote_snapshot_recorded")
        return self._save(state)

    def begin_delivery(self, *, request_text: str, links: dict[str, str]) -> tuple[dict[str, Any], bool]:
        state = self.load()
        if state.get("external_status") == "confirmed":
            return state, True
        state["delivery"] = {
            **(state.get("delivery") if isinstance(state.get("delivery"), dict) else {}),
            "request_fingerprint": _request_fingerprint(request_text),
            "links": {key: str(value or "") for key, value in links.items()},
        }
        state["lifecycle_status"] = self._advance_lifecycle(
            str(state.get("lifecycle_status") or "quoted"), "in_creation"
        )
        if state.get("external_status") not in {"document_created_unverified", "record_created_unverified"}:
            state["external_status"] = "retry_pending"
        state["retry"] = {
            "action": "retry_commercial_delivery",
            "loop_id": self.loop_id,
            "attempts": int((state.get("retry") or {}).get("attempts") or 0) + 1,
        }
        self._append_event(state, "delivery_attempt_started")
        return self._save(state), False

    def record_document(self, *, document_id: str, document_url: str) -> dict[str, Any]:
        state = self.load()
        delivery = state.setdefault("delivery", {})
        if not isinstance(delivery, dict):
            raise RuntimeError("commercial loop delivery state must be an object")
        delivery["document_id"] = str(document_id or "")
        delivery["document_url"] = str(document_url or "")
        state["external_status"] = "document_created_unverified"
        self._append_event(state, "document_created_unverified")
        return self._save(state)

    def document(self) -> dict[str, str]:
        state = self.load()
        delivery = state.get("delivery")
        if not isinstance(delivery, dict):
            return {"document_id": "", "document_url": ""}
        return {
            "document_id": str(delivery.get("document_id") or ""),
            "document_url": str(delivery.get("document_url") or ""),
        }

    def external_record(self) -> dict[str, Any]:
        state = self.load()
        delivery = state.get("delivery")
        if not isinstance(delivery, dict):
            return {}
        record = delivery.get("record")
        return dict(record) if isinstance(record, dict) else {}

    def record_external_record(self, record: dict[str, Any]) -> dict[str, Any]:
        record_id = str(record.get("record_id") or "").strip()
        if not record_id:
            raise RuntimeError("commercial loop external record requires record_id")
        state = self.load()
        delivery = state.setdefault("delivery", {})
        if not isinstance(delivery, dict):
            raise RuntimeError("commercial loop delivery state must be an object")
        delivery["record"] = dict(record)
        state["external_status"] = "record_created_unverified"
        self._append_event(state, "delivery_record_readback_confirmed")
        return self._save(state)

    def confirm_delivery(self, *, doc_url: str, record: dict[str, Any], review_links: dict[str, str]) -> dict[str, Any]:
        state = self.load()
        delivery = state.setdefault("delivery", {})
        if not isinstance(delivery, dict):
            raise RuntimeError("commercial loop delivery state must be an object")
        delivery["document_url"] = str(doc_url or delivery.get("document_url") or "")
        delivery["record"] = dict(record)
        delivery["review_links"] = {key: str(value or "") for key, value in review_links.items()}
        state["business_opportunity_id"] = str(review_links.get("business_opportunity_id") or "")
        state["creation_run_id"] = str(review_links.get("creation_run_id") or "")
        state["lifecycle_status"] = self._advance_lifecycle(
            str(state.get("lifecycle_status") or "quoted"), "delivered"
        )
        state["external_status"] = "confirmed"
        state["retry"] = {}
        state["delivery_status"] = "draft_ready_pending_review"
        state["publish_status"] = (
            "evidence_submitted_pending_verification"
            if str(review_links.get("publish_url") or "").strip()
            else "pending_manual"
        )
        state["acceptance_status"] = "pending_manual"
        state["retrospective_status"] = "pending_manual"
        state["settlement_status"] = "pending_manual"
        self._append_event(state, "delivery_external_readback_confirmed")
        return self._save(state)

    def mark_external_retry(self, *, reason_code: str) -> dict[str, Any]:
        state = self.load()
        if state.get("external_status") not in {"document_created_unverified", "record_created_unverified"}:
            state["external_status"] = "retry_pending"
        state["retry"] = {
            **(state.get("retry") if isinstance(state.get("retry"), dict) else {}),
            "action": "retry_commercial_delivery",
            "loop_id": self.loop_id,
            "reason_code": str(reason_code or "external_unverified"),
        }
        self._append_event(state, "delivery_external_retry_pending")
        return self._save(state)

    def artifact_path(self) -> str:
        return str(self.path)

    def _empty_state(self) -> dict[str, Any]:
        return {
            "schema_version": COMMERCIAL_LOOP_SCHEMA_VERSION,
            "tenant_id": self.tenant_id,
            "loop_id": self.loop_id,
            "lifecycle_status": "quoted",
            "external_status": "not_attempted",
            "events": [],
        }

    @staticmethod
    def _advance_lifecycle(current: str, requested: str) -> str:
        order = {"quoted": 0, "in_creation": 1, "delivered": 2, "settled": 3}
        current_value = current if current in order else "quoted"
        requested_value = requested if requested in order else "quoted"
        return requested_value if order[requested_value] >= order[current_value] else current_value

    @staticmethod
    def _append_event(state: dict[str, Any], event: str) -> None:
        events = state.setdefault("events", [])
        if not isinstance(events, list):
            raise RuntimeError("commercial loop events must be a list")
        events.append({"event": event, "at": _now()})
        state["updated_at"] = _now()

    def _save(self, state: dict[str, Any]) -> dict[str, Any]:
        self.vault.write_json_artifact(
            self.path.parent,
            COMMERCIAL_LOOP_FILENAME,
            state,
            owner_type="BusinessOpportunity",
            owner_id=self.loop_id,
            artifact_type="commercial_loop_state",
        )
        return state
