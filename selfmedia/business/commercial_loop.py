from __future__ import annotations

import hashlib
import ipaddress
import json
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit

from media_vault import MediaVault, require_tenant_id

from media_model.payloads import build_business_opportunity_payload


COMMERCIAL_LOOP_SCHEMA_VERSION = "commercial_loop_v1"
COMMERCIAL_LOOP_FILENAME = "commercial_loop_state.json"
LIFECYCLE_STAGES = (
    "quoted",
    "in_creation",
    "delivered",
    "published",
    "accepted",
    "retrospective",
    "settled",
)
LIFECYCLE_EVENTS = {
    "quote_recorded": ("quoted", None),
    "creation_started": ("in_creation", "quoted"),
    "delivery_confirmed": ("delivered", "in_creation"),
    "publication_confirmed": ("published", "delivered"),
    "acceptance_confirmed": ("accepted", "published"),
    "retrospective_recorded": ("retrospective", "accepted"),
    "settlement_confirmed": ("settled", "retrospective"),
}
LIFECYCLE_EVENT_ALIASES = {
    "quote": "quote_recorded",
    "delivery": "delivery_confirmed",
    "publish": "publication_confirmed",
    "publishing": "publication_confirmed",
    "acceptance": "acceptance_confirmed",
    "retrospective": "retrospective_recorded",
    "settlement": "settlement_confirmed",
}
EVIDENCE_EVENTS = {
    "delivery_confirmed",
    "publication_confirmed",
    "acceptance_confirmed",
    "retrospective_recorded",
    "settlement_confirmed",
}


class CommercialLifecycleError(ValueError):
    """A fail-closed lifecycle transition or evidence violation."""


LifecycleTransitionError = CommercialLifecycleError


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _request_fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def has_external_evidence(value: Any) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    try:
        parts = urlsplit(text)
    except ValueError:
        return False
    host = (parts.hostname or "").lower().rstrip(".")
    try:
        host_ip = ipaddress.ip_address(host)
    except ValueError:
        host_ip = None
    if host_ip is not None and (
        host_ip.is_private
        or host_ip.is_loopback
        or host_ip.is_link_local
        or host_ip.is_reserved
        or host_ip.is_multicast
        or host_ip.is_unspecified
    ):
        return False
    return bool(
        parts.scheme in {"http", "https"}
        and host
        and host not in {"localhost", "localhost.localdomain"}
        and not host.endswith((".localhost", ".local"))
        and not parts.username
        and not parts.password
        and not parts.fragment
    )


