from pathlib import Path

from selfmedia.business import id_business
from selfmedia.context import media_context
from selfmedia.deconstruct.viral_content.src.config import load_config


def test_media_path_defaults_use_the_repository_or_current_user_home(monkeypatch) -> None:
    monkeypatch.delenv("OPENCLAW_MEDIA_AGENT_ROOT", raising=False)
    monkeypatch.delenv("OPENCLAW_SELFMEDIA_ROOT", raising=False)
    monkeypatch.delenv("SELFMEDIA_CONTENT_INGEST_PATH", raising=False)

    repo_root = Path(__file__).resolve().parents[1]
    expected_agent_root = Path.home() / ".openclaw" / "agents" / "media"

    assert media_context.MEDIA_AGENT_ROOT == expected_agent_root
    assert id_business.SELFMEDIA_ROOT == repo_root
    assert id_business.MEDIA_ROOT == expected_agent_root
    assert load_config().part1_path == repo_root / "selfmedia" / "ingest" / "content_flow"


def test_media_path_defaults_never_embed_a_specific_host_home() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    source_files = (
        repo_root / "selfmedia/context/media_context.py",
        repo_root / "selfmedia/business/id_business.py",
        repo_root / "selfmedia/deconstruct/viral_content/src/config.py",
        repo_root / "selfmedia/deconstruct/viral_content/src/feishu_writer.py",
        repo_root / "openclaw-tag-router/openclaw_app/services/media_business/admin_platform_cookies.py",
        repo_root / "openclaw-tag-router/openclaw_app/services/media_business/lark_base_projection.py",
    )
    for path in source_files:
        source = path.read_text(encoding="utf-8")
        assert "/home/ubuntu" not in source
        assert "/Users/vsiyo" not in source
