from __future__ import annotations

import hashlib

import pytest

from openclaw_app.services.production_release_manifest import (
    ManifestValidationError,
    canonical_manifest_json,
    validate_manifest,
)


SOURCE_SHA = "a" * 40


def _entry(path: str, content: bytes) -> dict[str, str]:
    return {
        "path": path,
        "sha256": hashlib.sha256(content).hexdigest(),
        "mode": "100644",
    }


def test_manifest_validator_owns_inventory_ordering_before_planning(tmp_path) -> None:
    first = b"first"
    second = b"second"
    (tmp_path / "a.txt").write_bytes(first)
    (tmp_path / "z.txt").write_bytes(second)

    manifest = {
        "schema_version": "production-release-manifest.v1",
        "source": {"git_sha": SOURCE_SHA, "git_clean": True},
        "target": {
            "root": ".",
            "files": [
                _entry("z.txt", second),
                _entry("a.txt", first),
            ],
        },
        "previous_release_identity": None,
    }
    manifest["manifest_sha256"] = hashlib.sha256(
        canonical_manifest_json(manifest).encode("utf-8")
    ).hexdigest()

    with pytest.raises(ManifestValidationError) as caught:
        validate_manifest(
            manifest,
            tmp_path,
            expected_source_sha=SOURCE_SHA,
            expected_previous_release_identity=None,
        )

    assert caught.value.code == "SCHEMA_INVALID"
