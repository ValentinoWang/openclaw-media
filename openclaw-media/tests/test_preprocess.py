import json
from dataclasses import FrozenInstanceError
from pathlib import Path

from openclaw_media import LocalMediaManifest, LocalWorkspace, preprocess_media


def _import_source(tmp_path, payload=b"source-media"):
    source = tmp_path / "项目素材.mp4"
    source.write_bytes(payload)
    workspace = LocalWorkspace(tmp_path / "workspace")
    imported = workspace.import_file(source, project_id="project-a", purpose="source")
    assert imported.status == "completed" and imported.blob is not None
    return workspace, imported.blob.blob_ref, source


def _writing_runner(command):
    target = Path(command[-1])
    target.parent.mkdir(parents=True, exist_ok=True)
    marker = "proxy" if target.suffix == ".mp4" else target.suffix.removeprefix(".")
    target.write_bytes(f"artifact:{marker}:{target.name}".encode())


def test_cas_source_produces_deterministic_relative_manifest_and_preserves_source(tmp_path):
    workspace, source_ref, original = _import_source(tmp_path)
    original_stat = original.stat()
    managed_source = workspace.root / source_ref
    managed_bytes = managed_source.read_bytes()

    first = preprocess_media(
        workspace,
        source_ref,
        "derived/项目",
        duration_seconds=9.0,
        has_audio=True,
        runner=_writing_runner,
    )
    second = preprocess_media(
        workspace,
        source_ref,
        "derived/项目",
        duration_seconds=9.0,
        has_audio=True,
        runner=_writing_runner,
    )

    assert first == second
    assert first.status == "completed" and first.error_code is None
    assert first.proxy is not None and first.audio is not None
    assert [frame.timestamp_seconds for frame in first.keyframes] == [1.5, 4.5, 7.5]
    assert [item.kind for item in (first.proxy, *first.keyframes, first.audio)] == [
        "proxy",
        "keyframe",
        "keyframe",
        "keyframe",
        "audio",
    ]
    assert all(
        item.size_bytes > 0 and item.sha256.startswith("sha256:")
        for item in (first.proxy, *first.keyframes, first.audio)
    )
    payload = json.dumps(first.to_dict(), ensure_ascii=False)
    assert str(tmp_path) not in payload
    assert "Traceback" not in payload and "Exception" not in payload
    assert all(
        not Path(item.ref).is_absolute()
        for item in (first.proxy, *first.keyframes, first.audio)
    )
    assert original.read_bytes() == b"source-media"
    assert original.stat().st_ino == original_stat.st_ino
    assert managed_source.read_bytes() == managed_bytes
    assert not tuple((workspace.root / "tmp").iterdir())


def test_no_audio_is_explicit_partial_and_keeps_proxy_and_keyframes(tmp_path):
    workspace, source_ref, _ = _import_source(tmp_path)

    result = preprocess_media(
        workspace,
        source_ref,
        "derived/silent",
        duration_seconds=2.0,
        has_audio=False,
        runner=_writing_runner,
        keyframe_count=2,
    )

    assert (result.status, result.error_code, result.audio) == ("partial", "no_audio", None)
    assert result.proxy is not None and len(result.keyframes) == 2
    assert not tuple((workspace.root / "tmp").iterdir())


def test_missing_corrupt_and_invalid_cas_inputs_fail_closed(tmp_path):
    workspace, source_ref, _ = _import_source(tmp_path)
    (workspace.root / source_ref).write_bytes(b"corrupt")

    corrupt = preprocess_media(
        workspace, source_ref, "derived/a", duration_seconds=2.0, has_audio=True, runner=_writing_runner
    )
    missing_ref = "blobs/sha256/aa/" + "a" * 64
    missing = preprocess_media(
        workspace, missing_ref, "derived/b", duration_seconds=2.0, has_audio=True, runner=_writing_runner
    )
    invalid = preprocess_media(
        workspace, "../secret", "derived/c", duration_seconds=2.0, has_audio=True, runner=_writing_runner
    )
    windows_absolute = preprocess_media(
        workspace, missing_ref, "C:/private/out", duration_seconds=2.0, has_audio=True, runner=_writing_runner
    )

    assert (corrupt.status, corrupt.error_code) == ("manual", "blob_corrupt")
    assert (missing.status, missing.error_code) == ("manual", "blob_not_found")
    assert (invalid.status, invalid.error_code) == ("manual", "invalid_blob_ref")
    assert (windows_absolute.status, windows_absolute.error_code) == ("manual", "invalid_output_ref")
    serialized = json.dumps([item.to_dict() for item in (corrupt, missing, invalid, windows_absolute)])
    assert str(tmp_path) not in serialized and "Traceback" not in serialized


def test_runner_failure_removes_partial_staging_and_preserves_previous_manifest(tmp_path):
    workspace, source_ref, _ = _import_source(tmp_path)
    accepted = preprocess_media(
        workspace,
        source_ref,
        "derived/project",
        duration_seconds=2.0,
        has_audio=True,
        runner=_writing_runner,
    )
    before = {
        path.relative_to(workspace.root).as_posix(): path.read_bytes()
        for path in (workspace.root / "derived").rglob("*")
        if path.is_file()
    }

    def partial_failure(command):
        target = Path(command[-1])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"partial-secret")
        raise RuntimeError(f"/private/provider token {target}")

    failed = preprocess_media(
        workspace,
        source_ref,
        "derived/project",
        duration_seconds=2.0,
        has_audio=True,
        runner=partial_failure,
    )

    assert accepted.status == "completed"
    assert (failed.status, failed.error_code) == ("manual", "preprocess_failed")
    assert failed.proxy is failed.audio is None and failed.keyframes == ()
    after = {
        path.relative_to(workspace.root).as_posix(): path.read_bytes()
        for path in (workspace.root / "derived").rglob("*")
        if path.is_file()
    }
    assert after == before
    assert not tuple((workspace.root / "tmp").iterdir())
    assert "/private" not in json.dumps(failed.to_dict())


def test_empty_or_missing_runner_output_is_explicit_and_never_committed(tmp_path):
    workspace, source_ref, _ = _import_source(tmp_path)

    def empty_output(command):
        target = Path(command[-1])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"")

    empty = preprocess_media(
        workspace, source_ref, "derived/empty", duration_seconds=2.0, has_audio=True, runner=empty_output
    )
    missing = preprocess_media(
        workspace, source_ref, "derived/missing", duration_seconds=2.0, has_audio=True, runner=lambda _: None
    )

    assert (empty.status, empty.error_code) == ("manual", "corrupt_output")
    assert (missing.status, missing.error_code) == ("manual", "corrupt_output")
    assert not (workspace.root / "derived" / "empty").exists()
    assert not (workspace.root / "derived" / "missing").exists()
    assert not tuple((workspace.root / "tmp").iterdir())


def test_public_manifest_is_canonical_and_frozen(tmp_path):
    workspace, source_ref, _ = _import_source(tmp_path)
    manifest = preprocess_media(
        workspace, source_ref, "derived/frozen", duration_seconds=2.0, has_audio=False, runner=_writing_runner
    )

    assert isinstance(manifest, LocalMediaManifest)
    try:
        manifest.status = "changed"
    except FrozenInstanceError:
        pass
    else:
        raise AssertionError("LocalMediaManifest must be immutable")
