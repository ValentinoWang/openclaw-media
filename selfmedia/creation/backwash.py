from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from common.llm_validation import LLMValidationContract, register_llm_validation_contract
from media_vault.vault import MediaVault, utc_now_iso

from .llm_generator import CREATION_SCORE_THRESHOLD, call_creation_json
from .shooting_execution import (
    SHOOTING_PLAN_VALIDATION_CONTRACT,
    ShootingExecutionRequest,
    creator_facing_deconstruction_evidence,
    localize_shooting_execution_plan_values,
    validate_shooting_execution_plan,
)
from .writer import rewrite_shooting_execution_doc


NARRATIVE_PLAN_FIELDS = frozenset({"storyline", "strategy", "beats", "global_rules"})
NARRATIVE_BEAT_FIELDS = frozenset(
    {
        "beat_id",
        "order",
        "subject_id",
        "chapter",
        "location",
        "narrative_role",
        "purpose",
        "transition_from_previous",
        "callback_to",
    }
)
NARRATIVE_ROLES = frozenset(
    {"hook_setup", "context", "introduction", "development", "transition", "hook_payoff", "conclusion"}
)
NARRATIVE_STRATEGIES = frozenset(
    {"chronological", "result_hook_then_chronological", "problem_solution", "experience_escalation"}
)
COHERENCE_PASS_SCORE = CREATION_SCORE_THRESHOLD
NARRATIVE_STRATEGY_CODES = {
    "按时间推进": "chronological",
    "先给结果再回到过程": "result_hook_then_chronological",
    "问题与解决": "problem_solution",
    "体验逐层升级": "experience_escalation",
}
NARRATIVE_ROLE_CODES = {
    "悬念设置": "hook_setup",
    "背景交代": "context",
    "介绍主体": "introduction",
    "展开": "development",
    "转场": "transition",
    "悬念回收": "hook_payoff",
    "收束": "conclusion",
}
NARRATIVE_STRATEGY_LABELS = {value: key for key, value in NARRATIVE_STRATEGY_CODES.items()}
NARRATIVE_ROLE_LABELS = {value: key for key, value in NARRATIVE_ROLE_CODES.items()}
BACKWASH_REVIEW_FIELDS = frozenset(
    {
        "status",
        "coherence_score",
        "storyline_summary",
        "critical_issues",
        "transition_issues",
        "subject_reentry_issues",
        "satisfied_requirements",
        "missing_requirements",
        "reason",
    }
)


def _validate_narrative_plan(payload: dict[str, Any], _context: dict[str, Any]) -> dict[str, Any]:
    if set(payload) != NARRATIVE_PLAN_FIELDS:
        raise ValueError("narrative plan fields invalid")
    if _narrative_strategy_code(payload.get("strategy")) not in NARRATIVE_STRATEGIES:
        raise ValueError("narrative strategy invalid")
    if not str(payload.get("storyline") or "").strip():
        raise ValueError("narrative storyline missing")
    beats = payload.get("beats")
    if not isinstance(beats, list) or not 3 <= len(beats) <= 24:
        raise ValueError("narrative beats must contain 3-24 items")
    if not isinstance(payload.get("global_rules"), list) or not payload.get("global_rules"):
        raise ValueError("narrative global_rules missing")
    seen_beat_ids: set[str] = set()
    last_subject_index: dict[str, int] = {}
    last_location_index: dict[str, int] = {}
    for index, beat in enumerate(beats):
        if not isinstance(beat, dict) or set(beat) != NARRATIVE_BEAT_FIELDS:
            raise ValueError(f"narrative beat {index + 1} fields invalid")
        if beat.get("order") != index + 1:
            raise ValueError("narrative beat order must be contiguous")
        beat_id = str(beat.get("beat_id") or "").strip()
        if not beat_id or beat_id in seen_beat_ids:
            raise ValueError("narrative beat_id must be non-empty and unique")
        seen_beat_ids.add(beat_id)
        role = _narrative_role_code(beat.get("narrative_role"))
        if role not in NARRATIVE_ROLES:
            raise ValueError(f"narrative beat {beat_id} role invalid")
        for name in ("subject_id", "chapter", "location", "purpose", "transition_from_previous"):
            if not str(beat.get(name) or "").strip():
                raise ValueError(f"narrative beat {beat_id} missing {name}")
        callback_to = str(beat.get("callback_to") or "").strip()
        if callback_to and callback_to not in seen_beat_ids:
            raise ValueError(f"narrative beat {beat_id} callback target must precede the beat")
        subject_id = str(beat["subject_id"]).strip()
        previous_subject_index = last_subject_index.get(subject_id)
        if previous_subject_index is not None and index - previous_subject_index > 1:
            if role not in {"hook_payoff", "conclusion"} or not callback_to:
                raise ValueError(f"narrative subject {subject_id} re-enters without an explicit payoff callback")
        last_subject_index[subject_id] = index
        location = str(beat["location"]).strip()
        previous_location_index = last_location_index.get(location)
        if previous_location_index is not None and index - previous_location_index > 1:
            if role not in {"hook_payoff", "conclusion"} or not callback_to:
                raise ValueError(f"narrative location {location} re-enters without an explicit payoff callback")
        last_location_index[location] = index
    return payload


