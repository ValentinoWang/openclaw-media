from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any


KNOWLEDGE_EVIDENCE_BUNDLE_SCHEMA_VERSION = "knowledge_evidence_bundle_v1"
READY_EVIDENCE_STATUSES = {"ready", "verified", "accepted", "done"}
PENDING_EVIDENCE_STATUS = "pending_manual"
FORBIDDEN_REPLY_SOURCE_TYPES = {"reply", "knowledge_reply", "natural_language_reply", "bot_reply"}


class KnowledgeEvidenceContractError(ValueError):
    pass


class InsufficientKnowledgeEvidence(KnowledgeEvidenceContractError):
    def __init__(
        self,
        reason: str,
        *,
        limitations: tuple[str, ...] = (),
        blocked_sources: tuple[str, ...] = (),
    ) -> None:
        super().__init__(reason)
        self.reason = reason
        self.status = PENDING_EVIDENCE_STATUS
        self.limitations = limitations
        self.blocked_sources = blocked_sources

    def to_pending_payload(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "runtime_status": self.status,
            "reason": self.reason,
            "limitations": list(self.limitations),
            "blocked_sources": list(self.blocked_sources),
        }


@dataclass(frozen=True)
class EvidenceItem:
    source_url: str
    source_type: str
    text_or_summary: str
    status: str
    source_hash: str = ""
    citations: tuple[str, ...] = field(default_factory=tuple)
    limitations: tuple[str, ...] = field(default_factory=tuple)
    blocked_sources: tuple[str, ...] = field(default_factory=tuple)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "EvidenceItem":
        if not isinstance(payload, dict):
            raise KnowledgeEvidenceContractError("evidence item must be an object")
        source_url = _clean_text(payload.get("source_url") or payload.get("url"))
        citations = _clean_list(payload.get("citations"))
        if source_url and source_url not in citations:
            citations = (source_url, *citations)
        return cls(
            source_url=source_url,
            source_type=_clean_text(payload.get("source_type") or payload.get("type")),
            source_hash=_clean_text(payload.get("source_hash") or payload.get("hash")),
            text_or_summary=_clean_text(payload.get("text_or_summary") or payload.get("summary") or payload.get("text")),
            citations=citations,
            limitations=_clean_list(payload.get("limitations")),
            blocked_sources=_clean_list(payload.get("blocked_sources")),
            status=_clean_text(payload.get("status")),
            metadata=_clean_mapping(payload.get("metadata")),
        )

    def __post_init__(self) -> None:
        source_url = _clean_text(self.source_url)
        source_type = _clean_text(self.source_type)
        text_or_summary = _clean_text(self.text_or_summary)
        status = _clean_text(self.status)
        citations = _clean_list(self.citations)
        if source_url and source_url not in citations:
            citations = (source_url, *citations)
        source_hash = _clean_text(self.source_hash) or _source_hash(
            source_url=source_url,
            source_type=source_type,
            text_or_summary=text_or_summary,
        )
        object.__setattr__(self, "source_url", source_url)
        object.__setattr__(self, "source_type", source_type)
        object.__setattr__(self, "source_hash", source_hash)
        object.__setattr__(self, "text_or_summary", text_or_summary)
        object.__setattr__(self, "citations", citations)
        object.__setattr__(self, "limitations", _clean_list(self.limitations))
        object.__setattr__(self, "blocked_sources", _clean_list(self.blocked_sources))
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "metadata", _clean_mapping(self.metadata))

    @property
    def is_ready(self) -> bool:
        return self.status in READY_EVIDENCE_STATUSES

    def validate(self) -> "EvidenceItem":
        if self.source_type in FORBIDDEN_REPLY_SOURCE_TYPES:
            raise KnowledgeEvidenceContractError("Knowledge bot natural language reply is not a valid evidence source")
        missing = [
            field_name
            for field_name in ("source_url", "source_type", "source_hash", "text_or_summary", "status")
            if not getattr(self, field_name)
        ]
        if missing:
            raise KnowledgeEvidenceContractError(f"evidence item missing required fields: {', '.join(missing)}")
        if not self.citations:
            raise KnowledgeEvidenceContractError("evidence item missing citations")
        return self

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_url": self.source_url,
            "source_type": self.source_type,
            "source_hash": self.source_hash,
            "text_or_summary": self.text_or_summary,
            "citations": list(self.citations),
            "limitations": list(self.limitations),
            "blocked_sources": list(self.blocked_sources),
            "status": self.status,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class KnowledgeEvidenceBundle:
    bundle_id: str = ""
    query: str = ""
    evidence_items: tuple[EvidenceItem, ...] = field(default_factory=tuple)
    citations: tuple[str, ...] = field(default_factory=tuple)
    limitations: tuple[str, ...] = field(default_factory=tuple)
    blocked_sources: tuple[str, ...] = field(default_factory=tuple)
    status: str = PENDING_EVIDENCE_STATUS
    source_system: str = "knowledge"
    schema_version: str = KNOWLEDGE_EVIDENCE_BUNDLE_SCHEMA_VERSION
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "KnowledgeEvidenceBundle":
        if not isinstance(payload, dict):
            raise KnowledgeEvidenceContractError("knowledge evidence bundle must be an object")
        raw_items = payload.get("evidence_items")
        if raw_items is None:
            raw_items = payload.get("items")
        if raw_items is None:
            raw_items = []
        if not isinstance(raw_items, list):
            raise KnowledgeEvidenceContractError("knowledge evidence bundle evidence_items must be a list")
        blocked_sources = _clean_list(payload.get("blocked_sources"))
        limitations = _clean_list(payload.get("limitations"))
        if _clean_text(payload.get("reply")) and not raw_items:
            limitations = (*limitations, "Knowledge reply text is not typed evidence.")
            blocked_sources = (*blocked_sources, "knowledge_reply")
        items = tuple(EvidenceItem.from_dict(item) for item in raw_items)
        status = _clean_text(payload.get("status")) or PENDING_EVIDENCE_STATUS
        if not items:
            status = PENDING_EVIDENCE_STATUS
        return cls(
            bundle_id=_clean_text(payload.get("bundle_id")),
            query=_clean_text(payload.get("query")),
            evidence_items=items,
            citations=_clean_list(payload.get("citations")),
            limitations=limitations,
            blocked_sources=blocked_sources,
            status=status,
            source_system=_clean_text(payload.get("source_system")) or "knowledge",
            schema_version=_clean_text(payload.get("schema_version")) or KNOWLEDGE_EVIDENCE_BUNDLE_SCHEMA_VERSION,
            metadata=_clean_mapping(payload.get("metadata")),
        )

    def __post_init__(self) -> None:
        items = tuple(
            item if isinstance(item, EvidenceItem) else EvidenceItem.from_dict(item)
            for item in self.evidence_items
        )
        citations = _dedupe((*_clean_list(self.citations), *(citation for item in items for citation in item.citations)))
        limitations = _dedupe((*_clean_list(self.limitations), *(note for item in items for note in item.limitations)))
        blocked_sources = _dedupe((*_clean_list(self.blocked_sources), *(source for item in items for source in item.blocked_sources)))
        status = _clean_text(self.status) or (PENDING_EVIDENCE_STATUS if not items else "ready")
        object.__setattr__(self, "bundle_id", _clean_text(self.bundle_id))
        object.__setattr__(self, "query", _clean_text(self.query))
        object.__setattr__(self, "evidence_items", items)
        object.__setattr__(self, "citations", citations)
        object.__setattr__(self, "limitations", limitations)
        object.__setattr__(self, "blocked_sources", blocked_sources)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "source_system", _clean_text(self.source_system) or "knowledge")
        object.__setattr__(self, "schema_version", _clean_text(self.schema_version) or KNOWLEDGE_EVIDENCE_BUNDLE_SCHEMA_VERSION)
        object.__setattr__(self, "metadata", _clean_mapping(self.metadata))

    @property
    def ready_items(self) -> tuple[EvidenceItem, ...]:
        return tuple(item for item in self.evidence_items if item.is_ready)

    def require_ready(self) -> "KnowledgeEvidenceBundle":
        if not self.evidence_items:
            raise InsufficientKnowledgeEvidence(
                "typed KnowledgeEvidenceBundle has no evidence_items",
                limitations=self.limitations,
                blocked_sources=self.blocked_sources,
            )
        ready_items = self.ready_items
        if not ready_items:
            raise InsufficientKnowledgeEvidence(
                "typed KnowledgeEvidenceBundle has no ready evidence_items",
                limitations=self.limitations,
                blocked_sources=self.blocked_sources,
            )
        for item in ready_items:
            item.validate()
        return self

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "bundle_id": self.bundle_id,
            "query": self.query,
            "source_system": self.source_system,
            "status": self.status,
            "evidence_items": [item.to_dict() for item in self.evidence_items],
            "citations": list(self.citations),
            "limitations": list(self.limitations),
            "blocked_sources": list(self.blocked_sources),
            "metadata": dict(self.metadata),
        }


def coerce_knowledge_evidence_bundle(value: KnowledgeEvidenceBundle | dict[str, Any] | None) -> KnowledgeEvidenceBundle:
    if isinstance(value, KnowledgeEvidenceBundle):
        return value
    if isinstance(value, dict):
        return KnowledgeEvidenceBundle.from_dict(value)
    return KnowledgeEvidenceBundle(
        status=PENDING_EVIDENCE_STATUS,
        limitations=("Typed KnowledgeEvidenceBundle is required before Growth LLM generation.",),
        blocked_sources=("knowledge_evidence_bundle",),
    )


def _source_hash(*, source_url: str, source_type: str, text_or_summary: str) -> str:
    payload = json.dumps(
        {
            "source_url": source_url,
            "source_type": source_type,
            "text_or_summary": text_or_summary,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _clean_list(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    raw = [value] if isinstance(value, str) else list(value) if isinstance(value, (list, tuple, set)) else []
    return _dedupe(str(item or "").strip() for item in raw if str(item or "").strip())


def _clean_mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _dedupe(values: Any) -> tuple[str, ...]:
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in result:
            result.append(text)
    return tuple(result)
