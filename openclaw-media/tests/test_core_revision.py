from __future__ import annotations

import copy
import json

from openclaw_media.core import (
    Revision,
    RevisionArtifact,
    RevisionChange,
    RevisionConfirmation,
    create_revision,
)


IDENTITY_BASE = "sha256:" + "0" * 64
IDENTITY_STORYBOARD = "sha256:" + "1" * 64
IDENTITY_EDL = "sha256:" + "2" * 64
IDENTITY_EDITOR = "sha256:" + "3" * 64
IDENTITY_STORYBOARD_V2 = "sha256:" + "a" * 64
IDENTITY_EDL_V2 = "sha256:" + "b" * 64
IDENTITY_EDITOR_V2 = "sha256:" + "c" * 64


def _base(*artifacts: RevisionArtifact) -> Revision:
    default = (
        RevisionArtifact("storyboard", "storyboard", "artifacts/storyboard.json", IDENTITY_STORYBOARD),
        RevisionArtifact("edl", "edl", "artifacts/edit-list.json", IDENTITY_EDL),
        RevisionArtifact("editor", "editor_artifact", "artifacts/timeline.otio", IDENTITY_EDITOR),
    )
    return Revision("revisions/base.json", IDENTITY_BASE, None, tuple(artifacts) or default)


def _change(
    change_id: str,
    sequence: int,
    artifact_id: str,
    expected: str,
    updated_ref: str,
    updated_identity: str,
    operation: str = "replace",
) -> RevisionChange:
    return RevisionChange(change_id, sequence, artifact_id, expected, updated_ref, updated_identity, operation)


def test_confirmed_revision_golden_updates_all_artifacts_and_builds_receipts() -> None:
    changes = [
        _change("editor-change", 3, "editor", IDENTITY_EDITOR, "artifacts/timeline-v2.otio", IDENTITY_EDITOR_V2, "relink"),
        _change("storyboard-change", 1, "storyboard", IDENTITY_STORYBOARD, "artifacts/storyboard-v2.json", IDENTITY_STORYBOARD_V2),
        _change("edl-change", 2, "edl", IDENTITY_EDL, "artifacts/edit-list-v2.json", IDENTITY_EDL_V2, "retime"),
    ]

    result = create_revision(_base(), changes, RevisionConfirmation("confirmations/review-7", True))

    assert result.status == "ok"
    assert result.revision is not None
    assert result.ai_edit_log is not None
    assert result.revision.identity_ref == "sha256:1f97df218ba388821b02697247951e937a3d9ac99a997b566fa45b63123cfcb1"
    assert result.receipt.change_set_identity_ref == "sha256:3e7f5e68c32ee322400f2e377a69ee83b5e25c2eff97884069fd3f5cb67fcadb"
    assert result.revision.revision_ref == f"revisions/{result.revision.identity_ref.removeprefix('sha256:')}.json"
    assert result.revision.parent_identity_ref == IDENTITY_BASE
    assert [(item.kind, item.artifact_ref) for item in result.revision.artifacts] == [
        ("storyboard", "artifacts/storyboard-v2.json"),
        ("edl", "artifacts/edit-list-v2.json"),
        ("editor_artifact", "artifacts/timeline-v2.otio"),
    ]
    assert result.receipt.status == "applied"
    assert result.receipt.applied_change_ids == ("storyboard-change", "edl-change", "editor-change")
    assert [entry.change_id for entry in result.ai_edit_log.entries] == ["storyboard-change", "edl-change", "editor-change"]
    assert result.ai_edit_log.revision_identity_ref == result.revision.identity_ref


def test_unconfirmed_change_set_never_creates_a_revision() -> None:
    result = create_revision(
        _base(),
        [_change("change-1", 1, "storyboard", IDENTITY_STORYBOARD, "artifacts/storyboard-v2.json", IDENTITY_STORYBOARD_V2)],
        RevisionConfirmation("confirmations/pending", False),
    )

    assert result.status == "rejected"
    assert result.revision is None
    assert result.ai_edit_log is None
    assert result.receipt.status == "rejected"
    assert result.receipt.error_codes == ("unconfirmed_change",)
    assert result.receipt.revision_identity_ref is None


