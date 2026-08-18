"""Read-only Content OS v0.2 projections.

The functions here may overwrite generated projection files, but never the
project overview.  They derive every project-stage field from the overview so
the registry and collaboration board cannot become a second state source.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .content_os_project_lifecycle import ProjectState, read_project_state


def _markdown_cell(value: Any) -> str:
    return str(value or "").replace("|", "/").replace("\n", " ").strip()


def iter_project_states(vault_root: Path) -> list[ProjectState]:
    projects_root = Path(vault_root) / "08_内容项目"
    if not projects_root.exists():
        return []
    states: list[ProjectState] = []
    for directory in sorted(projects_root.iterdir(), key=lambda item: item.name):
        if directory.is_dir() and (directory / "00_项目总览.md").exists():
            states.append(read_project_state(vault_root, directory.name))
    return states


def _project_title(state: ProjectState) -> str:
    return str(
        state.frontmatter.get("title")
        or state.frontmatter.get("theme")
        or state.frontmatter.get("project_name")
        or state.project_id
    ).strip()


def _next_action(state: ProjectState) -> str:
    value = str(state.frontmatter.get("next_action") or "").strip()
    if value:
        return value
    if state.blocked:
        return "先解决阻塞事项"
    defaults = {
        "captured": "补全选题与项目说明",
        "planned": "完成剪辑交接材料",
        "edit_ready": "人工确认开始剪辑",
        "editing": "完成人工精剪并提交成片质检",
        "final_ready": "人工发布并回填链接",
        "published": "补充复盘结论",
    }
    return defaults[state.status]


def _collaborator_owner(value: Any) -> str:
    """Translate system role values while preserving a human's displayed name."""

    raw = str(value or "").strip()
    return {
        "human": "人工负责人",
        "cloud_openclaw": "云端协作",
        "mac_openclaw": "Mac 协作",
    }.get(raw, raw or "未指定")


def build_project_registry_markdown(vault_root: Path) -> str:
    """Render the complete, generated-only Markdown project registry."""

    rows = [
        "# Project Registry（自动投影）",
        "",
        "<!-- content_os_projection:project_registry:v0.2 -->",
        "",
        "请勿直接编辑本页的项目阶段、版本或剪辑方式；它们只从各项目的 `00_项目总览.md` 生成。",
        "",
        "| project_id | 标题/主题 | 项目阶段 | 版本 | 剪辑方式 | 负责人 | 下一步 | 阻塞原因 |",
        "| --- | --- | --- | ---: | --- | --- | --- | --- |",
    ]
    for state in iter_project_states(vault_root):
        owner = _markdown_cell(state.frontmatter.get("owner") or state.frontmatter.get("owner_agent") or "未指定")
        rows.append(
            "| "
            + " | ".join(
                [
                    state.project_id,
                    _markdown_cell(_project_title(state)),
                    state.status,
                    str(state.project_revision),
                    state.editor_backend,
                    owner,
                    _markdown_cell(_next_action(state)),
                    _markdown_cell(state.blocked_reason if state.blocked else ""),
                ]
            )
            + " |"
        )
    return "\n".join(rows).rstrip() + "\n"


def write_project_registry_projection(vault_root: Path) -> Path:
    """Write the registry projection. This function is the registry's only writer."""

    path = Path(vault_root) / "90_索引与注册表" / "project_registry.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_project_registry_markdown(vault_root), encoding="utf-8")
    return path


def build_feishu_project_projection(state: ProjectState) -> dict[str, str | int | bool]:
    """Return the operator-facing fields for a Feishu project row.

    This is deliberately data only: the Feishu adapter owns transport and
    record-id mapping, while this module stays a pure derived projection.
    """

    frontmatter = state.frontmatter
    stage_labels = {
        "captured": "已登记",
        "planned": "已规划",
        "edit_ready": "可开始剪辑",
        "editing": "剪辑中",
        "final_ready": "待发布",
        "published": "已发布",
    }
    backend_labels = {
        "handoff_pack": "标准剪辑",
        "otio_kdenlive": "自动生成可编辑时间线",
    }
    return {
        "项目名称": _project_title(state),
        "项目阶段": stage_labels[state.status],
        "当前版本": f"第 {state.project_revision} 版",
        "剪辑方式": backend_labels[state.editor_backend],
        "负责人": _collaborator_owner(frontmatter.get("owner") or frontmatter.get("owner_agent")),
        "下一步": _next_action(state),
        "是否阻塞": "是" if state.blocked else "否",
        "阻塞原因": state.blocked_reason if state.blocked else "",
        "项目说明摘要": str(frontmatter.get("brief_summary") or "未记录").strip(),
        "脚本摘要": str(frontmatter.get("script_summary") or "").strip(),
        "镜头安排与剪辑说明摘要": str(frontmatter.get("edit_summary") or "未记录").strip(),
        "交接完成情况": str(frontmatter.get("edit_handoff_status") or "未记录").strip(),
        "成片链接": str(frontmatter.get("final_url") or "").strip(),
        "质检链接": str(frontmatter.get("output_review_url") or "").strip(),
        "发布链接": str(frontmatter.get("post_url") or "").strip(),
        "复盘链接": str(frontmatter.get("review_url") or "").strip(),
        "提交修改": "请在 Media Bot 对话中发送“修改项目”，按提示填写修改内容；本看板不直接修改项目。",
    }


def build_feishu_project_projections(vault_root: Path) -> list[dict[str, str | int | bool]]:
    """Return a complete Feishu board projection without writing to Feishu."""

    return [build_feishu_project_projection(state) for state in iter_project_states(vault_root)]
