import json

from openclaw_media.core import (
    EDLEntry,
    LocalAssetReference,
    MaterialDescriptor,
    MaterialMatch,
    ShotRequest,
    StoryboardEntry,
    StoryboardFailure,
    StoryboardPlan,
    plan_storyboard,
)


def _material(ref, digest, duration=12.0, tags=(), kind="video"):
    return MaterialDescriptor(ref, kind, digest, duration, tuple(tags))


def test_storyboard_golden_is_ordered_deterministic_and_emits_edl_and_assets():
    a, b, c = (character * 64 for character in "abc")
    materials = [
        _material("素材/远景.mp4", b, tags=("outdoor", "wide", "calm")),
        _material("素材/人物.mp4", a, tags=("person", "close", "calm")),
        _material("重复/人物副本.mp4", a, tags=("calm", "close", "person")),
        _material("音频/旁白.wav", c, tags=("voice",), kind="audio"),
    ]
    shots = [
        ShotRequest("ending", 20, 2.0, 3.0, ("outdoor",), ("wide",)),
        ShotRequest("opening", 10, 1.5, 1.0, ("person",), ("close",)),
    ]

    first = plan_storyboard(materials, shots).to_dict()
    assert first == plan_storyboard(reversed(materials), reversed(shots)).to_dict()
    assert first == {
        "status": "ok",
        "matches": (
            {
                "shot_id": "opening",
                "status": "matched",
                "error_code": None,
                "material_ref": "素材/人物.mp4",
                "identity_ref": f"sha256:{a}",
                "candidate_identity_refs": (f"sha256:{a}",),
                "score": 1,
            },
            {
                "shot_id": "ending",
                "status": "matched",
                "error_code": None,
                "material_ref": "素材/远景.mp4",
                "identity_ref": f"sha256:{b}",
                "candidate_identity_refs": (f"sha256:{b}",),
                "score": 1,
            },
        ),
        "storyboard": (
            {
                "shot_id": "opening",
                "sequence": 10,
                "timeline_in_seconds": 0.0,
                "timeline_out_seconds": 1.5,
                "duration_seconds": 1.5,
                "match_status": "matched",
                "error_code": None,
                "material_ref": "素材/人物.mp4",
                "identity_ref": f"sha256:{a}",
            },
            {
                "shot_id": "ending",
                "sequence": 20,
                "timeline_in_seconds": 1.5,
                "timeline_out_seconds": 3.5,
                "duration_seconds": 2.0,
                "match_status": "matched",
                "error_code": None,
                "material_ref": "素材/远景.mp4",
                "identity_ref": f"sha256:{b}",
            },
        ),
        "edl": (
            {
                "edit_id": "edit-0001",
                "shot_id": "opening",
                "sequence": 10,
                "timeline_in_seconds": 0.0,
                "timeline_out_seconds": 1.5,
                "source_in_seconds": 1.0,
                "source_out_seconds": 2.5,
                "material_ref": "素材/人物.mp4",
                "identity_ref": f"sha256:{a}",
            },
            {
                "edit_id": "edit-0002",
                "shot_id": "ending",
                "sequence": 20,
                "timeline_in_seconds": 1.5,
                "timeline_out_seconds": 3.5,
                "source_in_seconds": 3.0,
                "source_out_seconds": 5.0,
                "material_ref": "素材/远景.mp4",
                "identity_ref": f"sha256:{b}",
            },
        ),
        "local_assets": (
            {
                "identity_ref": f"sha256:{a}",
                "material_ref": "素材/人物.mp4",
                "duplicate_refs": ("重复/人物副本.mp4",),
                "kind": "video",
                "sha256": a,
                "duration_seconds": 12.0,
            },
            {
                "identity_ref": f"sha256:{b}",
                "material_ref": "素材/远景.mp4",
                "duplicate_refs": (),
                "kind": "video",
                "sha256": b,
                "duration_seconds": 12.0,
            },
        ),
        "failures": (),
    }


