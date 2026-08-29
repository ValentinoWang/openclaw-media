from __future__ import annotations

import fcntl
import hashlib
import logging
import re
import json
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from media_vault import MediaVault, MediaVaultError, make_timestamp_id
from selfmedia.context.media_context import DEFAULT_MEMORY_ROOT, load_account_profile, record_review_memory
from selfmedia.request_constraints import parse_request_constraints

from .capability_registry import (
    CAPABILITY_SPECS,
    capability_creator_field_mappings,
    capability_implementation_status,
    is_capability_implemented,
)
from .contracts import (
    CommercialBrief,
    DecisionBrief,
    ExternalResearchBrief,
    PublishReadinessGate,
    PublishingPack,
    ReviewSignal,
    SourceAsset,
    clean_text,
    extract_urls,
)
from .feishu_summary_sync import sync_growth_summary_artifact
from .input_parser import parse_media_growth_input
from .knowledge_evidence_contract import (
    InsufficientKnowledgeEvidence,
    KnowledgeEvidenceBundle,
    KnowledgeEvidenceContractError,
    coerce_knowledge_evidence_bundle,
)
from .llm_runner import GrowthJsonProvider, GrowthLLMJsonRunner
from .planner import WorkflowPlan, plan_media_growth_workflow


LOGGER = logging.getLogger(__name__)


RUNNER_STATUS_ARTIFACT_CREATED = "artifact_created"
RUNNER_STATUS_NOT_IMPLEMENTED = "not_implemented"
RUNNER_STATUS_CONTRACT_FAILED = "contract_failed"
RUNNER_STATUS_PLAN_BLOCKED = "plan_blocked"
RUNNER_STATUS_PENDING_MANUAL = "pending_manual"
RUNNER_STATUS_EXECUTION_FAILED = "execution_failed"
RUNNER_STATUS_EXTERNAL_DELEGATION_REQUIRED = "external_delegation_required"
CREATION_RUN_INPUT_FILENAMES = ("draft.json", "draft_output.json", "request.json")
EVIDENCE_DRIVEN_CAPABILITY_IDS = frozenset(
    {
        "external_research_brief",
        "creation_decision_brief",
        "publishing_pack_build",
    }
)
LLM_DRIVEN_CAPABILITY_IDS = frozenset((*EVIDENCE_DRIVEN_CAPABILITY_IDS, "commercial_brief"))
GROWTH_CAPABILITY_PROMPTS = {
    "external_research_brief": (
        "请基于已提供的类型化证据，整理一份面向创作者的内容调研简报。返回一个合法 JSON 对象，"
        "字段必须包含：status、research_question、media_goal、audience_relevance、content_opportunity、"
        "usable_angles、unusable_angles、risk_notes、next_content_actions、source_evidence、display_title、"
        "display_summary。每一项事实判断都必须能追溯到类型化证据；所有面向创作者显示的文字均使用中文，"
        "JSON 键名保持既有合同，不要翻译或新增字段。"
    ),
    "commercial_brief": (
        "请清理并结构化品牌方提供的视频拍摄需求，形成可供创作者执行的商单简报。返回一个合法 JSON 对象，"
        "字段必须包含：status、brand、project_name、products、platforms、content_format、duration_requirement、"
        "locations、required_brand_mentions、must_cover、narrative_direction、interaction_design、"
        "compliance_restrictions、deliverables、technical_specs、approval_requirements、cleaned_brief、risk_notes、"
        "next_content_actions、source_evidence、display_title、display_summary。只能使用粘贴的需求和已加载素材；"
        "原文意图明确时可以修正识别噪声，不明确处写入 risk_notes，不得编造事实或宣称医疗诊断功能。"
        "所有面向创作者显示的文字均使用中文，JSON 键名保持既有合同，不要翻译或新增字段。"
    ),
    "creation_decision_brief": (
        "请基于已提供的类型化证据，为创作者整理下一步选题决策简报。返回一个合法 JSON 对象，"
        "字段必须包含：status、decision_goal、topic_candidates、recommended_next_capability_id、"
        "risk_or_missing_info、display_title、display_summary。每个 topic_candidates 条目都必须包含 title、"
        "target_audience、pain_point、content_angle、single_problem、self_check、source_refs。"
        "pain_point 对齐主创作链的选题五要素；旧版 audience_pain 会由系统兼容映射。每项必须能追溯到类型化证据，"
        "并继承已加载账号画像和复盘结论；缺少画像或复盘时写入 risk_or_missing_info。"
        "所有面向创作者显示的文字均使用中文，JSON 键名保持既有合同，不要翻译或新增字段。"
    ),
    "publishing_pack_build": (
        "请基于已提供的类型化证据与创作草稿，整理一份可人工确认后发布的内容发布包。返回一个合法 JSON 对象，"
        "字段必须包含：status、title、cover_text、caption、hashtags、comment_seed、publish_checklist、"
        "risk_notes、display_title、display_summary。title 对齐主创作链 title_1，caption 对齐 body_copy，"
        "comment_seed 对齐置顶评论和评论引导；publish_checklist 如有发布后 1 小时动作，必须单列写清。"
        "标题、封面文案、正文和评论引导必须使用中文，"
        "表达自然、短句清楚、可直接口播，避免书面套话、空泛承诺和英文平台术语。不得声称已经自动发布。"
        "必须继承已加载账号画像和复盘结论；缺少画像或复盘时写入 risk_notes。所有面向创作者显示的文字均使用中文，"
        "JSON 键名保持既有合同，不要翻译或新增字段。"
    ),
}


def capture_source_asset(
    text: str,
    *,
    platform: str = "",
    account_id: str = "",
    track_id: str = "",
    vault: MediaVault | None = None,
    run_id: str | None = None,
    input_artifact_ids: tuple[str, ...] | list[str] = (),
) -> SourceAsset:
    actual_run_id = run_id or make_timestamp_id("source_asset")
    urls = extract_urls(text)
    parsed = parse_media_growth_input(text)
    loaded_refs = _load_input_artifact_summaries(input_artifact_ids, vault=vault)
    display_text = _display_text_from_parsed(parsed, "备注", "说明", "目标", "主题", "正文") or _display_text_from_artifacts(loaded_refs)
    title = _title_from_text(display_text, default_text="素材输入")
    source_kind = _source_asset_kind(parsed, urls)
    request_constraints = parse_request_constraints(text).to_dict()
    asset = SourceAsset(
        artifact_id=actual_run_id,
        artifact_type="SourceAsset",
        source_capability_id="source_asset_intake",
        account_id=account_id,
        platform=platform,
        track_id=track_id,
        raw_text=text,
        urls=urls,
        source_kind=source_kind,
        display_title=title,
        display_summary=_summary(display_text, default_text="已捕获一条素材输入。"),
        request_constraints=request_constraints,
        source_trace=_source_trace_with_artifacts(
            {
                "source_type": "user_input",
                "loaded": True,
                "fields": ["raw_text", "urls", "source_kind", "request_constraints"],
                "source_kind": source_kind,
                "request_constraints": request_constraints,
            },
            loaded_refs,
        ),
    )
    return _persist_growth_artifact(asset, vault=vault, root="source_assets")


def build_external_research_brief(
    text: str,
    *,
    platform: str = "",
    account_id: str = "",
    track_id: str = "",
    vault: MediaVault | None = None,
    run_id: str | None = None,
    input_artifact_ids: tuple[str, ...] | list[str] = (),
    knowledge_evidence_bundle: KnowledgeEvidenceBundle | dict[str, Any] | None = None,
    growth_json_provider: GrowthJsonProvider | None = None,
    growth_json_settings: Any | None = None,
    require_typed_evidence: bool = False,
) -> ExternalResearchBrief:
    actual_run_id = run_id or make_timestamp_id("research_brief")
    urls = extract_urls(text)
    parsed = parse_media_growth_input(text)
    loaded_refs = _load_input_artifact_summaries(input_artifact_ids, vault=vault)
    display_text = _display_text_from_parsed(parsed, "问题", "question", "目标", "主题", "备注") or _display_text_from_artifacts(loaded_refs)
    pasted_evidence = parsed.value("证据", "evidence", "source_evidence", "资料", "source")
    artifact_urls = tuple(
        url
        for item in loaded_refs
        for url in item.get("urls", [])
        if isinstance(url, str) and url
    )
    evidence_bundle = _effective_knowledge_evidence_bundle(
        knowledge_evidence_bundle,
        display_text,
        loaded_refs,
        enabled=require_typed_evidence or growth_json_provider is not None or knowledge_evidence_bundle is not None,
    )
    if require_typed_evidence:
        _require_ready_knowledge_evidence_bundle(evidence_bundle)
    if not urls and not pasted_evidence.strip() and not artifact_urls and not _has_ready_knowledge_evidence_bundle(evidence_bundle):
        raise MediaGrowthPendingManual("external_research_brief requires explicit URL or pasted evidence text before writing artifact.")
    llm_payload = _growth_llm_payload(
        task="external_research_brief",
        prompt=GROWTH_CAPABILITY_PROMPTS["external_research_brief"],
        text=text,
        platform=platform,
        account_id=account_id,
        track_id=track_id,
        knowledge_evidence_bundle=evidence_bundle,
        growth_json_provider=growth_json_provider,
        growth_json_settings=growth_json_settings,
    )
    if _is_pending_llm_payload(llm_payload):
        raise MediaGrowthPendingManual(str(llm_payload.get("reason") or "Growth LLM evidence is pending/manual."))
    brief = ExternalResearchBrief(
        artifact_id=actual_run_id,
        artifact_type="ExternalResearchBrief",
        source_capability_id="external_research_brief",
        account_id=account_id,
        platform=platform,
        track_id=track_id,
        research_question=str(llm_payload["research_question"]),
        media_goal=str(llm_payload["media_goal"]),
        audience_relevance=str(llm_payload["audience_relevance"]),
        content_opportunity=str(llm_payload["content_opportunity"]),
        usable_angles=_tuple_text(llm_payload["usable_angles"]),
        unusable_angles=_tuple_text(llm_payload["unusable_angles"]),
        source_evidence=tuple(dict(item) for item in llm_payload["source_evidence"]),
        risk_notes=_tuple_text(llm_payload["risk_notes"]),
        next_content_actions=_tuple_text(llm_payload["next_content_actions"]),
        display_title=_title_from_text(str(llm_payload["display_title"]), default_text=""),
        display_summary=_summary(str(llm_payload["display_summary"]), default_text=""),
        source_trace=_source_trace_with_artifacts(
            {
                "source_type": "user_input",
                "loaded": True,
                "fields": ["research_question", "urls", "pasted_evidence"],
            },
            _knowledge_evidence_trace(evidence_bundle),
            loaded_refs,
        ),
    )
    return _persist_growth_artifact(brief, vault=vault, root="research_briefs")