class CommercialLoopLedger:
    """Tenant-scoped durable state for commercial work that awaits external proof."""

    def __init__(self, *, tenant_id: str, loop_id: str, root: str | None = None) -> None:
        self.tenant_id = require_tenant_id(tenant_id)
        self.loop_id = str(loop_id or "").strip()
        if not self.loop_id:
            raise ValueError("commercial loop_id is required")
        self.vault = MediaVault(tenant_id=self.tenant_id, root=root)
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
        state.setdefault("lifecycle_stage", self._stage_from_legacy(state.get("lifecycle_status")))
        if not isinstance(state.get("lifecycle_events"), list):
            state["lifecycle_events"] = []
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
        self._transition(
            state,
            "quote_recorded",
            idempotency_key=f"quote:{_request_fingerprint(str(quote_snapshot_uri or ''))}",
            evidence_uri=str(quote_snapshot_uri or ""),
            metadata={"business_account_id": str(business_account_id or "")},
        )
        self._append_event(state, "quote_snapshot_recorded")
        return self._save(state)

    def begin_delivery(self, *, request_text: str, links: dict[str, str]) -> tuple[dict[str, Any], bool]:
        state = self.load()
        if state.get("external_status") == "confirmed":
            return state, True
        request_fingerprint = _request_fingerprint(request_text)
        existing_delivery = state.get("delivery")
        state["delivery"] = {
            **(existing_delivery if isinstance(existing_delivery, dict) else {}),
            "request_fingerprint": request_fingerprint,
            "links": {key: str(value or "") for key, value in links.items()},
        }
        self._transition(
            state,
            "creation_started",
            idempotency_key=f"creation:{request_fingerprint}",
            metadata={"links": dict(state["delivery"]["links"])},
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
        document_url = str(doc_url or delivery.get("document_url") or "").strip()
        record = dict(record) if isinstance(record, dict) else {}
        record_id = str(record.get("record_id") or record.get("recordId") or "").strip()
        delivery["document_url"] = document_url
        delivery["record"] = record
        delivery["review_links"] = {key: str(value or "") for key, value in review_links.items()}
        state["business_opportunity_id"] = str(review_links.get("business_opportunity_id") or "")
        state["creation_run_id"] = str(review_links.get("creation_run_id") or "")
        if not document_url or not record_id:
            state["delivery_status"] = "pending_manual"
            state["external_status"] = "record_created_unverified"
            self._append_event(state, "delivery_missing_external_evidence")
            return self._save(state)
        self._transition(
            state,
            "delivery_confirmed",
            idempotency_key=f"delivery:{record_id}:{_request_fingerprint(document_url)}",
            evidence_uri=document_url,
            metadata={"record_id": record_id},
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

    def record_publication(
        self,
        *,
        published_url: str,
        evidence_uri: str = "",
        idempotency_key: str = "",
        published_at: str = "",
    ) -> dict[str, Any]:
        state = self.load()
        url = str(published_url or "").strip()
        evidence = str(evidence_uri or "").strip()
        key = idempotency_key or f"publish:{_request_fingerprint(url)}"
        self._validate_transition_order(
            state, "publication_confirmed", key, evidence_uri=evidence, metadata={"published_url": url}
        )
        if url and not has_external_evidence(url):
            raise CommercialLifecycleError("published_url must be a public URL")
        existing_publication = state.get("publication") if isinstance(state.get("publication"), dict) else {}
        recorded_at = str(published_at or existing_publication.get("published_at") or "").strip() or _now()
        state["publish_status"] = "pending_manual" if not url or not has_external_evidence(evidence) else "evidence_submitted_pending_verification"
        state["publication"] = {
            "published_url": url,
            "evidence_uri": evidence,
            "published_at": recorded_at,
        }
        if not url or not has_external_evidence(evidence):
            state["validation_schedule"] = {
                "status": "blocked",
                "blocking_reason": "publication_confirmation_missing",
            }
            self._append_event(state, "publication_missing_external_evidence")
            return self._save(state)
        self._transition(
            state,
            "publication_confirmed",
            idempotency_key=key,
            evidence_uri=evidence,
            metadata={"published_url": url},
        )
        state["publish_status"] = "confirmed"
        self._schedule_validation_windows_after_publication(state)
        return self._save(state)

    def _schedule_validation_windows_after_publication(self, state: dict[str, Any]) -> None:
        """Create review work only after this ledger recorded external publication proof."""
        from selfmedia.review.validation_window_scheduler import (
            ValidationWindowScheduleError,
            ValidationWindowScheduler,
        )

        publication = state.get("publication") if isinstance(state.get("publication"), dict) else {}
        try:
            schedule = ValidationWindowScheduler(tenant_id=self.tenant_id, root=self.vault.vault_root).schedule_for_publication(
                creation_run_id=str(state.get("creation_run_id") or ""),
                published_url=str(publication.get("published_url") or ""),
                publication_evidence_uri=str(publication.get("evidence_uri") or ""),
                publication_confirmed=True,
                published_at=str(publication.get("published_at") or ""),
            )
        except (OSError, RuntimeError, ValidationWindowScheduleError) as exc:
            state["validation_schedule"] = {"status": "blocked", "blocking_reason": str(exc)}
            self._append_event(state, "validation_schedule_blocked")
            return
        state["validation_schedule"] = {
            "status": schedule.get("status"),
            "schedule_id": schedule.get("schedule_id", ""),
            "creation_run_id": schedule.get("creation_run_id", ""),
            "task_count": len(schedule.get("tasks") or []),
            "blocking_reason": schedule.get("blocking_reason", ""),
        }
        self._append_event(state, "validation_schedule_created" if schedule.get("status") == "scheduled" else "validation_schedule_blocked")

    def record_acceptance(
        self,
        *,
        verdict: str,
        evidence_uri: str = "",
        external_verified: bool = False,
        idempotency_key: str = "",
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        state = self.load()
        normalized_verdict = str(verdict or "信息不足").strip() or "信息不足"
        evidence = str(evidence_uri or "").strip()
        key = idempotency_key or f"acceptance:{_request_fingerprint(normalized_verdict + evidence)}"
        acceptance_metadata = {"verdict": normalized_verdict, "details": dict(details or {})}
        self._validate_transition_order(
            state, "acceptance_confirmed", key, evidence_uri=evidence, metadata=acceptance_metadata
        )
        status = "confirmed" if has_external_evidence(evidence) and external_verified else "pending_manual"
        state["acceptance"] = {
            "verdict": normalized_verdict,
            "status": status,
            "evidence_uri": evidence,
            "external_verified": bool(external_verified),
            "details": dict(details or {}),
        }
        state["acceptance_status"] = status
        if status != "confirmed":
            self._append_event(state, "acceptance_missing_external_evidence")
            return self._save(state)
        self._transition(
            state,
            "acceptance_confirmed",
            idempotency_key=key,
            evidence_uri=evidence,
            metadata=acceptance_metadata,
        )
        return self._save(state)

    def record_retrospective(
        self,
        *,
        summary: str,
        evidence_uri: str = "",
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        state = self.load()
        text = str(summary or "").strip()
        evidence = str(evidence_uri or "").strip()
        key = idempotency_key or f"retrospective:{_request_fingerprint(text + evidence)}"
        self._validate_transition_order(
            state, "retrospective_recorded", key, evidence_uri=evidence, metadata={"summary": text}
        )
        state["retrospective"] = {"summary": text, "evidence_uri": evidence}
        state["retrospective_status"] = "confirmed" if text and has_external_evidence(evidence) else "pending_manual"
        if state["retrospective_status"] != "confirmed":
            self._append_event(state, "retrospective_missing_external_evidence")
            return self._save(state)
        self._transition(
            state,
            "retrospective_recorded",
            idempotency_key=key,
            evidence_uri=evidence,
            metadata={"summary": text},
        )
        return self._save(state)

    def record_settlement(
        self,
        *,
        evidence_uri: str = "",
        settled_at: str = "",
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        state = self.load()
        evidence = str(evidence_uri or "").strip()
        timestamp = str(settled_at or "").strip() or _now()
        key = idempotency_key or f"settlement:{_request_fingerprint(evidence + timestamp)}"
        self._validate_transition_order(
            state, "settlement_confirmed", key, evidence_uri=evidence, metadata={"settled_at": timestamp}
        )
        state["settlement"] = {"evidence_uri": evidence, "settled_at": timestamp}
        state["settlement_status"] = "confirmed" if has_external_evidence(evidence) else "pending_manual"
        if state["settlement_status"] != "confirmed":
            self._append_event(state, "settlement_missing_external_evidence")
            return self._save(state)
        self._transition(
            state,
            "settlement_confirmed",
            idempotency_key=key,
            evidence_uri=evidence,
            metadata={"settled_at": timestamp},
        )
        state["lifecycle_status"] = "settled"
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

    def canonical_opportunity_payload(self, base: dict[str, Any]) -> dict[str, Any]:
        """Return a Media Model v2 BusinessOpportunity projection for readback."""
        return BusinessOpportunityLifecycle.project_payload(base, self.load())

    def _empty_state(self) -> dict[str, Any]:
        return {
            "schema_version": COMMERCIAL_LOOP_SCHEMA_VERSION,
            "tenant_id": self.tenant_id,
            "loop_id": self.loop_id,
            "lifecycle_status": "quoted",
            "lifecycle_stage": "quoted",
            "lifecycle_events": [],
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
    def _stage_from_legacy(value: Any) -> str:
        return {"quoted": "quoted", "in_creation": "in_creation", "delivered": "delivered", "settled": "settled"}.get(
            str(value or "quoted"), "quoted"
        )

    @staticmethod
    def _canonical_status(stage: str) -> str:
        if stage in {"quoted", "in_creation"}:
            return stage
        if stage == "settled":
            return "settled"
        return "delivered"

    @classmethod
    def _transition(
        cls,
        state: dict[str, Any],
        event: str,
        *,
        idempotency_key: str,
        evidence_uri: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        event, target, expected, current = cls._validate_transition_order(
            state,
            event,
            idempotency_key,
            evidence_uri=evidence_uri,
            metadata=metadata,
        )
        history = state.setdefault("lifecycle_events", [])
        if any(
            isinstance(prior, dict)
            and prior.get("idempotency_key") == idempotency_key
            and prior.get("event") == event
            for prior in history
        ):
            return
        if event == "quote_recorded" and current != "quoted":
            # A quote refresh is a real event but must never rewind work that
            # has already entered delivery or settlement.
            history.append(
                {
                    "event": event,
                    "from_stage": current,
                    "to_stage": current,
                    "idempotency_key": idempotency_key,
                    "evidence_uri": str(evidence_uri or ""),
                    "metadata": dict(metadata or {}),
                    "at": _now(),
                }
            )
            return
        if event == "creation_started" and current == "in_creation":
            history.append(
                {
                    "event": event,
                    "from_stage": current,
                    "to_stage": current,
                    "idempotency_key": idempotency_key,
                    "evidence_uri": str(evidence_uri or ""),
                    "metadata": dict(metadata or {}),
                    "at": _now(),
                }
            )
            return
        if expected is not None and current != expected:
            raise CommercialLifecycleError(f"illegal commercial lifecycle transition: {current} -> {event}")
        if event in EVIDENCE_EVENTS and not has_external_evidence(evidence_uri):
            raise CommercialLifecycleError(f"commercial lifecycle event requires external evidence: {event}")
        history.append(
            {
                "event": event,
                "from_stage": current,
                "to_stage": target,
                "idempotency_key": idempotency_key,
                "evidence_uri": str(evidence_uri or ""),
                "metadata": dict(metadata or {}),
                "at": _now(),
            }
        )
        state["lifecycle_stage"] = target
        state["lifecycle_status"] = cls._canonical_status(target)

    @classmethod
    def _validate_transition_order(
        cls,
        state: dict[str, Any],
        event: str,
        idempotency_key: str,
        *,
        evidence_uri: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> tuple[str, str, str | None, str]:
        event = LIFECYCLE_EVENT_ALIASES.get(event, event)
        transition = LIFECYCLE_EVENTS.get(event)
        if transition is None:
            raise CommercialLifecycleError(f"unsupported commercial lifecycle event: {event}")
        target, expected = transition
        current = str(state.get("lifecycle_stage") or cls._stage_from_legacy(state.get("lifecycle_status")))
        history = state.setdefault("lifecycle_events", [])
        for prior in history:
            if isinstance(prior, dict) and prior.get("idempotency_key") == idempotency_key:
                if prior.get("event") != event:
                    raise CommercialLifecycleError("lifecycle idempotency key was reused for another event")
                if str(prior.get("evidence_uri") or "") != str(evidence_uri or ""):
                    raise CommercialLifecycleError("lifecycle replay evidence differs")
                if metadata is not None and dict(prior.get("metadata") or {}) != dict(metadata):
                    raise CommercialLifecycleError("lifecycle replay metadata differs")
                return event, target, expected, current
        if event == "quote_recorded" and current != "quoted":
            return event, target, expected, current
        if event == "creation_started" and current == "in_creation":
            return event, target, expected, current
        if expected is not None and current != expected:
            raise CommercialLifecycleError(f"illegal commercial lifecycle transition: {current} -> {event}")
        return event, target, expected, current

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


class BusinessOpportunityLifecycle:
    """Pure canonical BusinessOpportunity event state machine.

    The persisted projection intentionally keeps the Media Model v2 coarse
    lifecycle values (quoted/in_creation/delivered/settled), while this
    machine records the real intermediate events (publish, acceptance and
    retrospective) in ``lifecycle_stage`` and ``lifecycle_events``.
    """

    @staticmethod
    def transition(
        state: dict[str, Any],
        event: str,
        *,
        evidence_uri: str = "",
        idempotency_key: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not isinstance(state, dict):
            raise ValueError("BusinessOpportunity lifecycle state must be an object")
        next_state = json.loads(json.dumps(state, ensure_ascii=False))
        next_state.setdefault("lifecycle_stage", CommercialLoopLedger._stage_from_legacy(next_state.get("lifecycle_status")))
        next_state.setdefault("lifecycle_events", [])
        key = str(idempotency_key or "").strip()
        if not key:
            raise ValueError("lifecycle idempotency_key is required")
        CommercialLoopLedger._transition(
            next_state,
            event,
            idempotency_key=key,
            evidence_uri=evidence_uri,
            metadata=metadata,
        )
        return next_state

    @staticmethod
    def project_payload(base: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(base, dict):
            raise ValueError("BusinessOpportunity base payload must be an object")
        if not isinstance(state, dict):
            raise ValueError("BusinessOpportunity lifecycle state must be an object")
        stage = str(state.get("lifecycle_stage") or "quoted")
        if stage not in LIFECYCLE_STAGES:
            raise ValueError(f"unsupported lifecycle stage: {stage}")
        events = state.get("lifecycle_events") if isinstance(state.get("lifecycle_events"), list) else []
        latest = {str(item.get("event")): item for item in events if isinstance(item, dict)}
        delivery = latest.get("delivery_confirmed") or {}
        publication = latest.get("publication_confirmed") or {}
        settlement = latest.get("settlement_confirmed") or {}
        delivery_evidence = str(base.get("delivery_evidence_uri") or "")
        if not delivery_evidence.startswith("media://"):
            delivery_evidence = ""
        settlement_evidence = str(base.get("settlement_evidence_uri") or "")
        if not settlement_evidence.startswith("media://"):
            settlement_evidence = ""
        return build_business_opportunity_payload(
            opportunity_id=str(base.get("opportunity_id") or ""),
            brand=str(base.get("brand") or ""),
            business_account_id=str(base.get("business_account_id") or ""),
            product=str(base.get("product") or ""),
            platform=str(base.get("platform") or ""),
            content_type=str(base.get("content_type") or ""),
            brief_link=str(base.get("brief_link") or ""),
            current_quote_amount=base.get("current_quote_amount"),
            rebate_ratio=base.get("rebate_ratio"),
            valid_from=str(base.get("valid_from") or ""),
            valid_until=str(base.get("valid_until") or ""),
            schedule=str(base.get("schedule") or ""),
            price_protection_policy=str(base.get("price_protection_policy") or ""),
            authorization_scope=str(base.get("authorization_scope") or ""),
            authorization_duration=str(base.get("authorization_duration") or ""),
            quote_snapshot_uri=str(base.get("quote_snapshot_uri") or ""),
            lifecycle_status=CommercialLoopLedger._canonical_status(stage),
            linked_run_ids=list(base.get("linked_run_ids") or []),
            delivery_evidence_uri=delivery_evidence,
            delivery_published_url=str(base.get("delivery_published_url") or publication.get("metadata", {}).get("published_url") or ""),
            delivered_at=str(base.get("delivered_at") or delivery.get("at") or ""),
            settlement_evidence_uri=settlement_evidence,
            settled_at=str(base.get("settled_at") or settlement.get("metadata", {}).get("settled_at") or ""),
        )
