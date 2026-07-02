from __future__ import annotations

from typing import Any

from ..deletion_discovery import DiscoveryResult
from ..deletion_plan import DeletionEntity, DeletionPlan
from .base import DeletionContext


DAILY_LABELS = {"待办", "日程", "待办-开发", "今日", "完成", "延期", "取消", "开发-完成", "开发-验证"}
RECORD_KEYS = ("reminder_record_id", "record_id", "feishu_record_id")
CALENDAR_ID_KEYS = ("calendar_id", "日历ID")
EVENT_ID_KEYS = ("event_id", "calendar_event_id", "日历事件ID", "日程事件ID")


class ReminderCalendarDeletionAdapter:
    adapter_id = "reminder_calendar"
    capability_id = "reminder_calendar"
    labels = tuple(sorted(DAILY_LABELS))

    def can_handle(self, discovery: DiscoveryResult) -> bool:
        if discovery.entry_tags & DAILY_LABELS:
            return True
        for candidate in discovery.archive_candidates:
            if self._calendar_ref(candidate.frontmatter) or str(candidate.frontmatter.get("reminder_record_id") or "").strip():
                return True
        return False

    def build_plan(self, discovery: DiscoveryResult, context: DeletionContext) -> DeletionPlan:
        label = sorted(discovery.entry_tags & DAILY_LABELS)[0] if discovery.entry_tags & DAILY_LABELS else "提醒/日程"
        plan = DeletionPlan(
            target_id=discovery.target_id,
            capability_id=self.capability_id,
            capability_label=f"【{label}】",
            matched_by=list(discovery.matched_by),
        )
        for candidate in discovery.archive_candidates:
            for record_id in self._record_ids(candidate.frontmatter):
                plan.add_entity(DeletionEntity("reminder_record", record_id, "reminder_delete_record", "high", detail="将通过 reminder.py delete-record 删除并读回"))
            calendar = self._calendar_ref(candidate.frontmatter)
            if calendar:
                plan.add_entity(DeletionEntity("calendar_event", f"{calendar['calendar_id']}/{calendar['event_id']}", "feishu_calendar_delete_event", "high"))
        return plan

    def execute(self, plan: DeletionPlan, context: DeletionContext) -> DeletionPlan:
        plan.mode = "apply"
        results: list[DeletionEntity] = []
        reminder_service = context.reminder_service
        feishu_service = context.feishu_service
        for entity in plan.entities:
            if entity.kind == "reminder_record":
                if reminder_service is None or not hasattr(reminder_service, "delete"):
                    results.append(DeletionEntity(entity.kind, entity.target, entity.operation, entity.risk, "failed", "missing reminder delete service"))
                    continue
                try:
                    payload = reminder_service.delete(record_id=entity.target, dry_run=False, delete_calendar=True)
                    if not payload.get("ok"):
                        results.append(DeletionEntity(entity.kind, entity.target, entity.operation, entity.risk, "failed", str(payload.get("error") or payload.get("reason") or payload)[:500]))
                    else:
                        readback = ((payload.get("data") or {}).get("readback") or {}) if isinstance(payload, dict) else {}
                        status = "deleted" if readback.get("exists") is False or not readback else "failed"
                        detail = "reminder delete-record completed" if status == "deleted" else "delete-record returned but readback did not prove absence"
                        results.append(DeletionEntity(entity.kind, entity.target, entity.operation, entity.risk, status, detail))
                except Exception as exc:
                    results.append(DeletionEntity(entity.kind, entity.target, entity.operation, entity.risk, "failed", str(exc)[:500]))
            elif entity.kind == "calendar_event":
                parsed = self._parse_calendar_target(entity.target)
                if not parsed or feishu_service is None or not hasattr(feishu_service, "delete_calendar_event"):
                    results.append(DeletionEntity(entity.kind, entity.target, entity.operation, entity.risk, "failed", "missing calendar delete service or invalid target"))
                    continue
                try:
                    feishu_service.delete_calendar_event(parsed["calendar_id"], parsed["event_id"])
                    status = "deleted"
                    detail = ""
                    if hasattr(feishu_service, "read_calendar_event"):
                        try:
                            event = feishu_service.read_calendar_event(parsed["calendar_id"], parsed["event_id"])
                            if event:
                                status = "failed"
                                detail = "calendar readback still found event"
                        except Exception as exc:
                            detail = f"readback absent: {str(exc)[:160]}"
                    results.append(DeletionEntity(entity.kind, entity.target, entity.operation, entity.risk, status, detail))
                except Exception as exc:
                    results.append(DeletionEntity(entity.kind, entity.target, entity.operation, entity.risk, "failed", str(exc)[:500]))
            else:
                results.append(entity)
        plan.entities = results
        plan.blocked = any(entity.status == "failed" for entity in results)
        return plan

    @staticmethod
    def _record_ids(frontmatter: dict[str, Any]) -> list[str]:
        result: list[str] = []
        for key in RECORD_KEYS:
            text = str(frontmatter.get(key) or "").strip()
            if text.startswith("rec") and text not in result:
                result.append(text)
        return result

    @staticmethod
    def _calendar_ref(frontmatter: dict[str, Any]) -> dict[str, str] | None:
        calendar_id = ""
        event_id = ""
        for key in CALENDAR_ID_KEYS:
            calendar_id = str(frontmatter.get(key) or "").strip()
            if calendar_id:
                break
        for key in EVENT_ID_KEYS:
            event_id = str(frontmatter.get(key) or "").strip()
            if event_id:
                break
        return {"calendar_id": calendar_id, "event_id": event_id} if calendar_id and event_id else None

    @staticmethod
    def _parse_calendar_target(target: str) -> dict[str, str] | None:
        calendar_id, sep, event_id = target.partition("/")
        if not sep or not calendar_id or not event_id:
            return None
        return {"calendar_id": calendar_id, "event_id": event_id}
