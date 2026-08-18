from pathlib import Path

from scripts.backfill_asset_thumbnails import (
    RECOVERY_CATALOG,
    RecoveryCandidate,
    classify_recovery,
)


CURRENT_MISSING_FINGERPRINTS = {
    "sha256:1a906d6fd0107aa57d0c2b9eb034704d706b39bbdaa30ef98516974b26730003",
    "sha256:19499178f38d2bce76ce85450602eb738e6ae719ec5d2b64f9be9371786652de",
    "sha256:a4fff7d5aae051ac92685033b8476f79cbc3c385caa70b9e65c1fbc820344eab",
    "sha256:315d47ac55e0251cb7ed0b5825a9ad2a3d89207fb857ce522e4f24acfe8968b7",
    "sha256:c7d3f02af8a97453c6ac50675db91f31a03aa68177fe5a4de31885e7ea291793",
    "sha256:0bcfd83c13b7a039987abfbf679be62c8c45aa1e902054f2e3cb07825db4a439",
}


def test_current_missing_fingerprints_all_have_real_recovery_strategies() -> None:
    assert CURRENT_MISSING_FINGERPRINTS <= set(RECOVERY_CATALOG)
    assert all(RECOVERY_CATALOG[key]["kind"] != "synthetic" for key in CURRENT_MISSING_FINGERPRINTS)


def test_classify_recovery_never_overwrites_existing_cover(tmp_path: Path) -> None:
    result = classify_recovery(
        {
            "素材ID": "asset_existing",
            "内容指纹": next(iter(CURRENT_MISSING_FINGERPRINTS)),
            "封面附件": [{"name": "existing.jpg"}],
        },
        downloads_root=tmp_path,
        evidence_root=tmp_path,
        cache_root=tmp_path,
    )

    assert result.status == "skipped_existing_cover"
    assert result.candidate is None


def test_classify_recovery_uses_existing_evidence_file(tmp_path: Path) -> None:
    relative = Path(RECOVERY_CATALOG[
        "sha256:315d47ac55e0251cb7ed0b5825a9ad2a3d89207fb857ce522e4f24acfe8968b7"
    ]["relative_path"])
    image = tmp_path / relative
    image.parent.mkdir(parents=True)
    image.write_bytes(b"RIFF\x00\x00\x00\x00WEBPVP8 ")

    result = classify_recovery(
        {
            "素材ID": "asset_note",
            "内容指纹": "sha256:315d47ac55e0251cb7ed0b5825a9ad2a3d89207fb857ce522e4f24acfe8968b7",
            "封面附件": [],
        },
        downloads_root=tmp_path,
        evidence_root=tmp_path,
        cache_root=tmp_path,
    )

    assert result.status == "recoverable"
    assert result.candidate == RecoveryCandidate(image, "local_source_image")