def _validate_backwash_review(payload: dict[str, Any], _context: dict[str, Any]) -> dict[str, Any]:
    if str(payload.get("status") or "") not in {"passed", "needs_revision"}:
        raise ValueError("backwash review status must be passed or needs_revision")
    try:
        score = float(payload.get("coherence_score"))
    except (TypeError, ValueError) as exc:
        raise ValueError("backwash coherence_score must be numeric") from exc
    if not 0 <= score <= 100:
        raise ValueError("backwash coherence_score must be 0-100")
    for name in (
        "critical_issues",
        "transition_issues",
        "subject_reentry_issues",
        "satisfied_requirements",
        "missing_requirements",
    ):
        if not isinstance(payload.get(name), list):
            raise ValueError(f"backwash review {name} must be a list")
    if not str(payload.get("storyline_summary") or "").strip() or not str(payload.get("reason") or "").strip():
        raise ValueError("backwash review summary/reason missing")
    if payload.get("status") == "passed" and (
        score < COHERENCE_PASS_SCORE
        or payload.get("critical_issues")
        or payload.get("transition_issues")
        or payload.get("subject_reentry_issues")
        or payload.get("missing_requirements")
    ):
        raise ValueError("passed backwash review still contains coherence failures")
    return payload


NARRATIVE_PLAN_CONTRACT = register_llm_validation_contract(
    LLMValidationContract(
        contract_id="selfmedia.creation.shooting_narrative_plan.v1",
        profile="strict_structured",
        required_fields=tuple(NARRATIVE_PLAN_FIELDS),
        allowed_fields=NARRATIVE_PLAN_FIELDS,
        field_types={"storyline": str, "strategy": str, "beats": list, "global_rules": list},
        non_empty_fields=("storyline", "strategy", "beats", "global_rules"),
        validator=_validate_narrative_plan,
    )
)


BACKWASH_REVIEW_CONTRACT = register_llm_validation_contract(
    LLMValidationContract(
        contract_id="selfmedia.creation.shooting_backwash_review.v1",
        profile="strict_structured",
        required_fields=tuple(BACKWASH_REVIEW_FIELDS),
        allowed_fields=BACKWASH_REVIEW_FIELDS,
        field_types={
            "status": str,
            "coherence_score": (int, float),
            "storyline_summary": str,
            "critical_issues": list,
            "transition_issues": list,
            "subject_reentry_issues": list,
            "satisfied_requirements": list,
            "missing_requirements": list,
            "reason": str,
        },
        non_empty_fields=("status", "storyline_summary", "reason"),
        validator=_validate_backwash_review,
    )
)


