"""Read-only core for the U6 people recommendation flow.

The core deliberately knows nothing about HTTP, Feishu clients, or storage.
Callers inject a transport with these four read methods:

``get_directory_page(page_token)``
    Return a :class:`DirectoryPage` or a mapping with ``records``,
    ``has_more``, and ``next_page_token``.
``get_capability_records()``
    Return the independent capability record list keyed by ``directory_id``.
``get_tasks_snapshot()``
    Return the current Tasks snapshot.
``get_calendar_snapshot()``
    Return the current Calendar snapshot.

The injected LLM is a callable receiving a JSON-like mapping and returning
exactly ``{"assignments": [{"candidate_ref": ..., "role": ...}]}``.
Only the opaque candidate reference is ever sent to, or accepted from, the
LLM.  Directory IDs never leave the public API.  No workload or selection is
persisted; the workload digest is computed for the current call only.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence, Set
from dataclasses import dataclass
from datetime import date, datetime, timezone
from numbers import Real
from typing import Any, Callable, Optional, Protocol, Union

from common.social_runtime import parse_iso_datetime


JSONValue = Union[None, bool, int, float, str, list[Any], dict[str, Any]]


class RecommendationTransport(Protocol):
    """The read-only transport required by the core."""

    def get_directory_page(self, page_token: Optional[str]) -> Any:
        ...

    def get_capability_records(self) -> Any:
        ...

    def get_tasks_snapshot(self) -> Any:
        ...

    def get_calendar_snapshot(self) -> Any:
        ...


LLM = Callable[[Mapping[str, Any]], Any]


@dataclass(frozen=True)
class DirectoryPage:
    """A single complete Directory page returned by an injected transport."""

    records: Sequence[Mapping[str, Any]]
    has_more: bool
    next_page_token: Optional[str] = None


@dataclass(frozen=True)
class _Person:
    directory_id: str
    name: str
    department: Any
    capability: Optional[Mapping[str, Any]]


@dataclass(frozen=True)
class _Candidate:
    ref: str
    person: _Person


@dataclass(frozen=True)
class _Workload:
    tasks: Any
    calendar: Any
    fingerprint: str


class _EvidenceFailure(Exception):
    """An internal, non-sensitive failure code for a pending/manual result."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


_DIRECTORY_FIELDS = frozenset(("directory_id", "name", "department"))
_CAPABILITY_FIELDS = frozenset((
    "status",
    "confirmation_time",
    "expiry_time",
    "maintainer",
    "responsibilities",
    "skills",
    "roles",
    "evidence",
    "declared_hours",
    "unavailable_intervals",
))
_ALLOWED_ASSIGNMENT_ROLES = frozenset(("DRI", "Reviewer", "Participant"))
_ROLE_LIMITS = {"DRI": 1, "Reviewer": 1}


def _identifier_key(key: Any) -> bool:
    """Return whether a field name is an identifier/token field."""

    normalized = re.sub(r"[^a-z0-9]+", "_", str(key).lower()).strip("_")
    if normalized == "candidate_ref":
        return False
    if normalized in {
        "id",
        "directory_id",
        "directoryid",
        "record_id",
        "recordid",
        "task_id",
        "taskid",
        "event_id",
        "eventid",
        "calendar_id",
        "calendarid",
        "user_id",
        "userid",
        "open_id",
        "openid",
        "union_id",
        "unionid",
    }:
        return True
    return normalized.endswith("_id") or normalized.endswith("_token") or normalized.endswith("token")


def _canonical_json_value(value: Any) -> JSONValue:
    """Convert a JSON-like snapshot into a stable, strictly typed value."""

    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise _EvidenceFailure("invalid_snapshot")
        return value
    if isinstance(value, datetime):
        return _as_utc(value).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Mapping):
        result: dict[str, JSONValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise _EvidenceFailure("invalid_snapshot")
            result[key] = _canonical_json_value(item)
        return {key: result[key] for key in sorted(result)}
    if isinstance(value, (list, tuple)):
        return [_canonical_json_value(item) for item in value]
    if isinstance(value, Set) and not isinstance(value, (str, bytes, bytearray)):
        canonical_items = [_canonical_json_value(item) for item in value]
        return sorted(canonical_items, key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True))
    raise _EvidenceFailure("invalid_snapshot")


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_datetime(value: Any) -> Optional[datetime]:
    # Thin wrapper around common/social_runtime.parse_iso_datetime (H9) --
    # this was the canonical basis that function's core logic was taken
    # from. The isinstance guard is kept so a value that is none of
    # datetime/date/str (e.g. a raw int) still returns None exactly as
    # before, rather than being coerced through str().
    if not isinstance(value, (datetime, date, str)):
        return None
    if isinstance(value, str) and not value.strip():
        return None
    return parse_iso_datetime(value, assume_tz=timezone.utc, convert_to=timezone.utc)


