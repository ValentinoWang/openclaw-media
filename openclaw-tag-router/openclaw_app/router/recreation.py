from __future__ import annotations

from .tag_router_common import *


RECREATION_TASK_CARD_PROMPT = """你是 OpenClaw Media 的再创作任务卡规划器。只输出合法 JSON，不要 Markdown，不要解释。

任务：把用户发来的「拆解-再创」材料整理成可执行任务卡。任务卡主体必须由你基于语义生成，不要套关键词模板。

输入可能包含视频/图文链接、原素材描述、用户想迁移到的账号/平台/内容场景、转场/钩子/结构诉求、本地素材批次 ID。

标签与深度规则：
- 【拆解-再创】默认按简略深度处理。
- 【拆解-再创-简略】必须输出 recreation_depth="brief"、deconstruction_depth="partial"。
- 【拆解-再创-详细】必须输出 recreation_depth="detailed"、deconstruction_depth="full"。
- 【拆解-再创】正文明确写「详细 / 完整拆解 / 完整分镜 / Storyboard / EDL / 完整脚本 / 逐镜头」时，可以升级为 detailed；否则保持 brief。
- 正文明确写「不生成完整 Storyboard 和 EDL」时，必须保持 brief。

通用输出要求：
- 不要编造你没看过的原作品细节；无法确认时写「待明确：...」。
- target 要说明要转化到什么账号/平台/内容场景/选题。
- transferable_points 要说明可以迁移的钩子、结构、镜头/动作、叙事、情绪、节奏或表达机制。
- recreation_direction 要说明怎么改成自己的内容，不要只写泛泛建议。
- suggested_outputs 要给出建议产物，例如短视频脚本、分镜、标题封面、素材清单、剪辑决策等。
- pending_items 要列出继续生成可发布初稿前必须补齐的信息；这些信息缺口不等于任务卡主体缺失。
- next_steps 要列出下一步动作。
- confidence 低于 0.65 时必须说明原因并列 missing_fields，但仍要输出完整任务卡主体；不要只返回 reason。

简略模式要求：
- mode 输出 "轻量反抄_BGM卡点" 或 "简略再创作"。
- deconstruction_depth 输出 "partial"。
- suggested_outputs 只建议「轻量剪辑卡」「BGM/节奏参考」「素材填空建议」「标题/封面候选」「发布文案初稿」等轻量产物。
- 不要把「完整 Storyboard」「完整 EDL」「逐镜头复刻」列为建议产物。
- lightweight_edit_card 要写清楚钩子、BGM/节奏、素材填空、标题封面和发布文案方向。

详细模式要求：
- mode 输出 "详细再创作"。
- deconstruction_depth 输出 "full"。
- suggested_outputs 可以包含完整爆款拆解、可迁移结构、避抄说明、自己的发布脚本、视频分镜/图文脚本、素材需求清单、标题封面、发布文案、Mac 素材匹配任务。
- detailed 模式必须基于真实链接或明确素材证据；证据不足时不要硬写原视频细节，把缺口列入 pending_items。

输出 JSON 字段固定为：
{
  "title": "8-20 个汉字的任务短标题",
  "source_url": "素材来源 URL 或空字符串",
  "intent": "再创作意图",
  "target": "转化目标",
  "recreation_depth": "brief / detailed",
  "mode": "轻量反抄_BGM卡点 / 简略再创作 / 详细再创作 / 标准再创作任务 / 空字符串",
  "deconstruction_depth": "partial / full / none",
  "local_batch_id": "用户明确写出的本地素材批次ID，无法识别则空字符串",
  "bgm_plan": "原视频同款 / 同节奏替代 / 待剪映搜索 / 空字符串",
  "transferable_points": ["..."],
  "recreation_direction": ["..."],
  "suggested_outputs": ["..."],
  "lightweight_edit_card": ["..."],
  "material_fill_suggestions": ["..."],
  "titles": ["..."],
  "cover_candidates": ["..."],
  "publish_copy": "发布文案初稿或空字符串",
  "deconstruct_doc_url": "完整拆解文档链接或空字符串",
  "creative_positioning": "自己的创作定位或空字符串",
  "final_script": "自己的发布脚本初稿或空字符串",
  "video_storyboard": ["..."],
  "image_post_script": ["..."],
  "material_requirements": ["..."],
  "hashtags": ["..."],
  "production_notes": ["..."],
  "anti_copy_notes": "避抄说明或空字符串",
  "mac_task_intent": "none / local_material_match / native_import_pack",
  "pending_items": ["..."],
  "next_steps": ["..."],
  "confidence": 0.0,
  "missing_fields": ["..."],
  "evidence": "支持判断的原文片段",
  "reason": "一句话说明整理依据"
}
"""


