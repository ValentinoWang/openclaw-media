from __future__ import annotations

from .tag_router_common import *


class DocumentToolsMixin:
    def handle_去补丁(self, message: Message) -> TaskResult:
        doc_url = self._extract_first_url(message.body)
        if not doc_url or not doc_url.startswith("http"):
            return TaskResult(
                ok=False,
                status="missing_document_url",
                reply="请提供要去补丁的飞书文档链接，例如：`【去补丁】https://.../wiki/...`。",
                task_id="",
            )
        if not hasattr(self.feishu_service, "read_document_text") or not hasattr(self.feishu_service, "replace_document_url"):
            return TaskResult(ok=False, status="unsupported_feishu_service", reply="当前飞书服务不支持读取/覆盖文档。", task_id="")

        source = self.feishu_service.read_document_text(doc_url)
        original_text = str(source.get("text") or "").strip()
        if not source.get("ok") or not original_text:
            return TaskResult(ok=False, status="read_document_failed", reply=f"读取文档失败：{source.get('error') or '正文为空'}", task_id="")

        result = self._depatch_document_content(original_text, doc_url)
        if result.get("status") == "pending_manual":
            return TaskResult(ok=False, status="depatch_pending_manual", reply=f"去补丁失败：{result.get('reason') or 'LLM 未返回可用结果'}", task_id="")
        content = self._normalize_depatch_content(result.get("content") or result.get("markdown") or "")
        if len(content) < 80:
            return TaskResult(ok=False, status="depatch_empty", reply="去补丁失败：LLM 返回内容过短，已停止覆盖原文档。", task_id="")

        fs = self.feishu_service.replace_document_url(doc_url, content)
        entry = self.archive_service.save_archive(
            message,
            "去补丁",
            [
                ("目标文档", doc_url),
                ("原文字数", str(len(original_text))),
                ("整合后字数", str(len(content))),
                ("状态", "已覆盖写回同一文档"),
            ],
        )
        self.archive_service.update_frontmatter(entry.local_path, {"feishu_synced": True, "feishu_doc": fs.get("doc", "")})
        reply = "\n".join(
            [
                "已完成去补丁，并覆盖写回同一文档。",
                f"文档：{fs.get('doc') or doc_url}",
                f"原文字数：{len(original_text)}",
                f"整合后字数：{len(content)}",
            ]
        )
        return TaskResult(ok=True, status="depatched", reply=reply, task_id=entry.frontmatter["id"], local_path=entry.local_path, feishu_doc=fs.get("doc", ""))

    def handle_补充(self, message: Message) -> TaskResult:
        doc_url = self._extract_supplement_document_url(message)
        if not doc_url:
            return TaskResult(
                ok=False,
                status="missing_supplement_document",
                reply="请回复相关飞书文档对话后发送 `【补充】补充内容`，或在正文里带上目标飞书文档链接。",
                task_id="",
            )
        if not hasattr(self.feishu_service, "read_document_text") or not hasattr(self.feishu_service, "replace_document_url"):
            return TaskResult(ok=False, status="unsupported_feishu_service", reply="当前飞书服务不支持读取/覆盖文档。", task_id="")

        supplement_text = self._supplement_text_without_document_url(message.body, doc_url)
        if not supplement_text:
            return TaskResult(
                ok=False,
                status="missing_supplement_text",
                reply="请在 `【补充】` 后写要合并进文档的补充内容。",
                task_id="",
                feishu_doc=doc_url,
            )

        source = self.feishu_service.read_document_text(doc_url)
        original_text = str(source.get("text") or "").strip()
        if not source.get("ok") or not original_text:
            return TaskResult(ok=False, status="read_document_failed", reply=f"读取文档失败：{source.get('error') or '正文为空'}", task_id="")

        result = self._merge_document_supplement_content(original_text, supplement_text, doc_url, message)
        if result.get("status") == "pending_manual":
            return TaskResult(ok=False, status="supplement_pending_manual", reply=f"补充合并失败：{result.get('reason') or 'LLM 未返回可用结果'}", task_id="", feishu_doc=doc_url)
        content = self._normalize_depatch_content(result.get("content") or result.get("markdown") or "")
        if len(content) < 40 or (len(original_text) > 500 and len(content) < 120):
            return TaskResult(ok=False, status="supplement_empty", reply="补充合并失败：LLM 返回内容过短，已停止覆盖原文档。", task_id="", feishu_doc=doc_url)

        fs = self.feishu_service.replace_document_url(doc_url, content)
        entry = self.archive_service.save_archive(
            message,
            "补充文档",
            [
                ("目标文档", doc_url),
                ("补充内容", supplement_text),
                ("原文字数", str(len(original_text))),
                ("合并后字数", str(len(content))),
                ("状态", "已合并并覆盖写回同一文档"),
            ],
            {"workflow": "document_supplement", "target_doc": doc_url},
        )
        self.archive_service.update_frontmatter(entry.local_path, {"feishu_synced": True, "feishu_doc": fs.get("doc", "")})
        reply = "\n".join(
            [
                "已完成补充，并覆盖写回同一文档。",
                f"文档：{fs.get('doc') or doc_url}",
                f"补充字数：{len(supplement_text)}",
                f"合并后字数：{len(content)}",
            ]
        )
        return TaskResult(
            ok=True,
            status="supplement_merged",
            reply=reply,
            task_id=entry.frontmatter["id"],
            local_path=entry.local_path,
            feishu_doc=fs.get("doc", ""),
            extra={"workflow": "document_supplement", "target_doc": fs.get("doc") or doc_url},
        )

    def _merge_document_supplement_content(self, original_text: str, supplement_text: str, doc_url: str, message: Message) -> dict[str, Any]:
        if not hasattr(self.content_flow_client, "_call_postprocess_json"):
            return {"status": "pending_manual", "reason": "content_flow_client 缺少 LLM JSON 调用"}
        prompt = (
            "你是全局文档补充合并编辑器。只输出合法 JSON，不要 Markdown 代码块，不要解释。\n"
            "任务：把用户新增补充自然合并进目标飞书文档，使目标文档仍是一份单一、简单、可继续维护的 SSOT。\n"
            "要求：\n"
            "1. 保留原文档的稳定结构、事实、链接、结论、行动项和字段口径，不要编造新信息。\n"
            "2. 将用户补充归入最合适的原有章节；必要时新增小节，但不要保留“用户补充”“追加记录”“v2/v3”等过程痕迹。\n"
            "3. 如果补充与原文冲突，优先采用更具体、更新、证据更明确的信息；无法判断时保留为待确认，不要静默丢弃。\n"
            "4. 去重合并重复表达，删除过程量和临时讨论痕迹，除非它们本身就是目标文档的稳定内容。\n"
            "5. 输出字段固定为：{\"status\":\"done\",\"content\":\"合并后的完整 Markdown 正文\"}。"
        )
        user_content = json.dumps(
            {
                "document_url": doc_url,
                "document_text": original_text[:60000],
                "supplement_text": supplement_text[:20000],
                "created_at": format_display_time(message.created_at),
                "recent_conversation_context": self._conversation_context_prompt(message),
            },
            ensure_ascii=False,
        )
        try:
            env = self.content_flow_client._content_flow_env()
            return self.content_flow_client._call_postprocess_json(prompt, user_content, env, "补充合并")
        except Exception as exc:
            return {"status": "pending_manual", "reason": str(exc)}

    def _extract_supplement_document_url(self, message: Message) -> str:
        for value in (
            message.body,
            self._metadata_pick(message.metadata or {}, "target_doc_url", "target_document_url", "document_url", "doc_url", "feishu_doc", "url", "link"),
            message.metadata or {},
            self._conversation_context(message),
            self._conversation_context_prompt(message),
        ):
            found = self._extract_first_feishu_document_url(value)
            if found:
                return found
        return ""

    def _metadata_pick(self, metadata: dict[str, Any], *keys: str) -> Any:
        for key in keys:
            value = metadata.get(key)
            if value not in (None, "", [], {}):
                return value
        return ""

    def _extract_first_feishu_document_url(self, value: Any) -> str:
        if isinstance(value, dict):
            priority_keys = (
                "target_doc_url",
                "target_document_url",
                "document_url",
                "doc_url",
                "feishu_doc",
                "url",
                "link",
                "text",
                "content",
                "raw_text",
                "message",
                "reply",
                "quote",
                "quoted_message",
                "replied_message",
                "parent_message",
                "raw_event",
            )
            for key in priority_keys:
                if key in value:
                    found = self._extract_first_feishu_document_url(value.get(key))
                    if found:
                        return found
            for child in value.values():
                found = self._extract_first_feishu_document_url(child)
                if found:
                    return found
            return ""
        if isinstance(value, (list, tuple)):
            for item in value:
                found = self._extract_first_feishu_document_url(item)
                if found:
                    return found
            return ""
        text = str(value or "")
        for match in re.finditer(r"https?://[^\s)\]，。；;、]+", text):
            url = match.group(0).strip()
            lowered = url.lower()
            if ("feishu.cn" in lowered or "larksuite.com" in lowered) and re.search(r"/(?:wiki|docx|doc|docs)/", lowered):
                return url
        return ""

    def _supplement_text_without_document_url(self, body: str, doc_url: str) -> str:
        text = str(body or "").strip()
        if not text:
            return ""
        lines = [line for line in text.splitlines() if doc_url not in line]
        stripped = "\n".join(lines).strip()
        if stripped:
            return stripped
        stripped = text.replace(doc_url, "").strip()
        stripped = re.sub(r"^(?:目标文档链接|文档链接|目标文档|文档|链接)\s*[=:：]\s*", "", stripped).strip()
        return stripped

    def _depatch_document_content(self, original_text: str, doc_url: str) -> dict[str, Any]:
        if not hasattr(self.content_flow_client, "_call_postprocess_json"):
            return {"status": "pending_manual", "reason": "content_flow_client 缺少 LLM JSON 调用"}
        prompt = (
            "你是文档去补丁编辑器。只输出合法 JSON，不要 Markdown 代码块，不要解释。\n"
            "任务：把一个经过多次追加、含有“补充记录”“v1/v2/v3”“追加内容”等痕迹的文档，重整为一份完整、连贯、可直接发布/继续维护的正文。\n"
            "要求：\n"
            "1. 保留原文档中的事实、链接、标题主旨、脚本、分镜、结论和待办，不要编造新信息。\n"
            "2. 合并重复段落，把后续补充自然吸收到对应章节中，不要保留“补充记录”“追加”“版本”等补丁痕迹。\n"
            "3. 维持文档类型：爆款拆解仍是爆款拆解，再创作仍是再创作任务/脚本。\n"
            "4. 输出字段：{\"status\":\"done\",\"content\":\"整合后的完整 Markdown 正文\"}。"
        )
        user_content = json.dumps(
            {
                "document_url": doc_url,
                "document_text": original_text[:60000],
            },
            ensure_ascii=False,
        )
        env = self.content_flow_client._content_flow_env()
        return self.content_flow_client._call_postprocess_json(prompt, user_content, env, "去补丁")

    def _normalize_depatch_content(self, value: str) -> str:
        text = str(value or "").strip()
        text = re.sub(r"^```(?:markdown|md)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()
