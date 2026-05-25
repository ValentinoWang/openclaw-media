from __future__ import annotations

from .tag_router_common import *


class DevelopmentMixin:
    def handle_开发(self, message: Message) -> TaskResult:
        request = self._parse_development_request(message.body)
        task_id = make_record_id(message.created_at, message.source, message.entry_tag)
        sections = [
            ("原始内容", message.raw_text),
            (
                "需求摘要",
                "\n".join(
                    [
                        f"- 标题：{request['title']}",
                        f"- 类型：{request['kind']}",
                        f"- 模块：{request['module']}",
                        f"- 优先级：{request['priority']}",
                        f"- 状态：{request['status']}",
                        f"- 截止时间：{request['due_at']}",
                    ]
                ),
            ),
            ("背景", request["background"]),
            ("验收标准", request["acceptance"]),
            ("下一步", request["next_step"]),
        ]
        entry = self.archive_service.save_archive(
            message,
            f"开发：{request['title']}",
            sections,
            {
                "request_type": request["kind"],
                "module": request["module"],
                "priority": request["priority"],
                "dev_status": request["status"],
                "due_at": request["due_at"],
            },
        )
        reply = "\n".join(
            [
                "开发需求已归档",
                f"标题：{request['title']}",
                f"类型：{request['kind']}",
                f"模块：{request['module']}",
                f"优先级：{request['priority']}",
                f"状态：{request['status']}",
                f"本地路径：{entry.local_path}",
                "说明：`【开发】` 只沉淀开发需求；需要到点提醒时另发 `【待办】` 或 `【日程】`。",
            ]
        )
        return TaskResult(
            ok=True,
            status="archived",
            reply=reply,
            task_id=entry.frontmatter["id"],
            local_path=entry.local_path,
            extra=request,
        )

    def _parse_development_request(self, body: str) -> dict[str, str]:
        text = (body or "").strip()
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        labeled = self._extract_labeled_development_fields(text)
        title = (
            labeled.get("标题")
            or labeled.get("需求")
            or labeled.get("任务")
            or self._first_development_title(lines)
            or "未命名开发需求"
        )
        kind = labeled.get("类型") or self._infer_development_kind(text)
        module = labeled.get("模块") or labeled.get("系统") or self._infer_development_module(text)
        priority = labeled.get("优先级") or self._infer_development_priority(text)
        status = labeled.get("状态") or "待排期"
        due_at = labeled.get("截止") or labeled.get("截止时间") or labeled.get("时间") or "未设置"
        background = labeled.get("背景") or labeled.get("原因") or self._development_body_without_labels(lines) or "未补充"
        acceptance = labeled.get("验收") or labeled.get("验收标准") or labeled.get("完成标准") or "待补充"
        next_step = labeled.get("下一步") or labeled.get("处理") or "拆分实现步骤并确认是否需要排期。"
        return {
            "title": self._clean_development_value(title, "未命名开发需求"),
            "kind": self._normalize_development_kind(kind),
            "module": self._clean_development_value(module, "未分类"),
            "priority": self._normalize_development_priority(priority),
            "status": self._clean_development_value(status, "待排期"),
            "due_at": self._clean_development_value(due_at, "未设置"),
            "background": self._clean_development_value(background, "未补充"),
            "acceptance": self._clean_development_value(acceptance, "待补充"),
            "next_step": self._clean_development_value(next_step, "拆分实现步骤并确认是否需要排期。"),
        }

    def _extract_labeled_development_fields(self, text: str) -> dict[str, str]:
        fields: dict[str, str] = {}
        labels = "标题|需求|任务|类型|模块|系统|优先级|状态|截止|截止时间|时间|背景|原因|验收|验收标准|完成标准|下一步|处理"
        pattern = re.compile(rf"^\s*({labels})\s*[:：=]\s*(.+?)\s*$")
        for line in text.splitlines():
            match = pattern.match(line)
            if match:
                fields[match.group(1)] = match.group(2).strip()
        return fields

    def _first_development_title(self, lines: list[str]) -> str:
        if not lines:
            return ""
        first = re.sub(r"^\s*【开发】\s*", "", lines[0]).strip()
        if re.match(r"^(标题|需求|任务)\s*[:：=]", first):
            return re.sub(r"^(标题|需求|任务)\s*[:：=]\s*", "", first).strip()
        return first[:80]

    def _development_body_without_labels(self, lines: list[str]) -> str:
        kept = []
        for line in lines[1:] if lines else []:
            if re.match(r"^\s*(标题|需求|任务|类型|模块|系统|优先级|状态|截止|截止时间|时间|背景|原因|验收|验收标准|完成标准|下一步|处理)\s*[:：=]", line):
                continue
            kept.append(line)
        return "\n".join(kept).strip()

    def _infer_development_kind(self, text: str) -> str:
        lower = text.lower()
        if any(word in lower for word in ("bug", "报错", "失败", "修复", "崩", "timeout", "traceback")):
            return "bug"
        if any(word in lower for word in ("自动化", "同步", "脚本", "runner", "bot")):
            return "automation"
        if any(word in lower for word in ("重构", "refactor")):
            return "refactor"
        if any(word in lower for word in ("功能", "新增", "支持", "接入")):
            return "feature"
        return "task"

    def _infer_development_module(self, text: str) -> str:
        lower = text.lower()
        module_keywords = (
            ("knowledge", "Knowledge bot"),
            ("media", "Media bot"),
            ("social", "Social bot"),
            ("daily", "Daily bot"),
            ("tag-router", "tag-router"),
            ("飞书", "飞书"),
            ("多维表格", "飞书多维表格"),
            ("syncthing", "Syncthing"),
            ("obsidian", "Obsidian"),
            ("openhuman", "OpenHuman"),
            ("openclaw", "OpenClaw"),
        )
        for keyword, module in module_keywords:
            if keyword in lower:
                return module
        return "未分类"

    def _infer_development_priority(self, text: str) -> str:
        if re.search(r"(p0|紧急|立即|阻塞|严重|高优)", text, re.IGNORECASE):
            return "高"
        if re.search(r"(p2|低优|以后|不急)", text, re.IGNORECASE):
            return "低"
        return "中"

    def _normalize_development_kind(self, value: str) -> str:
        text = str(value or "").strip().lower()
        mapping = {
            "缺陷": "bug",
            "问题": "bug",
            "修复": "bug",
            "功能": "feature",
            "新增": "feature",
            "运维": "ops",
            "自动化": "automation",
            "重构": "refactor",
        }
        return mapping.get(text, text or "task")

    def _normalize_development_priority(self, value: str) -> str:
        text = str(value or "").strip()
        if re.search(r"(p0|p1|高|紧急|阻塞|严重)", text, re.IGNORECASE):
            return "高"
        if re.search(r"(p2|p3|低|不急|以后)", text, re.IGNORECASE):
            return "低"
        return text or "中"

    def _clean_development_value(self, value: str, fallback: str) -> str:
        text = str(value or "").strip()
        return text if text else fallback
