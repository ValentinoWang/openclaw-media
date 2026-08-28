from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from common.llm_client import generate_json_from_parts
from common.llm_validation import LLMValidationContract, register_llm_validation_contract
from common.llm_settings import load_profile_llm_settings

from .platform_validator import validate_platform_draft
from .request_parser import CreationRequest
from selfmedia.style.context_loader import load_anti_patterns


CREATOR_BRIEF_REPORT_MODE = {
    "report_mode": "creator_brief",
    "show_raw_evidence": False,
    "max_primary_options": 1,
    "max_backup_options": 2,
    "max_activities": 1,
    "max_viral_refs": 3,
    "max_inspiration_refs": 3,
    "appendix_enabled": True,
}


def creation_generation_metadata(mode: str) -> dict[str, str]:
    settings = load_profile_llm_settings("media_creation")
    return {
        "provider": "codex_responses",
        "profile": "media_creation",
        "model": settings.model,
        "thinking": settings.thinking,
        "mode": mode,
    }


def generate_creation_draft(
    request: CreationRequest,
    *,
    activity_candidates: list[dict[str, Any]],
    viral_candidates: list[dict[str, Any]],
    inspiration_candidates: list[dict[str, Any]],
    business_candidates: list[dict[str, Any]],
    reference_docs: list[dict[str, str]],
    media_context: dict[str, Any],
    platform_fit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    candidate_ids = {
        "selected_activity_ids": _candidate_id_set(activity_candidates),
        "selected_viral_ids": _candidate_id_set(viral_candidates),
        "selected_inspiration_ids": _candidate_id_set(inspiration_candidates),
        "selected_business_ids": _candidate_id_set(business_candidates),
    }
    prompt = build_creation_prompt(
        request,
        activity_candidates=activity_candidates,
        viral_candidates=viral_candidates,
        inspiration_candidates=inspiration_candidates,
        business_candidates=business_candidates,
        reference_docs=reference_docs,
        media_context=media_context,
        platform_fit=platform_fit,
    )
    last_error = ""
    for attempt in range(_env_int("SELFMEDIA_CREATION_LLM_RETRIES", 2) + 1):
        message = prompt
        if last_error:
            message = (
                f"{prompt}\n\n"
                "上一次输出没有通过代码校验。\n"
                f"错误：{last_error}\n"
                "请重新输出完整 JSON object，只修正格式和约束，不要解释。"
            )
        try:
            draft = call_creation_json(
                message,
                validation_contract=CREATION_DRAFT_VALIDATION_CONTRACT,
                validation_context={"request": request, "platform_fit": platform_fit, "candidate_ids": candidate_ids},
            )
            draft["_generation"] = creation_generation_metadata("creation_draft")
            return draft
        except ValueError as exc:
            last_error = str(exc)
            if attempt >= _env_int("SELFMEDIA_CREATION_LLM_RETRIES", 2):
                break
    raise RuntimeError(f"OpenClaw/LLM 创作输出未通过校验：{last_error}")


def build_creation_prompt(
    request: CreationRequest,
    *,
    activity_candidates: list[dict[str, Any]],
    viral_candidates: list[dict[str, Any]],
    inspiration_candidates: list[dict[str, Any]],
    business_candidates: list[dict[str, Any]],
    reference_docs: list[dict[str, str]],
    media_context: dict[str, Any],
    platform_fit: dict[str, Any] | None = None,
) -> str:
    payload = _compact_creation_prompt_payload({
        "request": request.to_dict(),
        "media_memory_prompt": (media_context or {}).get("prompt") or "",
        "media_context_loaded": (media_context or {}).get("loaded") or {},
        "account_profile": (media_context or {}).get("account_profile") or {},
        "recent_creations": (media_context or {}).get("recent_creations") or [],
        "recent_reviews": (media_context or {}).get("recent_reviews") or [],
        "activity_memory_candidates": activity_candidates,
        "viral_memory_candidates": viral_candidates,
        "inspiration_memory_candidates": inspiration_candidates,
        "business_memory_candidates": business_candidates,
        "reference_docs": reference_docs,
        "platform_mechanism_fit": platform_fit or {},
        "report_mode": CREATOR_BRIEF_REPORT_MODE,
    })
    platform_rules = {
        "小红书": "标题不超过 20 个字符；tags 必须给 3-10 个与内容强相关的标签，不得用无关标签凑数；图文必须输出 image_script 或 carousel；视频必须输出 storyboard。",
        "抖音": "标题不能为空；tags 必须给 2-5 个与内容强相关的标签，不得用无关标签凑数；视频必须输出 hook_3s、storyboard、voiceover、subtitles；图文必须输出 image_script 或 carousel。",
        "B站": "标题不能为空；tags 给 2-8 个与分区和主题强相关的标签；视频必须输出 hook_3s、storyboard、voiceover、subtitles；图文必须输出 image_script 或 carousel。",
    }
    return (
        "你是 OpenClaw media bot 的创作总编。现在由 OpenClaw/LLM 接管【创作】主链路，"
        "启发式规则只作为硬约束和资料边界，不负责写稿。\n\n"
        "任务：基于用户请求、活动记忆、爆款记忆、商务记忆、账号 Markdown 档案和最近对话，"
        "选择真正适合的参考记录，并生成可直接进入飞书创作文档的平台化初稿。\n\n"
        "硬约束：\n"
        f"1. platform 必须等于 {request.platform}；content_type 必须等于 {request.content_type}；topic 必须围绕 {request.topic}。\n"
        f"2. 平台规则：{platform_rules.get(request.platform, '必须符合平台字段校验。')}\n"
        "3. selected_activity_ids、selected_viral_ids、selected_inspiration_ids、selected_business_ids 只能使用候选里的 id；没有适合参考就输出空数组。\n"
        "4. 活动、商务、爆款、创作灵感数据只来自输入记忆；禁止编造活动奖励、投稿规则、商务承诺、互动数据、个人经历或账号事实。\n"
        "5. 允许创造表达、标题、脚本、分镜和叙事结构；但必须显式说明用了哪些活动/爆款/创作灵感/账号记忆，没用则说明原因。\n"
        "6. 参考爆款只能迁移结构、冲突、情绪推进、行动门槛和画面组织，不得复刻原文；参考创作灵感优先迁移真实场景、信号、观点和可复用角度。inspiration_memory_candidates 里 source_table=Obsidian:人性洞察库 的记录只能作为 insight-card reference，帮助选择目标群体、情绪路径和开头钩子句式；它不是源视频事实，不得写成观众真实画像或私人心理判断。\n"
        "7. 如果账号 Markdown 档案信息不足，要在 risks_or_missing_info 中说明要补什么，但仍基于现有输入完成初稿。\n"
        "8. 不要直接从主题跳到标题或脚本。必须先输出 content_core，再输出 topic_strategy；content_core 要回答这条内容真正要让观众记住什么、看见什么具体场景、解决哪个非泛泛的问题、用哪句内容承诺钉住主线。\n"
        "9. topic_strategy 中拆清楚目标人群、真实痛点、单一内容角度、只解决的一个小问题和自查标准，再在 script_options 中生成 title/final_copy。\n"
        "10. 如果参考素材里有 OCR 或图片文字，只能当作素材证据和文案补全来源；最终 final_copy、title、content_core、topic_strategy 必须经过清洗和改写，不得原样堆叠 OCR。\n"
        "11. 必须参考 platform_mechanism_fit 里的 platform_strategy、activity_strategy、creation_reverse_plan 和 validation_targets；平台机制只能约束标题、封面/首屏、发布策略和验证指标，不能决定内容核心；不得声称破解平台真实算法或掌握黑箱权重。\n"
        "12. 先生成 usable_material_brief，再写 script_options。usable_material_brief 必须按“来源 -> 可迁移层 -> 脚本落点”抽取可用素材：账号记忆的人设/禁区/复盘教训；创作灵感的真实场景/触发原话/核心观点；爆款候选只能使用其 multi_signal_contract 的 source_signal_dimensions、shot_adaptation_notes、conflict_notes、open_questions 和 validation。transform_rule 是可迁移结构，risk_boundary 与 do_not_copy 是硬边界；source_refs 只证明合同中的观察，不能补写原素材细节。不得绕回任何非合同的拆解摘要、镜头 compact、文档链接或内部源快照。活动候选的投稿约束/话题/截止或返稿要求；商务候选的品牌边界。script_options 只能吃这个 brief 写稿，不要在脚本正文里展开完整来源映射。\n"
        "13. 完整来源映射必须进入 usable_material_brief.source_mapping、creator_report.evidence_appendix 或 script_options 的机器字段；创作者执行区只出现拍摄、文案、发布和风险动作，不输出检索报告口吻。\n"
        "14. 每个 script_options 项都必须保留 activity_fit_reason、viral_reference_reason、inspiration_reference_reason 作为机器字段：写清用了哪个候选 id、迁移了哪一层、落到哪个镜头/页面/台词/封面/评论引导；没采用的来源要在 risks_or_missing_info 或 rejected_option_summaries 说明原因。活动只能约束发布/投稿/话题，不得硬改内容核心；爆款只能给结构和节奏，不得给事实；灵感和账号记忆优先决定内容事实与表达边界；洞察卡必须标为 insight-card reference，并在证据附录保留卡片路径/状态和风险边界。\n"
        f"15. 必须先评估多个创作方向，再把 2-5 个完整脚本放入 script_options；score > {CREATION_SCORE_THRESHOLD} 是高分方案，score <= {CREATION_SCORE_THRESHOLD} 也必须保留为可选方案，不得因为未达门槛而不给完整脚本。\n"
        f"16. script_options 最少 2 个、最多 5 个；如果没有方案超过 {CREATION_SCORE_THRESHOLD} 分，也必须输出至少 2 个评分最高且可执行的完整方案，并在风险中说明未达门槛的原因。\n"
        f"17. 每个 script_options 项必须包含 option_id、score_breakdown、title、angle、score_reason、selected_*_ids、activity_fit_reason、viral_reference_reason、inspiration_reference_reason、risk_level、risks_or_missing_info、tags、final_copy、image_script、carousel、hook_3s、storyboard、voiceover、subtitles、production_checklist、review_plan。score_reason 对所有方案都写评分理由；未达 {CREATION_SCORE_THRESHOLD} 的方案要写“未达门槛的原因 + 为什么仍可作为备选执行”。\n"
        "18. score_breakdown 固定 7 项：evidence_grounding(20)、platform_fit(15)、audience_pain(15)、creative_angle(15)、execution_completeness(15)、reference_integration(15)、risk_control(5)。总分由程序对分项求和，不要重复输出 score。\n"
        "19. script_options 初稿后必须输出 editor_pass。editor_pass 是同一次 LLM 输出里的苛刻总编二改阶段，必须检查：是否像真实内容而不是方案、是否有具体画面/动作/台词、是否有平庸表达、是否证据链污染执行稿、推荐方案改了哪些句子。"
        "editor_pass 还必须做去 AI 腔检查并把结论写进 blandness_risks：final_copy、voiceover、title、封面字、置顶评论里不得出现『首先/其次/最后』连用、『总之』『综上』『值得一提的是』『不难发现』『让我们一起』式套话、连续三个以上排比句、每句结尾都用感叹号、与账号无关的网络热词堆叠；口播每句尽量不超过 22 个字，允许口语连接词和自然的不完整句，写完要能直接读出口不别扭。"
        "editor_pass 完成后，必须把所有可执行修订直接写回 recommended_option_id 指向的 script_options 项；该项是唯一的可执行定稿，不能只改顶层字段。"
        "顶层 title/tags/final_copy/image_script/carousel/hook_3s/storyboard/voiceover/subtitles/production_checklist/review_plan/risks_or_missing_info 是旧消费者可选镜像，新输出不要重复完整脚本；如输出，必须逐字段等于编辑后的推荐项。\n"
        "20. recommended_option_id 必须来自 script_options 里的 option_id，并且 editor_pass.recommended_option_id 必须相同。\n"
        f"21. 可以输出 rejected_option_summaries 说明未进入前 5 的方向为什么被舍弃；但前 2 个最可执行方向必须进入 script_options，即使 score <= {CREATION_SCORE_THRESHOLD}。\n"
        "22. 必须输出 candidate_match_assessments，对被选中的爆款和创作灵感给出 0-100 匹配分、分项和 selection_reason。"
        "candidate_match_assessments 固定是 object，且必须只包含两个数组字段：viral 和 inspiration；即使没有已选参考，也必须输出 \"viral\": [] 和 \"inspiration\": []。"
        "每个 selected_viral_ids 中的 id 都必须在 candidate_match_assessments.viral 里有一项；每个 selected_inspiration_ids 中的 id 都必须在 candidate_match_assessments.inspiration 里有一项。"
        "每项固定结构为 {id, score_breakdown, selection_reason}；总分由程序对分项求和；不得把 viral 或 inspiration 输出成 object、字符串或按 id 分组的 map。"
        "爆款分项固定为 request_fit(40)、content_value(20)、transferability(25)、evidence_completeness(15)。"
        "灵感分项固定为 request_fit(35)、inspiration_quality(25)、transferability(25)、evidence_and_risk(15)。"
        "selected_viral_ids、selected_inspiration_ids 只是采用关系，不是满分依据；不得输出 LLM选择爆款=100 或 LLM选择创作灵感=100 作为评分。\n"
        "23. 输出协议必须是 creator_brief：你不是检索结果报告生成器，而是自媒体创作总编。"
        "creator_report 是给真人创作者看的执行稿，必须先讲拍什么、怎么开头、怎么发；不得在 creator_report 的执行区输出原始 JSON、record_id、评分细节、数据库字段、长链接或重复活动说明。\n"
        "24. creator_report 必须分两层：第一层创作者执行版；第二层证据附录。执行版包含创作方案总览、这条内容怎么拍、这条内容怎么发、素材检查清单、风险控制。证据附录只能放在最后，且必须摘要化展示：只保留来源类型、record_id、采用原因、可迁移层、脚本落点和风险边界；不得粘贴候选原文、长段活动 brief、完整爆款拆解或原始检索结果。\n"
        "25. creator_report 第一屏最终推荐只能有 1 个主方案，最多 2 个备选方向摘要；但 script_options 中 2-5 个完整脚本都必须保留，并由 writer 渲染在同一个创作文档的脚本方案区；不得拆成多个文档。"
        "评分、评分理由、选择论证、来源匹配论证一律只出现在证据附录和机器字段：执行区、脚本方案正文不得出现分数、score_reason、命中理由或任何『为什么选它』的论证段。"
        "活动最多保留 1 个父活动 + 推荐子方向；爆款最多 3 个且必须转译成“这条视频学什么”；灵感最多 3 个且必须说明落到哪个镜头/台词/道具。\n"
        "26. creator_report 不设置固定总字数预算，不以总长度作为裁剪依据。长度控制方式是结构完整性、去重复、去系统解释和执行密度控制：执行区必须清楚可扫读，脚本区必须完整可执行，证据附录必须摘要化后置；不得为了压缩篇幅牺牲完整 script_options、素材检查、风险控制或 evidence_appendix。\n"
        "27. 图文字段和视频字段条件化：content_type=图文 时 image_script 或 carousel 必须非空，hook_3s/storyboard/voiceover/subtitles 可为空字符串/空数组；content_type=视频 时 hook_3s、storyboard、voiceover、subtitles 必须非空，image_script/carousel 可为空数组。不要为了填满 irrelevant 字段硬编。\n"
        "28. 同一句策略不得在多个章节重复出现；只输出合法 JSON object，不要 Markdown 代码块，不要解释。\n"
        "29. 复盘必须回流：recent_reviews 非空时，usable_material_brief.execution_brief 必须写明上一轮复盘教训对这一条的具体动作（沿用什么、这次改掉什么），并且 creator_report.risk_controls 至少有一条直接来自最近复盘；recent_reviews 为空时在 risks_or_missing_info 说明缺少复盘数据。\n"
        "30. 账号声音优先：final_copy、voiceover、置顶评论必须贴合 account_profile 里可见的说话方式（称呼观众的习惯、常用句式、语气边界）；不得写成平台通用腔。account_profile 缺少语言风格信息时，在 risks_or_missing_info 写明需要补充账号语言样本，但仍按现有信息完成初稿。\n"
        "31. 商单必须落到执行：selected_business_ids 非空时，usable_material_brief 的 usage_boundaries 必须写明品牌必提点、禁词/禁区和审核红线各自落到哪一句文案或哪个镜头；publishing_pack.first_hour_action 必须给出发布后 1 小时内的具体运营动作（例如回评引导句、置顶时机、投放判断信号），无商单时 first_hour_action 也要给自然流量版动作。\n\n"
        "输出 JSON 字段固定为：\n"
        "platform, content_type, topic, content_core, topic_strategy, usable_material_brief, inspiration, activity_constraint, "
        "viral_reference, inspiration_reference, business_reference, account_context, positioning_analysis, platform_strategy, "
        "activity_strategy, traffic_hypothesis, creation_reverse_plan, validation_targets, selected_activity_ids, "
        "selected_viral_ids, selected_inspiration_ids, selected_business_ids, image_script, carousel, hook_3s, storyboard, voiceover, "
        "subtitles, production_checklist, review_plan, risks_or_missing_info, script_options, recommended_option_id, rejected_option_summaries, "
        "editor_pass, candidate_match_assessments, creator_report。report_mode 由程序注入，不要输出。\n\n"
        "content_core 字段必须包含：content_promise, viewer_problem, specific_scene, memorable_point, must_show。\n"
        "topic_strategy 字段必须包含：target_audience, pain_point, content_angle, single_problem, self_check。\n\n"
        "usable_material_brief 字段必须包含：execution_brief, source_mapping, usage_boundaries。\n"
        "editor_pass 字段必须包含：recommended_option_id, blandness_risks, revisions_applied, final_recommendation_reason。\n\n"
        "candidate_match_assessments 示例结构：{\"viral\":[{\"id\":\"候选id\",\"score_breakdown\":{\"request_fit\":34,\"content_value\":16,\"transferability\":22,\"evidence_completeness\":12},\"selection_reason\":\"可迁移的开头结构\"}],\"inspiration\":[{\"id\":\"候选id\",\"score_breakdown\":{\"request_fit\":30,\"inspiration_quality\":22,\"transferability\":22,\"evidence_and_risk\":12},\"selection_reason\":\"落到起跑前镜头\"}]}。\n\n"
        "report_mode 由程序注入，不要输出。\n"
        "creator_report 固定结构：{overview, opening_3s, mainline, storyboard, publishing_pack, material_checklist, risk_controls, evidence_appendix}。"
        "overview 包含 recommended_topic, core_sentence, platform, content_type, suitable_activity, strongly_recommend_activity, biggest_risk。"
        "opening_3s 包含 visual_0_0_5, caption_or_voice_0_5_3, do_not_open_like_this。"
        "mainline 包含 conflict, evidence, emotional_payoff, audience_resonance。"
        "storyboard 用数组，每项包含 time, visual, subtitle, sound, shooting_note。"
        "publishing_pack 包含 title_1, title_2, cover_text, body_copy, hashtags, pinned_comment, comment_prompt, first_hour_action。"
        "material_checklist 包含 must_have, better_to_have, can_rescue_without, must_not_fabricate。"
        "risk_controls 用数组，每项包含 condition, rewrite_or_action。"
        "evidence_appendix 包含 activities, viral_refs, inspiration_refs, business_info, scoring_and_record_ids。\n\n"
        "输入 JSON：\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )


def validate_llm_draft_payload(
    payload: dict[str, Any],
    request: CreationRequest,
    *,
    platform_fit: dict[str, Any] | None = None,
    candidate_ids: dict[str, set[str]] | None = None,
    must_keep: Any = (),
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("LLM JSON 顶层必须是 object")
    draft = dict(payload)
    optional_top_level_mirrors = _promote_legacy_top_level_mirror_to_recommended_option(draft)
    script_options = _normalize_script_options(draft.get("script_options"), request, candidate_ids=candidate_ids)
    if not script_options:
        raise ValueError("script_options_empty")
    draft["script_options"] = script_options
    recommended_option_id = str(draft.get("recommended_option_id") or "").strip()
    recommended = _recommended_script_option(script_options, recommended_option_id)
    if not recommended:
        raise ValueError("recommended_option_id 必须来自 script_options")
    draft["recommended_option_id"] = recommended["option_id"]
    _validate_optional_top_level_mirrors(optional_top_level_mirrors, recommended)
    _mirror_recommended_option_to_draft(draft, recommended)
    for key in ("platform", "content_type", "title", "topic", "final_copy", "hook_3s", "voiceover"):
        draft[key] = str(draft.get(key) or "").strip()
    if draft["platform"] != request.platform:
        raise ValueError(f"LLM 输出 platform 必须为 {request.platform}")
    if draft["content_type"] != request.content_type:
        raise ValueError(f"LLM 输出 content_type 必须为 {request.content_type}")
    for key in (
        "tags",
        "inspiration",
        "selected_activity_ids",
        "selected_viral_ids",
        "selected_inspiration_ids",
        "selected_business_ids",
        "subtitles",
        "production_checklist",
        "review_plan",
        "risks_or_missing_info",
    ):
        draft[key] = _as_string_list(draft.get(key))
    draft["candidate_match_assessments"] = _normalize_candidate_match_assessments(
        draft.get("candidate_match_assessments"),
        draft,
        candidate_ids or {},
    )
    for key in ("activity_constraint", "viral_reference", "inspiration_reference", "business_reference", "account_context"):
        draft[key] = _as_dict(draft.get(key), default_key="summary")
    draft["positioning_analysis"] = _as_dict(draft.get("positioning_analysis"), default_key="positioning")
    draft["content_core"] = _validate_content_core(draft.get("content_core"))
    draft["topic_strategy"] = _as_dict(draft.get("topic_strategy"), default_key="summary")
    _require_mapping_keys(draft["topic_strategy"], "topic_strategy", ("target_audience", "pain_point", "content_angle", "single_problem", "self_check"))
    draft["usable_material_brief"] = _validate_usable_material_brief(draft.get("usable_material_brief"))
    platform_fit = platform_fit or {}
    for key in ("platform_strategy", "activity_strategy", "traffic_hypothesis", "creation_reverse_plan", "validation_targets"):
        draft[key] = _as_dict(draft.get(key), default_key="summary") or _as_dict(platform_fit.get(key), default_key="summary")
    for key in ("image_script", "carousel", "storyboard"):
        draft[key] = _as_list(draft.get(key))
    draft["rejected_option_summaries"] = _as_list(draft.get("rejected_option_summaries"))
    if not draft["title"]:
        raise ValueError("title 不能为空")
    if not draft["final_copy"]:
        raise ValueError("final_copy 不能为空")
    if not draft["inspiration"]:
        raise ValueError("inspiration 不能为空")
    if not draft["production_checklist"]:
        raise ValueError("production_checklist 不能为空")
    if not draft["review_plan"]:
        raise ValueError("review_plan 不能为空")
    if request.content_type == "图文" and not (draft["image_script"] or draft["carousel"]):
        raise ValueError("图文稿必须输出 image_script 或 carousel")
    if request.content_type == "视频":
        if not draft["hook_3s"]:
            raise ValueError("视频稿必须输出 hook_3s")
        if not draft["storyboard"]:
            raise ValueError("视频稿必须输出 storyboard")
        if not draft["voiceover"]:
            raise ValueError("视频稿必须输出 voiceover")
        if not draft["subtitles"]:
            raise ValueError("视频稿必须输出 subtitles")
    _validate_recommended_anti_patterns(draft, must_keep=must_keep)
    validation = validate_platform_draft(request.platform, request.content_type, draft)
    if not validation.ok:
        messages = "; ".join(issue.message for issue in validation.issues)
        raise ValueError(f"平台规则校验失败：{messages}")
    draft["editor_pass"] = _validate_editor_pass(draft.get("editor_pass"), draft["recommended_option_id"])
    draft["report_mode"] = dict(CREATOR_BRIEF_REPORT_MODE)
    draft["creator_report"] = _validate_creator_report(draft.get("creator_report"), request)
    _validate_insight_card_reference_boundary(draft)
    return draft


def _validate_recommended_anti_patterns(draft: dict[str, Any], *, must_keep: Any) -> None:
    if isinstance(must_keep, str):
        preserved_phrases = {must_keep.strip()} if must_keep.strip() else set()
    elif isinstance(must_keep, (list, tuple, set, frozenset)):
        preserved_phrases = {str(phrase).strip() for phrase in must_keep if str(phrase).strip()}
    else:
        preserved_phrases = set()
    for field in ("title", "final_copy", "hook_3s", "voiceover"):
        text = draft[field]
        for phrase in load_anti_patterns():
            if any(phrase in preserved for preserved in preserved_phrases):
                continue
            if phrase in text:
                raise ValueError(f"推荐稿 {field} 包含通用模板表达：{phrase}")


CREATION_SCORE_THRESHOLD = 90
SCRIPT_OPTION_MIN_COUNT = 2
SCRIPT_OPTION_MAX_COUNT = 5
SCRIPT_OPTION_SCORE_BREAKDOWN_LIMITS = {
    "evidence_grounding": 20,
    "platform_fit": 15,
    "audience_pain": 15,
    "creative_angle": 15,
    "execution_completeness": 15,
    "reference_integration": 15,
    "risk_control": 5,
}
SCRIPT_OPTION_REQUIRED_TEXT_FIELDS = (
    "option_id",
    "title",
    "angle",
    "score_reason",
    "final_copy",
    "activity_fit_reason",
    "viral_reference_reason",
    "inspiration_reference_reason",
    "risk_level",
)
MATCH_ASSESSMENT_LIMITS = {
    "viral": {
        "request_fit": 40,
        "content_value": 20,
        "transferability": 25,
        "evidence_completeness": 15,
    },
    "inspiration": {
        "request_fit": 35,
        "inspiration_quality": 25,
        "transferability": 25,
        "evidence_and_risk": 15,
    },
}
SCRIPT_OPTION_LIST_FIELDS = (
    "tags",
    "selected_activity_ids",
    "selected_viral_ids",
    "selected_inspiration_ids",
    "selected_business_ids",
    "risks_or_missing_info",
    "image_script",
    "carousel",
    "storyboard",
    "subtitles",
    "production_checklist",
    "review_plan",
)

CREATION_PROMPT_TEXT_LIMITS = {
    "title": 140,
    "content": 420,
    "audience": 220,
    "pain_points": 260,
    "core_value": 260,
    "direction": 520,
    "activity_brief": 700,
    "activity_guidance": 520,
    "participation_requirement": 420,
    "participation_method": 320,
    "participation_form": 220,
    "submission_requirement": 420,
    "activity_reward": 260,
    "cover_opening_hook": 420,
    "core_data_summary": 420,
    "top_comment_insight": 900,
    "target_audience": 700,
    "pain_or_pleasure_points": 700,
    "attention_elements": 700,
    "viral_mechanism": 520,
    "viral_migration": 520,
    "creative_upgrade_suggestion": 520,
    "usable_material_brief": 900,
    "reference_shots": 1200,
    "reference_production_summary": 900,
    "reuse_guardrails": 900,
    "viral_reuse_assessment": 900,
}
CREATION_PROMPT_CANDIDATE_FIELDS = (
    "id",
    "source_record_id",
    "relation_id",
    "source_table",
    "record_type",
    "multi_signal_contract",
    "title",
    "content",
    "status",
    "platform",
    "content_type",
    "content_type_requirement",
    "track",
    "topic",
    "tags",
    "audience",
    "pain_points",
    "core_value",
    "publish_time",
    "start_time",
    "end_time",
    "deadline",
    "boost_date",
    "source_link",
    "doc_links",
    "metrics",
    "activity_level",
    "activity_reward",
    "participation_requirement",
    "direction",
    "activity_brief",
    "activity_guidance",
    "participation_method",
    "participation_form",
    "submission_requirement",
    "brief_link",
    "viral_example_link",
    "submission_link",
    "activity_doc_link",
    "cover_opening_hook",
    "core_data_summary",
    "top_comment_insight",
    "target_audience",
    "pain_or_pleasure_points",
    "attention_elements",
    "viral_mechanism",
    "viral_migration",
    "creative_upgrade_suggestion",
    "usable_material_brief",
    "reference_shots",
    "reference_production_summary",
    "reuse_guardrails",
    "viral_reuse_assessment",
    "pacing_notes",
    "score",
    "raw_score",
    "score_scale",
    "reasons",
)


def _compact_creation_prompt_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "request": payload.get("request") or {},
        "media_memory_prompt": _truncate_text(payload.get("media_memory_prompt"), 3000),
        "media_context_loaded": _truncate_nested(payload.get("media_context_loaded") or {}, 300),
        "account_profile": _truncate_nested(payload.get("account_profile") or {}, 2500),
        "recent_creations": _truncate_list(payload.get("recent_creations"), 8, 900),
        "recent_reviews": _truncate_list(payload.get("recent_reviews"), 8, 900),
        "activity_memory_candidates": _compact_candidates(payload.get("activity_memory_candidates"), 30),
        "viral_memory_candidates": _compact_candidates(payload.get("viral_memory_candidates"), 30),
        "inspiration_memory_candidates": _compact_candidates(payload.get("inspiration_memory_candidates"), 30),
        "business_memory_candidates": _compact_candidates(payload.get("business_memory_candidates"), 12),
        "reference_docs": _compact_reference_docs(payload.get("reference_docs")),
        "platform_mechanism_fit": _truncate_nested(payload.get("platform_mechanism_fit") or {}, 3000),
        "prompt_compaction_note": (
            "候选证据已按字段白名单和长度预算压缩；候选 id、标题、时间、状态、活动 brief、话题、"
            "报名/返稿链接、爆款示范链接、文档链接和 02B 可读拆解字段优先保留。详情 JSON 源快照不进入最终创作提示词。"
        ),
    }


def _compact_candidates(value: Any, max_items: int) -> list[dict[str, Any]]:
    candidates = value if isinstance(value, list) else []
    compacted: list[dict[str, Any]] = []
    for raw in candidates[:max_items]:
        if not isinstance(raw, dict):
            continue
        item: dict[str, Any] = {}
        for key in CREATION_PROMPT_CANDIDATE_FIELDS:
            if key not in raw:
                continue
            item[key] = _compact_candidate_value(key, raw.get(key))
        compacted.append({key: value for key, value in item.items() if value not in (None, "", [], {})})
    return compacted


def _compact_candidate_value(key: str, value: Any) -> Any:
    if key == "multi_signal_contract":
        return _truncate_nested(value or {}, 4000)
    if key == "tags":
        return _as_string_list(value)[:12]
    if key == "doc_links":
        return _truncate_nested(value or {}, 500)
    if key == "metrics":
        return _truncate_nested(value or {}, 500)
    if isinstance(value, str):
        return _truncate_text(value, CREATION_PROMPT_TEXT_LIMITS.get(key, 260))
    if isinstance(value, (dict, list)):
        return _truncate_nested(value, CREATION_PROMPT_TEXT_LIMITS.get(key, 500))
    return value


def _compact_reference_docs(value: Any) -> list[dict[str, str]]:
    docs = value if isinstance(value, list) else []
    compacted: list[dict[str, str]] = []
    for raw in docs[:8]:
        if not isinstance(raw, dict):
            continue
        compacted.append(
            {
                "title": _truncate_text(raw.get("title"), 160),
                "url": _truncate_text(raw.get("url"), 500),
                "source": _truncate_text(raw.get("source"), 120),
                "content": _truncate_text(raw.get("content") or raw.get("text"), 1800),
            }
        )
    return [item for item in compacted if any(item.values())]


def _truncate_list(value: Any, max_items: int, max_text: int) -> list[Any]:
    items = value if isinstance(value, list) else []
    return [_truncate_nested(item, max_text) for item in items[:max_items]]


def _truncate_nested(value: Any, max_text: int) -> Any:
    if isinstance(value, str):
        return _truncate_text(value, max_text)
    if isinstance(value, list):
        return [_truncate_nested(item, max_text) for item in value[:20]]
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= 40:
                result["_truncated_keys"] = len(value) - 40
                break
            result[str(key)] = _truncate_nested(item, max_text)
        return result
    return value


def _truncate_text(value: Any, max_chars: int) -> str:
    text = str(value or "").strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 12].rstrip() + "...[truncated]"


def _normalize_script_options(
    value: Any,
    request: CreationRequest,
    *,
    candidate_ids: dict[str, set[str]] | None = None,
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError("script_options 必须是 list")
    if len(value) < SCRIPT_OPTION_MIN_COUNT:
        raise ValueError("script_options 最少 2 个")
    if len(value) > SCRIPT_OPTION_MAX_COUNT:
        raise ValueError("script_options 最多 5 个")
    options: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in value:
        if not isinstance(raw, dict):
            raise ValueError("script_options 每一项必须是 object")
        option = dict(raw)
        for key in SCRIPT_OPTION_REQUIRED_TEXT_FIELDS:
            option[key] = str(option.get(key) or "").strip()
            if not option[key]:
                raise ValueError(f"script_options.{key} 不能为空")
        option_id = option["option_id"]
        if option_id in seen:
            raise ValueError(f"script_options option_id 重复：{option_id}")
        seen.add(option_id)
        option["score_breakdown"] = _normalize_score_breakdown(option.get("score_breakdown"))
        option["score"] = sum(option["score_breakdown"].values())
        for key in SCRIPT_OPTION_LIST_FIELDS:
            option[key] = _as_string_list(option.get(key)) if key != "storyboard" else _as_list(option.get(key))
        option["hook_3s"] = str(option.get("hook_3s") or "").strip()
        option["voiceover"] = str(option.get("voiceover") or "").strip()
        option.setdefault("platform", request.platform)
        option.setdefault("content_type", request.content_type)
        _validate_option_candidate_ids(option, candidate_ids or {})
        option_draft = {
            **option,
            "platform": request.platform,
            "content_type": request.content_type,
            "topic": request.topic,
        }
        validation = validate_platform_draft(request.platform, request.content_type, option_draft)
        if not validation.ok:
            messages = "; ".join(issue.message for issue in validation.issues)
            raise ValueError(f"script_options 平台规则校验失败：{option_id}: {messages}")
        options.append(option)
    return sorted(options, key=lambda item: int(item["score"]), reverse=True)


def _normalize_score_breakdown(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        raise ValueError("script_options.score_breakdown 必须是 object")
    normalized: dict[str, int] = {}
    for key, max_score in SCRIPT_OPTION_SCORE_BREAKDOWN_LIMITS.items():
        if key not in value:
            raise ValueError(f"script_options.score_breakdown 缺少 {key}")
        try:
            item = int(value.get(key))
        except (TypeError, ValueError):
            raise ValueError(f"script_options.score_breakdown.{key} 必须是整数") from None
        if item < 0 or item > max_score:
            raise ValueError(f"script_options.score_breakdown.{key} 必须在 0-{max_score}")
        normalized[key] = item
    return normalized


def _validate_option_candidate_ids(option: dict[str, Any], candidate_ids: dict[str, set[str]]) -> None:
    for key in ("selected_activity_ids", "selected_viral_ids", "selected_inspiration_ids", "selected_business_ids"):
        if key not in candidate_ids:
            continue
        unknown = [item for item in option.get(key, []) if item not in candidate_ids[key]]
        if unknown:
            raise ValueError(f"{key} 包含非候选 id：{unknown}")


def _normalize_candidate_match_assessments(
    value: Any,
    draft: dict[str, Any],
    candidate_ids: dict[str, set[str]],
) -> dict[str, list[dict[str, Any]]]:
    if not isinstance(value, dict):
        raise ValueError("candidate_match_assessments 必须是 object")
    normalized: dict[str, list[dict[str, Any]]] = {"viral": [], "inspiration": []}
    for kind, limits in MATCH_ASSESSMENT_LIMITS.items():
        raw_items = value.get(kind)
        if raw_items is None:
            raw_items = []
        if not isinstance(raw_items, list):
            raise ValueError(f"candidate_match_assessments.{kind} 必须是 list")
        selected_key = "selected_viral_ids" if kind == "viral" else "selected_inspiration_ids"
        id_key = "selected_viral_ids" if kind == "viral" else "selected_inspiration_ids"
        known_ids = candidate_ids.get(id_key, set())
        seen: set[str] = set()
        for raw in raw_items:
            if not isinstance(raw, dict):
                raise ValueError(f"candidate_match_assessments.{kind} 每项必须是 object")
            item = dict(raw)
            item_id = str(item.get("id") or "").strip()
            if not item_id:
                raise ValueError(f"candidate_match_assessments.{kind}.id 不能为空")
            if known_ids and item_id not in known_ids:
                raise ValueError(f"candidate_match_assessments.{kind}.id 非候选 id：{item_id}")
            if item_id in seen:
                raise ValueError(f"candidate_match_assessments.{kind}.id 重复：{item_id}")
            seen.add(item_id)
            breakdown = _normalize_match_breakdown(item.get("score_breakdown"), limits, f"candidate_match_assessments.{kind}.score_breakdown")
            score = sum(breakdown.values())
            selection_reason = str(item.get("selection_reason") or "").strip()
            if not selection_reason:
                raise ValueError(f"candidate_match_assessments.{kind}.selection_reason 不能为空")
            normalized[kind].append(
                {
                    "id": item_id,
                    "score": score,
                    "score_breakdown": breakdown,
                    "selection_reason": selection_reason,
                }
            )
        selected_ids = set(_as_string_list(draft.get(selected_key)))
        missing = sorted(item for item in selected_ids if item not in seen)
        if missing:
            raise ValueError(f"candidate_match_assessments.{kind} 缺少已选 id 评分：{missing}")
    return normalized


def _normalize_match_breakdown(value: Any, limits: dict[str, int], path: str) -> dict[str, int]:
    if not isinstance(value, dict):
        raise ValueError(f"{path} 必须是 object")
    normalized: dict[str, int] = {}
    for key, max_score in limits.items():
        if key not in value:
            raise ValueError(f"{path} 缺少 {key}")
        try:
            item = int(value.get(key))
        except (TypeError, ValueError):
            raise ValueError(f"{path}.{key} 必须是整数") from None
        if item < 0 or item > max_score:
            raise ValueError(f"{path}.{key} 必须在 0-{max_score}")
        normalized[key] = item
    return normalized


def _validate_insight_card_reference_boundary(draft: dict[str, Any]) -> None:
    selected = [item for item in _as_string_list(draft.get("selected_inspiration_ids")) if item.startswith("insight_card:")]
    if not selected:
        return
    payload_text = json.dumps(
        {
            "usable_material_brief": draft.get("usable_material_brief"),
            "inspiration_reference": draft.get("inspiration_reference"),
            "creator_report": draft.get("creator_report"),
            "script_options": [
                {
                    "option_id": item.get("option_id"),
                    "selected_inspiration_ids": item.get("selected_inspiration_ids"),
                    "inspiration_reference_reason": item.get("inspiration_reference_reason"),
                }
                for item in draft.get("script_options", [])
                if isinstance(item, dict)
            ],
            "candidate_match_assessments": (draft.get("candidate_match_assessments") or {}).get("inspiration"),
        },
        ensure_ascii=False,
    )
    if "insight-card reference" not in payload_text:
        raise ValueError("selected insight_card inspiration 必须标注为 insight-card reference")
    if "public_content_only" not in payload_text:
        raise ValueError("selected insight_card inspiration 必须保留 public_content_only evidence_boundary")
    forbidden = ("私密人物档案", "social 私密", "私人心理判断")
    if any(marker in payload_text for marker in forbidden):
        raise ValueError("selected insight_card inspiration 只能作为公开证据 reference，不能当作私密画像或源视频事实")
    source_fact_claims = ("作为源视频事实", "当作源视频事实", "就是源视频事实")
    if any(marker in payload_text for marker in source_fact_claims):
        raise ValueError("selected insight_card inspiration 只能作为公开证据 reference，不能当作源视频事实")


def _recommended_script_option(options: list[dict[str, Any]], recommended_option_id: str) -> dict[str, Any]:
    if not recommended_option_id:
        return {}
    for option in options:
        if option["option_id"] == recommended_option_id:
            return option
    return {}


def _mirror_recommended_option_to_draft(draft: dict[str, Any], option: dict[str, Any]) -> None:
    for key in SCRIPT_OPTION_MIRROR_FIELDS:
        draft[key] = option.get(key)


SCRIPT_OPTION_MIRROR_FIELDS = (
    "title",
    "tags",
    "final_copy",
    "selected_activity_ids",
    "selected_viral_ids",
    "selected_inspiration_ids",
    "selected_business_ids",
    "image_script",
    "carousel",
    "hook_3s",
    "storyboard",
    "voiceover",
    "subtitles",
    "production_checklist",
    "review_plan",
    "risks_or_missing_info",
)


def _promote_legacy_top_level_mirror_to_recommended_option(draft: dict[str, Any]) -> dict[str, Any]:
    """Normalize legacy editor revisions into the canonical recommended option."""
    top_level_mirrors = {key: draft[key] for key in SCRIPT_OPTION_MIRROR_FIELDS if key in draft}
    if not top_level_mirrors:
        return {}
    if len(top_level_mirrors) != len(SCRIPT_OPTION_MIRROR_FIELDS):
        return top_level_mirrors
    options = draft.get("script_options")
    recommended_option_id = str(draft.get("recommended_option_id") or "").strip()
    if not isinstance(options, list) or not recommended_option_id:
        return top_level_mirrors
    for index, raw_option in enumerate(options):
        if not isinstance(raw_option, dict) or str(raw_option.get("option_id") or "").strip() != recommended_option_id:
            continue
        option = dict(raw_option)
        option.update(top_level_mirrors)
        options[index] = option
        return {}
    return top_level_mirrors


def _validate_optional_top_level_mirrors(mirrors: dict[str, Any], option: dict[str, Any]) -> None:
    for key, value in mirrors.items():
        if _normalized_mirror_value(key, value) != option.get(key):
            raise ValueError(f"顶层 {key} 必须等于 recommended_option_id 指向的 script_options 项")


def _normalized_mirror_value(key: str, value: Any) -> Any:
    if key in {"title", "final_copy", "hook_3s", "voiceover"}:
        return str(value or "").strip()
    if key == "storyboard":
        return _as_list(value)
    return _as_string_list(value)


def _validate_report_mode(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("report_mode 必须是 object")
    normalized = dict(value)
    for key, expected in CREATOR_BRIEF_REPORT_MODE.items():
        if normalized.get(key) != expected:
            raise ValueError(f"report_mode.{key} 必须等于 {expected!r}")
    return normalized


def _validate_content_core(value: Any) -> dict[str, Any]:
    data = _as_dict(value, default_key="summary")
    _require_mapping_keys(data, "content_core", ("content_promise", "viewer_problem", "specific_scene", "memorable_point", "must_show"))
    return data


def _validate_usable_material_brief(value: Any) -> dict[str, Any]:
    data = _as_dict(value, default_key="execution_brief")
    _require_mapping_keys(data, "usable_material_brief", ("execution_brief", "source_mapping", "usage_boundaries"))
    if not str(data.get("execution_brief") or "").strip():
        raise ValueError("usable_material_brief.execution_brief 不能为空")
    if data.get("source_mapping") in (None, "", [], {}):
        raise ValueError("usable_material_brief.source_mapping 不能为空")
    return data


def _validate_editor_pass(value: Any, recommended_option_id: str) -> dict[str, Any]:
    data = _as_dict(value, default_key="summary")
    _require_mapping_keys(data, "editor_pass", ("recommended_option_id", "blandness_risks", "revisions_applied", "final_recommendation_reason"))
    if str(data.get("recommended_option_id") or "").strip() != recommended_option_id:
        raise ValueError("editor_pass.recommended_option_id 必须等于 recommended_option_id")
    return data


def _validate_creator_report(value: Any, request: CreationRequest) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("creator_report 必须是 object")
    report = dict(value)
    required_sections = {
        "overview": dict,
        "opening_3s": dict,
        "mainline": dict,
        "storyboard": list,
        "publishing_pack": dict,
        "material_checklist": dict,
        "risk_controls": list,
        "evidence_appendix": dict,
    }
    for section, expected_type in required_sections.items():
        if not isinstance(report.get(section), expected_type):
            raise ValueError(f"creator_report.{section} 必须是 {expected_type.__name__}")
    _require_report_keys(report["overview"], "creator_report.overview", ("recommended_topic", "core_sentence", "platform", "content_type", "suitable_activity", "strongly_recommend_activity", "biggest_risk"))
    if str(report["overview"].get("platform") or "").strip() != request.platform:
        raise ValueError(f"creator_report.overview.platform 必须等于 {request.platform}")
    if str(report["overview"].get("content_type") or "").strip() != request.content_type:
        raise ValueError(f"creator_report.overview.content_type 必须等于 {request.content_type}")
    _require_report_keys(report["opening_3s"], "creator_report.opening_3s", ("visual_0_0_5", "caption_or_voice_0_5_3", "do_not_open_like_this"))
    _require_report_keys(report["mainline"], "creator_report.mainline", ("conflict", "evidence", "emotional_payoff", "audience_resonance"))
    _require_report_keys(report["publishing_pack"], "creator_report.publishing_pack", ("title_1", "title_2", "cover_text", "body_copy", "hashtags", "pinned_comment", "comment_prompt", "first_hour_action"))
    if not str(report["publishing_pack"].get("first_hour_action") or "").strip():
        raise ValueError("creator_report.publishing_pack.first_hour_action 不能为空")
    _require_report_keys(report["material_checklist"], "creator_report.material_checklist", ("must_have", "better_to_have", "can_rescue_without", "must_not_fabricate"))
    for index, row in enumerate(report["storyboard"], 1):
        if not isinstance(row, dict):
            raise ValueError(f"creator_report.storyboard[{index}] 必须是 object")
        _require_report_keys(row, f"creator_report.storyboard[{index}]", ("time", "visual", "subtitle", "sound", "shooting_note"))
    for index, item in enumerate(report["risk_controls"], 1):
        if not isinstance(item, dict):
            raise ValueError(f"creator_report.risk_controls[{index}] 必须是 object")
        _require_report_keys(item, f"creator_report.risk_controls[{index}]", ("condition", "rewrite_or_action"))
    return report


def _require_report_keys(data: dict[str, Any], path: str, keys: tuple[str, ...]) -> None:
    missing = [key for key in keys if key not in data]
    if missing:
        raise ValueError(f"{path} 缺少字段：{missing}")


def _require_mapping_keys(data: dict[str, Any], path: str, keys: tuple[str, ...]) -> None:
    missing = [key for key in keys if key not in data]
    if missing:
        raise ValueError(f"{path} 缺少字段：{missing}")


def _candidate_id_set(candidates: list[dict[str, Any]]) -> set[str]:
    ids: set[str] = set()
    for item in candidates:
        for key in ("id", "source_record_id", "relation_id"):
            value = str(item.get(key) or "").strip()
            if value:
                ids.add(value)
    return ids


def _validate_creation_draft_contract(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    request = context.get("request")
    if not isinstance(request, CreationRequest):
        raise ValueError("creation draft validation requires CreationRequest context")
    return validate_llm_draft_payload(
        payload,
        request,
        platform_fit=context.get("platform_fit"),
        candidate_ids=context.get("candidate_ids"),
    )


CREATION_DRAFT_VALIDATION_CONTRACT = register_llm_validation_contract(
    LLMValidationContract(
        contract_id="selfmedia.creation.draft.v1",
        profile="strict_structured",
        validator=_validate_creation_draft_contract,
    )
)


def call_creation_json(
    message: str,
    *,
    validation_contract: str,
    validation_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    settings = load_profile_llm_settings("media_creation")
    return generate_json_from_parts(
        [{"text": message}],
        settings,
        max_retries=1,
        error_prefix="Codex Responses 创作输出 JSON 校验失败",
        instructions=_creation_role_instructions(validation_contract),
        validation_contract=validation_contract,
        validation_context=validation_context,
    )


def _creation_role_instructions(validation_contract: str) -> str:
    roles = {
        "selfmedia.creation.request_inference.v1": "需求解析员，只提取用户明确表达或可直接推导的创作条件，不补写文案。",
        "selfmedia.creation.platform_fit.v1": "平台策略编辑，依据平台机制和现有证据给出适配判断，不虚构数据。",
        "selfmedia.creation.platform_note.v1": "平台资料编辑，把现有机制整理成简洁、可执行的创作提示。",
        "selfmedia.creation.consultation.v1": "创作咨询同事，用自然中文回答当前选择和缺口，不写报告腔。",
        "selfmedia.creation.shooting_request.v1": "拍摄需求解析员，只整理本轮拍摄目标、条件和限制。",
        "selfmedia.creation.shooting_plan.v1": "拍摄导演，把已确认的创作方案转成现场可执行镜头和动作。",
        "selfmedia.creation.shooting_narrative_plan.v1": "叙事导演，检查镜头顺序、节奏和信息递进。",
        "selfmedia.creation.shooting_backwash_review.v1": "审稿编辑，只判断修改是否落实且是否引入新风险。",
        "selfmedia.creation.draft.v1": "中文自媒体主编，基于给定证据产出可直接拍摄和发布的方案。",
    }
    role = roles.get(validation_contract, "中文内容编辑，严格按当前任务和证据工作。")
    return (
        f"你是 OpenClaw Media 的{role}"
        "输出协议是严格 JSON：只输出一个合法 JSON object，不要 Markdown，不要解释。"
        "用户可见字段使用自然中文；机器字段遵守约定枚举。"
    )


def _as_string_list(value: Any) -> list[str]:
    result = []
    for item in _as_list(value):
        text = str(item or "").strip(" #\t")
        if text:
            result.append(text)
    return result


def _as_list(value: Any) -> list[Any]:
    if value in (None, "", []):
        return []
    if isinstance(value, list):
        return [item for item in value if item not in (None, "", [])]
    if isinstance(value, str):
        return [item.strip() for item in re.split(r"[\n,，、;；]+", value) if item.strip()]
    return [value]


def _as_dict(value: Any, *, default_key: str) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    text = str(value or "").strip()
    return {default_key: text} if text else {}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default
