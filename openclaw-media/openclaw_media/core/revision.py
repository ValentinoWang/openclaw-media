from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import PurePosixPath
from typing import Any, Iterable


_IDENTITY = re.compile(r"sha256:[0-9a-f]{64}")
_WINDOWS_ABSOLUTE = re.compile(r"^[a-zA-Z]:[/\\]")
_ARTIFACT_KINDS = ("storyboard", "edl", "editor_artifact")


@dataclass(frozen=True)
class RevisionArtifact:
    artifact_id: str
    kind: str
    artifact_ref: str
    identity_ref: str


@dataclass(frozen=True)
class Revision:
    revision_ref: str
    identity_ref: str
    parent_identity_ref: str | None
    artifacts: tuple[RevisionArtifact, ...]


@dataclass(frozen=True)
class RevisionChange:
    change_id: str
    sequence: int
    artifact_id: str
    expected_identity_ref: str
    updated_ref: str
    updated_identity_ref: str
    operation: str


@dataclass(frozen=True)
class RevisionConfirmation:
    confirmation_ref: str
    confirmed: bool


@dataclass(frozen=True)
class RevisionIssue:
    scope: str
    ref: str | None
    error_code: str


@dataclass(frozen=True)
class ChangeReceipt:
    contract: str
    status: str
    base_revision_identity_ref: str | None
    revision_identity_ref: str | None
    confirmation_ref: str | None
    change_set_identity_ref: str | None
    applied_change_ids: tuple[str, ...]
    error_codes: tuple[str, ...]


@dataclass(frozen=True)
class AIEditLogEntry:
    change_id: str
    sequence: int
    artifact_id: str
    artifact_kind: str
    operation: str
    prior_ref: str
    prior_identity_ref: str
    updated_ref: str
    updated_identity_ref: str


@dataclass(frozen=True)
class AIEditLog:
    contract: str
    revision_identity_ref: str
    entries: tuple[AIEditLogEntry, ...]