def build_commercial_brief(
    text: str,
    *,
    platform: str = "",
    account_id: str = "",
    track_id: str = "",
    vault: MediaVault | None = None,
    run_id: str | None = None,
    input_artifact_ids: tuple[str, ...] | list[str] = (),
    knowledge_evidence_bundle: KnowledgeEvidenceBundle | dict[str, Any] | None = None,
    growth_json_provider: GrowthJsonProvider | None = None,
    growth_json_settings: Any | None = None,
    require_typed_evidence: bool = False,
) -> CommercialBrief:
    actual_run_id = run_id or make_timestamp_id("commercial_brief")
    parsed = parse_media_growth_input(text)
    loaded_refs = _load_input_artifact_summaries(_merge_artifact_refs(input_artifact_ids, parsed.artifact_refs), vault=vault)
    raw_body = re.sub(r"^\s*【[^】]+】\s*", "", str(text or "").strip(), count=1).strip()
    explicit_brief = parsed.value("Brief", "brief", "原始Brief", "原始brief", "正文", "内容")
    raw_brief = raw_body or explicit_brief or parsed.content_text or _display_text_from_artifacts(loaded_refs)
    if not raw_brief.strip():
        raise MediaGrowthPendingManual("commercial_brief requires pasted brand brief text or a readable input artifact.")
    llm_payload = _growth_llm_payload(
        task="commercial_brief",
        prompt=GROWTH_CAPABILITY_PROMPTS["commercial_brief"],
        text=text,
        platform=platform,
        account_id=account_id,
        track_id=track_id,
        knowledge_evidence_bundle=knowledge_evidence_bundle,
        growth_json_provider=growth_json_provider,
        growth_json_settings=growth_json_settings,
        require_evidence=require_typed_evidence,
        extra_context={"input_artifacts": list(loaded_refs), "raw_brief": raw_brief},
    )
    if _is_pending_llm_payload(llm_payload):
        raise MediaGrowthPendingManual(str(llm_payload.get("reason") or "Commercial brief LLM structuring is pending/manual."))
    brief = CommercialBrief(
        artifact_id=actual_run_id,
        artifact_type="CommercialBrief",
        source_capability_id="commercial_brief",
        account_id=account_id,
        platform=platform or _first_llm_text(llm_payload, "platform") or _first_from_list(llm_payload.get("platforms")),
        track_id=track_id,
        brand=str(llm_payload["brand"]),
        project_name=str(llm_payload["project_name"]),
        products=tuple(dict(item) for item in llm_payload["products"] if isinstance(item, dict)),
        platforms=_tuple_text(llm_payload["platforms"]),
        content_format=str(llm_payload["content_format"]),
        duration_requirement=str(llm_payload["duration_requirement"]),
        locations=tuple(dict(item) for item in llm_payload["locations"] if isinstance(item, dict)),
        required_brand_mentions=_tuple_text(llm_payload["required_brand_mentions"]),
        must_cover=_tuple_text(llm_payload["must_cover"]),
        narrative_direction=_tuple_text(llm_payload["narrative_direction"]),
        interaction_design=_tuple_text(llm_payload["interaction_design"]),
        compliance_restrictions=_tuple_text(llm_payload["compliance_restrictions"]),
        deliverables=tuple(dict(item) for item in llm_payload["deliverables"] if isinstance(item, dict)),
        technical_specs=dict(llm_payload["technical_specs"]),
        approval_requirements=_tuple_text(llm_payload["approval_requirements"]),
        cleaned_brief=str(llm_payload["cleaned_brief"]),
        raw_brief=raw_brief,
        source_evidence=tuple(dict(item) for item in llm_payload["source_evidence"] if isinstance(item, dict)),
        risk_notes=_tuple_text(llm_payload["risk_notes"]),
        next_content_actions=_tuple_text(llm_payload["next_content_actions"]),
        display_title=_title_from_text(str(llm_payload["display_title"]), default_text=""),
        display_summary=_summary(str(llm_payload["display_summary"]), default_text=""),
        source_trace=_source_trace_with_artifacts(
            {
                "source_type": "user_input",
                "loaded": True,
                "fields": ["raw_brief"],
                "semantic_owner": "llm",
            },
            loaded_refs,
        ),
    )
    return _persist_growth_artifact(brief, vault=vault, root="commercial_briefs")


def build_decision_brief(
    text: str,
    *,
    platform: str = "",
    account_id: str = "",
    track_id: str = "",
    vault: MediaVault | None = None,
    run_id: str | None = None,
    input_artifact_ids: tuple[str, ...] | list[str] = (),
    knowledge_evidence_bundle: KnowledgeEvidenceBundle | dict[str, Any] | None = None,
    growth_json_provider: GrowthJsonProvider | None = None,
    growth_json_settings: Any | None = None,
    require_typed_evidence: bool = False,
) -> DecisionBrief:
    actual_run_id = run_id or make_timestamp_id("decision_brief")
    parsed = parse_media_growth_input(text)
    loaded_refs = _merge_artifact_summaries(
        _load_input_artifact_summaries(input_artifact_ids, vault=vault),
        _load_owned_review_signal_summaries(
            vault=vault,
            account_id=account_id,
            platform=platform,
            track_id=track_id,
        ),
    )
    creator_context = _load_owned_creator_context(
        vault=vault,
        account_id=account_id,
        platform=platform,
    )
    display_text = _display_text_from_parsed(parsed, "主题", "目标", "问题", "备注", "正文") or _display_text_from_artifacts(loaded_refs)
    evidence_bundle = _effective_knowledge_evidence_bundle(
        knowledge_evidence_bundle,
        display_text,
        loaded_refs,
        enabled=require_typed_evidence or growth_json_provider is not None or knowledge_evidence_bundle is not None,
        owned_memory_evidence=creator_context["evidence_items"],
    )
    if require_typed_evidence:
        _require_ready_knowledge_evidence_bundle(evidence_bundle)
    llm_payload = _growth_llm_payload(
        task="creation_decision_brief",
        prompt=GROWTH_CAPABILITY_PROMPTS["creation_decision_brief"],
        text=text,
        platform=platform,
        account_id=account_id,
        track_id=track_id,
        knowledge_evidence_bundle=evidence_bundle,
        growth_json_provider=growth_json_provider,
        growth_json_settings=growth_json_settings,
        extra_context={"input_artifacts": list(loaded_refs), "creator_context": creator_context["payload"]},
    )
    if _is_pending_llm_payload(llm_payload):
        raise MediaGrowthPendingManual(str(llm_payload.get("reason") or "Growth LLM evidence is pending/manual."))
    llm_candidates = _candidate_dicts(llm_payload.get("topic_candidates"))
    if not llm_candidates:
        raise MediaGrowthPendingManual("Growth LLM returned no grounded topic candidates.")
    candidates = tuple(llm_candidates)
    brief = DecisionBrief(
        artifact_id=actual_run_id,
        artifact_type="DecisionBrief",
        source_capability_id="creation_decision_brief",
        account_id=account_id,
        platform=platform,
        track_id=track_id,
        decision_goal=str(llm_payload["decision_goal"]),
        topic_candidates=candidates,
        recommended_next_capability_id=str(llm_payload["recommended_next_capability_id"]),
        risk_or_missing_info=_tuple_text(llm_payload["risk_or_missing_info"]),
        display_title=_title_from_text(str(llm_payload["display_title"]), default_text=""),
        display_summary=_summary(str(llm_payload["display_summary"]), default_text=""),
        source_trace=_source_trace_with_artifacts(
            {
                "source_type": "user_input",
                "loaded": True,
                "fields": ["topic_text", "urls"],
            },
            loaded_refs,
            _knowledge_evidence_trace(evidence_bundle),
            creator_context["trace"],
        ),
    )
    return _persist_growth_artifact(brief, vault=vault, root="decision_briefs")


def build_publishing_pack(
    text: str,
    *,
    platform: str = "",
    account_id: str = "",
    track_id: str = "",
    vault: MediaVault | None = None,
    run_id: str | None = None,
    input_artifact_ids: tuple[str, ...] | list[str] = (),
    knowledge_evidence_bundle: KnowledgeEvidenceBundle | dict[str, Any] | None = None,
    growth_json_provider: GrowthJsonProvider | None = None,
    growth_json_settings: Any | None = None,
    require_typed_evidence: bool = False,
) -> PublishingPack:
    actual_run_id = run_id or make_timestamp_id("publishing_pack")
    parsed = parse_media_growth_input(text)
    loaded_refs = _load_input_artifact_summaries(_merge_artifact_refs(input_artifact_ids, parsed.artifact_refs), vault=vault)
    creator_context = _load_owned_creator_context(
        vault=vault,
        account_id=account_id,
        platform=platform,
    )
    caption_text = parsed.value("草稿", "正文", "draft", "body") or parsed.content_text or _draft_text_from_artifacts(loaded_refs)
    display_text = caption_text or _display_text_from_artifacts(loaded_refs)
    evidence_bundle = _effective_knowledge_evidence_bundle(
        knowledge_evidence_bundle,
        display_text,
        loaded_refs,
        enabled=require_typed_evidence or growth_json_provider is not None or knowledge_evidence_bundle is not None,
        owned_memory_evidence=creator_context["evidence_items"],
    )
    if require_typed_evidence:
        _require_ready_knowledge_evidence_bundle(evidence_bundle)
    llm_payload = _growth_llm_payload(
        task="publishing_pack_build",
        prompt=GROWTH_CAPABILITY_PROMPTS["publishing_pack_build"],
        text=text,
        platform=platform,
        account_id=account_id,
        track_id=track_id,
        knowledge_evidence_bundle=evidence_bundle,
        growth_json_provider=growth_json_provider,
        growth_json_settings=growth_json_settings,
        extra_context={
            "input_artifacts": list(loaded_refs),
            "draft_text": caption_text,
            "creator_context": creator_context["payload"],
        },
    )
    if _is_pending_llm_payload(llm_payload):
        raise MediaGrowthPendingManual(str(llm_payload.get("reason") or "Growth LLM evidence is pending/manual."))
    pack = PublishingPack(
        artifact_id=actual_run_id,
        artifact_type="PublishingPack",
        source_capability_id="publishing_pack_build",
        account_id=account_id,
        platform=platform,
        track_id=track_id,
        title=str(llm_payload["title"]),
        cover_text=str(llm_payload["cover_text"]),
        caption=clean_text(llm_payload["caption"]),
        hashtags=tuple(f"#{item}" for item in _dedupe_tags(llm_payload["hashtags"])),
        comment_seed=str(llm_payload["comment_seed"]),
        publish_checklist=_tuple_text(llm_payload["publish_checklist"]),
        risk_notes=_tuple_text(llm_payload["risk_notes"]),
        asset_refs=tuple(
            str(item.get("artifact_uri") or item.get("artifact_id") or "")
            for item in loaded_refs
            if item.get("loaded") and (item.get("artifact_uri") or item.get("artifact_id"))
        ),
        display_title=_title_from_text(str(llm_payload["display_title"]), default_text=""),
        display_summary=_summary(str(llm_payload["display_summary"]), default_text=""),
        source_trace=_source_trace_with_artifacts(
            {
                "source_type": "user_input",
                "loaded": True,
                "fields": ["draft_text", "hashtags"],
            },
            loaded_refs,
            _knowledge_evidence_trace(evidence_bundle),
            creator_context["trace"],
        ),
    )
    return _persist_growth_artifact(pack, vault=vault, root="publishing_packs")


