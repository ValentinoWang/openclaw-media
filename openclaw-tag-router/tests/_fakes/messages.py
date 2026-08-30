"""Shared Message fixture for openclaw-tag-router tests.

``make_message`` used to be redefined verbatim (including the same
hardcoded timestamp) in test_llm_required_routes.py, test_creator_profiles.py
and test_activity_daily_llm.py. Import from here instead of redefining a
local copy.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from openclaw_app.models.message import Message

TZ = ZoneInfo("Asia/Shanghai")
DEFAULT_CREATED_AT = datetime(2026, 5, 29, 13, 30, tzinfo=TZ)


def make_message(
    tag: str,
    body: str,
    *,
    source: str = "feishu",
    chat_type: str = "private",
    created_at: datetime = DEFAULT_CREATED_AT,
    metadata: dict | None = None,
) -> Message:
    kwargs: dict = {}
    if metadata is not None:
        # Message.metadata defaults to field(default_factory=dict), not
        # None -- only pass it through when the caller actually supplied
        # one, so callers that don't care still get {} like before.
        kwargs["metadata"] = metadata
    return Message(
        entry_tag=tag,
        raw_text=f"【{tag}】{body}",
        body=body,
        source=source,
        chat_type=chat_type,
        created_at=created_at,
        **kwargs,
    )
