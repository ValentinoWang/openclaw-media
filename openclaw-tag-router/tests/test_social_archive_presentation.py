from openclaw_app.router.social_archive import SocialArchiveMixin


def test_social_archive_receipts_hide_internal_paths_and_raw_exceptions() -> None:
    raw_reason = "RuntimeError: /Users/creator/archive/rec_internal_001 permission denied"
    rendered = "\n".join(
        (
            SocialArchiveMixin._social_archive_metadata_pending_reply("社交", raw_reason),
            SocialArchiveMixin._social_archive_sync_warning_reply(raw_reason),
            SocialArchiveMixin._social_archive_sync_failure_reply("社交", "小王", raw_reason),
        )
    )

    assert "暂未可靠识别人物" in rendered
    assert "同步受限，请稍后重试或核实文档权限" in rendered
    assert "本次材料已保留，请稍后重试" in rendered
    for internal_value in ("RuntimeError", "/Users/creator", "rec_internal_001", "permission denied"):
        assert internal_value not in rendered