def test_revision_is_idempotent_ordered_non_ascii_and_does_not_mutate_inputs() -> None:
    base = _base()
    changes = [
        _change("字幕调整", 2, "edl", IDENTITY_EDL, "产物/剪辑表-v2.json", IDENTITY_EDL_V2, "retime"),
        _change("分镜调整", 1, "storyboard", IDENTITY_STORYBOARD, "产物/分镜-v2.json", IDENTITY_STORYBOARD_V2),
    ]
    confirmation = RevisionConfirmation("确认/第七轮", True)
    before = copy.deepcopy((base, changes, confirmation))

    first = create_revision(base, changes, confirmation)
    second = create_revision(base, reversed(changes), confirmation)

    assert first == second
    assert (base, changes, confirmation) == before
    assert first.receipt.applied_change_ids == ("分镜调整", "字幕调整")
    assert [entry.sequence for entry in first.ai_edit_log.entries] == [1, 2]  # type: ignore[union-attr]


def test_missing_and_conflicting_artifacts_reject_the_entire_change_set() -> None:
    missing_editor = _base(
        RevisionArtifact("storyboard", "storyboard", "artifacts/storyboard.json", IDENTITY_STORYBOARD),
        RevisionArtifact("edl", "edl", "artifacts/edit-list.json", IDENTITY_EDL),
    )
    missing = create_revision(
        missing_editor,
        [_change("missing", 1, "editor", IDENTITY_EDITOR, "artifacts/timeline-v2.otio", IDENTITY_EDITOR_V2)],
        RevisionConfirmation("confirmations/approved", True),
    )
    conflict = create_revision(
        _base(),
        [_change("stale", 1, "edl", IDENTITY_STORYBOARD, "artifacts/edit-list-v2.json", IDENTITY_EDL_V2)],
        RevisionConfirmation("confirmations/approved", True),
    )

    assert missing.revision is None
    assert missing.receipt.error_codes == ("missing_artifact",)
    assert conflict.revision is None
    assert conflict.receipt.error_codes == ("artifact_conflict",)


def test_duplicate_targets_and_corrupt_descriptors_are_explicit_invalid_outcomes() -> None:
    duplicate = create_revision(
        _base(),
        [
            _change("first", 1, "edl", IDENTITY_EDL, "artifacts/edit-list-v2.json", IDENTITY_EDL_V2),
            _change("second", 2, "edl", IDENTITY_EDL, "artifacts/edit-list-v3.json", IDENTITY_EDITOR_V2),
        ],
        RevisionConfirmation("confirmations/approved", True),
    )
    corrupt = create_revision(
        _base(),
        [{"change_id": "not-a-descriptor"}],  # type: ignore[list-item]
        RevisionConfirmation("confirmations/approved", True),
    )

    assert duplicate.revision is None
    assert duplicate.receipt.error_codes == ("artifact_conflict",)
    assert corrupt.revision is None
    assert corrupt.receipt.error_codes == ("invalid_input",)


def test_noop_and_invalid_revision_descriptors_do_not_create_revisions() -> None:
    noop = create_revision(
        _base(),
        [_change("noop", 1, "edl", IDENTITY_EDL, "artifacts/edit-list.json", IDENTITY_EDL)],
        RevisionConfirmation("confirmations/approved", True),
    )
    invalid = create_revision(
        Revision("/home/private/base.json", IDENTITY_BASE, None, _base().artifacts),
        [],
        RevisionConfirmation("confirmations/approved", True),
    )

    assert noop.receipt.error_codes == ("invalid_input",)
    assert noop.revision is None
    assert invalid.receipt.error_codes == ("invalid_input",)
    assert invalid.revision is None


def test_absolute_paths_and_iterator_exceptions_never_leak() -> None:
    class BrokenChanges:
        def __iter__(self):
            raise RuntimeError("/home/private/secret-timeline.otio")

    invalid_path = create_revision(
        _base(),
        [_change("bad", 1, "editor", IDENTITY_EDITOR, "/home/private/timeline.otio", IDENTITY_EDITOR_V2)],
        RevisionConfirmation("confirmations/approved", True),
    )
    broken = create_revision(_base(), BrokenChanges(), RevisionConfirmation("confirmations/approved", True))

    serialized = json.dumps([invalid_path.to_dict(), broken.to_dict()], ensure_ascii=False, sort_keys=True)
    assert "/home/" not in serialized
    assert "RuntimeError" not in serialized
    assert invalid_path.receipt.error_codes == ("invalid_input",)
    assert broken.receipt.error_codes == ("invalid_input",)
