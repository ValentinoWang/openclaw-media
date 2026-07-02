from __future__ import annotations

from .tag_router_common import *


class DevelopmentMixin:
    def handle_待办_开发(self, message: Message) -> TaskResult:
        request = self._parse_development_request(message.body, message.created_at)
        sections = [
            ("原始内容", message.raw_text),
            (
                "需求摘要",
                "\n".join(
                    [
                        f"- 标题：{request['title']}",
                        f"- 机器：{request['machine']}",
                        f"- 地址：{request['address']}",
                        f"- 类型：{request['kind']}",
                        f"- 模块：{request['module']}",
                        f"- 优先级：{request['priority']}",
                        f"- 状态：{request['status']}",
                        f"- 截止时间：{request['due_at']}",
                        f"- 飞书写入时间：{request['feishu_written_at']}",
                    ]
                ),
            ),
            ("背景", request["background"]),
            ("验收标准", request["acceptance"]),
            ("补充", request["supplement"]),
            ("下一步", request["next_step"]),
        ]
        entry = self.archive_service.save_archive(
            message,
            f"待办-开发：{request['title']}",
            sections,
            {
                "request_type": request["kind"],
                "module": request["module"],
                "priority": request["priority"],
                "dev_status": request["status"],
                "due_at": request["due_at"],
                "machine": request["machine"],
                "address": request["address"],
                "feishu_written_at": request["feishu_written_at"],
                "acceptance": request["acceptance"],
                "supplement": request["supplement"],
                "checklist_status": "pending",
                "creation_source": "feishu_bot/openclaw",
            },
        )
        base_result = self._write_development_base_record(message, request, entry)
        base_data = base_result.get("data") or {}
        base_record_id = str(base_data.get("record_id") or "").strip()
        table_url = str(base_data.get("table_url") or self._configured_bitable_url("待办-开发") or "").strip()
        checklist_result: Any = None
        checklist_error = ""
        try:
            checklist_result = self.obsidian_daily_checklist_service.append_checklist(
                text=message.body,
                now=message.created_at,
                checklist_tree=[
                    {
                        "text": self._development_checklist_text(request),
                        "children": [],
                    }
                ],
                feishu_record=base_record_id,
            )
        except Exception as exc:
            checklist_error = str(exc)

        archive_updates: dict[str, Any] = {
            "feishu_synced": bool(base_result.get("ok")),
            "feishu_base_record_id": base_record_id,
            "feishu_base_table_url": table_url,
            "obsidian_path": getattr(checklist_result, "path", ""),
        }
        if not base_result.get("ok"):
            archive_updates["feishu_base_error"] = base_result.get("error") or base_result.get("reason") or "unknown"
        if checklist_error:
            archive_updates["obsidian_error"] = checklist_error
        updated_entry = self.archive_service.update_frontmatter(entry.local_path, archive_updates)

        ok = bool(base_result.get("ok")) and bool(checklist_result)
        status = "archived" if ok else "partial_failed"
        reply = "\n".join(
            item
            for item in [
                "正式开发任务已登记",
                f"任务：{request['title']}",
                f"机器：{request['machine']}",
                f"地址：{request['address']}",
                f"飞书写入时间：{request['feishu_written_at']}",
                f"飞书多维表格：{table_url or ('写入失败' if not base_result.get('ok') else '已写入')}",
                f"飞书记录ID：{base_record_id}" if base_record_id else "",
                f"Obsidian checklist：{getattr(checklist_result, 'path', '') or '写入失败'}",
                f"本地路径：{updated_entry.local_path}",
                f"Base错误：{base_result.get('error') or base_result.get('reason')}" if not base_result.get("ok") else "",
                f"Obsidian错误：{checklist_error}" if checklist_error else "",
                "说明：`【待办-开发】` 是正式开发任务入口；checklist 勾选后由 Mac 侧 Codex high 做追溯与回档梳理。",
            ]
            if item
        )
        return TaskResult(
            ok=ok,
            status=status,
            reply=reply,
            task_id=base_record_id or updated_entry.frontmatter["id"],
            local_path=updated_entry.local_path,
            extra={
                **request,
                "base_result": base_result,
                "obsidian_path": getattr(checklist_result, "path", ""),
            },
        )

    def _write_development_base_record(self, message: Message, request: dict[str, str], entry: Any) -> dict[str, Any]:
        environment_kind = self._development_environment_kind(request["address"])
        extra_fields = {
            "机器": request["machine"],
            "地址": request["address"],
            "验收": request["acceptance"],
            "补充": request["supplement"],
            "飞书写入时间": request["feishu_written_at"],
            "checklist状态": "pending",
            "environment_kind": environment_kind,
            "match_status": "",
            "详细任务文档路径": "",
            "一句话总结": "",
            "回档状态": "",
            "更新时间": self._format_development_created_at(message.created_at),
            "创建来源": "feishu_bot/openclaw",
            "类型说明": "正式开发任务",
            "未填写原因": "截止/提醒时间使用飞书写入时间占位；真实完成与回档由 checklist 勾选后更新。",
        }
        return self.reminder_service.add(
            kind="待办-开发",
            title=request["title"],
            text=message.body,
            due_at=message.created_at,
            remind_at=message.created_at,
            source=message.source,
            ref_id=entry.frontmatter["id"],
            local_path=entry.local_path,
            extra_fields=extra_fields,
        )

    @staticmethod
    def _development_checklist_text(request: dict[str, str]) -> str:
        return f"【待办-开发】{request['title']}｜机器：{request['machine']}｜地址：{request['address']}"

    @staticmethod
    def _development_environment_kind(address: str) -> str:
        text = str(address or "").strip().lower()
        if text in {"localhost", "local", "本机", "mac"} or "localhost" in text:
            return "mac_local"
        if "@" in text or text.startswith("ssh"):
            return "cloud_server"
        return "unknown"

    def _parse_development_request(self, body: str, created_at: datetime | None = None) -> dict[str, str]:
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
        machine = labeled.get("机器") or labeled.get("machine") or labeled.get("machine_id") or "未填写"
        address = labeled.get("地址") or labeled.get("address") or "未填写"
        feishu_written_at = labeled.get("飞书写入时间") or self._format_development_created_at(created_at)
        kind = labeled.get("类型") or self._infer_development_kind(text)
        module = labeled.get("模块") or labeled.get("系统") or self._infer_development_module(text)
        priority = labeled.get("优先级") or self._infer_development_priority(text)
        status = labeled.get("状态") or "待排期"
        due_at = labeled.get("截止") or labeled.get("截止时间") or labeled.get("时间") or "未设置"
        background = labeled.get("背景") or labeled.get("原因") or self._development_body_without_labels(lines) or "未补充"
        acceptance = labeled.get("验收") or labeled.get("验收标准") or labeled.get("完成标准") or "待补充"
        supplement = labeled.get("补充") or "未补充"
        next_step = labeled.get("下一步") or labeled.get("处理") or "拆分实现步骤并确认是否需要排期。"
        return {
            "title": self._clean_development_value(title, "未命名开发需求"),
            "machine": self._clean_development_value(machine, "未填写"),
            "address": self._clean_development_value(address, "未填写"),
            "feishu_written_at": self._clean_development_value(feishu_written_at, "未写入"),
            "kind": self._normalize_development_kind(kind),
            "module": self._clean_development_value(module, "未分类"),
            "priority": self._normalize_development_priority(priority),
            "status": self._clean_development_value(status, "待排期"),
            "due_at": self._clean_development_value(due_at, "未设置"),
            "background": self._clean_development_value(background, "未补充"),
            "acceptance": self._clean_development_value(acceptance, "待补充"),
            "supplement": self._clean_development_value(supplement, "未补充"),
            "next_step": self._clean_development_value(next_step, "拆分实现步骤并确认是否需要排期。"),
        }

    def _extract_labeled_development_fields(self, text: str) -> dict[str, str]:
        fields: dict[str, str] = {}
        labels = "标题|需求|任务|机器|machine|machine_id|地址|address|飞书写入时间|类型|模块|系统|优先级|状态|截止|截止时间|时间|背景|原因|验收|验收标准|完成标准|下一步|处理|补充"
        pattern = re.compile(rf"^\s*({labels})\s*[:：=]\s*(.+?)\s*$")
        for line in text.splitlines():
            match = pattern.match(line)
            if match:
                fields[match.group(1)] = match.group(2).strip()
        return fields

    def _first_development_title(self, lines: list[str]) -> str:
        if not lines:
            return ""
        first = re.sub(r"^\s*【待办-开发】\s*", "", lines[0]).strip()
        if re.match(r"^(标题|需求|任务)\s*[:：=]", first):
            return re.sub(r"^(标题|需求|任务)\s*[:：=]\s*", "", first).strip()
        return first[:80]

    def _development_body_without_labels(self, lines: list[str]) -> str:
        kept = []
        for line in lines[1:] if lines else []:
            if re.match(r"^\s*(标题|需求|任务|机器|machine|machine_id|地址|address|飞书写入时间|类型|模块|系统|优先级|状态|截止|截止时间|时间|背景|原因|验收|验收标准|完成标准|下一步|处理|补充)\s*[:：=]", line):
                continue
            kept.append(line)
        return "\n".join(kept).strip()

    def _format_development_created_at(self, created_at: datetime | None = None) -> str:
        value = created_at or now_in_tz(self.timezone)
        return value.strftime("%Y-%m-%d %H:%M:%S %Z")

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

    def _clean_development_value(self, value: str, default_value: str) -> str:
        text = str(value or "").strip()
        return text if text else default_value