def _nonempty(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (Mapping, Sequence, Set)) and not isinstance(value, (bytes, bytearray)):
        return len(value) > 0
    return False


def _redact(value: Any, sensitive_ids: Set[str]) -> Any:
    """Make a JSON-like public value without identifier fields or values."""

    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if _identifier_key(key):
                continue
            result[str(key)] = _redact(item, sensitive_ids)
        return result
    if isinstance(value, (list, tuple)):
        return [_redact(item, sensitive_ids) for item in value]
    if isinstance(value, Set) and not isinstance(value, (str, bytes, bytearray)):
        return [_redact(item, sensitive_ids) for item in value]
    if isinstance(value, datetime):
        return _as_utc(value).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        redacted = value
        for identifier in sorted((item for item in sensitive_ids if item), key=len, reverse=True):
            redacted = redacted.replace(identifier, "[redacted]")
        return redacted
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return "[unavailable]"


def _collect_identifier_values(value: Any, result: set[str]) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if _identifier_key(key) and isinstance(item, str) and item:
                result.add(item)
            _collect_identifier_values(item, result)
    elif isinstance(value, (list, tuple, Set)) and not isinstance(value, (str, bytes, bytearray)):
        for item in value:
            _collect_identifier_values(item, result)


def _collect_string_leaves(value: Any, result: set[str]) -> None:
    if isinstance(value, str) and value:
        result.add(value)
    elif isinstance(value, Mapping):
        for item in value.values():
            _collect_string_leaves(item, result)
    elif isinstance(value, (list, tuple, Set)) and not isinstance(value, (str, bytes, bytearray)):
        for item in value:
            _collect_string_leaves(item, result)


