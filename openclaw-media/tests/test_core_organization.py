import json
from hashlib import sha256

from openclaw_media.core import (
    MediaFile,
    OrganizationFailure,
    OrganizationMapping,
    OrganizationPlan,
    ProbeResult,
    plan_media_organization,
    scan_media,
)


def _file(ref, kind, digest, probe=None):
    return MediaFile(ref, kind, "." + ref.rsplit(".", 1)[-1].lower(), 1, "small", digest, probe)


def test_organization_golden_is_stable_mixed_deduplicated_and_collision_safe():
    a, b, c, d, e = (character * 64 for character in "abcde")
    files = [
        _file("二/照片.JPG", "image", b),
        _file("一/照片.JPG", "image", a),
        _file("三/copy.jpg", "image", a),
        _file("音频/旁白.wav", "audio", c),
        _file("视频/成片.MP4", "video", d),
        _file("视频/成片.xmp", "xmp", e),
    ]
    first = plan_media_organization(files).to_dict()
    assert first == plan_media_organization(reversed(files)).to_dict()
    assert first == {
        "status": "ok",
        "mappings": (
            {
                "source_ref": "一/照片.JPG",
                "destination_ref": "organized/image/照片.JPG",
                "kind": "image",
                "sha256": a,
                "identity_ref": f"sha256:{a}",
                "decision": "planned",
                "duplicate_of": None,
            },
            {
                "source_ref": "三/copy.jpg",
                "destination_ref": "organized/image/照片.JPG",
                "kind": "image",
                "sha256": a,
                "identity_ref": f"sha256:{a}",
                "decision": "duplicate",
                "duplicate_of": "一/照片.JPG",
            },
            {
                "source_ref": "二/照片.JPG",
                "destination_ref": f"organized/image/照片--{b[:12]}.jpg",
                "kind": "image",
                "sha256": b,
                "identity_ref": f"sha256:{b}",
                "decision": "renamed_collision",
                "duplicate_of": None,
            },
            {
                "source_ref": "视频/成片.MP4",
                "destination_ref": "organized/video/成片.MP4",
                "kind": "video",
                "sha256": d,
                "identity_ref": f"sha256:{d}",
                "decision": "planned",
                "duplicate_of": None,
            },
            {
                "source_ref": "视频/成片.xmp",
                "destination_ref": "organized/sidecar/成片.xmp",
                "kind": "xmp",
                "sha256": e,
                "identity_ref": f"sha256:{e}",
                "decision": "planned",
                "duplicate_of": None,
            },
            {
                "source_ref": "音频/旁白.wav",
                "destination_ref": "organized/audio/旁白.wav",
                "kind": "audio",
                "sha256": c,
                "identity_ref": f"sha256:{c}",
                "decision": "planned",
                "duplicate_of": None,
            },
        ),
        "failures": (),
    }
    assert all(not m["destination_ref"].startswith("/") for m in first["mappings"])


def test_invalid_corrupt_and_unresolved_collision_inputs_are_sanitized():
    bad_probe = ProbeResult("corrupt", None, None, False, False, (), "probe_failed")
    shared_prefix = "1" * 12
    result = plan_media_organization(
        [
            _file("../secret.mp4", "video", "a" * 64),
            _file("C:/private/secret.mp4", "video", "b" * 64),
            _file("broken.mp4", "video", "d" * 64, bad_probe),
            _file("a/same.jpg", "image", "0" * 64),
            _file("b/same.jpg", "image", shared_prefix + "2" * 52),
            _file("c/same.jpg", "image", shared_prefix + "3" * 52),
        ]
    )
    payload = json.dumps(result.to_dict())
    assert result.status == "partial"
    assert [failure.error_code for failure in result.failures] == [
        "invalid_input",
        "invalid_input",
        "corrupt_input",
        "collision_unresolved",
    ]
    assert all(failure.source_ref is None for failure in result.failures[:2])
    assert "/home/" not in payload and "C:/private" not in payload and "probe_failed" not in payload


def test_same_source_ref_with_different_content_has_deterministic_order():
    low = _file("inbox/clip.mp4", "video", "1" * 64)
    high = _file("inbox/clip.mp4", "video", "2" * 64)

    forward = plan_media_organization([high, low])
    reverse = plan_media_organization([low, high])

    assert forward == reverse
    assert [mapping.decision for mapping in forward.mappings] == ["planned", "renamed_collision"]


def test_planning_does_not_mutate_originals(tmp_path):
    source = tmp_path / "待整理"
    (source / "相册").mkdir(parents=True)
    (source / "相册" / "照片.jpg").write_bytes(b"photo")
    (source / "旁白.wav").write_bytes(b"audio")

    before = {
        path.relative_to(source).as_posix(): sha256(path.read_bytes()).hexdigest()
        for path in source.rglob("*")
        if path.is_file()
    }
    scan = scan_media(source, probe_runner=lambda _path: {"format": {}, "streams": []})
    first = plan_media_organization(scan.files)
    second = plan_media_organization(scan.files)
    after = {
        path.relative_to(source).as_posix(): sha256(path.read_bytes()).hexdigest()
        for path in source.rglob("*")
        if path.is_file()
    }

    assert first == second
    assert first.status == "ok"
    assert before == after
    assert not (source / "organized").exists()


def test_malformed_iterable_returns_structured_failure_without_exception_text():
    def broken():
        yield _file("ok.jpg", "image", "f" * 64)
        raise OSError("private absolute path /home/user/media")

    result = plan_media_organization(broken())

    assert result == OrganizationPlan("failed", (), (OrganizationFailure(None, "invalid_input"),))
    assert all((OrganizationMapping, OrganizationFailure, OrganizationPlan))