def normalize_publishing_pack_for_creation(value: PublishingPack | dict[str, Any]) -> dict[str, Any]:
    """Expose only source-backed Growth values under the main creation package names."""
    source = value.to_dict() if isinstance(value, PublishingPack) else dict(value)
    mappings = capability_creator_field_mappings("publishing_pack_build")
    creation_pack: dict[str, Any] = {
        "title_1": clean_text(source.get("title")),
        "title_2": "",
        "cover_text": clean_text(source.get("cover_text")),
        "body_copy": clean_text(source.get("caption")),
        "hashtags": list(source.get("hashtags") or []),
        "pinned_comment": clean_text(source.get("comment_seed")),
        "comment_prompt": clean_text(source.get("comment_seed")),
        "first_hour_action": _first_post_publish_action(source.get("publish_checklist")),
    }
    missing_creator_fields = tuple(
        field_name for field_name, field_value in creation_pack.items() if field_value in ("", [], None)
    )
    return {
        "adapter_version": "growth_to_creation_publishing_pack_v1",
        "source_contract": clean_text(source.get("artifact_type")) or "PublishingPack",
        "creator_publishing_pack": creation_pack,
        "field_mappings": {target: list(sources) for target, sources in mappings.items()},
        "missing_creator_fields": list(missing_creator_fields),
    }


def capture_review_signal(
    text: str,
    *,
    platform: str = "",
    account_id: str = "",
    track_id: str = "",
    vault: MediaVault | None = None,
    run_id: str | None = None,
    input_artifact_ids: tuple[str, ...] | list[str] = (),
) -> ReviewSignal:
    actual_run_id = run_id or make_timestamp_id("review_signal")
    parsed = parse_media_growth_input(text)
    publish_id = parsed.value("作品ID", "发布ID", "publish_id", "post_id", "作品链接", "发布链接", "url")
    loaded_refs = _merge_artifact_summaries(
        _load_input_artifact_summaries(input_artifact_ids, vault=vault),
        _load_owned_post_review_summaries(vault=vault, publish_id=publish_id),
    )
    single_fact = (
        parsed.value("单一事实", "single_fact", "事实", "结论", "summary", "摘要")
        or parsed.content_text
        or _display_text_from_artifacts(loaded_refs)
    )
    metrics_summary = _review_signal_metrics(parsed.params)
    for item in loaded_refs:
        if item.get("artifact_type") != "PublishedPostReviewEvidence":
            continue
        for key, value in (item.get("metrics") or {}).items():
            metrics_summary.setdefault(str(key), str(value))
    signal = ReviewSignal(
        artifact_id=actual_run_id,
        artifact_type="ReviewSignal",
        source_capability_id="post_review_signal",
        account_id=account_id,
        platform=platform,
        track_id=track_id,
        publish_id=publish_id,
        metrics_summary=metrics_summary,
        single_fact=single_fact,
        effective_patterns=_split_review_items(parsed.value("有效模式", "有效", "亮点", "effective_patterns")),
        failure_reasons=_split_review_items(parsed.value("失败原因", "问题", "不足", "failure_reasons")),
        next_decision_inputs=_split_review_items(parsed.value("下一步", "选题输入", "建议", "next_decision_inputs")) or ((single_fact,) if single_fact else ()),
        display_title=_title_from_text(single_fact or publish_id, default_text="复盘信号"),
        display_summary=_summary(single_fact or publish_id, default_text="已记录一条复盘信号，可作为后续选题输入。"),
        source_trace=_source_trace_with_artifacts(
            {
                "source_type": "user_input",
                "loaded": True,
                "fields": ["publish_id", "metrics_summary", "single_fact", "next_decision_inputs"],
            },
            loaded_refs,
        ),
    )
    persisted_signal = _persist_growth_artifact(signal, vault=vault, root="review_signals")
    _record_growth_review_memory(signal, vault=vault)
    return persisted_signal


def build_publish_readiness_gate(
    text: str,
    *,
    platform: str = "",
    account_id: str = "",
    track_id: str = "",
    vault: MediaVault | None = None,
    run_id: str | None = None,
    input_artifact_ids: tuple[str, ...] | list[str] = (),
) -> PublishReadinessGate:
    actual_run_id = run_id or make_timestamp_id("publish_readiness")
    parsed = parse_media_growth_input(text)
    loaded_refs = _load_input_artifact_summaries(_merge_artifact_refs(input_artifact_ids, parsed.artifact_refs), vault=vault)
    if not loaded_refs:
        raise MediaGrowthPendingManual("publish_readiness_gate requires a PublishingPack, DraftPackage, or CreationRun artifact reference.")
    source_refs = tuple(
        str(item.get("artifact_uri") or item.get("reference") or item.get("artifact_id") or "")
        for item in loaded_refs
        if item.get("loaded") and (item.get("artifact_uri") or item.get("reference") or item.get("artifact_id"))
    )
    blocking_issues = _publish_readiness_blocking_issues(loaded_refs)
    gate_status = "ready" if not blocking_issues else "needs_review"
    title = _title_from_artifacts(loaded_refs) or _display_text_from_artifacts(loaded_refs) or "发布前 Gate"
    gate = PublishReadinessGate(
        artifact_id=actual_run_id,
        artifact_type="PublishReadinessGate",
        source_capability_id="publish_readiness_gate",
        account_id=account_id,
        platform=platform or _first_loaded_ref_field(loaded_refs, "platform"),
        track_id=track_id,
        gate_status=gate_status,
        ready_to_publish=gate_status == "ready",
        checklist=(
            "标题、封面、正文、标签已齐全",
            "事实、身份、数据、链接已人工核对",
            "确认不需要自动发布，人工去平台执行发布",
        ),
        blocking_issues=blocking_issues,
        source_refs=source_refs,
        display_title=_title_from_text(title, default_text="发布前 Gate"),
        display_summary=_summary("；".join(blocking_issues) if blocking_issues else "发布前门禁未发现结构性阻塞，仍需人工最终确认。", default_text="发布前门禁已生成。"),
        source_trace=_source_trace_with_artifacts(
            {
                "source_type": "input_artifacts",
                "loaded": True,
                "fields": ["PublishingPack", "DraftPackage", "CreationRun"],
            },
            loaded_refs,
        ),
    )
    return _persist_growth_artifact(gate, vault=vault, root="verification_reports")


