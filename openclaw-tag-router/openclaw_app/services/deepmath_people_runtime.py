"""DeepMath-only GET adapters for U6 people and workload evidence."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math
from pathlib import Path
import re
from typing import Any, Callable, Mapping

import requests
import yaml

from .deepmath_people_recommendation import DeepMathPeopleRecommendation, DirectoryPage
from .deepmath_resources import DeepMathResourceConfig


FEISHU_API = "https://open.feishu.cn/open-apis"
CAPABILITY_TABLE_NAME = "成员能力与容量"
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{8,160}$")


class DeepMathPeopleRuntimeError(RuntimeError):
    """A canonical U6 read source is missing, ambiguous, or unreadable."""


def load_people_capability_base_id(settings_path: str | Path) -> str:
    """Load the sole capability Base binding with no alternate lookup path."""

    try:
        value = yaml.safe_load(Path(settings_path).read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise DeepMathPeopleRuntimeError("DeepMath settings are unreadable") from exc
    section = value.get("deepmath_ceo_thinking") if isinstance(value, Mapping) else None
    if not isinstance(section, Mapping):
        raise DeepMathPeopleRuntimeError("DeepMath settings section is missing")
    token = str(section.get("people_capability_base_id") or "").strip()
    if not _TOKEN_RE.fullmatch(token):
        raise DeepMathPeopleRuntimeError("people_capability_base_id is unresolved")
    return token


class DeepMathPeopleRuntimeTransport:
    """Four-source read transport; it has no mutation method or cache."""

    def __init__(
        self,
        *,
        capability_app_token: str,
        resource: DeepMathResourceConfig,
        access_token: str,
        session: Any = requests,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not _TOKEN_RE.fullmatch(str(capability_app_token or "")):
            raise DeepMathPeopleRuntimeError("capability Base binding is invalid")
        if not resource.tasklist_id or not resource.calendar_id:
            raise DeepMathPeopleRuntimeError("canonical DeepMath workload resources are not bound")
        if not str(access_token or "").strip():
            raise DeepMathPeopleRuntimeError("DeepMath access token is unavailable")
        self.capability_app_token = capability_app_token
        self.resource = resource
        self._token = access_token
        self._session = session
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._capability_table_id: str | None = None

    def _get(self, path: str, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
        response = self._session.get(
            FEISHU_API + path,
            headers={"Authorization": f"Bearer {self._token}"},
            params=dict(params or {}),
            timeout=30,
        )
        try:
            payload = response.json()
        except ValueError as exc:
            raise DeepMathPeopleRuntimeError("Feishu returned non-JSON evidence") from exc
        if response.status_code in {401, 403}:
            raise PermissionError("DeepMath evidence permission denied")
        if response.status_code >= 400 or payload.get("code") not in (None, 0):
            code = payload.get("code", response.status_code)
            if code in {99991663, 99991672, 99991679}:
                raise PermissionError("DeepMath evidence permission denied")
            raise DeepMathPeopleRuntimeError(f"Feishu evidence read failed: code={code}")
        return payload

    def _all_items(
        self,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        item_keys: tuple[str, ...] = ("items",),
        page_size: int = 100,
    ) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        page_token = ""
        seen: set[str] = set()
        while True:
            query = dict(params or {})
            query["page_size"] = page_size
            if page_token:
                query["page_token"] = page_token
            data = self._get(path, query).get("data") or {}
            raw: Any = None
            for key in item_keys:
                if key in data:
                    raw = data.get(key)
                    break
            raw = [] if raw is None else raw
            if not isinstance(raw, list):
                raise DeepMathPeopleRuntimeError("Feishu evidence page is invalid")
            result.extend(item for item in raw if isinstance(item, dict))
            if not bool(data.get("has_more")):
                return result
            next_token = str(data.get("page_token") or "").strip()
            if not next_token or next_token in seen:
                raise DeepMathPeopleRuntimeError("Feishu evidence pagination is incomplete")
            seen.add(next_token)
            page_token = next_token

    def get_directory_page(self, page_token: str | None) -> DirectoryPage:
        params: dict[str, Any] = {
            "department_id": "0",
            "department_id_type": "open_department_id",
            "user_id_type": "open_id",
            "page_size": 50,
        }
        if page_token:
            params["page_token"] = page_token
        data = self._get("/contact/v3/users/find_by_department", params).get("data") or {}
        raw = data.get("items") or data.get("users") or []
        if not isinstance(raw, list) or not isinstance(data.get("has_more", False), bool):
            raise DeepMathPeopleRuntimeError("Directory page is invalid")
        records: list[dict[str, Any]] = []
        for item in raw:
            if not isinstance(item, Mapping):
                raise DeepMathPeopleRuntimeError("Directory record is invalid")
            identity = str(item.get("open_id") or "").strip()
            name = str(item.get("name") or "").strip()
            departments = item.get("department_ids") or []
            if not identity or not name or not isinstance(departments, list):
                raise DeepMathPeopleRuntimeError("Directory identity is incomplete")
            records.append({"directory_id": identity, "name": name, "department": list(departments)})
        return DirectoryPage(
            records=records,
            has_more=bool(data.get("has_more")),
            next_page_token=str(data.get("page_token") or "").strip() or None,
        )

    def _table_id(self) -> str:
        if self._capability_table_id:
            return self._capability_table_id
        tables = self._all_items(
            f"/bitable/v1/apps/{self.capability_app_token}/tables",
            page_size=100,
        )
        matches = [item for item in tables if str(item.get("name") or "") == CAPABILITY_TABLE_NAME]
        if len(tables) != 1 or len(matches) != 1:
            raise DeepMathPeopleRuntimeError("capability Base is not the canonical one-table schema")
        table_id = str(matches[0].get("table_id") or "").strip()
        if not table_id:
            raise DeepMathPeopleRuntimeError("capability table id is missing")
        self._capability_table_id = table_id
        return table_id

    @staticmethod
    def _one_user(value: Any, field: str) -> str:
        if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], Mapping):
            raise DeepMathPeopleRuntimeError(f"{field} must contain exactly one user")
        identity = str(value[0].get("id") or "").strip()
        if not identity:
            raise DeepMathPeopleRuntimeError(f"{field} user identity is missing")
        return identity

    @staticmethod
    def _time(value: Any) -> str | None:
        if value in (None, ""):
            return None
        if isinstance(value, bool):
            raise DeepMathPeopleRuntimeError("capability time is invalid")
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(float(value) / 1000, tz=timezone.utc).isoformat()
        if isinstance(value, str):
            return value
        raise DeepMathPeopleRuntimeError("capability time is invalid")

    @staticmethod
    def _number(value: Any) -> float | None:
        if value in (None, ""):
            return None
        if isinstance(value, bool):
            raise DeepMathPeopleRuntimeError("capability number is invalid")
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise DeepMathPeopleRuntimeError("capability number is invalid") from exc
        if not math.isfinite(number):
            raise DeepMathPeopleRuntimeError("capability number is invalid")
        return number

    def get_capability_records(self) -> list[dict[str, Any]]:
        records = self._all_items(
            f"/bitable/v1/apps/{self.capability_app_token}/tables/{self._table_id()}/records",
            params={"user_id_type": "open_id"},
            page_size=500,
        )
        result: list[dict[str, Any]] = []
        for record in records:
            fields = record.get("fields") or {}
            if not isinstance(fields, Mapping):
                raise DeepMathPeopleRuntimeError("capability record fields are invalid")
            item: dict[str, Any] = {
                "directory_id": self._one_user(fields.get("成员"), "成员"),
                "status": fields.get("记录状态"),
                "confirmation_time": self._time(fields.get("负荷确认时间")),
                "expiry_time": self._time(fields.get("负荷有效至")),
                "responsibilities": fields.get("职责范围"),
                "skills": fields.get("核心技能"),
                "roles": fields.get("可承担角色"),
                "evidence": fields.get("技能证据"),
                "declared_hours": self._number(fields.get("未来7天可分配工时")),
                "unavailable_intervals": fields.get("不可用区间"),
            }
            maintainer = fields.get("维护人")
            item["maintainer"] = self._one_user(maintainer, "维护人") if maintainer not in (None, "", []) else None
            result.append(item)
        return result

    def get_tasks_snapshot(self) -> list[dict[str, Any]]:
        return self._all_items(
            f"/task/v2/tasklists/{self.resource.tasklist_id}/tasks",
            page_size=100,
        )

    def get_calendar_snapshot(self) -> list[dict[str, Any]]:
        now = self._clock()
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        return self._all_items(
            f"/calendar/v4/calendars/{self.resource.calendar_id}/events",
            params={
                "start_time": str(int(now.timestamp())),
                "end_time": str(int((now + timedelta(days=7)).timestamp())),
            },
            page_size=100,
        )


def make_people_recommendation_service(
    *,
    capability_app_token: str,
    resource: DeepMathResourceConfig,
    access_token: str,
    llm: Callable[[Mapping[str, Any]], Any],
    session: Any = requests,
    clock: Callable[[], datetime] | None = None,
) -> DeepMathPeopleRecommendation:
    transport = DeepMathPeopleRuntimeTransport(
        capability_app_token=capability_app_token,
        resource=resource,
        access_token=access_token,
        session=session,
        clock=clock,
    )
    return DeepMathPeopleRecommendation(transport, llm, clock=clock)


__all__ = [
    "DeepMathPeopleRuntimeError",
    "DeepMathPeopleRuntimeTransport",
    "load_people_capability_base_id",
    "make_people_recommendation_service",
]