def handle_shooting_execution_backwash(
    doc_url: str,
    edit_requirements: str,
    *,
    tenant_id: str,
) -> dict[str, Any]:
    target = _canonical_doc_url(doc_url)
    requirements = str(edit_requirements or "").strip()
    if not requirements:
        raise ValueError("拍摄执行回洗缺少修改要求")
    run_id, run_dir, request_payload, input_payload, current_draft = _find_creation_run(
        target,
        tenant_id=tenant_id,
    )
    media_context = input_payload.get("media_context") if isinstance(input_payload.get("media_context"), dict) else {}
    request = _restore_shooting_request(request_payload, input_payload, current_draft)
    narrative_plan, narrative_plan_review = _build_narrative_plan(
        current_draft, requirements, media_context
    )
    revised, review = _generate_revised_draft(
        current_draft, requirements, media_context, narrative_plan
    )
    validation = validate_shooting_execution_plan(revised)
    if not validation.get("ok"):
        raise RuntimeError(f"拍摄执行回洗结构校验失败：{validation}")
    if not _reviews_passed(narrative_plan_review, review):
        return {
            "ok": False,
            "status": "pending_manual",
            "doc_link": target,
            "creation_run_id": run_id,
            "validation": validation,
            "narrative_plan": narrative_plan,
            "narrative_plan_review": narrative_plan_review,
            "semantic_review": review,
            "candidate_draft": revised,
            "reply": "自动回洗已生成候选稿，但语义验收未通过；原拍摄执行文档未被覆盖，请根据问题清单人工确认后再处理。",
        }
    _validate_practical_shape(current_draft, revised, requirements=requirements)
    written_url = rewrite_shooting_execution_doc(target, request, revised, validation, media_context=media_context)
    if _canonical_doc_url(written_url) != target:
        raise RuntimeError(f"拍摄执行回洗返回了不同文档：{written_url}")
    _persist_backwash(
        tenant_id,
        run_id,
        run_dir,
        request_payload,
        input_payload,
        revised,
        validation,
        target,
        requirements,
        narrative_plan,
        narrative_plan_review,
        review,
    )
    return {
        "ok": True,
        "status": "shooting_execution_backwashed",
        "doc_link": target,
        "creation_run_id": run_id,
        "validation": validation,
        "narrative_plan": narrative_plan,
        "narrative_plan_review": narrative_plan_review,
        "semantic_review": review,
        "reply": f"已通过【修改】回洗拍摄执行文档，并覆盖原链接：{target}",
    }


def _canonical_doc_url(value: str) -> str:
    parsed = urlparse(str(value or "").strip())
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2 or parts[-2] not in {"wiki", "docx", "doc", "docs"}:
        raise ValueError("只支持飞书 Wiki/Docx 文档链接")
    kind = "wiki" if parts[-2] == "wiki" else "docx"
    return f"https://tcnwueberajc.feishu.cn/{kind}/{parts[-1]}"


