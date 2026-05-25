from __future__ import annotations

from .tag_router_common import *


class SelfmediaCognitionMixin:
    def handle_selfmedia_cognition(self, message: Message) -> TaskResult:
        body = message.body.strip()
        if not body:
            return TaskResult(ok=False, status="empty_selfmedia_cognition", reply="请在 `【自媒体-认知】` 后写入要沉淀或纠正的自媒体认知。", task_id="")
        if not hasattr(self.feishu_service, "list_knowledge_child_nodes") or not hasattr(self.feishu_service, "replace_child_entry_under_node"):
            return TaskResult(ok=False, status="unsupported_feishu_service", reply="当前飞书服务不支持按知识库父节点分流/覆盖子文档。", task_id="")

        parent_node_token = SELFMEDIA_COGNITION_PARENT_NODE_TOKEN
        try:
            child_nodes = self.feishu_service.list_knowledge_child_nodes(parent_node_token)
        except Exception as exc:
            return TaskResult(ok=False, status="selfmedia_cognition_list_failed", reply=f"读取自媒体认知池子文档失败：{exc}", task_id="")

        plan = self._selfmedia_cognition_plan(message, child_nodes)
        if plan.get("status") == "pending_manual":
            return TaskResult(ok=False, status="selfmedia_cognition_pending_manual", reply=f"自媒体认知分流失败：{plan.get('reason') or 'OpenClaw 未返回可用分流结果'}", task_id="")

        doc_title = self._selfmedia_cognition_doc_title(plan)
        existing = self._find_child_node_by_title(child_nodes, doc_title)
        existing_text = ""
        existing_url = str(existing.get("doc_url") or "") if existing else ""
        if existing_url and hasattr(self.feishu_service, "read_document_text"):
            source = self.feishu_service.read_document_text(existing_url)
            existing_text = str(source.get("text") or "").strip() if source.get("ok") else ""

        merged = self._selfmedia_cognition_merge_content(
            doc_title=doc_title,
            message=message,
            plan=plan,
            existing_text=existing_text,
        )
        content = self._normalize_depatch_content(str(merged.get("content") or ""))
        if len(content) < 80:
            return TaskResult(ok=False, status="selfmedia_cognition_empty", reply="自媒体认知整合失败：OpenClaw 返回正文过短，已停止写入。", task_id="")

        try:
            fs = self.feishu_service.replace_child_entry_under_node(parent_node_token, doc_title, content)
        except Exception as exc:
            return TaskResult(ok=False, status="selfmedia_cognition_write_failed", reply=f"写入自媒体认知子文档失败：{exc}", task_id="")

        sections = [
            ("原始内容", body),
            ("分流标题", doc_title),
            ("赛道", str(plan.get("track") or "")),
            ("主旨", str(plan.get("theme") or plan.get("main_point") or "")),
            ("操作", "更新已有子文档" if existing else "新建子文档"),
            ("摘要", str(plan.get("summary") or "")),
        ]
        entry = self.archive_service.save_archive(
            message,
            f"自媒体认知：{self._selfmedia_cognition_title_segment(str(plan.get('theme') or plan.get('main_point') or body), limit=24) or '认知积累'}",
            sections,
            {
                "workflow": "selfmedia_cognition_accumulation",
                "feishu_doc_title": doc_title,
                "feishu_parent_node_token": parent_node_token,
                "operation": "update" if existing else "create",
            },
        )
        self.archive_service.update_frontmatter(entry.local_path, {"feishu_synced": True, "feishu_doc": fs.get("doc", ""), "feishu_doc_title": doc_title})
        reply = "\n".join(
            [
                "已沉淀自媒体认知。",
                f"子文档：{doc_title}",
                f"操作：{'更新已有子文档' if existing else '新建子文档'}",
                f"飞书文档：{fs.get('doc', '')}",
            ]
        )
        return TaskResult(
            ok=True,
            status="selfmedia_cognition_saved",
            reply=reply,
            task_id=entry.frontmatter["id"],
            local_path=entry.local_path,
            feishu_doc=fs.get("doc", ""),
            extra={"workflow": "selfmedia_cognition_accumulation", "doc_title": doc_title, "operation": "update" if existing else "create"},
        )

    def _selfmedia_cognition_plan(self, message: Message, child_nodes: list[dict[str, str]]) -> dict[str, Any]:
        if not hasattr(self.content_flow_client, "_call_postprocess_json"):
            return {"status": "pending_manual", "reason": "content_flow_client 缺少 OpenClaw JSON 调用"}
        candidates = [{"title": item.get("title", ""), "url": item.get("doc_url", "")} for item in child_nodes[:80]]
        prompt = (
            "你是 Media bot 的自媒体认知分流器。只输出合法 JSON，不要 Markdown 代码块，不要解释。\n"
            "任务：根据用户输入，把自媒体方法论、平台机制、账号运营、选题判断、商业化、复盘结论等认知，分流到认知池子文档。\n"
            "标题规则必须是：自媒体认知｜{赛道}｜{主旨}。\n"
            "要求：\n"
            "1. 赛道应是内容赛道、账号方向或认知类别，2-10 个汉字，例如：小红书、抖音、职场成长、校园成长、平台机制、选题判断、账号定位、商业化、复盘方法。没有明确赛道时用“通用”。\n"
            "2. 主旨用 8-20 个汉字概括认知，不要包含“自媒体认知/文档/记录/积累”等泛词。\n"
            "3. 如果现有子文档标题与本条认知属于同一主旨，target_title 必须直接使用现有标题；否则给出新标题。\n"
            "4. 判断这条内容是在纠正原有认知、补充原则、记录假设，还是沉淀案例。\n"
            "输出字段固定为：status, track, theme, target_title, summary, cognition_type, is_correction, is_hypothesis, key_points, data_gaps。"
        )
        user_content = json.dumps(
            {
                "raw_text": message.body,
                "created_at": format_display_time(message.created_at),
                "recent_conversation_context": self._conversation_context_prompt(message),
                "existing_child_docs": candidates,
            },
            ensure_ascii=False,
        )
        try:
            env = self.content_flow_client._content_flow_env()
            result = self.content_flow_client._call_postprocess_json(prompt, user_content, env, "自媒体认知分流")
        except Exception as exc:
            return {"status": "pending_manual", "reason": str(exc)}
        return result if isinstance(result, dict) else {"status": "pending_manual", "reason": "OpenClaw 返回非 JSON object"}

    def _selfmedia_cognition_merge_content(self, *, doc_title: str, message: Message, plan: dict[str, Any], existing_text: str) -> dict[str, Any]:
        if not hasattr(self.content_flow_client, "_call_postprocess_json"):
            return {"status": "pending_manual", "reason": "content_flow_client 缺少 OpenClaw JSON 调用"}
        prompt = (
            "你是自媒体认知库编辑器。只输出合法 JSON，不要 Markdown 代码块，不要解释。\n"
            "任务：把新输入整合成一个可持续维护的认知文档。如果已有文档，必须将新内容合并进对应章节并覆盖成完整正文，不要保留“补充记录/v1/v2/追加”痕迹。\n"
            "要求：\n"
            "1. 不要编造用户没有提供的事实、数据或案例。\n"
            "2. 文档标题第一行必须是 Markdown H1：# {doc_title}。\n"
            "3. 固定章节：当前结论、适用场景、原有认知/常见误区、新判断、操作原则、例子、待验证。\n"
            "4. 如果信息不足，对应章节写“待补充”，不要硬编。\n"
            "5. 语言要像内部方法论，不要像公众号文章。\n"
            "输出字段固定为：status, content。"
        ).format(doc_title=doc_title)
        user_content = json.dumps(
            {
                "doc_title": doc_title,
                "existing_document_text": existing_text[:50000],
                "new_raw_text": message.body,
                "plan": plan,
                "created_at": format_display_time(message.created_at),
            },
            ensure_ascii=False,
        )
        try:
            env = self.content_flow_client._content_flow_env()
            result = self.content_flow_client._call_postprocess_json(prompt, user_content, env, "自媒体认知整合")
        except Exception as exc:
            return {"status": "pending_manual", "reason": str(exc), "content": ""}
        return result if isinstance(result, dict) else {"status": "pending_manual", "reason": "OpenClaw 返回非 JSON object", "content": ""}

    def _selfmedia_cognition_doc_title(self, plan: dict[str, Any]) -> str:
        raw_title = str(plan.get("target_title") or "").strip()
        parts = [item.strip() for item in raw_title.split("｜") if item.strip()]
        if len(parts) >= 3 and parts[0] == "自媒体认知":
            track = self._selfmedia_cognition_title_segment(parts[1], limit=10) or "通用"
            theme = self._selfmedia_cognition_title_segment(parts[2], limit=20) or "未命名认知"
        else:
            track = self._selfmedia_cognition_title_segment(str(plan.get("track") or ""), limit=10) or "通用"
            theme = self._selfmedia_cognition_title_segment(str(plan.get("theme") or plan.get("main_point") or plan.get("summary") or ""), limit=20) or "未命名认知"
        return f"自媒体认知｜{track}｜{theme}"

    def _selfmedia_cognition_title_segment(self, value: str, *, limit: int) -> str:
        text = re.sub(r"https?://\S+", "", str(value or ""))
        text = re.sub(r"(自媒体认知|认知积累|文档|记录|标题|主旨|赛道)", "", text)
        text = re.sub(r"[【】「」『』《》\"'`#*_~]+", "", text)
        text = re.sub(r"[^\w\u4e00-\u9fff]+", "", text)
        text = text.strip("_ ")
        return text[:limit]

    def _find_child_node_by_title(self, child_nodes: list[dict[str, str]], title: str) -> dict[str, str] | None:
        clean = str(title or "").strip()
        for item in child_nodes:
            if str(item.get("title") or "").strip() == clean:
                return item
        return None
