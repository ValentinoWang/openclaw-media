from __future__ import annotations

from pathlib import Path

from _support import load_script_module


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "backfill_creator_profile_avatars.py"
backfill = load_script_module("backfill_creator_profile_avatars", SCRIPT)


def record(*, avatar: str = "") -> dict:
    return {
        "record_id": "rec_1",
        "fields": {
            "达人档案ID": "creator_1",
            "平台": "抖音",
            "作者ID": "12345",
            "账号名称": "测试账号",
            "主页链接": "https://www.douyin.com/user/example",
            "头像链接": avatar,
        },
    }


def resolved(*, author_id: str = "12345") -> dict:
    return {
        "ok": True,
        "platform": "抖音",
        "resolve_status": "exact_profile_resolved",
        "resolved_author_id": author_id,
        "extracted_profile": {"avatar_url": "https://cdn.example.test/avatar.jpg"},
    }


def test_existing_avatar_is_never_resolved_or_overwritten() -> None:
    def must_not_run(*_args):
        raise AssertionError("resolver must not run")

    outcome = backfill.process_record(
        record(avatar="https://cdn.example.test/current.jpg"),
        table_url="https://example.test/base/x?table=y",
        execute=True,
        resolver=must_not_run,
    )

    assert outcome["status"] == "skipped_existing_avatar"


def test_author_id_mismatch_blocks_write(monkeypatch) -> None:
    monkeypatch.setattr(backfill, "feishu_update_record", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not write")))

    outcome = backfill.process_record(
        record(),
        table_url="https://example.test/base/x?table=y",
        execute=True,
        resolver=lambda *_args: resolved(author_id="different"),
    )

    assert outcome["status"] == "blocked_author_id_mismatch"


def test_dry_run_reports_redacted_avatar_without_writing(monkeypatch) -> None:
    monkeypatch.setattr(backfill, "feishu_update_record", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not write")))

    outcome = backfill.process_record(
        record(),
        table_url="https://example.test/base/x?table=y",
        execute=False,
        resolver=lambda *_args: resolved(),
    )

    assert outcome["status"] == "dry_run_would_write"
    assert outcome["avatar_host"] == "cdn.example.test"
    assert "avatar_url" not in outcome


def test_execute_rechecks_empty_value_and_verifies_readback(monkeypatch) -> None:
    readbacks = iter(("", "https://cdn.example.test/avatar.jpg"))
    writes = []
    monkeypatch.setattr(backfill, "readback_avatar", lambda *_args: next(readbacks))
    monkeypatch.setattr(backfill, "feishu_update_record", lambda *args, **kwargs: writes.append((args, kwargs)))

    outcome = backfill.process_record(
        record(),
        table_url="https://example.test/base/x?table=y",
        execute=True,
        resolver=lambda *_args: resolved(),
    )

    assert outcome["status"] == "written_verified"
    assert len(writes) == 1
    assert writes[0][1]["specs"] == {"头像链接": 15}
