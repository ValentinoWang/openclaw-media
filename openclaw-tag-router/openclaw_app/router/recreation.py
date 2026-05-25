from __future__ import annotations

from .tag_router_common import *


class RecreationMixin:
    def handle_再创作(self, message: Message) -> TaskResult:
        metadata = message.metadata or {}
        sections = self._recreation_sections(message)
        section_map = dict(sections)
        title_source = section_map.get("转化目标") or section_map.get("再创作意图") or message.body
        llm_title, title_meta = self._recreation_llm_title(message, sections)
        title = f"再创作任务：{llm_title or self._recreation_compact_theme(title_source, limit=30)}"
        extra: dict[str, Any] = {
            "tags": ["再创作", "素材复用"],
            "workflow": "recreation_task_card",
            "llm_title": llm_title,
            "llm_title_status": title_meta.get("status", ""),
        }
        if title_meta.get("reason"):
            extra["llm_title_reason"] = title_meta.get("reason")
        if context_prompt := self._conversation_context_prompt(message):
            sections.append(("最近对话上下文", context_prompt))
            extra["conversation_context_count"] = self._conversation_context(message).get("loaded_count", 0)
        entry = self.archive_service.save_archive(message, title, sections, extra)
        fs = self._sync_recreation_entry_to_feishu(entry, message, "创作灵感表", sections, llm_title or "")
        unified_index: dict[str, str] = {}
        unified_warning = ""
        try:
            ingested_at = self._unified_now_iso()
            unified_index = self._sync_unified_creation_record(
                {
                    "记录类型": "再创作任务",
                    "标题": fs.get("entry_doc_name") or title,
                    "主题": llm_title or self._recreation_compact_theme(title_source, limit=20),
                    "内容": section_map.get("原始内容", ""),
                    "摘要": section_map.get("转化目标") or section_map.get("再创作意图", ""),
                    "关键词标签": "创作-再创、再创作、素材复用",
                    "来源链接": section_map.get("素材来源", ""),
                    "文档链接JSON": {"recreation_doc": fs.get("doc", "")},
                    "主状态": "已归档",
                    "入库时间": ingested_at,
                    "创建时间": message.created_at,
                    "更新时间": ingested_at,
                    "爆点分析JSON": {
                        "transferable_points": section_map.get("可迁移点", ""),
                        "recreation_direction": section_map.get("再创作方向", ""),
                        "suggested_outputs": section_map.get("建议产物", ""),
                        "target": section_map.get("转化目标", ""),
                    },
                    "详情JSON": {
                        "workflow": "creation_recreation",
                        "workflow_tag": "创作-再创",
                        "archive_id": entry.frontmatter.get("id", ""),
                        "local_path": entry.local_path,
                        "intent": section_map.get("再创作意图", ""),
                        "pending_items": section_map.get("待补充信息", ""),
                        "next_step": section_map.get("下一步", ""),
                        "field_guide_url": "https://tcnwueberajc.feishu.cn/wiki/OmDew1gmSiTQc8kv85rcZCvanib",
                    },
                }
            )
        except Exception as exc:
            unified_warning = f"创作任务总表写入失败：{exc}"
        reply = "\n".join(
            [
                "已生成再创作任务卡。",
                "标签：再创作",
                f"本地路径：{entry.local_path}",
            ]
        )
        if fs.get("doc"):
            reply = f"{reply}\n飞书文档：{fs.get('doc')}"
        if unified_index.get("record_id"):
            reply = f"{reply}\n创作任务总表记录：{unified_index.get('record_id')}"
        content_os_task = self._maybe_create_content_os_task_from_recreation(message, unified_index, fs)
        if content_os_task.get("task_id"):
            reply = f"{reply}\nContent OS Mac 任务：{content_os_task.get('task_path')}"
        if warning := fs.get("warning"):
            reply = ReplyService.append_warning(reply, warning)
        if unified_warning:
            reply = ReplyService.append_warning(reply, unified_warning)
        return TaskResult(
            ok=True,
            status="archived",
            reply=reply,
            task_id=entry.frontmatter["id"],
            local_path=entry.local_path,
            feishu_doc=fs.get("doc", ""),
            extra={"workflow": "recreation_task_card", "unified_index": unified_index, "content_os_task": content_os_task},
        )

    def _recreation_sections(self, message: Message) -> list[tuple[str, str]]:
        body = message.body.strip()
        source_url = self._extract_first_url(body)
        intent = self._recreation_intent(body, source_url)
        target = self._recreation_target(body)
        transferable = self._recreation_transferable_points(body)
        direction = self._recreation_direction(body, target)
        output = self._recreation_output_plan(target)
        pending = self._recreation_pending_items(body)
        next_step = "\n".join(
            [
                "- 需要可发布初稿时，用 `【创作】` 补充平台、账号、类型、主体和发布时间。",
                "- 需要逐镜头分析原作品时，再显式发送 `【拆解】`；本入口不会自动拆解。",
            ]
        )
        return [
            ("原始内容", body),
            ("素材来源", source_url if contains_link(body) else "未识别到链接，按文本想法归档"),
            ("再创作意图", intent),
            ("转化目标", target),
            ("可迁移点", transferable),
            ("再创作方向", direction),
            ("建议产物", output),
            ("待补充信息", pending),
            ("下一步", next_step),
        ]

    def _recreation_intent(self, body: str, source_url: str) -> str:
        text = body.replace(source_url, "").strip() if source_url else body.strip()
        text = re.sub(r"\s+", " ", text)
        return text or "记录素材复用、改编或转场方向。"

    def _recreation_target(self, body: str) -> str:
        patterns = [
            r"(?:跳到|接到|迁移到|转到|改成|做成)([^，。；;\n]+)",
            r"(?:用于|用到|放到)([^，。；;\n]+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, body)
            if match:
                target = re.sub(r"https?://\S+", "", match.group(1))
                return target.strip(" ：:，。；;")
        return "待明确目标场景/账号/选题。"

    def _recreation_transferable_points(self, body: str) -> str:
        points: list[str] = []
        keyword_points = [
            ("开头", "开头钩子"),
            ("转场", "转场方式"),
            ("音效", "音效/节奏点"),
            ("动作", "动作承接"),
            ("字幕", "字幕表达"),
            ("设定", "人物或情境设定"),
            ("反差", "反差结构"),
        ]
        for keyword, point in keyword_points:
            if keyword in body and point not in points:
                points.append(point)
        if not points:
            points = ["钩子", "节奏", "表达方式"]
        return "\n".join(f"- {point}" for point in points)

    def _recreation_direction(self, body: str, target: str) -> str:
        lines = []
        if "转场" in body:
            lines.append("- 保留原素材的开头/动作/节奏作为进入点，用画面或动作完成转场。")
        else:
            lines.append("- 提取原素材最有记忆点的钩子，迁移到自己的内容场景。")
        if target and not target.startswith("待明确"):
            lines.append(f"- 主体内容承接到：{target}。")
        lines.append("- 先记录方向，不把它升级为完整拆解；避免只看链接就编造原作品细节。")
        return "\n".join(lines)

    def _recreation_output_plan(self, target: str) -> str:
        subject = target if target and not target.startswith("待明确") else "目标内容"
        return "\n".join(
            [
                f"- 3 秒开头：借原素材钩子引出{subject}。",
                "- 转场点：卡动作、音效、字幕或画面节奏。",
                f"- 主体段落：进入{subject}的真实素材、观点或故事。",
                "- 结尾互动：抛出一个和目标受众相关的问题。",
            ]
        )

    def _recreation_pending_items(self, body: str) -> str:
        pending = []
        if not re.search(r"(小红书|抖音|视频号|B站|微博)", body):
            pending.append("目标平台")
        if not re.search(r"(图文|视频|短视频|口播|vlog|封面)", body, re.IGNORECASE):
            pending.append("内容形式")
        if not re.search(r"(账号|人设|受众|发布时间|发布)", body):
            pending.append("账号/受众/发布时间")
        if not pending:
            pending.append("是否需要继续生成可发布初稿")
        return "\n".join(f"- {item}" for item in pending)

    def _sync_recreation_entry_to_feishu(self, entry, message: Message, doc_name: str, sections: list[tuple[str, str]], short_title: str = "") -> dict[str, str]:
        try:
            entry_doc_name = self._recreation_entry_doc_name(entry.frontmatter.get("id", ""), message, sections, short_title)
            parts = self._recreation_feishu_parts(entry.local_path, message, sections, short_title)
            if hasattr(self.feishu_service, "replace_child_entry_under_node"):
                fs = self.feishu_service.replace_child_entry_under_node(UNIFIED_CREATION_PARENT_NODE_TOKEN, entry_doc_name, "\n".join(parts))
            else:
                raise RuntimeError("FeishuService 缺少按 wiki 节点创建子文档的能力，拒绝写入未统一任务池")

            updates = {
                "feishu_synced": True,
                "feishu_doc": fs.get("doc", ""),
                "feishu_doc_title": entry_doc_name,
            }
            self.archive_service.update_frontmatter(entry.local_path, updates)
            result = dict(fs)
            result["entry_doc_name"] = entry_doc_name
            return result
        except Exception as exc:
            self.archive_service.update_frontmatter(entry.local_path, {"feishu_synced": False, "feishu_doc": doc_name, "feishu_error": str(exc)})
            return {"status": "pending_manual", "doc": doc_name, "warning": f"飞书同步失败：{exc}"}

    def _recreation_entry_doc_name(self, record_id: str, message: Message, sections: list[tuple[str, str]], short_title: str = "") -> str:
        section_map = dict(sections)
        theme_source = (
            section_map.get("转化目标")
            or section_map.get("再创作意图")
            or section_map.get("原始内容")
            or message.body
        )
        theme = self._normalize_recreation_title(short_title, limit=20) or self._recreation_compact_theme(theme_source, limit=20) or "未命名方向"
        source_url = self._extract_first_url(message.body) if contains_link(message.body) else ""
        suffix_seed = source_url or str(record_id or "").strip()
        suffix = hashlib.sha1(suffix_seed.encode("utf-8")).hexdigest()[:4] if suffix_seed else ""
        return f"再创作｜{theme}｜{suffix}" if suffix else f"再创作｜{theme}"

    def _recreation_llm_title(self, message: Message, sections: list[tuple[str, str]]) -> tuple[str, dict[str, str]]:
        section_map = dict(sections)
        fallback = self._recreation_fallback_title(message, sections)
        if not hasattr(self.content_flow_client, "_call_postprocess_json"):
            return fallback, {"status": "fallback", "reason": "content_flow_client 缺少 LLM JSON 调用"}
        prompt = (
            "你是自媒体再创作任务命名助手。只输出合法 JSON，不要 Markdown，不要解释。\n"
            "任务：根据用户的再创作意图，提炼一个 8-20 个汉字的短标题，用作飞书子文档标题。\n"
            "标题必须概括这条任务的主旨，不要照抄完整分享文案，不要包含 URL、平台口令、作者名、日期、标点或“再创作/任务/记录/文档”等泛词。\n"
            "优先体现：目标场景、转场/钩子/脚本用途、核心内容。缺失信息不要编造。\n"
            "输出字段固定为 title、reason。"
        )
        user_content = json.dumps(
            {
                "raw_text": message.body,
                "source_url": section_map.get("素材来源", ""),
                "intent": section_map.get("再创作意图", ""),
                "target": section_map.get("转化目标", ""),
                "transferable_points": section_map.get("可迁移点", ""),
            },
            ensure_ascii=False,
        )
        try:
            env = self.content_flow_client._content_flow_env()
            result = self.content_flow_client._call_postprocess_json(prompt, user_content, env, "再创作标题生成")
        except Exception as exc:
            return fallback, {"status": "fallback", "reason": str(exc)}
        title = self._normalize_recreation_title(str(result.get("title") or ""), limit=20)
        if title:
            return title, {"status": str(result.get("status") or "done"), "reason": str(result.get("reason") or "")}
        return fallback, {"status": "fallback", "reason": str(result.get("reason") or "LLM 未返回可用标题")}

    def _recreation_fallback_title(self, message: Message, sections: list[tuple[str, str]]) -> str:
        section_map = dict(sections)
        target = self._recreation_compact_theme(section_map.get("转化目标") or "", limit=14)
        body = message.body
        if target and "转场" in body and "开头" in body:
            return self._normalize_recreation_title(f"{target}转场开头", limit=20)
        if target and "转场" in body:
            return self._normalize_recreation_title(f"{target}转场设计", limit=20)
        if target:
            return self._normalize_recreation_title(f"{target}内容改编", limit=20)
        return self._recreation_compact_theme(section_map.get("再创作意图") or message.body, limit=20)

    def _normalize_recreation_title(self, value: str, *, limit: int = 20) -> str:
        text = re.sub(r"https?://\S+", "", str(value or ""))
        text = re.sub(r"[【】「」『』《》\"'`#*_~]+", "", text)
        text = re.sub(r"(再创作|任务卡|任务|记录|文档|标题)", "", text)
        text = re.sub(r"[^\w\u4e00-\u9fff]+", "", text)
        text = text.strip("_ ")
        if not text:
            return ""
        return text[:limit]

    def _recreation_compact_theme(self, value: str, *, limit: int = 32) -> str:
        text = re.sub(r"https?://\S+", "", str(value or ""))
        text = re.sub(r"\[[^\]]{1,80}\]\([^)]*\)", "", text)
        text = re.sub(r"\b\d{1,2}/\d{1,2}\b", "", text)
        text = re.sub(r"[A-Za-z0-9._-]{2,}\s*[:：/]+", "", text)
        text = re.sub(r"\s+", " ", text).strip(" ：:，。；;|｜")
        return self._knowledge_compact_title(text, limit=limit)

    def _recreation_feishu_parts(self, local_path: str, message: Message, sections: list[tuple[str, str]], short_title: str = "") -> list[str]:
        section_map = dict(sections)
        title = self._normalize_recreation_title(short_title, limit=20) or self._recreation_compact_theme(section_map.get("转化目标") or message.body, limit=24) or "未命名方向"
        parts = [
            f"再创作任务卡｜{format_display_time(message.created_at)}｜{title}",
            f"来源：{message.source.upper()}",
            "标签：再创作",
            "",
            "素材来源",
            section_map.get("素材来源", "未识别到链接"),
            "",
            "原始内容",
            section_map.get("原始内容", message.body),
            "",
            "再创作意图",
            section_map.get("再创作意图", "待明确"),
            "",
            "转化目标",
            section_map.get("转化目标", "待明确"),
            "",
            "可迁移点",
            self._doc_friendly_list(section_map.get("可迁移点", "")),
            "",
            "再创作方向",
            self._doc_friendly_list(section_map.get("再创作方向", "")),
            "",
            "建议产物",
            self._doc_friendly_list(section_map.get("建议产物", "")),
            "",
            "待补充信息",
            self._doc_friendly_list(section_map.get("待补充信息", "")),
            "",
            "下一步",
            self._doc_friendly_list(section_map.get("下一步", "")),
            "",
            f"本地归档：{local_path}",
        ]
        return parts

    def _recreation_feishu_blocks(self, local_path: str, message: Message, sections: list[tuple[str, str]], short_title: str = "") -> list[dict[str, Any]]:
        section_map = dict(sections)
        title = self._normalize_recreation_title(short_title, limit=20) or self._recreation_compact_theme(section_map.get("转化目标") or message.body, limit=24) or "未命名方向"
        blocks: list[dict[str, Any]] = [
            self._docx_heading_block(1, f"再创作任务卡｜{format_display_time(message.created_at)}｜{title}"),
            self._docx_text_block(f"来源：{message.source.upper()}"),
            self._docx_text_block("标签：再创作"),
            self._docx_heading_block(2, "素材与目标"),
            self._docx_heading_block(3, "素材来源"),
            self._docx_text_block(section_map.get("素材来源", "未识别到链接")),
            self._docx_heading_block(3, "原始内容"),
        ]
        blocks.extend(self._docx_text_blocks(section_map.get("原始内容", message.body)))
        blocks.extend(
            [
                self._docx_heading_block(3, "再创作意图"),
                self._docx_text_block(section_map.get("再创作意图", "待明确")),
                self._docx_heading_block(3, "转化目标"),
                self._docx_text_block(section_map.get("转化目标", "待明确")),
                self._docx_heading_block(2, "执行方向"),
                self._docx_heading_block(3, "可迁移点"),
            ]
        )
        blocks.extend(self._docx_text_blocks(self._doc_friendly_list(section_map.get("可迁移点", ""))))
        blocks.append(self._docx_heading_block(3, "再创作方向"))
        blocks.extend(self._docx_text_blocks(self._doc_friendly_list(section_map.get("再创作方向", ""))))
        blocks.extend(
            [
                self._docx_heading_block(2, "产出计划"),
                self._docx_heading_block(3, "建议产物"),
            ]
        )
        blocks.extend(self._docx_text_blocks(self._doc_friendly_list(section_map.get("建议产物", ""))))
        blocks.append(self._docx_heading_block(3, "待补充信息"))
        blocks.extend(self._docx_text_blocks(self._doc_friendly_list(section_map.get("待补充信息", ""))))
        blocks.append(self._docx_heading_block(3, "下一步"))
        blocks.extend(self._docx_text_blocks(self._doc_friendly_list(section_map.get("下一步", ""))))
        blocks.append(self._docx_text_block(f"本地归档：{local_path}"))
        return blocks
