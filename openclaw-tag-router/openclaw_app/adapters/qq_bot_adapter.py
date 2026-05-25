from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ..app import OpenClawApp


@dataclass
class QQBotEvent:
    text: str
    user_id: str = "mock-user"
    chat_type: str = "private"
    source: str = "qq"
    created_at: datetime | None = None
    metadata: dict[str, Any] | None = None


class QQBotAdapter:
    def __init__(self, app: OpenClawApp):
        self.app = app

    def should_ignore_event(self, payload: dict[str, Any]) -> str | None:
        post_type = str(payload.get("post_type") or "").strip().lower()
        if post_type and post_type != "message":
            return f"unsupported_post_type:{post_type}"

        event_name = str(payload.get("t") or payload.get("event_type") or "").strip().upper()
        if event_name and "MESSAGE" not in event_name and "AT_MESSAGE" not in event_name:
            if self._extract_text(payload).strip():
                return None
            return f"unsupported_event_type:{event_name}"

        if not self._extract_text(payload).strip():
            return "missing_text"
        return None

    def handle_event(self, event: QQBotEvent | dict[str, Any]) -> dict[str, Any]:
        normalized = event if isinstance(event, QQBotEvent) else self.parse_event(event)
        result = self.app.process_text(
            normalized.text,
            source=normalized.source,
            chat_type=normalized.chat_type,
            created_at=normalized.created_at,
            metadata=normalized.metadata,
        )
        return {
            "reply": result.reply,
            "status": result.status,
            "task_id": result.task_id,
            "local_path": result.local_path,
            "feishu_doc": result.feishu_doc,
            "extra": result.extra,
        }

    def parse_event(self, payload: dict[str, Any]) -> QQBotEvent:
        root = self._unwrap_payload(payload)
        text = self._extract_text(payload).strip()
        if not text:
            raise ValueError("QQ 事件中未找到文本内容")
        normalized_text = self._normalize_text(text)
        if not normalized_text:
            raise ValueError("QQ 事件文本为空")
        source = str(payload.get("source") or root.get("source") or "qqbot")
        chat_type = self._detect_chat_type(payload)
        user_id = str(
            root.get("user_id")
            or root.get("openid")
            or root.get("member_openid")
            or root.get("group_openid")
            or root.get("sender", {}).get("user_id")
            or root.get("sender", {}).get("id")
            or root.get("author", {}).get("id")
            or "unknown-user"
        )
        created_at = self._parse_created_at(
            root.get("created_at")
            or root.get("time")
            or root.get("timestamp")
            or root.get("msg_timestamp")
        )
        metadata = {
            "user_id": user_id,
            "group_id": root.get("group_id") or root.get("group_openid"),
            "guild_id": root.get("guild_id"),
            "channel_id": root.get("channel_id"),
            "openid": root.get("openid"),
            "message_id": root.get("message_id") or root.get("id") or root.get("msg_id"),
            "event_type": payload.get("t") or payload.get("event_type"),
            "raw_event": payload,
        }
        return QQBotEvent(
            text=normalized_text,
            user_id=user_id,
            chat_type=chat_type,
            source=source,
            created_at=created_at,
            metadata=metadata,
        )

    @staticmethod
    def _unwrap_payload(payload: dict[str, Any]) -> dict[str, Any]:
        nested = payload.get("d")
        return nested if isinstance(nested, dict) else payload

    @classmethod
    def _extract_text(cls, payload: dict[str, Any]) -> str:
        root = cls._unwrap_payload(payload)
        direct_candidates = [
            root.get("text"),
            root.get("raw_text"),
            root.get("raw_message"),
            root.get("message_text"),
            root.get("content"),
            root.get("msg_content"),
        ]
        for candidate in direct_candidates:
            if isinstance(candidate, str) and candidate.strip():
                return candidate

        for key in ["message", "content", "data"]:
            candidate = root.get(key)
            if isinstance(candidate, dict):
                for nested_key in ["text", "content", "raw_text", "message"]:
                    nested = candidate.get(nested_key)
                    if isinstance(nested, str) and nested.strip():
                        return nested
                if isinstance(candidate.get("segments"), list):
                    return cls._join_segments(candidate["segments"])
            if isinstance(candidate, list):
                joined = cls._join_segments(candidate)
                if joined.strip():
                    return joined

        for key in ["message_chain", "segments"]:
            if isinstance(root.get(key), list):
                return cls._join_segments(root[key])
        return ""

    @staticmethod
    def _join_segments(segments: list[Any]) -> str:
        parts: list[str] = []
        for segment in segments:
            if isinstance(segment, str):
                parts.append(segment)
            elif isinstance(segment, dict):
                segment_type = str(segment.get("type") or "").lower()
                if segment_type in {"text", "plain"}:
                    parts.append(str(segment.get("data", {}).get("text", "")))
                elif "text" in segment:
                    parts.append(str(segment.get("text", "")))
                elif "content" in segment and isinstance(segment.get("content"), str):
                    parts.append(str(segment.get("content", "")))
                elif isinstance(segment.get("data"), dict) and isinstance(segment["data"].get("content"), str):
                    parts.append(str(segment["data"]["content"]))
        return "".join(parts)

    @staticmethod
    def _normalize_text(text: str) -> str:
        normalized = text.strip()
        normalized = normalized.replace("\r\n", "\n")
        normalized = normalized.replace("[CQ:at,qq=all]", "").strip()
        while normalized.startswith("[CQ:"):
            end = normalized.find("]")
            if end == -1:
                break
            normalized = normalized[end + 1 :].lstrip()
        return normalized

    @staticmethod
    def _detect_chat_type(payload: dict[str, Any]) -> str:
        root = QQBotAdapter._unwrap_payload(payload)
        if root.get("group_id") or root.get("group_openid"):
            return "group"
        if root.get("guild_id") or root.get("channel_id"):
            return "channel"
        if isinstance(root.get("message"), dict) and root["message"].get("chat_type"):
            return str(root["message"]["chat_type"])
        return str(root.get("chat_type") or root.get("message_type") or "private")

    @staticmethod
    def _parse_created_at(value: Any) -> datetime | None:
        if value in {None, ""}:
            return None
        if isinstance(value, (int, float)):
            timestamp = value / 1000 if value > 10_000_000_000 else value
            return datetime.fromtimestamp(timestamp)
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                if value.isdigit():
                    timestamp = int(value)
                    timestamp = timestamp / 1000 if timestamp > 10_000_000_000 else timestamp
                    return datetime.fromtimestamp(timestamp)
                return None
        return None
