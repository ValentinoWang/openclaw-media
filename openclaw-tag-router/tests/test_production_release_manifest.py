from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any, Mapping

import pytest

from openclaw_app.services.production_release_manifest import (
    ManifestValidationError,
    build_manifest,
    canonical_manifest_json,
    validate_manifest,
)


SCHEMA_VERSION = "production-release-manifest.v1"
SOURCE_SHA = "a" * 40
PREVIOUS_RELEASE = {
    "git_sha": "b" * 40,
    "manifest_sha256": "c" * 64,
}


def _canonical_for_fixture(manifest: Mapping[str, Any]) -> str:
    payload = copy.deepcopy(dict(manifest))
    payload.pop("manifest_sha256", None)
    return json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _seal(manifest: dict[str, Any]) -> dict[str, Any]:
    manifest["manifest_sha256"] = hashlib.sha256(
        _canonical_for_fixture(manifest).encode("utf-8")
    ).hexdigest()
    return manifest


def _file_entry(path: str = "app/main.py", content: bytes = b"immutable-source", mode: str = "100644") -> dict[str, str]:
    return {
        "path": path,
        "sha256": hashlib.sha256(content).hexdigest(),
        "mode": mode,
    }


def _manifest(
    root: Path,
    *,
    files: list[dict[str, str]] | None = None,
    source_sha: str = SOURCE_SHA,
    source_clean: bool = True,
    previous_release: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    (root / "app").mkdir(parents=True, exist_ok=True)
    (root / "app/main.py").write_bytes(b"immutable-source")
    return _seal(
        {
            "schema_version": SCHEMA_VERSION,
            "source": {
                "git_sha": source_sha,
                "git_clean": source_clean,
            },
            "target": {
                "root": ".",
                "files": files or [_file_entry()],
            },
            "previous_release_identity": copy.deepcopy(previous_release),
            "manifest_sha256": None,
        }
    )


def _expect_code(code: str, manifest: Mapping[str, Any], root: Path, **kwargs: Any) -> None:
    with pytest.raises(ManifestValidationError) as raised:
        validate_manifest(manifest, root, **kwargs)
    assert raised.value.code == code


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", os.fspath(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "release-source"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "manifest-test@example.invalid")
    _git(repo, "config", "user.name", "manifest-test")
    (repo / "app").mkdir()
    (repo / "config").mkdir()
    (repo / "app/main.py").write_text("print('release')\n", encoding="utf-8")
    (repo / "config/static.json").write_text('{"mode":"static"}\n', encoding="utf-8")
    _git(repo, "add", "app/main.py", "config/static.json")
    _git(repo, "commit", "-q", "-m", "fixture")
    return repo


def test_canonical_json_is_sorted_compact_and_excludes_manifest_digest(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    reordered = {
        "manifest_sha256": "digest-field-must-not-be-hashed",
        "previous_release_identity": manifest["previous_release_identity"],
        "target": manifest["target"],
        "source": manifest["source"],
        "schema_version": manifest["schema_version"],
    }

    canonical = canonical_manifest_json(reordered)

    assert canonical == _canonical_for_fixture(manifest)
    assert "digest-field-must-not-be-hashed" not in canonical
    assert "\n" not in canonical
    assert canonical.startswith('{"previous_release_identity"')


def test_canonical_json_never_serializes_secret_values(tmp_path: Path) -> None:
    marker = "SENTINEL_ONLY_NOT_A_CREDENTIAL"
    manifest = _manifest(tmp_path)
    manifest["secret_value"] = marker

    with pytest.raises(ManifestValidationError) as raised:
        canonical_manifest_json(manifest)

    assert raised.value.code == "SECRET_DISCLOSURE"
    assert marker not in str(raised.value)


def test_valid_manifest_passes_without_mutating_input(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path, previous_release=PREVIOUS_RELEASE)
    before = copy.deepcopy(manifest)

    validate_manifest(
        manifest,
        tmp_path,
        expected_source_sha=SOURCE_SHA,
        expected_previous_release_identity=PREVIOUS_RELEASE,
    )

    assert manifest == before


@pytest.mark.parametrize(
    ("path", "error_code"),
    [
        ("../outside.txt", "PATH_TRAVERSAL"),
        ("app/../../outside.txt", "PATH_TRAVERSAL"),
        ("/etc/passwd", "ABSOLUTE_PATH"),
        ("C:\\Windows\\system32\\config", "ABSOLUTE_PATH"),
    ],
)
def test_manifest_rejects_non_relative_paths(tmp_path: Path, path: str, error_code: str) -> None:
    manifest = _manifest(tmp_path, files=[_file_entry(path=path)])

    _expect_code(error_code, manifest, tmp_path, expected_source_sha=SOURCE_SHA)


def test_manifest_rejects_duplicate_paths(tmp_path: Path) -> None:
    manifest = _manifest(
        tmp_path,
        files=[_file_entry(), _file_entry(content=b"other")],
    )

    _expect_code("DUPLICATE_PATH", manifest, tmp_path, expected_source_sha=SOURCE_SHA)


def test_manifest_rejects_symlink_entries(tmp_path: Path) -> None:
    (tmp_path / "target.txt").write_bytes(b"target")
    (tmp_path / "link.txt").symlink_to(tmp_path / "target.txt")
    manifest = _manifest(tmp_path, files=[_file_entry(path="link.txt", content=b"target")])

    _expect_code("UNSUPPORTED_SYMLINK", manifest, tmp_path, expected_source_sha=SOURCE_SHA)


@pytest.mark.parametrize(
    ("path", "error_code"),
    [
        ("state/stage2.sqlite3", "MUTABLE_PATH"),
        ("runtime/generated.json", "RUNTIME_PATH"),
        ("stage2.env", "SECRET_PATH"),
        ("session-material.env", "SECRET_PATH"),
        ("credentials/provider.json", "SECRET_PATH"),
    ],
)
def test_manifest_rejects_mutable_secret_and_runtime_paths(
    tmp_path: Path,
    path: str,
    error_code: str,
) -> None:
    manifest = _manifest(tmp_path, files=[_file_entry(path=path)])

    _expect_code(error_code, manifest, tmp_path, expected_source_sha=SOURCE_SHA)


def test_manifest_rejects_missing_file_digest(tmp_path: Path) -> None:
    entry = _file_entry()
    del entry["sha256"]
    manifest = _manifest(tmp_path, files=[entry])

    _expect_code("MISSING_DIGEST", manifest, tmp_path, expected_source_sha=SOURCE_SHA)


def test_manifest_rejects_malformed_and_mismatched_file_digests(tmp_path: Path) -> None:
    malformed = _manifest(tmp_path, files=[dict(_file_entry(), sha256="not-a-digest")])
    mismatched = _manifest(tmp_path, files=[dict(_file_entry(), sha256="b" * 64)])

    _expect_code("MALFORMED_DIGEST", malformed, tmp_path, expected_source_sha=SOURCE_SHA)
    _expect_code("DIGEST_MISMATCH", mismatched, tmp_path, expected_source_sha=SOURCE_SHA)


@pytest.mark.parametrize("mode", ["0644", "100600", 0o644, "10064"])
def test_manifest_rejects_malformed_modes(tmp_path: Path, mode: Any) -> None:
    manifest = _manifest(tmp_path, files=[dict(_file_entry(), mode=mode)])

    _expect_code("MALFORMED_MODE", manifest, tmp_path, expected_source_sha=SOURCE_SHA)


def test_manifest_rejects_source_sha_mismatch_after_digest_is_resealed(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path, source_sha="d" * 40)

    _expect_code("SOURCE_SHA_MISMATCH", manifest, tmp_path, expected_source_sha=SOURCE_SHA)


def test_manifest_rejects_dirty_source_identity(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path, source_clean=False)

    _expect_code("SOURCE_NOT_CLEAN", manifest, tmp_path, expected_source_sha=SOURCE_SHA)


def test_manifest_rejects_manifest_digest_mismatch(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    manifest["source"]["git_sha"] = "d" * 40

    _expect_code("MANIFEST_DIGEST_MISMATCH", manifest, tmp_path, expected_source_sha=SOURCE_SHA)


def test_manifest_rejects_missing_manifest_digest(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    del manifest["manifest_sha256"]

    _expect_code("MANIFEST_DIGEST_MISMATCH", manifest, tmp_path, expected_source_sha=SOURCE_SHA)


def test_manifest_rejects_malformed_manifest_digest(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    manifest["manifest_sha256"] = "not-a-digest"

    _expect_code("MANIFEST_DIGEST_MISMATCH", manifest, tmp_path, expected_source_sha=SOURCE_SHA)


def test_manifest_rejects_previous_release_identity_mismatch(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path, previous_release={"git_sha": "d" * 40, "manifest_sha256": "e" * 64})

    _expect_code(
        "PREVIOUS_RELEASE_IDENTITY_MISMATCH",
        manifest,
        tmp_path,
        expected_source_sha=SOURCE_SHA,
        expected_previous_release_identity=PREVIOUS_RELEASE,
    )


def test_manifest_rejects_unknown_schema_fields(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    manifest["unexpected"] = "field"
    _seal(manifest)

    _expect_code("SCHEMA_INVALID", manifest, tmp_path, expected_source_sha=SOURCE_SHA)


def test_builder_binds_clean_git_sha_and_target_relative_inventory(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    expected_sha = _git(repo, "rev-parse", "HEAD")

    manifest = build_manifest(
        repo,
        file_paths=("config/static.json", "app/main.py"),
        previous_release_identity=PREVIOUS_RELEASE,
    )

    assert manifest["schema_version"] == SCHEMA_VERSION
    assert manifest["source"] == {"git_sha": expected_sha, "git_clean": True}
    assert manifest["target"]["root"] == "."
    assert [entry["path"] for entry in manifest["target"]["files"]] == [
        "app/main.py",
        "config/static.json",
    ]
    assert manifest["previous_release_identity"] == PREVIOUS_RELEASE
    validate_manifest(
        manifest,
        repo,
        expected_source_sha=expected_sha,
        expected_previous_release_identity=PREVIOUS_RELEASE,
    )


def test_builder_rejects_dirty_git_source_before_manifest_creation(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    (repo / "app/main.py").write_text("dirty\n", encoding="utf-8")

    with pytest.raises(ManifestValidationError) as raised:
        build_manifest(repo, file_paths=("app/main.py",))

    assert raised.value.code == "SOURCE_NOT_CLEAN"


def test_builder_rejects_untracked_git_source_before_manifest_creation(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    (repo / "untracked.txt").write_text("untracked\n", encoding="utf-8")

    with pytest.raises(ManifestValidationError) as raised:
        build_manifest(repo, file_paths=("app/main.py",))

    assert raised.value.code == "SOURCE_NOT_CLEAN"
