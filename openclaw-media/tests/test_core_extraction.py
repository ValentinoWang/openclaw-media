import json
from pathlib import Path

from openclaw_media.core import ExtractionArtifact, ExtractionResult, extract_media_evidence


def _writing_runner(commands):
    def run(command):
        commands.append(command)
        target = Path(command[-1])
        target.write_bytes(f"artifact:{target.name}:{command[6] if '-ss' in command else 'wav'}".encode())

    return run


def test_uniform_dense_and_wav_structured_golden_is_stable_and_relative(tmp_path):
    workspace = tmp_path / "工作区"
    source = workspace / "原片" / "旅行 视频.mp4"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"video")
    commands = []

    result = extract_media_evidence(
        workspace,
        "原片/旅行 视频.mp4",
        "证据/旅行",
        duration_seconds=12.0,
        has_audio=True,
        runner=_writing_runner(commands),
        uniform_count=3,
        dense_interval_seconds=5.0,
    )
    payload = result.to_dict()

    assert payload["status"] == "ok"
    assert payload["source_ref"] == "原片/旅行 视频.mp4"
    assert payload["error_code"] is None
    assert [(item["mode"], item["timestamp_seconds"]) for item in payload["artifacts"]] == [
        ("uniform", 2.0),
        ("uniform", 6.0),
        ("uniform", 10.0),
        ("dense", 0.0),
        ("dense", 5.0),
        ("dense", 10.0),
        ("wav", None),
    ]
    assert [item["ref"] for item in payload["artifacts"]] == [
        "证据/旅行/keyframes/uniform/frame-0001.jpg",
        "证据/旅行/keyframes/uniform/frame-0002.jpg",
        "证据/旅行/keyframes/uniform/frame-0003.jpg",
        "证据/旅行/keyframes/dense/frame-0001.jpg",
        "证据/旅行/keyframes/dense/frame-0002.jpg",
        "证据/旅行/keyframes/dense/frame-0003.jpg",
        "证据/旅行/audio/source.wav",
    ]
    assert all(len(item["sha256"]) == 64 and item["size_bytes"] > 0 for item in payload["artifacts"])
    assert payload["artifacts"][-1] | {"sha256": "HASH", "size_bytes": 0} == {
        "ref": "证据/旅行/audio/source.wav",
        "kind": "audio",
        "mime_type": "audio/wav",
        "size_bytes": 0,
        "sha256": "HASH",
        "mode": "wav",
        "timestamp_seconds": None,
        "duration_seconds": 12.0,
        "sample_rate": 16000,
        "channels": 1,
    }
    serialized = json.dumps(payload, ensure_ascii=False)
    assert str(tmp_path) not in serialized
    assert all(str(source) in command for command in commands)

    repeated = extract_media_evidence(
        workspace,
        "原片/旅行 视频.mp4",
        "证据/旅行",
        duration_seconds=12.0,
        has_audio=True,
        runner=_writing_runner([]),
        uniform_count=3,
        dense_interval_seconds=5.0,
    )
    assert repeated.to_dict() == payload


def test_no_audio_is_explicit_partial_result_and_keeps_frames(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "silent.mp4").write_bytes(b"silent")
    commands = []

    result = extract_media_evidence(
        workspace,
        "silent.mp4",
        "out",
        duration_seconds=4.0,
        has_audio=False,
        runner=_writing_runner(commands),
        uniform_count=1,
        dense_interval_seconds=3.0,
    )

    assert result.status == "partial"
    assert result.error_code == "no_audio"
    assert [artifact.kind for artifact in result.artifacts] == ["keyframe", "keyframe", "keyframe"]
    assert all("pcm_s16le" not in command for command in commands)


def test_corrupt_input_cleans_partial_output_without_exception_or_path_leak(tmp_path):
    workspace = tmp_path / "private" / "workspace"
    workspace.mkdir(parents=True)
    (workspace / "broken.mp4").write_bytes(b"broken")

    def corrupt(command):
        Path(command[-1]).write_bytes(b"partial")
        raise ValueError(f"ffmpeg stderr includes {workspace}/broken.mp4")

    result = extract_media_evidence(
        workspace,
        "broken.mp4",
        "out",
        duration_seconds=2.0,
        has_audio=True,
        runner=corrupt,
    )
    serialized = json.dumps(result.to_dict())

    assert result == ExtractionResult("failed", "broken.mp4", (), "corrupt_input")
    assert str(tmp_path) not in serialized
    assert "stderr" not in serialized
    assert not list((workspace / "out").rglob("*.jpg"))


def test_invalid_duration_is_structured_corrupt_failure(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "bad.mp4").write_bytes(b"bad")

    result = extract_media_evidence(
        workspace,
        "bad.mp4",
        "out",
        duration_seconds=0,
        has_audio=False,
        runner=lambda _command: None,
    )

    assert result.error_code == "corrupt_input"
    assert result.artifacts == ()
    assert all((ExtractionArtifact, ExtractionResult))

    non_finite = extract_media_evidence(
        workspace,
        "bad.mp4",
        "out",
        duration_seconds=float("nan"),
        has_audio=False,
        runner=lambda _command: None,
    )
    assert non_finite == ExtractionResult("failed", "bad.mp4", (), "corrupt_input")
