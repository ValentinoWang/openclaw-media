from __future__ import annotations

from .tag_router_common import *


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
        person = self._extract_social_person(message.body)
        gender = self._extract_social_gender(message.body)
        relationship_category = forced_category or self._extract_social_relationship_category(message.body)
        if not person:
            entry = self.archive_service.save_archive(
                message,
                f"{archive_kind}档案待确认",
                [
                    ("原始内容", message.body),
                    ("待补充信息", "缺少对象称呼。请补一句：对象：称呼"),
                ],
                {"status": "pending_person", "tags": [archive_kind, "人物档案"]},
            )
            reply = "\n".join(
                [
                    f"{archive_kind}档案待确认：缺少对象称呼。",
                    "请补一句：对象：称呼",
                    f"暂存路径：{entry.local_path}",
                ]
            )
            return TaskResult(ok=False, status="pending_person", reply=reply, task_id=entry.frontmatter["id"], local_path=entry.local_path)

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
                "feishu_doc": feishu_result.get("doc", ""),
                "feishu_synced": bool(feishu_result.get("doc") and not feishu_result.get("warning")),
                "feishu_skipped": feishu_skipped,
            },
        )
        if archive_result["ok"]:
            reply_lines = [
                f"{archive_kind}档案更新完成",
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
            cmd.append(str(tmp_path))
            proc = subprocess.run(
                cmd,
                cwd=social_root,
                text=True,
                capture_output=True,
                timeout=180,
                env=self._subprocess_env_with_context(message),
            )
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
            }
        except subprocess.TimeoutExpired as exc:
            return {"ok": False, "output": "", "error": f"person_archive.py 超时：{exc}"}
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