def run_media_growth_capability(
    canonical_capability_id: str,
    text: str,
    *,
    platform: str = "",
    account_id: str = "",
    track_id: str = "",
    input_artifact_ids: tuple[str, ...] | list[str] = (),
    input_artifact_types: tuple[str, ...] | list[str] = (),
    explicit_preset: str = "",
    vault: MediaVault | None = None,
    knowledge_evidence_bundle: KnowledgeEvidenceBundle | dict[str, Any] | None = None,
    growth_json_provider: GrowthJsonProvider | None = None,
    growth_json_settings: Any | None = None,
    require_typed_evidence_for_semantic_runs: bool = False,
) -> tuple[WorkflowPlan, dict[str, Any]]:
    plan = plan_media_growth_workflow(
        requested_capability_id=canonical_capability_id,
        text=text,
        input_artifact_ids=tuple(input_artifact_ids),
        input_artifact_types=tuple(input_artifact_types),
        explicit_preset=explicit_preset,
    )
    if plan.contract_check_result != "passed":
        return plan, {"runtime_status": RUNNER_STATUS_CONTRACT_FAILED, "status": "contract_failed", "reason": plan.reason}
    if plan.workflow_mode == "preset_flow":
        preset_flow_id = explicit_preset or _preset_flow_id_from_plan(plan)
        first_unimplemented = next(
            (
                node.canonical_capability_id
                for node in plan.planned_nodes
                if capability_implementation_status(node.canonical_capability_id) == "not_implemented"
            ),
            "",
        )
        if first_unimplemented:
            return plan, {
                "runtime_status": RUNNER_STATUS_PLAN_BLOCKED,
                "status": "plan_blocked",
                "blocked_capability_id": first_unimplemented,
                "preset_flow": preset_flow_id,
                "executable_alternative": _plan_blocked_executable_alternative(preset_flow_id, text),
                "planned_node_statuses": _planned_node_statuses(plan),
                "reason": f"{first_unimplemented} is not implemented; preset execution stopped before writing artifacts.",
            }
        node_payloads: list[dict[str, Any]] = []
        next_input_refs = tuple(input_artifact_ids)
        for node in plan.planned_nodes:
            if capability_implementation_status(node.canonical_capability_id) == "external":
                return plan, {
                    "runtime_status": RUNNER_STATUS_EXTERNAL_DELEGATION_REQUIRED,
                    "status": "external_delegation_required",
                    "blocked_capability_id": node.canonical_capability_id,
                    "preset_flow": preset_flow_id,
                    "preset_node_results": node_payloads,
                    "planned_node_statuses": _planned_node_statuses(plan),
                    "reason": f"{node.canonical_capability_id} is handled by an existing tag-router chain, not the local Mediaclaw artifact runner.",
                }
            try:
                artifact = _run_single_capability(
                    node.canonical_capability_id,
                    text,
                    platform=platform,
                    account_id=account_id,
                    track_id=track_id,
                    vault=vault,
                    input_artifact_ids=next_input_refs,
                    knowledge_evidence_bundle=knowledge_evidence_bundle,
                    growth_json_provider=growth_json_provider,
                    growth_json_settings=growth_json_settings,
                    require_typed_evidence=require_typed_evidence_for_semantic_runs,
                )
            except MediaGrowthPendingManual as exc:
                return plan, {
                    "runtime_status": RUNNER_STATUS_PENDING_MANUAL,
                    "status": "pending_manual",
                    "blocked_capability_id": node.canonical_capability_id,
                    "preset_flow": preset_flow_id,
                    "preset_node_results": node_payloads,
                    "planned_node_statuses": _planned_node_statuses(plan),
                    "reason": str(exc),
                }
            except Exception as exc:
                return plan, {
                    "runtime_status": RUNNER_STATUS_EXECUTION_FAILED,
                    "status": "execution_failed",
                    "blocked_capability_id": node.canonical_capability_id,
                    "preset_flow": preset_flow_id,
                    "preset_node_results": node_payloads,
                    "planned_node_statuses": _planned_node_statuses(plan),
                    "reason": str(exc),
                }
            payload = _artifact_response_payload(artifact, vault=vault)
            payload["runtime_status"] = RUNNER_STATUS_ARTIFACT_CREATED
            node_payloads.append(payload)
            next_input_refs = (str(payload.get("artifact_uri") or payload.get("artifact_id") or ""),)
        final_payload = dict(node_payloads[-1]) if node_payloads else {"runtime_status": RUNNER_STATUS_PLAN_BLOCKED, "status": "plan_blocked", "reason": "preset has no executable nodes"}
        final_payload["preset_node_results"] = node_payloads
        final_payload["preset_flow"] = preset_flow_id
        return plan, final_payload
    runner = RUNNERS.get(canonical_capability_id)
    if runner is None:
        return plan, {
            "runtime_status": RUNNER_STATUS_NOT_IMPLEMENTED,
            "status": "not_implemented",
            "reason": f"{canonical_capability_id} is registered but has no local runner.",
        }
    try:
        runner_kwargs: dict[str, Any] = {
            "platform": platform,
            "account_id": account_id,
            "track_id": track_id,
            "vault": vault,
            "input_artifact_ids": tuple(input_artifact_ids),
        }
        if canonical_capability_id in LLM_DRIVEN_CAPABILITY_IDS:
            runner_kwargs.update(
                {
                    "knowledge_evidence_bundle": knowledge_evidence_bundle,
                    "growth_json_provider": growth_json_provider,
                    "growth_json_settings": growth_json_settings,
                    "require_typed_evidence": require_typed_evidence_for_semantic_runs if canonical_capability_id in EVIDENCE_DRIVEN_CAPABILITY_IDS else False,
                }
            )
        artifact = runner(text, **runner_kwargs)
    except MediaGrowthPendingManual as exc:
        return plan, {"runtime_status": RUNNER_STATUS_PENDING_MANUAL, "status": "pending_manual", "reason": str(exc)}
    except Exception as exc:
        return plan, {"runtime_status": RUNNER_STATUS_EXECUTION_FAILED, "status": "execution_failed", "reason": str(exc)}
    payload = _artifact_response_payload(artifact, vault=vault)
    payload["runtime_status"] = RUNNER_STATUS_ARTIFACT_CREATED
    return plan, payload


RUNNERS = {
    "source_asset_intake": capture_source_asset,
    "commercial_brief": build_commercial_brief,
    "external_research_brief": build_external_research_brief,
    "creation_decision_brief": build_decision_brief,
    "publishing_pack_build": build_publishing_pack,
    "post_review_signal": capture_review_signal,
    "publish_readiness_gate": build_publish_readiness_gate,
}

IMPLEMENTED_CAPABILITY_IDS = frozenset((*RUNNERS.keys(), "media_growth_review"))


def _run_single_capability(
    capability_id: str,
    text: str,
    *,
    platform: str,
    account_id: str,
    track_id: str,
    vault: MediaVault | None,
    input_artifact_ids: tuple[str, ...] | list[str] = (),
    knowledge_evidence_bundle: KnowledgeEvidenceBundle | dict[str, Any] | None = None,
    growth_json_provider: GrowthJsonProvider | None = None,
    growth_json_settings: Any | None = None,
    require_typed_evidence: bool = False,
) -> Any:
    runner = RUNNERS.get(capability_id)
    if runner is None:
        raise RuntimeError(f"{capability_id} is not implemented")
    runner_kwargs: dict[str, Any] = {
        "platform": platform,
        "account_id": account_id,
        "track_id": track_id,
        "vault": vault,
        "input_artifact_ids": tuple(input_artifact_ids),
    }
    if capability_id in LLM_DRIVEN_CAPABILITY_IDS:
        runner_kwargs.update(
            {
                "knowledge_evidence_bundle": knowledge_evidence_bundle,
                "growth_json_provider": growth_json_provider,
                "growth_json_settings": growth_json_settings,
                "require_typed_evidence": require_typed_evidence if capability_id in EVIDENCE_DRIVEN_CAPABILITY_IDS else False,
            }
        )
    return runner(text, **runner_kwargs)


def make_media_vault(tenant_id: str, root: str | Path | None = None) -> MediaVault:
    return MediaVault(tenant_id=tenant_id, root=root)


def _result_path_under_vault(path: Path, vault: MediaVault) -> Path | None:
    try:
        resolved = Path(path).expanduser().resolve()
        resolved.relative_to(vault.root)
    except (OSError, ValueError):
        return None
    return resolved


def _growth_artifact_path_candidates(path: Path, vault: MediaVault) -> list[Path]:
    resolved = _result_path_under_vault(path, vault)
    if resolved is None:
        return []
    if resolved.name == "result.json" or resolved.suffix == ".json":
        return [resolved]
    candidates = [resolved / "result.json"]
    candidates.extend(_creation_run_path_candidates(resolved, vault))
    return candidates


def _creation_run_path_candidates(directory: Path, vault: MediaVault) -> list[Path]:
    resolved = _result_path_under_vault(directory, vault)
    if resolved is None:
        return []
    try:
        relative = resolved.relative_to(vault.root / "creation_runs")
    except ValueError:
        return []
    if len(relative.parts) != 1:
        return []
    return [resolved / filename for filename in CREATION_RUN_INPUT_FILENAMES]


def _is_creation_run_input_path(path: Path, vault: MediaVault) -> bool:
    try:
        relative = Path(path).expanduser().resolve().relative_to(vault.root)
    except ValueError:
        return False
    return len(relative.parts) == 3 and relative.parts[0] == "creation_runs" and relative.parts[2] in CREATION_RUN_INPUT_FILENAMES


