import json
from pathlib import Path

from openclaw_media.core import MediaFile, MediaScanResult, ProbeResult, StreamInfo, probe_media, scan_media


def _probe(path: Path):
    if path.name == "broken.mp4":
        raise OSError(f"cannot read {path}")
    streams = [{"index": 0, "codec_type": "video", "codec_name": "h264", "width": 1920, "height": 1080}]
    if path.name != "silent.mp4":
        streams.append({"index": 1, "codec_type": "audio", "codec_name": "aac", "sample_rate": "48000", "channels": 2})
    return {"format": {"duration": "12.5", "bit_rate": "8000000"}, "streams": streams}


def test_scan_media_structured_golden_has_relative_refs_and_stable_order(tmp_path):
    media = tmp_path / "项目素材"
    (media / "子目录").mkdir(parents=True)
    (media / "子目录" / "照片.JPG").write_bytes(b"image")
    (media / "silent.mp4").write_bytes(b"silent-video")
    (media / "broken.mp4").write_bytes(b"broken")
    (media / "notes.txt").write_text("ignored")

    result = scan_media(media, probe_runner=_probe, large_file_bytes=10)
    payload = result.to_dict()

    assert payload == {
        "status": "ok",
        "files": (
            {
                "ref": "broken.mp4",
                "kind": "video",
                "extension": ".mp4",
                "size_bytes": 6,
                "size_class": "small",
                "sha256": "f526795c95399cea27c055c842c3d6ab018ed0fa4f66f701c28ab22dec28237b",
                "probe": {
                    "status": "corrupt",
                    "duration_seconds": None,
                    "bit_rate": None,
                    "has_audio": False,
                    "has_video": False,
                    "streams": (),
                    "error_code": "probe_failed",
                },
            },
            {
                "ref": "silent.mp4",
                "kind": "video",
                "extension": ".mp4",
                "size_bytes": 12,
                "size_class": "large",
                "sha256": "62d1731352242fb4737994dd553776a5a00c2c7336852554f1dcb314792d7075",
                "probe": {
                    "status": "ok",
                    "duration_seconds": 12.5,
                    "bit_rate": 8000000,
                    "has_audio": False,
                    "has_video": True,
                    "streams": (
                        {
                            "index": 0,
                            "kind": "video",
                            "codec": "h264",
                            "width": 1920,
                            "height": 1080,
                            "sample_rate": None,
                            "channels": None,
                        },
                    ),
                    "error_code": None,
                },
            },
            {
                "ref": "子目录/照片.JPG",
                "kind": "image",
                "extension": ".jpg",
                "size_bytes": 5,
                "size_class": "small",
                "sha256": "6105d6cc76af400325e94d588ce511be5bfdbb73b437dc51eca43917d7a43e3d",
                "probe": None,
            },
        ),
        "counts": {"audio": 0, "image": 1, "video": 2, "xmp": 0},
    }
    serialized = json.dumps(payload, ensure_ascii=False)
    assert str(tmp_path) not in serialized
    assert serialized.startswith('{"status": "ok"')


def test_scan_media_audio_probe_reports_audio_only(tmp_path):
    media = tmp_path / "media"
    media.mkdir()
    (media / "voice.wav").write_bytes(b"wave")

    def audio_probe(_path):
        return {"format": {"duration": "1.25"}, "streams": [{"index": 0, "codec_type": "audio", "codec_name": "pcm_s16le"}]}

    probe = scan_media(media, probe_runner=audio_probe).files[0].probe
    assert probe is not None
    assert probe.has_audio is True
    assert probe.has_video is False
    assert probe.duration_seconds == 1.25


def test_probe_media_rejects_non_mapping_payload_without_exception_text(tmp_path):
    media = tmp_path / "bad.mp4"
    media.write_bytes(b"bad")

    result = probe_media(media, runner=lambda _path: ["not", "a", "mapping"])

    assert result.error_code == "probe_invalid"
    assert result.status == "corrupt"
    assert "bad.mp4" not in json.dumps(result.__dict__)


def test_core_exports_structured_result_types():
    assert all((StreamInfo, ProbeResult, MediaFile, MediaScanResult))