def test_stable_tie_is_ambiguous_and_unmatched_is_explicit():
    a, b = (character * 64 for character in "ab")
    materials = [
        _material("b/clip.mp4", b, tags=("city", "night")),
        _material("a/clip.mp4", a, tags=("city", "night")),
    ]
    result = plan_storyboard(
        materials,
        [
            ShotRequest("tie", 1, 1.0, required_tags=("city",), preferred_tags=("night",)),
            ShotRequest("missing", 2, 1.0, required_tags=("forest",)),
        ],
    )

    assert result.status == "failed"
    assert result.matches[0] == MaterialMatch("tie", "ambiguous", "ambiguous", None, None, (f"sha256:{a}", f"sha256:{b}"), 1)
    assert result.matches[1] == MaterialMatch("missing", "unmatched", "unmatched", None, None, (), None)
    assert [entry.match_status for entry in result.storyboard] == ["ambiguous", "unmatched"]
    assert result.edl == () and result.local_assets == ()


def test_invalid_timing_and_corrupt_descriptors_are_sanitized():
    digest = "d" * 64
    result = plan_storyboard(
        [
            _material("safe/short.mp4", digest, duration=2.0, tags=("short",)),
            _material("/home/private/secret.mp4", "a" * 64, tags=("secret",)),
            _material("C:/private/secret.mp4", "b" * 64, tags=("secret",)),
            _material("safe/bad.mp4", "not-a-hash", tags=("bad",)),
        ],
        [
            ShotRequest("too-long", 1, 2.0, 1.0, required_tags=("short",)),
            ShotRequest("bad-time", 2, float("nan")),
        ],
    )

    payload = json.dumps(result.to_dict())
    assert result.status == "failed"
    assert result.matches == (
        MaterialMatch("too-long", "invalid", "invalid_timing", None, None, (f"sha256:{digest}",), None),
    )
    assert result.failures == (
        StoryboardFailure("material", None, "invalid_input"),
        StoryboardFailure("material", None, "invalid_input"),
        StoryboardFailure("material", "safe/bad.mp4", "invalid_input"),
        StoryboardFailure("shot", "bad-time", "invalid_input"),
    )
    assert "/home/private" not in payload and "C:/private" not in payload and "nan" not in payload.lower()


def test_conflicting_duplicate_identities_and_refs_are_not_matched():
    digest = "e" * 64
    result = plan_storyboard(
        [
            _material("same/ref.mp4", "1" * 64, tags=("one",)),
            _material("same/ref.mp4", "2" * 64, tags=("two",)),
            _material("a/copy.mp4", digest, duration=3.0, tags=("copy",)),
            _material("b/copy.mp4", digest, duration=4.0, tags=("copy",)),
        ],
        [ShotRequest("shot", 1, 1.0, required_tags=("copy",))],
    )

    assert result.status == "failed"
    assert result.matches[0].error_code == "unmatched"
    assert result.failures == (
        StoryboardFailure("material", "same/ref.mp4", "invalid_input"),
        StoryboardFailure("material", f"sha256:{digest}", "invalid_input"),
    )


def test_preferred_score_selects_unique_best_without_semantic_fallback():
    a, b = (character * 64 for character in "ab")
    result = plan_storyboard(
        [
            _material("a.mp4", a, tags=("required", "warm")),
            _material("b.mp4", b, tags=("required", "warm", "steady")),
        ],
        [ShotRequest("best", 1, 1.0, required_tags=("required",), preferred_tags=("warm", "steady"))],
    )

    assert result.status == "ok"
    assert result.matches[0].identity_ref == f"sha256:{b}"
    assert result.matches[0].score == 2


def test_malformed_iterable_and_duplicate_shot_ids_return_structured_failures():
    def broken():
        yield _material("ok.mp4", "f" * 64, tags=("ok",))
        raise OSError("private exception /home/user/media")

    failed = plan_storyboard(broken(), [ShotRequest("ok", 1, 1.0)])
    assert failed == StoryboardPlan("failed", (), (), (), (), (StoryboardFailure("plan", None, "invalid_input"),))

    duplicate = plan_storyboard(
        [_material("ok.mp4", "f" * 64, tags=("ok",))],
        [ShotRequest("same", 2, 1.0), ShotRequest("same", 1, 1.0)],
    )
    assert duplicate.failures == (StoryboardFailure("shot", "same", "invalid_input"),)
    assert duplicate.matches == () and duplicate.storyboard == ()
    assert all((EDLEntry, LocalAssetReference, StoryboardEntry, StoryboardFailure, StoryboardPlan))
