from __future__ import annotations

from .tag_router_common import *


SOCIAL_METADATA_EXTRACTION_PROMPT = """你是 OpenClaw Social 的社交档案元数据抽取器。只输出合法 JSON，不要 Markdown，不要解释。

任务：从用户发来的社交/人脉档案材料中抽取 person、gender、relationship_category，用于调用 person_archive.py。

约束：
- 必须基于正文证据抽取，不要用正则模板猜字段。
- person 是用户要建档/更新档案的对象称呼或昵称，不要输出“对象”“她”“他”“这个”“截图”“聊天”等泛词。
- gender 只能是「男」「女」「未知」。用户没有明确指定性别时输出「女」；只有用户明确说男或未知时才输出对应值，不要因截图/头像/材料证据不足而输出「未知」。
- relationship_category 只能是「异性关系」「无性关系」或空字符串。职业合作、人脉、朋友、客户、校友、投资人、无性社交都归「无性关系」。普通【社交】建档在没有无性/人脉/职业/朋友等特殊说明时按默认女性对象输出「异性关系」。
- 如果当前入口 forced_category 非空，relationship_category 必须等于 forced_category，但 person/gender 仍要由 LLM 抽取。
- 只有 confidence 低于 0.65 或缺少 person 时才需要待确认；默认 gender=女、relationship_category=异性关系 是可继续归档的有效值，不要作为阻断缺口。

输出 JSON 字段固定为：
{
  "person": "称呼",
  "gender": "男|女|未知",
  "relationship_category": "异性关系|无性关系|",
  "confidence": 0.0,
  "missing_fields": ["..."],
  "evidence": "支持抽取的原文片段",
  "reason": "一句话说明判断依据"
}
"""

SOCIAL_ARCHIVE_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".heic", ".webp"}
SOCIAL_ARCHIVE_AUDIO_EXTS = {".m4a", ".mp3", ".wav", ".aac", ".flac", ".caf"}


