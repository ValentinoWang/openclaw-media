import json
import sqlite3
from pathlib import Path

from openclaw_media.workspace import LocalWorkspace


def test_duplicate_bytes_have_one_managed_blob_and_project_references(tmp_path):
    root = tmp_path / "workspace"
    first_source = tmp_path / "camera-a.mp4"
    second_source = tmp_path / "相机-b.mp4"
    payload = b"same-media-bytes\x00\x01"
    first_source.write_bytes(payload)
    second_source.write_bytes(payload)
    first_stat = first_source.stat()
    second_stat = second_source.stat()
    workspace = LocalWorkspace(root)

    first = workspace.import_file(first_source, project_id="project-a", purpose="source")
    repeated = workspace.import_file(first_source, project_id="project-a", purpose="source")
    second = workspace.import_file(second_source, project_id="project-b", purpose="素材")

    assert first == repeated
    assert (first.status, first.code) == ("completed", "ok")
    assert (second.status, second.code) == ("completed", "ok")
    assert first.blob == second.blob
    assert first.blob is not None
    assert first.blob.blob_ref.startswith("blobs/sha256/")
    assert first.blob.sha256.startswith("sha256:")
    assert first.blob.size_bytes == len(payload)
    assert first.reference is not None and second.reference is not None
    assert first.reference.project_id == "project-a"
    assert second.reference.project_id == "project-b"
    assert second.reference.purpose == "素材"

    managed = root / first.blob.blob_ref
    assert managed.read_bytes() == payload
    assert len(tuple((root / "blobs").rglob("*"))) == 3
    with sqlite3.connect(root / "workspace.sqlite3") as connection:
        assert connection.execute("SELECT count(*) FROM blobs").fetchone() == (1,)
        assert connection.execute("SELECT count(*) FROM project_blob_refs").fetchone() == (2,)

    assert first_source.read_bytes() == payload
    assert second_source.read_bytes() == payload
    assert first_source.stat().st_ino == first_stat.st_ino
    assert second_source.stat().st_ino == second_stat.st_ino
    assert not tuple(root.rglob("*.tmp"))


def test_reference_conflict_does_not_replace_existing_reference_or_source(tmp_path):
    workspace = LocalWorkspace(tmp_path / "workspace")
    original = tmp_path / "original.mov"
    replacement = tmp_path / "replacement.mov"
    original.write_bytes(b"original")
    replacement.write_bytes(b"replacement")

    accepted = workspace.import_file(original, project_id="project-a", purpose="source")
    conflict = workspace.import_file(replacement, project_id="project-a", purpose="source")

    assert accepted.status == "completed"
    assert (conflict.status, conflict.code) == ("manual", "reference_conflict")
    assert conflict.blob is conflict.reference is None
    refs = workspace.project_references("project-a")
    assert refs == (accepted.reference,)
    assert original.read_bytes() == b"original"
    assert replacement.read_bytes() == b"replacement"
    with sqlite3.connect(tmp_path / "workspace" / "workspace.sqlite3") as connection:
        assert connection.execute("SELECT count(*) FROM blobs").fetchone() == (1,)


def test_missing_invalid_and_non_file_sources_fail_without_path_or_exception_leakage(tmp_path):
    workspace = LocalWorkspace(tmp_path / "workspace")
    directory = tmp_path / "folder"
    directory.mkdir()
    missing = tmp_path / "private" / "missing.mp4"

    outcomes = (
        workspace.import_file(missing, project_id="project-a", purpose="source"),
        workspace.import_file(directory, project_id="project-a", purpose="source"),
        workspace.import_file(directory, project_id="../escape", purpose="source"),
        workspace.import_file(directory, project_id="project-a", purpose="../escape"),
    )

    assert [(item.status, item.code) for item in outcomes] == [
        ("manual", "source_not_found"),
        ("manual", "invalid_source"),
        ("manual", "invalid_project_id"),
        ("manual", "invalid_purpose"),
    ]
    serialized = json.dumps([item.model_dump(mode="json") for item in outcomes])
    assert str(tmp_path) not in serialized
    assert "FileNotFoundError" not in serialized
    assert "Traceback" not in serialized


def test_corrupt_managed_blob_is_explicit_and_never_silently_replaced(tmp_path):
    root = tmp_path / "workspace"
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"verified-content")
    workspace = LocalWorkspace(root)
    accepted = workspace.import_file(source, project_id="project-a", purpose="source")
    assert accepted.blob is not None
    managed = root / accepted.blob.blob_ref
    managed.write_bytes(b"corrupt")

    verification = workspace.verify_blob(accepted.blob.blob_ref)
    repeated = workspace.import_file(source, project_id="project-b", purpose="source")

    assert (verification.status, verification.code) == ("manual", "blob_corrupt")
    assert (repeated.status, repeated.code) == ("manual", "blob_corrupt")
    assert managed.read_bytes() == b"corrupt"
    assert workspace.project_references("project-b") == ()


def test_unknown_or_escaping_blob_refs_and_corrupt_database_rows_fail_closed(tmp_path):
    root = tmp_path / "workspace"
    workspace = LocalWorkspace(root)

    escaping = workspace.verify_blob("../secret")
    unknown = workspace.verify_blob("blobs/sha256/aa/" + "a" * 64)
    assert (escaping.status, escaping.code) == ("manual", "invalid_blob_ref")
    assert (unknown.status, unknown.code) == ("manual", "blob_not_found")

    with sqlite3.connect(root / "workspace.sqlite3") as connection:
        connection.execute(
            "INSERT INTO blobs(blob_ref, sha256, size_bytes) VALUES (?, ?, ?)",
            ("blobs/sha256/bb/" + "b" * 64, "sha256:" + "c" * 64, 1),
        )
    corrupt = workspace.verify_blob("blobs/sha256/bb/" + "b" * 64)
    assert (corrupt.status, corrupt.code) == ("manual", "workspace_corrupt")


def test_public_results_are_frozen_and_contain_only_relative_references(tmp_path):
    source = tmp_path / "视频.mp4"
    source.write_bytes("媒体内容".encode())
    workspace = LocalWorkspace(tmp_path / "workspace")

    outcome = workspace.import_file(source, project_id="项目-一", purpose="原片")

    assert outcome.status == "completed"
    assert outcome.blob is not None and not Path(outcome.blob.blob_ref).is_absolute()
    assert str(tmp_path) not in outcome.model_dump_json()
    assert "视频.mp4" not in outcome.model_dump_json()
    assert "项目-一" in outcome.model_dump_json()
    try:
        outcome.code = "changed"
    except Exception:
        pass
    else:
        raise AssertionError("workspace outcomes must be immutable")
