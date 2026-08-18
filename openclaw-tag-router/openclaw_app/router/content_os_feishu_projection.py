"""Read-only Content OS project-board projection for Feishu collaborators.

The adapter is intentionally transport-agnostic.  It receives an injected
client only after the live Base schema has been read and authorised.  No method
in this module reads or writes project overviews, registries, task queues, or
Feishu field definitions.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any, Protocol

import yaml

from .content_os_project_lifecycle import CONTENT_OS_SPEC_VERSION, ContentOSContractError, ProjectState
from .content_os_projections import build_feishu_project_projection


PROJECT_BOARD_FIELD_CONTRACT = {
    "spec_version": CONTENT_OS_SPEC_VERSION,
    "table": "00_Projects_项目看板",
    "source_of_truth": "08_内容项目/{project_id}/00_项目总览.md frontmatter",
    "writer": "content_os_feishu_projection.FeishuProjectBoardProjectionAdapter",
    "activation_precondition": "读取真实字段与视图并取得项目看板写入权限后，才能注入真实 client。",
    "fields": (
        "项目名称",
        "项目阶段",
        "当前版本",
        "剪辑方式",
        "负责人",
        "下一步",
        "是否阻塞",
        "阻塞原因",
        "项目说明摘要",
        "脚本摘要",
        "镜头安排与剪辑说明摘要",
        "交接完成情况",
        "成片链接",
        "质检链接",
        "发布链接",
        "复盘链接",
        "提交修改",
    ),
}

_SUMMARY_SPECS = (
    ("02_project_brief.md", "项目说明摘要"),
    ("04_script.md", "脚本摘要"),
    ("05_storyboard.md", "镜头安排与剪辑说明摘要"),
)
_FORBIDDEN_VISIBLE_PATTERN = re.compile(
    r"(?:/Users/|/home/|08_内容项目/|90_Draft_Project/|98_Agent|task_\d|change_\d|"
    r"\b(?:project_id|project_revision|editor_backend|handoff_pack|otio_kdenlive)\b|"
    r"Traceback|Exception:|Error:)",
    flags=re.I,
)


class FeishuProjectBoardClient(Protocol):
    """The only transport surface needed once a live schema owner is approved."""

    def upsert_content_os_project(self, project_key: str, fields: dict[str, str]) -> None: ...


@dataclass(frozen=True)
class FeishuProjectBoardProjection:
    """An internal record key plus exclusively collaborator-visible Chinese fields."""

    project_key: str
    fields: dict[str, str]


class FeishuProjectBoardProjectionAdapter:
    def __init__(self, client: FeishuProjectBoardClient):
        self._client = client

    def build(self, state: ProjectState) -> FeishuProjectBoardProjection:
        if not isinstance(state, ProjectState):
            raise ContentOSContractError("飞书项目看板只接受 Content OS v0.2 项目总览投影")
        if state.frontmatter.get("spec_version") != CONTENT_OS_SPEC_VERSION:
            raise ContentOSContractError("飞书项目看板只接受 Content OS v0.2 项目总览投影")
        fields = {key: self._visible_text(value) for key, value in build_feishu_project_projection(state).items()}
        for filename, field_name in _SUMMARY_SPECS:
            if fields.get(field_name) in {"", "未记录"}:
                fields[field_name] = self._evidence_summary(state.overview_path.parent / filename)
        fields["阻塞原因"] = self._visible_text(state.blocked_reason) if state.blocked else ""
        fields["交接完成情况"] = self._visible_text(fields.get("交接完成情况") or "未记录")
        for field_name in ("成片链接", "质检链接", "发布链接", "复盘链接"):
            fields[field_name] = self._safe_link(fields.get(field_name) or "")
        fields["提交修改"] = "请在 Media Bot 发送【修改】修改项目；机器人会给出项目选择和填写单。本看板不直接修改项目。"
        if tuple(fields) != PROJECT_BOARD_FIELD_CONTRACT["fields"]:
            raise ContentOSContractError("飞书项目看板字段与 owner 契约不一致")
        return FeishuProjectBoardProjection(project_key=state.project_id, fields=fields)

    def sync(self, state: ProjectState) -> dict[str, str | bool]:
        """Write a projection only through an approved injected client.

        The method never exposes a project key, filesystem path, exception text,
        or internal Content OS variable in the collaborator-facing reply.
        """

        projection = self.build(state)
        try:
            self._client.upsert_content_os_project(projection.project_key, dict(projection.fields))
        except Exception as exc:
            if isinstance(exc, PermissionError) or re.search(r"\b403\b|\b91403\b|permission", str(exc), flags=re.I):
                return {
                    "ok": False,
                    "status": "feishu_project_board_permission_required",
                    "reply": "飞书项目看板尚未获得必要授权，暂时不能更新；项目本身没有被改动。",
                }
            return {
                "ok": False,
                "status": "feishu_project_board_sync_pending",
                "reply": "飞书项目看板暂时无法更新；项目本身没有被改动，请稍后重试或联系负责人。",
            }
        return {
            "ok": True,
            "status": "feishu_project_board_projected",
            "reply": "飞书项目看板已更新为当前项目情况。",
        }

    @staticmethod
    def _safe_link(value: str) -> str:
        link = str(value or "").strip()
        return link if re.fullmatch(r"https?://[^\s]+", link) else ""

    @staticmethod
    def _visible_text(value: Any) -> str:
        text = str(value or "").replace("\r", " ").replace("\n", " ").strip()
        if not text or _FORBIDDEN_VISIBLE_PATTERN.search(text):
            return "未记录"
        return re.sub(r"\s+", " ", text)[:280]

    def _evidence_summary(self, path: Path) -> str:
        if not path.exists():
            return "未记录"
        text = path.read_text(encoding="utf-8", errors="replace")
        match = re.match(r"\A---\n(?P<frontmatter>.*?)\n---\n?(?P<body>.*)\Z", text, flags=re.S)
        if not match:
            return "未记录"
        try:
            frontmatter = yaml.safe_load(match.group("frontmatter")) or {}
        except yaml.YAMLError:
            return "未记录"
        if not isinstance(frontmatter, dict) or frontmatter.get("spec_version") != CONTENT_OS_SPEC_VERSION:
            return "未记录"
        body = re.sub(r"```.*?```", " ", match.group("body"), flags=re.S)
        body = re.sub(r"^#{1,6}\s*", "", body, flags=re.M)
        body = re.sub(r"\|", " ", body)
        return self._visible_text(body)
