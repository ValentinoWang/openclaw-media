from __future__ import annotations

import os
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from .tag_router_common import *


SELFMEDIA_ROOT = Path("/home/ubuntu/selfmedia-tools")
if str(SELFMEDIA_ROOT) not in sys.path:
    sys.path.insert(0, str(SELFMEDIA_ROOT))

from common.social_runtime import (  # noqa: E402
    FEISHU_BASE,
    feishu_bitable_refs,
    feishu_coerce_value,
    feishu_ensure_fields,
    feishu_field_types,
    feishu_headers,
    feishu_list_records,
    feishu_plain_text,
    feishu_tenant_access_token,
    feishu_update_record,
)
from common.standard_fields import standard_field_specs  # noqa: E402
from integrations.feishu.media_writer import upsert_entity_record  # noqa: E402
from selfmedia.creator_profiles import confirm_candidate_run, generate_candidate_run  # noqa: E402


DEFAULT_CREATOR_PROFILES_URL = (
    "https://tcnwueberajc.feishu.cn/base/OmjkbgBkwa2JEysEN8uc5PMhnTb"
    "?table=tblBrERiQnWvZFwp"
)
CREATOR_PROFILE_URL_ENV = "MEDIA_OS_CREATOR_PROFILES_V2_URL"
CREATOR_PROFILE_LIST_LIMIT = 20
CREATOR_PROFILE_DISPLAY_FIELDS = {
    "creator_profile_id": "达人档案ID",
    "platform": "平台",
    "author_id": "作者ID",
    "account_name": "账号名称",
    "profile_url": "主页链接",
    "identity_summary": "身份定位",
    "identity_tags": "身份标签",
    "education_background": "教育背景",
    "expertise_domains": "专业能力领域",
    "creator_role": "创作者角色",
    "public_persona_boundaries": "公开表达边界",
    "story_usable_identity_points": "可创作身份卖点",
    "current_metrics_summary": "当前指标摘要",
}
CREATOR_PROFILE_LIST_FIELDS = {"identity_tags", "expertise_domains"}
CREATOR_PROFILE_READ_ALIASES = {
    "author_id": ("平台ID",),
    "profile_url": ("主页链接",),
    "identity_tags": ("关键词标签",),
    "education_background": ("院校背景",),
}
CREATOR_PROFILE_FIELD_SPECS = {
    name: standard_field_specs()[name]
    for name in (
        "博主IP",
        "平台",
        "平台ID",
        "账号名称",
        "作者ID",
        "主页链接",
        "粉丝数(k)",
        "作品数",
        "赛道",
        "关键词标签",
        "院校背景",
        "创作者主档链接",
        "记录类型",
        "标题",
        "主状态",
        "入库时间",
        "创建时间",
        "更新时间",
    )
}
CREATOR_PROFILE_INPUT_ALIASES = {
    "博主IP": "博主IP",
    "博主": "博主IP",
    "达人": "博主IP",
    "平台": "平台",
    "平台ID": "平台ID",
    "平台账号ID": "平台ID",
    "外部ID": "平台ID",
    "外部唯一ID": "平台ID",
    "账号ID": "平台ID",
    "账号名称": "账号名称",
    "账号": "账号名称",
    "昵称": "账号名称",
    "作者ID": "作者ID",
    "author_id": "作者ID",
    "主页链接": "主页链接",
    "链接": "主页链接",
    "粉丝数(k)": "粉丝数(k)",
    "粉丝数K": "粉丝数(k)",
    "粉丝数": "粉丝数",
    "作品数": "作品数",
    "当前指标": "current_metrics_summary",
    "当前指标摘要": "current_metrics_summary",
    "指标摘要": "current_metrics_summary",
    "current_metrics_summary": "current_metrics_summary",
    "ID类型": "input_platform_id_type",
    "id_type": "input_platform_id_type",
    "模式": "mode",
    "mode": "mode",
    "run_id": "run_id",
    "运行ID": "run_id",
    "赛道": "赛道",
    "身份定位": "identity_summary",
    "一句话身份定位": "identity_summary",
    "个人身份": "identity_summary",
    "identity_summary": "identity_summary",
    "身份标签": "identity_tags",
    "身份标签列表": "identity_tags",
    "关键词": "identity_tags",
    "关键词标签": "identity_tags",
    "标签": "identity_tags",
    "个人特征": "identity_tags",
    "特征": "identity_tags",
    "identity_tags": "identity_tags",
    "教育背景": "education_background",
    "院校背景": "education_background",
    "学校": "education_background",
    "education_background": "education_background",
    "专业能力领域": "expertise_domains",
    "专业/能力领域": "expertise_domains",
    "专业领域": "expertise_domains",
    "能力领域": "expertise_domains",
    "专长": "expertise_domains",
    "expertise_domains": "expertise_domains",
    "创作者角色": "creator_role",
    "创作角色": "creator_role",
    "creator_role": "creator_role",
    "公开表达边界": "public_persona_boundaries",
    "表达边界": "public_persona_boundaries",
    "公开边界": "public_persona_boundaries",
    "人设边界": "public_persona_boundaries",
    "public_persona_boundaries": "public_persona_boundaries",
    "可创作身份卖点": "story_usable_identity_points",
    "可用于创作的身份卖点": "story_usable_identity_points",
    "创作身份卖点": "story_usable_identity_points",
    "身份卖点": "story_usable_identity_points",
    "story_usable_identity_points": "story_usable_identity_points",
    "主状态": "主状态",
    "状态": "主状态",
}
CREATOR_PROFILE_KEY_PATTERN = "|".join(
    re.escape(key) for key in sorted(CREATOR_PROFILE_INPUT_ALIASES, key=len, reverse=True)
)
CREATOR_PROFILE_PAIR_RE = re.compile(
    rf"(?P<key>{CREATOR_PROFILE_KEY_PATTERN})\s*[=:：]\s*(?P<value>.*?)(?=\s+(?:{CREATOR_PROFILE_KEY_PATTERN})\s*[=:：]|\n|$)",
    re.DOTALL,
)
COUNT_RE = re.compile(r"(?P<number>\d+(?:\.\d+)?)\s*(?P<unit>[kKmMwW万千]?)")


