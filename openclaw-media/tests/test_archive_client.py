from __future__ import annotations

from hashlib import sha256
import json

import pytest

from openclaw_media.archive_client import ArchiveClient, ArchiveClientError, ArtifactSelection


class FakeRemote:
    def __init__(self):
        self.payloads = []

    def archive_commit(self, payload):
        self.payloads.append(("commit", payload))
        return {"commit_receipt": {"cloud_bytes": 0}}

    def archive_readback(self, archive_id, **payload):
        self.payloads.append(("readback", archive_id, payload))
        return {"verified": True, "hard_deleted": False}

    def archive_delete_plan(self, archive_id):
        self.payloads.append(("plan", archive_id))
        return {"delete_plan_id": "plan_1"}

    def archive_delete(self, archive_id, **payload):
        self.payloads.append(("delete", archive_id, payload))
        return {"hard_deleted": True}


def test_manifest_content_and_media_descriptor_never_send_media_bytes(tmp_path):
    report = tmp_path / "report.json"
    report.write_text('{"ok":true}', encoding="utf-8")
    movie = tmp_path / "movie.mp4"
    movie.write_bytes(b"video-bytes")
    remote = FakeRemote()
    client = ArchiveClient(remote, workspace=tmp_path)
    manifest = client.build_manifest(
        manifest_id="manifest_1",
        run_id="runs/one",
        confirmation_ref="confirm_1",
        selections=[
            ArtifactSelection("reports/report.json", report, "application/json"),
            ArtifactSelection("media/movie.mp4", movie, "video/mp4"),
        ],
    )
    assert manifest["items"][0]["content"]["value"] == '{"ok":true}'
    assert manifest["items"][1]["mode"] == "descriptor_only"
    assert manifest["items"][1]["content"] is None
    result = client.commit(run_id="runs/one", manifest=manifest, confirmation_ref="confirm_1")
    assert result["commit_receipt"]["cloud_bytes"] == 0
    encoded = repr(remote.payloads)
    assert "video-bytes" not in encoded
    assert str(tmp_path) not in encoded


def test_delete_requires_plan_and_can_read_back(tmp_path):
    remote = FakeRemote()
    client = ArchiveClient(remote, workspace=tmp_path)
    result = client.delete("archive_1", confirmation_ref="confirm_1", expected_revision=1, readback_receipt_ref="receipt_1")
    assert result["delete"]["hard_deleted"] is True
    assert result["readback"]["verified"] is True
    with pytest.raises(ArchiveClientError):
        client.delete("archive_1", confirmation_ref="", expected_revision=1)


@pytest.mark.parametrize(
    ("name", "content"),
    [
        ("bad.txt", b"\xff\xfe"),
        ("nul.txt", b"ok\x00bad"),
        ("mislabeled.txt", b"\x89PNG\r\n\x1a\nbytes"),
    ],
)
def test_manifest_rejects_binary_nul_and_media_magic_text(tmp_path, name, content):
    path = tmp_path / name
    path.write_bytes(content)
    client = ArchiveClient(FakeRemote(), workspace=tmp_path)
    with pytest.raises(ArchiveClientError) as raised:
        client.build_manifest(
            manifest_id="manifest_1",
            run_id="runs/one",
            confirmation_ref="confirm_1",
            selections=[ArtifactSelection("reports/" + name, path, "text/plain")],
        )
    assert raised.value.code in {"content_forbidden", "content_mismatch"}


def test_manifest_rejects_caller_mime_that_disagrees_with_extension(tmp_path):
    report = tmp_path / "report.json"
    report.write_text(json.dumps({"ok": True}), encoding="utf-8")
    with pytest.raises(ArchiveClientError) as raised:
        ArchiveClient(FakeRemote(), workspace=tmp_path).build_manifest(
            manifest_id="manifest_1",
            run_id="runs/one",
            confirmation_ref="confirm_1",
            selections=[ArtifactSelection("reports/report.json", report, "text/plain")],
        )
    assert raised.value.code == "invalid_mime"


def test_descriptor_rejects_media_bytes_mislabeled_as_text(tmp_path):
    note = tmp_path / "note.txt"
    note.write_bytes(b"\x89PNG\r\n\x1a\nnot-a-text-file")
    with pytest.raises(ArchiveClientError) as raised:
        ArchiveClient(FakeRemote(), workspace=tmp_path).build_manifest(
            manifest_id="manifest_1",
            run_id="runs/one",
            confirmation_ref="confirm_1",
            selections=[
                ArtifactSelection(
                    "reports/note.txt", note, "text/plain", mode="descriptor_only"
                )
            ],
        )
    assert raised.value.code == "content_forbidden"


def test_confirm_recomputes_content_and_accepts_forbidden_without_content(tmp_path):
    report = tmp_path / "report.json"
    report.write_text('{"ok":true}', encoding="utf-8")
    client = ArchiveClient(FakeRemote(), workspace=tmp_path)
    manifest = client.build_manifest(
        manifest_id="manifest_1",
        run_id="runs/one",
        confirmation_ref="confirm_1",
        selections=[ArtifactSelection("reports/report.json", report, "application/json")],
    )
    tampered = json.loads(json.dumps(manifest))
    tampered["items"][0]["content"]["value"] = '{"ok":false}'
    with pytest.raises(ArchiveClientError) as raised:
        client.confirm(tampered, confirmation_ref="confirm_2")
    assert raised.value.code == "content_mismatch"

    forbidden = dict(manifest)
    forbidden["items"] = [dict(manifest["items"][0], mode="forbidden", descriptor=True, content=None)]
    confirmed = client.confirm(forbidden, confirmation_ref="confirm_2")
    assert confirmed["items"][0]["mode"] == "forbidden"
    assert confirmed["items"][0]["content"] is None


def test_confirm_rejects_media_content_and_invalid_artifact_shape():
    raw = b"not media bytes"
    item = {
        "ref": "media/movie.mp4",
        "mode": "content",
        "mime_type": "video/mp4",
        "sha256": sha256(raw).hexdigest(),
        "size_bytes": len(raw),
        "descriptor": False,
        "metadata": {"name": "movie.mp4", "description": None, "source_ref": "media/movie.mp4"},
        "content": {"encoding": "utf8", "value": raw.decode()},
    }
    manifest = {
        "manifest_id": "manifest_1",
        "run_id": "runs/one",
        "confirmation_ref": "confirm_1",
        "items": [item],
        "created_at": "2026-08-04T00:00:00Z",
    }
    with pytest.raises(ArchiveClientError) as raised:
        ArchiveClient(FakeRemote()).confirm(manifest, confirmation_ref="confirm_2")
    assert raised.value.code == "content_forbidden"