class SocialArchiveMixin:
    def handle_社交(self, message: Message) -> TaskResult:
        return self._handle_person_archive_message(message, archive_kind="社交", forced_category="", skip_feishu=False)

    def handle_人脉(self, message: Message) -> TaskResult:
        return self._handle_person_archive_message(message, archive_kind="人脉", forced_category="无性关系", skip_feishu=True)

    def _handle_person_archive_message(
        self,
        message: Message,
        *,
        archive_kind: str,
        forced_category: str = "",
        skip_feishu: bool = False,
    ) -> TaskResult:
        metadata = self._extract_social_metadata_with_llm(message, archive_kind=archive_kind, forced_category=forced_category)
        if not metadata.get("ok"):
            entry = self.archive_service.save_archive(
                message,
                f"{archive_kind}档案待确认",
                [
                    ("原始内容", message.body),
                    ("LLM元数据抽取", json.dumps(metadata, ensure_ascii=False, indent=2)),
                    ("待补充信息", "缺少对象称呼，或 LLM 未能可靠抽取对象/性别/关系。请补一句：对象：称呼；性别：男/女/未知；关系：异性关系/无性关系"),
                ],
                {"status": "pending_person", "tags": [archive_kind, "人物档案"], "llm_metadata_status": metadata.get("status", "")},
            )
            reply = "\n".join(
                [
                    f"{archive_kind}档案待确认：LLM 未能可靠抽取对象/性别/关系。",
                    f"原因：{metadata.get('reason') or '缺少必要字段'}",
                    "请补一句：对象：称呼；性别：男/女/未知；关系：异性关系/无性关系",
                    f"暂存路径：{entry.local_path}",
                ]
            )
            return TaskResult(ok=False, status="pending_person", reply=reply, task_id=entry.frontmatter["id"], local_path=entry.local_path)

        person = str(metadata["person"])
        gender = str(metadata.get("gender") or "未知")
        relationship_category = str(metadata.get("relationship_category") or "")

        archive_result = self._append_social_person_archive(
            message=message,
            person=person,
            body=message.body,
            gender=gender,
            relationship_category=relationship_category,
        )
        final_category = relationship_category or self._extract_output_path(archive_result.get("output", ""), "关系分类：") or "自动判定"
        feishu_skipped = skip_feishu or self._should_skip_social_feishu(message.body, final_category)
        feishu_result = {} if feishu_skipped else self._sync_social_person_feishu_doc(person, message, archive_result)
        status = "archived" if archive_result["ok"] else "pending_manual"
        sections = [
            ("原始内容", message.body),
            ("person-profile-skill 输出", archive_result["output"] or archive_result["error"]),
        ]
        if feishu_skipped:
            sections.append(("飞书云文档同步", "不同步：无性关系/人脉档案默认仅本地与 Obsidian"))
        if feishu_result.get("doc") or feishu_result.get("warning"):
            sections.append(("飞书云文档同步", feishu_result.get("doc") or feishu_result.get("warning", "")))
        entry = self.archive_service.save_archive(
            message,
            f"{archive_kind}档案：{person}",
            sections,
            {
                "status": status,
                "tags": [archive_kind, "人物档案"],
                "person": person,
                "person_archive_path": archive_result.get("archive_path", ""),
                "obsidian_path": archive_result.get("obsidian_path", ""),
                "llm_person": person,
                "llm_gender": gender,
                "llm_relationship_category": relationship_category,
                "llm_metadata_confidence": metadata.get("confidence", 0),
                "llm_metadata_evidence": metadata.get("evidence", ""),
                "feishu_doc": feishu_result.get("doc", ""),
                "feishu_synced": bool(feishu_result.get("doc") and not feishu_result.get("warning")),
                "feishu_skipped": feishu_skipped,
            },
        )
        if archive_result["ok"]:
            analysis_summary = self._social_archive_reply_summary(message, archive_result)
            reply_lines = [
                f"{archive_kind}档案更新完成",
                f"- 对象：【{person}】",
                f"- 关系分类：{final_category}",
                f"- 本地交互档案：{archive_result.get('archive_path') or '未解析到'}",
            ]
            if analysis_summary:
                reply_lines = [
                    f"{archive_kind}档案更新完成",
                    "",
                    "本次图像/材料结论：",
                    analysis_summary,
                    "",
                    f"- 对象：【{person}】",
                    f"- 关系分类：{final_category}",
                    f"- 本地交互档案：{archive_result.get('archive_path') or '未解析到'}",
                ]
            if archive_result.get("obsidian_path"):
                reply_lines.append(f"- Obsidian：{archive_result['obsidian_path']}")
            else:
                reply_lines.append("- Obsidian：未同步或未解析到路径")
            if feishu_result.get("doc"):
                reply_lines.append(f"- 飞书云文档：{feishu_result['doc']}")
            elif feishu_result.get("warning"):
                reply_lines.append(f"- 飞书云文档：同步受限：{feishu_result['warning']}")
            elif feishu_skipped:
                reply_lines.append("- 飞书云文档：不同步（无性关系/人脉档案默认仅本地与 Obsidian）")
            reply_lines.append("- 写入模板：已按 `【是不是不Jessica】交互档案` 标准，分为历史交互记录与分析区")
            if archive_kind == "人脉":
                reply_lines.append("- 下一步：可继续补充微信截图、介绍人、职业需求、故事记忆点或下次跟进时间")
            else:
                reply_lines.append("- 下一步：可继续补充截图、录音转写或指定 `【理论-...】` 视角")
            reply_lines.append(f"- 路由记录：{entry.local_path}")
            reply = "\n".join(reply_lines)
            return TaskResult(ok=True, status=status, reply=reply, task_id=entry.frontmatter["id"], local_path=archive_result.get("archive_path") or entry.local_path, feishu_doc=feishu_result.get("doc", ""))

        reply = "\n".join(
            [
                f"{archive_kind}档案更新失败，已保留路由记录。",
                f"对象：【{person}】",
                f"路由记录：{entry.local_path}",
                f"错误：{archive_result['error']}",
            ]
        )
        return TaskResult(ok=False, status=status, reply=reply, task_id=entry.frontmatter["id"], local_path=entry.local_path)

    def _blocked_social_theory_tags(self, tag: str, body: str) -> list[str]:
        if tag == "社交":
            return []
        text = re.sub(r"https?://\S+", " ", body or "")
        theory_tags = {self._clean_theory_tag(match.group("tag")) for match in BRACKET_THEORY_RE.finditer(text)}
        return [theory_tag for theory_tag in SOCIAL_THEORY_TAGS if theory_tag in theory_tags]

    def _clean_theory_tag(self, value: str) -> str:
        tag = value.strip().strip("【】")
        for suffix in THEORY_TAG_SUFFIXES:
            if tag.endswith(suffix) and len(tag) > len(suffix):
                tag = tag[: -len(suffix)]
                break
        return tag.strip()

    def _extract_social_metadata_with_llm(self, message: Message, *, archive_kind: str, forced_category: str) -> dict[str, Any]:
        if not hasattr(self.content_flow_client, "_call_profile_provider_json"):
            return {"ok": False, "status": "pending_manual", "reason": "content_flow_client 缺少 LLM JSON 调用", "missing_fields": ["llm_result"]}
        user_content = json.dumps(
            {
                "entry_tag": message.entry_tag,
                "archive_kind": archive_kind,
                "forced_category": forced_category,
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
                SOCIAL_METADATA_EXTRACTION_PROMPT,
                user_content,
                "社交档案元数据 LLM 抽取",
            )
        except Exception as exc:
            return {"ok": False, "status": "pending_manual", "reason": f"LLM 抽取异常：{exc}", "missing_fields": ["llm_result"]}
        return self._normalize_social_metadata(result, forced_category=forced_category)

    def _normalize_social_metadata(self, result: dict[str, Any], *, forced_category: str) -> dict[str, Any]:
        if not isinstance(result, dict):
            return {"ok": False, "status": "pending_manual", "reason": "LLM 未返回对象", "missing_fields": ["llm_result"]}
        if result.get("status") not in {"done", "", None}:
            return {
                "ok": False,
                "status": str(result.get("status") or "pending_manual"),
                "reason": str(result.get("reason") or "LLM 抽取未完成"),
                "missing_fields": ["llm_result"],
            }
        confidence = self._social_float_confidence(result.get("confidence"))
        person = self._clean_social_person(str(result.get("person") or ""))
        gender = self._normalize_social_gender(str(result.get("gender") or ""))
        relationship_category = forced_category or self._normalize_social_relationship_category(str(result.get("relationship_category") or ""))
        missing_fields = [str(item).strip() for item in result.get("missing_fields") or [] if str(item).strip()]
        blocking_missing_fields = [item for item in missing_fields if item not in {"gender", "relationship_category"}]
        if not person:
            blocking_missing_fields.append("person")
        if not gender:
            blocking_missing_fields.append("gender")
        if confidence < 0.65:
            blocking_missing_fields.append("confidence")
        if blocking_missing_fields:
            return {
                "ok": False,
                "status": "pending_manual",
                "reason": str(result.get("reason") or "LLM 缺少必要字段或置信度不足"),
                "person": person,
                "gender": gender or "未知",
                "relationship_category": relationship_category,
                "confidence": confidence,
                "missing_fields": sorted(set(blocking_missing_fields)),
                "evidence": str(result.get("evidence") or "").strip(),
            }
        return {
            "ok": True,
            "status": "done",
            "person": person,
            "gender": gender,
            "relationship_category": relationship_category,
            "confidence": confidence,
            "evidence": str(result.get("evidence") or "").strip(),
            "reason": str(result.get("reason") or "").strip(),
            "provider": str(result.get("postprocess_provider") or ""),
            "model": str(result.get("postprocess_model") or ""),
        }

    @staticmethod
    def _social_float_confidence(value: Any) -> float:
        try:
            confidence = float(value)
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, min(1.0, confidence))

    @staticmethod
    def _normalize_social_gender(value: str) -> str:
        text = str(value or "").strip()
        if text in {"男", "女", "未知"}:
            return text
        if text in {"男性", "男生", "男的"}:
            return "男"
        if text in {"女性", "女生", "女的"}:
            return "女"
        if text in {"", "不明", "不确定", "unknown", "Unknown"}:
            return "未知"
        return ""

    @staticmethod
    def _normalize_social_relationship_category(value: str) -> str:
        text = str(value or "").strip()
        if text in {"异性关系", "无性关系", ""}:
            return text
        if text in {"人脉关系", "职业关系", "合作关系", "朋友关系", "同性关系", "微信人脉"}:
            return "无性关系"
        return ""

    def _extract_social_person(self, body: str) -> str:
        text = body.strip()
        patterns = [
            r"(?:对象|称呼|昵称|名字|姓名|person)\s*[：:]\s*【?([^】\s，,。；;\n]{1,32})】?",
            r"(?:对象|她|他)?(?:就叫|叫|命名为|名字是|称呼是)\s*【?([^】\s，,。；;\n]{1,32})】?",
            r"(?:给|为|帮|把)\s*【?([^】\s，,。；;\n]{1,32})】?\s*(?:建|建立|生成|创建|更新|补充|归档|做|整理).{0,12}(?:档案|记录)",
            r"^【([^】\s]{1,32})】",
            r"^([A-Za-z0-9_\-\u4e00-\u9fff]{1,32})[：:]\s*",
            r"^([A-Za-z0-9_\-\u4e00-\u9fff]{1,32})\s+.{0,20}(?:档案|归档|建档|截图|聊天)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if not match:
                continue
            person = self._clean_social_person(match.group(1))
            if person:
                return person
        return ""

    def _clean_social_person(self, value: str) -> str:
        person = value.strip().strip("【】").strip()
        person = re.sub(r"[：:，,。；;\s].*$", "", person)
        blocked = {
            "对象",
            "称呼",
            "昵称",
            "名字",
            "姓名",
            "女生",
            "男生",
            "她",
            "他",
            "这个",
            "那个",
            "档案",
            "截图",
            "聊天",
            *SOCIAL_THEORY_TAGS,
        }
        if not person or person in blocked:
            return ""
        if "/" in person or "\\" in person or person in {".", ".."}:
            return ""
        return person[:32]

    def _extract_social_gender(self, body: str) -> str:
        text = body.strip()
        if re.search(r"性别\s*[：:]?\s*(未知|不明)", text):
            return "未知"
        if re.search(r"(性别\s*[：:]?\s*)?(男|男性|男生|男的)", text):
            return "男"
        if re.search(r"(性别\s*[：:]?\s*)?(女|女性|女生|女的)", text):
            return "女"
        return "女"

    def _extract_social_relationship_category(self, body: str) -> str:
        if any(keyword in body for keyword in DEMOTE_TO_ASEXUAL_KEYWORDS):
            return "无性关系"
        if any(keyword in body for keyword in ["无性关系", "人脉关系", "职业关系", "合作关系", "朋友关系", "同性关系", "微信人脉", "【人脉】"]):
            return "无性关系"
        if "异性关系" in body:
            return "异性关系"
        return ""

    def _should_skip_social_feishu(self, body: str, relationship_category: str) -> bool:
        if relationship_category == "无性关系":
            return True
        network_keywords = ["【人脉】", "人脉", "微信备注", "职业关系", "合作关系", "校友", "介绍人", "客户", "投资人"]
        return any(keyword in body for keyword in network_keywords)

    def _append_social_person_archive(
        self,
        *,
        message: Message,
        person: str,
        body: str,
        gender: str,
        relationship_category: str,
    ) -> dict[str, Any]:
        social_root = Path("/home/ubuntu/openclaw-agents/social")
        script = social_root / "person-profile-skill" / "tools" / "person_archive.py"
        if not script.exists():
            return {"ok": False, "output": "", "error": f"person_archive.py 不存在：{script}"}

        tmp_dir = self.workspace_root / "tmp" / "social-profile"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = Path("")
        try:
            with tempfile.NamedTemporaryFile("w", suffix=".txt", prefix="social-", encoding="utf-8", dir=tmp_dir, delete=False) as fh:
                tmp_path = Path(fh.name)
                fh.write(body.strip() + "\n")

            title = self._social_archive_title(body)
            input_path = self._social_person_archive_input_path(message, tmp_path)
            cmd = [
                "/usr/bin/python3",
                str(script),
                "--person",
                person,
                "--gender",
                gender,
                "--self-gender",
                "男",
                "--title",
                title,
            ]
            if relationship_category:
                cmd.extend(["--relationship-category", relationship_category])
            cmd.append(str(input_path))
            proc = run_media_subprocess_with_watchdog(
                cmd,
                cwd=social_root,
                timeout=180,
                env=self._subprocess_env_with_context(message),
            )
            if proc.returncode == -9:
                return {"ok": False, "output": proc.stderr.strip(), "error": proc.stderr.strip() or "person_archive.py 超时"}
            output = "\n".join(part for part in [proc.stdout.strip(), proc.stderr.strip()] if part)
            archive_path = self._extract_output_path(output, "已追加到交互档案：")
            obsidian_path = self._extract_output_path(output, "已同步到 Obsidian：")
            syncthing_scan = self._extract_output_path(output, "Syncthing 扫描：")
            return {
                "ok": proc.returncode == 0,
                "output": output,
                "error": output if proc.returncode != 0 else "",
                "archive_path": archive_path,
                "obsidian_path": obsidian_path,
                "syncthing_scan": syncthing_scan,
                "input_path": str(input_path),
            }
        except Exception as exc:
            return {"ok": False, "output": "", "error": str(exc)}
        finally:
            if tmp_path:
                tmp_path.unlink(missing_ok=True)

    def _sync_social_person_feishu_doc(
        self,
        person: str,
        message: Message,
        archive_result: dict[str, Any],
    ) -> dict[str, str]:
        if not archive_result.get("ok"):
            return {}
        doc_name = f"【{person}】交互档案"
        content = self._social_feishu_content(person, message, archive_result)
        try:
            fs = self.feishu_service.append_entry(doc_name, content)
            self._update_social_profile_cloud_doc(person, doc_name, fs)
            return {"doc": fs.get("doc", ""), "document_id": fs.get("document_id", "")}
        except Exception as exc:
            return {"warning": f"飞书云文档同步失败：{exc}"}

    def _social_feishu_content(self, person: str, message: Message, archive_result: dict[str, Any]) -> str:
        lines = [
            f"## {format_display_time(message.created_at)}｜社交档案更新",
            "",
            f"- 对象：【{person}】",
            f"- 本地交互档案：{archive_result.get('archive_path', '')}",
            f"- Obsidian：{archive_result.get('obsidian_path', '')}",
            f"- 来源：{message.source.upper()}",
            "",
            "### 本次材料",
            message.body.strip(),
        ]
        return "\n".join(lines).strip()

    def _update_social_profile_cloud_doc(self, person: str, doc_name: str, fs: dict[str, str]) -> None:
        doc_url = fs.get("doc", "")
        document_id = fs.get("document_id", "")
        if not doc_url and not document_id:
            return
        profile_path = Path("/home/ubuntu/openclaw-agents/social") / "person-profile-skill" / "data" / "persons" / person / "profile.json"
        if not profile_path.exists():
            return
        try:
            profile = json.loads(profile_path.read_text(encoding="utf-8"))
        except Exception:
            return
        profile["cloud_doc"] = {
            "provider": "feishu",
            "title": doc_name,
            "doc_token": document_id,
            "url": doc_url,
            "sync_policy": "one_person_archive_to_one_cloud_doc",
            "last_synced_at": datetime.now().isoformat(timespec="seconds"),
        }
        profile_path.write_text(json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def _social_archive_title(self, body: str) -> str:
        first_line = re.sub(r"\s+", " ", body.strip()).strip()
        first_line = first_line[:40] if first_line else "社交补充"
        return f"社交补充：{first_line}"

    def _social_person_archive_input_path(self, message: Message, text_path: Path) -> Path:
        for path in self._social_downloaded_media_paths(message):
            if path.suffix.lower() in SOCIAL_ARCHIVE_IMAGE_EXTS or path.suffix.lower() in SOCIAL_ARCHIVE_AUDIO_EXTS:
                return path
        return text_path

    def _social_downloaded_media_paths(self, message: Message) -> list[Path]:
        metadata = message.metadata or {}
        candidates: list[Any] = []
        downloaded_paths = metadata.get("downloaded_paths")
        if isinstance(downloaded_paths, list):
            candidates.extend(downloaded_paths)
        media_items = metadata.get("media")
        if isinstance(media_items, list):
            for item in media_items:
                if isinstance(item, dict):
                    candidates.append(item.get("path"))
        paths: list[Path] = []
        seen: set[Path] = set()
        for value in candidates:
            if not str(value or "").strip():
                continue
            try:
                path = Path(str(value)).expanduser().resolve()
            except OSError:
                continue
            if path in seen or not path.is_file():
                continue
            if not self._is_allowed_uploaded_media_path(path):
                continue
            seen.add(path)
            paths.append(path)
        return paths

    def _is_allowed_uploaded_media_path(self, path: Path) -> bool:
        roots = [root.expanduser().resolve() for root in UPLOADED_MEDIA_ROOTS]
        return any(path == root or root in path.parents for root in roots)

    def _social_archive_reply_summary(self, message: Message, archive_result: dict[str, Any]) -> str:
        archive_path = Path(str(archive_result.get("archive_path") or ""))
        if not archive_path.exists():
            return ""
        input_path = Path(str(archive_result.get("input_path") or ""))
        has_media_input = input_path.suffix.lower() in SOCIAL_ARCHIVE_IMAGE_EXTS or input_path.suffix.lower() in SOCIAL_ARCHIVE_AUDIO_EXTS
        if not has_media_input and not self._social_message_requests_analysis(message.body):
            return ""
        try:
            text = archive_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return ""
        latest = self._latest_social_record_block(text)
        material = self._extract_latest_material_summary(latest)
        if not material:
            return "已归档，但本次没有提取到可回传的图像/材料结论；请重发原图或查看路由记录。"
        return material[:1200].rstrip()

    def _latest_social_record_block(self, archive_text: str) -> str:
        matches = list(re.finditer(r"^## \d{3}｜", archive_text, flags=re.MULTILINE))
        if not matches:
            return archive_text
        start = matches[-1].start()
        next_match = re.search(r"^## \d{3}｜", archive_text[start + 1 :], flags=re.MULTILINE)
        end = start + 1 + next_match.start() if next_match else len(archive_text)
        return archive_text[start:end]

    def _extract_latest_material_summary(self, block: str) -> str:
        marker = "> 待归入本表的提纯材料如下。后续编辑时应拆成逐行聊天记录、事实摘要和分析证据；原始音频/截图/图片不进入档案。"
        if marker in block:
            content = block.split(marker, 1)[1]
            content = content.split("| 日期/时间 |", 1)[0].strip()
            if content and not self._looks_like_social_instruction_stub(content):
                return content
        fact_match = re.search(r"### 5\. 本次事实摘要\s*(?P<body>.*?)(?:\n### 6\.|\Z)", block, flags=re.S)
        if fact_match:
            content = fact_match.group("body").strip()
            if content and "主要话题：\n-" not in content:
                return content
        return ""

    def _looks_like_social_instruction_stub(self, content: str) -> bool:
        instruction_markers = (
            "这是一组连续上传的社交素材",
            "等待池已结束",
            "处理方式：先给整批素材建立 manifest",
            "人物照片观察必须使用 social workspace",
        )
        return any(marker in content for marker in instruction_markers)

    def _social_message_requests_analysis(self, body: str) -> bool:
        return any(keyword in body for keyword in ("说明什么", "怎么看", "分析", "结论", "评价", "判断"))