@dataclass(frozen=True)
class RevisionResult:
    status: str
    revision: Revision | None
    receipt: ChangeReceipt
    ai_edit_log: AIEditLog | None
    issues: tuple[RevisionIssue, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _ref(value: object) -> bool:
    if not isinstance(value, str) or not value or "\\" in value or _WINDOWS_ABSOLUTE.match(value):
        return False
    path = PurePosixPath(value)
    return not path.is_absolute() and ".." not in path.parts


def _identity(value: object) -> bool:
    return isinstance(value, str) and _IDENTITY.fullmatch(value) is not None


def _issue_ref(value: object) -> str | None:
    return value if _ref(value) else None


def _digest(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _rejected(
    issues: Iterable[RevisionIssue],
    *,
    base_identity: str | None = None,
    confirmation_ref: str | None = None,
) -> RevisionResult:
    ordered = tuple(sorted(issues, key=lambda item: (item.scope, item.ref or "", item.error_code)))
    receipt = ChangeReceipt(
        "media.edit.revise.change-receipt.v1",
        "rejected",
        base_identity if _identity(base_identity) else None,
        None,
        confirmation_ref if _ref(confirmation_ref) else None,
        None,
        (),
        tuple(sorted({item.error_code for item in ordered})),
    )
    return RevisionResult("rejected", None, receipt, None, ordered)


def create_revision(
    base_revision: Revision,
    changes: Iterable[RevisionChange],
    confirmation: RevisionConfirmation,
) -> RevisionResult:
    """Create one deterministic revision only from a valid, explicitly confirmed change set."""
    if not isinstance(confirmation, RevisionConfirmation):
        return _rejected((RevisionIssue("confirmation", None, "invalid_input"),))
    if not _ref(confirmation.confirmation_ref) or not isinstance(confirmation.confirmed, bool):
        return _rejected((RevisionIssue("confirmation", _issue_ref(confirmation.confirmation_ref), "invalid_input"),))
    if not confirmation.confirmed:
        base_identity = getattr(base_revision, "identity_ref", None)
        return _rejected(
            (RevisionIssue("confirmation", confirmation.confirmation_ref, "unconfirmed_change"),),
            base_identity=base_identity,
            confirmation_ref=confirmation.confirmation_ref,
        )

    try:
        change_items = list(changes)
    except Exception:
        return _rejected(
            (RevisionIssue("change", None, "invalid_input"),),
            base_identity=getattr(base_revision, "identity_ref", None),
            confirmation_ref=confirmation.confirmation_ref,
        )

    if not isinstance(base_revision, Revision):
        return _rejected(
            (RevisionIssue("revision", None, "invalid_input"),),
            confirmation_ref=confirmation.confirmation_ref,
        )
    try:
        artifact_items = list(base_revision.artifacts)
    except Exception:
        return _rejected(
            (RevisionIssue("revision", None, "invalid_input"),),
            base_identity=base_revision.identity_ref,
            confirmation_ref=confirmation.confirmation_ref,
        )

    issues: list[RevisionIssue] = []
    if (
        not _ref(base_revision.revision_ref)
        or not _identity(base_revision.identity_ref)
        or (base_revision.parent_identity_ref is not None and not _identity(base_revision.parent_identity_ref))
    ):
        issues.append(RevisionIssue("revision", _issue_ref(base_revision.revision_ref), "invalid_input"))

    valid_artifacts: list[RevisionArtifact] = []
    for artifact in artifact_items:
        if (
            not isinstance(artifact, RevisionArtifact)
            or not _ref(artifact.artifact_id)
            or artifact.kind not in _ARTIFACT_KINDS
            or not _ref(artifact.artifact_ref)
            or not _identity(artifact.identity_ref)
        ):
            issues.append(RevisionIssue("artifact", _issue_ref(getattr(artifact, "artifact_id", None)), "invalid_input"))
        else:
            valid_artifacts.append(artifact)

    by_id: dict[str, RevisionArtifact] = {}
    by_kind: dict[str, RevisionArtifact] = {}
    for artifact in sorted(valid_artifacts, key=lambda item: (item.kind, item.artifact_id)):
        if artifact.artifact_id in by_id or artifact.kind in by_kind:
            issues.append(RevisionIssue("artifact", artifact.artifact_id, "artifact_conflict"))
            continue
        by_id[artifact.artifact_id] = artifact
        by_kind[artifact.kind] = artifact
    for kind in _ARTIFACT_KINDS:
        if kind not in by_kind:
            issues.append(RevisionIssue("artifact", kind, "missing_artifact"))

    valid_changes: list[RevisionChange] = []
    for change in change_items:
        if (
            not isinstance(change, RevisionChange)
            or not _ref(change.change_id)
            or not isinstance(change.sequence, int)
            or isinstance(change.sequence, bool)
            or change.sequence < 0
            or not _ref(change.artifact_id)
            or not _identity(change.expected_identity_ref)
            or not _ref(change.updated_ref)
            or not _identity(change.updated_identity_ref)
            or not _ref(change.operation)
        ):
            issues.append(RevisionIssue("change", _issue_ref(getattr(change, "change_id", None)), "invalid_input"))
        else:
            valid_changes.append(change)

    if not valid_changes and not change_items:
        issues.append(RevisionIssue("change", None, "invalid_input"))

    seen_change_ids: set[str] = set()
    seen_artifact_ids: set[str] = set()
    ordered_changes = sorted(valid_changes, key=lambda item: (item.sequence, item.change_id))
    for change in ordered_changes:
        if change.change_id in seen_change_ids or change.artifact_id in seen_artifact_ids:
            issues.append(RevisionIssue("change", change.change_id, "artifact_conflict"))
            continue
        seen_change_ids.add(change.change_id)
        seen_artifact_ids.add(change.artifact_id)
        artifact = by_id.get(change.artifact_id)
        if artifact is None:
            issues.append(RevisionIssue("change", change.change_id, "missing_artifact"))
        elif change.expected_identity_ref != artifact.identity_ref:
            issues.append(RevisionIssue("change", change.change_id, "artifact_conflict"))
        elif change.updated_ref == artifact.artifact_ref and change.updated_identity_ref == artifact.identity_ref:
            issues.append(RevisionIssue("change", change.change_id, "invalid_input"))

    if issues:
        return _rejected(
            issues,
            base_identity=base_revision.identity_ref,
            confirmation_ref=confirmation.confirmation_ref,
        )

    replacements = {change.artifact_id: change for change in ordered_changes}
    updated_artifacts: list[RevisionArtifact] = []
    log_entries: list[AIEditLogEntry] = []
    for artifact in sorted(valid_artifacts, key=lambda item: (_ARTIFACT_KINDS.index(item.kind), item.artifact_id)):
        change = replacements.get(artifact.artifact_id)
        if change is None:
            updated_artifacts.append(artifact)
            continue
        updated_artifacts.append(RevisionArtifact(artifact.artifact_id, artifact.kind, change.updated_ref, change.updated_identity_ref))
        log_entries.append(
            AIEditLogEntry(
                change.change_id,
                change.sequence,
                artifact.artifact_id,
                artifact.kind,
                change.operation,
                artifact.artifact_ref,
                artifact.identity_ref,
                change.updated_ref,
                change.updated_identity_ref,
            )
        )
    log_entries.sort(key=lambda item: (item.sequence, item.change_id))

    change_set_identity = _digest(
        {
            "contract": "media.edit.revise.change-set.v1",
            "base_revision_identity_ref": base_revision.identity_ref,
            "confirmation_ref": confirmation.confirmation_ref,
            "changes": [asdict(change) for change in ordered_changes],
        }
    )
    revision_identity = _digest(
        {
            "contract": "media.edit.revision.v1",
            "parent_identity_ref": base_revision.identity_ref,
            "change_set_identity_ref": change_set_identity,
            "artifacts": [asdict(artifact) for artifact in updated_artifacts],
        }
    )
    revision = Revision(
        f"revisions/{revision_identity.removeprefix('sha256:')}.json",
        revision_identity,
        base_revision.identity_ref,
        tuple(updated_artifacts),
    )
    receipt = ChangeReceipt(
        "media.edit.revise.change-receipt.v1",
        "applied",
        base_revision.identity_ref,
        revision_identity,
        confirmation.confirmation_ref,
        change_set_identity,
        tuple(change.change_id for change in ordered_changes),
        (),
    )
    edit_log = AIEditLog("media.edit.revise.ai-edit-log.v1", revision_identity, tuple(log_entries))
    return RevisionResult("ok", revision, receipt, edit_log, ())
