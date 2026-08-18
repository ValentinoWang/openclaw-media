import json
from hashlib import sha256

from openclaw_media import ArchiveItem, ArchiveManifest, ArchiveRegistry


def item(ref="reports/review.json", content=b'{"ok":true}', mime="application/json", descriptor_only=False):
    return ArchiveItem(ref=ref, mime_type=mime, sha256=sha256(content).hexdigest(), size_bytes=len(content), content=None if descriptor_only else content, descriptor_only=descriptor_only)


def manifest(tenant="t1", owner="u1", items=None):
    return ArchiveManifest(manifest_id="manifest-001", tenant_id=tenant, owner_id=owner, items=tuple(items or [item()]), quota_bytes=1000)


def test_manifest_commit_is_atomic_and_idempotent_with_descriptor_zero_cloud_bytes():
    registry = ArchiveRegistry()
    assert registry.create_manifest(manifest(items=[item(), item("artifacts/media.json", b'{}', descriptor_only=True)])).code == "manifest_accepted"
    first = registry.commit("t1", "u1", "manifest-001")
    assert first.code == "committed" and first.receipt.cloud_bytes == 0
    assert registry.commit("t1", "u1", "manifest-001") == first


def test_cross_tenant_owner_and_invalid_content_fail_closed_without_mutation():
    registry = ArchiveRegistry()
    assert registry.create_manifest(manifest()).code == "manifest_accepted"
    assert registry.commit("t2", "u1", "manifest-001").code == "manifest_missing"
    assert registry.commit("t1", "u2", "manifest-001").code == "owner_forbidden"
    bad = item(content=b'bad')
    bad = bad.model_copy(update={"sha256": "0" * 64})
    invalid = manifest("t1", "u1", [bad]).model_copy(update={"manifest_id": "manifest-002"})
    assert registry.create_manifest(invalid).code == "content_mismatch"


def test_rejects_video_audio_magic_paths_duplicates_and_quota():
    registry = ArchiveRegistry(max_item_bytes=4)
    assert registry.create_manifest(manifest(items=[item(mime="video/mp4")])).code == "media_bytes_forbidden"
    assert registry.create_manifest(manifest(items=[item(mime="audio/wav")])).code == "media_bytes_forbidden"
    assert registry.create_manifest(manifest(items=[item(ref="/tmp/x")])).code == "unsafe_ref"
    tiny = item(content=b"a")
    assert registry.create_manifest(manifest(items=[tiny, tiny])).code == "duplicate_ref"
    assert registry.create_manifest(manifest(items=[item(content=b'12345')])).code == "quota_exceeded"


def test_no_sensitive_or_absolute_path_leakage():
    registry = ArchiveRegistry()
    outcome = registry.create_manifest(manifest())
    payload = json.dumps(outcome.model_dump())
    assert all(value not in payload for value in ("/home/", "C:\\Users", "TOKEN", "Authorization"))
