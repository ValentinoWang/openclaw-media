from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from selfmedia.ingest.content_flow.src.downloader import (
    parse_video_ratio_pixels,
    transcode_video_to_ratio,
)


def test_parse_video_ratio_pixels() -> None:
    assert parse_video_ratio_pixels("480p") == 480
    assert parse_video_ratio_pixels("ratio=720p") == 720
    assert parse_video_ratio_pixels("bad") is None


def test_transcode_video_to_ratio_uses_mp4_temp_path_and_portrait_scale(tmp_path: Path) -> None:
    video_path = tmp_path / "video.mp4"
    video_path.write_bytes(b"old-video")
    seen: dict[str, list[str]] = {}

    def fake_run(cmd: list[str], **_kwargs) -> SimpleNamespace:
        seen["cmd"] = cmd
        output_path = Path(cmd[-1])
        assert output_path.name == "video.480p.tmp.mp4"
        output_path.write_bytes(b"new-video")
        return SimpleNamespace(returncode=0)

    with (
        patch(
            "selfmedia.ingest.content_flow.src.downloader.probe_video_dimensions",
            side_effect=[(720, 1280), (480, 854)],
        ),
        patch(
            "selfmedia.ingest.content_flow.src.downloader.subprocess.run",
            side_effect=fake_run,
        ),
    ):
        assert transcode_video_to_ratio(str(video_path), "480p")

    command = seen["cmd"]
    assert command[command.index("-vf") + 1] == "scale=480:-2"
    assert video_path.read_bytes() == b"new-video"


def test_transcode_video_to_ratio_skips_when_portrait_width_already_within_target(
    tmp_path: Path,
) -> None:
    video_path = tmp_path / "video.mp4"
    video_path.write_bytes(b"video")
    run = Mock()

    with (
        patch(
            "selfmedia.ingest.content_flow.src.downloader.probe_video_dimensions",
            return_value=(480, 854),
        ),
        patch("selfmedia.ingest.content_flow.src.downloader.subprocess.run", run),
    ):
        assert not transcode_video_to_ratio(str(video_path), "480p")

    run.assert_not_called()