def _find_creation_run(
    target: str,
    *,
    tenant_id: str,
) -> tuple[str, Path, dict[str, Any], dict[str, Any], dict[str, Any]]:
    vault = MediaVault(tenant_id=tenant_id)
    matches: list[tuple[str, Path, dict[str, Any]]] = []
    root = vault.root / "creation_runs"
    for path in root.glob("*/request.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            candidate = _canonical_doc_url(str(payload.get("doc_link") or ""))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if candidate == target:
            matches.append((path.parent.name, path.parent, payload))
    if len(matches) != 1:
        raise RuntimeError(f"拍摄执行文档必须唯一映射 CreationRun，当前匹配数：{len(matches)}")
    run_id, run_dir, request_payload = matches[0]
    try:
        input_payload = json.loads((run_dir / "input.json").read_text(encoding="utf-8"))
        draft = json.loads((run_dir / "draft_output.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"CreationRun artifact 不可读：{exc}") from exc
    if not isinstance(input_payload, dict) or not isinstance(draft, dict):
        raise RuntimeError("CreationRun artifact 结构无效")
    return run_id, run_dir, request_payload, input_payload, draft


def _restore_shooting_request(
    request_payload: dict[str, Any], input_payload: dict[str, Any], draft: dict[str, Any]
) -> ShootingExecutionRequest:
    saved = request_payload.get("request") if isinstance(request_payload.get("request"), dict) else {}
    goal = draft.get("shooting_goal") if isinstance(draft.get("shooting_goal"), dict) else {}
    locations = _unique_strings(item.get("location") for item in draft.get("route_map") or [] if isinstance(item, dict))
    people = _unique_strings(item.get("people") for item in draft.get("route_map") or [] if isinstance(item, dict))
    topic = str(saved.get("topic") or "").strip()
    time_window = _time_window_from_title_hint(input_payload, topic)
    return ShootingExecutionRequest(
        platform=str(saved.get("platform") or goal.get("platform") or "抖音"),
        content_type=str(saved.get("content_type") or goal.get("content_type") or "视频"),
        track=str(saved.get("track") or "未提供"),
        topic=topic,
        shooting_goal=str(saved.get("user_idea") or goal.get("mainline") or "回洗既有拍摄执行稿"),
        locations=locations or ["以原执行稿为准"],
        people=people or ["以原执行稿为准"],
        time_window=time_window,
        project=str(saved.get("project") or ""),
        account=str(saved.get("account") or ""),
        keywords=list(saved.get("keywords") or []),
        source_asset_id=str(saved.get("source_asset_id") or ""),
        raw_text=str(input_payload.get("raw_text") or saved.get("raw_text") or ""),
    )


def _time_window_from_title_hint(input_payload: dict[str, Any], topic: str) -> str:
    raw = str(input_payload.get("raw_text") or "")
    for line in raw.splitlines():
        if line.startswith(("时间窗口=", "时间窗口：", "总时长=", "总时长：")):
            return line.split("=", 1)[-1].split("：", 1)[-1].strip()
    return "未定时间"


def _unique_strings(values: Any) -> list[str]:
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _build_narrative_plan(
    current: dict[str, Any], requirements: str, media_context: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    prompt = _narrative_plan_prompt(current, requirements, media_context)
    last_plan: dict[str, Any] = {}
    last_review: dict[str, Any] = {}
    for _attempt in range(2):
        last_plan = call_creation_json(prompt, validation_contract=NARRATIVE_PLAN_CONTRACT)
        last_review = _review_narrative_plan(current, requirements, last_plan)
        if last_review.get("status") == "passed":
            return last_plan, last_review
        prompt = _narrative_plan_prompt(
            current,
            requirements,
            media_context,
            review=last_review,
            previous=last_plan,
        )
    return last_plan, last_review


def _narrative_plan_prompt(
    current: dict[str, Any],
    requirements: str,
    media_context: dict[str, Any],
    *,
    review: dict[str, Any] | None = None,
    previous: dict[str, Any] | None = None,
) -> str:
    return (
        "你是 OpenClaw Media 的叙事规划导演。先规划整条拍摄执行稿的唯一叙事顺序，不写最终分镜，只输出合法 JSON object。\n"
        "先固定一条主线和连续章节，再安排产品、地点与因果关系。每个产品或主题必须在一个连续章节内介绍完成。\n"
        "禁止无理由的 A→B→A 主体回跳或场地回跳；只有开头设置的明确悬念，才允许在后文以悬念回收处理，"
        "并用 callback_to 指向前面的悬念设置。结尾总结不得重新介绍已经结束的产品。\n"
        "transition_from_previous 必须说明相邻两拍的事实、空间、时间或因果关系，不能用一句口播掩盖无关主题切换。\n"
        "beats 按 order 严格排序，subject_id 对同一主体始终使用同一个稳定名称。\n"
        "叙事策略只能是按时间推进、先给结果再回到过程、问题与解决、体验逐层升级之一。\n"
        "叙事角色只能是悬念设置、背景交代、介绍主体、展开、转场、悬念回收、收束之一。\n"
        "输出字段固定为 storyline, strategy, beats, global_rules。每个 beat 字段固定为 beat_id, order, subject_id, "
        "chapter, location, narrative_role, purpose, transition_from_previous, callback_to。无回扣时 callback_to 为空字符串。\n\n"
        f"用户修改要求：\n{requirements}\n\n"
        f"账号与创作上下文：\n{json.dumps(_creator_facing_media_context(media_context), ensure_ascii=False, default=str)[:12000]}\n\n"
        f"当前结构化执行单：\n{json.dumps(_creator_facing_draft(current), ensure_ascii=False)}\n\n"
        f"上次规划验收：\n{json.dumps(review or {}, ensure_ascii=False)}\n\n"
        f"上次叙事规划：\n{json.dumps(_creator_facing_narrative_plan(previous or {}), ensure_ascii=False)}"
    )


def _review_narrative_plan(
    current: dict[str, Any], requirements: str, narrative_plan: dict[str, Any]
) -> dict[str, Any]:
    prompt = (
        "你是拍摄执行叙事规划验收员。只审核规划，不改写规划，只输出合法 JSON object。\n"
        "逐一审核所有相邻 beat：是否有明确的事实、时间、空间或因果承接；是否用口播假装连接无关主体；"
        "是否出现无理由的主体回流、场地回流、章节重复开启；开头悬念是否有唯一且明确的 setup/payoff；"
        "结尾是否只收束已建立主线而没有重新介绍产品；用户要求和原稿未被推翻的事实是否完整保留。\n"
        f"coherence_score 必须严格评分。只有分数不低于{COHERENCE_PASS_SCORE}，且 critical_issues、transition_issues、"
        "subject_reentry_issues、missing_requirements 全部为空时，status 才能是 passed。\n"
        "输出字段固定为 status, coherence_score, storyline_summary, critical_issues, transition_issues, "
        "subject_reentry_issues, satisfied_requirements, missing_requirements, reason。\n\n"
        f"用户要求：{requirements}\n"
        f"原稿：{json.dumps(current, ensure_ascii=False)}\n"
        f"待验收叙事规划：{json.dumps(narrative_plan, ensure_ascii=False)}"
    )
    return call_creation_json(prompt, validation_contract=BACKWASH_REVIEW_CONTRACT)


def _generate_revised_draft(
    current: dict[str, Any],
    requirements: str,
    media_context: dict[str, Any],
    narrative_plan: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    prompt = _revision_prompt(current, requirements, media_context, narrative_plan)
    last_review: dict[str, Any] = {}
    candidate: dict[str, Any] = {}
    for _attempt in range(2):
        candidate = localize_shooting_execution_plan_values(
            call_creation_json(prompt, validation_contract=SHOOTING_PLAN_VALIDATION_CONTRACT)
        )
        last_review = _review_revision(current, candidate, requirements, narrative_plan)
        if last_review.get("status") == "passed":
            return candidate, last_review
        prompt = _revision_prompt(
            current,
            requirements,
            media_context,
            narrative_plan,
            review=last_review,
            previous=candidate,
        )
    return candidate, last_review


def _revision_prompt(
    current: dict[str, Any],
    requirements: str,
    media_context: dict[str, Any],
    narrative_plan: dict[str, Any],
    *,
    review: dict[str, Any] | None = None,
    previous: dict[str, Any] | None = None,
) -> str:
    prompt = (
        "你是 OpenClaw Media 的拍摄执行回洗导演。根据用户修改要求整份重写现有执行单，只输出合法 JSON object。\n"
        "必须保持现有顶层结构和每个列表项字段；把要求吸收到分镜、路线、必拍、分支、现场检查和发布包等相关章节。\n"
        "不得生成补充记录、修改记录、追加说明、证据附录正文或文末补丁。分镜保持可直接拍摄；除非用户明确要求删减或压缩，否则整体长度和原稿相当。\n"
        "保留未被修改要求推翻的原事实、产品名、合规边界、交付规格和账号边界；不确定的信息标为“待人工核实”。\n"
        "分镜、拍摄目标主线、路线图、必拍镜头、现场检查和发布包必须使用叙事规划的唯一顺序。\n"
        "每个产品或主体必须连续介绍完成，禁止无理由 A→B→A；只有规划中明确成对的“悬念设置/悬念回收”才能回收。\n"
        "每个相邻分镜必须有可见动作、空间、时间或因果承接；禁止用空泛口播把无关主体粘在一起。\n"
        "结尾剪辑只能收束主线，不得用回闪重新介绍已结束产品，也不得重新开启产品章节。\n"
        "证据附录只保留已有证据，不写给创作者看的解释。优先级只能写“必拍”“重要”或“可选”；"
        "来源状态只能写“已核验”“仅凭文字描述，未看过原片”或“待人工核实”。"
        "发布后首小时动作必须保留为创作者手动完成的具体动作，不得声称系统会自动执行或提醒。\n\n"
        f"用户修改要求：\n{requirements}\n\n"
        f"账号与创作上下文：\n{json.dumps(_creator_facing_media_context(media_context), ensure_ascii=False, default=str)[:12000]}\n\n"
        f"当前结构化执行单：\n{json.dumps(_creator_facing_draft(current), ensure_ascii=False)}\n\n"
        f"已通过验收的叙事规划（唯一顺序）：\n{json.dumps(_creator_facing_narrative_plan(narrative_plan), ensure_ascii=False)}\n\n"
        f"上次语义验收：\n{json.dumps(review or {}, ensure_ascii=False)}\n\n"
        f"上次候选稿：\n{json.dumps(_creator_facing_draft(previous or {}), ensure_ascii=False)}"
    )
    return prompt


def _narrative_strategy_code(value: Any) -> str:
    raw_value = str(value or "").strip()
    return NARRATIVE_STRATEGY_CODES.get(raw_value, raw_value)


def _narrative_role_code(value: Any) -> str:
    raw_value = str(value or "").strip()
    return NARRATIVE_ROLE_CODES.get(raw_value, raw_value)


def _creator_facing_draft(draft: dict[str, Any]) -> dict[str, Any]:
    return localize_shooting_execution_plan_values(draft)


def _creator_facing_narrative_plan(plan: dict[str, Any]) -> dict[str, Any]:
    creator_plan = dict(plan)
    raw_strategy = str(plan.get("strategy") or "").strip()
    creator_plan["strategy"] = NARRATIVE_STRATEGY_LABELS.get(raw_strategy, raw_strategy)
    beats: list[Any] = []
    for beat in plan.get("beats") or []:
        if not isinstance(beat, dict):
            beats.append(beat)
            continue
        creator_beat = dict(beat)
        raw_role = str(beat.get("narrative_role") or "").strip()
        creator_beat["narrative_role"] = NARRATIVE_ROLE_LABELS.get(raw_role, raw_role)
        beats.append(creator_beat)
    creator_plan["beats"] = beats
    return creator_plan


def _creator_facing_media_context(media_context: dict[str, Any]) -> dict[str, Any]:
    creator_context = dict(media_context)
    if "deconstruction_evidence" in creator_context:
        creator_context["deconstruction_evidence"] = creator_facing_deconstruction_evidence(
            creator_context["deconstruction_evidence"]
        )
    return creator_context


def _review_revision(
    current: dict[str, Any],
    candidate: dict[str, Any],
    requirements: str,
    narrative_plan: dict[str, Any],
) -> dict[str, Any]:
    prompt = (
        "你是拍摄执行回洗验收员。只根据用户要求、原稿和候选稿判断，不补写内容。只输出 JSON。\n"
        "逐条检查要求是否已被吸收到所有相关章节，是否保留未被推翻的事实与合规约束，是否仍是完整可拍摄执行单，"
        "是否出现补充记录/修改记录/文末补丁。逐一审核 storyboard 的每个相邻边界，并对照叙事规划检查 "
        "shooting_goal.mainline、route_map、must_shot_list、onsite_checklist、publishing_pack 的顺序是否一致。\n"
        "transition_issues 必须列出靠空泛口播掩盖的主题切换、缺少空间/时间/因果承接的相邻镜头和场地跳转。"
        "subject_reentry_issues 必须列出无明确 setup/payoff 的 A→B→A、结尾 montage 重新介绍产品、已结束章节再次开启。\n"
        f"coherence_score 必须严格评分。只有分数不低于{COHERENCE_PASS_SCORE}，且 critical_issues、transition_issues、"
        "subject_reentry_issues、missing_requirements 全部为空时，status 才能是 passed。\n"
        "输出字段固定为 status, coherence_score, storyline_summary, critical_issues, transition_issues, "
        "subject_reentry_issues, satisfied_requirements, missing_requirements, reason。\n\n"
        f"用户要求：{requirements}\n"
        f"原稿：{json.dumps(current, ensure_ascii=False)}\n"
        f"已通过的叙事规划：{json.dumps(narrative_plan, ensure_ascii=False)}\n"
        f"候选稿：{json.dumps(candidate, ensure_ascii=False)}"
    )
    return call_creation_json(prompt, validation_contract=BACKWASH_REVIEW_CONTRACT)


def _review_failure_summary(review: dict[str, Any]) -> str:
    issues: list[str] = []
    for key in ("critical_issues", "transition_issues", "subject_reentry_issues", "missing_requirements"):
        issues.extend(str(item) for item in review.get(key) or [] if str(item).strip())
    if not issues:
        issues.append(str(review.get("reason") or f"未达到{COHERENCE_PASS_SCORE}分连贯性门槛"))
    return "；".join(issues)


def _reviews_passed(*reviews: dict[str, Any]) -> bool:
    return all(review.get("status") == "passed" for review in reviews)


def _validate_practical_shape(
    current: dict[str, Any],
    revised: dict[str, Any],
    *,
    requirements: str = "",
) -> None:
    if _requires_structural_reduction(requirements):
        return
    for key in ("storyboard", "route_map", "must_shot_list", "onsite_checklist"):
        before = len(current.get(key) or [])
        after = len(revised.get(key) or [])
        minimum = max(1, int(before * 0.7))
        if after < minimum:
            raise RuntimeError(f"拍摄执行回洗后 {key} 过短：{after} < {minimum}")


def _requires_structural_reduction(requirements: str) -> bool:
    text = str(requirements or "").lower()
    reduction_markers = (
        "删除",
        "删掉",
        "删减",
        "去掉",
        "移除",
        "精简",
        "压缩",
        "缩短",
        "减少",
        "砍掉",
        "只保留",
        "delete",
        "remove",
        "shorten",
        "condense",
        "cut ",
    )
    return any(marker in text for marker in reduction_markers)


def _persist_backwash(
    tenant_id: str,
    run_id: str,
    run_dir: Path,
    request_payload: dict[str, Any],
    input_payload: dict[str, Any],
    draft: dict[str, Any],
    validation: dict[str, Any],
    doc_url: str,
    requirements: str,
    narrative_plan: dict[str, Any],
    narrative_plan_review: dict[str, Any],
    review: dict[str, Any],
) -> None:
    vault = MediaVault(tenant_id=tenant_id)
    vault.write_json_artifact(run_dir, "draft_output.json", draft, owner_type="CreationRun", owner_id=run_id, artifact_type="draft_output")
    vault.write_json_artifact(run_dir, "validation_report.json", validation, owner_type="CreationRun", owner_id=run_id, artifact_type="validation_report")
    vault.write_json_artifact(run_dir, "narrative_plan.json", narrative_plan, owner_type="CreationRun", owner_id=run_id, artifact_type="narrative_plan")
    vault.write_json_artifact(run_dir, "narrative_plan_review.json", narrative_plan_review, owner_type="CreationRun", owner_id=run_id, artifact_type="narrative_plan_review")
    vault.write_json_artifact(run_dir, "backwash_coherence_review.json", review, owner_type="CreationRun", owner_id=run_id, artifact_type="backwash_coherence_review")
    revised_input = dict(input_payload)
    history = list(revised_input.get("backwash_history") or [])
    history.append(
        {
            "created_at": utc_now_iso(),
            "target_doc_link": doc_url,
            "requirements": requirements,
            "narrative_plan": narrative_plan,
            "narrative_plan_review": narrative_plan_review,
            "semantic_review": review,
        }
    )
    revised_input["backwash_history"] = history
    vault.write_json_artifact(run_dir, "input.json", revised_input, owner_type="CreationRun", owner_id=run_id, artifact_type="input")
    revised_request = dict(request_payload)
    revised_request["doc_link"] = doc_url
    vault.write_json_artifact(run_dir, "request.json", revised_request, owner_type="CreationRun", owner_id=run_id, artifact_type="request")
