from __future__ import annotations

import json
import os
import re
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

import openclaw_app.services.content_flow_client as content_flow_client_module
import openclaw_app.router.transcription_storage as transcription_storage_module
from common.llm_settings import LLMProviderSettings
from openclaw_app.router.content_os_bridge import ContentOSBridgeMixin
from openclaw_app.router.content_os_utils import ContentOSUtilsMixin
from openclaw_app.services.completion_guard import CompletionGuard
from openclaw_app.services.content_flow_client import ContentFlowClient
from openclaw_app.models.message import Message
from openclaw_app.router.media_creation import MediaCreationMixin
from openclaw_app.router.media_knowledge_fields import MediaKnowledgeFieldsMixin
from openclaw_app.router.content_os_renderers import ContentOSRenderersMixin
from openclaw_app.router.transcription_formatters import TranscriptionFormattersMixin
from openclaw_app.router.transcription_storage import TranscriptionStorageMixin
from openclaw_app.services.transcription_postprocess_contract import validate_transcription_final_note_contract


def _jpeg_bytes(width: int, height: int) -> bytes:
    return (
        b"\xff\xd8\xff\xc0\x00\x11\x08"
        + height.to_bytes(2, "big")
        + width.to_bytes(2, "big")
        + b"\x03\x01\x11\x00\x02\x11\x01\x03\x11\x01\xff\xd9"
    )


def _role_labeled_transcript(
    text: str = "先完成小规模验证。",
    source: str = "audio-01-u-000000-000010",
) -> list[dict[str, str]]:
    return [
        {
            "speaker_key": "speaker_a",
            "speaker": "说话人 A",
            "role": "产品推进方",
            "text": text,
            "source": source,
            "confidence": "中",
        }
    ]


def _valid_transcription_final_note(**overrides: object) -> dict[str, object]:
    note: dict[str, object] = {
        "status": "done",
        "title": "数学智能产品推进讨论",
        "meeting_info": {
            "meeting_name": "数学智能产品推进讨论",
            "meeting_goal": "明确产品验证顺序并确定进入高成本投入前的验证条件",
            "meeting_time": "未从来源识别",
            "participants": ["未从来源识别"],
            "facilitator": "未从来源识别",
            "minutes_owner": "未从来源识别",
            "related_project": "数学智能产品",
            "related_documents": ["未从来源识别"],
            "version": "v1.0",
        },
        "conclusion_summary": {
            "overall_judgment": "当前应先完成小规模验证，再决定是否进入高成本投入。",
            "key_implications": [
                {
                    "item": "验证结果将决定后续投入节奏。",
                    "rationale": "成本收益尚未核清。",
                    "implications": "高成本投入暂不启动。",
                    "related_ids": ["T-01"],
                }
            ],
        },
        "decision_list": [],
        "topic_cards": [
            {
                "id": "T-01",
                "topic": "验证顺序",
                "current_facts": ["当前成本收益尚未核清。"],
                "core_question": "何时进入高成本投入？",
                "options": [{"option": "先小规模验证", "assessment": "降低投入风险"}],
                "conclusion_status": "tentative_direction",
                "conclusion": "先完成小规模验证。",
                "unresolved_questions": [],
                "next_step": "形成验证报告。",
            }
        ],
        "pending_decisions": [],
        "validation_hypotheses": [],
        "action_items": [],
        "risks_and_constraints": [],
        "next_meeting": {
            "trigger_conditions": ["验证报告完成后"],
            "required_materials": ["验证报告"],
            "decisions_needed": ["是否扩大投入"],
        },
        "topical_attachments": [],
        "speaker_notes": [
            {
                "speaker_key": "speaker_a",
                "display_name": "说话人 A",
                "meeting_role": "产品推进方",
                "identity_evidence": "来源中的稳定发言立场",
                "confidence": "中",
            }
        ],
        "labeled_transcript": _role_labeled_transcript(),
        "sensitive_summary": "",
        "archive_macro_summary": "会议讨论数学智能产品的验证与投入顺序。",
        "archive_summary_bullets": ["先完成小规模验证。"],
        "covered_evidence_hashes": [],
        "detail_coverage": [],
    }
    note.update(overrides)
    return note


def _write_content_os_v2_state_rules(root: Path) -> None:
    path = root / "00_入口与总览" / "state_transition_rules.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        """spec_version: content_os_v0.2
project_statuses:
  - captured
  - planned
  - edit_ready
  - editing
  - final_ready
  - published
transitions:
  captured_to_planned:
    from: captured
    to: planned
    allowed_actor: cloud_openclaw_or_human
    required_evidence:
      - 01_idea_card.md
      - 02_project_brief.md
      - 04_script.md
  planned_to_edit_ready:
    from: planned
    to: edit_ready
    allowed_actor: cloud_openclaw
    required_evidence: []
  edit_ready_to_editing:
    from: edit_ready
    to: editing
    allowed_actor: human
    required_evidence: []
  editing_to_final_ready:
    from: editing
    to: final_ready
    allowed_actor: human
    required_evidence: []
  final_ready_to_published:
    from: final_ready
    to: published
    allowed_actor: human
    required_evidence: []
