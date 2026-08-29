from pathlib import Path


def test_transcription_final_note_helper_has_one_staticmethod_decorator() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "openclaw-tag-router"
        / "openclaw_app"
        / "services"
        / "content_flow_client.py"
    ).read_text(encoding="utf-8")
    marker = "def _transcription_final_note_value_missing"
    before, _, _ = source.partition(marker)
    window = before[-160:]
    assert window.count("@staticmethod") == 1