@contextmanager
def _artifact_file_lock(path: Path) -> Iterator[None]:
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("w", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _allowed_reviewers() -> set[str]:
    return {
        item.strip()
        for item in os.environ.get("OPENCLAW_MEDIA_GROWTH_REVIEWERS", "").split(",")
        if item.strip()
    }


def _review_authorization_error(reviewer: str, allowed_reviewers: set[str]) -> dict[str, Any]:
    if not allowed_reviewers:
        return {
            "ok": False,
            "status": "review_authorization_not_configured",
            "reason": "OPENCLAW_MEDIA_GROWTH_REVIEWERS must be configured before reviewing Mediaclaw artifacts",
        }
    if not reviewer:
        return {"ok": False, "status": "review_unauthorized", "reason": "reviewer id is required"}
    if reviewer not in allowed_reviewers:
        return {"ok": False, "status": "review_unauthorized", "reason": "reviewer is not allowed to review Mediaclaw artifacts"}
    return {}


def resolve_growth_artifact_type(reference: str, *, vault: MediaVault | None = None) -> str:
    payload = load_growth_artifact_payload(reference, vault=vault)
    return str(payload.get("artifact_type") or "").strip()


def resolve_growth_artifact_path(reference: str, *, vault: MediaVault | None = None) -> Path | None:
    ref = str(reference or "").strip()
    if not ref:
        return None
    if vault is None:
        raise MediaVaultError("tenant-scoped vault is required")
    actual_vault = vault
    candidates: list[Path] = []
    try:
        if ref.startswith("media://"):
            path = actual_vault.resolve_uri(ref)
            candidates.extend(_growth_artifact_path_candidates(path, actual_vault))
        else:
            raw_path = Path(ref).expanduser()
            if raw_path.is_absolute():
                candidates.extend(_growth_artifact_path_candidates(raw_path, actual_vault))
            elif "/" in ref or "\\" in ref:
                candidates.extend(_growth_artifact_path_candidates(actual_vault.root / raw_path, actual_vault))
            elif re.fullmatch(r"[A-Za-z0-9_.=-]+", ref):
                candidates.extend(
                    path
                    for path in actual_vault.root.glob(f"*/{ref}/result.json")
                    if _result_path_under_vault(path, actual_vault) is not None
                )
                candidates.extend(_creation_run_path_candidates(actual_vault.creation_run_dir(ref), actual_vault))
    except (MediaVaultError, OSError):
        return None
    for path in candidates:
        if path.is_file():
            return path
    return None


def load_growth_artifact_payload(reference: str, *, vault: MediaVault | None = None) -> dict[str, Any]:
    if vault is None:
        raise MediaVaultError("tenant-scoped vault is required")
    actual_vault = vault
    path = resolve_growth_artifact_path(reference, vault=actual_vault)
    if path is None:
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if isinstance(loaded, dict) and _is_creation_run_input_path(path, actual_vault):
        return _creation_run_input_payload(path, loaded, actual_vault)
    if isinstance(loaded, dict):
        return loaded
    return {}


def _creation_run_input_payload(path: Path, payload: dict[str, Any], vault: MediaVault) -> dict[str, Any]:
    run_id = path.parent.name
    request_payload = payload if path.name == "request.json" else _read_sibling_json(path.parent / "request.json")
    title = _creation_run_title(payload) or _creation_run_title(request_payload) or run_id
    draft_text = _creation_run_draft_text(payload)
    request_text = _creation_run_request_text(request_payload)
    summary_text = draft_text or _creation_run_summary_text(payload) or request_text or title
    hashtags = _dedupe_tags((*_creation_run_tags(payload), *_creation_run_tags(request_payload)))
    url_text = " ".join(item for item in (title, draft_text, summary_text, request_text) if item)
    artifact_uri = vault.to_uri(path)
    return {
        "artifact_id": run_id,
        "artifact_type": "DraftPackage",
        "artifact_uri": artifact_uri,
        "source_capability_id": "creation_run_projection",
        "display_title": _title_from_text(title, default_text=run_id),
        "display_summary": _summary(summary_text, default_text=title),
        "draft_text": draft_text or request_text,
        "hashtags": hashtags,
        "urls": list(extract_urls(url_text)),
        "quality_status": "",
        "source_creation_run_id": run_id,
        "source_creation_run_uri": artifact_uri,
        "source_creation_run_file": path.name,
        "platform": _creation_run_platform(payload) or _creation_run_platform(request_payload),
    }


def _read_sibling_json(path: Path) -> dict[str, Any]:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _creation_run_title(payload: dict[str, Any]) -> str:
    option = _recommended_script_option(payload)
    return (
        _first_text_field(payload, "title", "标题", "display_title", "topic", "主题")
        or _nested_text(payload, ("creator_report", "overview", "recommended_topic"))
        or _first_text_field(option, "title", "标题", "angle", "角度")
    )


def _creation_run_draft_text(payload: dict[str, Any]) -> str:
    option = _recommended_script_option(payload)
    return (
        _first_text_field(payload, "caption", "发布文案", "final_copy", "body", "正文", "draft", "草稿", "content", "text", "voiceover", "口播")
        or _first_text_field(option, "caption", "发布文案", "final_copy", "body", "正文", "draft", "草稿", "content", "text", "voiceover", "口播")
        or _nested_text(payload, ("creator_report", "overview", "core_sentence"))
    )


def _creation_run_summary_text(payload: dict[str, Any]) -> str:
    option = _recommended_script_option(payload)
    return (
        _creation_run_draft_text(payload)
        or _nested_text(payload, ("creator_report", "overview", "core_sentence"))
        or _first_text_field(option, "hook_3s", "why_over_90", "angle")
        or _first_text_field(payload, "summary", "摘要", "input_summary")
    )


def _creation_run_request_text(payload: dict[str, Any]) -> str:
    request = payload.get("request") if isinstance(payload.get("request"), dict) else {}
    return (
        _first_text_field(payload, "input", "raw_text", "input_summary", "topic", "主题", "body", "正文")
        or _first_text_field(request, "raw_text", "topic", "主题", "subject", "主体", "theme", "类型", "content_type")
    )


def _creation_run_platform(payload: dict[str, Any]) -> str:
    request = payload.get("request") if isinstance(payload.get("request"), dict) else {}
    return _first_text_field(payload, "platform", "平台") or _first_text_field(request, "platform", "平台")


def _creation_run_tags(payload: dict[str, Any]) -> tuple[str, ...]:
    option = _recommended_script_option(payload)
    return _dedupe_tags((*_tag_values(payload.get("hashtags")), *_tag_values(payload.get("tags")), *_tag_values(option.get("hashtags")), *_tag_values(option.get("tags"))))


def _recommended_script_option(payload: dict[str, Any]) -> dict[str, Any]:
    options = payload.get("script_options")
    if not isinstance(options, list):
        return {}
    dict_options = [item for item in options if isinstance(item, dict)]
    if not dict_options:
        return {}
    recommended_id = str(payload.get("recommended_option_id") or "").strip()
    if recommended_id:
        for option in dict_options:
            if str(option.get("option_id") or "").strip() == recommended_id:
                return option
    return dict_options[0]


def _first_text_field(payload: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = payload.get(key)
        text = _readable_text(value)
        if text:
            return text
    return ""


def _first_llm_text(payload: dict[str, Any], *keys: str) -> str:
    return _first_text_field(payload, *keys)


def _first_from_list(value: Any) -> str:
    if isinstance(value, str):
        return clean_text(value)
    if isinstance(value, (list, tuple)):
        for item in value:
            text = clean_text(item)
            if text:
                return text
    return ""


def _nested_text(payload: dict[str, Any], keys: tuple[str, ...]) -> str:
    current: Any = payload
    for key in keys:
        if not isinstance(current, dict):
            return ""
        current = current.get(key)
    return _readable_text(current)


def _readable_text(value: Any) -> str:
    if isinstance(value, str):
        return clean_text(value)
    if isinstance(value, (int, float)):
        return clean_text(value)
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return clean_text(" / ".join(value))
    return ""


def _tag_values(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        parts = re.split(r"[#,\s，、]+", value)
    elif isinstance(value, (list, tuple)):
        parts = [str(item or "") for item in value]
    else:
        parts = []
    return tuple(item.strip().lstrip("#") for item in parts if item.strip().lstrip("#"))


def review_growth_artifact(
    reference: str,
    *,
    action: str,
    reviewer_id: str = "",
    note: str = "",
    vault: MediaVault | None = None,
) -> dict[str, Any]:
    if vault is None:
        raise MediaVaultError("tenant-scoped vault is required")
    actual_vault = vault
    path = resolve_growth_artifact_path(reference, vault=actual_vault)
    if path is None:
        return {"ok": False, "status": "artifact_not_found", "reason": "artifact reference cannot be resolved"}
    if path.name != "result.json":
        return {"ok": False, "status": "artifact_contract_failed", "reason": "reference is an input artifact, not a reviewable Mediaclaw result"}
    reviewer = clean_text(reviewer_id)
    allowed_reviewers = _allowed_reviewers()
    auth_error = _review_authorization_error(reviewer, allowed_reviewers)
    if auth_error:
        return auth_error
    review_action = _normalize_review_action(action)
    if not review_action:
        return {"ok": False, "status": "unsupported_review_action", "reason": f"unsupported review action: {action}"}
    with _artifact_file_lock(path):
        payload = load_growth_artifact_payload(str(path), vault=actual_vault)
        if not _is_media_growth_payload(payload):
            return {"ok": False, "status": "artifact_contract_failed", "reason": "reference is not a Mediaclaw artifact"}
        now = _utc_now_iso()
        payload["schema_version"] = payload.get("schema_version") or "media_growth_artifact_v1"
        payload["updated_at"] = now
        payload["reviewed_at"] = now
        payload["reviewed_by"] = reviewer
        payload["review_note"] = clean_text(note)
        payload["review_action"] = review_action
        review_history = [dict(item) for item in payload.get("review_history") or [] if isinstance(item, dict)]
        if review_action == "approve":
            payload["quality_status"] = "cleaned"
            payload["status"] = "candidate"
            payload["front_end_eligible"] = True
        elif review_action == "verify":
            payload["quality_status"] = "verified"
            payload["status"] = "candidate"
            payload["front_end_eligible"] = True
        elif review_action == "reject":
            payload["quality_status"] = "rejected"
            payload["status"] = "rejected"
            payload["front_end_eligible"] = False
        review_history.append(
            {
                "action": review_action,
                "reviewed_at": now,
                "reviewed_by": reviewer,
                "note": clean_text(note),
                "quality_status": str(payload.get("quality_status") or ""),
                "status": str(payload.get("status") or ""),
            }
        )
        payload["review_history"] = review_history[-50:]
        actual_vault.write_json_artifact(
            path.parent,
            path.name,
            payload,
            owner_type=str(payload.get("artifact_type") or "MediaGrowthArtifact"),
            owner_id=str(payload.get("artifact_id") or path.parent.name),
            artifact_type=str(payload.get("artifact_type") or "media_growth_artifact"),
            artifact_id=str(payload.get("artifact_id") or path.parent.name),
        )
        summary_sync = _sync_growth_summary_if_configured(payload, tenant_id=actual_vault.tenant_id)
    return {
        "ok": True,
        "status": {
            "approve": "artifact_approved",
            "verify": "artifact_verified",
            "reject": "artifact_rejected",
        }[review_action],
        "artifact_id": str(payload.get("artifact_id") or ""),
        "artifact_type": str(payload.get("artifact_type") or ""),
        "artifact_uri": str(payload.get("artifact_uri") or ""),
        "quality_status": str(payload.get("quality_status") or ""),
        "payload": payload,
        "growth_summary_sync": summary_sync,
    }


def _persist_growth_artifact(artifact: Any, *, vault: MediaVault | None, root: str) -> Any:
    if vault is None:
        raise MediaVaultError("tenant-scoped vault is required")
    actual_vault = vault
    directory = actual_vault.root / root / artifact.artifact_id
    path = directory / "result.json"
    uri = actual_vault.to_uri(path)
    payload = artifact.to_dict()
    payload["artifact_uri"] = uri
    actual_vault.write_json_artifact(
        directory,
        "result.json",
        payload,
        owner_type=artifact.artifact_type,
        owner_id=artifact.artifact_id,
        artifact_type=artifact.artifact_type,
    )
    summary_sync = _sync_growth_summary_if_configured(payload, tenant_id=actual_vault.tenant_id)
    payload["growth_summary_sync"] = summary_sync
    if summary_sync.get("status") == RUNNER_STATUS_EXECUTION_FAILED:
        payload["display_summary"] = "；".join(
            item
            for item in (
                str(payload.get("display_summary") or "").strip(),
                f"GrowthSummary 同步失败：{str(summary_sync.get('reason') or '未知原因').strip()}",
            )
            if item
        )
    actual_vault.write_json_artifact(
        directory,
        "result.json",
        payload,
        owner_type=artifact.artifact_type,
        owner_id=artifact.artifact_id,
        artifact_type=artifact.artifact_type,
    )
    return _replace_artifact_uri(artifact, uri)


def _artifact_response_payload(artifact: Any, *, vault: MediaVault | None) -> dict[str, Any]:
    payload = artifact.to_dict()
    if vault is None or not payload.get("artifact_uri"):
        return payload
    persisted = vault.read_json_artifact(str(payload["artifact_uri"]))
    if isinstance(persisted, dict):
        payload.update(persisted)
    return payload


def _sync_growth_summary_if_configured(
    payload: Any,
    *,
    tenant_id: str,
) -> dict[str, Any]:
    try:
        result = sync_growth_summary_artifact(payload, tenant_id=tenant_id)
    except Exception as exc:
        LOGGER.exception("GrowthSummary sync execution failed for artifact_id=%s", payload.get("artifact_id"))
        return {"ok": False, "status": "execution_failed", "reason": str(exc)}
    if not isinstance(result, dict):
        LOGGER.error("GrowthSummary sync returned non-object result for artifact_id=%s", payload.get("artifact_id"))
        return {"ok": False, "status": "execution_failed", "reason": "GrowthSummary sync returned non-object result"}
    if result.get("status") == "execution_failed":
        LOGGER.error(
            "GrowthSummary sync execution failed for artifact_id=%s: %s",
            payload.get("artifact_id"),
            result.get("reason") or "unknown reason",
        )
    return result


def _replace_artifact_uri(artifact: Any, uri: str) -> Any:
    data = artifact.__dict__.copy()
    data["artifact_uri"] = uri
    return artifact.__class__(**data)


DISPLAY_TEXT_FALLBACK_LABELS = (
    "正文",
    "草稿",
    "备注",
    "说明",
    "目标",
    "主题",
    "问题",
    "内容",
    "标题",
    "body",
    "draft",
    "note",
    "goal",
    "topic",
    "question",
    "content",
    "title",
)


def _display_text_from_parsed(parsed: Any, *preferred_labels: str) -> str:
    if parsed.content_text:
        return str(parsed.content_text).strip()
    for label in (*preferred_labels, *DISPLAY_TEXT_FALLBACK_LABELS):
        value = parsed.value(label)
        if value:
            return value
    return ""


def _display_text_from_artifacts(artifact_summaries: tuple[dict[str, Any], ...] | list[dict[str, Any]]) -> str:
    for item in artifact_summaries:
        if not item.get("loaded"):
            continue
        title = str(item.get("display_title") or "").strip()
        summary = str(item.get("display_summary") or "").strip()
        if title and summary and title != summary:
            return f"{title} {summary}"
        if title:
            return title
        if summary:
            return summary
    return ""


def _draft_text_from_artifacts(artifact_summaries: tuple[dict[str, Any], ...] | list[dict[str, Any]]) -> str:
    for item in artifact_summaries:
        if not item.get("loaded"):
            continue
        draft_text = str(item.get("draft_text") or "").strip()
        if draft_text:
            return draft_text
    return ""


def _title_from_artifacts(artifact_summaries: tuple[dict[str, Any], ...] | list[dict[str, Any]]) -> str:
    for item in artifact_summaries:
        if not item.get("loaded"):
            continue
        title = str(item.get("display_title") or "").strip()
        if title:
            return title
    return ""


def _merge_artifact_refs(*groups: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    refs: list[str] = []
    for group in groups:
        for item in group:
            ref = str(item or "").strip()
            if ref and ref not in refs:
                refs.append(ref)
    return tuple(refs)


def _load_input_artifact_summaries(
    input_artifact_ids: tuple[str, ...] | list[str],
    *,
    vault: MediaVault | None,
) -> tuple[dict[str, Any], ...]:
    summaries: list[dict[str, Any]] = []
    for reference in input_artifact_ids:
        ref = str(reference or "").strip()
        if not ref:
            continue
        payload = load_growth_artifact_payload(ref, vault=vault)
        if not payload:
            summaries.append({"reference": ref, "loaded": False})
            continue
        summaries.append(
            {
                "reference": ref,
                "loaded": True,
                "artifact_id": str(payload.get("artifact_id") or ""),
                "artifact_type": str(payload.get("artifact_type") or ""),
                "artifact_uri": str(payload.get("artifact_uri") or ""),
                "source_capability_id": str(payload.get("source_capability_id") or ""),
                "display_title": str(payload.get("display_title") or ""),
                "display_summary": str(payload.get("display_summary") or ""),
                "raw_text": str(payload.get("raw_text") or ""),
                "draft_text": str(payload.get("draft_text") or ""),
                "caption": str(payload.get("caption") or ""),
                "title": str(payload.get("title") or ""),
                "single_fact": str(payload.get("single_fact") or ""),
                "next_decision_inputs": [str(item) for item in payload.get("next_decision_inputs") or [] if str(item or "").strip()],
                "metrics_summary": dict(payload.get("metrics_summary") or {}) if isinstance(payload.get("metrics_summary"), dict) else {},
                "hashtags": _dedupe_tags(payload.get("hashtags") or ()),
                "urls": [str(url) for url in payload.get("urls") or [] if str(url or "").strip()],
                "quality_status": str(payload.get("quality_status") or ""),
                "source_creation_run_id": str(payload.get("source_creation_run_id") or ""),
                "source_creation_run_file": str(payload.get("source_creation_run_file") or ""),
            }
        )
    return tuple(summaries)


def _merge_artifact_summaries(*groups: tuple[dict[str, Any], ...] | list[dict[str, Any]]) -> tuple[dict[str, Any], ...]:
    summaries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for group in groups:
        for summary in group:
            if not isinstance(summary, dict):
                continue
            key = str(summary.get("artifact_uri") or summary.get("reference") or summary.get("artifact_id") or "").strip()
            if key and key in seen:
                continue
            if key:
                seen.add(key)
            summaries.append(dict(summary))
    return tuple(summaries)


def _load_owned_review_signal_summaries(
    *,
    vault: MediaVault | None,
    account_id: str,
    platform: str,
    track_id: str,
    limit: int = 5,
) -> tuple[dict[str, Any], ...]:
    """Load recent ReviewSignals only from the current tenant's owned vault partition."""
    if vault is None or not clean_text(account_id):
        return ()
    review_root = vault.root / "review_signals"
    if not review_root.is_dir():
        return ()
    candidates: list[tuple[str, str]] = []
    try:
        paths = tuple(review_root.glob("*/result.json"))
    except OSError:
        return ()
    for path in paths:
        try:
            uri = vault.to_uri(path)
            payload = load_growth_artifact_payload(uri, vault=vault)
        except (MediaVaultError, OSError):
            continue
        if str(payload.get("artifact_type") or "") != "ReviewSignal":
            continue
        if clean_text(payload.get("account_id")) != clean_text(account_id):
            continue
        if platform and clean_text(payload.get("platform")) and clean_text(payload.get("platform")) != clean_text(platform):
            continue
        if track_id and clean_text(payload.get("track_id")) and clean_text(payload.get("track_id")) != clean_text(track_id):
            continue
        candidates.append((str(payload.get("updated_at") or payload.get("created_at") or ""), uri))
    refs = tuple(uri for _, uri in sorted(candidates, reverse=True)[: max(1, limit)])
    return _load_input_artifact_summaries(refs, vault=vault)


def _load_owned_post_review_summaries(
    *, vault: MediaVault | None, publish_id: str
) -> tuple[dict[str, Any], ...]:
    """Load local PublishedPost review evidence without crossing tenant boundaries."""
    if vault is None or not clean_text(publish_id):
        return ()
    post_ref = clean_text(publish_id)
    review_root = vault.root / "published_posts"
    if not review_root.is_dir():
        return ()
    summaries: list[dict[str, Any]] = []
    try:
        paths = tuple(review_root.glob("*/review/*/metrics.json"))
    except OSError:
        return ()
    for path in paths:
        post_id = path.parents[2].name
        if post_ref not in {post_id, f"post_{post_ref}"} and post_ref not in path.as_posix():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        metrics = payload.get("metrics") if isinstance(payload, dict) else {}
        if not isinstance(metrics, dict):
            metrics = {}
        summaries.append(
            {
                "artifact_type": "PublishedPostReviewEvidence",
                "artifact_uri": vault.to_uri(path),
                "artifact_id": f"{post_id}:{path.parent.name}",
                "post_id": post_id,
                "review_node": path.parent.name,
                "metrics": {
                    **{str(key): value for key, value in metrics.items()},
                    **{str(key): value for key, value in (metrics.get("format_specific_metrics") or {}).items()},
                },
                "loaded": True,
            }
        )
    return tuple(summaries)


def _load_owned_creator_context(
    *,
    vault: MediaVault | None,
    account_id: str,
    platform: str,
    review_limit: int = 5,
) -> dict[str, Any]:
    empty = {
        "payload": {"source": "owned_local_media_memory", "loaded": False},
        "evidence_items": (),
        "trace": {"source_type": "owned_account_memory", "loaded": False},
    }
    if vault is None or not clean_text(account_id):
        return empty
    try:
        profile = load_account_profile(
            clean_text(platform),
            clean_text(account_id),
            tenant_id=vault.tenant_id,
            root=_owned_media_memory_base(),
        )
    except (OSError, ValueError):
        profile = {}
    reviews_path = _owned_media_memory_root(vault.tenant_id) / "reviews.jsonl"
    reviews = _load_owned_review_memory(
        reviews_path,
        tenant_id=vault.tenant_id,
        account_id=account_id,
        platform=platform,
        limit=review_limit,
    )
    profile_fields = {
        key: profile[key]
        for key in (
            "identity_summary",
            "identity_tags",
            "creator_role",
            "public_persona_boundaries",
            "story_usable_identity_points",
            "positioning_summary",
            "target_audience",
            "content_pillars",
            "proven_patterns",
            "avoid_patterns",
            "recent_lessons",
        )
        if profile.get(key) not in (None, "", [])
    }
    review_text = _owned_review_context_text(reviews)
    prompt_lines = ["仅使用本租户本地账号档案与历史复盘："]
    for label, key in (
        ("账号定位", "positioning_summary"),
        ("核心受众", "target_audience"),
        ("已验证有效模式", "proven_patterns"),
        ("需要规避", "avoid_patterns"),
        ("最近复盘结论", "recent_lessons"),
    ):
        value = profile_fields.get(key)
        if isinstance(value, (list, tuple)):
            value = "；".join(clean_text(item) for item in value if clean_text(item))
        if clean_text(value):
            prompt_lines.append(f"- {label}：{clean_text(value)}")
    if review_text:
        prompt_lines.append("- 历史复盘：" + review_text)
    loaded = bool(profile_fields or reviews)
    source_url = _owned_memory_uri(vault.tenant_id, "reviews.jsonl") if reviews else ""
    evidence_items: tuple[dict[str, Any], ...] = ()
    if review_text and source_url:
        evidence_items = (
            {
                "source_url": source_url,
                "source_type": "account_memory",
                "text_or_summary": review_text,
                "citations": [source_url],
                "status": "ready",
                "metadata": {
                    "tenant_id": vault.tenant_id,
                    "account_id": clean_text(account_id),
                    "platform": clean_text(platform),
                    "record_count": len(reviews),
                },
            },
        )
    return {
        "payload": {
            "source": "owned_local_media_memory",
            "loaded": loaded,
            "profile": profile_fields,
            "recent_reviews": list(reviews),
            "prompt": "\n".join(prompt_lines) if loaded else "",
        },
        "evidence_items": evidence_items,
        "trace": {
            "source_type": "owned_account_memory",
            "loaded": loaded,
            "profile_loaded": bool(profile_fields),
            "recent_review_count": len(reviews),
            "source_urls": [source_url] if source_url else [],
        },
    }


def _load_owned_review_memory(
    path: Path,
    *,
    tenant_id: str,
    account_id: str,
    platform: str,
    limit: int,
) -> tuple[dict[str, Any], ...]:
    if not path.is_file():
        return ()
    rows: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            lines = handle.readlines()[-200:]
    except OSError:
        return ()
    for line in lines:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        if clean_text(row.get("tenant_id")) != tenant_id:
            continue
        if clean_text(row.get("account")) != clean_text(account_id):
            continue
        if platform and clean_text(row.get("platform")) and clean_text(row.get("platform")) != clean_text(platform):
            continue
        rows.append(
            {
                key: row.get(key)
                for key in (
                    "created_at",
                    "platform",
                    "account",
                    "track",
                    "topic",
                    "title",
                    "metrics",
                    "lesson",
                    "summary",
                    "next_step",
                    "performance_level",
                    "key_insights",
                    "next_actions",
                )
                if row.get(key) not in (None, "", [])
            }
        )
    rows.sort(key=lambda row: str(row.get("created_at") or ""), reverse=True)
    return tuple(rows[: max(1, limit)])


def _owned_review_context_text(reviews: tuple[dict[str, Any], ...]) -> str:
    lines: list[str] = []
    for review in reviews:
        lesson = clean_text(review.get("lesson") or review.get("summary"))
        next_step = clean_text(review.get("next_step"))
        if lesson:
            lines.append((lesson + (f"；下一步：{next_step}" if next_step else ""))[:600])
    return "\n".join(dict.fromkeys(lines))[:4000]


def _record_growth_review_memory(signal: ReviewSignal, *, vault: MediaVault | None) -> None:
    if vault is None or not signal.account_id:
        return
    lines = ["【复盘】", f"账号={signal.account_id}"]
    if signal.platform:
        lines.append(f"平台={signal.platform}")
    if signal.track_id:
        lines.append(f"赛道={signal.track_id}")
    if signal.publish_id:
        lines.append(f"作品链接={signal.publish_id}")
    for key, value in signal.metrics_summary.items():
        if clean_text(key) and clean_text(value):
            lines.append(f"{clean_text(key)}={clean_text(value)}")
    if signal.single_fact:
        lines.append(f"结论={signal.single_fact}")
    if signal.next_decision_inputs:
        lines.append(f"下一步={'；'.join(signal.next_decision_inputs)}")
    record_review_memory(
        "\n".join(lines),
        tenant_id=vault.tenant_id,
        source=f"media_growth:ReviewSignal:{signal.artifact_id}",
        analysis={
            "key_insights": list(signal.effective_patterns),
            "next_actions": list(signal.next_decision_inputs),
        },
        root=_owned_media_memory_base(),
    )


def _owned_media_memory_base() -> Path:
    configured = os.environ.get("SELFMEDIA_MEMORY_ROOT", "").strip()
    return Path(configured).expanduser() if configured else DEFAULT_MEMORY_ROOT


def _owned_media_memory_root(tenant_id: str) -> Path:
    return _owned_media_memory_base() / "tenants" / tenant_id


def _owned_memory_uri(tenant_id: str, filename: str) -> str:
    return f"media-memory://tenants/{tenant_id}/{filename}"


def _first_post_publish_action(value: Any) -> str:
    for item in _tuple_text(value):
        if any(marker in item for marker in ("发布后", "首小时", "第一小时", "1小时", "1 小时")):
            return item
    return ""


def _growth_llm_payload(
    *,
    task: str,
    prompt: str,
    text: str,
    platform: str,
    account_id: str,
    track_id: str,
    knowledge_evidence_bundle: KnowledgeEvidenceBundle | dict[str, Any] | None,
    growth_json_provider: GrowthJsonProvider | None,
    growth_json_settings: Any | None,
    require_evidence: bool = True,
    extra_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    runner = GrowthLLMJsonRunner(provider=growth_json_provider, settings=growth_json_settings)
    return runner.run_json(
        task=task,
        prompt=prompt,
        evidence_bundle=knowledge_evidence_bundle,
        require_evidence=require_evidence,
        extra_context={
            "raw_text": clean_text(text),
            "platform": clean_text(platform),
            "account_id": clean_text(account_id),
            "track_id": clean_text(track_id),
            **(extra_context or {}),
        },
    )


def _is_pending_llm_payload(payload: dict[str, Any]) -> bool:
    if not payload:
        return False
    status = str(payload.get("runtime_status") or payload.get("status") or "").strip()
    return status in {"pending_manual", "manual_review", "blocked", "failed"}


def _tuple_text(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        parts = re.split(r"[\n；;]+", value)
    elif isinstance(value, (list, tuple)):
        parts = [str(item or "") for item in value]
    else:
        parts = [str(value or "")]
    result: list[str] = []
    for item in parts:
        text = clean_text(item)
        if text and text not in result:
            result.append(text)
    return tuple(result)


def _split_review_items(value: Any) -> tuple[str, ...]:
    return _tuple_text(value)


def _review_signal_metrics(params: dict[str, str]) -> dict[str, Any]:
    excluded = {
        "平台",
        "platform",
        "账号",
        "account",
        "account_id",
        "赛道",
        "track",
        "track_id",
        "流程",
        "preset",
        "preset_flow",
        "flow",
        "作品id",
        "发布id",
        "publish_id",
        "post_id",
        "作品链接",
        "发布链接",
        "url",
        "单一事实",
        "single_fact",
        "事实",
        "结论",
        "summary",
        "摘要",
        "有效模式",
        "有效",
        "亮点",
        "effective_patterns",
        "失败原因",
        "问题",
        "不足",
        "failure_reasons",
        "下一步",
        "选题输入",
        "建议",
        "next_decision_inputs",
    }
    metrics: dict[str, Any] = {}
    for key, value in params.items():
        normalized_key = str(key or "").strip()
        if not normalized_key or normalized_key.lower() in excluded or normalized_key in excluded:
            continue
        metrics[normalized_key] = _coerce_metric_value(value)
    return metrics


def _coerce_metric_value(value: Any) -> Any:
    text = clean_text(value)
    if re.fullmatch(r"-?\d+", text):
        try:
            return int(text)
        except ValueError:
            return text
    if re.fullmatch(r"-?\d+\.\d+", text):
        try:
            return float(text)
        except ValueError:
            return text
    return text


def _candidate_dicts(value: Any) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, list):
        return ()
    candidates: list[dict[str, Any]] = []
    for raw in value:
        if not isinstance(raw, dict):
            continue
        source_refs = raw.get("source_refs") or raw.get("sources") or raw.get("证据")
        if isinstance(source_refs, str):
            refs = [item for item in re.split(r"[\s,，、]+", source_refs) if item]
        elif isinstance(source_refs, (list, tuple)):
            refs = [str(item or "").strip() for item in source_refs if str(item or "").strip()]
        else:
            refs = []
        pain_point = clean_text(raw.get("pain_point") or raw.get("audience_pain") or raw.get("受众痛点"))
        candidate = {
            "title": clean_text(raw.get("title") or raw.get("标题")),
            "target_audience": clean_text(raw.get("target_audience") or raw.get("目标受众")),
            "pain_point": pain_point,
            "audience_pain": pain_point,
            "content_angle": clean_text(raw.get("content_angle") or raw.get("内容角度")),
            "single_problem": clean_text(raw.get("single_problem") or raw.get("单一问题")),
            "self_check": clean_text(raw.get("self_check") or raw.get("自检")),
            "source_refs": [ref for index, ref in enumerate(refs) if ref and ref not in refs[:index]],
        }
        if candidate["title"]:
            candidates.append(candidate)
    return tuple(candidates[:5])


def _knowledge_evidence_trace(knowledge_evidence_bundle: KnowledgeEvidenceBundle | dict[str, Any] | None) -> dict[str, Any]:
    if knowledge_evidence_bundle is None:
        return {
            "source_type": "knowledge_evidence",
            "loaded": False,
            "note": "typed Knowledge evidence exporter is not available; no delegate fallback is used.",
        }
    try:
        bundle = coerce_knowledge_evidence_bundle(knowledge_evidence_bundle)
    except Exception as exc:
        return {
            "source_type": "knowledge_evidence",
            "loaded": False,
            "status": "contract_failed",
            "note": str(exc),
        }
    ready_items = bundle.ready_items
    return {
        "source_type": "knowledge_evidence",
        "loaded": bool(ready_items),
        "schema_version": bundle.schema_version,
        "bundle_id": bundle.bundle_id,
        "status": bundle.status,
        "evidence_item_count": len(bundle.evidence_items),
        "ready_evidence_item_count": len(ready_items),
        "citations": list(bundle.citations),
        "limitations": list(bundle.limitations),
        "blocked_sources": list(bundle.blocked_sources),
    }


def _effective_knowledge_evidence_bundle(
    knowledge_evidence_bundle: KnowledgeEvidenceBundle | dict[str, Any] | None,
    query: str,
    artifact_summaries: tuple[dict[str, Any], ...] | list[dict[str, Any]],
    *,
    enabled: bool,
    owned_memory_evidence: tuple[dict[str, Any], ...] | list[dict[str, Any]] = (),
) -> KnowledgeEvidenceBundle | dict[str, Any] | None:
    if not enabled:
        return knowledge_evidence_bundle
    bundles: list[KnowledgeEvidenceBundle] = []
    if _has_ready_knowledge_evidence_bundle(knowledge_evidence_bundle):
        bundles.append(coerce_knowledge_evidence_bundle(knowledge_evidence_bundle))
    artifact_bundle = _knowledge_evidence_bundle_from_artifacts(query, artifact_summaries)
    if artifact_bundle is not None:
        bundles.append(artifact_bundle)
    if owned_memory_evidence:
        bundles.append(
            KnowledgeEvidenceBundle.from_dict(
                {
                    "bundle_id": "owned_account_memory",
                    "query": clean_text(query),
                    "status": "ready",
                    "source_system": "owned_account_memory",
                    "evidence_items": [dict(item) for item in owned_memory_evidence if isinstance(item, dict)],
                }
            )
        )
    if not bundles:
        return knowledge_evidence_bundle
    if len(bundles) == 1 and _has_ready_knowledge_evidence_bundle(knowledge_evidence_bundle):
        return bundles[0]
    return _merge_knowledge_evidence_bundles(query, bundles)


def _merge_knowledge_evidence_bundles(
    query: str,
    bundles: list[KnowledgeEvidenceBundle],
) -> KnowledgeEvidenceBundle:
    evidence_items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for bundle in bundles:
        for item in bundle.evidence_items:
            payload = item.to_dict()
            key = str(payload.get("source_hash") or payload.get("source_url") or "")
            if not key or key in seen:
                continue
            seen.add(key)
            evidence_items.append(payload)
    payload = json.dumps(
        {
            "query": clean_text(query),
            "evidence_items": evidence_items,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return KnowledgeEvidenceBundle.from_dict(
        {
            "bundle_id": "combined_bundle_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16],
            "query": clean_text(query),
            "status": "ready",
            "source_system": "media_growth_owned_contracts",
            "evidence_items": evidence_items,
        }
    )


def _knowledge_evidence_bundle_from_artifacts(
    query: str,
    artifact_summaries: tuple[dict[str, Any], ...] | list[dict[str, Any]],
) -> KnowledgeEvidenceBundle | None:
    evidence_items: list[dict[str, Any]] = []
    for item in artifact_summaries:
        if not item.get("loaded"):
            continue
        source_url = str(item.get("artifact_uri") or item.get("reference") or item.get("artifact_id") or "").strip()
        text = _artifact_evidence_text(item)
        if not source_url or not text:
            continue
        evidence_items.append(
            {
                "source_url": source_url,
                "source_type": f"media_growth_artifact:{item.get('artifact_type') or 'unknown'}",
                "text_or_summary": text,
                "citations": [source_url],
                "status": "ready",
                "metadata": {
                    "artifact_id": str(item.get("artifact_id") or ""),
                    "artifact_type": str(item.get("artifact_type") or ""),
                    "source_capability_id": str(item.get("source_capability_id") or ""),
                    "source_creation_run_file": str(item.get("source_creation_run_file") or ""),
                },
            }
        )
    if not evidence_items:
        return None
    payload = json.dumps(
        {
            "query": clean_text(query),
            "items": [
                {
                    "source_url": item.get("source_url"),
                    "source_type": item.get("source_type"),
                    "text_or_summary": item.get("text_or_summary"),
                }
                for item in evidence_items
            ],
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return KnowledgeEvidenceBundle.from_dict(
        {
            "bundle_id": "artifact_bundle_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16],
            "query": clean_text(query),
            "status": "ready",
            "source_system": "media_growth_artifact",
            "evidence_items": evidence_items,
        }
    )


def _artifact_evidence_text(item: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in (
        "display_title",
        "display_summary",
        "raw_text",
        "draft_text",
        "caption",
        "title",
        "single_fact",
    ):
        value = clean_text(item.get(key))
        if value and value not in parts:
            parts.append(value)
    next_inputs = [clean_text(value) for value in item.get("next_decision_inputs") or [] if clean_text(value)]
    if next_inputs:
        parts.append("next_decision_inputs: " + "；".join(next_inputs))
    metrics_summary = item.get("metrics_summary")
    if isinstance(metrics_summary, dict) and metrics_summary:
        parts.append("metrics_summary: " + json.dumps(metrics_summary, ensure_ascii=False, sort_keys=True))
    return "\n".join(parts).strip()[:20000]


def _publish_readiness_blocking_issues(artifact_summaries: tuple[dict[str, Any], ...] | list[dict[str, Any]]) -> tuple[str, ...]:
    issues: list[str] = []
    loaded = [item for item in artifact_summaries if item.get("loaded")]
    if not loaded:
        return ("输入 artifact 无法解析。",)
    for item in loaded:
        artifact_type = str(item.get("artifact_type") or "").strip()
        title = clean_text(item.get("title") or item.get("display_title"))
        body = clean_text(item.get("caption") or item.get("draft_text") or item.get("display_summary"))
        if artifact_type not in {"PublishingPack", "DraftPackage"}:
            issues.append(f"{artifact_type or 'unknown'} 不是发布前 gate 支持的输入类型。")
            continue
        if not title:
            issues.append(f"{artifact_type} 缺少标题。")
        if not body:
            issues.append(f"{artifact_type} 缺少正文/草稿。")
    return tuple(dict.fromkeys(issues))


def _first_loaded_ref_field(artifact_summaries: tuple[dict[str, Any], ...] | list[dict[str, Any]], key: str) -> str:
    for item in artifact_summaries:
        if item.get("loaded") and clean_text(item.get(key)):
            return clean_text(item.get(key))
    return ""


def _has_ready_knowledge_evidence_bundle(knowledge_evidence_bundle: KnowledgeEvidenceBundle | dict[str, Any] | None) -> bool:
    if knowledge_evidence_bundle is None:
        return False
    try:
        bundle = coerce_knowledge_evidence_bundle(knowledge_evidence_bundle).require_ready()
    except Exception:
        return False
    return bool(bundle.ready_items)


def _require_ready_knowledge_evidence_bundle(knowledge_evidence_bundle: KnowledgeEvidenceBundle | dict[str, Any] | None) -> None:
    try:
        coerce_knowledge_evidence_bundle(knowledge_evidence_bundle).require_ready()
    except (InsufficientKnowledgeEvidence, KnowledgeEvidenceContractError) as exc:
        raise MediaGrowthPendingManual(str(exc)) from exc


def _source_trace_with_artifacts(*items: Any) -> tuple[dict[str, Any], ...]:
    traces: list[dict[str, Any]] = []
    artifact_summaries: tuple[dict[str, Any], ...] = ()
    for item in items:
        if isinstance(item, dict):
            traces.append(dict(item))
        elif isinstance(item, (list, tuple)):
            artifact_summaries = tuple(dict(value) for value in item if isinstance(value, dict))
    if artifact_summaries:
        traces.append(
            {
                "source_type": "input_artifacts",
                "loaded": all(bool(item.get("loaded")) for item in artifact_summaries),
                "artifacts": [
                    {
                        "reference": str(item.get("reference") or ""),
                        "artifact_id": str(item.get("artifact_id") or ""),
                        "artifact_type": str(item.get("artifact_type") or ""),
                        "artifact_uri": str(item.get("artifact_uri") or ""),
                        "display_title": str(item.get("display_title") or ""),
                        "source_creation_run_file": str(item.get("source_creation_run_file") or ""),
                        "loaded": bool(item.get("loaded")),
                    }
                    for item in artifact_summaries
                ],
            }
        )
    return tuple(traces)


def _title_from_text(text: str, *, default_text: str) -> str:
    cleaned = _strip_urls_for_display(text)
    if not cleaned:
        return default_text
    first_line = next((line.strip() for line in cleaned.splitlines() if line.strip()), cleaned)
    first_line = re.sub(r"^【[^】]+】\s*", "", first_line).strip()
    return first_line[:60] or default_text


def _summary(text: str, *, default_text: str) -> str:
    cleaned = re.sub(r"\s+", " ", _strip_urls_for_display(text))
    return cleaned[:160] if cleaned else default_text


def _strip_urls_for_display(text: str) -> str:
    cleaned = clean_text(text)
    for url in extract_urls(cleaned):
        cleaned = cleaned.replace(url, " ")
    return re.sub(r"\s+", " ", cleaned).strip()


def _extract_hash_tags(text: str) -> list[str]:
    tags: list[str] = []
    for match in re.finditer(r"#([\w\u4e00-\u9fff-]+)", text or ""):
        tag = match.group(1).strip()
        if tag and tag not in tags:
            tags.append(tag)
    return tags[:8]


def _dedupe_tags(values: Any) -> tuple[str, ...]:
    tags: list[str] = []
    raw_values = values if isinstance(values, (list, tuple)) else (values,)
    for value in raw_values:
        for tag in _tag_values(value):
            if tag and tag not in tags:
                tags.append(tag)
    return tuple(tags[:8])


def _source_asset_kind(parsed: ParsedMediaGrowthInput, urls: tuple[str, ...]) -> str:
    raw = clean_text(parsed.value("素材类型", "类型", "source_kind", "kind")).lower()
    normalized = re.sub(r"[\s_-]+", "", raw)
    if normalized in {"链接", "link", "url", "网址"}:
        return "link"
    if normalized in {"图片", "图文", "照片", "截图", "image", "photo", "screenshot"}:
        return "image"
    if normalized in {"视频", "video", "短视频"}:
        return "video"
    if normalized in {"文字", "文本", "灵感", "表达", "text", "idea"}:
        return "text"
    if normalized in {"转写", "转写稿", "transcript"}:
        return "transcript"
    if normalized in {"活动", "活动brief", "activity", "activitybrief"}:
        return "activity_brief"
    if normalized in {"附件", "attachment", "file"}:
        return "attachment"
    return "link" if urls else "user_text"


def _preset_flow_id_from_plan(plan: WorkflowPlan) -> str:
    match = re.search(r"preset_flow=([A-Za-z0-9_.=-]+)", str(plan.reason or ""))
    if match:
        return match.group(1)
    if "activity_brief_to_shooting" in str(plan.reason or ""):
        return "activity_brief_to_shooting"
    return ""


def _plan_blocked_executable_alternative(preset_flow_id: str, text: str) -> dict[str, str]:
    if preset_flow_id != "activity_brief_to_shooting":
        return {}
    parsed = parse_media_growth_input(text)
    hint = (
        parsed.content_text
        or parsed.value("备注", "说明", "主题", "目标", "正文", "问题")
        or clean_text(re.sub(r"^【[^】]+】", "", text or ""))
    )
    hint = _summary(hint, default_text="你的素材/主题") if hint else "你的素材/主题"
    return {
        "preset_flow": "asset_to_topic",
        "label": "素材",
        "button_text": "先做素材→选题",
        "command": f"【素材】流程=asset_to_topic 备注={hint}",
        "description": "先执行已实装的素材→选题子流程；拍摄执行节点接入前不自动串行。",
    }


def _planned_node_statuses(plan: WorkflowPlan) -> list[dict[str, Any]]:
    return [
        {
            "canonical_capability_id": node.canonical_capability_id,
            "implemented": is_capability_implemented(node.canonical_capability_id),
            "implementation_status": capability_implementation_status(node.canonical_capability_id),
            "produces": list(node.produces),
            "consumes": list(node.consumes),
        }
        for node in plan.planned_nodes
    ]


def _is_media_growth_payload(payload: dict[str, Any]) -> bool:
    if not isinstance(payload, dict):
        return False
    if str(payload.get("schema_version") or "") == "media_growth_artifact_v1":
        return True
    return str(payload.get("source_capability_id") or "") in CAPABILITY_SPECS


def _normalize_review_action(action: str) -> str:
    mapping = {
        "approve": "approve",
        "approved": "approve",
        "clean": "approve",
        "cleaned": "approve",
        "pass": "approve",
        "通过": "approve",
        "verify": "verify",
        "verified": "verify",
        "accept": "verify",
        "accepted": "verify",
        "验收": "verify",
        "reject": "reject",
        "rejected": "reject",
        "discard": "reject",
        "废弃": "reject",
    }
    return mapping.get(str(action or "").strip().lower(), "")


def _utc_now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class MediaGrowthPendingManual(RuntimeError):
    pass
