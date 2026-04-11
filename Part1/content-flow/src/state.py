from __future__ import annotations

from typing import Optional, TypedDict


class FlowState(TypedDict):
    url: str
    video_path: Optional[str]
    audio_path: Optional[str]
    image_paths: Optional[list[str]]
    media_type: Optional[str]
    caption: Optional[str]
    cover_url: Optional[str]
    transcript: str
    analysis_result: dict
    is_success: bool
    notion_page_id: Optional[str]
    platform: Optional[str]
    like_count: Optional[int]
    comment_count: Optional[int]
    share_count: Optional[int]
    top_comments: Optional[list[dict]]
    video_id: Optional[str]