class RecreationMixin:
    def handle_再创作(self, message: Message) -> TaskResult:
        task_card = self._recreation_task_card_with_llm(message)
        if not task_card.get("ok"):
            return self._recreation_task_card_failure(message, task_card)
        recreation_depth = self._recreation_depth(message, task_card)
        task_card["recreation_depth"] = recreation_depth
        task_card["deconstruction_depth"] = "full" if recreation_depth == "detailed" else "partial"
        if recreation_depth == "detailed" and not task_card.get("mode"):
            task_card["mode"] = "详细再创作"
        if recreation_depth == "brief" and not task_card.get("mode"):
            task_card["mode"] = "简略再创作"

        partial_deconstruct: dict[str, Any] = {}
        full_deconstruct: dict[str, Any] = {}
        if recreation_depth == "detailed":
            full_deconstruct = self._maybe_full_deconstruct_for_detailed_recreation(message, task_card)
            if full_deconstruct:
                task_card["full_deconstruct"] = full_deconstruct
                if doc_url := self._recreation_deconstruct_doc_url(full_deconstruct):
                    task_card["deconstruct_doc_url"] = task_card.get("deconstruct_doc_url") or doc_url
        else:
            partial_deconstruct = self._maybe_partial_deconstruct_for_lightweight_recreation(message, task_card)
            if partial_deconstruct:
                task_card["partial_deconstruct"] = partial_deconstruct

        sections = self._recreation_sections_from_task_card(message, task_card)
        section_map = dict(sections)
        llm_title = str(task_card.get("title") or "").strip()
        title = f"再创作任务：{llm_title}"
        extra: dict[str, Any] = {
            "tags": ["再创作", "素材复用", f"再创作{self._recreation_depth_label(recreation_depth)}"],
            "workflow": "recreation_task_card",
            "recreation_depth": recreation_depth,
            "llm_title": llm_title,
            "llm_task_card_status": "done",
            "llm_task_card_confidence": task_card.get("confidence", 0),
            "llm_task_card_evidence": task_card.get("evidence", ""),
        }
        if task_card.get("reason"):
            extra["llm_task_card_reason"] = task_card.get("reason")
        if partial_deconstruct:
            extra["partial_deconstruct_status"] = partial_deconstruct.get("status", "")
            extra["partial_deconstruct_mode"] = partial_deconstruct.get("mode", "")
        if full_deconstruct:
            extra["full_deconstruct_status"] = full_deconstruct.get("status", "")
            extra["full_deconstruct_mode"] = full_deconstruct.get("mode", "")
        if context_prompt := self._conversation_context_prompt(message):
            sections.append(("最近对话上下文", context_prompt))
            extra["conversation_context_count"] = self._conversation_context(message).get("loaded_count", 0)
        entry = self.archive_service.save_archive(message, title, sections, extra)
        fs = self._sync_recreation_entry_to_feishu(entry, message, "03_CreationRuns_创作运行", sections, llm_title or "")
        unified_index: dict[str, str] = {}
        unified_warning = ""
        try:
            ingested_at = self._unified_now_iso()
            unified_index = self._sync_unified_creation_record(
                {
                    "记录类型": "再创作任务",
                    "标题": fs.get("entry_doc_name") or title,
                    "主题": llm_title,
                    "内容": section_map.get("原始内容", ""),
                    "摘要": section_map.get("转化目标") or section_map.get("再创作意图", ""),
                    "关键词标签": f"拆解-再创、再创作、素材复用、{self._recreation_depth_label(recreation_depth)}",
                    "来源链接": section_map.get("素材来源", ""),
                    "再创作文档链接": fs.get("doc", ""),
                    "主状态": "已归档",
                    "入库时间": ingested_at,
                    "创建时间": message.created_at,
                    "更新时间": ingested_at,
                    "可迁移点": section_map.get("可迁移点", ""),
                    "拆解-再创方向": section_map.get("再创作方向", ""),
                    "建议产物": section_map.get("建议产物", ""),
                    "下一步": section_map.get("下一步", ""),
                    "本地报告路径": entry.local_path,
                }
            )
        except Exception as exc:
            unified_warning = f"创作运行索引写入失败：{exc}"
        reply = "\n".join(
            [
                "已生成再创作任务卡。",
                f"再创作深度：{self._recreation_depth_label(recreation_depth)}",
                "标签：再创作",
                f"本地路径：{entry.local_path}",
            ]
        )
        if partial_deconstruct:
            reply = f"{reply}\n部分拆解：{partial_deconstruct.get('status', '')}"
        if full_deconstruct:
            reply = f"{reply}\n完整拆解：{full_deconstruct.get('status', '')}"
        if fs.get("doc"):
            reply = f"{reply}\n飞书文档：{fs.get('doc')}"
        if unified_index.get("record_id"):
            reply = f"{reply}\n创作运行记录：{unified_index.get('record_id')}"
        local_batch_task = self._maybe_create_openclaw_queue_dispatch_from_recreation(message, task_card, unified_index, fs)
        content_os_task = self._maybe_create_content_os_task_from_recreation(message, unified_index, fs)
        if local_batch_task.get("task_id"):
            reply = f"{reply}\nMac 本地素材读取任务：{local_batch_task.get('task_path')}"
        if content_os_task.get("task_id"):
            reply = f"{reply}\nContent OS Mac 任务：{content_os_task.get('task_path')}"
        if recreation_depth == "detailed" and message.entry_tag == "拆解-再创":
            reply = f"{reply}\n提示：这次已按详细模式处理；下次可直接使用【拆解-再创-详细】。"
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
            extra={
                "workflow": "recreation_task_card",
                "recreation_depth": recreation_depth,
                "unified_index": unified_index,
                "content_os_task": content_os_task,
                "local_batch_task": local_batch_task,
                "partial_deconstruct": partial_deconstruct,
                "full_deconstruct": full_deconstruct,
            },
        )

    def _recreation_task_card_with_llm(self, message: Message) -> dict[str, Any]:
        if not hasattr(self.content_flow_client, "_call_profile_provider_json"):
            return {"ok": False, "status": "pending_manual", "reason": "content_flow_client 缺少 LLM JSON 调用", "missing_fields": ["llm_result"]}
        user_content = json.dumps(
            {
                "entry_tag": message.entry_tag,
                "text": message.body,
                "raw_text": message.raw_text,
                "recent_conversation_context": self._conversation_context_prompt(message),
            },
            ensure_ascii=False,
            indent=2,
        )
        try:
            result = self.content_flow_client._call_profile_provider_json(
                "content_cleaner",
                RECREATION_TASK_CARD_PROMPT,
                user_content,
                "再创作任务卡 LLM 生成",
            )
        except Exception as exc:
            return {"ok": False, "status": "pending_manual", "reason": f"LLM 任务卡生成异常：{exc}", "missing_fields": ["llm_result"]}
        return self._normalize_recreation_task_card(result)

    def _maybe_partial_deconstruct_for_lightweight_recreation(self, message: Message, task_card: dict[str, Any]) -> dict[str, Any]:
        if not self._is_lightweight_recreation(message, task_card):
            return {}
        return self._run_recreation_deconstruct(message, task_card, partial=True)

    def _maybe_full_deconstruct_for_detailed_recreation(self, message: Message, task_card: dict[str, Any]) -> dict[str, Any]:
        if self._recreation_depth(message, task_card) != "detailed":
            return {}
        return self._run_recreation_deconstruct(message, task_card, partial=False)

    def _run_recreation_deconstruct(self, message: Message, task_card: dict[str, Any], *, partial: bool) -> dict[str, Any]:
        source_url = self._recreation_source_url(message, task_card)
        mode = "partial_deconstruct" if partial else "full_deconstruct"
        if not source_url:
            return {"status": "skipped_missing_source_url", "mode": mode, "reason": "再创作未提供爆款视频链接"}
        command = [
            "/home/ubuntu/openclaw-agents/media/scripts/selfmedia.py",
            "run",
            "deconstruct",
            "--text",
            f"【拆解】{source_url}",
            "--timeout",
            "3600" if partial else "7200",
        ]
        if partial:
            command.extend(["--partial", "--no-write"])
        try:
            completed = run_media_subprocess_with_watchdog(
                command,
                cwd="/home/ubuntu/selfmedia-tools",
                timeout=3660 if partial else 7260,
                env=os.environ.copy(),
            )
        except Exception as exc:
            return {"status": "failed", "mode": mode, "source_url": source_url, "reason": f"拆解调用异常：{exc}"}
        if completed.returncode == -9:
            return {
                "status": "failed",
                "mode": mode,
                "source_url": source_url,
                "returncode": completed.returncode,
                "reason": (completed.stderr.strip() or "拆解调用超时")[-3000:],
            }
        parsed = self._parse_recreation_deconstruct_stdout(completed.stdout)
        result: dict[str, Any] = {
            "status": "done" if completed.returncode == 0 and parsed else "failed",
            "mode": mode,
            "source_url": source_url,
            "returncode": completed.returncode,
        }
        if parsed:
            result["deconstruct_result"] = parsed
        if completed.returncode != 0:
            result["reason"] = (completed.stderr.strip() or completed.stdout.strip() or "拆解失败")[-3000:]
        return result

    def _recreation_depth(self, message: Message, task_card: dict[str, Any] | None = None) -> str:
        tag = str(message.entry_tag or "").strip()
        if tag == "拆解-再创-详细":
            return "detailed"
        if tag == "拆解-再创-简略":
            return "brief"
        text = f"{message.raw_text}\n{message.body}"
        if any(signal in text for signal in ("不生成完整 Storyboard", "不生成完整Storyboard", "不生成完整 EDL", "不生成完整EDL", "轻量反抄", "BGM 卡点", "BGM卡点")):
            return "brief"
        if any(signal in text for signal in ("模式：详细", "模式:详细", "详细模式", "完整拆解", "完整分镜", "完整 Storyboard", "完整Storyboard", "Storyboard", "完整 EDL", "完整EDL", "EDL", "完整脚本", "逐镜头", "素材需求清单")):
            return "detailed"
        if task_card:
            if str(task_card.get("recreation_depth") or "").strip().lower() in {"detailed", "full", "详细"}:
                return "detailed"
            if str(task_card.get("deconstruction_depth") or "").strip().lower() == "full":
                return "detailed"
        return "brief"

    @staticmethod
    def _recreation_depth_label(depth: str) -> str:
        return "详细" if depth == "detailed" else "简略"

    def _is_lightweight_recreation(self, message: Message, task_card: dict[str, Any]) -> bool:
        if self._recreation_depth(message, task_card) == "detailed":
            return False
        text = "\n".join(
            str(value or "")
            for value in (
                task_card.get("mode"),
                task_card.get("deconstruction_depth"),
                task_card.get("suggested_outputs"),
                task_card.get("lightweight_edit_card"),
                message.raw_text,
                message.body,
            )
        )
        if str(task_card.get("deconstruction_depth") or "").strip().lower() == "partial":
            return True
        return any(signal in text for signal in ("轻量反抄", "BGM 卡点", "BGM卡点", "不生成完整 Storyboard", "不生成完整 EDL")) or message.entry_tag in {"拆解-再创", "拆解-再创-简略"}

    def _recreation_source_url(self, message: Message, task_card: dict[str, Any]) -> str:
        value = str(task_card.get("source_url") or "").strip()
        if value:
            return value
        text = f"{message.raw_text}\n{message.body}"
        match = re.search(r"https?://[^\s)\]，。；;、]+", text or "")
        return match.group(0).strip() if match else ""

    def _parse_recreation_deconstruct_stdout(self, stdout: str) -> dict[str, Any]:
        text = (stdout or "").strip()
        if not text:
            return {}
        try:
            outer = json.loads(text)
        except json.JSONDecodeError:
            last_json = re.search(r"(?s)(\{.*\})\s*$", text)
            if not last_json:
                return {"raw_stdout": text[-4000:]}
            try:
                outer = json.loads(last_json.group(1))
            except json.JSONDecodeError:
                return {"raw_stdout": text[-4000:]}
        if isinstance(outer, dict) and isinstance(outer.get("stdout"), str):
            try:
                inner = json.loads(outer.get("stdout") or "{}")
            except json.JSONDecodeError:
                inner = {"raw_stdout": outer.get("stdout", "")[-4000:]}
        else:
            inner = outer
        if not isinstance(inner, dict):
            return {"raw_result": inner}
        if isinstance(inner.get("partial_deconstruct"), dict):
            return inner.get("partial_deconstruct") or {}
        return inner

    def _parse_recreation_partial_deconstruct_stdout(self, stdout: str) -> dict[str, Any]:
        return self._parse_recreation_deconstruct_stdout(stdout)

    def _recreation_deconstruct_doc_url(self, result: dict[str, Any]) -> str:
        def walk(value: Any) -> str:
            if isinstance(value, str) and value.startswith("http"):
                return value
            if isinstance(value, dict):
                for key, item in value.items():
                    key_text = str(key).lower()
                    if any(token in key_text for token in ("doc", "url", "link", "文档")):
                        found = walk(item)
                        if found:
                            return found
                for item in value.values():
                    found = walk(item)
                    if found:
                        return found
            if isinstance(value, list):
                for item in value:
                    found = walk(item)
                    if found:
                        return found
            return ""
        return walk(result)

    def _maybe_create_openclaw_queue_dispatch_from_recreation(self, message: Message, task_card: dict[str, Any], unified_index: dict[str, str], fs: dict[str, str]) -> dict[str, Any]:
        batch_id = self._recreation_local_batch_id(message, task_card)
        if not batch_id:
            return {}
        if not all(hasattr(self, name) for name in ("_content_os_vault_root", "_next_content_os_task_id", "_append_registry_row", "_content_os_date", "_md_cell")):
            return {}
        if not re.match(r"^[A-Za-z0-9_\-\u4e00-\u9fff]{2,120}$", batch_id):
            return {"status": "blocked_unsafe_batch_id", "batch_id": batch_id}
        vault_root = self._content_os_vault_root()
        task_root = vault_root / "98_Agent任务队列" / "01_cloud_to_mac_ready"
        task_root.mkdir(parents=True, exist_ok=True)
        creation_run_id = str(unified_index.get("record_id") or "").strip()
        if not creation_run_id:
            seed = f"{message.created_at.isoformat()}|{batch_id}|{task_card.get('source_url', '')}"
            creation_run_id = f"run_{self._content_os_date(message.created_at)}_{hashlib.sha1(seed.encode('utf-8')).hexdigest()[:8]}"
        for existing in task_root.glob("*.yaml"):
            existing_text = existing.read_text(encoding="utf-8", errors="replace")
            if batch_id in existing_text and creation_run_id in existing_text and "openclaw_queue_dispatch" in existing_text:
                return {"status": "ready_task_exists", "batch_id": batch_id, "task_id": existing.stem, "task_path": str(existing)}
        task_id = self._next_content_os_task_id(vault_root, self._content_os_date(message.created_at))
        task_path = task_root / f"{task_id}_openclaw_queue_dispatch.yaml"
        if self._recreation_depth(message, task_card) == "detailed":
            requested_outputs = ["完整拆解摘要", "可迁移结构", "避抄说明", "发布脚本", "视频分镜/图文脚本", "素材需求清单", "Storyboard/EDL准备"]
        else:
            requested_outputs = ["轻量剪辑卡", "BGM/节奏参考", "素材填空建议", "标题/封面候选", "发布文案初稿"]
        payload = {
            "schema_version": "openclaw_mac_queue_task_v1",
            "task_type": "bind_creation_run_to_local_batch",
            "creation_run_id": creation_run_id,
            "feishu_doc_link": fs.get("doc", ""),
            "batch_id": batch_id,
            "topic": task_card.get("title") or task_card.get("target") or "再创作任务",
            "source_url": self._recreation_source_url(message, task_card),
            "recreation_depth": self._recreation_depth(message, task_card),
            "requested_outputs": requested_outputs,
            "constraints": {
                "do_not_sync_raw_media": True,
                "do_not_include_original_photos_or_videos_in_result": True,
                "mac_reads_local_inbox_batch": True,
                "cloud_must_not_guess_local_media": True,
            },
        }
        task_doc = {
            "spec_version": "content_os_v0.1",
            "task_id": task_id,
            "task_type": "openclaw_queue_dispatch",
            "created_at": now_in_tz("Asia/Shanghai").isoformat(),
            "created_by": "cloud_openclaw",
            "owner": "mac_openclaw",
            "status": "ready",
            "creation_run_id": creation_run_id,
            "feishu_doc_link": fs.get("doc", ""),
            "batch_id": batch_id,
            "allowed_actions": ["write_local_assets"],
            "openclaw_queue_payload": payload,
        }
        task_path.write_text(yaml.safe_dump(task_doc, allow_unicode=True, sort_keys=False).rstrip() + "\n", encoding="utf-8")
        self._append_registry_row(
            vault_root / "90_索引与注册表" / "task_registry.md",
            header="# Task Registry\n\n| task_id | project_id | task_type | status | owner | result_path | 下一步 |\n| --- | --- | --- | --- | --- | --- | --- |\n",
            key=task_id,
            row=f"| {task_id} |  | openclaw_queue_dispatch | ready | mac_openclaw |  | Mac 读取 batch_id={self._md_cell(batch_id)} 的本地素材批次并回写 result |",
        )
        return {"status": "created", "batch_id": batch_id, "task_id": task_id, "task_path": str(task_path), "creation_run_id": creation_run_id}

    def _recreation_local_batch_id(self, message: Message, task_card: dict[str, Any]) -> str:
        value = str(task_card.get("local_batch_id") or "").strip().strip("` ")
        if not value:
            text = f"{message.raw_text}\n{message.body}"
            for label in ("本地素材批次ID", "本地素材批次", "素材批次ID", "batch_id"):
                match = re.search(rf"{label}\s*[：:=]\s*(?P<value>[^\n\r]+)", text)
                if match:
                    value = match.group("value").strip().strip("` ")
                    break
        if not value:
            return ""
        value = re.split(r"\s+(?:目标平台|平台|BGM|目标|模仿重点|tags?)\s*[：:=]", value, maxsplit=1)[0].strip(" ，,。；;")
        value = value.replace("\\", "/")
        if "/" in value:
            value = value.rstrip("/").split("/")[-1]
        return value.strip()

    def _normalize_recreation_task_card(self, result: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(result, dict):
            return {"ok": False, "status": "pending_manual", "reason": "LLM 未返回对象", "missing_fields": ["llm_result"]}
        if result.get("status") not in {"done", "", None}:
            return {
                "ok": False,
                "status": str(result.get("status") or "pending_manual"),
                "reason": str(result.get("reason") or "LLM 任务卡生成未完成"),
                "missing_fields": ["llm_result"],
            }
        confidence = self._recreation_float_confidence(result.get("confidence"))
        card: dict[str, Any] = {
            "ok": True,
            "status": "done",
            "title": self._normalize_recreation_title(str(result.get("title") or ""), limit=20),
            "source_url": str(result.get("source_url") or "").strip(),
            "intent": str(result.get("intent") or "").strip(),
            "target": str(result.get("target") or "").strip(),
            "mode": str(result.get("mode") or "").strip(),
            "recreation_depth": str(result.get("recreation_depth") or "").strip(),
            "deconstruction_depth": str(result.get("deconstruction_depth") or "").strip(),
            "local_batch_id": str(result.get("local_batch_id") or "").strip(),
            "bgm_plan": str(result.get("bgm_plan") or "").strip(),
            "transferable_points": self._recreation_llm_list(result.get("transferable_points")),
            "recreation_direction": self._recreation_llm_list(result.get("recreation_direction")),
            "suggested_outputs": self._recreation_llm_list(result.get("suggested_outputs")),
            "lightweight_edit_card": self._recreation_llm_list(result.get("lightweight_edit_card")),
            "material_fill_suggestions": self._recreation_llm_list(result.get("material_fill_suggestions")),
            "titles": self._recreation_llm_list(result.get("titles")),
            "cover_candidates": self._recreation_llm_list(result.get("cover_candidates")),
            "publish_copy": str(result.get("publish_copy") or "").strip(),
            "deconstruct_doc_url": str(result.get("deconstruct_doc_url") or "").strip(),
            "creative_positioning": str(result.get("creative_positioning") or "").strip(),
            "final_script": str(result.get("final_script") or "").strip(),
            "video_storyboard": self._recreation_llm_list(result.get("video_storyboard")),
            "image_post_script": self._recreation_llm_list(result.get("image_post_script")),
            "material_requirements": self._recreation_llm_list(result.get("material_requirements")),
            "hashtags": self._recreation_llm_list(result.get("hashtags")),
            "production_notes": self._recreation_llm_list(result.get("production_notes")),
            "anti_copy_notes": str(result.get("anti_copy_notes") or "").strip(),
            "mac_task_intent": str(result.get("mac_task_intent") or "").strip(),
            "pending_items": self._recreation_llm_list(result.get("pending_items")),
            "next_steps": self._recreation_llm_list(result.get("next_steps")),
            "confidence": confidence,
            "evidence": str(result.get("evidence") or "").strip(),
            "reason": str(result.get("reason") or "").strip(),
            "provider": str(result.get("postprocess_provider") or ""),
            "model": str(result.get("postprocess_model") or ""),
        }
        llm_missing_fields = [str(item).strip() for item in result.get("missing_fields") or [] if str(item).strip()]
        card["missing_fields"] = sorted(set(llm_missing_fields))
        missing_required: list[str] = []
        required = ("title", "intent", "target", "transferable_points", "recreation_direction", "suggested_outputs", "pending_items", "next_steps")
        for key in required:
            if not card.get(key):
                missing_required.append(key)
        if missing_required:
            card.update(
                {
                    "ok": False,
                    "status": "pending_manual",
                    "reason": card.get("reason") or "LLM 任务卡缺少必要字段或置信度不足",
                    "missing_fields": sorted(set([*llm_missing_fields, *missing_required])),
                }
            )
        return card

    @staticmethod
    def _recreation_float_confidence(value: Any) -> float:
        try:
            confidence = float(value)
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, min(1.0, confidence))

    def _recreation_llm_list(self, value: Any) -> str:
        if isinstance(value, list):
            items = []
            for item in value:
                if isinstance(item, dict):
                    text = "；".join(f"{key}：{val}" for key, val in item.items() if str(val).strip())
                else:
                    text = str(item).strip()
                if text:
                    items.append(text)
        else:
            text = str(value or "").strip()
            items = [line.strip("-*+ 　") for line in text.splitlines() if line.strip()]
        return "\n".join(f"- {item}" for item in items if item)

    def _recreation_sections_from_task_card(self, message: Message, task_card: dict[str, Any]) -> list[tuple[str, str]]:
        body = message.body.strip()
        sections = [
            ("原始内容", body),
            ("素材来源", str(task_card.get("source_url") or "").strip() or "LLM未识别到素材链接"),
            ("再创作意图", str(task_card.get("intent") or "").strip()),
            ("转化目标", str(task_card.get("target") or "").strip()),
            ("模式", str(task_card.get("mode") or "").strip()),
            ("再创作深度", self._recreation_depth_label(str(task_card.get("recreation_depth") or self._recreation_depth(message, task_card)))),
            ("拆解深度", str(task_card.get("deconstruction_depth") or "").strip()),
            ("本地素材批次ID", str(task_card.get("local_batch_id") or "").strip()),
            ("BGM计划", str(task_card.get("bgm_plan") or "").strip()),
            ("可迁移点", str(task_card.get("transferable_points") or "").strip()),
            ("再创作方向", str(task_card.get("recreation_direction") or "").strip()),
            ("建议产物", str(task_card.get("suggested_outputs") or "").strip()),
            ("轻量剪辑卡", str(task_card.get("lightweight_edit_card") or "").strip()),
            ("素材填空建议", str(task_card.get("material_fill_suggestions") or "").strip()),
            ("标题候选", str(task_card.get("titles") or "").strip()),
            ("封面候选", str(task_card.get("cover_candidates") or "").strip()),
            ("发布文案", str(task_card.get("publish_copy") or "").strip()),
            ("完整拆解文档", str(task_card.get("deconstruct_doc_url") or "").strip()),
            ("创作定位", str(task_card.get("creative_positioning") or "").strip()),
            ("发布脚本", str(task_card.get("final_script") or "").strip()),
            ("视频分镜", str(task_card.get("video_storyboard") or "").strip()),
            ("图文脚本", str(task_card.get("image_post_script") or "").strip()),
            ("素材需求", str(task_card.get("material_requirements") or "").strip()),
            ("话题标签", str(task_card.get("hashtags") or "").strip()),
            ("制作说明", str(task_card.get("production_notes") or "").strip()),
            ("避抄说明", str(task_card.get("anti_copy_notes") or "").strip()),
            ("Mac任务意图", str(task_card.get("mac_task_intent") or "").strip()),
            ("待补充信息", str(task_card.get("pending_items") or "").strip()),
            ("下一步", str(task_card.get("next_steps") or "").strip()),
        ]
        partial = task_card.get("partial_deconstruct") if isinstance(task_card.get("partial_deconstruct"), dict) else {}
        if partial:
            sections.append(("部分拆解结果", json.dumps(partial, ensure_ascii=False, indent=2)[:12000]))
        full = task_card.get("full_deconstruct") if isinstance(task_card.get("full_deconstruct"), dict) else {}
        if full:
            sections.append(("完整拆解结果", json.dumps(full, ensure_ascii=False, indent=2)[:12000]))
        missing_fields = "\n".join(f"- {item}" for item in task_card.get("missing_fields") or [] if str(item).strip())
        basis = f"- 置信度：{task_card.get('confidence', 0)}\n- 证据：{task_card.get('evidence', '')}\n- 说明：{task_card.get('reason', '')}"
        if missing_fields:
            basis = f"{basis}\n- LLM标记的信息缺口：\n{missing_fields}"
        sections.append(("LLM整理依据", basis))
        return sections

    def _recreation_task_card_failure(self, message: Message, task_card: dict[str, Any]) -> TaskResult:
        reason = str(task_card.get("reason") or "LLM 未生成可用再创作任务卡").strip()
        entry = self.archive_service.save_archive(
            message,
            "再创作任务卡待 LLM 生成",
            [
                ("原始内容", message.body),
                ("LLM任务卡结果", json.dumps(task_card, ensure_ascii=False, indent=2)),
                ("处理状态", "pending_manual\n本入口不再使用正则/关键词模板生成转化目标、可迁移点、建议产物或待补充信息。"),
            ],
            {
                "status": "pending_manual",
                "tags": ["再创作", "LLM任务卡失败"],
                "workflow": "recreation_task_card",
                "llm_task_card_status": "pending_manual",
                "llm_task_card_reason": reason,
            },
        )
        lines = [
            "再创作任务卡没有生成：LLM 未返回可用主体字段。",
            f"原因：{reason}",
        ]
        missing_fields = [str(item).strip() for item in task_card.get("missing_fields") or [] if str(item).strip()]
        if missing_fields:
            lines.append(f"缺失/待补字段：{', '.join(missing_fields[:8])}")
        lines.extend(
            [
                "已保留本地记录；不会生成任务卡主体。",
                f"本地路径：{entry.local_path}",
            ]
        )
        reply = "\n".join(lines)
        return TaskResult(ok=False, status="recreation_llm_pending_manual", reply=reply, task_id=entry.frontmatter["id"], local_path=entry.local_path)

    def _sync_recreation_entry_to_feishu(self, entry, message: Message, doc_name: str, sections: list[tuple[str, str]], short_title: str = "") -> dict[str, str]:
        try:
            entry_doc_name = self._recreation_entry_doc_name(entry.frontmatter.get("id", ""), message, sections, short_title)
            blocks = self._recreation_feishu_blocks(entry.local_path, message, sections, short_title)
            fs = self._sync_unified_creation_child_blocks(entry_doc_name, blocks)

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
        return f"拆解-再创｜{theme}｜{suffix}" if suffix else f"拆解-再创｜{theme}"

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