class DeepMathPeopleRecommendation:
    """Pure read/validate/recommend core with an injected transport and LLM."""

    def __init__(self, transport: RecommendationTransport, llm: LLM, clock: Optional[Callable[[], datetime]] = None) -> None:
        self._transport = transport
        self._llm = llm
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def recommend(
        self,
        *,
        now: Optional[datetime] = None,
        requested_name: Optional[str] = None,
        department: Optional[str] = None,
        task_context: Optional[Mapping[str, Any]] = None,
    ) -> dict[str, Any]:
        """Read evidence, ask the strict LLM, and return a public result.

        ``department`` is included as request evidence only.  It never filters
        or ranks candidates, so a valid cross-department candidate remains
        eligible.
        """

        try:
            effective_now = self._effective_now(now)
            people = self._read_directory()
            if requested_name is not None:
                people = self._select_exact_name(people, requested_name)
            candidates = self._eligible_candidates(people, effective_now)
            if not candidates:
                raise _EvidenceFailure("no_eligible_candidate")

            workload = self._read_workload()
            sensitive_ids = {person.directory_id for person in people}
            for person in people:
                if not isinstance(person.department, str):
                    _collect_string_leaves(person.department, sensitive_ids)
            _collect_identifier_values(workload.tasks, sensitive_ids)
            _collect_identifier_values(workload.calendar, sensitive_ids)
            llm_request = self._build_llm_request(
                candidates=candidates,
                workload=workload,
                task_context=task_context,
                department=department,
                sensitive_ids=sensitive_ids,
            )
            assignments = self._read_llm_assignments(llm_request, {candidate.ref for candidate in candidates})
            return {
                "status": "recommended",
                "workload_fingerprint": workload.fingerprint,
                "candidates": [self._public_candidate(candidate, sensitive_ids) for candidate in candidates],
                "recommendation": assignments,
            }
        except _EvidenceFailure as failure:
            return self._pending(failure.code)
        except Exception:
            return self._pending("evidence_failure")

    def lookup_by_name(self, name: str, *, now: Optional[datetime] = None) -> dict[str, Any]:
        """Resolve one exact Directory name, rejecting zero or multiple matches."""

        try:
            effective_now = self._effective_now(now)
            people = self._read_directory()
            matches = self._select_exact_name(people, name)
            candidates = self._eligible_candidates(matches, effective_now)
            if len(candidates) != 1:
                raise _EvidenceFailure("person_not_eligible")
            sensitive_ids = {person.directory_id for person in people}
            for person in people:
                if not isinstance(person.department, str):
                    _collect_string_leaves(person.department, sensitive_ids)
            return {
                "status": "found",
                "candidate": self._public_candidate(candidates[0], sensitive_ids),
            }
        except _EvidenceFailure as failure:
            return self._pending(failure.code)
        except Exception:
            return self._pending("evidence_failure")

    def validate_human_selection(
        self,
        selection: Mapping[str, Any],
        workload_fingerprint: Optional[str] = None,
        *,
        now: Optional[datetime] = None,
    ) -> dict[str, Any]:
        """Validate a human selection against fresh evidence and workload."""

        try:
            workload, assignments, _ = self._validate_selection_against_current_evidence(
                selection,
                workload_fingerprint,
                now=now,
            )
            return {
                "status": "accepted",
                "workload_fingerprint": workload.fingerprint,
                "selection": assignments,
            }
        except _EvidenceFailure as failure:
            return self._pending(failure.code)
        except Exception:
            return self._pending("evidence_failure")

    def _resolve_private_selection(
        self,
        selection: Mapping[str, Any],
        workload_fingerprint: Optional[str] = None,
        *,
        now: Optional[datetime] = None,
    ) -> dict[str, Any]:
        """Resolve an accepted selection to exact IDs for a private payload.

        This method is intentionally private.  It reads Directory,
        capabilities, Tasks, and Calendar again, verifies the supplied
        workload fingerprint, validates the opaque references, and only then
        creates a new private assignment payload containing exact IDs.
        """

        try:
            workload, assignments, candidates_by_ref = self._validate_selection_against_current_evidence(
                selection,
                workload_fingerprint,
                now=now,
            )
            return {
                "status": "accepted",
                "workload_fingerprint": workload.fingerprint,
                "assignments": [
                    {
                        "directory_id": candidates_by_ref[assignment["candidate_ref"]].person.directory_id,
                        "role": assignment["role"],
                    }
                    for assignment in assignments
                ],
            }
        except _EvidenceFailure as failure:
            return self._pending(failure.code)
        except Exception:
            return self._pending("evidence_failure")

    def _validate_selection_against_current_evidence(
        self,
        selection: Mapping[str, Any],
        workload_fingerprint: Optional[str],
        *,
        now: Optional[datetime],
    ) -> tuple[_Workload, list[dict[str, str]], dict[str, _Candidate]]:
        if not isinstance(selection, Mapping):
            raise _EvidenceFailure("invalid_selection")
        embedded_fingerprint = selection.get("workload_fingerprint")
        expected_fingerprint = workload_fingerprint
        if expected_fingerprint is None:
            expected_fingerprint = embedded_fingerprint
        elif embedded_fingerprint is not None and embedded_fingerprint != expected_fingerprint:
            raise _EvidenceFailure("workload_fingerprint_mismatch")
        if not isinstance(expected_fingerprint, str) or not expected_fingerprint:
            raise _EvidenceFailure("missing_workload_fingerprint")

        effective_now = self._effective_now(now)
        people = self._read_directory()
        candidates = self._eligible_candidates(people, effective_now)
        if not candidates:
            raise _EvidenceFailure("no_eligible_candidate")
        workload = self._read_workload()
        if workload.fingerprint != expected_fingerprint:
            raise _EvidenceFailure("workload_drift")

        assignments = self._validate_assignments(
            selection.get("assignments"),
            {candidate.ref for candidate in candidates},
        )
        return workload, assignments, {candidate.ref: candidate for candidate in candidates}

    def _effective_now(self, value: Optional[datetime]) -> datetime:
        candidate = self._clock() if value is None else value
        parsed = _parse_datetime(candidate)
        if parsed is None:
            raise _EvidenceFailure("invalid_time")
        return parsed

    def _read_directory(self) -> list[_Person]:
        records: list[Mapping[str, Any]] = []
        requested_tokens: set[Optional[str]] = set()
        page_token: Optional[str] = None

        while True:
            if page_token in requested_tokens:
                raise _EvidenceFailure("repeated_page_token")
            requested_tokens.add(page_token)
            try:
                page = self._transport.get_directory_page(page_token)
            except PermissionError:
                raise _EvidenceFailure("permission_failure") from None
            except Exception:
                raise _EvidenceFailure("evidence_failure") from None

            page_records, has_more, next_page_token = self._parse_directory_page(page)
            records.extend(page_records)
            if not has_more:
                break
            if not isinstance(next_page_token, str) or not next_page_token:
                raise _EvidenceFailure("missing_page_token")
            if next_page_token in requested_tokens:
                raise _EvidenceFailure("repeated_page_token")
            page_token = next_page_token

        directory_records: list[tuple[str, str, Any]] = []
        seen_directory_ids: set[str] = set()
        for record in records:
            if not isinstance(record, Mapping):
                raise _EvidenceFailure("invalid_directory_record")
            if set(record) != _DIRECTORY_FIELDS:
                if "capability" in record or any(key in _CAPABILITY_FIELDS for key in record):
                    raise _EvidenceFailure("embedded_capability")
                raise _EvidenceFailure("invalid_directory_record")
            directory_id = record.get("directory_id")
            if not isinstance(directory_id, str) or not directory_id.strip():
                raise _EvidenceFailure("invalid_directory_identity")
            if directory_id in seen_directory_ids:
                raise _EvidenceFailure("duplicate_identity")
            seen_directory_ids.add(directory_id)

            name = record.get("name")
            if not isinstance(name, str) or not name.strip():
                raise _EvidenceFailure("invalid_directory_name")
            directory_records.append((directory_id, name, record.get("department")))

        capabilities = self._read_capability_records(seen_directory_ids)
        return [
            _Person(
                directory_id=directory_id,
                name=name,
                department=department,
                capability=capabilities.get(directory_id),
            )
            for directory_id, name, department in directory_records
        ]

    @staticmethod
    def _parse_directory_page(page: Any) -> tuple[list[Mapping[str, Any]], bool, Optional[str]]:
        if isinstance(page, DirectoryPage):
            raw_records = page.records
            has_more = page.has_more
            next_page_token = page.next_page_token
        elif isinstance(page, Mapping):
            page_keys = set(page)
            required_keys = {"records", "has_more"}
            if page_keys not in {required_keys, required_keys | {"next_page_token"}}:
                raise _EvidenceFailure("invalid_directory_page")
            raw_records = page.get("records")
            if not isinstance(page.get("has_more"), bool):
                raise _EvidenceFailure("invalid_directory_page")
            has_more = page["has_more"]
            next_page_token = page.get("next_page_token")
        else:
            raise _EvidenceFailure("invalid_directory_page")

        if not isinstance(has_more, bool):
            raise _EvidenceFailure("invalid_directory_page")
        if isinstance(raw_records, (str, bytes, bytearray)) or not isinstance(raw_records, Sequence):
            raise _EvidenceFailure("invalid_directory_page")
        if next_page_token is not None and (
            not isinstance(next_page_token, str) or not next_page_token
        ):
            raise _EvidenceFailure("invalid_directory_page")
        return list(raw_records), has_more, next_page_token

    def _read_capability_records(self, directory_ids: set[str]) -> dict[str, Mapping[str, Any]]:
        try:
            records = self._transport.get_capability_records()
        except PermissionError:
            raise _EvidenceFailure("permission_failure") from None
        except Exception:
            raise _EvidenceFailure("evidence_failure") from None

        if not isinstance(records, list):
            raise _EvidenceFailure("invalid_capability_records")

        allowed_fields = _CAPABILITY_FIELDS | {"directory_id"}
        capabilities: dict[str, Mapping[str, Any]] = {}
        for record in records:
            if not isinstance(record, Mapping) or not set(record).issubset(allowed_fields):
                raise _EvidenceFailure("invalid_capability_record")
            directory_id = record.get("directory_id")
            if not isinstance(directory_id, str) or not directory_id.strip():
                raise _EvidenceFailure("invalid_capability_identity")
            if directory_id not in directory_ids:
                raise _EvidenceFailure("unknown_directory_id")
            if directory_id in capabilities:
                raise _EvidenceFailure("duplicate_capability_identity")
            capabilities[directory_id] = dict(record)
        return capabilities

    @staticmethod
    def _select_exact_name(people: Sequence[_Person], name: Any) -> list[_Person]:
        if not isinstance(name, str) or not name:
            raise _EvidenceFailure("name_not_found")
        matches = [person for person in people if person.name == name]
        if not matches:
            raise _EvidenceFailure("name_not_found")
        if len(matches) != 1:
            raise _EvidenceFailure("ambiguous_name")
        return matches

    @staticmethod
    def _eligible_candidates(people: Sequence[_Person], now: datetime) -> list[_Candidate]:
        candidates: list[_Candidate] = []
        for person in people:
            if not DeepMathPeopleRecommendation._is_eligible(person.capability, now):
                continue
            candidates.append(
                _Candidate(
                    ref=DeepMathPeopleRecommendation._candidate_ref(person.directory_id),
                    person=person,
                )
            )
        return candidates

    @staticmethod
    def _is_eligible(capability: Optional[Mapping[str, Any]], now: datetime) -> bool:
        if capability is None:
            return False
        if capability.get("status") != "有效":
            return False
        if _parse_datetime(capability.get("confirmation_time")) is None:
            return False
        expiry = _parse_datetime(capability.get("expiry_time"))
        if expiry is None or expiry <= now:
            return False
        if not _nonempty(capability.get("maintainer")):
            return False
        for field in ("responsibilities", "skills", "roles", "evidence"):
            if not _nonempty(capability.get(field)):
                return False
        hours = capability.get("declared_hours")
        if isinstance(hours, bool) or not isinstance(hours, Real):
            return False
        if not math.isfinite(float(hours)) or hours < 0:
            return False
        return True

    @staticmethod
    def _candidate_ref(directory_id: str) -> str:
        digest = hashlib.sha256(f"deepmath-candidate-v1\0{directory_id}".encode("utf-8")).hexdigest()
        return f"candidate_{digest}"

    @staticmethod
    def _read_workload_from_values(tasks: Any, calendar: Any) -> _Workload:
        canonical = {
            "calendar": _canonical_json_value(calendar),
            "tasks": _canonical_json_value(tasks),
        }
        encoded = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        fingerprint = hashlib.sha256(encoded).hexdigest()
        return _Workload(tasks=tasks, calendar=calendar, fingerprint=fingerprint)

    def _read_workload(self) -> _Workload:
        try:
            tasks = self._transport.get_tasks_snapshot()
        except PermissionError:
            raise _EvidenceFailure("permission_failure") from None
        except Exception:
            raise _EvidenceFailure("evidence_failure") from None
        try:
            calendar = self._transport.get_calendar_snapshot()
        except PermissionError:
            raise _EvidenceFailure("permission_failure") from None
        except Exception:
            raise _EvidenceFailure("evidence_failure") from None
        return self._read_workload_from_values(tasks, calendar)

    @staticmethod
    def _build_llm_request(
        *,
        candidates: Sequence[_Candidate],
        workload: _Workload,
        task_context: Optional[Mapping[str, Any]],
        department: Optional[str],
        sensitive_ids: Set[str],
    ) -> dict[str, Any]:
        public_candidates = [
            DeepMathPeopleRecommendation._public_candidate(candidate, sensitive_ids) for candidate in candidates
        ]
        return {
            "contract": {
                "assignments": "list of objects with candidate_ref and role",
                "candidate_ref": "must be copied exactly from candidates",
                "role": ["DRI", "Reviewer", "Participant"],
                "maximum_per_role": {"DRI": 1, "Reviewer": 1, "Participant": None},
            },
            "department_evidence": _redact(department, sensitive_ids),
            "task_context": _redact(task_context, sensitive_ids),
            "workload": {
                "tasks": _redact(workload.tasks, sensitive_ids),
                "calendar": _redact(workload.calendar, sensitive_ids),
            },
            "workload_fingerprint": workload.fingerprint,
            "candidates": public_candidates,
        }

    def _read_llm_assignments(self, request: Mapping[str, Any], valid_refs: set[str]) -> list[dict[str, str]]:
        try:
            result = self._llm(request)
        except Exception:
            raise _EvidenceFailure("llm_failure") from None
        try:
            if not isinstance(result, Mapping) or set(result.keys()) != {"assignments"}:
                raise _EvidenceFailure("llm_schema_failure")
            return self._validate_assignments(result.get("assignments"), valid_refs)
        except _EvidenceFailure:
            raise
        except Exception:
            raise _EvidenceFailure("llm_schema_failure") from None

    @staticmethod
    def _validate_assignments(value: Any, valid_refs: set[str]) -> list[dict[str, str]]:
        if not isinstance(value, list) or not value:
            raise _EvidenceFailure("invalid_selection")
        role_counts: dict[str, int] = {}
        used_refs: set[str] = set()
        normalized: list[dict[str, str]] = []
        for assignment in value:
            if not isinstance(assignment, Mapping) or set(assignment.keys()) != {"candidate_ref", "role"}:
                raise _EvidenceFailure("invalid_assignment")
            candidate_ref = assignment.get("candidate_ref")
            role = assignment.get("role")
            if not isinstance(candidate_ref, str) or candidate_ref not in valid_refs:
                raise _EvidenceFailure("invented_candidate_ref")
            if not isinstance(role, str) or role not in _ALLOWED_ASSIGNMENT_ROLES:
                raise _EvidenceFailure("invalid_role")
            role_counts[role] = role_counts.get(role, 0) + 1
            if role in _ROLE_LIMITS and role_counts[role] > _ROLE_LIMITS[role]:
                raise _EvidenceFailure("duplicate_role")
            if candidate_ref in used_refs:
                raise _EvidenceFailure("duplicate_candidate_ref")
            used_refs.add(candidate_ref)
            normalized.append({"candidate_ref": candidate_ref, "role": role})
        return normalized

    @staticmethod
    def _public_candidate(candidate: _Candidate, sensitive_ids: Set[str]) -> dict[str, Any]:
        capability = candidate.person.capability or {}
        return {
            "candidate_ref": candidate.ref,
            "name": _redact(candidate.person.name, sensitive_ids),
            "department": _redact(candidate.person.department, sensitive_ids),
            "status": _redact(capability.get("status"), sensitive_ids),
            "confirmation_time": _redact(capability.get("confirmation_time"), sensitive_ids),
            "expiry_time": _redact(capability.get("expiry_time"), sensitive_ids),
            "maintainer": _redact(capability.get("maintainer"), sensitive_ids),
            "responsibilities": _redact(capability.get("responsibilities"), sensitive_ids),
            "skills": _redact(capability.get("skills"), sensitive_ids),
            "roles": _redact(capability.get("roles"), sensitive_ids),
            "evidence": _redact(capability.get("evidence"), sensitive_ids),
            "declared_hours": _redact(capability.get("declared_hours"), sensitive_ids),
            "unavailable_intervals": _redact(capability.get("unavailable_intervals"), sensitive_ids),
        }

    @staticmethod
    def _pending(reason: str) -> dict[str, Any]:
        return {
            "status": "pending_manual",
            "reason": reason,
            "workload_fingerprint": None,
            "candidates": [],
            "recommendation": [],
        }


RecommendationService = DeepMathPeopleRecommendation


def recommend_people(
    transport: RecommendationTransport,
    llm: LLM,
    *,
    now: Optional[datetime] = None,
    requested_name: Optional[str] = None,
    department: Optional[str] = None,
    task_context: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Convenience wrapper that creates one read-only recommendation core."""

    return DeepMathPeopleRecommendation(transport, llm).recommend(
        now=now,
        requested_name=requested_name,
        department=department,
        task_context=task_context,
    )


__all__ = [
    "DeepMathPeopleRecommendation",
    "DirectoryPage",
    "RecommendationService",
    "RecommendationTransport",
    "recommend_people",
]
