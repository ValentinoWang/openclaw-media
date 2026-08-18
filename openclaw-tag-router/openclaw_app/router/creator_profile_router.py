from __future__ import annotations

import json
import os
import re
import sys
import unicodedata
from dataclasses import replace
from pathlib import Path
from typing import Any

from .tag_router_common import *


SELFMEDIA_ROOT = Path("/home/ubuntu/selfmedia-tools")
if str(SELFMEDIA_ROOT) not in sys.path:
    sys.path.insert(0, str(SELFMEDIA_ROOT))

from common.social_runtime import (  # noqa: E402
    feishu_list_records,
    feishu_plain_text,
    feishu_tenant_access_token,
)
from selfmedia.creator_profiles import confirm_candidate_run, generate_candidate_run  # noqa: E402
from ..services.tenant_execution_context import current_session_tenant_id


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
    "avatar_url": "头像链接",
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
    "avatar_url": ("头像链接",),
    "identity_tags": ("关键词标签",),
    "education_background": ("院校背景",),
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
    "头像链接": "avatar_url",
    "avatar_url": "avatar_url",
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
    "内容领域": "expertise_domains",
    "账号类型": "expertise_domains",
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
CREATOR_PROFILE_UNIFIED_ACTION_RE = re.compile(
    r"(?:^|\n)\s*(?:能力|动作|操作|意图|类型)\s*[：:]\s*(?P<value>[^\n；;，,。]+)",
    re.I,
)
CREATOR_PROFILE_INFO_LINE_RE = re.compile(r"^\s*(?:信息|内容|资料|材料|正文)\s*[：:]\s*(?P<value>.*)$", re.I)
CREATOR_PROFILE_ACTION_LINE_RE = re.compile(r"^\s*(?:能力|动作|操作|意图|类型)\s*[：:].*$", re.I)
CREATOR_PROFILE_UNIFIED_ACTIONS = {
    "查询": "query",
    "入库": "upsert",
}
CREATOR_PROFILE_BATCH_RE = re.compile(r"^\s*(?:批量入库|批量导入|批量)\s*[：:]?\s*", re.I)
CREATOR_PROFILE_BATCH_LIMIT = 100


