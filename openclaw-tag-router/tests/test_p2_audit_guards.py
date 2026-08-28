from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_social_success_reply_does_not_expose_internal_identifiers_or_paths() -> None:
    source = (ROOT / "openclaw-tag-router/openclaw_app/router/social_archive.py").read_text(encoding="utf-8")
    success_block = source.split("if sync_ok:", 1)[1].split("sync_error =", 1)[0]
    assert "人物 ID" not in success_block
    assert "人物目录" not in success_block
    assert "读取视图" not in success_block
    assert "SSOT" not in success_block
    assert "路由记录" not in success_block
    assert '"person_id": archive_result.get' in success_block


def test_inspiration_failure_archive_is_human_readable() -> None:
    source = (ROOT / "openclaw-tag-router/openclaw_app/router/business_vlog.py").read_text(encoding="utf-8")
    failure_block = source.split('"灵感待 LLM 整理"', 1)[1].split("reply =", 1)[0]
    reply_block = source.split("reply =", 1)[1].split("return TaskResult", 1)[0]
    assert "json.dumps(result" not in failure_block
    assert "整理失败原因" in failure_block
    assert "建议补充" in failure_block
    assert "pending_manual" not in reply_block


def test_creation_writer_has_no_retired_score_or_bitable_writer_cluster() -> None:
    source = (ROOT / "selfmedia/creation/writer.py").read_text(encoding="utf-8")
    for name in (
        "LEGACY_CREATION_RECORD_FIELD_SPECS",
        "_creation_output_fields_for_write",
        "_option_score_summary",
        "_script_option_storyboard",
        "_score_payload",
        "_score_summary",
        "_creation_relation_id",
        "_now_ms",
    ):
        if name == "LEGACY_CREATION_RECORD_FIELD_SPECS":
            assert name not in source
        else:
            assert f"def {name}(" not in source
    assert "def _shooting_evidence_appendix_blocks" in source
    assert "_shooting_evidence_appendix_blocks(draft.get(\"evidence_appendix\"))" in source


def test_social_and_inspiration_defaults_are_checkout_bound() -> None:
    social = (ROOT / "openclaw-tag-router/openclaw_app/router/social_archive.py").read_text(encoding="utf-8")
    business = (ROOT / "openclaw-tag-router/openclaw_app/router/business_vlog.py").read_text(encoding="utf-8")
    assert "/home/ubuntu" not in social
    assert "/home/ubuntu" not in business
