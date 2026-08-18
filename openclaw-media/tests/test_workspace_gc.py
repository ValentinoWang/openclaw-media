import json
import sqlite3

from openclaw_media import LocalWorkspace, WorkspaceGcCandidate, WorkspaceGcOutcome


def _import(tmp_path, payload=b"gc-bytes", project="project"):
    source = tmp_path / "源文件.bin"
    source.write_bytes(payload)
    workspace = LocalWorkspace(tmp_path / "workspace")
    result = workspace.import_file(source, project_id=project, purpose="source")
    assert result.blob
    return workspace, result.blob.blob_ref, source


def _age(workspace, blob_ref, last_accessed_at=0):
    with sqlite3.connect(workspace.database_path) as db:
        db.execute(
            "UPDATE blobs SET created_at = ?, last_accessed_at = ? WHERE blob_ref = ?",
            (last_accessed_at, last_accessed_at, blob_ref),
        )


def test_gc_dry_run_then_apply_removes_only_old_unreferenced_blob(tmp_path):
    workspace, blob_ref, source = _import(tmp_path)
    assert workspace.release_project_reference("project", "source").status == "completed"
    _age(workspace, blob_ref)
    preview = workspace.collect_garbage(now=14 * 86400, dry_run=True)
    candidate = WorkspaceGcCandidate(
        blob_ref=blob_ref,
        sha256=f"sha256:{blob_ref.rsplit('/', 1)[-1]}",
        size_bytes=len(b"gc-bytes"),
        reference_count=0,
        reason="unreferenced_unleased_unpinned_expired",
    )
    assert preview == WorkspaceGcOutcome(
        status="completed", code="ok", dry_run=True, candidates=(candidate,)
    )
    assert (workspace.root / blob_ref).exists() and source.exists()
    applied = workspace.collect_garbage(now=14 * 86400, dry_run=False)
    assert applied.deleted == (blob_ref,) and not (workspace.root / blob_ref).exists()
    assert workspace.verify_blob(blob_ref).code == "blob_not_found"


def test_project_reference_and_active_lease_or_pin_protect_blob(tmp_path):
    workspace, blob_ref, _ = _import(tmp_path)
    _age(workspace, blob_ref)
    assert workspace.collect_garbage(now=14 * 86400).candidates == ()
    workspace.release_project_reference("project", "source")
    assert workspace.lease_blob(blob_ref, "run-1", ttl_seconds=60, now=14 * 86400).status == "completed"
    assert workspace.collect_garbage(now=14 * 86400).candidates == ()
    workspace.release_lease(blob_ref, "run-1")
    assert workspace.pin_blob(blob_ref, "archive").status == "completed"
    assert workspace.collect_garbage(now=14 * 86400).candidates == ()
    assert workspace.unpin_blob(blob_ref, "archive").status == "completed"
    assert tuple(item.blob_ref for item in workspace.collect_garbage(now=14 * 86400).candidates) == (blob_ref,)


def test_invalid_and_corrupt_gc_inputs_fail_closed_without_leakage(tmp_path):
    workspace, blob_ref, _ = _import(tmp_path)
    invalid = workspace.lease_blob("/private/blob", "lease", ttl_seconds=1)
    bad_gc = workspace.collect_garbage(now=float("nan"))
    assert invalid.code == "invalid_blob_ref" and bad_gc.code == "invalid_timestamp"
    (workspace.root / blob_ref).write_bytes(b"tampered")
    workspace.release_project_reference("project", "source")
    _age(workspace, blob_ref)
    corrupt = workspace.collect_garbage(now=14 * 86400, dry_run=False)
    payload = json.dumps([invalid.model_dump(), bad_gc.model_dump(), corrupt.model_dump()])
    assert corrupt.code == "blob_corrupt"
    assert str(tmp_path) not in payload and "Traceback" not in payload and "Exception" not in payload


def test_gc_results_are_deterministic_and_immutable(tmp_path):
    workspace, first, _ = _import(tmp_path, b"a", "a")
    _, second, _ = _import(tmp_path, b"b", "b")
    workspace.release_project_reference("a", "source")
    workspace.release_project_reference("b", "source")
    _age(workspace, first); _age(workspace, second)
    result = workspace.collect_garbage(now=14 * 86400, dry_run=True)
    assert tuple(item.blob_ref for item in result.candidates) == tuple(sorted((first, second)))
    try:
        result.candidates = ()
    except Exception:
        pass
    else:
        raise AssertionError("GC receipt must be immutable")


def test_successful_readback_refreshes_last_access_age(tmp_path):
    workspace, blob_ref, _ = _import(tmp_path)
    workspace.release_project_reference("project", "source")
    _age(workspace, blob_ref)
    assert workspace.verify_blob(blob_ref, now=13 * 86400).status == "completed"
    assert workspace.collect_garbage(now=14 * 86400).candidates == ()
    later = workspace.collect_garbage(now=28 * 86400)
    assert tuple(item.blob_ref for item in later.candidates) == (blob_ref,)


def test_apply_preflights_all_candidates_before_deleting_any_blob(tmp_path):
    workspace, first, _ = _import(tmp_path, b"a", "a")
    _, second, _ = _import(tmp_path, b"b", "b")
    workspace.release_project_reference("a", "source")
    workspace.release_project_reference("b", "source")
    _age(workspace, first); _age(workspace, second)
    (workspace.root / second).write_bytes(b"corrupt")
    result = workspace.collect_garbage(now=14 * 86400, dry_run=False)
    assert result.code == "blob_corrupt"
    assert (workspace.root / first).read_bytes() == b"a"
