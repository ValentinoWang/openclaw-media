from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from openclaw_app.models.message import Message
from openclaw_app.router.hotlist import HotlistMixin
from selfmedia.context import build_media_context
from selfmedia.hotlist.service import HotlistItem, HotlistRequest, HotlistResult, TimeWindow


TENANT_A = "00000000-0000-4000-8000-000000000101"
TENANT_B = "00000000-0000-4000-8000-000000000202"
CHECKED_AT = datetime.fromisoformat("2026-08-28T10:30:00+08:00")


class _HotlistHarness(HotlistMixin):
    def __init__(self, result: HotlistResult) -> None:
        self.hotlist_service = _HotlistService(result)


class _HotlistService:
    def __init__(self, result: HotlistResult) -> None:
        self.result = result

    def run(self, _body: str) -> HotlistResult:
        return self.result


def _request() -> HotlistRequest:
    return HotlistRequest(
        platform="小红书",
        keyword="跑步训练",
        time_window=TimeWindow(label="近7天"),
        tags=("跑步", "训练"),
        sort="likes_desc",
        sort_label="点赞降序",
        limit=5,
    )


def _item() -> HotlistItem:
    return HotlistItem(
        platform="小红书",
        content_id="note-1",
        title="跑步训练：先完成第一周",
        author="跑步小王",
        like_count=321,
        published_at=CHECKED_AT,
        tags=("跑步", "训练"),
        url="https://www.xiaohongshu.com/explore/note-1",
        source_url="https://www.xiaohongshu.com/explore/note-1",
        source_status="platform_detail_verified",
    )


def _result(*, status: str, items: tuple[HotlistItem, ...] = (), blocked_source: str = "", reason: str = "") -> HotlistResult:
    return HotlistResult(
        status=status,
        request=_request(),
        checked_at=CHECKED_AT,
        trace_id="hotlist_internal_trace_123",
        items=items,
        discovered_count=4,
        verified_count=len(items),
        source_status={"candidate_discovery": {"error_code": "HOTLIST_SEARCH_RATE_LIMITED"}},
        blocked_source=blocked_source,
        reason=reason,
    )


def _message(tenant_id: str) -> Message:
    return Message(
        entry_tag="热榜",
        raw_text="【热榜】平台=小红书 关键词=跑步训练",
        body="平台=小红书 关键词=跑步训练",
        metadata={"tenant_id": tenant_id},
    )


def test_ranked_hotlist_persists_only_in_current_tenant_memory_and_is_retrievable() -> None:
    with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"SELFMEDIA_MEMORY_ROOT": tmp}, clear=False):
        result = _HotlistHarness(_result(status="ok", items=(_item(),))).handle_热榜(_message(TENANT_A))

        assert result.ok
        assert result.extra["persisted"] is True
        snapshot_path = Path(tmp) / "tenants" / TENANT_A / "hotlist_snapshots.jsonl"
        saved = json.loads(snapshot_path.read_text(encoding="utf-8").strip())
        assert saved["tenant_id"] == TENANT_A
        assert saved["query_scope"]["keyword"] == "跑步训练"
        assert saved["items"][0] == {
            "author": "跑步小王",
            "content_id": "note-1",
            "like_count": 321,
            "published_at": "2026-08-28T10:30:00+08:00",
            "rank": 1,
            "tags": ["跑步", "训练"],
            "title": "跑步训练：先完成第一周",
        }

        context = build_media_context(platform="小红书", topic="跑步训练", tenant_id=TENANT_A, root=tmp)
        other_tenant = build_media_context(platform="小红书", topic="跑步训练", tenant_id=TENANT_B, root=tmp)

    assert context["loaded"]["recent_hotlist_snapshots"] == 1
    assert "跑步训练：先完成第一周" in context["prompt"]
    assert other_tenant["loaded"]["recent_hotlist_snapshots"] == 0
    assert "跑步训练：先完成第一周" not in other_tenant["prompt"]


def test_pending_and_zero_result_do_not_persist_and_creator_reply_uses_localized_labels() -> None:
    pending = _HotlistHarness(
        _result(
            status="pending_manual",
            blocked_source="platform_note_page",
            reason="作品页需要登录态。",
        )
    )
    zero = _HotlistHarness(
        _result(
            status="no_verified_results",
            reason="没有满足筛选条件的作品。",
        )
    )
    with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"SELFMEDIA_MEMORY_ROOT": tmp}, clear=False):
        pending_result = pending.handle_热榜(_message(TENANT_A))
        zero_result = zero.handle_热榜(_message(TENANT_A))
        snapshot_path = Path(tmp) / "tenants" / TENANT_A / "hotlist_snapshots.jsonl"

    assert not pending_result.ok
    assert pending_result.extra["persisted"] is False
    assert "状态：需要人工处理" in pending_result.reply
    assert "阻塞来源：小红书作品页" in pending_result.reply
    assert "pending_manual" not in pending_result.reply
    assert "platform_note_page" not in pending_result.reply
    assert "追溯ID" not in pending_result.reply
    assert not snapshot_path.exists()

    assert zero_result.ok
    assert zero_result.extra["persisted"] is False
    assert "核验情况：候选 4 条，详情核验 0 条，入榜 0 条。" in zero_result.reply
    assert "来源状态" not in zero_result.reply
    assert "追溯ID" not in zero_result.reply
