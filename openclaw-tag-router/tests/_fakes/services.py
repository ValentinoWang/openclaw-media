"""Shared test fakes for openclaw-tag-router service dependencies.

These fakes are the canonical (most complete / most production-faithful)
versions that used to be duplicated across several test files. Import from
here instead of redefining a local copy, so the fakes can't silently drift
from the real service signatures they stand in for.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from openclaw_app.models.message import Message


class FakeArchiveService:
    def __init__(self):
        self.calls: list[dict] = []
        self.frontmatter_updates: list[dict] = []

    def save_archive(self, message: Message, title: str, sections: list[tuple[str, str]], extra_frontmatter: dict | None = None):
        self.calls.append(
            {
                "message": message,
                "title": title,
                "sections": sections,
                "extra_frontmatter": extra_frontmatter or {},
            }
        )
        return SimpleNamespace(frontmatter={"id": "archive-id"}, local_path="/tmp/archive.md")

    def update_frontmatter(self, path: str, updates: dict):
        self.frontmatter_updates.append({"path": path, "updates": updates})
        return SimpleNamespace(frontmatter={"id": "archive-id", **updates}, local_path=path)
