from __future__ import annotations

from .tag_router_common import *
from ..services.media_text_cleaner import MEDIA_TEXT_CLEANER


class TranscriptionFormattersMixin:
    def _postprocess_artifact_lines(self, formatted: dict[str, Any]) -> list[str]:
        artifacts = formatted.get("postprocess_artifacts")
        if not isinstance(artifacts, dict) or not artifacts:
            return []
        lines = []
        if artifacts.get("dir"):
            lines.append(f"- 后处理产物目录：{artifacts['dir']}")
        for label, key in (
            ("全局整理草稿", "global_note_draft"),
            ("一致性检查", "consistency_check"),
        ):
            value = str(artifacts.get(key) or "").strip()
            if value:
                lines.append(f"- {label}：{value}")
        for label, key in (
            ("分片产物", "chunks"),
            ("单附件合并产物", "attachments"),
            ("中间合并产物", "groups"),
        ):
            values = artifacts.get(key)
            if isinstance(values, list) and values:
                lines.append(f"- {label}：{len(values)} 个")
        return lines

    def _format_consistency_check(self, value: Any) -> str:
        if not isinstance(value, dict) or not value:
            return ""
        approved_value = value.get("approved")
        approved = approved_value is True or str(approved_value).strip().lower() == "true"
        lines = [f"- 通过：{'是' if approved else '否'}"]
        blocking = value.get("blocking_issues")
        if isinstance(blocking, list) and blocking:
            lines.append("- 阻断问题：")
            lines.extend(f"  - {str(item).strip()}" for item in blocking if str(item).strip())
        warnings = value.get("warnings")
        if isinstance(warnings, list) and warnings:
            lines.append("- 警告：")
            lines.extend(f"  - {str(item).strip()}" for item in warnings if str(item).strip())
        notes = str(value.get("revision_notes") or "").strip()
        if notes:
            lines.append(f"- 修订说明：{notes}")
        return "\n".join(lines)

    def _format_dialogue_transcription(self, transcript: str, source_hint: str = "", artifact_dir: str | Path | None = None) -> dict[str, Any]:
        result = self.content_flow_client.summarize_dialogue_transcript(transcript, source_hint=source_hint, artifact_dir=artifact_dir)
        if result.get("status") == "done":
            title = self._clean_meeting_topic_candidate(result.get("title", ""))
            meeting_info_data = result.get("meeting_info") if isinstance(result.get("meeting_info"), dict) else {}
            conclusion_summary_data = (
                result.get("conclusion_summary") if isinstance(result.get("conclusion_summary"), dict) else {}
            )
            meeting_info = self._format_meeting_info(meeting_info_data)
            conclusion_summary = self._format_conclusion_summary(conclusion_summary_data)
            decision_list = self._format_decision_list(result.get("decision_list"))
            topic_cards = self._format_topic_cards(result.get("topic_cards"))
            pending_decisions = self._format_pending_decisions(result.get("pending_decisions"))
            validation_hypotheses = self._format_validation_hypotheses(result.get("validation_hypotheses"))
            action_items = self._format_action_items(result.get("action_items"))
            risks_and_constraints = self._format_risks_and_constraints(result.get("risks_and_constraints"))
            next_meeting = self._format_next_meeting(result.get("next_meeting"))
            topical_attachments = self._format_topical_attachments(result.get("topical_attachments"))
            detail_fidelity_appendix = self._format_detail_fidelity_appendix(
                result.get("detail_coverage"),
                result.get("sensitive_summary"),
            )
            conclusion_section = self._format_conclusion_section(
                conclusion_summary,
                pending_decisions,
                validation_hypotheses,
                risks_and_constraints,
            )
            speaker_notes = self._format_speaker_notes(result.get("speaker_notes"))
            labeled_transcript = self._format_labeled_transcript(result.get("labeled_transcript"))
            archive_macro_summary = self._format_archive_macro_summary(result.get("archive_macro_summary"))
            archive_summary_bullets = self._format_archive_summary_bullets(result.get("archive_summary_bullets"))
            validation_issue = self._transcription_postprocess_validation_issue(
                result,
                meeting_info,
                conclusion_summary,
                topic_cards,
                next_meeting,
                speaker_notes,
                labeled_transcript,
                archive_macro_summary,
                archive_summary_bullets,
            )
            if not validation_issue:
                return {
                    "status": "done",
                    "reason": "",
                    "title": title,
                    "meeting_info": meeting_info,
                    "meeting_info_data": meeting_info_data,
                    "conclusion_summary": conclusion_summary,
                    "conclusion_summary_data": conclusion_summary_data,
                    "conclusion_section": conclusion_section,
                    "decision_list": decision_list,
                    "topic_cards": topic_cards,
                    "pending_decisions": pending_decisions,
                    "validation_hypotheses": validation_hypotheses,
                    "action_items": action_items,
                    "risks_and_constraints": risks_and_constraints,
                    "next_meeting": next_meeting,
                    "topical_attachments": topical_attachments,
                    "topical_attachments_data": (
                        result.get("topical_attachments")
                        if isinstance(result.get("topical_attachments"), list)
                        else []
                    ),
                    "detail_fidelity_appendix": detail_fidelity_appendix,
                    "speaker_notes": speaker_notes,
                    "labeled_transcript": labeled_transcript,
                    "archive_macro_summary": archive_macro_summary,
                    "archive_summary_bullets": archive_summary_bullets,
                    "postprocess_provider": result.get("postprocess_provider", ""),
                    "postprocess_model": result.get("postprocess_model", ""),
                    "postprocess_pipeline": result.get("postprocess_pipeline", ""),
                    "chunk_count": result.get("chunk_count", 0),
                    "attachment_count": result.get("attachment_count", 0),
                    "detail_coverage_count": len(result.get("detail_coverage") or []),
                    "consistency_check": result.get("consistency_check", {}),
                    "postprocess_artifacts": result.get("postprocess_artifacts", {}),
                }
            result = {**result, "reason": validation_issue}

        return {
            "status": "pending_manual",
            "reason": str(result.get("reason") or "摘要/说话人整理结果不完整"),
            "title": "",
            "meeting_info": "",
            "meeting_info_data": {},
            "conclusion_summary": "",
            "conclusion_summary_data": {},
            "conclusion_section": "",
            "decision_list": "",
            "topic_cards": "",
            "pending_decisions": "",
            "validation_hypotheses": "",
            "action_items": "",
            "risks_and_constraints": "",
            "next_meeting": "",
            "topical_attachments": "",
            "topical_attachments_data": [],
            "detail_fidelity_appendix": "",
            "speaker_notes": "",
            "labeled_transcript": "",
            "archive_macro_summary": "",
            "archive_summary_bullets": [],
            "postprocess_provider": result.get("postprocess_provider", ""),
            "postprocess_model": result.get("postprocess_model", ""),
            "postprocess_pipeline": result.get("postprocess_pipeline", ""),
            "chunk_count": result.get("chunk_count", 0),
            "attachment_count": result.get("attachment_count", 0),
            "detail_coverage_count": 0,
            "consistency_check": result.get("consistency_check", {}),
            "postprocess_artifacts": result.get("postprocess_artifacts", {}),
        }

    def _transcription_postprocess_succeeded(self, formatted: dict[str, Any]) -> bool:
        return formatted.get("status") == "done"

    def _transcription_postprocess_validation_issue(
        self,
        result: dict[str, Any],
        meeting_info: str,
        conclusion_summary: str,
        topic_cards: str,
        next_meeting: str,
        speaker_notes: str,
        labeled_transcript: str,
        archive_macro_summary: str,
        archive_summary_bullets: list[str],
    ) -> str:
        if not meeting_info:
            return "后处理结果缺少会议基本信息"
        if not conclusion_summary:
            return "后处理结果缺少管理层结论摘要"
        if not topic_cards:
            return "后处理结果缺少议题分析卡"
        if not next_meeting:
            return "后处理结果缺少重议条件和下次会议信息"
        if not speaker_notes:
            return "后处理结果缺少对话人说明"
        if not labeled_transcript:
            return "后处理结果缺少说话人标注逐字稿"
        if not archive_macro_summary:
            return "后处理结果缺少周记宏观总结"
        if not archive_summary_bullets:
            return "后处理结果缺少周记分点摘要"
        if len(archive_summary_bullets) > 5:
            return "后处理结果周记分点摘要超过 5 条"
        if result.get("postprocess_pipeline") == "chunked-map-reduce-final":
            consistency = result.get("consistency_check", {})
            approved_value = consistency.get("approved") if isinstance(consistency, dict) else None
            approved = approved_value is True or str(approved_value).strip().lower() == "true"
            if not approved:
                issues = consistency.get("blocking_issues") if isinstance(consistency, dict) else []
                if isinstance(issues, list) and issues:
                    return "一致性检查未通过：" + "；".join(str(item) for item in issues[:5])
                return "一致性检查未通过或缺失"
        return ""

    def _format_meeting_info(self, value: dict[str, Any]) -> str:
        fields = (
            ("会议名称", "meeting_name"),
            ("会议目标", "meeting_goal"),
            ("会议时间", "meeting_time"),
            ("参会人员", "participants"),
            ("主持人", "facilitator"),
            ("纪要负责人", "minutes_owner"),
            ("关联项目", "related_project"),
            ("关联文档", "related_documents"),
            ("纪要版本", "version"),
        )
        return "\n".join(f"- {label}：{self._transcription_value_text(value.get(key))}" for label, key in fields)

    def _format_conclusion_summary(self, value: dict[str, Any]) -> str:
        lines = [
            "### 1.1 总体判断",
            self._transcription_value_text(value.get("overall_judgment")),
            "",
            "### 1.2 关键影响",
        ]
        implications = value.get("key_implications") if isinstance(value.get("key_implications"), list) else []
        if not implications:
            lines.append("- 暂无需要单列的跨议题影响。")
        for item in implications:
            if not isinstance(item, dict):
                continue
            text = self._transcription_value_text(item.get("item"))
            rationale = self._transcription_value_text(item.get("rationale"), empty="")
            impact = self._transcription_value_text(item.get("implications"), empty="")
            related_ids = self._transcription_value_text(item.get("related_ids"), empty="")
            lines.append(f"- {text}")
            if rationale:
                lines.append(f"  - 依据：{rationale}")
            if impact:
                lines.append(f"  - 影响：{impact}")
            if related_ids:
                lines.append(f"  - 关联记录：{related_ids}")
        return "\n".join(lines).strip()

    @staticmethod
    def _format_conclusion_section(
        conclusion_summary: str,
        pending_decisions: str,
        validation_hypotheses: str,
        risks_and_constraints: str,
    ) -> str:
        return "\n\n".join(
            [
                conclusion_summary,
                "### 1.3 开放问题与待拍板事项\n" + pending_decisions,
                "### 1.4 验证假设\n" + validation_hypotheses,
                "### 1.5 风险与约束\n" + risks_and_constraints,
            ]
        ).strip()

    def _format_decision_list(self, value: Any) -> str:
        lines: list[str] = []
        for index, item in enumerate(value if isinstance(value, list) else [], start=1):
            if not isinstance(item, dict):
                continue
            decision_id = self._transcription_value_text(item.get("id"), empty=f"D-{index:02d}")
            topic = self._transcription_value_text(item.get("topic"), empty=f"决策 {index}")
            lines.extend(
                [
                    f"### {decision_id} {topic}",
                    f"- 决策结果：{self._transcription_value_text(item.get('decision'))}",
                    f"- 状态：{self._transcription_status_label(item.get('status'))}",
                    f"- 决策依据：{self._transcription_value_text(item.get('rationale'))}",
                    f"- 适用范围：{self._transcription_value_text(item.get('scope'))}",
                    f"- 复审条件：{self._transcription_value_text(item.get('review_condition'))}",
                    "",
                ]
            )
        return "\n".join(lines).strip() or "暂无正式决策记录。"

    def _format_topic_cards(self, value: Any) -> str:
        lines: list[str] = []
        for index, item in enumerate(value if isinstance(value, list) else [], start=1):
            if not isinstance(item, dict):
                continue
            topic_id = self._transcription_value_text(item.get("id"), empty=f"T-{index:02d}")
            topic = self._transcription_value_text(item.get("topic"), empty=f"议题 {index}")
            lines.extend(
                [
                    f"#### {topic_id} {topic}",
                    "##### 1. 当前事实",
                    self._markdown_bullets(item.get("current_facts"), "未从来源识别明确事实。"),
                    "",
                    "##### 2. 核心问题",
                    self._transcription_value_text(item.get("core_question")),
                    "",
                    "##### 3. 会议中讨论的方案",
                    self._format_topic_options(item.get("options")),
                    "",
                    "##### 4. 会议结论",
                    f"- 状态：{self._transcription_status_label(item.get('conclusion_status'))}",
                    f"- 结论：{self._transcription_value_text(item.get('conclusion'))}",
                    "",
                    "##### 5. 仍未解决的问题",
                    self._markdown_bullets(item.get("unresolved_questions"), "暂无。"),
                    "",
                    "##### 6. 下一步",
                    self._transcription_value_text(item.get("next_step")),
                    "",
                ]
            )
        return "\n".join(lines).strip()

    def _format_topic_options(self, value: Any) -> str:
        lines: list[str] = []
        for item in value if isinstance(value, list) else []:
            if isinstance(item, dict):
                option = self._transcription_value_text(item.get("option"))
                assessment = self._transcription_value_text(item.get("assessment"), empty="")
                lines.append(f"- {option}" + (f"：{assessment}" if assessment else ""))
            else:
                lines.append(f"- {self._transcription_value_text(item)}")
        return "\n".join(lines) or "- 暂无明确候选方案。"

    def _format_pending_decisions(self, value: Any) -> str:
        rows = []
        for item in value if isinstance(value, list) else []:
            if isinstance(item, dict):
                rows.append([item.get("id"), item.get("question"), item.get("options"), item.get("decision_owner"), item.get("deadline")])
        return self._markdown_table(
            ["ID", "问题", "可选方案", "决策人", "最晚时间"],
            rows,
            empty_label="暂无待拍板问题。",
        )

    def _format_validation_hypotheses(self, value: Any) -> str:
        rows = []
        for item in value if isinstance(value, list) else []:
            if isinstance(item, dict):
                rows.append(
                    [
                        item.get("id"),
                        item.get("hypothesis"),
                        item.get("validation_method"),
                        item.get("metrics"),
                        item.get("pass_criteria"),
                        item.get("owner"),
                    ]
                )
        return self._markdown_table(
            ["ID", "假设", "验证方式", "指标", "通过标准", "负责人"],
            rows,
            empty_label="暂无待验证假设。",
        )

    def _format_action_items(self, value: Any) -> str:
        rows = []
        for item in value if isinstance(value, list) else []:
            if isinstance(item, dict):
                rows.append(
                    [
                        item.get("id"),
                        item.get("action"),
                        item.get("assignee"),
                        item.get("deliverable"),
                        item.get("acceptance_criteria"),
                        item.get("deadline"),
                        item.get("dependencies"),
                    ]
                )
        return self._markdown_table(
            ["ID", "行动项", "负责人", "交付物", "验收标准", "截止时间", "依赖"],
            rows,
            empty_label="暂无明确行动项。",
        )

    def _format_risks_and_constraints(self, value: Any) -> str:
        rows = []
        for item in value if isinstance(value, list) else []:
            if isinstance(item, dict):
                rows.append([item.get("risk"), item.get("impact"), item.get("mitigation")])
        return self._markdown_table(["风险", "当前影响", "应对措施"], rows, empty_label="暂无明确风险与约束。")

    def _format_next_meeting(self, value: Any) -> str:
        data = value if isinstance(value, dict) else {}
        return "\n".join(
            [
                "### 4.1 召开条件",
                self._markdown_bullets(data.get("trigger_conditions"), "未指定。"),
                "",
                "### 4.2 需要准备的材料",
                self._markdown_bullets(data.get("required_materials"), "未指定。"),
                "",
                "### 4.3 需要拍板的问题",
                self._markdown_bullets(data.get("decisions_needed"), "暂无。"),
            ]
        )

    def _format_topical_attachments(self, value: Any) -> str:
        items = [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []
        if not items:
            return ""
        lines = ["本节为会议讨论后的结构化整理，用于后续方案设计；除明确标为已决策的内容外，不代表已经形成正式决策。"]
        for index, item in enumerate(items, start=1):
            attachment_id = self._transcription_value_text(item.get("id"), empty=f"附件 {index}")
            title = self._transcription_value_text(item.get("title"), empty=f"专题 {index}")
            lines.extend(
                [
                    "",
                    f"### {attachment_id}：{title}",
                    f"- 状态：{self._transcription_value_text(item.get('status_note'))}",
                    f"- 摘要：{self._transcription_value_text(item.get('summary'))}",
                    self._markdown_bullets(item.get("details"), "暂无更多细节。"),
                ]
            )
        return "\n".join(lines).strip()

    def _format_detail_fidelity_appendix(self, detail_coverage: Any, sensitive_summary: Any) -> str:
        lines = [
            "> visibility=restricted | public_use=forbidden",
            "> 本附录保留来源中全部非重复业务细节；敏感性只决定访问和公开权限，不用于删除或概括内容。",
            "",
            "### 5.1 来源业务细节",
        ]
        details = [item for item in detail_coverage if isinstance(item, dict)] if isinstance(detail_coverage, list) else []
        if not details:
            lines.append("- 本次没有额外的逐条业务细节记录。")
        for index, item in enumerate(details, start=1):
            detail = self._transcription_value_text(item.get("detail"), empty="未记录细节正文")
            theme = self._transcription_value_text(item.get("theme"), empty="未分类")
            source = self._format_source_range(item.get("source_range"))
            evidence_hash = self._transcription_value_text(item.get("evidence_hash"), empty="")
            lines.extend(["", f"#### 细节 {index}：{theme}", detail])
            metadata = []
            if source:
                metadata.append(f"来源：{source}")
            if evidence_hash:
                metadata.append(f"证据哈希：{evidence_hash}")
            permissions = self._transcription_permission_labels(item)
            if permissions:
                metadata.extend(permissions)
            extra_fields = self._transcription_business_fields(
                item,
                excluded={"detail", "theme", "source_range", "evidence_hash"},
            )
            if extra_fields:
                metadata.append(f"补充信息：{self._transcription_business_value_text(extra_fields)}")
            lines.extend(f"- {entry}" for entry in metadata)

        lines.extend(["", "### 5.2 敏感性、核验与公开权限"])
        sensitive_items = self._normalize_transcription_sensitive_items(sensitive_summary)
        if not sensitive_items:
            lines.append("- 未单列敏感标记；本附录整体仍按受限内容处理，禁止公开使用。")
        for index, item in enumerate(sensitive_items, start=1):
            detail_fields = self._transcription_business_fields(
                item,
                excluded={"source_range", "evidence_hash"},
            )
            detail = self._transcription_business_value_text(detail_fields, empty="未记录敏感细节正文")
            lines.extend(["", f"#### 敏感细节 {index}", detail])
            permissions = self._transcription_permission_labels(item, restricted_defaults=True)
            lines.extend(f"- {entry}" for entry in permissions)
            evidence_hash = self._transcription_value_text(item.get("evidence_hash"), empty="")
            if evidence_hash:
                lines.append(f"- 证据哈希：{evidence_hash}")
        return "\n".join(lines).strip()

    @staticmethod
    def _normalize_transcription_sensitive_items(value: Any) -> list[dict[str, Any]]:
        if isinstance(value, list):
            return [item if isinstance(item, dict) else {"detail": str(item)} for item in value if str(item).strip()]
        if isinstance(value, dict):
            nested = value.get("items")
            if isinstance(nested, list):
                items = [item if isinstance(item, dict) else {"detail": str(item)} for item in nested if str(item).strip()]
                remaining = {key: item for key, item in value.items() if key != "items"}
                if remaining:
                    items.append(remaining)
                return items
            return [value] if value else []
        text = str(value or "").strip()
        return [{"detail": text}] if text else []

    def _transcription_permission_labels(
        self,
        item: dict[str, Any],
        *,
        restricted_defaults: bool = False,
    ) -> list[str]:
        visibility = str(item.get("visibility") or ("restricted" if restricted_defaults else "")).strip()
        verification = str(item.get("verification_status") or ("unverified" if restricted_defaults else "")).strip()
        public_use = str(item.get("public_use") or ("forbidden" if restricted_defaults else "")).strip()
        labels = []
        if visibility:
            labels.append(
                "可见范围：" + {"restricted": "受限", "private": "私密", "public": "公开"}.get(visibility, visibility)
            )
        if verification:
            labels.append(
                "核验状态：" + {"unverified": "未核验", "verified": "已核验"}.get(verification, verification)
            )
        if public_use:
            labels.append(
                "公开使用：" + {"forbidden": "禁止", "allowed": "允许"}.get(public_use, public_use)
            )
        return labels

    @staticmethod
    def _transcription_business_fields(item: dict[str, Any], *, excluded: set[str]) -> dict[str, Any]:
        metadata_fields = {
            "visibility",
            "verification_status",
            "public_use",
            "handling",
        }
        return {
            key: value
            for key, value in item.items()
            if key not in excluded and key not in metadata_fields and value not in (None, "", [], {})
        }

    def _transcription_business_value_text(self, value: Any, *, empty: str = "未指定") -> str:
        if isinstance(value, dict):
            parts = [
                f"{key}：{self._transcription_business_value_text(item, empty='')}"
                for key, item in value.items()
            ]
            return "；".join(part for part in parts if not part.endswith("：")) or empty
        if isinstance(value, list):
            parts = [self._transcription_business_value_text(item, empty="") for item in value]
            return "；".join(part for part in parts if part) or empty
        return self._transcription_value_text(value, empty=empty)

    def _markdown_table(self, headers: list[str], rows: list[list[Any]], *, empty_label: str) -> str:
        if not rows:
            return empty_label
        header = "| " + " | ".join(headers) + " |"
        separator = "|" + "|".join("---" for _ in headers) + "|"
        body = ["| " + " | ".join(self._markdown_cell(cell) for cell in row) + " |" for row in rows]
        return "\n".join([header, separator, *body])

    def _markdown_cell(self, value: Any) -> str:
        return self._transcription_value_text(value).replace("|", "\\|").replace("\n", " / ")

    def _markdown_bullets(self, value: Any, empty_label: str) -> str:
        items = value if isinstance(value, list) else ([value] if self._transcription_value_text(value, empty="") else [])
        rendered = [self._transcription_value_text(item, empty="") for item in items]
        rendered = [item for item in rendered if item]
        return "\n".join(f"- {item}" for item in rendered) or f"- {empty_label}"

    def _transcription_value_text(self, value: Any, *, empty: str = "未指定") -> str:
        if isinstance(value, list):
            parts = [self._transcription_value_text(item, empty="") for item in value]
            return "；".join(part for part in parts if part) or empty
        if isinstance(value, dict):
            if value.get("option"):
                option = self._transcription_value_text(value.get("option"), empty="")
                assessment = self._transcription_value_text(value.get("assessment"), empty="")
                return option + (f"：{assessment}" if assessment else "")
            source = self._format_source_range(value)
            if source:
                return source
            parts = [f"{key}：{self._transcription_value_text(item, empty='')}" for key, item in value.items()]
            return "；".join(part for part in parts if not part.endswith("：")) or empty
        text = str(value or "").strip()
        return re.sub(r"\s+", " ", text) if text else empty

    @staticmethod
    def _transcription_status_label(value: Any) -> str:
        return {
            "decided": "已决策",
            "tentative_direction": "暂定方向",
            "pending_validation": "待验证",
            "pending_decision": "待拍板",
        }.get(str(value or "").strip(), str(value or "未指定").strip())

    def _format_archive_macro_summary(self, value: Any) -> str:
        text = str(value or "").strip()
        text = re.sub(r"\s+", " ", text).strip()
        return text[:500]

    def _format_archive_summary_bullets(self, value: Any) -> list[str]:
        if isinstance(value, str):
            candidates = value.splitlines()
        elif isinstance(value, list):
            candidates = [str(item) for item in value]
        else:
            candidates = []
        bullets: list[str] = []
        for item in candidates:
            text = re.sub(r"^\s*[-*•\d.、]+\s*", "", str(item or "")).strip()
            text = re.sub(r"\s+", " ", text).strip()
            if text:
                bullets.append(text[:500])
            if len(bullets) >= 5:
                break
        return bullets

    def _format_source_range(self, value: Any) -> str:
        if isinstance(value, dict):
            parts = [
                str(value.get("source_audio") or "").strip(),
                str(value.get("chunk_id") or "").strip(),
            ]
            start = value.get("char_start")
            end = value.get("char_end")
            if start is not None and end is not None:
                parts.append(f"{start}-{end}")
            return "/".join(part for part in parts if part)
        if isinstance(value, list):
            return "；".join(self._format_source_range(item) or str(item).strip() for item in value if item)
        return str(value or "").strip()

    def _format_speaker_notes(self, value: Any) -> str:
        if isinstance(value, list):
            lines: list[str] = []
            for item in value:
                if isinstance(item, dict):
                    speaker = str(item.get("display_name") or item.get("speaker_key") or "未区分说话人").strip()
                    role = str(item.get("meeting_role") or "未从来源识别").strip()
                    evidence = str(item.get("identity_evidence") or "未从来源识别").strip()
                    confidence = str(item.get("confidence") or "未从来源识别").strip()
                    lines.append(f"- {speaker}｜角色：{role}｜依据：{evidence}｜置信度：{confidence}")
                else:
                    text = str(item).strip()
                    if text:
                        lines.append(f"- {text.lstrip('- ').strip()}")
            return "\n".join(lines)
        if isinstance(value, dict):
            return "\n".join(f"- {str(key).strip()}：{str(val).strip()}" for key, val in value.items() if str(val).strip())
        return str(value or "").strip()

    def _format_labeled_transcript(self, value: Any) -> str:
        if isinstance(value, list):
            lines: list[str] = []
            for item in value:
                if not isinstance(item, dict):
                    continue
                speaker = str(item.get("speaker") or "未区分说话人").strip()
                role = str(item.get("role") or "未从来源识别").strip()
                text = self._clean_labeled_transcript_text(item.get("text") or "")
                if text:
                    label = speaker if role in {"", "未从来源识别"} else f"{speaker}（{role}）"
                    lines.append(f"{label}：{text}")
            return "\n".join(lines)
        return ""

    def _clean_labeled_transcript_text(self, value: Any) -> str:
        return MEDIA_TEXT_CLEANER.clean_spoken_line(value)

    def _clean_transcript_for_postprocess(self, transcript: str) -> str:
        return MEDIA_TEXT_CLEANER.clean_transcript_for_copy(transcript)
