from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


AUTO_DELETE_KINDS = {
    "inbox_json",
    "archive_markdown",
    "local_file",
    "local_dir",
    "obsidian_note",
    "obsidian_transcript",
    "content_flow_artifact",
    "media_vault_artifact",
    "mac_queue_task",
}

STATUS_ORDER = [
    ("planned", "将删除"),
    ("deleted", "已删除"),
    ("already_absent", "已不存在"),
    ("skipped", "跳过"),
    ("manual_required", "需人工处理"),
    ("blocked", "已阻断"),
    ("failed", "失败"),
]

KIND_LABELS = {
    "inbox_json": "inbox",
    "archive_markdown": "本地归档",
    "local_file": "本地文件",
    "local_dir": "本地目录",
    "obsidian_note": "Obsidian会议纪要",
    "obsidian_transcript": "Obsidian原字稿",
    "obsidian_block": "Obsidian块",
    "content_flow_artifact": "中间产物",
    "media_vault_artifact": "media_vault产物",
    "mac_queue_task": "Mac队列任务",
    "feishu_doc": "飞书文档",
    "bitable_record": "多维表格记录",
    "calendar_event": "日历事件",
    "reminder_record": "提醒记录",
    "external_reference": "外部引用",
    "creation_run_script": "创作运行清理脚本",
}


@dataclass
class DeletionEntity:
    kind: str
    target: str
    operation: str = "unlink"
    risk: str = "normal"
    status: str = "planned"
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "target": self.target,
            "operation": self.operation,
            "risk": self.risk,
            "status": self.status,
            "detail": self.detail,
        }


@dataclass
class DeletionPlan:
    target_id: str
    capability_id: str
    capability_label: str
    matched_by: list[str] = field(default_factory=list)
    entities: list[DeletionEntity] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    blocked: bool = False
    mode: str = "dry_run"

    def add_entity(self, entity: DeletionEntity) -> None:
        existing = {(item.kind, item.target) for item in self.entities}
        if (entity.kind, entity.target) not in existing:
            self.entities.append(entity)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "target_id": self.target_id,
            "capability_id": self.capability_id,
            "capability_label": self.capability_label,
            "matched_by": self.matched_by,
            "entities": [entity.to_dict() for entity in self.entities],
            "warnings": self.warnings,
            "blocked": self.blocked,
        }


def is_path_under(path: Path, roots: list[Path]) -> bool:
    try:
        resolved = path.expanduser().resolve(strict=False)
    except OSError:
        return False
    for root in roots:
        try:
            resolved.relative_to(root.expanduser().resolve(strict=False))
            return True
        except (OSError, ValueError):
            continue
    return False


def execute_local_plan(plan: DeletionPlan, allowed_roots: list[Path]) -> DeletionPlan:
    plan.mode = "apply"
    ordered = sorted(plan.entities, key=lambda entity: 0 if entity.kind == "local_dir" else 1)
    results: list[DeletionEntity] = []
    for entity in ordered:
        if entity.status == "manual_required" or entity.kind not in AUTO_DELETE_KINDS:
            results.append(
                DeletionEntity(
                    entity.kind,
                    entity.target,
                    entity.operation,
                    entity.risk,
                    entity.status if entity.status != "planned" else "manual_required",
                    entity.detail or "该对象未声明为可自动删除",
                )
            )
            continue
        path = Path(entity.target)
        if not is_path_under(path, allowed_roots):
            results.append(
                DeletionEntity(
                    entity.kind,
                    entity.target,
                    entity.operation,
                    entity.risk,
                    "failed",
                    "path is outside allowed deletion roots",
                )
            )
            continue
        try:
            if not path.exists():
                status = "already_absent"
            elif path.is_dir():
                shutil.rmtree(path)
                status = "deleted"
            else:
                path.unlink()
                status = "deleted"
            results.append(DeletionEntity(entity.kind, entity.target, entity.operation, entity.risk, status, entity.detail))
        except OSError as exc:
            results.append(DeletionEntity(entity.kind, entity.target, entity.operation, entity.risk, "failed", str(exc)))
    plan.entities = results
    plan.blocked = any(entity.status == "failed" for entity in results)
    return plan


def render_deletion_reply(plans: list[DeletionPlan], *, apply: bool) -> str:
    lines = ["删除执行结果：" if apply else "删除预览："]
    for plan in plans:
        lines.append(f"- 能力：{plan.capability_label}")
        lines.append(f"- 目标ID：{plan.target_id}")
        if plan.matched_by:
            lines.append(f"- 匹配依据：{', '.join(plan.matched_by)}")
        grouped: dict[str, list[DeletionEntity]] = {}
        for entity in plan.entities:
            grouped.setdefault(entity.status, []).append(entity)
        if not plan.entities:
            lines.append("- 没找到可删除项。")
        for status, title in STATUS_ORDER:
            items = grouped.get(status) or []
            if not items:
                continue
            lines.append("")
            lines.append(f"{title}：")
            for entity in items:
                label = KIND_LABELS.get(entity.kind, entity.kind)
                target = entity.target if len(entity.target) <= 180 else entity.target[:177] + "..."
                line = f"- {label}：`{target}`"
                if entity.detail:
                    line += f"（{entity.detail[:220]}）"
                lines.append(line)
        if plan.warnings:
            lines.append("")
            lines.append("提醒：")
            for warning in plan.warnings:
                lines.append(f"- {warning}")
        lines.append("")
    if not apply:
        joined = " ".join(plan.target_id for plan in plans)
        lines.append(f"当前只是预览；确认执行请发送：`【删除】确认删除 {joined}`")
    return "\n".join(lines).strip()
