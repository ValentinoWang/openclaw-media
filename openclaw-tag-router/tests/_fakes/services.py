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


class FakeReminderService:
    """Stand-in for ReminderService whose add() keyword signature is copied
    verbatim from reminder_service.py so a new production kwarg (e.g.
    ``priority``) can't silently start being dropped/mismatched here.

    ``result`` overrides the default success payload wholesale (use this
    when a caller's assertions depend on specific record_id/table_url
    values); ``ok=False`` without an explicit ``result`` yields a generic
    failure payload; ``enabled=False`` mirrors the real service's
    short-circuit before it would otherwise attempt anything.
    """

    bitable_url = "https://bitable.default"
    config_paths: dict[str, str] = {}

    def __init__(self, *, result: dict | None = None, ok: bool = True, enabled: bool = True):
        self.calls: list[dict] = []
        self.enabled = enabled
        self._ok = ok
        self._result = result

    def add(
        self,
        *,
        kind: str,
        title: str,
        text: str,
        due_at: datetime | None,
        remind_at: datetime | None = None,
        source: str = "openclaw",
        ref_id: str = "",
        local_path: str = "",
        priority: str = "",
        extra_fields: dict | None = None,
        omit_management_fields: bool = False,
        config_path_key: str | None = None,
    ) -> dict:
        self.calls.append(
            {
                "kind": kind,
                "title": title,
                "text": text,
                "due_at": due_at,
                "remind_at": remind_at,
                "source": source,
                "ref_id": ref_id,
                "local_path": local_path,
                "priority": priority,
                "extra_fields": extra_fields,
                "omit_management_fields": omit_management_fields,
                "config_path_key": config_path_key,
            }
        )
        if not self.enabled:
            return {"ok": False, "skipped": True, "reason": "disabled"}
        if self._result is not None:
            return self._result
        if not self._ok:
            return {"ok": False, "error": "fake_reminder_add_failed"}
        return {
            "ok": True,
            "data": {
                "record_id": "rec-test",
                "table_url": "https://bitable.test",
                "calendar": {"ok": True, "event_id": "evt-test", "app_link": "https://calendar.test"},
            },
        }