class CreatorProfilesMixin:
    def handle_博主(self, message: Message) -> TaskResult:
        dispatch = self._creator_profile_unified_dispatch(message.body)
        if dispatch == "unknown":
            return TaskResult(
                ok=False,
                status="creator_profile_unknown_ability",
                reply="【博主】能力字段只支持：查询、入库。商单交付请继续使用【商单交付】。",
                task_id="",
            )
        if dispatch:
            action, body = dispatch
            if action == "upsert":
                return TaskResult(
                    ok=False,
                    status="creator_profile_write_requires_upsert_capability",
                    reply="博主查询能力不执行写入。请使用【博主-入库】，主页链接可先解析为待确认候选。",
                    task_id="",
                )
            message = self._creator_profile_handoff_message(message, "博主", body)

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

    def _creator_profile_unified_dispatch(self, body: str) -> tuple[str, str] | str | None:
        text = str(body or "").replace("\r\n", "\n").strip()
        match = CREATOR_PROFILE_UNIFIED_ACTION_RE.search(text)
        if not match:
            return None
        action = self._normalize_creator_profile_action(match.group("value"))
        if not action:
            return "unknown"
        return action, self._strip_creator_profile_unified_fields(text)

    def _normalize_creator_profile_action(self, value: str) -> str:
        text = unicodedata.normalize("NFKC", str(value or "")).strip().lower()
        text = re.sub(r"\s+", "", text)
        return CREATOR_PROFILE_UNIFIED_ACTIONS.get(text, "")

    def _strip_creator_profile_unified_fields(self, body: str) -> str:
        lines: list[str] = []
        for line in str(body or "").replace("\r\n", "\n").splitlines():
            if CREATOR_PROFILE_ACTION_LINE_RE.match(line):
                continue
            info_match = CREATOR_PROFILE_INFO_LINE_RE.match(line)
            if info_match:
                value = info_match.group("value").strip()
                if value:
                    lines.append(value)
                continue
            lines.append(line)
        return "\n".join(lines).strip()

    def _creator_profile_handoff_message(self, message: Message, tag: str, body: str) -> Message:
        metadata = dict(message.metadata or {})
        metadata["unified_creator_profile_entry"] = "博主"
        metadata["handoff_tag"] = tag
        return replace(message, entry_tag=tag, raw_text=f"【{tag}】{body}", body=body, metadata=metadata)

    def handle_博主_入库(self, message: Message) -> TaskResult:
        batch_bodies = self._creator_profile_batch_bodies(message.body)
        if batch_bodies is not None:
            return self._handle_creator_profile_batch(message, batch_bodies)
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

        return self._handle_creator_profile_auto_enrichment(fields)

    def _creator_profile_batch_bodies(self, body: str) -> list[str] | None:
        text = str(body or "").replace("\r\n", "\n").strip()
        marker = CREATOR_PROFILE_BATCH_RE.match(text)
        if not marker:
            return None
        payload = text[marker.end() :].strip()
        if not payload:
            return []
        if payload.startswith("[") or payload.startswith("{"):
            try:
                decoded = json.loads(payload)
            except json.JSONDecodeError:
                decoded = None
            if decoded is not None:
                rows = decoded.get("records") if isinstance(decoded, dict) else decoded
                if not isinstance(rows, list):
                    return []
                bodies: list[str] = []
                for row in rows:
                    if not isinstance(row, dict):
                        bodies.append("")
                        continue
                    lines: list[str] = []
                    for key, value in row.items():
                        if isinstance(value, list):
                            value = "、".join(str(item) for item in value if str(item).strip())
                        lines.append(f"{key}：{value}")
                    bodies.append("\n".join(lines))
                return bodies[: CREATOR_PROFILE_BATCH_LIMIT + 1]
        return [
            item.strip()
            for item in re.split(r"\n\s*(?:---+\s*)?\n", payload)
            if item.strip()
        ][: CREATOR_PROFILE_BATCH_LIMIT + 1]

    def _handle_creator_profile_batch(self, message: Message, bodies: list[str]) -> TaskResult:
        if not bodies:
            return TaskResult(
                ok=False,
                status="creator_profile_batch_empty",
                reply="批量博主入库没有可处理的记录。请提交 JSON records 数组，或用空行/---分隔多条表单。",
                task_id="",
            )
        if len(bodies) > CREATOR_PROFILE_BATCH_LIMIT:
            return TaskResult(
                ok=False,
                status="creator_profile_batch_too_large",
                reply=f"单次批量博主入库最多 {CREATOR_PROFILE_BATCH_LIMIT} 条，本次未写入。",
                task_id="",
            )

        outcomes: list[dict[str, Any]] = []
        for index, body in enumerate(bodies, start=1):
            child = self.handle_博主_入库(self._creator_profile_handoff_message(message, "博主-入库", body))
            outcomes.append(
                {
                    "row": index,
                    "ok": bool(child.ok),
                    "status": child.status,
                    "task_id": child.task_id,
                    "reply": child.reply,
                }
            )

        succeeded = sum(1 for item in outcomes if item["ok"])
        failed = len(outcomes) - succeeded
        if succeeded == len(outcomes):
            status = "creator_profile_batch_candidates_ready"
            ok = True
        elif succeeded:
            status = "creator_profile_batch_candidates_partial"
            ok = True
        else:
            status = "creator_profile_batch_failed"
            ok = False
        lines = [f"批量博主入库完成：成功 {succeeded} 条，失败 {failed} 条。"]
        for item in outcomes:
            result_label = "成功" if item["ok"] else "失败"
            lines.append(f"{item['row']}. {result_label}；{item['status']}；{item['task_id'] or '无记录ID'}")
        return TaskResult(
            ok=ok,
            status=status,
            reply="\n".join(lines),
            task_id="",
            extra={"creator_profile_batch": {"total": len(outcomes), "succeeded": succeeded, "failed": failed, "outcomes": outcomes}},
        )

    def _creator_confirm_write_requested(self, body: str, fields: dict[str, Any]) -> bool:
        return "确认写入" in str(body or "") and bool(self._creator_run_id(body, fields))

    def _creator_auto_enrichment_requested(self, body: str, fields: dict[str, Any]) -> bool:
        mode = self._profile_text(fields.get("mode"))
        if mode == "自动补全":
            return True
        profile_url = self._profile_text(fields.get("主页链接"))
        missing_identity = not self._profile_text(fields.get("作者ID") or fields.get("平台ID")) or not self._profile_text(
            fields.get("账号名称") or fields.get("博主IP")
        )
        return bool(profile_url and missing_identity)

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
        profile_url = self._profile_text(fields.get("主页链接"))
        if not profile_url and (not platform or not platform_id):
            return TaskResult(
                ok=False,
                status="creator_profile_auto_missing_required",
                reply="博主档案解析未执行：请提供主页链接，或同时提供平台和平台ID。",
                task_id="",
            )
        try:
            candidate = self._generate_creator_profile_candidate_run(
                tenant_id=self._creator_profile_session_tenant_id(),
                platform=platform,
                platform_id=platform_id,
                id_type=self._profile_text(fields.get("input_platform_id_type")),
                url=profile_url,
                creator_name=self._profile_text(fields.get("账号名称") or fields.get("博主IP")),
                user_fields=self._creator_profile_v2_payload(fields),
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
            "avatar_url",
        ):
            if key in fields:
                edits[key] = self._profile_list(fields[key]) if key in CREATOR_PROFILE_LIST_FIELDS else self._profile_text(fields[key])
        return edits

    def _generate_creator_profile_candidate_run(self, **kwargs: Any) -> dict[str, Any]:
        return generate_candidate_run(**kwargs)

    @staticmethod
    def _creator_profile_session_tenant_id() -> str:
        return str(current_session_tenant_id())

    def _confirm_creator_profile_candidate_run(self, run_id: str, *, user_edits: dict[str, Any] | None = None) -> dict[str, Any]:
        return confirm_candidate_run(
            run_id,
            tenant_id=str(current_session_tenant_id()),
            user_edits=user_edits or {},
        )

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
        owner_service = getattr(self, "tenant_owned_resources", None)
        if owner_service is None:
            raise RuntimeError("canonical resource owner service is unavailable")
        tenant_id = str(current_session_tenant_id())
        table_url = url or self._creator_profile_table_url()
        access_token = token or feishu_tenant_access_token()
        owners = owner_service.registry.list_all_by_tenant(
            tenant_id,
            resource_type="media.creator_profile",
        )
        records: list[dict[str, Any]] = []
        for owner in owners:
            matched = feishu_list_records(
                table_url,
                token=access_token,
                page_size=2,
                filter_formula=(
                    f'CurrentValue.[达人档案ID] = "{owner.canonical_resource_id}"'
                ),
            )
            if len(matched) != 1:
                raise RuntimeError("canonical creator profile projection is missing or duplicated")
            record = matched[0]
            record_id = str(record.get("record_id") or "")
            owner_service.assert_projection_read(
                "media.creator_profile",
                owner.canonical_resource_id,
                session_tenant_id=tenant_id,
                fields=record.get("fields") or {},
                projection_source=f"feishu:creator_profiles/{record_id}",
            )
            records.append(record)
        return records

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
            "avatar_url",
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
                    f"   头像链接：{self._creator_field_text(fields, 'avatar_url') or '待补'}",
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
            "avatar_url": self._profile_text(fields.get("avatar_url") or fields.get("头像链接")),
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