class CreatorProfilesMixin:
    def handle_博主(self, message: Message) -> TaskResult:
        try:
            records = self._creator_profile_records()
        except Exception as exc:
            return TaskResult(ok=False, status="creator_profile_list_failed", reply=f"读取博主档案表失败：{exc}", task_id="")

        query = self._parse_creator_profile_query(message.body)
        matched = self._filter_creator_profile_records(records, query)
        limit = int(query.get("limit") or CREATOR_PROFILE_LIST_LIMIT)
        visible = matched[:limit]
        return TaskResult(
            ok=True,
            status="creator_profile_listed",
            reply=self._format_creator_profile_list(visible, total=len(matched), limit=limit),
            task_id="",
            extra={"count": len(matched), "shown": len(visible)},
        )

    def handle_博主_入库(self, message: Message) -> TaskResult:
        fields = self._parse_creator_profile_fields(message.body)
        if self._creator_confirm_write_requested(message.body, fields):
            return self._handle_creator_profile_confirm_write(message.body, fields)
        if self._creator_auto_enrichment_requested(message.body, fields):
            return self._handle_creator_profile_auto_enrichment(fields)

        missing = [name for name in ("平台",) if not self._profile_text(fields.get(name))]
        if not self._profile_text(fields.get("作者ID") or fields.get("平台ID")):
            missing.append("作者ID/平台ID")
        if not self._profile_text(fields.get("账号名称") or fields.get("博主IP")):
            missing.append("账号名称/博主IP")
        if missing:
            return TaskResult(
                ok=False,
                status="creator_profile_missing_required",
                reply=(
                    "博主档案没有写入：缺少必填字段 "
                    + "、".join(missing)
                    + "\n\n最小格式：\n【博主-入库】\n账号名称：\n平台：\n作者ID：\n身份定位：\n身份标签："
                ),
                task_id="",
            )

        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        fields.setdefault("记录类型", "达人账号档案")
        fields.setdefault("标题", self._creator_profile_title(fields))
        fields.setdefault("主状态", "已入库")
        fields.setdefault("入库时间", now)
        fields.setdefault("创建时间", now)
        fields["更新时间"] = now

        try:
            result = self._creator_upsert_profile(fields)
        except Exception as exc:
            return TaskResult(ok=False, status="creator_profile_upsert_failed", reply=f"博主档案写入失败：{exc}", task_id="")

        action = {"created": "新建", "updated": "更新"}.get(str(result.get("action") or ""), "写入")
        reply_lines = [
            f"博主档案已{action}",
            f"账号名称：{fields.get('账号名称') or fields.get('博主IP')}",
            f"外部唯一ID：{self._creator_external_id(fields)}",
            f"平台：{fields.get('平台')}",
            f"身份信息：{self._creator_feature_summary(fields)}",
        ]
        if result.get("record_id"):
            reply_lines.append(f"记录 ID：{result['record_id']}")
        if result.get("table_url"):
            reply_lines.append(f"多维表格：{result['table_url']}")
        return TaskResult(
            ok=True,
            status="creator_profile_upserted",
            reply="\n".join(reply_lines),
            task_id=str(result.get("record_id") or ""),
            extra={"creator_profile": {"fields": fields, "feishu": result}},
        )

    def _creator_confirm_write_requested(self, body: str, fields: dict[str, Any]) -> bool:
        return "确认写入" in str(body or "") and bool(self._creator_run_id(body, fields))

    def _creator_auto_enrichment_requested(self, body: str, fields: dict[str, Any]) -> bool:
        mode = self._profile_text(fields.get("mode"))
        text = str(body or "")
        return "自动补全" in mode or "自动补全" in text or mode.lower() in {"auto", "candidate", "enrich"}

    def _creator_run_id(self, body: str, fields: dict[str, Any]) -> str:
        explicit = self._profile_text(fields.get("run_id"))
        if explicit:
            return explicit
        match = re.search(r"run_id\s*[=:：]\s*([0-9TZ]+)", str(body or ""), flags=re.IGNORECASE)
        if match:
            return match.group(1).strip()
        match = re.search(r"运行ID\s*[=:：]\s*([0-9TZ]+)", str(body or ""))
        return match.group(1).strip() if match else ""

    def _handle_creator_profile_auto_enrichment(self, fields: dict[str, Any]) -> TaskResult:
        platform = self._profile_text(fields.get("平台"))
        platform_id = self._profile_text(fields.get("平台ID") or fields.get("作者ID"))
        if not platform or not platform_id:
            return TaskResult(
                ok=False,
                status="creator_profile_auto_missing_required",
                reply="博主档案自动补全未执行：缺少 平台 或 平台ID。",
                task_id="",
            )
        try:
            candidate = self._generate_creator_profile_candidate_run(
                platform=platform,
                platform_id=platform_id,
                id_type=self._profile_text(fields.get("input_platform_id_type")),
                url=self._profile_text(fields.get("主页链接")),
                creator_name=self._profile_text(fields.get("账号名称") or fields.get("博主IP")),
            )
        except Exception as exc:
            return TaskResult(ok=False, status="creator_profile_auto_failed", reply=f"博主档案自动补全失败：{exc}", task_id="")
        if candidate.get("write_status") != "candidate_only_not_written":
            resolver = candidate.get("resolver") if isinstance(candidate.get("resolver"), dict) else {}
            return TaskResult(
                ok=False,
                status=str(resolver.get("resolve_status") or candidate.get("write_status") or "creator_profile_auto_blocked"),
                reply=(
                    "博主档案自动补全未生成可写候选，未写入。\n"
                    f"run_id：{candidate.get('run_id') or '待补'}\n"
                    f"状态：{resolver.get('resolve_status') or candidate.get('write_status') or 'blocked'}\n"
                    f"证据：{candidate.get('evidence_uri') or '待补'}"
                ),
                task_id=str(candidate.get("run_id") or ""),
                extra={"creator_profile_candidate": candidate},
            )
        reply = self._format_creator_profile_candidate_reply(candidate)
        return TaskResult(
            ok=True,
            status="creator_profile_candidate_ready",
            reply=reply,
            task_id=str(candidate.get("run_id") or ""),
            extra={"creator_profile_candidate": candidate},
        )

    def _handle_creator_profile_confirm_write(self, body: str, fields: dict[str, Any]) -> TaskResult:
        run_id = self._creator_run_id(body, fields)
        if not run_id:
            return TaskResult(ok=False, status="creator_profile_confirm_missing_run_id", reply="确认写入缺少 run_id。", task_id="")
        try:
            result = self._confirm_creator_profile_candidate_run(run_id, user_edits=self._creator_candidate_user_edits(fields))
        except Exception as exc:
            return TaskResult(ok=False, status="creator_profile_confirm_failed", reply=f"博主档案确认写入失败：{exc}", task_id=run_id)
        creator = result.get("creator_profile") if isinstance(result.get("creator_profile"), dict) else {}
        reply_lines = [
            "已写入 06_CreatorProfiles_达人账号档案。",
            f"run_id：{run_id}",
            f"record_id：{creator.get('record_id') or '待补'}",
            f"指标快照：{result.get('metric_snapshot_status') or '待补'}",
            f"evidence_uri：{result.get('evidence_uri') or '待补'}",
        ]
        return TaskResult(
            ok=True,
            status="creator_profile_confirmed_written",
            reply="\n".join(reply_lines),
            task_id=str(creator.get("record_id") or run_id),
            extra={"creator_profile_confirm": result},
        )

    def _creator_candidate_user_edits(self, fields: dict[str, Any]) -> dict[str, Any]:
        edits: dict[str, Any] = {}
        for key in (
            "identity_summary",
            "identity_tags",
            "education_background",
            "expertise_domains",
            "creator_role",
            "public_persona_boundaries",
            "story_usable_identity_points",
            "current_metrics_summary",
        ):
            if key in fields:
                edits[key] = self._profile_list(fields[key]) if key in CREATOR_PROFILE_LIST_FIELDS else self._profile_text(fields[key])
        return edits

    def _generate_creator_profile_candidate_run(self, **kwargs: Any) -> dict[str, Any]:
        return generate_candidate_run(**kwargs)

    def _confirm_creator_profile_candidate_run(self, run_id: str, *, user_edits: dict[str, Any] | None = None) -> dict[str, Any]:
        return confirm_candidate_run(run_id, user_edits=user_edits or {})

    def _format_creator_profile_candidate_reply(self, candidate: dict[str, Any]) -> str:
        payload = candidate.get("candidate_payload") if isinstance(candidate.get("candidate_payload"), dict) else {}
        resolver = candidate.get("resolver") if isinstance(candidate.get("resolver"), dict) else {}
        lines = [
            "已生成 CreatorProfile v2 候选，暂未写入。",
            "",
            f"平台：{payload.get('platform') or resolver.get('platform') or '待补'}",
            f"输入平台ID：{resolver.get('input_platform_id') or '待补'}",
            f"账号名：{payload.get('account_name') or '待补'}",
            f"主页链接：{payload.get('profile_url') or '待补'}",
            f"验证状态：{resolver.get('resolve_status') or '待补'}",
            f"当前指标：{payload.get('current_metrics_summary') or '待补'}",
            f"evidence_uri：{candidate.get('evidence_uri') or '待补'}",
            f"run_id：{candidate.get('run_id') or '待补'}",
            "",
            "候选字段：",
        ]
        for key, label in (
            ("identity_summary", "身份定位"),
            ("identity_tags", "身份标签"),
            ("education_background", "教育背景"),
            ("expertise_domains", "专业能力领域"),
            ("creator_role", "创作者角色"),
            ("public_persona_boundaries", "公开表达边界"),
            ("story_usable_identity_points", "可创作身份卖点"),
        ):
            value = payload.get(key)
            if isinstance(value, list):
                value = "、".join(str(item) for item in value if str(item).strip())
            lines.append(f"- {label}：{value or '待人工补充'}")
        lines.extend(
            [
                "",
                "确认写入：",
                "【博主-入库】",
                "确认写入",
                f"run_id：{candidate.get('run_id') or ''}",
            ]
        )
        return "\n".join(lines)

    def _creator_profile_table_url(self) -> str:
        return os.getenv(CREATOR_PROFILE_URL_ENV, "").strip() or DEFAULT_CREATOR_PROFILES_URL

    def _creator_profile_records(self, *, url: str | None = None, token: str | None = None) -> list[dict[str, Any]]:
        return feishu_list_records(url or self._creator_profile_table_url(), token=token or feishu_tenant_access_token(), page_size=500)

    def _parse_creator_profile_query(self, body: str) -> dict[str, Any]:
        text = str(body or "").strip()
        limit = CREATOR_PROFILE_LIST_LIMIT
        if match := re.search(r"(?:最近|前)?\s*(\d{1,3})\s*(?:条|个)?", text):
            limit = max(1, min(100, int(match.group(1))))
        filters = self._parse_creator_profile_fields(text)
        return {"text": text, "limit": limit, "filters": filters}

    def _parse_creator_profile_fields(self, body: str) -> dict[str, Any]:
        text = str(body or "").replace("\r\n", "\n").strip()
        fields: dict[str, Any] = {}
        for match in CREATOR_PROFILE_PAIR_RE.finditer(text):
            key = match.group("key").strip()
            value = match.group("value").strip(" \t\n；;")
            if not value:
                continue
            target = CREATOR_PROFILE_INPUT_ALIASES.get(key, key)
            if target == "粉丝数":
                parsed_fans = self._parse_fans_k(value)
                if parsed_fans is not None:
                    fields["粉丝数(k)"] = parsed_fans
                continue
            if target == "平台ID" and key in {"外部ID", "外部唯一ID"}:
                platform, platform_id = self._split_creator_external_id(value)
                if platform and not fields.get("平台"):
                    fields["平台"] = platform
                fields["平台ID"] = platform_id
                continue
            if target in CREATOR_PROFILE_LIST_FIELDS:
                fields[target] = self._profile_list([*self._as_profile_list(fields.get(target)), *self._as_profile_list(value)])
                continue
            if target == "赛道" and fields.get(target):
                fields[target] = self._join_profile_values(fields[target], value)
            else:
                fields[target] = value
        return fields

    def _split_creator_external_id(self, value: str) -> tuple[str, str]:
        text = self._profile_text(value)
        if "：" in text:
            platform, platform_id = text.split("：", 1)
            return platform.strip(), platform_id.strip()
        if ":" in text:
            platform, platform_id = text.split(":", 1)
            return platform.strip(), platform_id.strip()
        return "", text

    def _parse_fans_k(self, value: Any) -> float | None:
        text = self._profile_text(value)
        if not text:
            return None
        match = COUNT_RE.search(text.replace(",", ""))
        if not match:
            return None
        number = float(match.group("number"))
        unit = match.group("unit").lower()
        if unit == "万" or unit == "w":
            return round(number * 10, 2)
        if unit == "千":
            return round(number, 2)
        if unit == "k":
            return round(number, 2)
        if number >= 1000:
            return round(number / 1000, 2)
        return round(number, 2)

    def _join_profile_values(self, *values: Any) -> str:
        result: list[str] = []
        seen: set[str] = set()
        for value in values:
            for part in re.split(r"[,，/、;；|]\s*", self._profile_text(value)):
                item = part.strip()
                if not item or item in seen:
                    continue
                seen.add(item)
                result.append(item)
        return "、".join(result)

    def _filter_creator_profile_records(self, records: list[dict[str, Any]], query: dict[str, Any]) -> list[dict[str, Any]]:
        filters = query.get("filters") if isinstance(query.get("filters"), dict) else {}
        text = self._query_text_without_pairs(str(query.get("text") or ""))
        result: list[dict[str, Any]] = []
        for record in records:
            fields = record.get("fields") or {}
            if not isinstance(fields, dict):
                continue
            if filters and not self._creator_fields_match_filters(fields, filters):
                continue
            if text and self._profile_search_text(text) not in self._profile_search_text(self._creator_search_blob(fields)):
                continue
            result.append(record)
        return result

    def _query_text_without_pairs(self, text: str) -> str:
        cleaned = CREATOR_PROFILE_PAIR_RE.sub("", text).strip(" \n；;")
        cleaned = re.sub(r"(?:最近|前)?\s*\d{1,3}\s*(?:条|个)?", "", cleaned).strip()
        return cleaned

    def _creator_fields_match_filters(self, fields: dict[str, Any], filters: dict[str, Any]) -> bool:
        for key, expected in filters.items():
            actual = self._creator_field_text(fields, key)
            if not actual:
                actual = self._profile_text(fields.get(key))
            if not actual:
                return False
            if self._profile_search_text(expected) not in self._profile_search_text(actual):
                return False
        return True

    def _creator_search_blob(self, fields: dict[str, Any]) -> str:
        names = (
            "博主IP",
            "平台",
            "平台ID",
            "账号名称",
            "作者ID",
            "profile_url",
            "赛道",
            "identity_summary",
            "identity_tags",
            "education_background",
            "expertise_domains",
            "creator_role",
            "public_persona_boundaries",
            "story_usable_identity_points",
            "主状态",
        )
        return "\n".join(self._creator_field_text(fields, name) for name in names)

    def _format_creator_profile_list(self, records: list[dict[str, Any]], *, total: int, limit: int) -> str:
        if not records:
            return "暂无匹配的博主档案记录。"
        lines = [f"已归档博主：共 {total} 条，显示 {len(records)} 条。"]
        if total > limit:
            lines.append(f"可用 `【博主】30` 查看更多，或加平台/博主IP/平台ID筛选。")
        for index, record in enumerate(records, start=1):
            fields = record.get("fields") or {}
            title = self._creator_field_text(fields, "account_name") or self._profile_text(fields.get("博主IP")) or self._creator_field_text(fields, "author_id") or str(record.get("record_id") or "未命名")
            lines.extend(
                [
                    f"{index}. 账号名称：{title}",
                    f"   外部唯一ID：{self._creator_external_id(fields)}",
                    f"   记录ID：{record.get('record_id') or '待补'}",
                    f"   平台：{self._creator_field_text(fields, 'platform') or '待补'}；账号名称：{self._creator_field_text(fields, 'account_name') or '待补'}；作者ID：{self._creator_field_text(fields, 'author_id') or '待补'}",
                    f"   主页链接：{self._creator_field_text(fields, 'profile_url') or '待补'}",
                    f"   身份信息：{self._creator_feature_summary(fields)}",
                ]
            )
            creator_doc = self._profile_text(fields.get("创作者主档链接"))
            if creator_doc:
                lines.append(f"   档案：{creator_doc}")
        return "\n".join(lines)

    def _creator_feature_summary(self, fields: dict[str, Any]) -> str:
        parts = [
            f"身份定位={self._creator_field_text(fields, 'identity_summary')}" if self._creator_field_text(fields, "identity_summary") else "",
            f"身份标签={self._creator_field_text(fields, 'identity_tags')}" if self._creator_field_text(fields, "identity_tags") else "",
            f"教育背景={self._creator_field_text(fields, 'education_background')}" if self._creator_field_text(fields, "education_background") else "",
            f"专业能力={self._creator_field_text(fields, 'expertise_domains')}" if self._creator_field_text(fields, "expertise_domains") else "",
            f"创作者角色={self._creator_field_text(fields, 'creator_role')}" if self._creator_field_text(fields, "creator_role") else "",
            f"公开边界={self._creator_field_text(fields, 'public_persona_boundaries')}" if self._creator_field_text(fields, "public_persona_boundaries") else "",
            f"创作卖点={self._creator_field_text(fields, 'story_usable_identity_points')}" if self._creator_field_text(fields, "story_usable_identity_points") else "",
            f"当前指标={self._creator_field_text(fields, 'current_metrics_summary')}" if self._creator_field_text(fields, "current_metrics_summary") else "",
            f"赛道={self._profile_text(fields.get('赛道'))}" if self._profile_text(fields.get("赛道")) else "",
            f"粉丝数(k)={self._profile_text(fields.get('粉丝数(k)'))}" if self._profile_text(fields.get("粉丝数(k)")) else "",
            f"作品数={self._profile_text(fields.get('作品数'))}" if self._profile_text(fields.get("作品数")) else "",
        ]
        return "；".join(part for part in parts if part) or "待补"

    def _creator_external_id(self, fields: dict[str, Any]) -> str:
        platform = self._creator_field_text(fields, "platform") or "未知平台"
        platform_id = self._creator_field_text(fields, "author_id") or self._profile_text(fields.get("平台ID"))
        if platform_id:
            return f"{platform}:{platform_id}"
        return "待补（缺平台ID）"

    def _creator_profile_title(self, fields: dict[str, Any]) -> str:
        name = self._profile_text(fields.get("账号名称") or fields.get("博主IP") or fields.get("作者ID") or fields.get("平台ID")) or "未命名博主"
        return f"博主档案｜{name}"

    def _creator_upsert_profile(self, fields: dict[str, Any]) -> dict[str, Any]:
        url = self._creator_profile_table_url()
        payload = self._creator_profile_v2_payload(fields)
        result = upsert_entity_record("CreatorProfile", url, payload, key_field="creator_profile_id")
        return {"ok": True, "action": result.get("mode") or "write", "record_id": result.get("record_id") or "", "table_url": url}

    def _creator_profile_v2_payload(self, fields: dict[str, Any]) -> dict[str, Any]:
        platform = self._profile_text(fields.get("平台"))
        author_id = self._profile_text(fields.get("作者ID") or fields.get("平台ID"))
        account_name = self._profile_text(fields.get("账号名称") or fields.get("博主IP"))
        profile_id = f"creator_{self._safe_id_part(platform)}_{self._safe_id_part(author_id)}"
        return {
            "creator_profile_id": profile_id,
            "platform": platform,
            "author_id": author_id,
            "account_name": account_name,
            "profile_url": self._profile_text(fields.get("主页链接")),
            "identity_summary": self._profile_text(fields.get("identity_summary")),
            "identity_tags": self._profile_list(fields.get("identity_tags")),
            "education_background": self._profile_text(fields.get("education_background")),
            "expertise_domains": self._profile_list(fields.get("expertise_domains")),
            "creator_role": self._profile_text(fields.get("creator_role")),
            "public_persona_boundaries": self._profile_text(fields.get("public_persona_boundaries")),
            "story_usable_identity_points": self._profile_text(fields.get("story_usable_identity_points")),
            "current_metrics_summary": self._creator_metrics_summary(fields),
        }

    def _creator_metrics_summary(self, fields: dict[str, Any]) -> str:
        explicit = self._profile_text(fields.get("current_metrics_summary"))
        if explicit:
            return explicit
        parts = [
            f"粉丝数(k)={self._profile_text(fields.get('粉丝数(k)'))}" if self._profile_text(fields.get("粉丝数(k)")) else "",
            f"作品数={self._profile_text(fields.get('作品数'))}" if self._profile_text(fields.get("作品数")) else "",
        ]
        return "；".join(part for part in parts if part)

    def _safe_id_part(self, value: Any) -> str:
        text = self._profile_search_text(value)
        text = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "_", text, flags=re.IGNORECASE)
        return re.sub(r"_+", "_", text).strip("_") or "unknown"

    def _find_creator_profile_record(self, fields: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, Any] | None:
        platform = self._profile_text(fields.get("平台"))
        platform_id = self._profile_text(fields.get("平台ID"))
        creator_ip = self._profile_text(fields.get("博主IP"))
        for record in records:
            current = record.get("fields") or {}
            if not isinstance(current, dict):
                continue
            same_platform = not platform or platform == self._profile_text(current.get("平台"))
            if same_platform and platform_id and platform_id == self._profile_text(current.get("平台ID")):
                return record
            if same_platform and creator_ip and creator_ip == self._profile_text(current.get("博主IP")):
                return record
        return None

    def _creator_create_profile(self, url: str, fields: dict[str, Any], *, token: str) -> str:
        app_token, table_id, token = feishu_bitable_refs(url, token)
        feishu_ensure_fields(app_token, table_id, token, CREATOR_PROFILE_FIELD_SPECS)
        field_types = feishu_field_types(app_token, table_id, token)
        payload_fields: dict[str, Any] = {}
        for key, value in fields.items():
            if key not in field_types:
                continue
            coerced = feishu_coerce_value(value, field_types[key])
            if coerced in (None, "", []):
                continue
            payload_fields[key] = coerced
        if not payload_fields:
            raise RuntimeError("没有可写入飞书的博主字段")
        response = requests.post(
            f"{FEISHU_BASE}/bitable/v1/apps/{app_token}/tables/{table_id}/records",
            headers=feishu_headers(token),
            json={"fields": payload_fields},
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("code") != 0:
            raise RuntimeError(f"创建博主档案记录失败：{payload}")
        return str((payload.get("data", {}).get("record") or {}).get("record_id") or "")

    def _profile_text(self, value: Any) -> str:
        return feishu_plain_text(value).strip()

    def _creator_field_text(self, fields: dict[str, Any], canonical_name: str) -> str:
        display_name = CREATOR_PROFILE_DISPLAY_FIELDS.get(canonical_name, canonical_name)
        value = self._profile_text(fields.get(canonical_name) or fields.get(display_name))
        if not value:
            for alias in CREATOR_PROFILE_READ_ALIASES.get(canonical_name, ()):
                value = self._profile_text(fields.get(alias))
                if value:
                    break
        return value

    def _as_profile_list(self, value: Any) -> list[str]:
        if value in (None, "", []):
            return []
        if isinstance(value, list):
            raw_items = value
        else:
            raw_items = re.split(r"[,，/、;；|]\s*", self._profile_text(value))
        result: list[str] = []
        seen: set[str] = set()
        for item in raw_items:
            text = self._profile_text(item)
            if not text or text in seen:
                continue
            seen.add(text)
            result.append(text)
        return result

    def _profile_list(self, value: Any) -> list[str]:
        return self._as_profile_list(value)

    def _profile_search_text(self, value: Any) -> str:
        text = unicodedata.normalize("NFKC", self._profile_text(value)).casefold()
        return re.sub(r"\s+", "", text)
