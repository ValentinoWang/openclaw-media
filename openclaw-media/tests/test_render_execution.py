from __future__ import annotations

import json
from pathlib import Path

from openclaw_media import (
    RenderInput,
    RenderManifest,
    RenderOutput,
    execute_render,
)


def _manifest(audio: int = 1) -> RenderManifest:
    return RenderManifest(
        "media.render.manifest.v1",
        "render-manifests/" + "a" * 64 + ".json",
        "sha256:" + "a" * 64,
        "sha256:" + "b" * 64,
        "artifacts/project.otio",
        "sha256:" + "c" * 64,
        (RenderInput("sha256:" + "d" * 64, "media/source.mp4", "d" * 64, 8, (4, 1), bool(audio)),),
        (30, 1),
        (4, 1),
        120,
        audio,
        "mix_if_present" if audio else "none",
        RenderOutput("renders/" + "a" * 64 + "/final.mp4", "video/mp4", 0),
    )


def test_execute_render_publishes_deterministic_sanitized_receipt_and_preserves_sources(tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"immutable-source")
    before = source.read_bytes()
    calls: list[tuple[str, ...]] = []

    def runner(command: tuple[str, ...]) -> None:
        calls.append(command)
        Path(command[-1]).write_bytes(b"final-output")

    def probe(_path: Path) -> dict[str, object]:
        return {
            "format": {"duration": "4.000000"},
            "streams": [
                {"codec_type": "video", "nb_read_frames": "120", "duration": "4.0"},
                {"codec_type": "audio", "duration": "4.0"},
            ],
        }

    first = execute_render(_manifest(), {"media/source.mp4": source}, tmp_path / "work", runner=runner, probe_runner=probe)
    second = execute_render(_manifest(), {"media/source.mp4": source}, tmp_path / "work-2", runner=runner, probe_runner=probe)

    assert first == second
    assert first.status == "ok"
    assert first.output_ref == "renders/" + "a" * 64 + "/final.mp4"
    assert first.cloud_bytes == 0
    assert first.receipt is not None
    serialized = json.dumps(first.to_dict(), sort_keys=True)
    assert str(tmp_path) not in serialized
    assert "Traceback" not in serialized and "source.mp4" not in serialized
    assert source.read_bytes() == before
    assert calls and any(str(source) in item for item in calls)


def test_execute_render_rejects_corrupt_or_mismatched_output_without_publish(tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")

    def runner(command: tuple[str, ...]) -> None:
        Path(command[-1]).write_bytes(b"bad")

    def probe(_path: Path) -> dict[str, object]:
        return {"format": {"duration": "3.0"}, "streams": [{"codec_type": "video", "nb_read_frames": "2"}]}

    result = execute_render(_manifest(), {"media/source.mp4": source}, tmp_path / "work", runner=runner, probe_runner=probe)
    assert result.status == "rejected"
    assert result.output_ref is None
    assert result.error_codes == ("output_mismatch",)


def test_execute_render_exposes_stable_ffmpeg_failure_and_rejects_absolute_output(tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")

    def failing_runner(_command: tuple[str, ...]) -> None:
        raise RuntimeError("/home/private/secret: ffmpeg exploded")

    failed = execute_render(
        _manifest(), {"media/source.mp4": source}, tmp_path / "work", runner=failing_runner,
        probe_runner=lambda _path: {},
    )
    assert failed.status == "rejected"
    assert failed.error_codes == ("ffmpeg_failed",)
    assert "/home/private" not in json.dumps(failed.to_dict())

    unsafe = _manifest()
    unsafe = RenderManifest(
        unsafe.contract, unsafe.manifest_ref, unsafe.identity_ref, unsafe.revision_identity_ref,
        unsafe.project_otio_ref, unsafe.project_otio_identity_ref, unsafe.inputs, unsafe.frame_rate,
        unsafe.duration, unsafe.expected_video_frames, unsafe.expected_audio_tracks,
        unsafe.audio_disposition, RenderOutput("/home/private/final.mp4", "video/mp4", 0),
    )
    rejected = execute_render(unsafe, {"media/source.mp4": source}, tmp_path / "work", runner=failing_runner)
    assert rejected.error_codes == ("invalid_manifest",)