""",
        encoding="utf-8",
    )

class KnowledgeFieldHarness(MediaCreationMixin, MediaKnowledgeFieldsMixin):
    def _extract_first_url(self, text: str) -> str:
        match = re.search(r"https?://\S+", text or "")
        return match.group(0) if match else ""


class CreationPersistenceHarness(ContentOSBridgeMixin, ContentOSUtilsMixin, ContentOSRenderersMixin):
    def _maybe_advance_content_os_status(self, **kwargs: object) -> str:
        return ""


class TranscriptionFormatterHarness(TranscriptionFormattersMixin):
    pass


class TranscriptionStorageHarness(TranscriptionStorageMixin):
    pass


class ContentFlowClientCompletionTest(unittest.TestCase):
    def test_role_aware_preparation_identifies_registry_before_rewriting(self) -> None:
        client = ContentFlowClient("")
        registry = [
            {
                "speaker_key": "speaker1",
                "display_name": "说话人 A",
                "meeting_role": "产品方",
                "identity_evidence": "来源显式 speaker1 标签",
                "confidence": "高",
            },
            {
                "speaker_key": "speaker2",
                "display_name": "说话人 B",
                "meeting_role": "需求方",
                "identity_evidence": "来源显式 speaker2 标签",
                "confidence": "高",
            },
        ]
        stages: list[str] = []

        def identify(evidence: list[dict[str, object]], source_hint: str, env: dict[str, str]) -> dict[str, object]:
            stages.append("identify")
            self.assertEqual(evidence[0]["observed_speaker_keys"], ["speaker1", "speaker2"])
            return {"status": "done", "speaker_registry": registry}

        def rewrite(**kwargs: object) -> dict[str, object]:
            stages.append("rewrite")
            source_units = kwargs["source_units"]
            return {
                "status": "done",
                "rewritten_units": [
                    {
                        "source_unit_id": unit["source_unit_id"],
                        "turns": [
                            {
                                "speaker_key": "speaker1",
                                "display_name": "说话人 A",
                                "meeting_role": "产品方",
                                "text": unit["text"],
                                "confidence": "高",
                            }
                        ],
                    }
                    for unit in source_units
                ],
            }

        with (
            patch.object(client, "_identify_transcript_speakers", side_effect=identify),
            patch.object(client, "_rewrite_transcript_chunk_by_role", side_effect=rewrite),
        ):
            result = client._prepare_role_aware_transcript(
                "speaker1：先验证产品。\nspeaker2：需要明确验收标准。",
                "产品讨论",
                {},
            )

        self.assertEqual(result["status"], "done")
        self.assertEqual(stages, ["identify", "rewrite"])
        self.assertEqual(result["speaker_registry"], registry)
        self.assertIn("说话人 A（产品方）：", result["rewritten_transcript"])
        self.assertTrue(result["labeled_transcript"])

    def test_rewrite_coverage_rejects_unknown_speaker_and_overcompression(self) -> None:
        units = [
            {
                "source_unit_id": "audio-01-u-000000-000020",
                "chunk_id": "audio-01-rewrite-01",
                "char_start": 0,
                "char_end": 20,
                "text": "这是一段包含产品价格交付条件和风险约束的完整讨论内容。",
            }
        ]
        issue = ContentFlowClient._transcription_rewrite_coverage_error(
            {
                "rewritten_units": [
                    {
                        "source_unit_id": units[0]["source_unit_id"],
                        "turns": [
                            {
                                "speaker_key": "invented",
                                "display_name": "未知",
                                "meeting_role": "未知",
                                "text": "讨论产品。",
                                "confidence": "低",
                            }
                        ],
                    }
                ]
            },
            units,
            {"speaker_a"},
        )

        self.assertIn("角色注册表之外的说话人", issue)
        self.assertIn("存在过度压缩", issue)

    def test_transcription_sections_preserve_multiple_text_attachments(self) -> None:
        sections = ContentFlowClient._split_transcript_audio_sections(
            "### 文字稿 1：多人讨论2.txt\n第一份内容\n\n"
            "### 文字稿 2：多人讨论.txt\n第二份内容\n\n"
            "### 文字稿 3：多人讨论3.txt\n第三份内容"
        )

        self.assertEqual([item["source_audio"] for item in sections], ["audio-01", "audio-02", "audio-03"])
        self.assertEqual(
            [item["source_title"] for item in sections],
            ["多人讨论2.txt", "多人讨论.txt", "多人讨论3.txt"],
        )

    def test_global_transcription_prompt_uses_role_stage_and_has_no_length_limit(self) -> None:
        client = ContentFlowClient("")
        seen: dict[str, str] = {}

        def fake_call(prompt: str, user_content: str, stage: str) -> dict[str, object]:
            seen["prompt"] = prompt
            return {"status": "done"}

        with patch.object(client, "_call_postprocess_json", side_effect=fake_call):
            client._summarize_global_note([], "关键词", {})

        self.assertIn("说话人注册表和角色化文字稿由前序阶段注入", seen["prompt"])
        self.assertNotIn("labeled_transcript: 必须", seen["prompt"])
        self.assertIn("covered_evidence_hashes 和 detail_coverage 由系统从已校验附件原样继承", seen["prompt"])
        self.assertIn("不限制结论摘要、决策清单、议题分析或其他清单的篇幅和条目数", seen["prompt"])
        self.assertIn("overall_judgment、key_implications", seen["prompt"])
        self.assertNotIn("1页结论", seen["prompt"])
        self.assertIn("meeting_goal 必须写成可判断是否完成的目标", seen["prompt"])
        self.assertIn("来源未明确统一会议目标时固定写“来源未明确会议目标”", seen["prompt"])
        self.assertIn("不得把待验证问题混入待拍板", seen["prompt"])
        self.assertIn("负责人、交付物、验收标准、截止时间均不得省略", seen["prompt"])
        self.assertIn("细节保全附录", seen["prompt"])
        self.assertNotIn("do_not" + "_include_in_final_note", seen["prompt"])

    def test_transcription_prompts_share_detail_fidelity_contract(self) -> None:
        client = ContentFlowClient("")
        seen: list[str] = []

        def fake_call(prompt: str, user_content: str, stage: str) -> dict[str, object]:
            seen.append(prompt)
            if stage == "分片整理":
                source_units = json.loads(user_content)["source_units"]
                return {
                    "status": "done",
                    "source_unit_coverage": [
                        {
                            "source_unit_id": source_units[0]["source_unit_id"],
                            "disposition": "retained",
                            "theme": "讨论内容",
                            "cleaned_details": ["讨论内容"],
                        }
                    ],
                }
            return {"status": "done"}

        with patch.object(client, "_call_postprocess_json", side_effect=fake_call):
            client._summarize_transcript_chunk(
                chunk_id="audio-01-chunk-01",
                source_audio="audio-01",
                source_title="录音.txt",
                char_start=0,
                char_end=10,
                text="讨论内容",
                source_hint="补充关键词",
                env={},
            )
            client._summarize_attachment_chunks(
                source_audio="audio-01",
                source_title="录音.txt",
                chunks=[],
                source_hint="补充关键词",
                env={},
            )
            client._summarize_attachment_group(1, [], "补充关键词", {})
            client._summarize_global_note([], "补充关键词", {})
            client._check_global_note_consistency({}, [], {})
            client._revise_global_note({}, [], {}, "补充关键词", {})

        self.assertEqual(len(seen), 6)
        for prompt in seen:
            self.assertIn("细节保真契约：目标是去冗余整理，不是摘要", prompt)
            self.assertIn("来源补充和关键词只作为逐字稿校正、检索和关联线索", prompt)
            self.assertNotIn("do_not" + "_include_in_final_note", prompt)
        self.assertIn("visibility=restricted/private", seen[0])
        self.assertIn("verification_status=unverified", seen[0])
        self.assertIn("public_use=forbidden", seen[0])
        self.assertIn("逐条 detail_coverage 和精确 source_range 已由系统完成一对一结构校验", seen[4])
        self.assertIn("meeting_info 的固定字段写入 Obsidian 笔记属性", seen[4])
        self.assertIn("1 结论摘要、2 决策清单", seen[4])
        self.assertNotIn("0 基本信息", seen[4])
        self.assertIn("原字稿单独落盘", seen[4])
        self.assertIn("source_range 是该 source_unit 的精确字符范围", seen[4])
        self.assertIn("blocking_issues 每项必须是对象", seen[4])
        self.assertIn("speaker_notes 和 labeled_transcript 由前序角色阶段固定注入", seen[4])
        self.assertIn("只能给 warning", seen[4])
        self.assertIn("禁止建议 confirmed_current_state", seen[4])
        for prompt in seen[3:6]:
            self.assertIn("不得升级成“重点候选”、优先方向或会议结论", prompt)
            self.assertIn(
                "conclusion_summary、pending_decisions、validation_hypotheses、risks_and_constraints",
                prompt,
            )
        self.assertIn("其他推进上下文必须保留", seen[5])
        self.assertIn("同一事项收敛到唯一正确字段", seen[5])

    def test_transcription_consistency_routes_only_requested_repair_fields(self) -> None:
        structured = ContentFlowClient._transcription_consistency_repair_fields(
            {
                "blocking_issues": [
                    {
                        "issue": "行动项需要降级并保留到待验证",
                        "repair_fields": ["action_items", "validation_hypotheses", "not_a_field"],
                        "required_fix": "保留来源上下文",
                    }
                ]
            }
        )
        legacy = ContentFlowClient._transcription_consistency_repair_fields(
            {"blocking_issues": ["决策清单复审条件无来源；专题附件遗漏来源细节"]}
        )

        self.assertEqual(structured, {"action_items", "validation_hypotheses"})
        self.assertEqual(legacy, {"decision_list", "topical_attachments"})

    def test_attachment_prompt_receives_exact_allowed_evidence_ids(self) -> None:
        client = ContentFlowClient("")
        seen: dict[str, object] = {}

        def fake_call(prompt: str, user_content: str, stage: str) -> dict[str, object]:
            seen.update(json.loads(user_content))
            return {"status": "done"}

        with patch.object(client, "_call_postprocess_json", side_effect=fake_call):
            client._summarize_attachment_chunks(
                source_audio="audio-01",
                source_title="讨论.txt",
                chunks=[
                    {
                        "key_points": [{"point": "报价", "evidence_hash": "hash-b"}],
                        "pending_questions": [{"text": "成本？", "evidence_hash": "hash-a"}],
                        "sensitive_items": [{"text": "不公开", "evidence_hash": "hash-sensitive"}],
                    }
                ],
                source_hint="报价",
                env={},
            )

        self.assertEqual(seen["expected_evidence_hashes"], ["hash-b"])

    def test_transcription_source_units_require_one_semantic_disposition_per_source_segment(self) -> None:
        client = ContentFlowClient("")
        units = client._split_transcript_source_units(
            "产品按月收费。\n教师关心报销。\n工业客户按项目报价。",
            source_audio="audio-01",
            chunk_id="audio-01-chunk-01",
            base_char_start=20,
        )
        coverage = {
            "source_unit_coverage": [
                {
                    "source_unit_id": unit["source_unit_id"],
                    "disposition": "retained",
                    "theme": "商业化",
                    "cleaned_details": [unit["text"]],
                }
                for unit in units
            ]
        }

        self.assertEqual(client._transcription_source_unit_coverage_error(coverage, units, {}), "")
        coverage["source_unit_coverage"] = coverage["source_unit_coverage"][:-1]
        self.assertIn("缺少 1 个来源段", client._transcription_source_unit_coverage_error(coverage, units, {}))

    def test_transcription_chunking_has_no_overlap_when_source_units_are_accountable(self) -> None:
        chunks = ContentFlowClient._split_text_chunks(
            ("第一段讨论产品定价。\n" * 700) + "最后一段讨论交付。",
            target_chars=3000,
            max_chars=4000,
            overlap_chars=0,
        )

        self.assertGreater(len(chunks), 1)
        for previous, current in zip(chunks, chunks[1:]):
            self.assertGreaterEqual(current["char_start"], previous["char_end"])

    def test_transcription_source_unit_coverage_rejects_overcompression(self) -> None:
        client = ContentFlowClient("")
        units = [
            {
                "source_unit_id": "audio-01-u-000000-000100",
                "chunk_id": "audio-01-chunk-01",
                "char_start": 0,
                "char_end": 100,
                "text": "产品采用固定七环节，每个环节支持用户介入、跳过、循环和反馈修改，并分别核算模型调用成本。",
            }
        ]
        issue = client._transcription_source_unit_coverage_error(
            {
                "source_unit_coverage": [
                    {
                        "source_unit_id": units[0]["source_unit_id"],
                        "disposition": "retained",
                        "theme": "产品",
                        "cleaned_details": ["讨论产品。"],
                    }
                ]
            },
            units,
            {},
        )

        self.assertIn("存在过度压缩", issue)

    def test_source_unit_details_materialize_as_exact_range_key_points(self) -> None:
        client = ContentFlowClient("")
        units = [
            {
                "source_unit_id": "audio-02-u-000120-000180",
                "chunk_id": "audio-02-chunk-01",
                "char_start": 120,
                "char_end": 180,
                "text": "教师版先验证按月收费，工业客户按项目报价。",
            }
        ]
        payload = {
            "source_unit_coverage": [
                {
                    "source_unit_id": units[0]["source_unit_id"],
                    "disposition": "retained",
                    "theme": "定价",
                    "cleaned_details": ["教师版先验证按月收费。", "工业客户按项目报价。"],
                }
            ]
        }

        client._materialize_source_unit_key_points(payload, units)

        self.assertEqual(len(payload["key_points"]), 2)
        self.assertEqual(payload["key_points"][0]["source_range"]["char_start"], 120)
        self.assertEqual(payload["key_points"][1]["source_range"]["char_end"], 180)

    def test_transcription_postprocess_has_one_canonical_chunked_path(self) -> None:
        client = ContentFlowClient("")
        expected = {"status": "done", "summary": "完整整理稿"}
        prepared = {
            "status": "done",
            "speaker_registry": [
                {
                    "speaker_key": "speaker_a",
                    "display_name": "说话人 A",
                    "meeting_role": "未从来源识别",
                    "identity_evidence": "来源未标注",
                    "confidence": "低",
                }
            ],
            "labeled_transcript": [{"speaker": "说话人 A", "text": "逐字稿"}],
            "rewritten_transcript": "说话人 A：逐字稿",
        }
        with (
            patch.object(client, "_content_flow_env", return_value={"TRANSCRIPTION_POSTPROCESS_CHUNKED": "0"}),
            patch.object(client, "_prepare_role_aware_transcript", return_value=prepared) as role_prepare,
            patch.object(client, "_summarize_dialogue_transcript_chunked", return_value=expected) as chunked,
        ):
            result = client.summarize_dialogue_transcript("逐字稿", "补充关键词")

        self.assertEqual(result, expected)
        role_prepare.assert_called_once()
        chunked.assert_called_once()
        self.assertEqual(chunked.call_args.args[0], "说话人 A：逐字稿")
        self.assertEqual(chunked.call_args.kwargs["speaker_notes"], prepared["speaker_registry"])
        self.assertEqual(chunked.call_args.kwargs["labeled_transcript"], prepared["labeled_transcript"])

    def test_transcription_coverage_rejects_missing_or_unknown_detail_ids(self) -> None:
        client = ContentFlowClient("")
        expected = {"detail-a", "detail-b"}

        self.assertEqual(
            client._transcription_coverage_error(
                {
                    "covered_evidence_hashes": ["detail-a", "detail-b"],
                    "detail_coverage": [
                        {"evidence_hash": "detail-a", "theme": "定价", "detail": "报价为一万元。"},
                        {"evidence_hash": "detail-b", "theme": "交付", "detail": "交付前需要验收。"},
                    ],
                },
                expected,
            ),
            "",
        )
        issue = client._transcription_coverage_error(
            {
                "covered_evidence_hashes": ["detail-a", "invented"],
                "detail_coverage": [
                    {"evidence_hash": "detail-a", "theme": "定价", "detail": "报价为一万元。"},
                    {"evidence_hash": "invented", "theme": "其他", "detail": "无来源内容。"},
                ],
            },
            expected,
        )
        self.assertIn("缺少 1 个来源细节 ID", issue)
        self.assertIn("包含 1 个无来源细节 ID", issue)
        self.assertIn("缺少 1 条来源细节正文", issue)
        self.assertIn("包含 1 条无来源细节正文", issue)

    def test_transcription_evidence_hashes_normalize_string_and_content_items(self) -> None:
        summary = {
            "chunk_id": "audio-01-chunk-01",
            "source_audio": "audio-01",
            "char_start": 0,
            "char_end": 20,
            "local_observations": ["观察到教师更关心报销。"],
            "local_decisions_or_claims": [{"content": "先验证高校场景。", "status": "discussion_tendency"}],
            "pending_questions": ["报价是否覆盖模型成本？"],
        }

        ContentFlowClient._annotate_evidence_hashes(summary)

        for field in ("local_observations", "local_decisions_or_claims", "pending_questions"):
            self.assertIsInstance(summary[field][0], dict)
            self.assertTrue(summary[field][0].get("evidence_hash"))
            self.assertEqual(summary[field][0]["source_range"]["chunk_id"], "audio-01-chunk-01")

    def test_transcription_contract_rejects_unclassified_or_unverifiable_decision_interface(self) -> None:
        no_conclusion = _valid_transcription_final_note(
            conclusion_summary={
                "overall_judgment": "",
                "key_implications": [],
            }
        )
        invalid_action = _valid_transcription_final_note(
            action_items=[
                {
                    "id": "A-01",
                    "action": "继续研究",
                    "assignee": "负责人",
                    "deliverable": "",
                    "acceptance_criteria": "",
                    "deadline": "未指定",
                    "dependencies": "无",
                }
            ]
        )

        self.assertIn(
            "conclusion_summary.overall_judgment must be a non-empty string",
            validate_transcription_final_note_contract(no_conclusion),
        )
        action_errors = validate_transcription_final_note_contract(invalid_action)
        self.assertTrue(any("deliverable" in error for error in action_errors))
        self.assertTrue(any("acceptance_criteria" in error for error in action_errors))

    def test_transcription_formatter_renders_decision_interface_and_readable_detail_appendix(self) -> None:
        harness = TranscriptionFormatterHarness()
        harness._clean_meeting_topic_candidate = lambda value: value
        harness.content_flow_client = Mock()
        harness.content_flow_client.summarize_dialogue_transcript.return_value = _valid_transcription_final_note(
            decision_list=[
                {
                    "id": "D-01",
                    "topic": "模型投入",
                    "decision": "先做小模型验证",
                    "status": "decided",
                    "rationale": "成本收益尚未核清",
                    "scope": "模型研发",
                    "review_condition": "小模型出现稳定正收益",
                }
            ],
            detail_coverage=[
                {
                    "evidence_hash": "a",
                    "theme": "商业化",
                    "detail": "会议举例首单可按数万元级验证。",
                    "source_range": {"source_audio": "audio-01", "chunk_id": "audio-01-chunk-01"},
                    "commercial_condition": "仅在试点范围内生效。",
                }
            ],
            sensitive_summary=[
                {
                    "detail": "首单金额仅限内部验证使用。",
                    "business_boundary": "对外报价前必须重新核验。",
                    "visibility": "restricted",
                    "verification_status": "unverified",
                    "public_use": "forbidden",
                }
            ],
            postprocess_pipeline="chunked-map-reduce-final",
            consistency_check={"approved": True},
        )

        formatted = harness._format_dialogue_transcription("逐字稿")

        self.assertEqual(formatted["status"], "done")
        self.assertIn("会议目标：明确产品验证顺序", formatted["meeting_info"])
        self.assertIn("### 1.1 总体判断", formatted["conclusion_summary"])
        self.assertIn("### 1.2 关键影响", formatted["conclusion_summary"])
        self.assertIn("### D-01 模型投入", formatted["decision_list"])
        self.assertIn("- 决策结果：先做小模型验证", formatted["decision_list"])
        self.assertIn("##### 1. 当前事实", formatted["topic_cards"])
        self.assertNotIn("会议举例首单可按数万元级验证", formatted["topic_cards"])
        self.assertIn("会议举例首单可按数万元级验证", formatted["detail_fidelity_appendix"])
        self.assertIn("仅在试点范围内生效", formatted["detail_fidelity_appendix"])
        self.assertIn("首单金额仅限内部验证使用", formatted["detail_fidelity_appendix"])
        self.assertIn("对外报价前必须重新核验", formatted["detail_fidelity_appendix"])
        self.assertIn("公开使用：禁止", formatted["detail_fidelity_appendix"])
        self.assertNotIn("do_not" + "_include_in_final_note", formatted["detail_fidelity_appendix"])

    def test_transcription_storage_writes_restricted_detail_appendix_into_main_note(self) -> None:
        harness = TranscriptionStorageHarness()
        harness._meeting_note_topic = lambda *_args: "业务细节保全测试"
        formatted = {
            "meeting_info_data": {},
            "archive_macro_summary": "讨论首单验证。",
            "archive_summary_bullets": ["保留完整报价与使用边界。"],
            "postprocess_pipeline": "chunked-map-reduce-final",
            "postprocess_artifacts": {},
            "topical_attachments_data": [],
            "topical_attachments": "",
            "speaker_notes": "- 说话人 A",
            "labeled_transcript": "说话人 A：首单按数万元级验证。",
            "conclusion_section": "先进行首单验证。",
            "decision_list": "暂无正式决策记录。",
            "topic_cards": "#### T-01 首单验证",
            "action_items": "暂无明确行动项。",
            "next_meeting": "未指定。",
            "detail_fidelity_appendix": (
                "> visibility=restricted | public_use=forbidden\n\n"
                "首单金额仅限内部验证使用，具体按数万元级评估。"
            ),
        }
        message = Message(
            entry_tag="转写",
            raw_text="【转写】",
            body="",
            source="feishu",
            created_at=datetime(2026, 8, 12, 10, 0),
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            minutes_dir = root / "整理版"
            transcripts_dir = root / "原字稿"
            topical_dir = root / "专题附件"
            archived = Mock()
            archived.to_dict.return_value = {"status": "archived"}
            with (
                patch.object(transcription_storage_module, "MEETING_MINUTES_DIR", minutes_dir),
                patch.object(transcription_storage_module, "MEETING_TRANSCRIPTS_DIR", transcripts_dir),
                patch.object(transcription_storage_module, "MEETING_TOPICAL_ATTACHMENTS_DIR", topical_dir),
                patch.object(transcription_storage_module, "archive_meeting_content_section", return_value=archived),
            ):
                note_path = harness._save_transcription_meeting_note(
                    message,
                    "",
                    "",
                    [],
                    formatted,
                    "首单按数万元级验证。",
                )
            note = Path(note_path).read_text(encoding="utf-8")

        self.assertIn("5. 细节保全附录（受限）", note)
        self.assertIn("visibility=restricted | public_use=forbidden", note)
        self.assertIn("首单金额仅限内部验证使用，具体按数万元级评估。", note)
        self.assertIn("detail_fidelity_appendix_visibility: restricted", note)
        self.assertIn("detail_fidelity_appendix_public_use: forbidden", note)
        self.assertIn("6. 关联文档", note)

    def test_global_detail_coverage_is_structurally_inherited_from_attachments(self) -> None:
        inherited = {"evidence_hash": "detail-a", "theme": "定价", "detail": "报价是一万元。"}
        merged = ContentFlowClient._merge_transcription_detail_coverage(
            [
                {"detail_coverage": [inherited, {"evidence_hash": "unknown", "theme": "其他", "detail": "无来源"}]},
                {"detail_coverage": [dict(inherited)]},
            ],
            {"detail-a"},
        )

        self.assertEqual(merged, [inherited])
        self.assertIsNot(merged[0], inherited)

    def test_attachment_detail_coverage_is_structurally_inherited_from_chunk_key_points(self) -> None:
        client = ContentFlowClient("")
        inherited = client._detail_coverage_from_key_points(
            [
                {
                    "key_points": [
                        {
                            "point": "具体报价为一万元",
                            "theme": "定价",
                            "evidence_hash": "detail-a",
                            "source_range": {"char_start": 20, "char_end": 30},
                        }
                    ]
                }
            ],
            {"detail-a"},
        )

        self.assertEqual(
            inherited,
            [
                {
                    "evidence_hash": "detail-a",
                    "theme": "定价",
                    "detail": "具体报价为一万元",
                    "source_range": {"char_start": 20, "char_end": 30},
                }
            ],
        )

    def test_chunked_transcription_reuses_completed_chunk_artifact_on_retry(self) -> None:
        client = ContentFlowClient("")
        transcript_text = "报价是一万。"
        attachment = {
            "status": "done",
            "covered_evidence_hashes": ["detail-a"],
            "detail_coverage": [
                {"evidence_hash": "detail-a", "theme": "定价", "detail": "报价是一万元。"}
            ],
        }
        final_note = _valid_transcription_final_note(
            title="数学产品定价讨论",
            labeled_transcript=_role_labeled_transcript("讨论产品定价。"),
            archive_macro_summary="讨论产品定价。",
            archive_summary_bullets=["报价需要进一步确认。"],
        )
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp)
            (artifact_dir / "audio-01-chunk-01.json").write_text(
                json.dumps(
                    {
                        "schema_version": "3.0",
                        "chunk_id": "audio-01-chunk-01",
                        "source_audio": "audio-01",
                        "source_title": "讨论.txt",
                        "char_start": 0,
                        "char_end": len(transcript_text),
                        "key_points": [
                            {"point": "报价是一万元", "evidence_hash": "detail-a"}
                        ],
                        "source_unit_coverage": [
                            {
                                "source_unit_id": f"audio-01-u-{0:06d}-{len(transcript_text):06d}",
                                "disposition": "retained",
                                "theme": "定价",
                                "cleaned_details": ["报价是一万元"],
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            with (
                patch.object(client, "_summarize_transcript_chunk") as chunk_call,
                patch.object(client, "_summarize_attachment_chunks", return_value=attachment),
                patch.object(client, "_summarize_global_note", return_value=final_note),
                patch.object(
                    client,
                    "_check_global_note_consistency",
                    return_value={"approved": True, "blocking_issues": [], "warnings": []},
                ),
            ):
                result = client._summarize_dialogue_transcript_chunked(
                    f"### 文字稿 1：讨论.txt\n{transcript_text}",
                    "报价",
                    {},
                    artifact_dir=artifact_dir,
                )

        self.assertEqual(result["status"], "done")
        self.assertEqual(result["covered_evidence_hashes"], ["detail-a"])
        self.assertEqual(result["detail_coverage"][0]["detail"], "报价是一万元")
        self.assertEqual(result["detail_coverage"][0]["source_range"]["char_end"], len(transcript_text))
        chunk_call.assert_not_called()

    def test_transcription_retry_resumes_from_latest_complete_global_note(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp)
            draft = _valid_transcription_final_note(title="初始稿")
            revised = _valid_transcription_final_note(title="修订稿")
            (artifact_dir / "global-note-draft.json").write_text(
                json.dumps(draft, ensure_ascii=False),
                encoding="utf-8",
            )
            (artifact_dir / "global-note-revised.json").write_text(
                json.dumps(revised, ensure_ascii=False),
                encoding="utf-8",
            )

            selected = ContentFlowClient._latest_transcription_global_note_artifact(artifact_dir)

            self.assertEqual(selected["title"], "修订稿")

            (artifact_dir / "global-note-revised.json").write_text(
                json.dumps({"title": "残缺修订稿"}, ensure_ascii=False),
                encoding="utf-8",
            )

            fallback = ContentFlowClient._latest_transcription_global_note_artifact(artifact_dir)

        self.assertEqual(fallback["title"], "初始稿")

    def test_transcription_partial_object_repair_preserves_sibling_fields(self) -> None:
        note = _valid_transcription_final_note()
        original_name = note["meeting_info"]["meeting_name"]

        ContentFlowClient._apply_transcription_field_repairs(
            note,
            {"meeting_info": {"meeting_goal": "多项目路线交流，未设统一决策目标"}},
            {"meeting_info"},
        )

        self.assertEqual(note["meeting_info"]["meeting_name"], original_name)
        self.assertEqual(note["meeting_info"]["meeting_goal"], "多项目路线交流，未设统一决策目标")

    def test_transcription_schema_repair_merges_partial_list_item_by_id(self) -> None:
        note = _valid_transcription_final_note()
        original_card = note["topic_cards"][0]

        ContentFlowClient._apply_transcription_field_repairs(
            note,
            {"topic_cards": [{"id": "T-01", "conclusion_status": "pending_validation"}]},
            {"topic_cards"},
            merge_list_items=True,
        )

        self.assertEqual(len(note["topic_cards"]), 1)
        self.assertEqual(note["topic_cards"][0]["topic"], original_card["topic"])
        self.assertEqual(note["topic_cards"][0]["conclusion_status"], "pending_validation")

    def test_transcription_schema_repair_merges_partial_list_items_by_index(self) -> None:
        note = _valid_transcription_final_note()
        original_card = note["topic_cards"][0]

        ContentFlowClient._apply_transcription_field_repairs(
            note,
            {"topic_cards": {"0": {"conclusion_status": "pending_validation"}}},
            {"topic_cards"},
            merge_list_items=True,
        )

        self.assertIsInstance(note["topic_cards"], list)
        self.assertEqual(note["topic_cards"][0]["topic"], original_card["topic"])
        self.assertEqual(note["topic_cards"][0]["conclusion_status"], "pending_validation")

    def test_transcription_schema_repair_keeps_invalid_index_map_contract_invalid(self) -> None:
        note = _valid_transcription_final_note()

        ContentFlowClient._apply_transcription_field_repairs(
            note,
            {"topic_cards": {"outside": {"conclusion_status": "pending_validation"}}},
            {"topic_cards"},
            merge_list_items=True,
        )

        self.assertIn("field topic_cards must be a list", validate_transcription_final_note_contract(note))

    def test_chunked_transcription_repairs_invalid_global_note_schema_with_llm(self) -> None:
        client = ContentFlowClient("")
        invalid_note = _valid_transcription_final_note(
            title="数学智能产品讨论",
            labeled_transcript="完整逐字稿见来源路径",
            archive_macro_summary="讨论数学智能产品方向。",
            archive_summary_bullets=["讨论了产品方向。"],
            covered_evidence_hashes=["detail-a"],
            detail_coverage=[
                {"evidence_hash": "detail-a", "theme": "产品方向", "detail": "讨论数学智能产品方向。"}
            ],
        )
        role_registry = list(_valid_transcription_final_note()["speaker_notes"])
        role_transcript = _role_labeled_transcript("讨论产品方向。")

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(
                client,
                "_summarize_transcript_chunk",
                return_value={
                    "status": "done",
                    "key_points": [{"point": "产品方向", "evidence_hash": "detail-a"}],
                },
            ),
            patch.object(
                client,
                "_summarize_attachment_chunks",
                return_value={
                    "status": "done",
                    "main_value": "产品方向",
                    "covered_evidence_hashes": ["detail-a"],
                    "detail_coverage": [
                        {"evidence_hash": "detail-a", "theme": "产品方向", "detail": "讨论数学智能产品方向。"}
                    ],
                },
            ),
            patch.object(client, "_summarize_global_note", return_value=invalid_note),
            patch.object(client, "_repair_global_note_contract") as repair,
            patch.object(
                client,
                "_check_global_note_consistency",
                return_value={"approved": True, "blocking_issues": [], "warnings": []},
            ),
        ):
            result = client._summarize_dialogue_transcript_chunked(
                "### 录音 1：多人讨论.m4a\n讨论产品方向。",
                "补充关键词",
                {},
                artifact_dir=Path(tmp),
                speaker_notes=role_registry,
                labeled_transcript=role_transcript,
            )

        self.assertEqual(result["status"], "done")
        self.assertEqual(result["speaker_notes"], role_registry)
        self.assertEqual(result["labeled_transcript"], role_transcript)
        self.assertEqual(result["meeting_info"], invalid_note["meeting_info"])
        repair.assert_not_called()

    def test_consistency_revision_patches_only_blocking_fields(self) -> None:
        client = ContentFlowClient("")
        original_note = _valid_transcription_final_note(
            title="数学产品定价讨论",
            decision_list=[
                {
                    "id": "D-01",
                    "topic": "定价",
                    "decision": "合并了两个倾向",
                    "status": "tentative_direction",
                    "rationale": "来源讨论",
                    "scope": "定价",
                    "review_condition": "获得新证据",
                }
            ],
            labeled_transcript=_role_labeled_transcript("讨论产品定价。"),
            archive_macro_summary="讨论产品定价。",
            archive_summary_bullets=["报价需要确认。"],
            detail_coverage=[{"evidence_hash": "kept", "theme": "定价", "detail": "不得改写"}],
        )
        repaired_decisions = [
            {
                "id": "D-01",
                "topic": "高校场景",
                "decision": "先验证高校场景",
                "status": "tentative_direction",
                "rationale": "来源讨论",
                "scope": "产品验证",
                "review_condition": "验证完成",
            },
            {
                "id": "D-02",
                "topic": "工业定制",
                "decision": "另行评估",
                "status": "tentative_direction",
                "rationale": "来源讨论",
                "scope": "工业场景",
                "review_condition": "获得需求证据",
            },
        ]
        with (
            patch.object(
                client,
                "_summarize_transcript_chunk",
                return_value={"status": "done", "key_points": [{"point": "不得改写", "evidence_hash": "kept"}]},
            ),
            patch.object(
                client,
                "_summarize_attachment_chunks",
                return_value={
                    "status": "done",
                    "covered_evidence_hashes": ["kept"],
                    "detail_coverage": [
                        {"evidence_hash": "kept", "theme": "定价", "detail": "不得改写"}
                    ],
                },
            ),
            patch.object(client, "_summarize_global_note", return_value=original_note),
            patch.object(
                client,
                "_check_global_note_consistency",
                side_effect=[
                    {"approved": False, "blocking_issues": ["`decision_list` 合并了两个不同讨论倾向"], "warnings": []},
                    {"approved": True, "blocking_issues": [], "warnings": []},
                ],
            ),
            patch.object(
                client,
                "_revise_global_note",
                return_value={"status": "done", "repairs": {"decision_list": repaired_decisions}},
            ),
        ):
            result = client._summarize_dialogue_transcript_chunked(
                "### 文字稿 1：讨论.txt\n讨论产品定价。",
                "定价",
                {},
            )

        self.assertEqual(result["status"], "done")
        self.assertEqual(result["decision_list"], repaired_decisions)
        self.assertEqual(result["meeting_info"], original_note["meeting_info"])
        self.assertEqual(result["detail_coverage"][0]["detail"], "不得改写")
        self.assertEqual(result["detail_coverage"][0]["source_range"]["chunk_id"], "audio-01-chunk-01")

    def test_consistency_revision_accepts_partial_allowed_repairs_before_recheck(self) -> None:
        client = ContentFlowClient("")
        note = _valid_transcription_final_note(
            title="产品讨论",
            labeled_transcript=_role_labeled_transcript("讨论产品。"),
            archive_macro_summary="讨论产品。",
            archive_summary_bullets=["讨论产品。"],
        )
        repaired_conclusion = {
            "overall_judgment": "补齐后的总体方向。",
            "key_implications": [
                {
                    "item": "补齐后的影响",
                    "rationale": "来源讨论",
                    "implications": "后续按此方向推进",
                    "related_ids": ["T-01"],
                }
            ],
        }
        with (
            patch.object(
                client,
                "_summarize_transcript_chunk",
                return_value={"status": "done", "key_points": [{"point": "讨论产品", "evidence_hash": "a"}]},
            ),
            patch.object(client, "_summarize_attachment_chunks", return_value={"status": "done"}),
            patch.object(client, "_summarize_global_note", return_value=note),
            patch.object(
                client,
                "_check_global_note_consistency",
                side_effect=[
                    {"approved": False, "blocking_issues": ["conclusion_summary 缺少主题"], "warnings": []},
                    {"approved": True, "blocking_issues": [], "warnings": []},
                ],
            ),
            patch.object(
                client,
                "_revise_global_note",
                return_value={"status": "done", "repairs": {"conclusion_summary": repaired_conclusion}},
            ),
        ):
            result = client._summarize_dialogue_transcript_chunked(
                "### 文字稿 1：讨论.txt\n讨论产品。",
                "",
                {},
            )

        self.assertEqual(result["status"], "done")
        self.assertEqual(result["conclusion_summary"], repaired_conclusion)

    def test_consistency_revision_repairs_schema_before_consistency_recheck(self) -> None:
        client = ContentFlowClient("")
        note = _valid_transcription_final_note(
            labeled_transcript=_role_labeled_transcript("讨论产品方案。"),
        )
        broken_card = dict(note["topic_cards"][0])
        broken_card.pop("options")
        unresolved = {
            "approved": False,
            "blocking_issues": [
                {
                    "issue": "议题卡需要按来源修订",
                    "repair_fields": ["topic_cards"],
                    "required_fix": "修订议题卡但保持 schema 完整",
                }
            ],
            "warnings": [],
        }
        check_count = 0

        def check_after_schema(note_to_check: dict[str, object], *_args: object) -> dict[str, object]:
            nonlocal check_count
            check_count += 1
            if check_count == 1:
                return unresolved
            self.assertEqual(validate_transcription_final_note_contract(note_to_check), [])
            return {"approved": True, "blocking_issues": [], "warnings": []}

        with (
            patch.object(
                client,
                "_summarize_transcript_chunk",
                return_value={"status": "done", "key_points": [{"point": "讨论产品方案", "evidence_hash": "a"}]},
            ),
            patch.object(client, "_summarize_attachment_chunks", return_value={"status": "done"}),
            patch.object(client, "_summarize_global_note", return_value=note),
            patch.object(client, "_check_global_note_consistency", side_effect=check_after_schema),
            patch.object(
                client,
                "_revise_global_note",
                return_value={"status": "done", "repairs": {"topic_cards": [broken_card]}},
            ),
            patch.object(
                client,
                "_repair_global_note_contract",
                return_value={
                    "status": "done",
                    "repairs": {
                        "topic_cards": [
                            {
                                "id": "T-01",
                                "options": [{"option": "先小规模验证", "assessment": "降低投入风险"}],
                            }
                        ]
                    },
                },
            ) as schema_repair,
        ):
            result = client._summarize_dialogue_transcript_chunked(
                "### 文字稿 1：讨论.txt\n讨论产品方案。",
                "",
                {},
            )

        self.assertEqual(result["status"], "done", result)
        self.assertEqual(result["topic_cards"][0]["options"][0]["option"], "先小规模验证")
        self.assertEqual(check_count, 2)
        schema_repair.assert_called_once()

    def test_invalid_consistency_revision_is_retried_without_abandoning_job(self) -> None:
        client = ContentFlowClient("")
        note = _valid_transcription_final_note(
            labeled_transcript=_role_labeled_transcript("讨论定价。"),
        )
        unresolved = {
            "approved": False,
            "blocking_issues": [
                {
                    "issue": "决策清单需要修订",
                    "repair_fields": ["decision_list"],
                    "required_fix": "按来源补齐决策",
                }
            ],
            "warnings": [],
        }
        repaired_decisions = [
            {
                "id": "D-01",
                "topic": "定价",
                "decision": "先验证报价",
                "status": "tentative_direction",
                "rationale": "来源讨论",
                "scope": "首轮验证",
                "review_condition": "来源未约定复审条件",
            }
        ]
        with (
            patch.object(
                client,
                "_summarize_transcript_chunk",
                return_value={"status": "done", "key_points": [{"point": "讨论定价", "evidence_hash": "a"}]},
            ),
            patch.object(client, "_summarize_attachment_chunks", return_value={"status": "done"}),
            patch.object(client, "_summarize_global_note", return_value=note),
            patch.object(
                client,
                "_check_global_note_consistency",
                side_effect=[
                    unresolved,
                    {"approved": True, "blocking_issues": [], "warnings": []},
                ],
            ),
            patch.object(
                client,
                "_revise_global_note",
                side_effect=[
                    {"status": "pending_manual", "reason": "未返回可解析 JSON"},
                    {"status": "done", "repairs": {"decision_list": repaired_decisions}},
                ],
            ) as revise,
        ):
            result = client._summarize_dialogue_transcript_chunked(
                "### 文字稿 1：讨论.txt\n讨论定价。",
                "",
                {},
            )

        self.assertEqual(result["status"], "done", result)
        self.assertEqual(result["decision_list"], repaired_decisions)
        self.assertEqual(revise.call_count, 2)

    def test_consistency_revision_replaces_id_list_and_removes_omitted_pending_decisions(self) -> None:
        client = ContentFlowClient("")
        pending_decisions = [
            {
                "id": decision_id,
                "question": question,
                "options": ["继续核验"],
                "decision_owner": "未指定",
                "deadline": "未指定",
            }
            for decision_id, question in (
                ("PD-01", "错误归类一"),
                ("PD-02", "真实待拍板事项"),
                ("PD-03", "错误归类二"),
            )
        ]
        note = _valid_transcription_final_note(
            pending_decisions=pending_decisions,
            labeled_transcript=_role_labeled_transcript("只保留真实待拍板事项。"),
        )
        repaired_pending_decisions = [pending_decisions[1]]

        with (
            patch.object(
                client,
                "_summarize_transcript_chunk",
                return_value={"status": "done", "key_points": [{"point": "真实待拍板事项", "evidence_hash": "a"}]},
            ),
            patch.object(client, "_summarize_attachment_chunks", return_value={"status": "done"}),
            patch.object(client, "_summarize_global_note", return_value=note),
            patch.object(
                client,
                "_check_global_note_consistency",
                side_effect=[
                    {
                        "approved": False,
                        "blocking_issues": [
                            {
                                "issue": "PD-01 和 PD-03 被错误归类为待拍板",
                                "repair_fields": ["pending_decisions"],
                                "required_fix": "只保留 PD-02",
                            }
                        ],
                        "warnings": [],
                    },
                    {"approved": True, "blocking_issues": [], "warnings": []},
                ],
            ),
            patch.object(
                client,
                "_revise_global_note",
                return_value={"status": "done", "repairs": {"pending_decisions": repaired_pending_decisions}},
            ),
        ):
            result = client._summarize_dialogue_transcript_chunked(
                "### 文字稿 1：讨论.txt\n只保留真实待拍板事项。",
                "",
                {},
            )

        self.assertEqual(result["status"], "done", result)
        self.assertEqual(result["pending_decisions"], repaired_pending_decisions)
        self.assertNotIn("PD-01", {item["id"] for item in result["pending_decisions"]})
        self.assertNotIn("PD-03", {item["id"] for item in result["pending_decisions"]})

    def test_consistency_recheck_failure_triggers_another_targeted_revision(self) -> None:
        client = ContentFlowClient("")
        existing_attachment = {
            "id": "A-01",
            "title": "既有项目路径",
            "status_note": "结构化整理；未形成正式决策。",
            "summary": "保留既有专题。",
            "details": ["既有专题细节不得被后续局部修订删除。"],
            "source_ranges": ["audio-01"],
        }
        note = _valid_transcription_final_note(
            decision_list=[
                {
                    "id": "D-04",
                    "topic": "项目切入路径",
                    "decision": "项目原本从短跑切入",
                    "status": "tentative_direction",
                    "rationale": "来源讨论",
                    "scope": "项目路径",
                    "review_condition": "来源未约定复审条件",
                }
            ],
            topical_attachments=[existing_attachment],
            labeled_transcript=_role_labeled_transcript("讨论项目路径。"),
        )
        repaired_decisions = [
            {
                "id": "D-04",
                "topic": "项目切入路径",
                "decision": "项目原本从短跑切入",
                "status": "tentative_direction",
                "rationale": "既有现状，非本次新决策",
                "scope": "项目路径",
                "review_condition": "来源未约定复审条件",
            }
        ]
        repaired_attachments = [
            existing_attachment,
            {
                "id": "A-02",
                "title": "华为问题处理上下文",
                "status_note": "待继续核验",
                "summary": "补回 audio-02 中的处理起点与 proof 状态。",
                "details": [
                    "华为问题刚取得，最早自 17 日共同处理。",
                    "已有较多 proof，仍需展示核验。",
                ],
            }
        ]
        consistency_results = [
            {
                "approved": False,
                "blocking_issues": [
                    {
                        "issue": "D-04 把既有路径写成本次会议决策",
                        "repair_fields": ["decision_list"],
                        "required_fix": "注明非本次新决策",
                    }
                ],
                "warnings": [],
            },
            {
                "approved": False,
                "blocking_issues": [
                    {
                        "issue": "遗漏 audio-02 的华为处理时间与 proof 核验上下文",
                        "repair_fields": ["topical_attachments"],
                        "required_fix": "补回两段来源上下文",
                    }
                ],
                "warnings": [],
            },
            {"approved": True, "blocking_issues": [], "warnings": []},
        ]

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(
                client,
                "_summarize_transcript_chunk",
                return_value={"status": "done", "key_points": [{"point": "讨论项目路径", "evidence_hash": "a"}]},
            ),
            patch.object(client, "_summarize_attachment_chunks", return_value={"status": "done"}),
            patch.object(client, "_summarize_global_note", return_value=note),
            patch.object(client, "_check_global_note_consistency", side_effect=consistency_results) as check,
            patch.object(
                client,
                "_revise_global_note",
                side_effect=[
                    {"status": "done", "repairs": {"decision_list": repaired_decisions}},
                    {"status": "done", "repairs": {"topical_attachments": repaired_attachments}},
                ],
            ) as revise,
        ):
            artifact_root = Path(tmp)
            result = client._summarize_dialogue_transcript_chunked(
                "### 文字稿 1：讨论.txt\n讨论项目路径。",
                "",
                {},
                artifact_dir=artifact_root,
            )
            latest = ContentFlowClient._latest_transcription_global_note_artifact(artifact_root)

        self.assertEqual(result["status"], "done", result)
        self.assertEqual(result["consistency_revision_count"], 2)
        self.assertEqual(result["consistency_revision_limit"], 5)
        self.assertEqual(result["decision_list"], repaired_decisions)
        self.assertEqual(result["topical_attachments"], repaired_attachments)
        self.assertEqual(latest["topical_attachments"], repaired_attachments)
        self.assertEqual(check.call_count, 3)
        self.assertEqual(revise.call_count, 2)
        self.assertIn("global_note_revised_02", result["postprocess_artifacts"])
        self.assertIn("consistency_check_revised_02", result["postprocess_artifacts"])

    def test_consistency_revision_limit_returns_final_blockers_without_unbounded_retry(self) -> None:
        client = ContentFlowClient("")
        note = _valid_transcription_final_note(
            labeled_transcript=_role_labeled_transcript("讨论既有项目路径。"),
        )
        unresolved = {
            "approved": False,
            "blocking_issues": [
                {
                    "issue": "既有项目路径仍未注明非本次新决策",
                    "repair_fields": ["decision_list"],
                    "required_fix": "补充来源边界",
                }
            ],
            "warnings": [],
        }

        with (
            patch.object(
                client,
                "_summarize_transcript_chunk",
                return_value={"status": "done", "key_points": [{"point": "既有项目路径", "evidence_hash": "a"}]},
            ),
            patch.object(client, "_summarize_attachment_chunks", return_value={"status": "done"}),
            patch.object(client, "_summarize_global_note", return_value=note),
            patch.object(client, "_check_global_note_consistency", side_effect=[unresolved, unresolved]) as check,
            patch.object(
                client,
                "_revise_global_note",
                return_value={"status": "done", "repairs": {"decision_list": []}},
            ) as revise,
        ):
            result = client._summarize_dialogue_transcript_chunked(
                "### 文字稿 1：讨论.txt\n讨论既有项目路径。",
                "",
                {"TRANSCRIPTION_CONSISTENCY_MAX_REVISIONS": "1"},
            )

        self.assertEqual(result["status"], "pending_manual")
        self.assertEqual(result["consistency_revision_count"], 1)
        self.assertEqual(result["consistency_revision_limit"], 1)
        self.assertEqual(result["consistency_check"], {**unresolved, "approved": False})
        self.assertEqual(check.call_count, 2)
        self.assertEqual(revise.call_count, 1)

    def test_consistency_repairs_replace_lists_without_stable_item_ids(self) -> None:
        note = {
            "labeled_transcript": _role_labeled_transcript("旧的跨主题归纳。"),
            "archive_summary_bullets": ["旧摘要"],
        }
        repairs = {
            "labeled_transcript": _role_labeled_transcript(
                "独立的短跑产品讨论。",
                "audio-04-u-000000-000012",
            ),
            "archive_summary_bullets": ["新摘要"],
        }

        ContentFlowClient._apply_transcription_field_repairs(
            note,
            repairs,
            set(repairs),
            merge_list_items=True,
        )

        self.assertEqual(note, repairs)

    def test_transcribe_file_imports_selfmedia_from_project_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project_root = root / "selfmedia-tools"
            content_flow_root = project_root / "selfmedia" / "ingest" / "content_flow"
            src_root = content_flow_root / "src"
            src_root.mkdir(parents=True)
            for package_dir in (
                project_root / "selfmedia",
                project_root / "selfmedia" / "ingest",
                content_flow_root,
                src_root,
            ):
                (package_dir / "__init__.py").write_text("", encoding="utf-8")
            (src_root / "config.py").write_text(
                "def load_settings():\n    return object()\n",
                encoding="utf-8",
            )
            (src_root / "transcriber.py").write_text(
                "import os\n"
                "def transcribe_audio(path, settings, raise_errors=False):\n"
                "    if os.environ.get('DASHSCOPE_API_KEY') != 'test-dashscope-key':\n"
                "        raise RuntimeError('missing test DashScope key')\n"
                "    if os.environ.get('ASR_PROVIDER') != 'dashscope':\n"
                "        raise RuntimeError('missing project ASR config')\n"
                "    return '真实包根导入成功'\n",
                encoding="utf-8",
            )
            (content_flow_root / ".env").write_text("ASR_PROVIDER=dashscope\n", encoding="utf-8")
            secret_env = root / "openclaw-media.env"
            secret_env.write_text("DASHSCOPE_API_KEY=test-dashscope-key\n", encoding="utf-8")
            audio_path = root / "sample.m4a"
            audio_path.write_bytes(b"audio")
            output_dir = root / "output"

            with (
                patch.dict(os.environ, {}, clear=True),
                patch.object(content_flow_client_module, "CONTENT_FLOW_ROOT", content_flow_root),
                patch.object(content_flow_client_module, "SELFMEDIA_TOOLS_ROOT", project_root),
                patch.object(content_flow_client_module, "CONTENT_FLOW_SECRET_ENV_PATH", secret_env),
            ):
                result = ContentFlowClient("").transcribe_file(str(audio_path), output_dir)

            self.assertEqual(result["status"], "done")
            self.assertEqual(Path(str(result["transcript_path"])).read_text(encoding="utf-8"), "真实包根导入成功\n")

    def test_parse_json_payload_accepts_fenced_model_reply(self) -> None:
        payload = ContentFlowClient._parse_json_payload(
            '整理结果如下：\n```json\n{"title":"体育训练软件定位讨论","summary":"内容整理"}\n```\n后续说明 {非 JSON}'
        )

        self.assertEqual(payload["title"], "体育训练软件定位讨论")

    def test_profile_provider_json_accepts_openclaw_agent_runtime(self) -> None:
        client = ContentFlowClient("")
        runtime = LLMProviderSettings(
            model="openai/gpt-5.6-terra",
            base_url="openclaw://agent",
            api_key="codex_auth_file",
            api_type="openclaw_agent",
            timeout=1800,
            thinking="high",
            bin="/bin/openclaw",
            agent="feishu-main",
            cwd="/tmp",
            codex_home="/home/ubuntu/.codex",
        )

        with patch.object(content_flow_client_module, "profile_config", return_value={"provider": "openclaw_codex"}), patch.object(
            content_flow_client_module, "load_profile_llm_settings", return_value=runtime
        ), patch.object(content_flow_client_module, "generate_json_from_parts", return_value={"value": "ok"}):
            result = client._call_profile_provider_json("content_cleaner", "prompt", "{}", "再创作任务卡 LLM 生成")

        self.assertEqual(result["status"], "done")
        self.assertEqual(result["postprocess_provider"], "openclaw_codex")

    def test_wechat_semantics_uses_shared_categories_and_bounded_fallback(self) -> None:
        client = ContentFlowClient("")
        captured: dict[str, str] = {}

        def fake_call(_profile: str, prompt: str, _content: str, _stage: str, **_kwargs: object) -> dict[str, object]:
            captured["prompt"] = prompt
            return {
                "status": "done",
                "title": "一篇内容",
                "summary": "摘要",
                "primary_category": "非标准分类",
                "secondary_category": ["非标准细分"],
            }

        with patch.object(client, "_call_profile_provider_json", side_effect=fake_call):
            result = client._analyze_wechat_article_semantics(
                url="https://mp.weixin.qq.com/s/example",
                article={"body_text": "正文", "blocks": []},
                base_analysis={"title": "标题", "full_content": "正文"},
                image_count=0,
            )

        self.assertIn("统一词表", captured["prompt"])
        self.assertIn("未细分", captured["prompt"])
        self.assertEqual(result["primary_category"], "其他")
        self.assertEqual(result["secondary_category"], ["未细分"])

    def test_profile_provider_json_accepts_timeout_override(self) -> None:
        client = ContentFlowClient("")
        runtime = Mock(
            api_type="openai_codex_responses",
            model="gpt-5.6-terra",
            base_url="https://example.com/v1",
            api_key="test",
            timeout=1800,
            thinking="high",
        )
        seen: dict[str, object] = {}

        def fake_generate(_parts, settings, **_kwargs):
            seen["timeout"] = settings.timeout
            seen["thinking"] = settings.thinking
            return {"status": "done", "value": "ok"}

        settings = LLMProviderSettings(
            model=runtime.model,
            base_url=runtime.base_url,
            api_key=runtime.api_key,
            api_type=runtime.api_type,
            timeout=runtime.timeout,
            thinking=runtime.thinking,
        )
        with patch.object(content_flow_client_module, "profile_config", return_value={}), patch.object(
            content_flow_client_module, "load_profile_llm_settings", return_value=settings
        ), patch.object(content_flow_client_module, "generate_json_from_parts", side_effect=fake_generate):
            result = client._call_profile_provider_json(
                "content_cleaner",
                "prompt",
                "{}",
                "文档修改 patch plan",
                timeout_seconds=120,
                thinking="medium",
            )

        self.assertEqual(result["status"], "done")
        self.assertEqual(seen["timeout"], 120)
        self.assertEqual(seen["thinking"], "medium")

    def test_daily_profile_passes_bounded_capacity_retry_budget(self) -> None:
        client = ContentFlowClient("")
        settings = LLMProviderSettings(
            model="gpt-5.6-terra",
            base_url="openclaw://agent",
            api_key="codex_auth_file",
            api_type="openclaw_agent",
            timeout=120,
            thinking="medium",
            bin="/bin/openclaw",
            agent="feishu-daily",
            cwd="/tmp",
            codex_home="/home/ubuntu/.codex",
        )
        with patch.object(
            content_flow_client_module,
            "profile_config",
            return_value={"provider": "openclaw_codex", "capacity_max_retries": 2},
        ), patch.object(
            content_flow_client_module, "load_profile_llm_settings", return_value=settings
        ), patch.object(
            content_flow_client_module, "generate_json_from_parts", return_value={"value": "ok"}
        ) as generate:
            result = client._call_profile_provider_json(
                "daily_task_extraction", "prompt", "{}", "Daily 待办清单与提醒分流"
            )

        self.assertEqual(result["status"], "done")
        self.assertEqual(generate.call_args.kwargs["max_retries"], 1)
        self.assertEqual(generate.call_args.kwargs["capacity_max_retries"], 2)

    def test_daily_profile_surfaces_capacity_exhaustion_as_structured_error(self) -> None:
        client = ContentFlowClient("")
        settings = LLMProviderSettings(
            model="gpt-5.6-terra",
            base_url="openclaw://agent",
            api_key="codex_auth_file",
            api_type="openclaw_agent",
            timeout=120,
            thinking="medium",
            bin="/bin/openclaw",
            agent="feishu-daily",
            cwd="/tmp",
            codex_home="/home/ubuntu/.codex",
        )
        with patch.object(
            content_flow_client_module, "profile_config", return_value={"capacity_max_retries": 2}
        ), patch.object(
            content_flow_client_module, "load_profile_llm_settings", return_value=settings
        ), patch.object(
            content_flow_client_module,
            "generate_json_from_parts",
            side_effect=RuntimeError(
                "GatewayClientRequestError: Selected model is at capacity. Retry after 90 seconds.\n"
                "internal transport trace must not reach the user"
            ),
        ):
            result = client._call_profile_provider_json(
                "daily_task_extraction", "prompt", "{}", "待办清单与提醒分流"
            )

        self.assertEqual(result["status"], "pending_manual")
        self.assertEqual(result["error_code"], "DAILY_LLM_MODEL_AT_CAPACITY")
        self.assertEqual(result["detail"], "Selected model is at capacity. Retry after 90 seconds.")
        self.assertIn("直接重试原消息", result["suggested_action"])

    def test_daily_profile_keeps_generic_error_for_non_capacity_failure(self) -> None:
        client = ContentFlowClient("")
        settings = LLMProviderSettings(
            model="gpt-5.6-terra",
            base_url="openclaw://agent",
            api_key="codex_auth_file",
            api_type="openclaw_agent",
            timeout=120,
            bin="/bin/openclaw",
            agent="feishu-daily",
            cwd="/tmp",
            codex_home="/home/ubuntu/.codex",
        )
        with patch.object(content_flow_client_module, "profile_config", return_value={}), patch.object(
            content_flow_client_module, "load_profile_llm_settings", return_value=settings
        ), patch.object(
            content_flow_client_module, "generate_json_from_parts", side_effect=RuntimeError("invalid JSON")
        ):
            result = client._call_profile_provider_json(
                "daily_task_extraction", "prompt", "{}", "待办清单与提醒分流"
            )

        self.assertEqual(result["status"], "pending_manual")
        self.assertNotIn("error_code", result)
        self.assertIn("invalid JSON", result["reason"])

    def test_transcription_revision_missing_required_fields_remains_invalid(self) -> None:
        revised_note = {
            "title": "AI科普账号定位讨论",
            "summary": "修订后的整理",
            "speaker_notes": [],
            "labeled_transcript": [],
        }

        errors = validate_transcription_final_note_contract(revised_note)

        self.assertIn("missing required field: meeting_info", errors)
        self.assertIn("missing required field: conclusion_summary", errors)
        self.assertIn("missing required field: decision_list", errors)
        self.assertIn("missing required field: topic_cards", errors)
        self.assertIn("missing required field: action_items", errors)
        self.assertIn("missing required field: pending_decisions", errors)
        self.assertIn("missing required field: validation_hypotheses", errors)
        self.assertIn("empty required field: speaker_notes", errors)
        self.assertIn("empty required field: labeled_transcript", errors)

    def test_transcription_formatter_renders_canonical_role_labeled_turn(self) -> None:
        harness = TranscriptionFormatterHarness()

        formatted = harness._format_labeled_transcript(_role_labeled_transcript("提出账号定位问题。"))

        self.assertEqual(formatted, "说话人 A（产品推进方）：提出账号定位问题。")

    def test_transcription_final_note_contract_accepts_only_canonical_role_labeled_turns(self) -> None:
        base_note = _valid_transcription_final_note(
            title="AI科普账号定位讨论",
            speaker_notes=[
                {
                    "speaker_key": "speaker_a",
                    "display_name": "说话人 A",
                    "meeting_role": "账号定位讨论方",
                    "identity_evidence": "来源中的稳定发言立场",
                    "confidence": "中",
                }
            ],
            labeled_transcript=_role_labeled_transcript("讨论 AI 账号定位。"),
            archive_macro_summary="这次转写聚焦 AI 科普账号定位。",
            archive_summary_bullets=["讨论了 AI 工具体验。", "账号定位仍需继续验证。"],
        )

        self.assertEqual(validate_transcription_final_note_contract(base_note), [])

        legacy_key_flow_note = {
            **base_note,
            "labeled_transcript": [{"source": "audio-01", "key_flow": ["旧归纳文字。"]}],
        }
        errors = validate_transcription_final_note_contract(legacy_key_flow_note)
        self.assertTrue(any("labeled_transcript[0] missing required field: speaker_key" in error for error in errors))

    def test_transcription_final_note_contract_rejects_missing_or_unknown_labeled_transcript_shape(self) -> None:
        invalid_note = _valid_transcription_final_note(
            title="AI科普账号定位讨论",
            speaker_notes=[{"speaker": "说话人 A", "note": "主讲账号定位"}],
            labeled_transcript=[{"speaker_key": "speaker_a", "speaker": "说话人 A", "text": ""}],
            archive_macro_summary="这次转写聚焦 AI 科普账号定位。",
            archive_summary_bullets=["讨论了 AI 工具体验。"],
        )

        errors = validate_transcription_final_note_contract(invalid_note)

        self.assertTrue(any("labeled_transcript[0]" in error for error in errors))

    def test_parse_json_payload_prefers_structured_object_among_multiple_objects(self) -> None:
        payload = ContentFlowClient._parse_json_payload(
            '{"debug": "ignored"}\n正文：{"title":"体育训练软件定位讨论","pending_questions":[]}'
        )

        self.assertEqual(payload["title"], "体育训练软件定位讨论")

    def test_parse_json_payload_prefers_todo_intake_object(self) -> None:
        payload = ContentFlowClient._parse_json_payload(
            '{"debug": "ignored"}\n正文：{"mode":"structured_checklist","checklist_tree":[{"text":"购买","children":[{"text":"购买杠铃杆","children":[]}]}],"confidence":0.95}'
        )

        self.assertEqual(payload["mode"], "structured_checklist")
        self.assertEqual(payload["checklist_tree"][0]["text"], "购买")

    def test_activity_clean_preserves_wrapped_douyin_and_submission_form_links(self) -> None:
        client = ContentFlowClient("")
        raw_text = (
            "爆款范式参考：https://\n"
            "www.douyin.com/note/\n"
            "7644475419148913000\n"
            "填表将有机会获得官方流量扶持：抖音「请回答2026高考」返稿报名表：\n"
            "https://bytedance.larkoffice.com/\n"
            "sheets/\n"
            "Ho28s2373h4akNtWWz8cnxqZnhb"
        )
        payload = client._normalize_activity_clean_result(
            {
                "status": "done",
                "title": "毕业季有问必答话题活动",
                "source_links": [],
            },
            raw_text=raw_text,
        )

        self.assertIn(
            {"label": "爆款范式参考", "url": "https://www.douyin.com/note/7644475419148913000"},
            payload["source_links"],
        )
        self.assertIn(
            {"label": "返稿报名表", "url": "https://bytedance.larkoffice.com/sheets/Ho28s2373h4akNtWWz8cnxqZnhb"},
            payload["source_links"],
        )

    def test_activity_clean_preserves_generic_wrapped_activity_links(self) -> None:
        client = ContentFlowClient("")
        raw_text = (
            "平台活动入口：https://\n"
            "events.example.com/campaigns/\n"
            "summer-brief?from=feishu\n"
            "报名表：https://\n"
            "forms.example.com/apply/\n"
            "creator-2026"
        )
        payload = client._normalize_activity_clean_result(
            {
                "status": "done",
                "title": "夏季内容活动",
                "source_links": [],
            },
            raw_text=raw_text,
        )

        self.assertIn(
            {"label": "活动链接", "url": "https://events.example.com/campaigns/summer-brief?from=feishu"},
            payload["source_links"],
        )
        self.assertIn(
            {"label": "返稿报名表", "url": "https://forms.example.com/apply/creator-2026"},
            payload["source_links"],
        )

    def test_activity_clean_does_not_reconstruct_links_after_llm_failure(self) -> None:
        client = ContentFlowClient("")
        client._call_profile_provider_json = Mock(
            return_value={"status": "pending_manual", "reason": "LLM_TIMEOUT"}
        )

        payload = client.clean_activity_brief("报名表：https://\nforms.example.com/apply/creator-2026")

        self.assertEqual(payload, {"status": "pending_manual", "reason": "LLM_TIMEOUT"})

    def test_activity_clean_prompt_treats_publish_time_as_boost_date_evidence(self) -> None:
        client = ContentFlowClient("")
        calls = []

        def fake_clean(profile_name, prompt, user_content, stage):
            calls.append({"profile_name": profile_name, "prompt": prompt, "user_content": user_content, "stage": stage})
            return {
                "status": "done",
                "title": "毕业旅行有问必答",
                "platform": "抖音",
                "brief_summary": "活动摘要",
                "activity_time": "即日起-2026-06-30",
                "activity_time_start": "2026-06-18",
                "activity_time_end": "2026-06-30",
                "boost_date": "2026-06-18",
                "main_topic": "#毕业旅行有问必答",
                "activity_level": "平台",
                "reward": "",
                "participation_method": "发布图文或短视频",
                "participation_form": "图文或短视频",
                "filling_points": "填写返稿报名表",
                "submission_requirements": "发布时间：即日起；带话题发布并填表。",
                "subtopic_directions": [],
                "source_links": [],
                "activity_status": "进行中",
                "parse_status": "已解析",
                "missing_info": [],
            }

        client._call_profile_provider_json = fake_clean

        payload = client.clean_activity_brief("发布时间：即日起-2026年6月30日，填表后有机会获得官方流量扶持")

        self.assertEqual(calls[0]["profile_name"], "activity_cleaning")
        self.assertEqual(payload["boost_date"], "2026-06-18")
        self.assertIn("投稿时间", calls[0]["prompt"])
        self.assertIn("发布时间", calls[0]["prompt"])
        self.assertIn("抢占首波流量建议提前发布", calls[0]["prompt"])

    def test_activity_clean_prompt_extracts_creation_ready_title(self) -> None:
        client = ContentFlowClient("")
        calls = []

        def fake_clean(profile_name, prompt, user_content, stage):
            calls.append({"profile_name": profile_name, "prompt": prompt, "user_content": user_content, "stage": stage})
            return {
                "status": "done",
                "title": "毕业旅行前最该问清楚的事",
                "platform": "抖音",
                "brief_summary": "活动摘要",
                "activity_time": "",
                "activity_time_start": "",
                "activity_time_end": "",
                "boost_date": "",
                "main_topic": "#毕业旅行有问必答",
                "activity_level": "平台",
                "reward": "",
                "participation_method": "带话题发布毕业旅行问答内容",
                "participation_form": "图文或短视频",
                "filling_points": "",
                "submission_requirements": "",
                "subtopic_directions": [],
                "source_links": [],
                "activity_status": "进行中",
                "parse_status": "已解析",
                "missing_info": [],
            }

        client._call_profile_provider_json = fake_clean

        payload = client.clean_activity_brief("抖音请回答2026高考｜毕业旅行有问必答")

        self.assertEqual(calls[0]["profile_name"], "activity_cleaning")
        self.assertEqual(payload["title"], "毕业旅行前最该问清楚的事")
        self.assertIn("最适合直接创作的选题标题", calls[0]["prompt"])
        self.assertIn("抖音请回答2026高考｜毕业旅行有问必答", calls[0]["prompt"])
        self.assertIn("不要输出“毕业旅行有问必答”", calls[0]["prompt"])
        self.assertIn("subtopic_directions 作为子记录标题来源", calls[0]["prompt"])

    def test_loads_analysis_json_after_job_payload_has_no_analysis(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            media_dir = Path(tmp)
            analysis_path = media_dir / "analysis.json"
            analysis_path.write_text(
                json.dumps(
                    {
                        "title": "开源动捕工具把专业设备降到摄像头",
                        "summary": ["普通摄像头可以生成3D人体骨骼数据。"],
                        "primary_category": "AI/工具",
                        "secondary_category": "AI工具应用",
                        "action_plan": "1. 展示工具。2. 展示场景。3. 展示结果。",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            client = ContentFlowClient("", workspace_root=tmp)
            payload = client.complete_analysis_payload(
                "http://xhslink.com/o/example",
                {"status": "done", "media_dir": str(media_dir), "analysis_path": str(analysis_path)},
                wait=False,
            )

        self.assertEqual(payload["analysis"]["title"], "开源动捕工具把专业设备降到摄像头")

    def test_structured_analysis_missing_returns_pending_manual(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = ContentFlowClient("", workspace_root=tmp)
            payload = client.complete_analysis_payload(
                "http://xhslink.com/o/example",
                {
                    "status": "done",
                    "caption": "开源3D精准动捕工具，能导出多种格式\n#AI工具[话题]# #开源[话题]#",
                    "video_path": "/tmp/video.mp4",
                    "media_type": "video",
                },
                wait=False,
            )

        self.assertEqual(payload["status"], "pending_manual")
        self.assertEqual(payload["error_code"], "LLM_SEMANTIC_PERSISTENCE_REQUIRED")
        self.assertEqual(payload["reason"], "LLM_SEMANTIC_PERSISTENCE_REQUIRED:content_flow_structured_analysis_required")
        self.assertTrue(payload["analysis_completion_checked"])

    def test_completion_guard_preserves_terminal_failure_without_waiting(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            original_sleep = content_flow_client_module.time.sleep
            content_flow_client_module.time.sleep = Mock(side_effect=AssertionError("unexpected second analysis wait"))
            try:
                client = ContentFlowClient("", workspace_root=tmp)
                payload = client.complete_analysis_payload(
                    "http://xhslink.com/o/example",
                    {
                        "status": "pending_manual",
                        "error_code": "WECHAT_ARTICLE_BODY_EMPTY",
                        "reason": "公众号页面未包含可提取正文",
                        "media_dir": tmp,
                        "caption": "平台文案",
                    },
                    wait=True,
                )
            finally:
                content_flow_client_module.time.sleep = original_sleep

        self.assertEqual(payload["status"], "pending_manual")
        self.assertEqual(payload["error_code"], "WECHAT_ARTICLE_BODY_EMPTY")
        self.assertEqual(payload["reason"], "公众号页面未包含可提取正文")
        self.assertTrue(payload["analysis_completion_checked"])

    def test_completion_guard_returns_terminal_llm_contract_failure_without_waiting(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            analysis_path = Path(tmp) / "analysis.json"
            analysis_path.write_text(
                json.dumps(
                    {
                        "analysis_status": "complete",
                        "analysis_provider": "openclaw_codex",
                        "semantic_persistence_version": "llm_cleaned_user_fields_v1",
                        "title": "Codex 联动 Mobbin 完成 UI 设计",
                        "full_content": "完整图文内容",
                        "work_copy": "",
                        "caption": "平台原始文案",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            original_sleep = content_flow_client_module.time.sleep
            content_flow_client_module.time.sleep = Mock(side_effect=AssertionError("terminal analysis must not be polled"))
            try:
                client = ContentFlowClient("", workspace_root=tmp)
                payload = client.complete_analysis_payload(
                    "http://xhslink.cn/o/example",
                    {
                        "status": "done",
                        "caption": "平台原始文案",
                        "media_dir": tmp,
                        "analysis_path": str(analysis_path),
                    },
                    wait=True,
                )
            finally:
                content_flow_client_module.time.sleep = original_sleep

        self.assertEqual(payload["status"], "pending_manual")
        self.assertEqual(payload["reason"], "LLM_SEMANTIC_PERSISTENCE_REQUIRED:llm_cleaned_work_copy_missing")
        self.assertTrue(payload["analysis_completion_checked"])

    def test_completion_guard_routes_all_media_analysis_kinds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            guard = CompletionGuard(ContentFlowClient("", workspace_root=tmp))
            for kind in ("content_flow_analysis", "自媒体知识"):
                payload = guard.complete_external_result(
                    kind=kind,
                    body="http://xhslink.com/o/example",
                    result={
                        "status": "done",
                        "caption": "开源3D精准动捕工具，能导出多种格式\n#AI工具[话题]#",
                        "video_path": "/tmp/video.mp4",
                        "media_type": "video",
                    },
                    wait=False,
                )
                self.assertEqual(payload["status"], "pending_manual")
                self.assertEqual(payload["reason"], "LLM_SEMANTIC_PERSISTENCE_REQUIRED:content_flow_structured_analysis_required")

    def test_wechat_article_analyze_extracts_text_images_and_structured_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            article_response = Mock()
            article_response.text = """
            <html><head>
              <meta property="og:title" content="公众号 AI 方法论">
              <meta name="keywords" content="AI,自媒体">
              <script>var nickname = "AI指南"; var publish_time = "2026-05-27";</script>
            </head><body>
              <div id="js_content">
                <h2>方法框架</h2>
                <p>第一段：用 AI 做选题，先拆人群和痛点。</p>
                <ul><li>保留原文结构，不做再创作。</li></ul>
                <p>第二段：再把角度转成标题和内容结构。</p>
                <img data-src="https://mmbiz.qpic.cn/mmbiz_jpg/example/0?wx_fmt=jpeg">
              </div>
            </body></html>
            """
            article_response.raise_for_status.return_value = None

            image_response = Mock()
            image_response.content = _jpeg_bytes(1206, 1608)
            image_response.headers = {"Content-Type": "image/jpeg"}
            image_response.raise_for_status.return_value = None

            client = ContentFlowClient("", workspace_root=tmp)
            client.session.get = Mock(side_effect=[article_response, image_response])

            cleaning_result = {
                "status": "done",
                "postprocess_provider": "codex_responses",
                "postprocess_model": "gpt-5.6-terra",
                "full_content": "## 方法框架\n\n第一段：用 AI 做选题，先拆人群和痛点。\n\n- 保留原文结构，不做再创作。\n\n第二段：再把角度转成标题和内容结构。",
            }
            semantic_result = {
                "status": "done",
                "title": "公众号 AI 方法论",
                "work_copy": "用 AI 做选题，先拆人群和痛点，再把角度转成标题和内容结构。",
                "summary": "先拆人群和痛点，再把角度转成标题与内容结构。",
                "breakdown": ["拆人群", "拆痛点", "转标题和结构"],
                "hooks": ["先拆人群和痛点"],
                "action_plan": "做选题时先定义受众、痛点和角度，再写标题。",
                "hidden_info": "选题不是直接要标题，而是先明确问题场景。",
                "visual_cues": "正文有 1 张图片；未对图片内容做视觉解读。",
                "transferable_expression": "先拆人群和痛点，再转成标题和内容结构。",
                "target_audience": "AI 自媒体创作者",
                "pain_point": "选题和标题同质化",
                "primary_category": "AI/工具",
                "secondary_category": ["AI工具应用", "内容运营"],
                "tags": ["AI", "自媒体", "选题方法"],
                "questions": ["如何把受众痛点转成标题？"],
                "open_questions": ["图片内容未做视觉识别。"],
                "risks": "需要结合账号定位验证。",
            }
            with patch.object(
                ContentFlowClient,
                "_call_profile_provider_json",
                side_effect=[cleaning_result, {"status": "done", "full_content": "公众号平台正文"}, semantic_result],
            ) as llm_mock:
                payload = client.analyze("【自媒体知识】\n链接：https://mp.weixin.qq.com/s/example")
            self.assertTrue(Path(payload["structure_path"]).is_file())
            saved_analysis = json.loads(Path(payload["analysis_path"]).read_text(encoding="utf-8"))

        self.assertEqual(llm_mock.call_count, 3)

        self.assertEqual(payload["status"], "done")
        self.assertEqual(payload["media_type"], "article")
        self.assertEqual(payload["analysis"]["platform"], "公众号")
        self.assertEqual(payload["analysis"]["analysis_provider"], "wechat-article-llm")
        self.assertEqual(payload["analysis"]["source_analysis_provider"], "wechat-article-extractor")
        self.assertEqual(payload["analysis"]["analysis_status"], "llm_structured")
        self.assertEqual(payload["analysis"]["summary"], "先拆人群和痛点，再把角度转成标题与内容结构。")
        self.assertEqual(payload["analysis"]["primary_category"], "AI/工具")
        self.assertEqual(payload["analysis"]["secondary_category"], ["AI工具应用", "内容运营"])
        self.assertIn("第一段：用 AI 做选题", payload["caption"])
        self.assertIn("## 方法框架", payload["analysis"]["full_content"])
        self.assertIn("- 保留原文结构", payload["analysis"]["full_content"])
        self.assertEqual(saved_analysis["analysis_status"], "llm_structured")
        self.assertEqual(len(payload["image_paths"]), 1)

    def test_wechat_article_fetch_failure_has_fetch_error_code(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            article_response = Mock()
            article_response.raise_for_status.side_effect = RuntimeError("403 Forbidden")

            client = ContentFlowClient("", workspace_root=tmp)
            client.session.get = Mock(return_value=article_response)

            payload = client.analyze("【自媒体知识】\n链接：https://mp.weixin.qq.com/s/example")

        self.assertEqual(payload["status"], "pending_manual")
        self.assertEqual(payload["error_code"], "WECHAT_ARTICLE_FETCH_FAILED")
        self.assertIn("公众号图文抓取失败", payload["reason"])

    def test_wechat_dynamic_page_uses_embedded_complete_source_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            article_response = Mock()
            article_response.text = r"""
            <html><head><meta property="og:title" content="动态公众号文章"></head><body>
              <script>
                window.cgiDataNew = {
                  nick_name: '来源账号',
                  title: '动态公众号文章',
                  content_noencode: '第一段：完整来源正文。\x0a\x0a第二段：不是页面摘要。',
                  create_time: '2026-07-10 14:20',
                  author: '原作者'
                };
              </script>
              <div id="js_article"><div id="js_base_container"></div></div>
            </body></html>
            """
            article_response.raise_for_status.return_value = None

            client = ContentFlowClient("", workspace_root=tmp)
            client.session.get = Mock(return_value=article_response)
            semantic_result = {
                "status": "done",
                "title": "动态公众号文章",
                "work_copy": "第一段：完整来源正文。第二段：不是页面摘要。",
                "summary": "两段完整来源正文。",
                "primary_category": "学习/认知",
                "secondary_category": ["认知方法"],
                "tags": ["公众号", "认知"],
            }
            with patch.object(
                ContentFlowClient,
                "_call_profile_provider_json",
                side_effect=[
                    {"status": "done", "full_content": "第一段：完整来源正文。\n\n第二段：不是页面摘要。"},
                    {"status": "done", "full_content": "页面摘要"},
                    semantic_result,
                ],
            ):
                payload = client.analyze("【自媒体知识】https://mp.weixin.qq.com/s/dynamic")

        self.assertEqual(payload["status"], "done")
        self.assertEqual(payload["analysis"]["source_layout"], "cgi_data_content")
        self.assertEqual(payload["analysis"]["account_name"], "来源账号")
        self.assertIn("第一段：完整来源正文。", payload["caption"])
        self.assertIn("第二段：不是页面摘要。", payload["caption"])
        self.assertGreaterEqual(payload["diagnostics"]["extracted_blocks"], 2)

    def test_wechat_picture_page_info_list_is_the_full_image_source(self) -> None:
        client = ContentFlowClient("")
        article = client._parse_wechat_article_html(
            """
            <script>
              window.cgiDataNew = {
                content_noencode: '完整正文',
                cdn_url: 'https://mmbiz.qpic.cn/cover/0?wx_fmt=jpeg'
              };
              window.picture_page_info_list = [
                {width: '1206' * 1, height: '1999' * 1, cdn_url: 'https://mmbiz.qpic.cn/full-01/0?wx_fmt=jpeg'},
                {width: '1206' * 1, height: '2008' * 1, cdn_url: 'https://mmbiz.qpic.cn/full-02/0?wx_fmt=jpeg'}
              ];
            </script>
            """
        )

        self.assertEqual([item["url"] for item in article["image_sources"]], [
            "https://mmbiz.qpic.cn/full-01/0?wx_fmt=jpeg",
            "https://mmbiz.qpic.cn/full-02/0?wx_fmt=jpeg",
        ])
        self.assertEqual(article["image_sources"][0]["width"], 1206)
        self.assertEqual(article["image_sources"][1]["height"], 2008)
        self.assertNotIn("cover", " ".join(article["image_urls"]))

    def test_wechat_article_refuses_incomplete_source_image_download(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            article_response = Mock()
            article_response.text = """
            <script>
              window.cgiDataNew = {title: '图集文章', content_noencode: '完整正文'};
              window.picture_page_info_list = [
                {width: '1206' * 1, height: '1999' * 1, cdn_url: 'https://mmbiz.qpic.cn/full-01/0?wx_fmt=jpeg'},
                {width: '1206' * 1, height: '2008' * 1, cdn_url: 'https://mmbiz.qpic.cn/full-02/0?wx_fmt=jpeg'}
              ];
            </script>
            """
            article_response.raise_for_status.return_value = None
            first_image_response = Mock()
            first_image_response.content = _jpeg_bytes(1206, 1999)
            first_image_response.raise_for_status.return_value = None
            second_image_response = Mock()
            second_image_response.content = _jpeg_bytes(1206, 1608)
            second_image_response.raise_for_status.return_value = None

            client = ContentFlowClient("", workspace_root=tmp)
            client.session.get = Mock(side_effect=[article_response, first_image_response, second_image_response])
            with patch.object(ContentFlowClient, "_call_profile_provider_json") as llm_mock:
                payload = client.analyze("【自媒体知识】https://mp.weixin.qq.com/s/incomplete-images")

        self.assertEqual(payload["status"], "pending_manual")
        self.assertEqual(payload["error_code"], "WECHAT_ARTICLE_IMAGE_DOWNLOAD_INCOMPLETE")
        self.assertEqual(payload["diagnostics"]["expected_source_image_count"], 2)
        self.assertEqual(payload["diagnostics"]["downloaded_source_image_count"], 1)
        self.assertEqual(payload["diagnostics"]["failed_source_image_count"], 1)
        self.assertEqual(len(payload["image_paths"]), 1)
        llm_mock.assert_not_called()

    def test_wechat_picture_gallery_uses_complete_ocr_as_full_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            article_response = Mock()
            article_response.text = """
            <script>
              window.cgiDataNew = {title: '图集文章', content_noencode: '页面摘要'};
              window.picture_page_info_list = [
                {width: '1206' * 1, height: '1999' * 1, cdn_url: 'https://mmbiz.qpic.cn/full-01/0?wx_fmt=jpeg'},
                {width: '1206' * 1, height: '2008' * 1, cdn_url: 'https://mmbiz.qpic.cn/full-02/0?wx_fmt=jpeg'}
              ];
            </script>
            """
            article_response.raise_for_status.return_value = None
            first_image_response = Mock(content=_jpeg_bytes(1206, 1999))
            first_image_response.raise_for_status.return_value = None
            second_image_response = Mock(content=_jpeg_bytes(1206, 2008))
            second_image_response.raise_for_status.return_value = None
            client = ContentFlowClient("", workspace_root=tmp)
            client.session.get = Mock(side_effect=[article_response, first_image_response, second_image_response])
            semantic_result = {
                "status": "done",
                "title": "图集文章",
                "summary": "图集全文已完成 OCR。",
                "primary_category": "学习/认知",
                "secondary_category": ["学习方法"],
                "tags": ["图集", "OCR"],
                "work_copy": {"platform_body": "语义模型对象不应进入用户字段"},
            }
            cleaning_result = {
                "status": "done",
                "full_content": "第一页完整文字\n\n第二页完整文字",
            }
            ocr_text = "## 01 image-01.jpg\n第一页完整文字\n\n## 02 image-02.jpg\n第二页完整文字"
            with patch.object(content_flow_client_module, "_extract_image_ocr", return_value=ocr_text) as ocr_mock, patch.object(
                ContentFlowClient,
                "_call_profile_provider_json",
                side_effect=[cleaning_result, {"status": "done", "full_content": "页面摘要"}, semantic_result],
            ) as llm_mock:
                payload = client.analyze("【自媒体知识】https://mp.weixin.qq.com/s/gallery-ocr")

        self.assertEqual(payload["status"], "done")
        self.assertEqual(payload["image_ocr"], ocr_text)
        self.assertEqual(payload["analysis"]["full_content"], "第一页完整文字\n\n第二页完整文字")
        self.assertEqual(payload["analysis"]["work_copy"], "页面摘要")
        self.assertEqual(payload["diagnostics"]["expected_source_image_ocr_count"], 2)
        self.assertEqual(payload["diagnostics"]["completed_source_image_ocr_count"], 2)
        ocr_mock.assert_called_once()
        self.assertEqual(llm_mock.call_count, 3)
        self.assertEqual(llm_mock.call_args_list[0].args[0], "content_cleaner")
        self.assertEqual(llm_mock.call_args_list[1].args[0], "content_cleaner")
        self.assertEqual(llm_mock.call_args_list[2].args[0], "media_analysis")
        llm_payload = json.loads(llm_mock.call_args_list[2].args[2])
        self.assertEqual(llm_payload["image_ocr"], ocr_text)

    def test_wechat_picture_gallery_requires_llm_cleaned_full_content(self) -> None:
        client = ContentFlowClient("")
        with patch.object(
            ContentFlowClient,
            "_call_profile_provider_json",
            return_value={
                "status": "done",
                "summary": "结构化摘要",
                "primary_category": "学习/认知",
                "secondary_category": ["学习方法"],
            },
        ):
            result = client._clean_wechat_gallery_ocr("图集文章", "## 01 image-01.jpg\n完整 OCR 文字")

        self.assertEqual(result["status"], "pending_manual")
        self.assertIn("full_content", result["reason"])

    def test_wechat_semantic_analysis_ignores_object_work_copy(self) -> None:
        client = ContentFlowClient("")
        with patch.object(
            ContentFlowClient,
            "_call_profile_provider_json",
            return_value={
                "status": "done",
                "title": "公众号图文标题",
                "work_copy": {"platform_body": "这不是可写入的文本字段"},
                "summary": "结构化摘要",
                "primary_category": "学习/认知",
                "secondary_category": ["学习方法"],
            },
        ):
            result = client._analyze_wechat_article_semantics(
                url="https://mp.weixin.qq.com/s/object-work-copy",
                article={"body_text": "原始公众号正文"},
                base_analysis={"title": "公众号图文标题", "full_content": "LLM 清洗后的全文"},
                image_count=0,
            )

        self.assertEqual(result["status"], "done")

    def test_wechat_picture_gallery_stops_when_any_ocr_page_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            article_response = Mock()
            article_response.text = """
            <script>
              window.cgiDataNew = {title: '图集文章', content_noencode: '页面摘要'};
              window.picture_page_info_list = [
                {width: '1206' * 1, height: '1999' * 1, cdn_url: 'https://mmbiz.qpic.cn/full-01/0?wx_fmt=jpeg'},
                {width: '1206' * 1, height: '2008' * 1, cdn_url: 'https://mmbiz.qpic.cn/full-02/0?wx_fmt=jpeg'}
              ];
            </script>
            """
            article_response.raise_for_status.return_value = None
            first_image_response = Mock(content=_jpeg_bytes(1206, 1999))
            first_image_response.raise_for_status.return_value = None
            second_image_response = Mock(content=_jpeg_bytes(1206, 2008))
            second_image_response.raise_for_status.return_value = None
            client = ContentFlowClient("", workspace_root=tmp)
            client.session.get = Mock(side_effect=[article_response, first_image_response, second_image_response])
            with patch.object(
                content_flow_client_module,
                "_extract_image_ocr",
                return_value="## 01 image-01.jpg\n仅有第一页文字",
            ), patch.object(ContentFlowClient, "_call_profile_provider_json") as llm_mock:
                payload = client.analyze("【自媒体知识】https://mp.weixin.qq.com/s/gallery-ocr-missing")

        self.assertEqual(payload["status"], "pending_manual")
        self.assertEqual(payload["error_code"], "WECHAT_ARTICLE_IMAGE_OCR_INCOMPLETE")
        self.assertEqual(payload["diagnostics"]["expected_source_image_ocr_count"], 2)
        self.assertEqual(payload["diagnostics"]["completed_source_image_ocr_count"], 1)
        self.assertEqual(payload["diagnostics"]["failed_source_image_ocr_count"], 1)
        llm_mock.assert_not_called()

    def test_wechat_body_empty_error_is_not_rewritten_as_llm_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            article_response = Mock()
            article_response.text = "<html><body><div id='js_base_container'></div></body></html>"
            article_response.raise_for_status.return_value = None
            client = ContentFlowClient("", workspace_root=tmp)
            client.session.get = Mock(return_value=article_response)
            payload = client.analyze("【自媒体知识】https://mp.weixin.qq.com/s/empty")

            with patch.object(content_flow_client_module.time, "sleep", side_effect=AssertionError("terminal failure must not wait")):
                completed = client.complete_analysis_payload(
                    "https://mp.weixin.qq.com/s/empty",
                    payload,
                    wait=True,
                )

        self.assertEqual(completed["error_code"], "WECHAT_ARTICLE_BODY_EMPTY")
        self.assertEqual(completed["reason"], "公众号页面未包含可提取正文")
        self.assertEqual(completed["diagnostics"]["extracted_characters"], 0)

    def test_wechat_article_analyze_remains_pending_when_llm_fields_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            article_response = Mock()
            article_response.text = """
            <html><head><meta property="og:title" content="公众号 AI 方法论"></head><body>
              <div id="js_content"><p>第一段：用 AI 做选题，先拆人群和痛点。</p></div>
            </body></html>
            """
            article_response.raise_for_status.return_value = None

            client = ContentFlowClient("", workspace_root=tmp)
            client.session.get = Mock(return_value=article_response)

            with patch.object(
                ContentFlowClient,
                "_call_profile_provider_json",
                side_effect=[
                    {"status": "done", "full_content": "第一段：用 AI 做选题，先拆人群和痛点。"},
                    {"status": "done", "full_content": "第一段：用 AI 做选题，先拆人群和痛点。"},
                    {"status": "done", "summary": "只有摘要，缺少分类。"},
                ],
            ):
                payload = client.analyze("【自媒体知识】\n链接：https://mp.weixin.qq.com/s/example")
            saved_analysis = json.loads(Path(payload["analysis_path"]).read_text(encoding="utf-8"))

        self.assertEqual(payload["status"], "pending_manual")
        self.assertEqual(payload["error_code"], "LLM_SEMANTIC_PERSISTENCE_REQUIRED")
        self.assertIn("wechat_article_semantic_analysis_required", payload["reason"])
        self.assertIn("primary_category", payload["reason"])
        self.assertEqual(payload["analysis"]["analysis_status"], "needs_model_rerun")
        self.assertEqual(saved_analysis["incomplete_reason"], "wechat_article_semantic_analysis_required")

    def test_selfmedia_knowledge_reply_uses_fetch_error_code(self) -> None:
        harness = KnowledgeFieldHarness()
        harness.rule_service = Mock()
        harness.rule_service.get_tag_rule.return_value = {"detect_links": True}
        harness.content_flow_client = Mock()
        harness.content_flow_client.analyze.return_value = {
            "status": "pending_manual",
            "error_code": "WECHAT_ARTICLE_FETCH_FAILED",
            "reason": "公众号图文抓取失败：403 Forbidden",
            "media_type": "article",
        }
        harness.completion_guard = Mock()
        harness.completion_guard.complete_external_result.side_effect = lambda **kwargs: kwargs["result"]
        message = Message(
            entry_tag="自媒体知识",
            raw_text="【自媒体知识】 https://mp.weixin.qq.com/s/example",
            body="https://mp.weixin.qq.com/s/example",
            source="feishu",
            created_at=datetime(2026, 7, 4, 23, 20),
        )

        result = harness._handle_selfmedia_knowledge(message)

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "wechat_article_fetch_failed")
        self.assertIn("错误代码：WECHAT_ARTICLE_FETCH_FAILED", result.reply)
        self.assertIn("公众号图文抓取失败", result.reply)
        self.assertIn("详情：", result.reply)
        self.assertIn("建议：", result.reply)

    def test_selfmedia_knowledge_reply_keeps_llm_error_code_for_semantic_failure(self) -> None:
        harness = KnowledgeFieldHarness()

        error_code, public_reason, status_code = harness._selfmedia_knowledge_failure(
            {},
            "LLM_SEMANTIC_PERSISTENCE_REQUIRED:wechat_article_semantic_analysis_required:缺少 primary_category",
        )

        self.assertEqual(error_code, "LLM_SEMANTIC_PERSISTENCE_REQUIRED")
        self.assertEqual(public_reason, "wechat_article_semantic_analysis_required:缺少 primary_category")
        self.assertEqual(status_code, "llm_semantic_persistence_required")

    def test_run_job_recovers_video_path_from_media_dir_when_status_payload_omits_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            media_dir = Path(tmp)
            video_path = media_dir / "video.mp4"
            video_path.write_bytes(b"video")

            post_response = Mock()
            post_response.json.return_value = {"job_id": "job-1"}
            post_response.raise_for_status.return_value = None

            status_response = Mock()
            status_response.json.return_value = {
                "status": "done",
                "result": {
                    "media_dir": str(media_dir),
                    "media_type": "video",
                    "caption": "平台文案",
                },
            }
            status_response.raise_for_status.return_value = None

            client = ContentFlowClient("http://content-flow.test", workspace_root=tmp)
            client.poll_attempts = 1
            client.session.post = Mock(return_value=post_response)
            client.session.get = Mock(return_value=status_response)

            payload = client._run_job("/api/download", "https://www.douyin.com/video/123")

        self.assertEqual(payload["status"], "done")
        self.assertEqual(payload["video_path"], str(video_path))
        self.assertEqual(payload["media_dir"], str(media_dir))

    def test_analyze_job_poll_budget_uses_structured_analysis_wait_seconds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ,
            {"CONTENT_FLOW_ANALYSIS_WAIT_SECONDS": "3"},
        ), patch.object(content_flow_client_module.time, "sleep") as sleep_mock:
            post_response = Mock()
            post_response.json.return_value = {"job_id": "job-structured"}
            post_response.raise_for_status.return_value = None

            status_response = Mock()
            status_response.json.return_value = {"status": "running"}
            status_response.raise_for_status.return_value = None

            client = ContentFlowClient("http://content-flow.test", poll_interval_seconds=1, poll_attempts=1, workspace_root=tmp)
            client.session.post = Mock(return_value=post_response)
            client.session.get = Mock(return_value=status_response)

            payload = client._run_job("/api/analyze", "http://xhslink.com/o/example")

        self.assertEqual(client.session.get.call_count, 3)
        self.assertEqual(sleep_mock.call_count, 3)
        self.assertEqual(payload["status"], "pending_manual")
        self.assertIn("轮询超时 job_id=job-structured", payload["reason"])

    def test_image_knowledge_stores_images_in_original_file_attachment_field(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            image_path = Path(tmp) / "note.jpg"
            image_path.write_bytes(b"image")
            payload = {
                "status": "done",
                "caption": "用 AI 做自媒体选题，不要只说帮我想 10 个标题",
                "image_ocr": "## 01 image-01.jpg\nAl 自媒体\n用Al做选题\n误区 €D\n第1页：先拆人群、痛点、角度\n€D",
                "image_paths": [str(image_path)],
                "media_type": "image",
                "analysis": {
                    "title": "AI 自媒体选题方法",
                    "summary": "先拆人群痛点，再产出标题。",
                    "platform": "小红书",
                    "media_type": "image",
                    "primary_category": "AI/工具",
                    "secondary_category": "AI工具应用",
                    "target_audience": "AI 小白",
                    "pain_point": "标题同质化",
                    "analysis_provider": "codex_responses",
                    "analysis_status": "complete",
                    "semantic_persistence_version": "llm_cleaned_user_fields_v1",
                    "work_copy": "用 AI 做自媒体选题，先拆人群和痛点。",
                    "full_content": "第 1 页：AI 自媒体选题。先拆人群、痛点和角度。",
                },
            }
            harness = KnowledgeFieldHarness()
            fields = harness._knowledge_extra_fields("http://xhslink.com/o/example", payload)

        self.assertEqual(fields["内容类型"], "图文")
        self.assertIn("全部文案", fields)
        self.assertEqual(fields["全部文案"], "用 AI 做自媒体选题，先拆人群和痛点。")
        self.assertIn("全部内容", fields)
        self.assertEqual(fields["全部内容"], "第 1 页：AI 自媒体选题。先拆人群、痛点和角度。")
        self.assertEqual(fields["目标人群"], "AI 小白")
        self.assertEqual(fields["核心痛点"], "标题同质化")
        self.assertEqual(fields["_attachment_fields"], {"原文件": [str(image_path)]})

    def test_llm_work_copy_is_written_instead_of_raw_caption(self) -> None:
        payload = {
            "status": "done",
            "caption": "原始平台文案",
            "image_ocr": "## 01 image-01.jpg\nAl 噪声",
            "media_type": "image",
                "analysis": {
                    "title": "AI 自媒体选题方法",
                    "summary": "先拆人群痛点，再产出标题。",
                    "platform": "小红书",
                    "media_type": "image",
                    "primary_category": "AI/工具",
                    "secondary_category": "AI工具应用",
                    "work_copy": "模型清洗后的正文",
                    "full_content": "第 1 页：AI 自媒体选题方法。",
                    "analysis_provider": "codex_responses",
                    "analysis_status": "complete",
                    "semantic_persistence_version": "llm_cleaned_user_fields_v1",
                },
        }
        harness = KnowledgeFieldHarness()
        fields = harness._knowledge_extra_fields("http://xhslink.com/o/example", payload)

        self.assertEqual(fields["全部文案"], "模型清洗后的正文")
        self.assertEqual(fields["全部内容"], "第 1 页：AI 自媒体选题方法。")
        metadata = fields["_llm_semantic_persistence"]
        self.assertEqual(metadata["analysis_provider"], "codex_responses")
        self.assertIn("source_url", metadata["raw_evidence"])
        self.assertIn("全部内容", metadata["field_digests"])

    def test_analysis_full_content_writes_to_knowledge_full_content_without_raw_ocr(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            image_path = Path(tmp) / "note.jpg"
            image_path.write_bytes(b"image")
            payload = {
                "status": "done",
                "caption": "平台正文只进入全部文案",
                "image_paths": [str(image_path)],
                "media_type": "图文",
                "analysis": {
                    "title": "Codex 把备课素材整理成教案",
                    "summary": "两张素材图生成可编辑教案。",
                    "platform": "小红书",
                    "media_type": "图文",
                    "primary_category": "AI/工具",
                    "secondary_category": ["AI工具应用"],
                    "target_audience": "教师",
                    "pain_point": "备课材料整理耗时",
                    "work_copy": "模型正文不应覆盖平台正文",
                    "full_content": "第 1 页：数学老师的省时备课法。\n第 2 页：教材目录 + 手写思路图。",
                    "analysis_provider": "codex_responses",
                    "analysis_status": "complete",
                    "semantic_persistence_version": "llm_cleaned_user_fields_v1",
                },
            }
            harness = KnowledgeFieldHarness()
            fields = harness._knowledge_extra_fields("http://xhslink.com/o/example", payload)

        self.assertEqual(fields["全部文案"], "模型正文不应覆盖平台正文")
        self.assertEqual(fields["全部内容"], "第 1 页：数学老师的省时备课法。\n第 2 页：教材目录 + 手写思路图。")
        self.assertEqual(fields["_attachment_fields"], {"原文件": [str(image_path)]})

    def test_analysis_full_content_writes_to_knowledge_full_content_without_raw_ocr(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            image_path = Path(tmp) / "note.jpg"
            image_path.write_bytes(b"image")
            payload = {
                "status": "done",
                "caption": "平台正文只进入全部文案",
                "image_paths": [str(image_path)],
                "media_type": "图文",
                "analysis": {
                    "title": "Codex 把备课素材整理成教案",
                    "summary": "两张素材图生成可编辑教案。",
                    "platform": "小红书",
                    "media_type": "图文",
                    "primary_category": "AI/工具",
                    "secondary_category": ["AI工具应用"],
                    "target_audience": "教师",
                    "pain_point": "备课材料整理耗时",
                    "work_copy": "平台正文只进入全部文案",
                    "full_content": "第 1 页：数学老师的省时备课法。\n第 2 页：教材目录 + 手写思路图。",
                    "analysis_provider": "codex_responses",
                    "analysis_status": "complete",
                    "semantic_persistence_version": "llm_cleaned_user_fields_v1",
                },
            }
            harness = KnowledgeFieldHarness()
            fields = harness._knowledge_extra_fields("http://xhslink.com/o/example", payload)

        self.assertEqual(fields["全部文案"], "平台正文只进入全部文案")
        self.assertEqual(fields["全部内容"], "第 1 页：数学老师的省时备课法。\n第 2 页：教材目录 + 手写思路图。")
        self.assertEqual(fields["_attachment_fields"], {"原文件": [str(image_path)]})

    def test_video_transcript_uses_full_content_field(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            media_dir = Path(tmp)
            video_path = media_dir / "video.mp4"
            transcript_path = media_dir / "transcript.txt"
            video_path.write_bytes(b"video")
            transcript_path.write_text(
                "[音乐]\n嗯嗯 然后 这是视频语音转写内容\n这是视频语音转写内容\n<|nospeech|>",
                encoding="utf-8",
            )
            payload = {
                "status": "done",
                "media_dir": str(media_dir),
                "video_path": str(video_path),
                "transcript_path": str(transcript_path),
                "caption": "这是平台文案",
                "media_type": "video",
                "analysis": {
                    "title": "视频内容方法论",
                    "summary": "视频说明了一个方法。",
                    "platform": "抖音",
                    "media_type": "video",
                    "primary_category": "AI/工具",
                    "secondary_category": "AI工具应用",
                    "tags": ["模型标签"],
                    "work_copy": "这是清洗后的平台文案。",
                    "full_content": "这是清洗后的视频语音转写内容。",
                    "analysis_provider": "codex_responses",
                    "analysis_status": "complete",
                    "semantic_persistence_version": "llm_cleaned_user_fields_v1",
                },
            }
            harness = KnowledgeFieldHarness()
            fields = harness._knowledge_extra_fields("http://example.com/video", payload)

        self.assertEqual(fields["内容类型"], "短视频")
        self.assertEqual(fields["全部文案"], "这是清洗后的平台文案。")
        self.assertNotIn("模型标签", fields["全部文案"])
        self.assertEqual(fields["全部内容"], "这是清洗后的视频语音转写内容。")
        self.assertNotIn("这是视频语音转写内容", fields["全部文案"])
        self.assertNotIn("全部视频脚本", fields)
        self.assertEqual(fields["_attachment_fields"], {"原文件": [str(video_path)]})
        self.assertNotIn("local_video_path=", fields.get("待验证问题", ""))

    def test_knowledge_source_url_prefers_content_flow_resolved_url(self) -> None:
        body = "6.66 复制打开抖音，看看这个视频 https://v.douyin.com/short-token/"
        payload = {
            "status": "done",
            "caption": "平台文案",
            "media_type": "video",
            "analysis": {
                "title": "视频内容方法论",
                "summary": "视频说明了一个方法。",
                "platform": "抖音",
                "media_type": "video",
                "source_url": "https://www.douyin.com/video/7632178370587046586",
                "full_content": "这是视频逐字稿。",
                "work_copy": "这是清洗后的平台文案。",
                "primary_category": "AI/工具",
                "secondary_category": "AI工具应用",
                "analysis_provider": "codex_responses",
                "analysis_status": "complete",
                "semantic_persistence_version": "llm_cleaned_user_fields_v1",
            },
        }
        harness = KnowledgeFieldHarness()

        fields = harness._knowledge_extra_fields(body, payload)

        self.assertEqual(fields["原链接"], "https://www.douyin.com/video/7632178370587046586")

    def test_wechat_article_knowledge_fields_use_article_body_and_image_attachments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            image_path = Path(tmp) / "article.jpg"
            image_path.write_bytes(b"image")
            payload = {
                "status": "done",
                "caption": "第一段：用 AI 做选题，先拆人群和痛点。\n第二段：再把角度转成标题和内容结构。",
                "image_paths": [str(image_path)],
                "media_type": "article",
                "analysis": {
                    "title": "公众号 AI 方法论",
                    "summary": ["公众号图文正文已提取入库。"],
                    "platform": "公众号",
                    "media_type": "article",
                    "primary_category": "AI/工具",
                    "secondary_category": "AI工具应用",
                    "work_copy": "先拆人群和痛点，再把角度转成标题和内容结构。",
                    "full_content": "## 方法框架\n\n第一段：用 AI 做选题，先拆人群和痛点。\n\n- 保留原文结构，不做再创作。\n\n第二段：再把角度转成标题和内容结构。",
                    "tags": ["AI", "自媒体"],
                    "analysis_provider": "wechat-article-llm",
                    "analysis_status": "llm_structured",
                    "semantic_persistence_version": "llm_cleaned_user_fields_v1",
                },
            }
            harness = KnowledgeFieldHarness()
            fields = harness._knowledge_extra_fields("https://mp.weixin.qq.com/s/example", payload)

        self.assertEqual(fields["来源平台"], "公众号")
        self.assertEqual(fields["内容类型"], "图文")
        self.assertEqual(fields["全部文案"], "先拆人群和痛点，再把角度转成标题和内容结构。")
        self.assertIn("## 方法框架", fields["全部内容"])
        self.assertIn("- 保留原文结构", fields["全部内容"])
        self.assertIn("第二段：再把角度转成标题", fields["全部内容"])
        self.assertEqual(fields["_attachment_fields"], {"原文件": [str(image_path)]})

    def test_douyin_image_post_does_not_require_video(self) -> None:
        body = "9.28 复制打开抖音，看看【迷雾院长的图文作品】男人必懂的10个恋爱心理学。 https://v.douyin.com/example/"
        payload = {
            "status": "done",
            "caption": "男人必懂的10个恋爱心理学。",
            "media_type": "unknown",
            "analysis": {
                "title": "恋爱心理学包装下的情绪拿捏风险",
                "summary": ["用巴纳姆效应解释恋爱中“被懂”的错觉。"],
                "primary_category": "学习/认知",
                "secondary_category": ["心理认知", "关系风险", "案例拆解"],
                "platform": "抖音",
                "media_type": "unknown",
                "full_content": "男人必懂的10个恋爱心理学。",
                "work_copy": "男人必懂的 10 个恋爱心理学。",
                "analysis_provider": "openclaw",
                "analysis_status": "complete",
                "semantic_persistence_version": "llm_cleaned_user_fields_v1",
            },
        }
        harness = KnowledgeFieldHarness()

        self.assertFalse(harness._selfmedia_knowledge_requires_video(body, payload))
        self.assertEqual(harness._knowledge_completion_issue(payload, require_video=False), "")
        self.assertEqual(harness._knowledge_content_type(body, payload, "抖音"), "图文")
        fields = harness._knowledge_extra_fields(body, payload)
        self.assertEqual(fields["内容类型"], "图文")
        self.assertEqual(fields["二级分类"], ["心理认知", "关系风险", "案例拆解"])

    def test_knowledge_secondary_categories_use_standard_values(self) -> None:
        harness = KnowledgeFieldHarness()
        fields = harness._knowledge_category_fields(
            {
                "primary_category": "运营/管理",
                "secondary_category": ["平台机制", "内容增长", "创作者变现"],
            },
            "小红书新规让普通创作者获得流量和变现窗口",
        )

        self.assertEqual(fields["二级分类"], ["算法拆解/增长", "自媒体运营"])

    def test_incomplete_analysis_is_not_treated_as_structured_for_knowledge_archive(self) -> None:
        harness = KnowledgeFieldHarness()

        self.assertFalse(
            harness._knowledge_has_structured_analysis(
                {
                    "analysis_status": "needs_model_rerun",
                    "incomplete_reason": "primary_analysis_unavailable",
                    "summary": [],
                }
            )
        )

    def test_knowledge_fields_reject_raw_ocr_and_transcript_without_llm_cleaning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            transcript_path = Path(tmp) / "transcript.txt"
            transcript_path.write_text("原始 ASR 逐字稿", encoding="utf-8")
            payload = {
                "status": "done",
                "caption": "原始平台文案",
                "transcript_path": str(transcript_path),
                "image_ocr": "## 01 image.jpg\n原始 OCR 文本",
                "analysis": {
                    "summary": "虽然存在摘要，但没有清洗用户字段。",
                    "primary_category": "AI/工具",
                    "secondary_category": ["AI工具应用"],
                    "analysis_provider": "codex_responses",
                    "analysis_status": "complete",
                },
            }
            harness = KnowledgeFieldHarness()

            with self.assertRaisesRegex(ValueError, "llm_cleaning_provenance_missing"):
                harness._knowledge_extra_fields("https://example.com/post", payload)

    def test_completion_issue_blocks_archive_when_analysis_is_incomplete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            media_dir = Path(tmp)
            video_path = media_dir / "video.mp4"
            transcript_path = media_dir / "transcript.txt"
            video_path.write_bytes(b"video")
            transcript_path.write_text("正式逐字稿", encoding="utf-8")
            harness = KnowledgeFieldHarness()

            issue = harness._knowledge_completion_issue(
                {
                    "status": "done",
                    "media_dir": str(media_dir),
                    "video_path": str(video_path),
                    "transcript_path": str(transcript_path),
                    "caption": "平台文案",
                    "media_type": "video",
                    "analysis": {
                        "analysis_status": "needs_model_rerun",
                        "incomplete_reason": "primary_analysis_unavailable",
                        "summary": [],
                    },
                },
                require_video=True,
            )

        self.assertIn("结构化分析需要重新运行模型", issue)

    def test_video_caption_only_blocks_knowledge_archive_without_full_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            media_dir = Path(tmp)
            video_path = media_dir / "video.mp4"
            video_path.write_bytes(b"video")
            harness = KnowledgeFieldHarness()

            issue = harness._knowledge_completion_issue(
                {
                    "status": "done",
                    "media_dir": str(media_dir),
                    "video_path": str(video_path),
                    "caption": "一定要大量的记录自己，因为频繁的记录自己能改命#认知",
                    "media_type": "video",
                    "analysis": {
                        "title": "频繁记录自己才是普通人的改命入口",
                        "summary": ["把记录自己包装成低门槛方法。"],
                        "platform": "抖音",
                        "media_type": "video",
                        "primary_category": "学习/认知",
                        "secondary_category": ["心理认知"],
                    },
                },
                require_video=True,
            )

        self.assertEqual(issue, "content-flow 未产出视频逐字稿、OCR 或全部内容")

    def test_selfmedia_knowledge_writes_obsidian_markdown_card(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            old_root = os.environ.get("CONTENT_OS_VAULT_ROOT")
            os.environ["CONTENT_OS_VAULT_ROOT"] = tmp
            try:
                harness = KnowledgeFieldHarness()
                message = Message(
                    entry_tag="自媒体知识",
                    raw_text="【自媒体知识】 https://v.douyin.com/example/",
                    body="https://v.douyin.com/example/",
                    source="feishu",
                    created_at=datetime(2026, 6, 11, 0, 30),
                )
                result = {
                    "status": "done",
                    "media_dir": "/tmp/douyin-7649061784112362610",
                        "analysis": {
                            "title": "拆解低门槛口播智能体的赚钱逻辑",
                            "video_id": "7649061784112362610",
                            "hooks": "千万销售额制造好奇。",
                            "score": 97,
                            "internal_only_marker": "must remain in analysis artifact only",
                            "image_ocr": "## 01 image-01.jpg\n原始 OCR 不应出现在知识卡。",
                    },
                }
                local_path = harness._write_selfmedia_knowledge_markdown(
                    message=message,
                    title="拆解低门槛口播智能体的赚钱逻辑",
                    result=result,
                    extra_fields={
                        "原链接": "https://v.douyin.com/example/",
                        "来源平台": "抖音",
                        "内容类型": "短视频",
                        "一级分类": "AI/工具",
                        "二级分类": ["AI视频/自动化"],
                        "摘要": "把成熟能力打包成一键应用。",
                        "全部文案": "蒸馏 #codex",
                        "全部内容": "今天拆解了一个爆款口播视频生成智能体。",
                        "应用建议": "复刻成低门槛应用。",
                    },
                    record_text="今天拆解了一个爆款口播视频生成智能体。",
                )
                path = Path(local_path)
                self.assertTrue(path.exists())
                self.assertIn("05_素材与爆款库/自媒体知识", local_path)
                text = path.read_text(encoding="utf-8")
                self.assertIn("doc_type: selfmedia_knowledge", text)
                self.assertIn("拆解低门槛口播智能体的赚钱逻辑", text)
                self.assertIn("今天拆解了一个爆款口播视频生成智能体。", text)
                self.assertNotIn("## 01 image-01.jpg", text)
                self.assertNotIn("结构化分析JSON", text)
                self.assertNotIn("internal_only_marker", text)
            finally:
                if old_root is None:
                    os.environ.pop("CONTENT_OS_VAULT_ROOT", None)
                else:
                    os.environ["CONTENT_OS_VAULT_ROOT"] = old_root

    def test_creation_without_project_id_skips_cloud_markdown_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            old_root = os.environ.get("CONTENT_OS_VAULT_ROOT")
            os.environ["CONTENT_OS_VAULT_ROOT"] = tmp
            try:
                harness = CreationPersistenceHarness()
                message = Message(
                    entry_tag="创作",
                    raw_text="【创作】平台=抖音 类型=视频 主体=AI口播生产管道",
                    body="平台=抖音 类型=视频 主体=AI口播生产管道",
                    source="feishu",
                    created_at=datetime(2026, 6, 11, 1, 0),
                )
                result = harness._write_standalone_creation_output(
                    message,
                    {
                        "ok": True,
                        "creation_record_id": "recCreation1",
                        "doc_link": "https://example.feishu.cn/doc",
                        "draft": {"title": "把AI口播从特效玩具变成生产管道"},
                        "reply": "这是创作稿正文",
                    },
                    "这是创作稿正文",
                )
                self.assertEqual(result, {})
                self.assertFalse((Path(tmp) / "03_脚本生产").exists())
            finally:
                if old_root is None:
                    os.environ.pop("CONTENT_OS_VAULT_ROOT", None)
                else:
                    os.environ["CONTENT_OS_VAULT_ROOT"] = old_root

    def test_creation_with_existing_material_intent_skips_cloud_project_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            old_root = os.environ.get("CONTENT_OS_VAULT_ROOT")
            old_md = os.environ.get("CONTENT_OS_CLOUD_MARKDOWN")
            os.environ["CONTENT_OS_VAULT_ROOT"] = tmp
            os.environ.pop("CONTENT_OS_CLOUD_MARKDOWN", None)
            try:
                harness = CreationPersistenceHarness()
                message = Message(
                    entry_tag="创作>抖音",
                    raw_text=(
                        "【创作>抖音】\n"
                        "类型：视频\n"
                        "赛道：教育、校园\n"
                        "主体：第一视角体验清华毕业典礼\n"
                        "素材/参考：抖音口令/链接...\n"
                        "希望产出：剪辑说明，已有素材"
                    ),
                    body="第一视角体验清华毕业典礼",
                    source="feishu",
                    created_at=datetime(2026, 6, 27, 12, 0),
                )
                result = harness._maybe_create_content_os_project_from_creation(
                    message,
                    {
                        "ok": True,
                        "creation_record_id": "run_001",
                        "doc_link": "https://example.feishu.cn/wiki/creation",
                        "request": {"platform": "抖音", "content_type": "视频", "track": "教育、校园", "topic": "第一视角体验清华毕业典礼"},
                        "draft": {"title": "第一视角体验清华毕业典礼", "production_checklist": ["毕业服", "典礼现场", "走位镜头"]},
                        "reply": "云端创作稿",
                    },
                    "云端创作稿",
                )
                self.assertEqual(result, {})
                self.assertFalse((Path(tmp) / "08_内容项目").exists())
                self.assertFalse((Path(tmp) / "03_脚本生产").exists())
            finally:
                if old_root is None:
                    os.environ.pop("CONTENT_OS_VAULT_ROOT", None)
                else:
                    os.environ["CONTENT_OS_VAULT_ROOT"] = old_root
                if old_md is None:
                    os.environ.pop("CONTENT_OS_CLOUD_MARKDOWN", None)
                else:
                    os.environ["CONTENT_OS_CLOUD_MARKDOWN"] = old_md

    def test_creation_with_editing_material_intent_creates_content_os_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            old_root = os.environ.get("CONTENT_OS_VAULT_ROOT")
            old_md = os.environ.get("CONTENT_OS_CLOUD_MARKDOWN")
            os.environ["CONTENT_OS_VAULT_ROOT"] = tmp
            os.environ["CONTENT_OS_CLOUD_MARKDOWN"] = "1"
            _write_content_os_v2_state_rules(Path(tmp))
            try:
                harness = CreationPersistenceHarness()
                message = Message(
                    entry_tag="创作>抖音",
                    raw_text=(
                        "【创作>抖音】\n"
                        "类型：视频\n"
                        "赛道：教育、校园\n"
                        "主体：第一视角体验清华毕业典礼\n"
                        "素材/参考：学业副本结算完毕 - 抖音复制口令\n"
                        "希望产出：剪辑说明，已有素材"
                    ),
                    body="第一视角体验清华毕业典礼",
                    source="feishu",
                    created_at=datetime(2026, 6, 27, 12, 0),
                )
                result = harness._maybe_create_content_os_project_from_creation(
                    message,
                    {
                        "ok": True,
                        "creation_record_id": "run_001",
                        "doc_link": "https://example.feishu.cn/wiki/creation",
                        "request": {"platform": "抖音", "content_type": "视频", "track": "教育、校园", "topic": "第一视角体验清华毕业典礼"},
                        "draft": {"title": "第一视角体验清华毕业典礼", "production_checklist": ["毕业服", "典礼现场", "走位镜头"]},
                        "reply": "云端创作稿",
                    },
                    "云端创作稿",
                )

                project_path = Path(result["project_path"])
                self.assertEqual(result["local_material_binding"], "unbound")
                self.assertTrue((project_path / "00_项目总览.md").exists())
                self.assertTrue((project_path / "04_script.md").exists())
                self.assertTrue((project_path / "09_publish_pack.md").exists())
                self.assertIn("Mac 素材未绑定", result["reply"])
                script_text = (project_path / "04_script.md").read_text(encoding="utf-8")
                self.assertIn("云端创作稿", script_text)
                self.assertIn("run_001", script_text)
            finally:
                if old_root is None:
                    os.environ.pop("CONTENT_OS_VAULT_ROOT", None)
                else:
                    os.environ["CONTENT_OS_VAULT_ROOT"] = old_root
                if old_md is None:
                    os.environ.pop("CONTENT_OS_CLOUD_MARKDOWN", None)
                else:
                    os.environ["CONTENT_OS_CLOUD_MARKDOWN"] = old_md

    def test_creation_with_local_material_path_creates_content_os_mac_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            old_root = os.environ.get("CONTENT_OS_VAULT_ROOT")
            old_md = os.environ.get("CONTENT_OS_CLOUD_MARKDOWN")
            os.environ["CONTENT_OS_VAULT_ROOT"] = tmp
            os.environ["CONTENT_OS_CLOUD_MARKDOWN"] = "1"
            _write_content_os_v2_state_rules(Path(tmp))
            try:
                harness = CreationPersistenceHarness()
                local_path = "/Users/vsiyo/Movies/OpenClaw/20260627_清华毕业典礼"
                message = Message(
                    entry_tag="创作>抖音",
                    raw_text=(
                        "【创作>抖音】 类型：视频 赛道：教育 主体：第一视角体验清华毕业典礼 "
                        f"希望产出：剪辑说明，已有素材 本地素材路径：{local_path}"
                    ),
                    body="第一视角体验清华毕业典礼",
                    source="feishu",
                    created_at=datetime(2026, 6, 27, 12, 30),
                )
                result = harness._maybe_create_content_os_project_from_creation(
                    message,
                    {
                        "ok": True,
                        "creation_record_id": "run_002",
                        "request": {"platform": "抖音", "content_type": "视频", "track": "教育", "topic": "第一视角体验清华毕业典礼"},
                        "draft": {"title": "第一视角体验清华毕业典礼"},
                        "reply": "云端创作稿",
                    },
                    "云端创作稿",
                )

                self.assertEqual(result["local_material_binding"], "bound")
                self.assertIn("task_path", result)
                task_text = Path(result["task_path"]).read_text(encoding="utf-8")
                self.assertIn("task_type: local_material_match", task_text)
                self.assertIn(f"local_project_path: {local_path}", task_text)
                self.assertIn("Mac 任务", result["reply"])
            finally:
                if old_root is None:
                    os.environ.pop("CONTENT_OS_VAULT_ROOT", None)
                else:
                    os.environ["CONTENT_OS_VAULT_ROOT"] = old_root
                if old_md is None:
                    os.environ.pop("CONTENT_OS_CLOUD_MARKDOWN", None)
                else:
                    os.environ["CONTENT_OS_CLOUD_MARKDOWN"] = old_md

    def test_inspiration_project_creation_without_local_path_writes_project_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            old_root = os.environ.get("CONTENT_OS_VAULT_ROOT")
            old_md = os.environ.get("CONTENT_OS_CLOUD_MARKDOWN")
            os.environ["CONTENT_OS_VAULT_ROOT"] = tmp
            os.environ["CONTENT_OS_CLOUD_MARKDOWN"] = "1"
            _write_content_os_v2_state_rules(Path(tmp))
            try:
                harness = CreationPersistenceHarness()
                message = Message(
                    entry_tag="创作",
                    raw_text="【创作】请立项，生成项目包、brief 和初稿脚本。目标：毕业季田径比赛做成内容。",
                    body="请立项，生成项目包、brief 和初稿脚本。目标：毕业季田径比赛做成内容。",
                    source="feishu",
                    created_at=datetime(2026, 6, 26, 12, 0),
                )
                result = harness._maybe_create_content_os_project_from_inspiration(
                    message=message,
                    result={
                        "title": "毕业季田径比赛",
                        "theme": "把毕业季和田径比赛结合",
                        "platform": "抖音",
                        "content_type": "视频",
                        "material_requirements": ["比赛过程镜头", "人物反应镜头"],
                    },
                    record_text="创作灵感正文",
                    doc_fs={"doc": "https://example.feishu.cn/wiki/doc"},
                    unified_index={"record_id": "rec_inspiration_1"},
                )

                project_path = Path(result["project_path"])
                self.assertEqual(result["local_material_binding"], "unbound")
                self.assertNotIn("task_path", result)
                self.assertTrue((project_path / "00_项目总览.md").exists())
                self.assertTrue((project_path / "01_idea_card.md").exists())
                self.assertTrue((project_path / "02_project_brief.md").exists())
                self.assertTrue((project_path / "04_script.md").exists())
                self.assertFalse((Path(tmp) / "98_Agent任务队列" / "01_cloud_to_mac_ready").exists())
                index_text = (project_path / "00_项目总览.md").read_text(encoding="utf-8")
                brief_text = (project_path / "02_project_brief.md").read_text(encoding="utf-8")
                self.assertIn("local_material_binding: unbound", index_text)
                self.assertIn("next_owner: human", index_text)
                self.assertIn("等人在 Mac 上把素材批次和项目包绑定", index_text)
                self.assertIn("比赛过程镜头", brief_text)
                self.assertIn("不声称 Mac 本地已有这些素材", brief_text)
            finally:
                if old_root is None:
                    os.environ.pop("CONTENT_OS_VAULT_ROOT", None)
                else:
                    os.environ["CONTENT_OS_VAULT_ROOT"] = old_root
                if old_md is None:
                    os.environ.pop("CONTENT_OS_CLOUD_MARKDOWN", None)
                else:
                    os.environ["CONTENT_OS_CLOUD_MARKDOWN"] = old_md

    def test_inspiration_project_creation_with_local_path_creates_ready_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            old_root = os.environ.get("CONTENT_OS_VAULT_ROOT")
            old_md = os.environ.get("CONTENT_OS_CLOUD_MARKDOWN")
            os.environ["CONTENT_OS_VAULT_ROOT"] = tmp
            os.environ["CONTENT_OS_CLOUD_MARKDOWN"] = "1"
            _write_content_os_v2_state_rules(Path(tmp))
            try:
                harness = CreationPersistenceHarness()
                local_path = "/Users/vsiyo/Desktop/照片筛选/01_Project_Workspace/20260514_400米比赛"
                message = Message(
                    entry_tag="创作",
                    raw_text=f"【创作】目标=生成项目包和初稿脚本，再交给 Mac 做素材匹配。本地素材路径：{local_path}",
                    body="生成项目包和初稿脚本，再交给 Mac 做素材匹配。",
                    source="feishu",
                    created_at=datetime(2026, 6, 26, 12, 30),
                )
                result = harness._maybe_create_content_os_project_from_inspiration(
                    message=message,
                    result={"title": "400米比赛第一视角", "theme": "400米第一视角挑战"},
                    record_text="创作灵感正文",
                    doc_fs={},
                    unified_index={},
                )

                self.assertEqual(result["local_material_binding"], "bound")
                self.assertIn("task_path", result)
                task_text = Path(result["task_path"]).read_text(encoding="utf-8")
                self.assertIn("status: ready", task_text)
                self.assertIn(f"local_project_path: {local_path}", task_text)
                self.assertIn("script_path: 08_内容项目/", task_text)
            finally:
                if old_root is None:
                    os.environ.pop("CONTENT_OS_VAULT_ROOT", None)
                else:
                    os.environ["CONTENT_OS_VAULT_ROOT"] = old_root
                if old_md is None:
                    os.environ.pop("CONTENT_OS_CLOUD_MARKDOWN", None)
                else:
                    os.environ["CONTENT_OS_CLOUD_MARKDOWN"] = old_md

    def test_inspiration_project_creation_with_batch_note_creates_ready_task_without_local_project_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            old_root = os.environ.get("CONTENT_OS_VAULT_ROOT")
            old_md = os.environ.get("CONTENT_OS_CLOUD_MARKDOWN")
            os.environ["CONTENT_OS_VAULT_ROOT"] = tmp
            os.environ["CONTENT_OS_CLOUD_MARKDOWN"] = "1"
            _write_content_os_v2_state_rules(Path(tmp))
            try:
                harness = CreationPersistenceHarness()
                batch_note = "00_Inbox_Mac_Intake/20260626_毕业季田径_待整理/00_批次说明.md"
                message = Message(
                    entry_tag="创作",
                    raw_text=f"【创作】目标=生成项目包和初稿脚本，并派 Mac 素材匹配。批次说明路径：{batch_note}",
                    body="生成项目包和初稿脚本，并派 Mac 素材匹配。",
                    source="feishu",
                    created_at=datetime(2026, 6, 26, 13, 0),
                )
                result = harness._maybe_create_content_os_project_from_inspiration(
                    message=message,
                    result={"title": "毕业季田径项目", "theme": "毕业季田径内容项目"},
                    record_text="创作正文",
                    doc_fs={},
                    unified_index={},
                )

                self.assertEqual(result["local_material_binding"], "bound")
                task_text = Path(result["task_path"]).read_text(encoding="utf-8")
                self.assertIn(f"batch_note_path: {batch_note}", task_text)
                self.assertIn("local_project_path: ''", task_text)
                project_text = (Path(result["project_path"]) / "00_项目总览.md").read_text(encoding="utf-8")
                self.assertIn("local_project_path: ''", project_text)
                self.assertIn(f"batch_note_path: {batch_note}", project_text)
            finally:
                if old_root is None:
                    os.environ.pop("CONTENT_OS_VAULT_ROOT", None)
                else:
                    os.environ["CONTENT_OS_VAULT_ROOT"] = old_root
                if old_md is None:
                    os.environ.pop("CONTENT_OS_CLOUD_MARKDOWN", None)
                else:
                    os.environ["CONTENT_OS_CLOUD_MARKDOWN"] = old_md


if __name__ == "__main__":
    unittest.main()
