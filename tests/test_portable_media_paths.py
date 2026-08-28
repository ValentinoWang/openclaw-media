from pathlib import Path

from selfmedia.business import id_business
from selfmedia.context import media_context
from selfmedia.deconstruct.viral_content.src.config import load_config


def test_media_path_defaults_use_the_repository_or_current_user_home(monkeypatch) -> None:
    monkeypatch.delenv("OPENCLAW_MEDIA_AGENT_ROOT", raising=False)
    monkeypatch.delenv("OPENCLAW_SELFMEDIA_ROOT", raising=False)
    monkeypatch.delenv("SELFMEDIA_CONTENT_INGEST_PATH", raising=False)

    repo_root = Path(__file__).resolve().parents[1]
    expected_agent_root = repo_root / "config" / "media-agent"

    assert media_context.MEDIA_AGENT_ROOT == expected_agent_root
    assert id_business.SELFMEDIA_ROOT == repo_root
    assert id_business.MEDIA_ROOT == Path.home() / ".openclaw" / "agents" / "media"
    assert load_config().part1_path == repo_root / "selfmedia" / "ingest" / "content_flow"


def test_media_path_defaults_never_embed_a_specific_host_home() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    source_files = (
        repo_root / "selfmedia/context/media_context.py",
        repo_root / "selfmedia/business/id_business.py",
        repo_root / "selfmedia/deconstruct/viral_content/src/config.py",
        repo_root / "selfmedia/deconstruct/viral_content/src/feishu_writer.py",
        repo_root / "selfmedia/deconstruct/viral_content/src/human_insight_cards.py",
        repo_root / "selfmedia/creation/retrieval.py",
        repo_root / "openclaw-tag-router/openclaw_app/services/media_business/admin_platform_cookies.py",
        repo_root / "openclaw-tag-router/openclaw_app/services/media_business/lark_base_projection.py",
    )
    for path in source_files:
        source = path.read_text(encoding="utf-8")
        assert "/home/ubuntu" not in source
        assert "/Users/vsiyo" not in source


def test_insight_and_activity_paths_accept_runtime_overrides(monkeypatch, tmp_path) -> None:
    from selfmedia.creation import retrieval
    from selfmedia.deconstruct.viral_content.src import human_insight_cards

    card_root = tmp_path / "cards"
    monkeypatch.setenv("OPENCLAW_INSIGHT_CARD_LIBRARY_ROOT", str(card_root))
    assert human_insight_cards.card_library_paths()["root"] == card_root

    activity_config = tmp_path / "activity.json"
    activity_config.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("OPENCLAW_ACTIVITY_CONFIG_PATH", str(activity_config))
    assert retrieval.resolve_activity_bitable_url() == ""
